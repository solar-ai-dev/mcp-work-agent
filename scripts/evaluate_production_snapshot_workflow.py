"""One preregistered actual Main Graph trial against local Provider snapshots.

Outputs are local-only observations, not automatic semantic PASS judgements.
Run with ``python -m scripts.evaluate_production_snapshot_workflow --plan ... --output ...``.
The parent enforces the wall bound outside the unchanged Product process budget.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import multiprocessing
import platform
import subprocess
import sys
import threading
import time
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any, Final
from unittest.mock import patch
from uuid import UUID, uuid4

from scripts.production_snapshot_runtime import (
    DATASET,
    PROJECT_ROOT,
    load_case,
    snapshot_production_runtime,
)
from scripts.ru_observation import metrics, object_hash
from scripts.serve_canonical_v8_product import PROVIDER_SNAPSHOT, _case_resources

from google_work_agent.adapters.llm.ollama import transport as ollama_transport
from google_work_agent.adapters.llm.ollama.transport import OllamaHTTPClient
from google_work_agent.api import composition
from google_work_agent.application.agents.retrieval.resolve_route_container_scopes import (
    resolve_route_container_scopes,
)
from google_work_agent.application.agents.tool_routing.contracts.tool_route_plan import (
    InputToolRouteV1,
)
from google_work_agent.application.prompt_runtime.prompt_registry import (
    default_prompt_manifest_path,
)
from google_work_agent.application.use_cases.conversation.create_conversation import (
    CreateConversationCommand,
)
from google_work_agent.application.use_cases.resource.issue_selection_handle import (
    IssueSelectionHandleCommand,
)
from google_work_agent.application.use_cases.resource.require_resource_selection import (
    RequireResourceSelectionHandler,
)
from google_work_agent.application.use_cases.resource.resolve_selection_handle import (
    ResolveSelectionHandleQuery,
)
from google_work_agent.application.use_cases.run.get_run_snapshot import (
    GetExecutionContextQuery,
    GetRunSnapshotQuery,
)
from google_work_agent.application.use_cases.run.schedule_run_execution import (
    ScheduleRunExecutionCommand,
)
from google_work_agent.application.use_cases.run.start_run import StartRunCommand
from google_work_agent.ports.llm.structured_inference_contracts import (
    LLMErrorCode,
    LLMInvocationError,
)
from google_work_agent.ports.system.settings_port import SettingsPatchV1

RESULTS_ROOT = PROJECT_ROOT / "evaluation/results"
CASE_ID = "CASE-CORE-005"
MODEL_ID: Final = "qwen3.5:9b"
SEED = 20260923
CALL_CAP = 20
WALL_SECONDS = 600
CANDIDATE = "goal-output-v4-connected"
STOP_STATUSES = frozenset(
    {
        "COMPLETED",
        "FAILED",
        "BLOCKED",
        "CANCELLED",
        "WAITING_CONFIRMATION",
        "WAITING_APPROVAL",
        "REAUTH_REQUIRED",
        "RECOVERY_REQUIRED",
    }
)


class SnapshotProvisioningError(RuntimeError):
    """The preregistered local account/selection is not ready for this trial."""


def selected_task_scope(case: Mapping[str, Any], resources: list[dict[str, Any]]) -> dict[str, Any]:
    """Bind only the selected Task's real snapshot parent, not other pack resources."""
    selections = case.get("selected_resource_bindings", [])
    if case.get("case_id") != CASE_ID or len(selections) != 1:
        raise SnapshotProvisioningError("this fixed trial requires one selected CORE-005 Task")
    selected = selections[0]
    if (
        selected.get("resource_type") != "task"
        or selected.get("authority") != "PROVIDER_REREAD"
        or not selected.get("account_email")
        or not selected.get("parent_id")
    ):
        raise SnapshotProvisioningError("selected Task account/parent authority is missing")
    tasks = [
        item
        for item in resources
        if item["resource_type"] == "task"
        and item["resource_id"] == selected["resource_id"]
        and item.get("parent_id") == selected["parent_id"]
    ]
    parents = [
        item
        for item in resources
        if item["resource_type"] == "task_list" and item["resource_id"] == selected["parent_id"]
    ]
    if len(tasks) != 1 or len(parents) != 1 or not parents[0].get("payload"):
        raise SnapshotProvisioningError("selected Task/parent snapshot is missing or ambiguous")
    return {
        "google_resource_account_id": selected["account_email"],
        "selected_tasklist_ids": [selected["parent_id"]],
        "selected_calendar_ids": None,
        "selected_resource_binding": deepcopy(selected),
        "selected_task_snapshot_sha256": object_hash(tasks[0]),
        "selected_container_snapshot_sha256": object_hash(parents[0]),
    }


def _selection_guard(container: Any) -> RequireResourceSelectionHandler:
    return RequireResourceSelectionHandler(
        settings=container.settings_port.get_settings,
        current_account_id=lambda connector_id: (
            container.current_account_id_provider() if connector_id == "google_workspace" else None
        ),
    )


def verify_prepared_scope(container: Any, scope: Mapping[str, Any]) -> None:
    """Check the same account-bound allowlist consumer used by Product READs."""
    settings = container.settings_port.get_settings()
    if (
        container.current_account_id_provider() != scope["google_resource_account_id"]
        or settings.google_resource_account_id != scope["google_resource_account_id"]
        or settings.selected_tasklist_ids != tuple(scope["selected_tasklist_ids"])
        or settings.selected_calendar_ids is not None
    ):
        raise SnapshotProvisioningError("prepared scope differs from registered account/selection")
    selected = scope["selected_resource_binding"]
    _selection_guard(container)(
        "google_workspace",
        "tasks_get_task",
        {"task_list_id": selected["parent_id"], "task_id": selected["resource_id"]},
    )


def preflight_admitted_selection(
    container: Any, boundary: Any, run_id: str, scope: Mapping[str, Any]
) -> dict[str, Any]:
    """Resolve persisted selection scope before scheduling; never inject a semantic route."""
    verify_prepared_scope(container, scope)
    context = container.get_execution_context_handler(GetExecutionContextQuery(run_id))
    if context is None or len(context.selected_resources) != 1:
        raise SnapshotProvisioningError("admitted selected resource projection is missing")
    selected = context.selected_resources[0]
    expected = scope["selected_resource_binding"]
    if (
        selected.connector_id != "google_workspace"
        or selected.resource_type != expected["resource_type"]
        or selected.resource_id != expected["resource_id"]
        or selected.parent_resource_id != expected["parent_id"]
    ):
        raise SnapshotProvisioningError("admitted selected identity differs from snapshot binding")
    binding = boundary.registry.bind_required("google_workspace", "tasks_get_task", "READ")
    # This isolated capability probe is not a ToolRoutePlan or a WorkUnit decision.
    route: InputToolRouteV1 = {
        "route_id": selected.resource_ref_id,
        "resource_type": "TASK",
        "connector_id": binding.connector_id,
        "allowed_read_tool_ids": [binding.tool_id],
        "required": True,
        "reason_codes": ["RESOURCE_SELECTED"],
        "work_unit_ids": [],
    }
    guard = _selection_guard(container)
    containers = resolve_route_container_scopes(
        frozen_routes=[route],
        selected_resources=context.selected_resources,
        authorized_tasklist_ids=guard.authorized_targets("tasks"),
        authorized_calendar_ids=guard.authorized_targets("calendar"),
    )
    return {
        "status": "READY",
        "kind": "ENVIRONMENT_SELECTION_PROBE_NOT_SEMANTIC_ROUTE",
        "selected_resources": [asdict(selected)],
        "validated_container_refs": containers,
        "provider_dispatches": 0,
    }


def file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _head() -> str:
    return subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=PROJECT_ROOT, text=True
    ).strip()


def _tree_hash(path: Path) -> str:
    files = sorted(
        p
        for p in path.rglob("*")
        if p.is_file()
        and p.suffix in {".py", ".json", ".md", ".sql"}
        and "__pycache__" not in p.parts
    )
    return object_hash({str(p.relative_to(PROJECT_ROOT).as_posix()): file_hash(p) for p in files})


def build_plan(
    model_digest: str, *, trial_id: str | None = None, candidate: str | None = None
) -> dict[str, Any]:
    """Read-only preregistration helper: no catalog, Provider, or model call."""
    normalized_digest = model_digest.removeprefix("sha256:")
    if len(normalized_digest) != 64 or any(c not in "0123456789abcdef" for c in normalized_digest):
        raise ValueError("actual model SHA-256 digest required")
    identifier = str(UUID(trial_id)) if trial_id is not None else str(uuid4())
    if candidate not in {None, CANDIDATE}:
        raise ValueError("unregistered connected candidate")
    case = load_case(CASE_ID)
    manifest = default_prompt_manifest_path()
    dependencies: tuple[Path, ...] = (
        Path(__file__),
        PROJECT_ROOT / "scripts/production_snapshot_runtime.py",
        PROJECT_ROOT / "scripts/ru_observation.py",
        PROJECT_ROOT / "scripts/serve_canonical_v8_product.py",
        PROJECT_ROOT / "evaluation/harness/stateful_provider.py",
        PROJECT_ROOT / "evaluation/harness/gmail_query.py",
        manifest,
        manifest.parent / "prompt_runtime_input_contract_v1.json",
    )
    if candidate is not None:
        from evaluation.request_semantic_authority_candidate import GOAL_OUTPUT_MODALITY_PROMPT_PATH

        dependencies += (
            PROJECT_ROOT / "scripts/production_goal_output_candidate.py",
            PROJECT_ROOT / "evaluation/request_semantic_authority_candidate.py",
            GOAL_OUTPUT_MODALITY_PROMPT_PATH,
        )
    return {
        "schema_version": 3,
        "kind": "PRODUCTION_SNAPSHOT_SINGLE_TRIAL",
        "candidate": candidate,
        "trial_id": identifier,
        "case_id": CASE_ID,
        "trials": 1,
        "head_sha": _head(),
        "dataset_sha256": file_hash(DATASET),
        "case_sha256": object_hash(case),
        "snapshot_sha256": file_hash(PROVIDER_SNAPSHOT),
        "resource_scope": selected_task_scope(case, _case_resources(case)),
        "product_tree_sha256": _tree_hash(PROJECT_ROOT / "src"),
        "prompt_tree_sha256": _tree_hash(manifest.parent),
        "tool_registry_sha256": composition.load_development_tool_registry().entries_hash,
        "dependency_sha256": {
            p.resolve().relative_to(PROJECT_ROOT).as_posix(): file_hash(p) for p in dependencies
        },
        "python": {
            "version": platform.python_version(),
            "executable_sha256": file_hash(Path(sys.executable)),
        },
        "model": {"id": MODEL_ID, "digest": model_digest},
        "runtime": {
            "requested_mode": "LOCAL_GPU",
            "seed": SEED,
            "temperature_override": None,
            "joint_authority_temperature": 0.0 if candidate else None,
            "reference_time": None,
            "fault_profile": None,
        },
        "bounds": {
            "actual_llm_calls": CALL_CAP,
            "provider_dispatch_attempts": CALL_CAP,
            "wall_seconds": WALL_SECONDS,
        },
        "approval_resumes": 0,
        "provider_writes": 0,
    }


def validate_plan(plan: Mapping[str, Any]) -> None:
    expected = build_plan(
        plan["model"]["digest"], trial_id=plan["trial_id"], candidate=plan.get("candidate")
    )
    if dict(plan) != expected:
        differing = sorted(
            key for key in set(plan) | set(expected) if plan.get(key) != expected.get(key)
        )
        raise ValueError(f"preregistered binding mismatch: {','.join(differing)}")


def _jsonable(value: Any) -> Any:
    if is_dataclass(value) and not isinstance(value, type):
        return asdict(value)
    raise TypeError(f"unsupported observation type:{type(value).__name__}")


def write_json(path: Path, value: Any) -> None:
    """Publish whole observations atomically; retain the complete temp on failure."""
    payload = json.dumps(value, ensure_ascii=False, indent=2, default=_jsonable)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    with temporary.open("x", encoding="utf-8") as stream:
        stream.write(payload)
    # Windows readers may temporarily deny delete-sharing on the destination.
    # Retry only publishing the same completed bytes, never inference or capture.
    delays = (0.01, 0.02, 0.04, 0.08, 0.1, 0.1, 0.1)
    for attempt in range(len(delays) + 1):
        try:
            temporary.replace(path)
            return
        except OSError as error:
            if getattr(error, "winerror", None) not in {5, 32, 33} or attempt == len(delays):
                raise
            time.sleep(delays[attempt])


class TrialObservation:
    def __init__(self, output: Path) -> None:
        self.output = output
        self.started = time.monotonic()
        self.lock = threading.RLock()
        self.local = threading.local()
        self.calls: list[dict[str, Any]] = []
        self.bound_reason: str | None = None

    def _save(self) -> None:
        write_json(
            self.output / "calls.json",
            {
                "calls": self.calls,
                "metrics": self.metrics(),
                "bound_reason": self.bound_reason,
            },
        )

    def metrics(self) -> dict[str, Any]:
        dispatched = [call for call in self.calls if call.get("wire_request_count", 0)]
        return {
            **metrics(dispatched),
            "provider_dispatch_attempts": len(self.calls),
            "actual_wire_calls": sum(call.get("wire_request_count", 0) for call in self.calls),
        }

    def invoke(self, delegate: Any, operation: str, kwargs: dict[str, Any]) -> Any:
        with self.lock:
            if self.bound_reason is None:
                if time.monotonic() - self.started >= WALL_SECONDS:
                    self.bound_reason = "WALL_TIMEOUT"
                elif len(self.calls) >= CALL_CAP:
                    self.bound_reason = "PROVIDER_DISPATCH_ATTEMPT_CAP"
            if self.bound_reason is not None:
                self._save()
                raise LLMInvocationError(
                    LLMErrorCode.LLM_CALL_BUDGET_EXHAUSTED,
                    f"EXPERIMENT_BOUND_REACHED:{self.bound_reason}",
                )
            if delegate.provider_name != "ollama" or str(delegate.runtime) != "LOCAL_GPU":
                raise RuntimeError("non-local model dispatch forbidden")
            if delegate.model_id != MODEL_ID:
                raise RuntimeError("registered model differs from runtime selection")
            policy = kwargs["runtime_policy"]
            if policy.sampling_seed != SEED:
                raise RuntimeError("registered seed differs from actual runtime policy")
            ref = kwargs["prompt_ref"]
            event: dict[str, Any] = {
                "call_index": len(self.calls) + 1,
                "operation": operation,
                "prompt_id": ref.prompt_id,
                "prompt_ref": asdict(ref),
                "input": deepcopy(kwargs["prompt_input"]),
                "input_sha256": object_hash(kwargs["prompt_input"]),
                "runtime_policy": asdict(policy),
                "temperature": policy.sampling_temperature,
                "seed": policy.sampling_seed,
                "model": delegate.model_id,
                "state": "DISPATCH_STARTED",
                "wire_request_count": 0,
            }
            if "output_schema" in kwargs:
                event["output_schema"] = deepcopy(dict(kwargs["output_schema"].json_schema))
            if "tools" in kwargs:
                event["tools"] = [asdict(tool) for tool in kwargs["tools"]]
            self.calls.append(event)
            self.local.event = event
            self._save()
        started = time.monotonic()
        try:
            result = getattr(delegate, operation)(**kwargs)
            with self.lock:
                event.update(
                    state="RETURNED",
                    content=deepcopy(getattr(result, "content", None)),
                    result=_jsonable(result),
                    input_tokens=result.input_tokens,
                    output_tokens=result.output_tokens,
                    latency_ms=result.latency_ms,
                )
            return result
        except Exception as error:
            with self.lock:
                event.update(state="ERROR", error_type=type(error).__name__, error=str(error)[:500])
            raise
        finally:
            with self.lock:
                event["wall_latency_ms"] = int((time.monotonic() - started) * 1000)
                self._save()
            self.local.event = None

    def decorate(self, delegate: Any) -> Any:
        owner = self

        class ObservedProvider:
            provider_name = delegate.provider_name
            runtime = delegate.runtime

            def invoke_structured(self, **kwargs: Any) -> Any:
                return owner.invoke(delegate, "invoke_structured", kwargs)

            def invoke_tool_call(self, **kwargs: Any) -> Any:
                return owner.invoke(delegate, "invoke_tool_call", kwargs)

        return ObservedProvider()

    @contextmanager
    def wire_observer(self) -> Iterator[None]:
        original = ollama_transport._post_json

        def dispatch(**kwargs: Any) -> Any:
            event = getattr(self.local, "event", None)
            if event is not None:
                payload = kwargs["payload"]
                with self.lock:
                    if sum(call["wire_request_count"] for call in self.calls) >= CALL_CAP:
                        self.bound_reason = "ACTUAL_WIRE_CALL_CAP"
                        self._save()
                        raise LLMInvocationError(
                            LLMErrorCode.LLM_CALL_BUDGET_EXHAUSTED,
                            "EXPERIMENT_BOUND_REACHED:ACTUAL_WIRE_CALL_CAP",
                        )
                    event["wire_request_count"] += 1
                    event.update(
                        wire_path=kwargs["path"],
                        wire_options=deepcopy(payload.get("options")),
                        wire_think=payload.get("think"),
                        wire_sha256=object_hash(payload),
                    )
                    self._save()
            return original(**kwargs)

        with patch.object(ollama_transport, "_post_json", dispatch):
            yield


@contextmanager
def drain_before_guard_release(
    container: Any, *, on_drained: Callable[[], None] | None = None
) -> Iterator[None]:
    """Keep process-global isolation until the actual Product worker is idle.

    Only the external parent deadline may end this wait; it terminates the
    entire isolated child. Product's bounded shutdown alone is insufficient.
    """
    executor = container.schedule_run_execution._workflow_execution
    try:
        yield
    finally:
        executor.begin_shutdown()
        while not executor.await_drained(100):
            pass
        if on_drained is not None:
            on_drained()


@contextmanager
def candidate_scope(
    candidate: str | None, observation: TrialObservation, events: list[dict[str, object]]
) -> Iterator[Callable[[Any], Any]]:
    if candidate is None:
        yield observation.decorate
        return
    if candidate != CANDIDATE:
        raise ValueError("unregistered connected candidate")
    from scripts.production_goal_output_candidate import (
        decorate_goal_output_provider,
        goal_output_node_candidate,
    )

    with goal_output_node_candidate(
        tool_catalog=composition.load_development_tool_registry(),
        model_id=MODEL_ID,
        sampling_seed=SEED,
        observations=events,
    ):
        yield lambda provider: observation.decorate(decorate_goal_output_provider(provider))


def capture_drained_run(container: Any, report: dict[str, Any]) -> None:
    """Observe terminalization while the isolated runtime and its guard are still alive."""
    run_id = report.get("run_id")
    if run_id is None:
        return
    snapshot = container.get_run_snapshot_handler(GetRunSnapshotQuery(run_id))
    report["drained_snapshot"] = None if snapshot is None else asdict(snapshot)
    with container.read_unit_of_work_factory() as uow:
        run = uow.runs.get(run_id)
        report["drained_persisted_run"] = None if run is None else asdict(run)


def start_case(
    container: Any,
    boundary: Any,
    case: Mapping[str, Any],
    *,
    scope: Mapping[str, Any],
    report: dict[str, Any],
) -> Any:
    conversation_id, session_digest = str(uuid4()), hashlib.sha256(uuid4().bytes).hexdigest()
    container.create_conversation_handler(
        CreateConversationCommand(
            str(uuid4()),
            object_hash({"conversation_id": conversation_id}),
            conversation_id,
            boundary.account_id,
            "Canonical snapshot evaluation",
            "1",
        )
    )
    selections = []
    for selected in case["selected_resource_bindings"]:
        handle = container.issue_selection_handle(
            IssueSelectionHandleCommand(
                session_digest,
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
                    session_digest,
                    boundary.account_id,
                    expected_connector_id="google_workspace",
                    expected_resource_type=selected["resource_type"],
                    expected_resource_id=selected["resource_id"],
                    expected_parent_resource_id=selected["parent_id"],
                    require_parent_match=True,
                )
            )
        )
    command_id = str(uuid4())
    result = container.start_run_handler(
        StartRunCommand(
            command_id,
            object_hash({"command_id": command_id, "request": case["canonical_user_prompt"]}),
            conversation_id,
            case["canonical_user_prompt"],
            case["entry_mode"],
            "LOCAL_GPU",
            "1",
            tuple(selections),
        )
    )
    if not result.applied:
        raise RuntimeError(f"StartRun rejected:{result.result_code}")
    report.update(run_id=result.run_id, start_result=asdict(result), state="ADMISSION_PREPARED")
    report["selection_preflight"] = preflight_admitted_selection(
        container, boundary, result.run_id, scope
    )
    accepted = container.schedule_run_execution(ScheduleRunExecutionCommand(result.handoff_id))
    if not accepted.accepted:
        raise RuntimeError("durable workflow admission rejected")
    return result


def run_trial(plan: dict[str, Any], output: Path) -> None:
    """Child entry; callers must validate/claim the preregistered trial first."""
    observation = TrialObservation(output)
    candidate_events: list[dict[str, object]] = []
    report: dict[str, Any] = {
        "schema_version": 1,
        "plan": plan,
        "execution_mode": "PRODUCTION_GRAPH_SNAPSHOT_PROVIDER",
        "semantic_verdict": "UNREVIEWED",
        "state": "STARTING",
        "run_id": None,
        "rerun_to_pass": 0,
        "provider_write_count": None,
        "approval_resume_count": 0,
        "candidate_events": candidate_events,
    }
    try:
        validate_plan(plan)
        with (
            observation.wire_observer(),
            candidate_scope(plan.get("candidate"), observation, candidate_events) as decorate,
            snapshot_production_runtime(
                output / "runtime",
                case_id=CASE_ID,
                allow_loopback_model=True,
                sampling_seed=SEED,
                llm_provider_decorator=decorate,
            ) as (container, boundary),
            drain_before_guard_release(
                container, on_drained=lambda: capture_drained_run(container, report)
            ),
        ):
            case = load_case(CASE_ID)
            scope = selected_task_scope(case, boundary.resources)
            if (
                scope != plan["resource_scope"]
                or boundary.account_id != scope["google_resource_account_id"]
            ):
                raise SnapshotProvisioningError("runtime snapshot scope differs from registration")
            report["settings_before"] = asdict(container.settings_port.get_settings())
            settings = container.settings_port.update_settings(
                SettingsPatchV1(
                    1,
                    preferred_local_model_id=MODEL_ID,
                    preferred_llm_mode="LOCAL_GPU",
                    selected_tasklist_ids=tuple(scope["selected_tasklist_ids"]),
                    google_resource_account_id=scope["google_resource_account_id"],
                ),
                operation_ref=plan["trial_id"],
            )
            report["settings"] = asdict(settings)
            verify_prepared_scope(container, scope)
            models = OllamaHTTPClient().list_installed_models()
            observed = [model for model in models if model.model_id == MODEL_ID]
            if len(observed) != 1 or observed[0].digest != plan["model"]["digest"]:
                raise RuntimeError("installed model digest differs from preregistration")
            result = start_case(container, boundary, case, scope=scope, report=report)
            report.update(run_id=result.run_id, start_result=asdict(result), state="RUNNING")
            write_json(output / "raw.json", report)
            while True:
                snapshot = container.get_run_snapshot_handler(GetRunSnapshotQuery(result.run_id))
                if snapshot is not None:
                    report["snapshot"] = asdict(snapshot)
                    report["answer_messages"] = [
                        asdict(message)
                        for message in snapshot.messages
                        if message.role == "ASSISTANT" and message.run_id == result.run_id
                    ]
                report.update(
                    read_results=deepcopy(boundary.read_results),
                    boundary_events=deepcopy(boundary.events),
                    metrics=observation.metrics(),
                    provider_write_count=len(boundary.provider.write_calls),
                    provider_write_attempts=sum(
                        event.get("boundary") == "provider_write_dispatch"
                        for event in boundary.events
                    ),
                )
                write_json(output / "raw.json", report)
                if observation.bound_reason is not None:
                    report.update(
                        state="EXPERIMENT_BOUND_REACHED", bound_reason=observation.bound_reason
                    )
                    break
                if time.monotonic() - observation.started >= WALL_SECONDS:
                    observation.bound_reason = "WALL_TIMEOUT"
                    report.update(state="EXPERIMENT_BOUND_REACHED", bound_reason="WALL_TIMEOUT")
                    break
                if snapshot is not None and snapshot.status in STOP_STATUSES:
                    report["state"] = (
                        "COMPLETED_OBSERVATION"
                        if snapshot.status == "COMPLETED"
                        else "PRODUCT_STOP"
                    )
                    break
                time.sleep(0.1)
            with container.read_unit_of_work_factory() as uow:
                report["evidence"] = [
                    asdict(item) for item in uow.evidence.list_for_run(result.run_id)
                ]
                run = uow.runs.get(result.run_id)
                report["persisted_run"] = None if run is None else asdict(run)
            report.update(
                read_results=deepcopy(boundary.read_results),
                boundary_events=deepcopy(boundary.events),
            )
            write_json(output / "raw.json", report)
    except SnapshotProvisioningError as error:
        report.update(
            state_before_environment_error=report["state"],
            state="ENV_NOT_PROVISIONED",
            error_type=type(error).__name__,
            error=str(error),
        )
    except Exception as error:
        report.update(
            state_before_harness_error=report["state"],
            state="EXPERIMENT_BOUND_REACHED" if observation.bound_reason else "HARNESS_ERROR",
            bound_reason=observation.bound_reason,
            error_type=type(error).__name__,
            error=str(error)[:1000],
        )
    finally:
        report.update(
            metrics=observation.metrics(),
            wall_latency_ms=int((time.monotonic() - observation.started) * 1000),
        )
        write_json(output / "raw.json", report)


def execute_plan(plan_path: Path, output: Path) -> int:
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    validate_plan(plan)
    output = output.resolve()
    if not output.is_relative_to(RESULTS_ROOT.resolve()) or output == RESULTS_ROOT.resolve():
        raise ValueError("local results directory required")
    if output.exists() and any(output.iterdir()):
        raise ValueError("result directory must be empty")
    claims = RESULTS_ROOT / ".snapshot-trials"
    claims.mkdir(parents=True, exist_ok=True)
    with (claims / f"{plan['trial_id']}.json").open("x", encoding="utf-8") as stream:
        json.dump({"plan_sha256": object_hash(plan), "output": str(output)}, stream)
    write_json(output / "plan.json", plan)
    context = multiprocessing.get_context("spawn")
    process = context.Process(target=run_trial, args=(plan, output))
    process.start()
    process.join(WALL_SECONDS)
    if process.is_alive():
        process.terminate()
        process.join(10)
        raw_path = output / "raw.json"
        report = (
            json.loads(raw_path.read_text(encoding="utf-8"))
            if raw_path.exists()
            else {"plan": plan}
        )
        report.update(
            state_before_external_timeout=report.get("state"),
            state="EXPERIMENT_BOUND_REACHED",
            bound_reason="EXTERNAL_WALL_TIMEOUT",
            semantic_verdict="UNREVIEWED",
        )
        write_json(raw_path, report)
    elif not (output / "raw.json").exists():
        write_json(
            output / "raw.json",
            {"plan": plan, "state": "HARNESS_ERROR", "exit_code": process.exitcode},
        )
    ending = {"head_sha": _head(), "product_tree_sha256": _tree_hash(PROJECT_ROOT / "src")}
    write_json(
        output / "end_binding.json",
        {**ending, "unchanged": all(plan[key] == value for key, value in ending.items())},
    )
    return 0 if process.exitcode == 0 else 2


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    raise SystemExit(execute_plan(args.plan, args.output))


if __name__ == "__main__":
    main()
