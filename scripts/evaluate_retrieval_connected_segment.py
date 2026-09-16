"""Run the production Retrieval segment against query-sensitive Canonical fixtures.

The runner restores only the persisted current-Run request intent and frozen input
routes.  It then executes the current Query Planner, provider-neutral materializer,
synthetic Connector READs, evidence selection, and sufficiency loop.  Request
Understanding, Planning, and the Main Product Graph are intentionally not run.
"""

from __future__ import annotations

import argparse
import json
import tempfile
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, fields, replace
from itertools import count
from pathlib import Path
from typing import Any, Literal, cast
from uuid import uuid4

from evaluation.dataset_v8 import CanonicalCaseV8, load_cases
from evaluation.harness.stateful_provider import StatefulSimulatedProvider
from evaluation.semantic_judge_v8 import review_semantics
from langgraph.graph import END, START, StateGraph
from scripts.evaluate_retrieval_plan_query_node import (
    _case_timezone,
    _load_latest_state,
    _original_started_at_ms,
)
from scripts.serve_canonical_v8_product import _case_resources

from google_work_agent.adapters.langgraph.main.state import (
    GraphState,
    WorkflowPhase,
    initial_graph_state,
)
from google_work_agent.adapters.langgraph.profiles.profile_registry import GraphProfile
from google_work_agent.adapters.langgraph.subgraphs.retrieval.graph import RetrievalSubgraph
from google_work_agent.adapters.llm.ollama.transport import OllamaHTTPClient
from google_work_agent.adapters.llm.runtime.llm_credential_router import (
    SessionMemorySecretStore,
)
from google_work_agent.adapters.system.memory.retrieval_evidence_store import (
    RunScopedEvidenceStore,
)
from google_work_agent.adapters.system.memory.run_retrieval_cache import (
    InMemoryRunRetrievalCache,
)
from google_work_agent.api.composition import (
    ProductionRuntimeConfig,
    build_production_runtime,
)
from google_work_agent.application.agents.request_understanding.contracts.request_intent import (
    RequestIntentV2,
)
from google_work_agent.application.agents.tool_routing.bind_registry_candidates import (
    is_retrieval_dependency_route,
)
from google_work_agent.application.agents.tool_routing.contracts.tool_route_plan import (
    InputToolRouteV1,
    ToolRoutePlanV2,
)
from google_work_agent.application.prompt_runtime.prompt_registry import DEVELOPMENT_SMOKE
from google_work_agent.application.tool_registry.load_signed_tool_registry import (
    load_development_tool_registry,
)
from google_work_agent.application.use_cases.run.account_provider_dispatch import (
    provider_dispatch_budget_scope,
    provider_dispatch_execution_scope,
)
from google_work_agent.application.use_cases.run.guard_run_budget import (
    build_default_run_budget,
)
from google_work_agent.application.use_cases.setting.update_settings import (
    UpdateSettingsCommand,
)
from google_work_agent.ports.connector.connector_read_port import ConnectorReadResultV1
from google_work_agent.ports.system.contracts.workflow_execution import WorkflowStartRequest
from google_work_agent.ports.system.settings_port import SettingsPatchV1

DEFAULT_MODEL_ID = "qwen3.5:9b"
SupportedModelId = Literal["qwen3.5:9b", "qwen3.5:4b"]


@dataclass
class _RecordingInferencePort:
    delegate: Any
    calls: list[dict[str, object]]

    def infer(self, *args: Any, **kwargs: Any) -> Any:
        result = self.delegate.infer(*args, **kwargs)
        prompt_ref = args[1] if len(args) > 1 else kwargs.get("prompt_ref")
        self.calls.append(
            {
                "prompt_id": getattr(prompt_ref, "prompt_id", None),
                "input_tokens": result.input_tokens,
                "output_tokens": result.output_tokens,
                "latency_ms": result.latency_ms,
                "semantic_summary": _summarize_llm_output(
                    getattr(prompt_ref, "prompt_id", None), result.structured_output
                ),
            }
        )
        return result


class _RecordingReadPort:
    def __init__(self, delegate: StatefulSimulatedProvider) -> None:
        self._delegate = delegate
        self.calls: list[dict[str, object]] = []

    def execute_read(self, binding: Any, tool_arguments: dict[str, Any]) -> Any:
        result = self._delegate.execute_read(binding, tool_arguments)
        output = result.output
        raw_items = output.get("items") if isinstance(output, Mapping) else None
        item = output.get("item") if isinstance(output, Mapping) else None
        self.calls.append(
            {
                "tool_id": str(binding.tool_id),
                "arguments": dict(tool_arguments),
                "result_resource_ids": (
                    [
                        str(value["resource_id"])
                        for value in raw_items
                        if isinstance(value, Mapping) and value.get("resource_id") is not None
                    ]
                    if isinstance(raw_items, list)
                    else [str(item["resource_id"])]
                    if isinstance(item, Mapping) and item.get("resource_id") is not None
                    else []
                ),
            }
        )
        return result


class _IdFactory:
    def __init__(self, prefix: str) -> None:
        self._prefix = prefix
        self._values = count()

    def __call__(self) -> str:
        return f"{self._prefix}-{next(self._values)}"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--checkpoint-root", type=Path, required=True)
    parser.add_argument("--result-path", type=Path, required=True)
    parser.add_argument("--case", action="append", required=True)
    parser.add_argument("--model", default=DEFAULT_MODEL_ID)
    parser.add_argument("--sampling-temperature", type=float, default=0.0)
    parser.add_argument("--sampling-seed", type=int, default=1729)
    arguments = parser.parse_args()
    result = evaluate(
        checkpoint_root=arguments.checkpoint_root.resolve(),
        result_path=arguments.result_path.resolve(),
        case_ids=tuple(arguments.case),
        model_id=arguments.model,
        sampling_temperature=arguments.sampling_temperature,
        sampling_seed=arguments.sampling_seed,
    )
    print(json.dumps(result["summary"], ensure_ascii=False, sort_keys=True), flush=True)


def evaluate(
    *,
    checkpoint_root: Path,
    result_path: Path,
    case_ids: Sequence[str],
    model_id: str,
    sampling_temperature: float,
    sampling_seed: int,
    input_overrides: Mapping[str, tuple[RequestIntentV2, ToolRoutePlanV2]] | None = None,
    emit_case_records: bool = True,
) -> dict[str, object]:
    if model_id not in {"qwen3.5:9b", "qwen3.5:4b"}:
        raise ValueError(f"unsupported local model for connected replay: {model_id}")
    cases = load_cases()
    unknown = sorted(set(case_ids) - set(cases))
    if unknown:
        raise ValueError(f"unknown Canonical cases: {', '.join(unknown)}")
    if input_overrides is not None and set(input_overrides) != set(case_ids):
        raise ValueError("current upstream overrides must cover exactly the replayed cases")
    installed_models = {
        model.model_id: model.digest for model in OllamaHTTPClient().list_installed_models()
    }
    runtime_root = Path(tempfile.mkdtemp(prefix="gwa-retrieval-connected-"))
    config = ProductionRuntimeConfig.development(
        runtime_root=runtime_root,
        working_directory=Path(__file__).resolve().parents[1],
        mcp_manifest_version="2026-08-07.p0",
        keyring_store=SessionMemorySecretStore(),
        sampling_temperature=sampling_temperature,
        sampling_seed=sampling_seed,
    )
    container = build_production_runtime(
        **{field.name: getattr(config, field.name) for field in fields(config)},
        bootstrap_secret=uuid4().hex,
        service_instance_id=f"retrieval-connected-{uuid4()}",
    )
    runtime = container.structured_inference_port
    update_settings = container.update_settings_handler
    if runtime is None or update_settings is None:
        raise RuntimeError("production LLM runtime is unavailable")
    runtime.run_context_provider = lambda: None
    dispatch_count = 0
    before_dispatch = runtime.before_provider_dispatch

    def count_dispatch() -> None:
        nonlocal dispatch_count
        before_dispatch()
        dispatch_count += 1

    runtime.before_provider_dispatch = count_dispatch
    update_settings(
        UpdateSettingsCommand(
            str(uuid4()),
            SettingsPatchV1(
                schema_version=1,
                preferred_local_model_id=cast(SupportedModelId, model_id),
                preferred_llm_mode="LOCAL_GPU",
                external_llm_consent=False,
            ),
        )
    )

    records: list[dict[str, object]] = []
    started = time.perf_counter()
    for case_id in case_ids:
        record = _evaluate_case(
            case=cases[case_id],
            checkpoint_root=checkpoint_root,
            llm_runtime=runtime,
            model_id=model_id,
            input_override=(input_overrides or {}).get(case_id),
            dispatch_count=lambda: dispatch_count,
        )
        records.append(record)
        if emit_case_records:
            print(json.dumps(record, ensure_ascii=False, sort_keys=True), flush=True)
    task_achievable = sum(record.get("task_achievable") is True for record in records)
    node_correct = sum(record.get("node_processing_correct") is True for record in records)
    summary = {
        "case_count": len(records),
        "executed_count": sum(record.get("outcome") == "COMPLETED" for record in records),
        "skipped_missing_input_count": sum(
            record.get("outcome") == "SKIP_NO_NODE_INPUT" for record in records
        ),
        "task_achievable_count": task_achievable,
        "node_processing_correct_count": node_correct,
        "connector_read_count": sum(
            len(cast(list[object], record.get("connector_reads", []))) for record in records
        ),
        "llm_call_count": sum(
            int(cast(int, record.get("llm_call_count", 0))) for record in records
        ),
        "provider_dispatch_count": sum(
            int(cast(int, record.get("provider_dispatch_count", 0)))
            for record in records
        ),
        "evaluation_judge_call_count": sum(
            int(cast(int, record.get("evaluation_judge_call_count", 0)))
            for record in records
        ),
        "node_processing_review_required_count": sum(
            record.get("node_processing_correct") is None for record in records
        ),
        "provider_write_count": 0,
        "duration_ms": int((time.perf_counter() - started) * 1000),
    }
    result: dict[str, object] = {
        "binding": {
            "schema_version": 1,
            "checkpoint_corpus": checkpoint_root.name,
            "model_id": model_id,
            "model_digest": installed_models.get(model_id),
            "sampling_temperature": sampling_temperature,
            "sampling_seed": sampling_seed,
            "execution_scope": "QUERY_TO_EVIDENCE_SYNTHETIC_PROVIDER",
            "request_understanding_executed": False,
            "current_upstream_input_supplied": bool(input_overrides),
            "input_source": (
                "CURRENT_UPSTREAM_IN_MEMORY" if input_overrides else "SAVED_CHECKPOINT"
            ),
            "planning_executed": False,
            "product_main_graph_compiled": False,
            "provider_write_enabled": False,
        },
        "summary": summary,
        "cases": records,
    }
    result_path.parent.mkdir(parents=True, exist_ok=True)
    result_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return result


def _evaluate_case(
    *,
    case: CanonicalCaseV8,
    checkpoint_root: Path,
    llm_runtime: Any,
    model_id: str,
    input_override: tuple[RequestIntentV2, ToolRoutePlanV2] | None = None,
    dispatch_count: Callable[[], int] | None = None,
) -> dict[str, object]:
    database = checkpoint_root / case.case_id / "state" / "data" / "google_work_agent.db"
    if not database.is_file():
        return {"case_id": case.case_id, "outcome": "SKIP_CHECKPOINT_MISSING"}
    persisted = _load_latest_state(database)
    request = persisted.get("__request__")
    request_intent, tool_route_plan = _select_replay_inputs(persisted, input_override)
    input_plan = tool_route_plan.get("input_plan") if isinstance(tool_route_plan, Mapping) else None
    routes = input_plan.get("input_routes") if isinstance(input_plan, Mapping) else None
    if (
        not isinstance(request, WorkflowStartRequest)
        or not isinstance(request_intent, Mapping)
        or not isinstance(tool_route_plan, Mapping)
        or not isinstance(routes, list)
    ):
        return {"case_id": case.case_id, "outcome": "SKIP_NO_NODE_INPUT"}
    if not routes:
        return {"case_id": case.case_id, "outcome": "SKIP_NO_NODE_INPUT"}

    wall_started_at_ms = int(time.time() * 1_000)
    original_started_at_ms = _original_started_at_ms(persisted, wall_started_at_ms)
    run_budget = build_default_run_budget(started_at_ms=original_started_at_ms)
    replay_id = f"connected-{case.case_id.lower()}-{uuid4().hex[:8]}"
    replay_request = replace(
        request,
        run_id=replay_id,
        workflow_key=replay_id,
        requested_mode="LOCAL_GPU",
        run_budget=run_budget,
    )
    profile_value = persisted.get("graph_profile", GraphProfile.SIX_ROLE_BASELINE.value)
    profile = GraphProfile(str(profile_value))
    state = initial_graph_state(
        replay_request,
        graph_profile=profile,
        graph_version="retrieval-connected-evaluation-v1",
        initial_target="context_retriever",
    )
    state["workflow_phase"] = WorkflowPhase.CONTEXT_RETRIEVAL.value
    state["request_intent"] = cast(Any, dict(request_intent))
    state["tool_route_plan"] = cast(Any, dict(tool_route_plan))
    state["admitted_connector_ids"] = sorted(
        {
            str(route["connector_id"])
            for route in routes
            if isinstance(route, Mapping) and route.get("connector_id") is not None
        }
    )

    provider_resources = _case_resources(case.raw)
    provider = StatefulSimulatedProvider(
        initial_resources=provider_resources,
        read_result_factory=_read_result,
    )
    recording_reader = _RecordingReadPort(provider)
    recording_llm = _RecordingInferencePort(llm_runtime, [])
    evidence_store = RunScopedEvidenceStore()
    scope = case.google_resource_scope()
    now_ms = original_started_at_ms
    timezone = _case_timezone(case, checkpoint_path=database)
    retrieval = RetrievalSubgraph(
        llm_runtime=recording_llm,
        prompt_manifest_path=None,
        prompt_execution_scope=DEVELOPMENT_SMOKE,
        id_factory=_IdFactory(replay_id),
        graph_profile=profile,
        transition_run=lambda *_: None,
        should_stop_for_cancel=lambda _: False,
        merge_decision=cast(Any, _merge_decision),
        evidence_store=evidence_store,
        connector_reader=recording_reader,
        tool_catalog=load_development_tool_registry(),
        read_result_cache=InMemoryRunRetrievalCache(),
        confirm_inline=lambda _: (_raise_confirmation_required(), None),
        now_ms=lambda: now_ms,
        timezone_provider=lambda: timezone,
        authorized_tasklist_ids_provider=lambda: tuple(scope["tasklist_ids"]),
        authorized_calendar_ids_provider=lambda: tuple(scope["calendar_ids"]),
    ).build()
    wrapper = StateGraph(GraphState)
    wrapper.add_node("retrieval", retrieval)
    wrapper.add_edge(START, "retrieval")
    wrapper.add_edge("retrieval", END)
    graph = wrapper.compile()
    started = time.perf_counter()
    dispatches_before = dispatch_count() if dispatch_count is not None else 0
    try:
        with (
            provider_dispatch_execution_scope(
                run_id=replay_id,
                now_ms=lambda: _replay_clock_ms(
                    original_started_at_ms,
                    int((time.perf_counter() - started) * 1_000),
                ),
            ),
            provider_dispatch_budget_scope(run_budget),
        ):
            output = graph.invoke(state, {"recursion_limit": 100})
        retrieval_result = output.get("retrieval_result")
        evidence = (
            []
            if not isinstance(retrieval_result, Mapping)
            else evidence_store.resolve(
                run_id=replay_id,
                evidence_refs=cast(list[str], retrieval_result.get("evidence_refs", [])),
            )
        )
        responsibilities = request_intent.get("resource_responsibilities")
        requested_outputs = (
            responsibilities.get("outputs", [])
            if isinstance(responsibilities, Mapping)
            else []
        )
        has_downstream_output = bool(requested_outputs)
        semantic_review = None
        task_achievable = None
        if not has_downstream_output and isinstance(retrieval_result, Mapping):
            semantic_review = review_semantics(
                required_semantics=cast(str, case.gold["required_semantics"]),
                forbidden_semantics=cast(str, case.gold["forbidden_semantics"]),
                observation={
                    "public_status": None,
                    "terminal_result_kind": None,
                    "assistant_final_message": None,
                    "actions": [],
                    "context_preview": {
                        "items": evidence,
                        "coverage": (
                            retrieval_result.get("coverage")
                            if isinstance(retrieval_result, Mapping)
                            else None
                        ),
                        "missing_information": (
                            retrieval_result.get("missing_information", [])
                            if isinstance(retrieval_result, Mapping)
                            else []
                        ),
                    },
                    "error": None,
                },
                model=model_id,
            )
            task_achievable = (
                semantic_review["required_semantics_satisfied"] is True
                and semantic_review["forbidden_semantics_observed"] is False
            )
        coverage = (
            retrieval_result.get("coverage")
            if isinstance(retrieval_result, Mapping)
            else None
        )
        node_processing_correct = None
        node_processing_classification = "OWNER_REVIEW_REQUIRED"
        if not isinstance(retrieval_result, Mapping):
            node_processing_classification = "NO_RETRIEVAL_RESULT"
        elif has_downstream_output:
            node_processing_classification = "DOWNSTREAM_OUTPUT_NOT_EVALUATED"
        elif task_achievable is True:
            node_processing_correct = True
            node_processing_classification = "VALID_TASK_EVIDENCE"
        elif coverage == "SUFFICIENT":
            node_processing_correct = False
            node_processing_classification = "FALSE_SUFFICIENT"
        return {
            "case_id": case.case_id,
            "outcome": (
                "COMPLETED"
                if isinstance(retrieval_result, Mapping)
                else "NO_RETRIEVAL_RESULT"
            ),
            "next_target": output.get("__target__"),
            "workflow_phase": output.get("workflow_phase"),
            "reference_started_at_ms": original_started_at_ms,
            "retrieval_result_present": isinstance(retrieval_result, Mapping),
            "user_interrupt_present": output.get("user_interrupt") is not None,
            "coverage": coverage,
            "missing_information": (
                retrieval_result.get("missing_information", [])
                if isinstance(retrieval_result, Mapping)
                else []
            ),
            "evidence_count": len(evidence),
            "evidence": evidence,
            "task_achievable": task_achievable,
            "node_processing_correct": node_processing_correct,
            "node_processing_classification": node_processing_classification,
            "state_diagnostics": _state_diagnostics(output),
            "source_route_diagnostics": _source_route_diagnostics(
                tool_route_plan,
                output.get("acquisition_result"),
            ),
            "semantic_review": semantic_review,
            "evaluation_limitations": (
                ["DOWNSTREAM_OUTPUT_NOT_EXECUTED"] if has_downstream_output else []
            ),
            "connector_reads": recording_reader.calls,
            "query_attempts": output.get("__context_query_attempts__", []),
            "llm_prompt_counts": _prompt_counts(recording_llm.calls),
            "llm_call_count": len(recording_llm.calls),
            "provider_dispatch_count": (
                dispatch_count() - dispatches_before if dispatch_count is not None else None
            ),
            "llm_semantic_summaries": [
                {"prompt_id": call["prompt_id"], "summary": call["semantic_summary"]}
                for call in recording_llm.calls
            ],
            "evaluation_judge_call_count": int(semantic_review is not None),
            "input_tokens": sum(_metric(call["input_tokens"]) for call in recording_llm.calls),
            "output_tokens": sum(_metric(call["output_tokens"]) for call in recording_llm.calls),
            "provider_latency_ms": sum(
                _metric(call["latency_ms"]) for call in recording_llm.calls
            ),
            "duration_ms": int((time.perf_counter() - started) * 1000),
        }
    except Exception as error:
        return {
            "case_id": case.case_id,
            "outcome": "FAILED",
            "error_type": type(error).__name__,
            "error_message": str(error),
            "reason_code": getattr(error, "reason_code", None),
            "connector_reads": recording_reader.calls,
            "llm_prompt_counts": _prompt_counts(recording_llm.calls),
            "llm_call_count": len(recording_llm.calls),
            "provider_dispatch_count": (
                dispatch_count() - dispatches_before if dispatch_count is not None else None
            ),
            "llm_semantic_summaries": [
                {"prompt_id": call["prompt_id"], "summary": call["semantic_summary"]}
                for call in recording_llm.calls
            ],
            "duration_ms": int((time.perf_counter() - started) * 1000),
        }


def _read_result(
    tool_id: str,
    output: dict[str, Any],
    call_no: int,
) -> ConnectorReadResultV1:
    next_page_token = output.get("next_page_token")
    total_count = output.get("total_count")
    return ConnectorReadResultV1(
        1,
        tool_id,
        f"synthetic-connected-{call_no}",
        output,
        next_page_token if isinstance(next_page_token, str) else None,
        total_count if isinstance(total_count, int) else None,
    )


def _select_replay_inputs(
    persisted: Mapping[str, object],
    input_override: tuple[RequestIntentV2, ToolRoutePlanV2] | None,
) -> tuple[object, object]:
    if input_override is not None:
        return input_override
    return persisted.get("request_intent"), persisted.get("tool_route_plan")


def _replay_clock_ms(original_started_at_ms: int, elapsed_ms: int) -> int:
    """Advance the frozen semantic clock only by this replay's elapsed time."""
    return original_started_at_ms + max(elapsed_ms, 0)


def _summarize_llm_output(prompt_id: object, output: object) -> dict[str, object]:
    """Keep first-call shape and decisions without source text or completions."""
    if not isinstance(output, Mapping):
        return {"shape": "NON_OBJECT"}
    summary: dict[str, object] = {"field_names": sorted(str(key) for key in output)}
    if prompt_id == "retrieval.assess_sufficiency":
        summary["status"] = output.get("status")
        issues = output.get("issues")
        summary["issue_bindings"] = (
            [
                {
                    "slot": item.get("slot"),
                    "issue_type": item.get("issue_type"),
                    "resolution_source": item.get("resolution_source"),
                }
                for item in issues
                if isinstance(item, Mapping)
            ]
            if isinstance(issues, list)
            else []
        )
    elif prompt_id == "retrieval.plan_query":
        queries = output.get("route_queries")
        summary["route_query_count"] = len(queries) if isinstance(queries, list) else None
        summary["operation_kinds"] = (
            [item.get("operation") for item in queries if isinstance(item, Mapping)]
            if isinstance(queries, list)
            else []
        )
    elif prompt_id == "retrieval.select_evidence":
        for field_name in (
            "segment_assessments",
            "assessments",
            "selected_segment_ids",
            "evidence_drafts",
        ):
            value = output.get(field_name)
            if isinstance(value, list):
                summary[f"{field_name}_count"] = len(value)
    return summary


def _state_diagnostics(state: Mapping[str, object]) -> dict[str, object]:
    sufficiency = state.get("sufficiency")
    if isinstance(sufficiency, tuple) and sufficiency:
        sufficiency = sufficiency[0]
    selection = state.get("evidence_selection")
    workflow_signal = state.get("workflow_signal")
    final_result = state.get("final_result")
    acquisition = state.get("acquisition_result")
    read_result_handles = state.get("read_result_handles")
    finalize_intent = state.get("finalize_intent")
    return {
        "sufficiency_status": (
            sufficiency.get("status") if isinstance(sufficiency, Mapping) else None
        ),
        "sufficiency_issue_slots": (
            [
                item.get("slot")
                for item in sufficiency.get("issues", [])
                if isinstance(item, Mapping)
            ]
            if isinstance(sufficiency, Mapping)
            else []
        ),
        "selected_segment_count": (
            len(selection.get("selected_segment_ids", []))
            if isinstance(selection, Mapping)
            else None
        ),
        "workflow_signal_kind": (
            workflow_signal.get("kind") if isinstance(workflow_signal, Mapping) else None
        ),
        "final_result_status": (
            final_result.get("status") if isinstance(final_result, Mapping) else None
        ),
        "final_result_kind": (
            final_result.get("kind") if isinstance(final_result, Mapping) else None
        ),
        "acquisition_status": (
            acquisition.get("status") if isinstance(acquisition, Mapping) else None
        ),
        "finalize_intent": (
            finalize_intent.get("intent") if isinstance(finalize_intent, Mapping) else None
        ),
        "finalize_reason_code": (
            finalize_intent.get("reason_code")
            if isinstance(finalize_intent, Mapping)
            else None
        ),
        "read_result_handle_count": (
            len(read_result_handles) if isinstance(read_result_handles, list) else None
        ),
    }


def _source_route_diagnostics(plan: object, acquisition: object) -> list[dict[str, object]]:
    if not isinstance(plan, Mapping) or not isinstance(acquisition, Mapping):
        return []
    input_plan = plan.get("input_plan")
    routes = input_plan.get("input_routes") if isinstance(input_plan, Mapping) else None
    summaries = acquisition.get("source_summaries")
    if not isinstance(routes, list) or not isinstance(summaries, list):
        return []
    result: list[dict[str, object]] = []
    for route in routes:
        if not isinstance(route, dict):
            continue
        matched = [
            item
            for item in summaries
            if isinstance(item, Mapping) and item.get("route_id") == route.get("route_id")
        ]
        result.append(
            {
                "resource_type": route.get("resource_type"),
                "guard_required": bool(route.get("required"))
                and not is_retrieval_dependency_route(cast(InputToolRouteV1, route)),
                "policy_required": bool(route.get("required"))
                and any(
                    isinstance(code, str) and code.startswith("POLICY_")
                    for code in route.get("reason_codes", [])
                ),
                "reason_codes": list(route.get("reason_codes", [])),
                "attempted": bool(matched),
                "source_statuses": [item.get("status") for item in matched],
                "resource_counts": [item.get("resource_count") for item in matched],
            }
        )
    return result


def _merge_decision(
    state: Mapping[str, object],
    update: Mapping[str, object],
    decision: Mapping[str, object],
) -> dict[str, object]:
    decision_state = cast(Mapping[str, object], decision["state_update"])
    return {
        **state,
        **update,
        **decision_state,
        "__target__": cast(str, decision["target"]),
    }


def _raise_confirmation_required() -> Any:
    raise RuntimeError("CONNECTED_EVALUATION_REQUIRES_CONFIRMATION")


def _prompt_counts(calls: Sequence[Mapping[str, object]]) -> dict[str, int]:
    result: dict[str, int] = {}
    for call in calls:
        prompt_id = str(call.get("prompt_id"))
        result[prompt_id] = result.get(prompt_id, 0) + 1
    return result


def _metric(value: object) -> int:
    if not isinstance(value, int):
        raise TypeError("connected evaluation metric must be an integer")
    return value


if __name__ == "__main__":
    main()
