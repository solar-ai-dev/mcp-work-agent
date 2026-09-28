"""088: frozen Planning inputs through the real registered router and compiled graph.

This is an isolated component Run, not Main/public API completion. No dependency
callable supplies semantic answers. Fake-wire mode replaces only HTTP generation
responses; hardware selection, assembly, router, budget and graph remain real.
"""

from __future__ import annotations

import argparse
import json
import time
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import asdict
from itertools import count
from pathlib import Path
from typing import Any, Literal, cast
from unittest.mock import patch
from uuid import uuid4

from scripts import evaluate_read_answer_handoff as handoff
from scripts.evaluate_answer_mode_first import mode_first_wire, transport_hash
from scripts.evaluate_effect_prohibition_sampler import head, write_json
from scripts.evaluate_output_format_ablation import file_hash, inspect_diagnostic_model
from scripts.production_answer_choice_candidate import (
    EVALUATION_SLOT,
    OUTPUT_VERSION,
    AnswerChoicePlanningSubgraph,
    _EvaluationRegistry,
    decorate_answer_choice_provider,
)
from scripts.production_snapshot_runtime import snapshot_production_runtime
from scripts.ru_observation import metrics, object_hash
from scripts.verify_answer_fact_handoff import _ObservedStore, load_checkpoint

from google_work_agent.adapters.langgraph.main.state import WorkflowPhase
from google_work_agent.adapters.langgraph.main.supervisor_state_projection import (
    project_supervisor_state,
)
from google_work_agent.adapters.langgraph.profiles.profile_registry import GraphProfile
from google_work_agent.adapters.langgraph.subgraphs.planning.graph import PlanningSubgraph
from google_work_agent.adapters.llm.ollama import transport
from google_work_agent.application.agents.retrieval.resolve_task_calendar_snapshot import (
    resolve_task_calendar_snapshot,
)
from google_work_agent.application.agents.tool_routing.bind_registry_candidates import (
    bind_registry_candidates,
    normalize_resource_type,
)
from google_work_agent.application.agents.tool_routing.determine_io_resources import (
    _resource_responsibility_candidate,
)
from google_work_agent.application.agents.tool_routing.finalize_route import finalize_route
from google_work_agent.application.prompt_runtime.assemble_prompt import assemble_prompt
from google_work_agent.application.prompt_runtime.prompt_registry import EVALUATION, PromptRegistry
from google_work_agent.application.use_cases.conversation.create_conversation import (
    CreateConversationCommand,
)
from google_work_agent.application.use_cases.run.account_provider_dispatch import (
    current_provider_dispatch_budget,
    provider_dispatch_execution_scope,
)
from google_work_agent.application.use_cases.run.get_supervisor_observation import (
    GetSupervisorObservationHandler,
    GetSupervisorObservationQuery,
)
from google_work_agent.application.use_cases.run.guard_run_budget import build_default_run_budget
from google_work_agent.application.use_cases.run.start_run import StartRunCommand
from google_work_agent.ports.llm.structured_inference_contracts import OutputSchemaDefinition
from google_work_agent.ports.system.contracts.workflow_execution import (
    WorkflowCorrelationContext,
    WorkflowStartRequest,
)
from google_work_agent.ports.system.settings_port import SettingsPatchV1

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "evaluation/results"
HISTORY = RESULTS / "084-answer-mode-first-t1/raw.json"
HISTORY_HASH = "3ce662090733ad1d7c8811a566f8f4541514198463212b69615540beca6a8a1b"
CALENDAR = RESULTS / "065-read-answer-handoff-t1/plan.json"
CALENDAR_HASH = "00fd6f33489da6d33660e204bfafcabf68c9b88780c09da41b372eb64e614fb4"
CRITERIA = "evaluation/experiments/088-registered-answer-choice-criteria.md"
TASK_FIELD_CRITERIA = "evaluation/experiments/094-product-task-field-scope-criteria.md"
ANSWER_CHOICE_MODE = "ANSWER_CHOICE_088"
PRODUCT_TASK_FIELD_SCOPE = "PRODUCT_TASK_FIELD_SCOPE"
PLANNING_MODES = (ANSWER_CHOICE_MODE, PRODUCT_TASK_FIELD_SCOPE)
TASK_FIELD_GROUPS = ("PRODUCT_TASK_FIELD_FULL", "PRODUCT_TASK_FIELD_PARTIAL")
MODEL_ID: Literal["qwen3.5:9b"] = "qwen3.5:9b"
SEED = 20260923
DISPATCH_CAP, CALL_TIMEOUT, WALL_SECONDS = 4, 180, 1200
GROUPS = (
    "CORE005_LOOKUP",
    "SYNTHETIC_COMPLETED",
    "SYNTHETIC_REFORMULATION",
    "SYNTHETIC_CALENDAR_LOCATION",
)


def _read(path: Path) -> dict[str, Any]:
    return cast(dict[str, Any], json.loads(path.read_text(encoding="utf-8")))


def _ref(evidence: Mapping[str, Any]) -> str:
    value = evidence.get("evidence_ref") or evidence.get("evidence_id") or evidence.get("id")
    if not isinstance(value, str) or not value:
        raise ValueError("frozen Evidence needs its existing exact reference")
    return value


def _verify_snapshots(projection: dict[str, Any], snapshots: dict[str, Any]) -> None:
    if set(snapshots) != {_ref(item) for item in projection["evidence"]}:
        raise ValueError("every registered Evidence must retain its exact snapshot")
    for evidence in projection["evidence"]:
        if resolve_task_calendar_snapshot(evidence, source_snapshots=snapshots) is None:
            raise ValueError("missing, conflicting, or invalid same-resource/version snapshot")


def expected_first(
    projection: dict[str, Any],
    snapshots: dict[str, Any],
    *,
    planning_mode: str = ANSWER_CHOICE_MODE,
) -> dict[str, Any]:
    """Capture current actual transport construction, with no external dispatch."""
    from scripts.answer_fact_selection_candidate import bind_fact_selection_schema
    from scripts.answer_rendering_choice_candidate import bind_answer_rendering_choice_schema

    if planning_mode not in PLANNING_MODES:
        raise ValueError("unknown compiled Planning mode")
    _verify_snapshots(projection, snapshots)
    arguments = handoff._call_arguments(projection)
    has_catalog = (
        bind_fact_selection_schema(projection, source_snapshots=snapshots) is not None
        if planning_mode == ANSWER_CHOICE_MODE
        else None
    )
    if has_catalog:
        registry = _EvaluationRegistry(
            product_registry=PromptRegistry(),
            product_ref=arguments["prompt_ref"],
            projection=projection,
        )
        arguments["prompt_ref"] = registry.prompt_ref
        arguments["output_schema"] = OutputSchemaDefinition(
            schema_version=OUTPUT_VERSION,
            json_schema=mode_first_wire(
                {
                    "format": bind_answer_rendering_choice_schema(
                        projection, source_snapshots=snapshots
                    )
                }
            )["format"],
        )
        arguments["instruction_text"] = assemble_prompt(
            registry.prompt_ref,
            projection,
            registry=cast(Any, registry),
            execution_scope=EVALUATION,
        )
    captured: list[dict[str, Any]] = []

    def capture(**kwargs: Any) -> dict[str, object]:
        captured.append(deepcopy(kwargs))
        return {"response": "{}"}

    with patch.object(transport, "_post_json", capture):
        transport.OllamaHTTPClient().invoke_structured(**arguments)
    if len(captured) != 1 or captured[0]["path"] != "/api/generate":
        raise ValueError("FIRST must construct one local generate request")
    payload = captured[0]["payload"]
    if payload["options"] != {"num_ctx": 16384, "seed": SEED} or payload["think"] is not False:
        raise ValueError("registered runtime/sampling changed")
    return {
        "prompt_ref": asdict(arguments["prompt_ref"]),
        "output_schema_version": arguments["output_schema"].schema_version,
        "payload": payload,
        "transport_sha256": transport_hash(payload),
        "input_sha256": object_hash(projection),
        "has_fact_catalog": has_catalog,
    }


def _source_cases() -> list[dict[str, Any]]:
    if file_hash(HISTORY) != HISTORY_HASH or file_hash(CALENDAR) != CALENDAR_HASH:
        raise ValueError("frozen source history changed")
    history, calendar = _read(HISTORY), _read(CALENDAR)
    if not history["completed"] or not history["binding_unchanged"]:
        raise ValueError("084 complete immutable history required")
    result: list[dict[str, Any]] = []
    checkpoint = load_checkpoint()
    for group in GROUPS[:3]:
        item = next(
            c for c in history["binding"]["cases"] if c["group"] == group and c["trial"] == 1
        )
        result.append(
            {
                "group": group,
                "prompt_input": deepcopy(item["prompt_input"]),
                "snapshots": deepcopy(item["snapshots"]),
                "component_state": deepcopy(checkpoint) if group == GROUPS[0] else None,
                "source_case_id": item["case_id"],
                "source_sha256": HISTORY_HASH,
                "upstream": "ACTUAL_067_CHECKPOINT" if group == GROUPS[0] else "SYNTHETIC_CONTROL",
            }
        )
    item = next(c for c in calendar["cases"] if c["case_id"] == GROUPS[3])
    result.append(
        {
            "group": GROUPS[3],
            "prompt_input": deepcopy(item["first"]["input"]),
            "snapshots": deepcopy(item["pipeline_input"]["source_snapshots"]),
            "component_state": None,
            "source_case_id": item["case_id"],
            "source_sha256": CALENDAR_HASH,
            "upstream": "SYNTHETIC_CONTROL",
        }
    )
    for case in result:
        if case["component_state"] is None:
            case["component_state"] = _synthetic_component_state(
                case["prompt_input"], group=case["group"]
            )
    return result


def _synthetic_component_state(projection: dict[str, Any], *, group: str) -> dict[str, Any]:
    """Close synthetic artifact freshness without inventing Source/Work meaning.

    Existing Product Source-to-Registry and finalize owners supply route metadata.
    The frozen Retrieval projection remains a supplied component fixture, not a
    newly executed acquisition, and its LLM-facing fields remain byte-identical.
    """
    from google_work_agent.api.composition import load_development_tool_registry

    intent = deepcopy(projection["request_intent"])
    semantic = _resource_responsibility_candidate(intent)
    if semantic is None or semantic.output_mode != "ANSWER":
        raise ValueError("frozen synthetic ANSWER responsibilities required")
    serial = count(1)

    def next_id() -> str:
        return f"088-{group}-artifact-{next(serial)}"

    catalog = load_development_tool_registry()
    binding = bind_registry_candidates(candidate=semantic, tool_catalog=catalog, id_factory=next_id)
    for route in binding.input_routes:
        matches = [
            status
            for status in projection.get("source_statuses", [])
            if normalize_resource_type(status["resource_type"]) == route["resource_type"]
            and status.get("work_unit_ids") == route["work_unit_ids"]
        ]
        if len(matches) > 1:
            raise ValueError("synthetic source projection has ambiguous route identity")
        if matches:
            route["route_id"] = matches[0]["route_id"]
    frozen = finalize_route(
        request_intent=intent,
        binding=binding,
        selected_tools={},
        tool_catalog=catalog,
        id_factory=next_id,
    )
    plan = frozen["tool_route_plan"]
    if plan is None:
        raise ValueError("Product could not freeze synthetic route metadata")
    retrieval = {
        key: deepcopy(value)
        for key, value in projection.items()
        if key not in {"user_request", "request_intent", "answer_outline", "evidence"}
    }
    retrieval.update(
        schema_version=1,
        meta={
            "artifact_id": next_id(),
            "revision": 1,
            "based_on": [
                {"artifact_id": item["artifact_id"], "revision": item["revision"]}
                for item in (intent["meta"], plan["input_plan"]["meta"])
            ],
        },
    )
    return {"request_intent": intent, "tool_route_plan": plan, "retrieval_result": retrieval}


def make_plan(model: dict[str, Any], *, planning_mode: str = ANSWER_CHOICE_MODE) -> dict[str, Any]:
    if planning_mode not in PLANNING_MODES:
        raise ValueError("unknown compiled Planning mode")
    if model.get("model_id") != MODEL_ID or not model.get("model_digest"):
        raise ValueError("actual fixed model metadata required")
    if planning_mode == PRODUCT_TASK_FIELD_SCOPE:
        return _make_task_field_plan(model)
    if model != _read(HISTORY)["binding"]["model"]:
        raise ValueError("historical model digest/parameters/backend metadata changed")
    cases = []
    sources = _source_cases()
    for trial in (1, 2):
        for source in sources:
            case = deepcopy(source)
            case.update(case_id=f"{source['group']}-REGISTERED-T{trial}", trial=trial)
            case["input_binding_sha256"] = object_hash(
                [case["prompt_input"], case["snapshots"], case["component_state"]]
            )
            case["expected_first"] = expected_first(case["prompt_input"], case["snapshots"])
            cases.append(case)
    hashes = handoff._bound_files()
    for path in (
        "scripts/evaluate_registered_answer_choice.py",
        "scripts/production_answer_choice_candidate.py",
        "scripts/production_goal_output_candidate.py",
        "scripts/production_snapshot_runtime.py",
        "scripts/verify_answer_fact_handoff.py",
        "scripts/answer_fact_selection_candidate.py",
        "scripts/answer_rendering_choice_candidate.py",
        "scripts/evaluate_answer_rendering_choice.py",
        "scripts/evaluate_answer_mode_first.py",
        "tests/evaluation/test_evaluate_registered_answer_choice.py",
        CRITERIA,
    ):
        hashes[path] = file_hash(ROOT / path)
    return {
        "kind": "088_REGISTERED_COMPILED_PLANNING",
        "head_sha": head(),
        "model": model,
        "source_hashes": hashes,
        "history_hashes": {
            str(HISTORY.relative_to(ROOT)): HISTORY_HASH,
            str(CALENDAR.relative_to(ROOT)): CALENDAR_HASH,
        },
        "cases": cases,
        "scope": "FRESH_COMPONENT_ACTUAL_SUPERVISOR_PROJECTION_NOT_MAIN_OR_DB_TERMINAL",
        "terminal_intent": "NOT_EVALUATED",
        "policy": {
            "expected_first": 8,
            "trials_per_input": 2,
            "per_trial_actual_dispatch_cap": DISPATCH_CAP,
            "total_actual_dispatch_cap": 8 * DISPATCH_CAP,
            "call_timeout_seconds": CALL_TIMEOUT,
            "wall_seconds": WALL_SECONDS,
            "wall_enforcement": "BEFORE_NEXT_DISPATCH_NOT_THREAD_CANCELLATION",
            "product_schema_semantic_repair": "UNCHANGED_WITHIN_CAP",
            "product_run_budget": (
                "UNCHANGED_NORMAL_PROFILE_WITH_ADDITIONAL_EVALUATION_DISPATCH_CAP"
            ),
            "rerun": 0,
            "concurrency": 1,
            "provider_read_write": 0,
        },
    }


def _make_task_field_plan(model: dict[str, Any]) -> dict[str, Any]:
    from scripts.task_field_scope_diagnostic import build_cases

    cases = deepcopy(build_cases())
    if [(case["group"], case["case_id"], case["trial"]) for case in cases] != [
        (group, f"{group}-T1", 1) for group in TASK_FIELD_GROUPS
    ]:
        raise ValueError("094 requires exactly full then partial, one trial each")
    for case in cases:
        if case["input_binding_sha256"] != object_hash(
            [case["prompt_input"], case["snapshots"], case["component_state"]]
        ):
            raise ValueError("094 fixture input binding changed")
        case["expected_first"] = expected_first(
            case["prompt_input"], case["snapshots"], planning_mode=PRODUCT_TASK_FIELD_SCOPE
        )
    hashes = handoff._bound_files()
    for path in (
        "scripts/evaluate_registered_answer_choice.py",
        "scripts/task_field_scope_diagnostic.py",
        "scripts/production_snapshot_runtime.py",
        "scripts/serve_canonical_v8_product.py",
        "scripts/verify_answer_fact_handoff.py",
        "evaluation/datasets/e2e/canonical_cases_v8.jsonl",
        "evaluation/datasets/e2e/dataset-manifest-v8.json",
        "evaluation/datasets/e2e/fixtures/google_workspace/provider-snapshot-v8.json",
        "tests/evaluation/test_evaluate_registered_answer_choice.py",
        "tests/evaluation/test_task_field_scope_diagnostic.py",
        TASK_FIELD_CRITERIA,
    ):
        hashes[path] = file_hash(ROOT / path)
    return {
        "kind": "094_PRODUCT_COMPILED_PLANNING",
        "planning_mode": PRODUCT_TASK_FIELD_SCOPE,
        "head_sha": head(),
        "model": model,
        "source_hashes": hashes,
        "history_hashes": {},
        "cases": cases,
        "scope": "SYNTHETIC_PRODUCT_COMPONENT_NOT_MAIN_OR_CANONICAL_SCORE",
        "runtime_account_scaffold": "CASE-CORE-005_NOT_SEMANTIC_INPUT_OR_CANONICAL_TRIAL",
        "terminal_intent": "NOT_EVALUATED",
        "policy": {
            "expected_first": 2,
            "trials_per_input": 1,
            "per_trial_actual_dispatch_cap": 1,
            "total_actual_dispatch_cap": 2,
            "call_timeout_seconds": CALL_TIMEOUT,
            "wall_seconds": WALL_SECONDS,
            "wall_enforcement": "BEFORE_NEXT_DISPATCH_NOT_THREAD_CANCELLATION",
            "product_schema_semantic_repair": "FOLLOWUP_BLOCKED_BEFORE_DISPATCH_BY_EVALUATION_CAP",
            "product_run_budget": (
                "UNCHANGED_NORMAL_PROFILE_WITH_ADDITIONAL_EVALUATION_DISPATCH_CAP"
            ),
            "rerun": 0,
            "concurrency": 1,
            "provider_read_write": 0,
            "answer_choice_overlay": False,
        },
    }


def validate_plan(plan: dict[str, Any]) -> None:
    for case in plan["cases"]:
        first = case["expected_first"]
        if transport_hash(first["payload"]) != first["transport_sha256"]:
            raise ValueError("stored FIRST HTTP byte/order seal changed")
    planning_mode = plan.get("planning_mode", ANSWER_CHOICE_MODE)
    regenerated = (
        make_plan(plan["model"])
        if planning_mode == ANSWER_CHOICE_MODE
        else make_plan(plan["model"], planning_mode=planning_mode)
    )
    if plan != regenerated:
        raise ValueError("registered code, input, snapshot, wire or plan changed")


class _Observation:
    def __init__(
        self,
        case: dict[str, Any],
        *,
        started: float,
        save: Any,
        fake: bool,
        planning_mode: str = ANSWER_CHOICE_MODE,
    ) -> None:
        if planning_mode not in PLANNING_MODES:
            raise ValueError("unknown compiled Planning mode")
        self.case, self.started, self.save, self.fake = case, started, save, fake
        self.planning_mode = planning_mode
        self.calls: list[dict[str, Any]] = []
        self.active: dict[str, Any] | None = None
        self.blocked_dispatches: list[str] = []
        self.transport_interrupted = False

    def _guard(self) -> None:
        if time.monotonic() - self.started >= WALL_SECONDS:
            raise RuntimeError("EXPERIMENT_WALL_BOUND_BEFORE_DISPATCH")
        cap = 1 if self.planning_mode == PRODUCT_TASK_FIELD_SCOPE else DISPATCH_CAP
        if len(self.calls) >= cap:
            if self.planning_mode == PRODUCT_TASK_FIELD_SCOPE:
                self.blocked_dispatches.append("EXPERIMENT_TRIAL_DISPATCH_CAP")
                self.save()
            raise RuntimeError("EXPERIMENT_TRIAL_DISPATCH_CAP")

    def decorate(self, raw: Any) -> Any:
        delegate = (
            raw
            if self.planning_mode == PRODUCT_TASK_FIELD_SCOPE
            else decorate_answer_choice_provider(raw)
        )
        owner = self

        class ObservedProvider:
            provider_name = delegate.provider_name
            runtime = delegate.runtime

            def invoke_structured(self, **kwargs: Any) -> Any:
                owner._guard()
                policy, ref = kwargs["runtime_policy"], kwargs["prompt_ref"]
                if (
                    delegate.provider_name != "ollama"
                    or str(delegate.runtime) != "LOCAL_GPU"
                    or delegate.model_id != MODEL_ID
                ):
                    raise ValueError("actual local fixed-model selection required")
                if (
                    policy.sampling_seed != SEED
                    or policy.sampling_temperature is not None
                    or policy.local_timeout_seconds != CALL_TIMEOUT
                ):
                    raise ValueError("actual runtime differs from fixed sampling/timeout")
                if not owner.calls and (
                    asdict(ref) != owner.case["expected_first"]["prompt_ref"]
                    or dict(kwargs["prompt_input"]) != owner.case["prompt_input"]
                ):
                    raise ValueError("actual compiled FIRST differs from frozen projection/ref")
                event: dict[str, Any] = {
                    "call_index": len(owner.calls) + 1,
                    "prompt_ref": asdict(ref),
                    "input": deepcopy(dict(kwargs["prompt_input"])),
                    "input_sha256": object_hash(kwargs["prompt_input"]),
                    "schema_version": kwargs["output_schema"].schema_version,
                    "output_schema": deepcopy(dict(kwargs["output_schema"].json_schema)),
                    "runtime_policy": asdict(policy),
                    "phase": "FIRST" if not owner.calls else "EXISTING_PRODUCT_REPAIR_OR_REVISION",
                    "state": "DISPATCH_STARTED",
                    "wire_request_count": 0,
                    "dispatch_budget_at_entry": deepcopy(current_provider_dispatch_budget()),
                }
                owner.calls.append(event)
                owner.active = event
                owner.save()
                before = time.monotonic()
                try:
                    result = delegate.invoke_structured(**kwargs)
                    event.update(
                        state="RETURNED",
                        content=result.content,
                        input_tokens=result.input_tokens,
                        output_tokens=result.output_tokens,
                        latency_ms=result.latency_ms,
                        actual_model=result.model,
                    )
                    return result
                except Exception as error:
                    event.update(
                        state="ERROR", error_type=type(error).__name__, error=str(error)[:500]
                    )
                    raise
                finally:
                    event["dispatch_budget_at_return"] = deepcopy(
                        current_provider_dispatch_budget()
                    )
                    event["wall_latency_ms"] = int((time.monotonic() - before) * 1000)
                    owner.active = None
                    owner.save()

            def invoke_tool_call(self, **_kwargs: Any) -> Any:
                raise ValueError("this compose-only diagnostic permits no Tool call")

        return ObservedProvider()

    @contextmanager
    def wire(self) -> Iterator[None]:
        original = transport._post_json

        def dispatch(**kwargs: Any) -> Any:
            if kwargs["path"] != "/api/generate":
                return original(**kwargs)
            event = self.active
            if event is None or event["wire_request_count"]:
                raise ValueError("unobserved or repeated HTTP generation forbidden")
            payload = kwargs["payload"]
            if kwargs["timeout_seconds"] != CALL_TIMEOUT:
                raise ValueError("HTTP timeout differs from preregistration")
            if (
                event["phase"] == "FIRST"
                and transport_hash(payload) != self.case["expected_first"]["transport_sha256"]
            ):
                raise ValueError("actual registered FIRST HTTP bytes differ from plan")
            event.update(
                payload=deepcopy(payload),
                transport_sha256=transport_hash(payload),
                wire_request_count=1,
                endpoint=kwargs["endpoint"],
                path=kwargs["path"],
                dispatched_at_ms=int(time.time() * 1000),
                fake_wire=self.fake,
            )
            self.save()
            if self.fake:
                refs = self.case["prompt_input"]["answer_outline"]["evidence_refs"]
                draft = {
                    "schema_version": 2,
                    "answer": "모델 없는 연결 검증용 응답입니다.",
                    "evidence_refs": refs,
                }
                value = (
                    {"mode": "PROSE", **draft}
                    if event["prompt_ref"]["prompt_id"] == EVALUATION_SLOT
                    else draft
                )
                response: dict[str, object] = {
                    "response": json.dumps(value, ensure_ascii=False),
                    "model": MODEL_ID,
                    "done": True,
                    "done_reason": "stop",
                }
            else:
                try:
                    response = original(**kwargs)
                except Exception:
                    self.transport_interrupted = True
                    raise
            # Hidden thinking text is deliberately not copied into the local record.
            if self.planning_mode == PRODUCT_TASK_FIELD_SCOPE:
                # Keep failed JSON FIRSTs before the Product parser consumes them.
                event["provider_visible_output"] = response.get("response")
            event["provider_response_metadata"] = {
                key: deepcopy(response[key])
                for key in (
                    "model",
                    "created_at",
                    "done",
                    "done_reason",
                    "total_duration",
                    "load_duration",
                    "prompt_eval_count",
                    "prompt_eval_duration",
                    "eval_count",
                    "eval_duration",
                )
                if key in response
            }
            self.save()
            if self.planning_mode == PRODUCT_TASK_FIELD_SCOPE and (
                response.get("model") != MODEL_ID or response.get("done") is not True
            ):
                self.transport_interrupted = True
                event["rejected_response_content"] = response.get("response")
                self.save()
                raise ValueError("094 requires the completed response from the fixed model")
            return response

        with patch.object(transport, "_post_json", dispatch):
            yield


def _component_state(case: dict[str, Any], *, run: Any, store: _ObservedStore) -> dict[str, Any]:
    projection = case["prompt_input"]
    refs = [_ref(item) for item in projection["evidence"]]
    store.put(run_id=run.run_id, evidence_drafts=deepcopy(projection["evidence"]))
    for item in projection["evidence"]:
        store.put_resource_snapshot(
            run_id=run.run_id,
            resource_handle=item["resource_handle"],
            source_version_ref=item["locator"]["source_version_ref"],
            snapshot=deepcopy(case["snapshots"][_ref(item)]),
        )
    state = deepcopy(case["component_state"])
    if not isinstance(state, dict):
        raise ValueError("sealed component artifact envelope required")
    state["retrieval_result"]["evidence_refs"] = refs
    budget = build_default_run_budget(started_at_ms=int(time.time() * 1000))
    request = WorkflowStartRequest(
        run_id=run.run_id,
        conversation_id=run.conversation_id,
        workflow_key=run.workflow_key,
        entry_mode="AGENT_SEARCH",
        requested_mode="LOCAL_GPU",
        request_text=projection["user_request"],
        # This fresh local row is only the component's correlation/lifecycle row.
        # Frozen selected identity remains in the unchanged typed Intent; do not
        # infer a new UI selection or Provider authority from Evidence here.
        selected_resource_ids=(),
        correlation=WorkflowCorrelationContext(str(uuid4()), None, "1"),
        run_budget=budget,
        user_message_id=run.user_message_id,
    )
    state.update(
        schema_version=2,
        run_id=run.run_id,
        conversation_id=run.conversation_id,
        langgraph_thread_id=run.workflow_key,
        workflow_phase=WorkflowPhase.SOLUTION_PLANNING.value,
        retry_budget=budget,
        trace_context={},
        prompt_context={},
        __request__=request,
    )
    if "evidence" in state or "user_request" in state:
        raise ValueError("direct evidence/user_request may not bypass Product input schema")
    return cast(dict[str, Any], state)


def _start_component_run(container: Any, boundary: Any, request: str) -> Any:
    conversation_id, command_id = str(uuid4()), str(uuid4())
    container.create_conversation_handler(
        CreateConversationCommand(
            str(uuid4()),
            object_hash(conversation_id),
            conversation_id,
            boundary.account_id,
            "088 isolated Planning component",
            "1",
        )
    )
    result = container.start_run_handler(
        StartRunCommand(
            command_id,
            object_hash([command_id, request]),
            conversation_id,
            request,
            "AGENT_SEARCH",
            "LOCAL_GPU",
            "1",
        )
    )
    if not result.applied:
        raise ValueError("local correlation Run creation failed: " + result.result_code)
    # The pending handoff is deliberately NOT scheduled or resumed.
    return result


def _boundary_observations(boundary: Any | None) -> dict[str, Any]:
    """Keep failed/denied attempts visible; absence of an observer is not zero."""
    if boundary is None:
        return {"observed": False, "events": [], "read_results": [], "counts": None}
    events, reads = deepcopy(boundary.events), deepcopy(boundary.read_results)
    return {
        "observed": True,
        "events": events,
        "read_results": reads,
        "counts": {
            "snapshot_read_attempts": len(reads),
            "snapshot_read_returned": sum("result" in item for item in reads),
            "provider_write_attempts_denied": sum(
                item["boundary"] == "provider_write_dispatch" for item in events
            ),
            "all_boundary_denials": sum(item.get("decision") == "DENY" for item in events),
        },
    }


def _planning_subgraph(
    *,
    planning_mode: str,
    runtime: Any,
    store: Any,
    graph_profile: GraphProfile,
    merge: Any,
    observations: list[dict[str, Any]],
) -> PlanningSubgraph:
    options = {
        "llm_runtime": runtime,
        "prompt_manifest_path": runtime.prompt_manifest_path,
        "prompt_execution_scope": EVALUATION,
        "evidence_store": store,
        "id_factory": lambda: str(uuid4()),
        "graph_profile": graph_profile,
        "merge_decision": merge,
    }
    if planning_mode == PRODUCT_TASK_FIELD_SCOPE:
        return PlanningSubgraph(**options)
    if planning_mode != ANSWER_CHOICE_MODE:
        raise ValueError("unknown compiled Planning mode")
    return AnswerChoicePlanningSubgraph(**options, observations=observations)


def execute_plan(plan: dict[str, Any], output: Path, *, fake_wire: bool = False) -> dict[str, Any]:
    validate_plan(plan)
    planning_mode = plan.get("planning_mode", ANSWER_CHOICE_MODE)
    output = output.resolve()
    if not output.is_relative_to(RESULTS.resolve()) or output == RESULTS.resolve():
        raise ValueError("dedicated evaluation/results directory required")
    if output.exists() and any(output.iterdir()):
        raise ValueError("output already exists; no overwrite or rerun")
    if inspect_diagnostic_model("presence_zero") != plan["model"]:
        raise ValueError("current model/backend differs from sealed plan")
    if not fake_wire:
        claim_namespace = (
            ".094-plan-claims" if planning_mode == PRODUCT_TASK_FIELD_SCOPE else ".088-plan-claims"
        )
        write_json(
            RESULTS / claim_namespace / (object_hash(plan) + ".json"),
            {"plan_sha256": object_hash(plan), "output": output.relative_to(RESULTS).as_posix()},
            exclusive=True,
        )
    write_json(
        output / "execution-claim.json",
        {"plan_sha256": object_hash(plan), "fake_wire": fake_wire},
        exclusive=True,
    )
    raw: dict[str, Any] = {
        "binding": plan,
        "plan_sha256": object_hash(plan),
        "fake_wire": fake_wire,
        "completed": False,
        "semantic_verdict": "NOT_EVALUATED" if fake_wire else "UNREVIEWED",
        "trials": [],
        "calls": [],
        "provider_execution_policy": "NO_READ_WRITE",
        "scope": plan["scope"],
        "rerun": 0,
        "terminal_intent": "NOT_EVALUATED",
    }
    path, started = output / "raw.json", time.monotonic()

    def save() -> None:
        raw["calls"] = [call for trial in raw["trials"] for call in trial.get("calls", [])]
        raw["metrics"] = metrics([item for item in raw["calls"] if item.get("wire_request_count")])
        write_json(path, raw)

    save()
    try:
        for case in plan["cases"]:
            result: dict[str, Any] = {
                "case_id": case["case_id"],
                "group": case["group"],
                "trial": case["trial"],
                "state": "STARTING",
                "events": [],
            }
            raw["trials"].append(result)
            observation = _Observation(
                case, started=started, save=save, fake=fake_wire, planning_mode=planning_mode
            )
            result["calls"] = observation.calls
            trial_directory = output / case["case_id"]
            trial_started = time.monotonic()
            store = _ObservedStore()
            boundary: Any | None = None
            try:
                with (
                    observation.wire(),
                    snapshot_production_runtime(
                        trial_directory / "runtime",
                        allow_loopback_model=True,
                        sampling_seed=SEED,
                        llm_provider_decorator=observation.decorate,
                    ) as (container, boundary),
                ):
                    container.settings_port.update_settings(
                        SettingsPatchV1(
                            1, preferred_local_model_id=MODEL_ID, preferred_llm_mode="LOCAL_GPU"
                        ),
                        operation_ref=case["case_id"],
                    )
                    result["settings"] = asdict(container.settings_port.get_settings())
                    run = _start_component_run(
                        container, boundary, case["prompt_input"]["user_request"]
                    )
                    result["local_run"] = asdict(run)
                    state = _component_state(case, run=run, store=store)
                    result["input_artifact_sha256"] = object_hash(
                        [
                            state.get(key)
                            for key in (
                                "request_intent",
                                "tool_route_plan",
                                "retrieval_result",
                                "work_analysis_result",
                            )
                        ]
                    )

                    def merge(
                        current: Any,
                        update: Any,
                        decision: Any,
                        *,
                        run: Any = run,
                        result: dict[str, Any] = result,
                    ) -> Any:
                        facts = GetSupervisorObservationHandler(
                            container.read_unit_of_work_factory
                        )(GetSupervisorObservationQuery(run.run_id))
                        if facts is None:
                            raise ValueError("actual local Run supervision facts unavailable")
                        projection = project_supervisor_state(
                            state=current,
                            stage_update=update,
                            candidate=decision,
                            durable_facts=facts,
                        )
                        result["supervisor"] = {
                            "durable_facts": asdict(facts),
                            "decision": deepcopy(projection.decision),
                            "source_phase": projection.source_phase,
                            "transition_kind": projection.transition_kind,
                            "invalidated_fields": list(projection.invalidated_fields),
                        }
                        return projection.state

                    runtime = container.structured_inference_port
                    planning = _planning_subgraph(
                        planning_mode=planning_mode,
                        runtime=runtime,
                        store=store,
                        graph_profile=GraphProfile(container.graph_profile),
                        merge=merge,
                        observations=result["events"],
                    )
                    with provider_dispatch_execution_scope(
                        run_id=run.run_id, now_ms=lambda: int(time.time() * 1000)
                    ):
                        try:
                            actual = planning.build().invoke(state)
                            result.update(
                                state="RETURNED",
                                planning_result=actual.get("planning_result"),
                                trace_context=actual.get("trace_context"),
                                retry_budget=actual.get("retry_budget"),
                                supervisor_target=result.get("supervisor", {})
                                .get("decision", {})
                                .get("target"),
                            )
                        finally:
                            # LangGraph copies ContextVars into its worker. The
                            # authoritative dispatch capture must occur there,
                            # not in this caller's unchanged context.
                            result["actual_dispatch_budget"] = next(
                                (
                                    deepcopy(call["dispatch_budget_at_return"])
                                    for call in reversed(observation.calls)
                                    if call.get("dispatch_budget_at_return") is not None
                                ),
                                None,
                            )
                    if any(
                        item["boundary"] not in {"local_auth_status", "local_hardware_probe"}
                        for item in boundary.events
                    ):
                        raise ValueError(
                            "Planning component unexpectedly accessed a Provider boundary"
                        )
            except Exception as error:
                result.update(
                    state="ERROR", error_type=type(error).__name__, error=str(error)[:700]
                )
            finally:
                for call in observation.calls:
                    call.update(case_id=case["case_id"], group=case["group"], trial=case["trial"])
                    if call not in raw["calls"]:
                        raw["calls"].append(call)
                result["calls"] = observation.calls
                result["provider_boundary"] = _boundary_observations(boundary)
                result["snapshot_resolutions"] = store.observations
                result["wall_latency_ms"] = int((time.monotonic() - trial_started) * 1000)
                result["input_binding_unchanged"] = case["input_binding_sha256"] == object_hash(
                    [case["prompt_input"], case["snapshots"], case["component_state"]]
                )
                if planning_mode == PRODUCT_TASK_FIELD_SCOPE:
                    result["blocked_dispatches"] = observation.blocked_dispatches
                    if observation.blocked_dispatches:
                        result.update(
                            state="ERROR", evaluation_bound="EXPERIMENT_TRIAL_DISPATCH_CAP"
                        )
                save()
            if planning_mode == PRODUCT_TASK_FIELD_SCOPE and observation.transport_interrupted:
                remaining = plan["cases"][len(raw["trials"]) :]
                raw["not_dispatched"] = [
                    {"case_id": item["case_id"], "reason": "PRIOR_TRANSPORT_INCOMPLETE"}
                    for item in remaining
                ]
                raw["circuit_break"] = "PRIOR_TRANSPORT_INCOMPLETE"
                break
        else:
            raw["completed"] = True
    finally:
        raw["binding_unchanged"] = False
        try:
            validate_plan(plan)
            raw["binding_unchanged"] = True
        except Exception as error:
            raw["end_binding_error"] = str(error)[:500]
        raw["model_binding_unchanged"] = inspect_diagnostic_model("presence_zero") == plan["model"]
        raw["wall_latency_ms"] = int((time.monotonic() - started) * 1000)
        raw["actual_wire_calls"] = sum(item.get("wire_request_count", 0) for item in raw["calls"])
        raw["actual_model_generations"] = 0 if fake_wire else raw["actual_wire_calls"]
        if planning_mode == PRODUCT_TASK_FIELD_SCOPE:
            raw["execution_coverage"] = {
                "planned_cases": len(plan["cases"]),
                "started_cases": len(raw["trials"]),
                "dispatched_firsts": raw["actual_wire_calls"],
                "not_dispatched_cases": len(raw.get("not_dispatched", [])),
                "returned_trials": sum(item["state"] == "RETURNED" for item in raw["trials"]),
                "failed_trials": sum(item["state"] == "ERROR" for item in raw["trials"]),
                "completion_means": "FIXED_TRIALS_ATTEMPTED_NOT_SEMANTIC_SUCCESS",
            }
        boundaries = [trial["provider_boundary"] for trial in raw["trials"]]
        raw["provider_observation_complete"] = all(item["observed"] for item in boundaries)
        raw["provider_counts"] = (
            {
                key: sum(item["counts"][key] for item in boundaries)
                for key in (
                    "snapshot_read_attempts",
                    "snapshot_read_returned",
                    "provider_write_attempts_denied",
                    "all_boundary_denials",
                )
            }
            if raw["provider_observation_complete"]
            else None
        )
        save()
    return raw


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--prepare", type=Path)
    mode.add_argument("--execute-plan", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--fake-wire", action="store_true")
    parser.add_argument("--planning-mode", choices=PLANNING_MODES)
    args = parser.parse_args()
    if args.prepare:
        if args.fake_wire or args.output:
            parser.error("prepare writes only its sealed plan; no generation")
        plan = make_plan(
            inspect_diagnostic_model("presence_zero"),
            planning_mode=args.planning_mode or ANSWER_CHOICE_MODE,
        )
        write_json(args.prepare, plan, exclusive=True)
        print(
            json.dumps(
                {"plan_sha256": object_hash(plan), "cases": len(plan["cases"]), "generation": 0}
            )
        )
    else:
        if args.planning_mode is not None:
            parser.error("execute uses only the sealed plan mode; no CLI override")
        if args.output is None:
            parser.error("--output is required for execution")
        raw = execute_plan(_read(args.execute_plan), args.output, fake_wire=args.fake_wire)
        print(
            json.dumps(
                {
                    "completed": raw["completed"],
                    "actual_wire_calls": raw["actual_wire_calls"],
                    "fake_wire": raw["fake_wire"],
                    "semantic_verdict": raw["semantic_verdict"],
                }
            )
        )


if __name__ == "__main__":
    main()
