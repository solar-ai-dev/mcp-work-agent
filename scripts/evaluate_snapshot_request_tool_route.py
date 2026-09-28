"""Preregistered paired RU -> Tool Route components, never a whole-workflow score.

Reuse the actual snapshot composition, Product subgraphs, router and dispatch budget.
One isolated process per Case/arm; confirmation and Retrieval are stop boundaries.
"""

from __future__ import annotations

import argparse
import json
import multiprocessing
import time
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any
from unittest.mock import patch
from uuid import uuid4

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from scripts import evaluate_production_snapshot_workflow as shared
from scripts import production_snapshot_runtime as snapshot
from scripts.ru_observation import object_hash

from google_work_agent.adapters.langgraph.main.state import GraphState
from google_work_agent.application.use_cases.conversation.create_conversation import (
    CreateConversationCommand,
)
from google_work_agent.application.use_cases.resource.issue_selection_handle import (
    IssueSelectionHandleCommand,
)
from google_work_agent.application.use_cases.resource.resolve_selection_handle import (
    ResolveSelectionHandleQuery,
)
from google_work_agent.application.use_cases.run.account_provider_dispatch import (
    provider_dispatch_execution_scope,
)
from google_work_agent.application.use_cases.run.get_run_snapshot import GetExecutionContextQuery
from google_work_agent.application.use_cases.run.guard_run_budget import build_default_run_budget
from google_work_agent.application.use_cases.run.start_run import StartRunCommand
from google_work_agent.ports.system.contracts.workflow_execution import (
    WorkflowCorrelationContext,
    WorkflowStartRequest,
)
from google_work_agent.ports.system.settings_port import SettingsPatchV1

CASE_IDS = (
    "CASE-CORE-005",  # Selected READ / explicit no CREATE.
    "CASE-CORE-009",  # Mail + Task, answer only.
    "CASE-CORE-017",  # Task + Calendar -> one Draft.
    "CASE-CORE-019",  # Event + Draft with unresolved timing.
    "CASE-CORE-023",  # Mail + Task -> Event with explicit timing.
    "CASE-CORE-025",  # Mail + Task -> Event with relative timing.
    "CASE-CORE-035",  # Explicit CREATE / untrusted mail instruction prohibition.
    "CASE-CORE-059",  # Explicit SEND counterexample to answer-only overcorrection.
)
ARMS = ("production", shared.CANDIDATE)


def case_binding(case: Mapping[str, Any], default_reference_ms: int) -> dict[str, Any]:
    if case["case_id"] not in CASE_IDS or case["split"] != "CORE":
        raise ValueError("only the preregistered Core diagnostic set is accepted")
    if case["evaluation_gold"]["fault_profile"] is not None:
        raise ValueError("fault injection is outside this component gate")
    document = json.loads(shared.PROVIDER_SNAPSHOT.read_text(encoding="utf-8"))
    account = document["address_bindings"]["user@example.test"]
    selected = case.get("selected_resource_bindings", [])
    if any(
        item.get("account_email") != account or item.get("authority") != "PROVIDER_REREAD"
        for item in selected
    ):
        raise ValueError("selected identity and snapshot test-account authority differ")
    packs = document["resource_packs"]
    if any(name not in packs for name in case["resource_packs"]):
        raise ValueError("Case references a missing Provider snapshot pack")
    reference = (case.get("evaluation_context") or {}).get("run_reference_time")
    reference_ms = default_reference_ms
    if reference is not None:
        stamp = datetime.fromisoformat(reference)
        if stamp.utcoffset() is None:
            raise ValueError("Case reference time requires an explicit offset")
        reference_ms = int(stamp.timestamp() * 1000)
    return {
        "case_id": case["case_id"],
        "case_sha256": object_hash(case),
        "request_sha256": object_hash(case["canonical_user_prompt"]),
        "entry_mode": case["entry_mode"],
        "selected_bindings": deepcopy(selected),
        "resource_pack_sha256": {name: object_hash(packs[name]) for name in case["resource_packs"]},
        "account_id": account,
        "account_authority": "provider_snapshot.address_bindings.user@example.test",
        "case_reference_time": reference,
        "effective_reference_time_ms": reference_ms,
        "reference_time_source": "CASE" if reference else "PREREGISTERED_PAIR_START",
        "fault_profile": None,
    }


def build_plan(
    model_digest: str, *, trial_id: str | None = None, reference_time_ms: int | None = None
) -> dict[str, Any]:
    """Read-only; neither runtime bootstrap nor model discovery is performed."""
    base = shared.build_plan(model_digest, trial_id=trial_id, candidate=shared.CANDIDATE)
    for key in ("case_id", "case_sha256", "resource_scope", "candidate"):
        base.pop(key)
    reference_ms = int(time.time() * 1000) if reference_time_ms is None else reference_time_ms
    if not isinstance(reference_ms, int) or isinstance(reference_ms, bool) or reference_ms < 1:
        raise ValueError("a positive preregistered pair reference time is required")
    base.update(
        schema_version=1,
        kind="PAIRED_PRODUCTION_RU_TOOL_ROUTE_COMPONENTS",
        arms=list(ARMS),
        cases=[case_binding(snapshot.load_case(case_id), reference_ms) for case_id in CASE_IDS],
        preregistered_reference_time_ms=reference_ms,
        trials_per_case_arm=1,
        scope="ACTUAL_PRODUCT_SUBGRAPHS_NOT_MAIN_WORKFLOW_SUCCESS",
        stop_before=["Retrieval", "WorkAnalysis", "Planning", "Approval", "Execution"],
        component_orchestration="PRODUCTION_CALLBACKS_STOP_BEFORE_DURABLE_CONFIRMATION_COMMAND",
        provider_reads=0,
        semantic_grader="UNREVIEWED_RAW_PRESERVED_NO_AUTOMATIC_PASS",
    )
    base["runtime"]["joint_authority_temperature"] = {"production": None, shared.CANDIDATE: 0.0}
    base["dependency_sha256"][Path(__file__).relative_to(shared.PROJECT_ROOT).as_posix()] = (
        shared.file_hash(Path(__file__))
    )
    return base


def validate_plan(plan: Mapping[str, Any]) -> None:
    expected = build_plan(
        plan["model"]["digest"],
        trial_id=plan["trial_id"],
        reference_time_ms=plan["preregistered_reference_time_ms"],
    )
    if dict(plan) != expected:
        raise ValueError("paired preregistered input/code/runtime binding changed")


@contextmanager
def component_boundary(account_id: str) -> Iterator[None]:
    """Reject every Connector dispatch; account metadata comes only from the bound snapshot."""

    class NoDispatchBoundary(snapshot.SnapshotBoundary):
        @property
        def account_id(self) -> str:
            actual = case_binding(self.case, 1)["account_id"]
            if actual != account_id:
                raise snapshot.SnapshotSafetyError("registered account differs from fixture")
            return str(actual)

        def execute_read(self, *args: Any, **kwargs: Any) -> Any:
            return self.deny("component_connector_read", *args, **kwargs)

    def stop_confirmation(_workflow: Any, state: Any, *, semantic_owner_id: str) -> Any:
        raise ComponentConfirmationBoundary(state, semantic_owner_id)

    with (
        patch.object(snapshot, "SnapshotBoundary", NoDispatchBoundary),
        patch.object(
            shared.composition.LangGraphWorkflowRuntime, "_confirm_owner_inline", stop_confirmation
        ),
    ):
        yield


class ComponentConfirmationBoundary(RuntimeError):
    """No durable confirmation/resume claim is made by a pre-confirmation component gate."""

    def __init__(self, state: Mapping[str, Any], owner: str) -> None:
        super().__init__("component scope ends before durable confirmation command")
        self.observed_state = deepcopy(dict(state))
        self.semantic_owner = owner


def admit_request(
    container: Any, boundary: Any, case: Mapping[str, Any], binding: Mapping[str, Any]
) -> WorkflowStartRequest:
    """Use actual signed selection and StartRun, without scheduling the Main Graph."""
    conversation_id, command_id, session = str(uuid4()), str(uuid4()), object_hash(uuid4().hex)
    container.create_conversation_handler(
        CreateConversationCommand(
            str(uuid4()),
            object_hash(conversation_id),
            conversation_id,
            boundary.account_id,
            "Canonical component comparison",
            "1",
        )
    )
    selections = []
    for selected in case["selected_resource_bindings"]:
        handle = container.issue_selection_handle(
            IssueSelectionHandleCommand(
                session,
                boundary.account_id,
                "google_workspace",
                selected["resource_type"],
                selected["resource_id"],
                selected["parent_id"],
                None,
            )
        )
        selections.append(
            container.resolve_selection_handle(
                ResolveSelectionHandleQuery(
                    handle,
                    session,
                    boundary.account_id,
                    expected_connector_id="google_workspace",
                    expected_resource_type=selected["resource_type"],
                    expected_resource_id=selected["resource_id"],
                    expected_parent_resource_id=selected["parent_id"],
                    require_parent_match=True,
                )
            )
        )
    admitted = container.start_run_handler(
        StartRunCommand(
            command_id,
            object_hash({"command": command_id, "case": case["canonical_user_prompt"]}),
            conversation_id,
            case["canonical_user_prompt"],
            case["entry_mode"],
            "LOCAL_GPU",
            "1",
            tuple(selections),
        )
    )
    if not admitted.applied:
        raise RuntimeError(f"StartRun rejected:{admitted.result_code}")
    context = container.get_execution_context_handler(GetExecutionContextQuery(admitted.run_id))
    if context is None:
        raise RuntimeError("admitted execution context is missing")
    return WorkflowStartRequest(
        run_id=admitted.run_id,
        conversation_id=conversation_id,
        workflow_key=admitted.workflow_key,
        entry_mode=case["entry_mode"],
        requested_mode="LOCAL_GPU",
        request_text=case["canonical_user_prompt"],
        selected_resource_ids=tuple(ref.resource_id for ref in context.selected_resources),
        selected_resources=context.selected_resources,
        correlation=WorkflowCorrelationContext(command_id, command_id, "1"),
        run_budget=build_default_run_budget(started_at_ms=binding["effective_reference_time_ms"]),
    )


def compile_components(workflow: Any) -> Any:
    """Retain actual Product transitions/merge/confirmation; trim only outer execution scope."""
    wrapper = StateGraph(GraphState)
    wrapper.add_node("request_understanding", workflow._request_subgraph)
    wrapper.add_node("tool_route", workflow._tool_route_subgraph)
    wrapper.add_edge(START, "request_understanding")
    wrapper.add_conditional_edges(
        "request_understanding",
        lambda state: (
            "tool_route"
            if (
                state.get("request_intent") is not None
                and state.get("user_interrupt") is None
                and state.get("__target__") == "tool_route"
            )
            else "end"
        ),
        {"tool_route": "tool_route", "end": END},
    )
    wrapper.add_edge("tool_route", END)
    return wrapper.compile(checkpointer=InMemorySaver())


def run_arm(plan: dict[str, Any], binding: dict[str, Any], arm: str, output: Path) -> None:
    observation = shared.TrialObservation(output)
    candidate_events: list[dict[str, object]] = []
    report: dict[str, Any] = {
        "plan_sha256": object_hash(plan),
        "case_binding": binding,
        "arm": arm,
        "state": "STARTING",
        "semantic_verdict": "UNREVIEWED",
        "rerun_to_pass": 0,
        "scope": plan["scope"],
        "candidate_events": candidate_events,
    }
    try:
        validate_plan(plan)
        if arm not in ARMS or binding not in plan["cases"]:
            raise ValueError("unregistered Case/arm")
        with (
            observation.wire_observer(),
            shared.candidate_scope(
                None if arm == "production" else arm, observation, candidate_events
            ) as decorate,
            component_boundary(binding["account_id"]),
            snapshot.snapshot_production_runtime(
                output / "runtime",
                case_id=binding["case_id"],
                allow_loopback_model=True,
                llm_provider_decorator=decorate,
                sampling_seed=shared.SEED,
            ) as (container, boundary),
        ):
            report["settings"] = asdict(
                container.settings_port.update_settings(
                    SettingsPatchV1(
                        1, preferred_llm_mode="LOCAL_GPU", preferred_local_model_id=shared.MODEL_ID
                    ),
                    operation_ref=plan["trial_id"],
                )
            )
            installed = [
                item
                for item in shared.OllamaHTTPClient().list_installed_models()
                if item.model_id == shared.MODEL_ID
            ]
            if len(installed) != 1 or installed[0].digest != plan["model"]["digest"]:
                raise RuntimeError("model digest differs from preregistration")
            case = snapshot.load_case(binding["case_id"])
            request = admit_request(container, boundary, case, binding)
            graph = compile_components(container.workflow_runtime)
            state = container.workflow_runtime._initial_state(request)
            report.update(run_id=request.run_id, request=asdict(request), state="RUNNING")
            shared.write_json(output / "raw.json", report)
            started = time.monotonic()
            reference = binding["effective_reference_time_ms"]
            config = {"configurable": {"thread_id": request.run_id}}
            try:
                with provider_dispatch_execution_scope(
                    run_id=request.run_id,
                    now_ms=lambda: reference + int((time.monotonic() - started) * 1000),
                ):
                    for current in graph.stream(state, config=config, stream_mode="values"):
                        report["last_state"] = current
                        report["metrics"] = observation.metrics()
                        shared.write_json(output / "raw.json", report)
                ending = graph.get_state(config)
                report.update(
                    last_state=ending.values,
                    state="COMPONENT_INTERRUPT" if ending.next else "COMPONENT_RETURNED",
                    pending_nodes=list(ending.next),
                )
            finally:
                report.update(
                    boundary_events=deepcopy(boundary.events),
                    provider_reads=len(boundary.read_results),
                    provider_writes=len(boundary.provider.write_calls),
                    provider_read_attempts=sum(
                        item.get("boundary") == "component_connector_read"
                        for item in boundary.events
                    ),
                    provider_write_attempts=sum(
                        item.get("boundary") == "provider_write_dispatch"
                        for item in boundary.events
                    ),
                )
    except ComponentConfirmationBoundary as stop:
        report.update(
            state="COMPONENT_CONFIRMATION_BOUNDARY",
            last_state=stop.observed_state,
            semantic_owner=stop.semantic_owner,
            durable_confirmation_executed=False,
        )
    except Exception as error:
        report.update(
            state_before_error=report["state"],
            state="EXPERIMENT_BOUND_REACHED" if observation.bound_reason else "COMPONENT_ERROR",
            bound_reason=observation.bound_reason,
            error_type=type(error).__name__,
            error=str(error),
        )
    finally:
        report.update(
            metrics=observation.metrics(),
            wall_latency_ms=int((time.monotonic() - observation.started) * 1000),
        )
        shared.write_json(output / "raw.json", report)


def execute_plan(plan_path: Path, output: Path) -> int:
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    validate_plan(plan)
    output = output.resolve()
    root = shared.RESULTS_ROOT.resolve()
    if (
        not output.is_relative_to(root)
        or output == root
        or (output.exists() and any(output.iterdir()))
    ):
        raise ValueError("a new dedicated evaluation/results directory is required")
    claims = root / ".snapshot-component-trials"
    claims.mkdir(parents=True, exist_ok=True)
    with (claims / f"{plan['trial_id']}.json").open("x", encoding="utf-8") as stream:
        json.dump({"plan_sha256": object_hash(plan), "output": str(output)}, stream)
    shared.write_json(output / "plan.json", plan)
    summary = []
    for binding in plan["cases"]:
        for arm in plan["arms"]:
            validate_plan(plan)
            arm_output = output / binding["case_id"] / arm
            process = multiprocessing.get_context("spawn").Process(
                target=run_arm, args=(plan, binding, arm, arm_output)
            )
            process.start()
            process.join(shared.WALL_SECONDS)
            path = arm_output / "raw.json"
            if process.is_alive():
                process.terminate()
                process.join(10)
                report = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
                report.update(
                    state_before_timeout=report.get("state"),
                    state="EXPERIMENT_BOUND_REACHED",
                    bound_reason="EXTERNAL_WALL_TIMEOUT",
                    semantic_verdict="UNREVIEWED",
                )
                shared.write_json(path, report)
            if not path.exists():
                shared.write_json(path, {"state": "HARNESS_ERROR", "exit_code": process.exitcode})
            record = json.loads(path.read_text(encoding="utf-8"))
            summary.append(
                {
                    "case_id": binding["case_id"],
                    "arm": arm,
                    "state": record["state"],
                    "metrics": record.get("metrics"),
                    "raw_sha256": shared.file_hash(path),
                    "semantic_verdict": "UNREVIEWED",
                }
            )
            shared.write_json(output / "summary.json", summary)
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    raise SystemExit(execute_plan(arguments.plan, arguments.output))


if __name__ == "__main__":
    main()
