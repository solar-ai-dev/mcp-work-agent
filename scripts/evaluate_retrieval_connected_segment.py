"""Run the production Retrieval segment against query-sensitive Canonical fixtures.

The runner restores only the persisted current-Run request intent and frozen input
routes.  It then executes the current Query Planner, provider-neutral materializer,
synthetic Connector READs, evidence selection, and sufficiency loop.  Request
Understanding, Planning, and the Main Product Graph are intentionally not run.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import tempfile
import time
from collections.abc import Callable, Mapping, Sequence
from copy import deepcopy
from dataclasses import dataclass, field, fields, replace
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

from google_work_agent.adapters.langgraph.main.routing.route_after_supervisor import (
    RESUME_CONTRACT_VERSION,
)
from google_work_agent.adapters.langgraph.main.state import (
    GraphState,
    WorkflowPhase,
    initial_graph_state,
)
from google_work_agent.adapters.langgraph.profiles.profile_registry import GraphProfile
from google_work_agent.adapters.langgraph.registry.node_registry import NodeRegistry
from google_work_agent.adapters.langgraph.registry.resume_target_registry import (
    ResumeTargetRegistry,
)
from google_work_agent.adapters.langgraph.subgraphs.planning.graph import PlanningSubgraph
from google_work_agent.adapters.langgraph.subgraphs.retrieval.graph import RetrievalSubgraph
from google_work_agent.adapters.langgraph.subgraphs.review.graph import ReviewSubgraph
from google_work_agent.adapters.langgraph.subgraphs.work_analysis.graph import (
    WorkAnalysisSubgraph,
)
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
    RequestIntentV3,
)
from google_work_agent.application.agents.tool_routing.bind_registry_candidates import (
    is_retrieval_dependency_route,
)
from google_work_agent.application.agents.tool_routing.contracts.tool_route_plan import (
    InputToolRouteV1,
    ToolRoutePlanV2,
)
from google_work_agent.application.agents.work_analysis.contracts.work_analysis_candidates import (
    WorkAnalysisSemanticInputV1,
)
from google_work_agent.application.agents.work_analysis.extract_work_facts import (
    extract_work_facts,
)
from google_work_agent.application.prompt_runtime.prompt_registry import (
    DEVELOPMENT_SMOKE,
    default_prompt_manifest_path,
    load_prompt_reference,
)
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
    attempts: list[dict[str, object]] = field(default_factory=list)
    capture_structured_output: bool = False

    def infer(self, *args: Any, **kwargs: Any) -> Any:
        prompt_ref = args[1] if len(args) > 1 else kwargs.get("prompt_ref")
        prompt_input = args[2] if len(args) > 2 else kwargs.get("prompt_input")
        attempt: dict[str, object] = {
            "prompt_id": getattr(prompt_ref, "prompt_id", None),
            "input_chars": len(str(prompt_input)),
        }
        self.attempts.append(attempt)
        started = time.perf_counter()
        try:
            result = self.delegate.infer(*args, **kwargs)
        except Exception as error:
            code = getattr(error, "code", None)
            attempt.update(
                {
                    "outcome": "FAILED",
                    "error_type": type(error).__name__,
                    "error_code": getattr(code, "value", None),
                    "duration_ms": int((time.perf_counter() - started) * 1000),
                }
            )
            raise
        attempt.update(
            {
                "outcome": "COMPLETED",
                "duration_ms": int((time.perf_counter() - started) * 1000),
            }
        )
        self.calls.append(
            {
                "prompt_id": getattr(prompt_ref, "prompt_id", None),
                "input_tokens": result.input_tokens,
                "output_tokens": result.output_tokens,
                "latency_ms": result.latency_ms,
                "semantic_summary": _summarize_llm_output(
                    getattr(prompt_ref, "prompt_id", None), result.structured_output
                ),
                **(
                    {
                        "prompt_input": prompt_input,
                        "structured_output": result.structured_output,
                    }
                    if self.capture_structured_output
                    else {}
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
    input_overrides: Mapping[str, tuple[RequestIntentV3, ToolRoutePlanV2]] | None = None,
    request_text_overrides: Mapping[str, str] | None = None,
    emit_case_records: bool = True,
    connect_work_analysis: bool = False,
    work_analysis_trials: int = 1,
    capture_work_analysis_detail: bool = False,
    compare_compact_fact_projection: bool = False,
    connect_planning_review: bool = False,
) -> dict[str, object]:
    if work_analysis_trials < 1 or (work_analysis_trials > 1 and not connect_work_analysis):
        raise ValueError("work analysis trials require a connected analysis and count >= 1")
    if capture_work_analysis_detail and not connect_work_analysis:
        raise ValueError("work analysis detail requires a connected analysis")
    if compare_compact_fact_projection and not capture_work_analysis_detail:
        raise ValueError("compact comparison requires captured work analysis detail")
    if connect_planning_review and (not connect_work_analysis or work_analysis_trials != 1):
        raise ValueError("planning/review connection requires one work analysis trial")
    if model_id not in {"qwen3.5:9b", "qwen3.5:4b"}:
        raise ValueError(f"unsupported local model for connected replay: {model_id}")
    cases = load_cases()
    unknown = sorted(set(case_ids) - set(cases))
    if unknown:
        raise ValueError(f"unknown Canonical cases: {', '.join(unknown)}")
    if input_overrides is not None and set(input_overrides) != set(case_ids):
        raise ValueError("current upstream overrides must cover exactly the replayed cases")
    if request_text_overrides is not None and set(request_text_overrides) != set(case_ids):
        raise ValueError("request text overrides must cover exactly the replayed cases")
    if request_text_overrides is not None and any(
        not isinstance(value, str) or not value.strip()
        for value in request_text_overrides.values()
    ):
        raise ValueError("request text overrides must be nonempty strings")
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
            request_text_override=(request_text_overrides or {}).get(case_id),
            dispatch_count=lambda: dispatch_count,
            connect_work_analysis=connect_work_analysis,
            work_analysis_trials=work_analysis_trials,
            capture_work_analysis_detail=capture_work_analysis_detail,
            compare_compact_fact_projection=compare_compact_fact_projection,
            connect_planning_review=connect_planning_review,
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
            "planning_requested": connect_planning_review,
            "work_analysis_trials_per_input": work_analysis_trials if connect_work_analysis else 0,
            "work_analysis_detail_in_local_result": capture_work_analysis_detail,
            "compact_fact_projection_compared": compare_compact_fact_projection,
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
    input_override: tuple[RequestIntentV3, ToolRoutePlanV2] | None = None,
    request_text_override: str | None = None,
    dispatch_count: Callable[[], int] | None = None,
    connect_work_analysis: bool = False,
    work_analysis_trials: int = 1,
    capture_work_analysis_detail: bool = False,
    compare_compact_fact_projection: bool = False,
    connect_planning_review: bool = False,
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
        request_text=request_text_override or request.request_text,
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
    analysis_record: dict[str, object] | None = None
    analysis_trials: list[dict[str, object]] = []
    compact_fact_comparison: dict[str, object] | None = None
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
        retrieval_calls = list(recording_llm.calls)
        retrieval_dispatches = (
            dispatch_count() - dispatches_before if dispatch_count is not None else None
        )
        retrieval_duration_ms = int((time.perf_counter() - started) * 1000)
        if connect_work_analysis and output.get("__target__") == "WORK_ANALYSIS":
            frozen_input = deepcopy(output)
            input_fingerprint = _work_analysis_input_fingerprint(
                frozen_input, evidence_store=evidence_store, replay_id=replay_id
            )
            for trial_index in range(work_analysis_trials):
                trial_input_fingerprint = _work_analysis_input_fingerprint(
                    frozen_input, evidence_store=evidence_store, replay_id=replay_id
                )
                if trial_input_fingerprint != input_fingerprint:
                    raise RuntimeError("frozen work analysis input changed between trials")
                trial_started = time.perf_counter()
                trial_budget = deepcopy(frozen_input.get("retry_budget", run_budget))
                with (
                    provider_dispatch_execution_scope(
                        run_id=replay_id,
                        now_ms=lambda trial_started=trial_started: _replay_clock_ms(
                            original_started_at_ms,
                            retrieval_duration_ms
                            + int((time.perf_counter() - trial_started) * 1_000),
                        ),
                    ),
                    provider_dispatch_budget_scope(trial_budget),
                ):
                    analysis_trials.append(
                        _evaluate_work_analysis(
                            state=deepcopy(frozen_input),
                            llm_runtime=recording_llm,
                            evidence_store=evidence_store,
                            graph_profile=profile,
                            replay_id=replay_id,
                            dispatch_count=dispatch_count,
                            capture_detail=capture_work_analysis_detail,
                            connect_planning_review=connect_planning_review,
                            scope=scope,
                        )
                    )
                analysis_trials[-1]["trial_index"] = trial_index + 1
                analysis_trials[-1]["input_fingerprint"] = trial_input_fingerprint
            analysis_record = analysis_trials[0]
            if compare_compact_fact_projection:
                candidate_started = time.perf_counter()
                with (
                    provider_dispatch_execution_scope(
                        run_id=replay_id,
                        now_ms=lambda: _replay_clock_ms(
                            original_started_at_ms,
                            retrieval_duration_ms
                            + int((time.perf_counter() - candidate_started) * 1_000),
                        ),
                    ),
                    provider_dispatch_budget_scope(
                        deepcopy(frozen_input.get("retry_budget", run_budget))
                    ),
                ):
                    compact_fact_comparison = _evaluate_compact_fact_projection(
                        baseline_trial=analysis_record,
                        llm_runtime=recording_llm,
                        dispatch_count=dispatch_count,
                    )
                compact_fact_comparison["input_fingerprint"] = input_fingerprint
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
                [
                    "WORK_ANALYSIS_SEMANTIC_NOT_EVALUATED",
                    *([] if connect_planning_review else ["PLANNING_NOT_EXECUTED"]),
                    *(
                        ["WORK_ANALYSIS_INCOMPLETE"]
                        if analysis_record["outcome"] != "COMPLETED"
                        else []
                    ),
                ]
                if analysis_record is not None
                else ["DOWNSTREAM_OUTPUT_NOT_EXECUTED"]
                if has_downstream_output
                else []
            ),
            "work_analysis": analysis_record,
            "work_analysis_trials": analysis_trials,
            "compact_fact_projection": compact_fact_comparison,
            "connector_reads": recording_reader.calls,
            "query_attempts": output.get("__context_query_attempts__", []),
            "llm_prompt_counts": _prompt_counts(retrieval_calls),
            "llm_call_count": len(retrieval_calls),
            "provider_dispatch_count": retrieval_dispatches,
            "llm_semantic_summaries": [
                {"prompt_id": call["prompt_id"], "summary": call["semantic_summary"]}
                for call in retrieval_calls
            ],
            "evaluation_judge_call_count": int(semantic_review is not None),
            "input_tokens": sum(_metric(call["input_tokens"]) for call in retrieval_calls),
            "output_tokens": sum(_metric(call["output_tokens"]) for call in retrieval_calls),
            "provider_latency_ms": sum(
                _metric(call["latency_ms"]) for call in retrieval_calls
            ),
            "duration_ms": retrieval_duration_ms,
        }
    except Exception as error:
        return {
            "case_id": case.case_id,
            "outcome": "FAILED",
            "error_type": type(error).__name__,
            "error_message": str(error),
            "reason_code": getattr(error, "reason_code", None),
            "connector_reads": recording_reader.calls,
            "source_route_diagnostics": _source_route_diagnostics(tool_route_plan, None),
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
    input_override: tuple[RequestIntentV3, ToolRoutePlanV2] | None,
) -> tuple[object, object]:
    if input_override is not None:
        return input_override
    return persisted.get("request_intent"), persisted.get("tool_route_plan")


def _replay_clock_ms(original_started_at_ms: int, elapsed_ms: int) -> int:
    """Advance the frozen semantic clock only by this replay's elapsed time."""
    return original_started_at_ms + max(elapsed_ms, 0)


def _evaluate_work_analysis(
    *,
    state: GraphState,
    llm_runtime: _RecordingInferencePort,
    evidence_store: RunScopedEvidenceStore,
    graph_profile: GraphProfile,
    replay_id: str,
    dispatch_count: Callable[[], int] | None,
    capture_detail: bool = False,
    connect_planning_review: bool = False,
    scope: Mapping[str, object] | None = None,
) -> dict[str, object]:
    """Consume the in-memory Retrieval output without persisting raw evidence."""
    calls_before = len(llm_runtime.calls)
    attempts_before = len(llm_runtime.attempts)
    dispatches_before = dispatch_count() if dispatch_count is not None else 0
    started = time.perf_counter()
    previous_capture = llm_runtime.capture_structured_output
    llm_runtime.capture_structured_output = capture_detail
    try:
        analysis = WorkAnalysisSubgraph(
            llm_runtime=llm_runtime,
            prompt_manifest_path=None,
            prompt_execution_scope=DEVELOPMENT_SMOKE,
            id_factory=_IdFactory(f"{replay_id}-analysis"),
            graph_profile=graph_profile,
            transition_run=lambda *_: None,
            merge_decision=cast(Any, _merge_decision),
            evidence_store=evidence_store,
            confirm_inline=lambda _: (_raise_confirmation_required(), None),
        ).build()
        wrapper = StateGraph(GraphState)
        wrapper.add_node("work_analysis", analysis)
        wrapper.add_edge(START, "work_analysis")
        wrapper.add_edge("work_analysis", END)
        output = wrapper.compile().invoke(state, {"recursion_limit": 100})
        artifact = output.get("work_analysis_result")
        artifact_summary = (
            {
                "fact_count": len(artifact.get("work_facts", [])),
                "relation_count": len(artifact.get("relations", [])),
                "ambiguity_count": len(artifact.get("ambiguities", [])),
                "risk_count": len(artifact.get("risks", [])),
                "route_action_necessity_count": len(
                    artifact.get("route_action_necessities", [])
                ),
                "action_necessity": artifact.get("action_necessity"),
            }
            if isinstance(artifact, Mapping)
            else None
        )
        result: dict[str, object] = {
            "outcome": "COMPLETED" if artifact_summary is not None else "NO_RESULT",
            "next_target": output.get("__target__"),
            "workflow_phase": output.get("workflow_phase"),
            "user_interrupt_present": output.get("user_interrupt") is not None,
            "artifact": artifact_summary,
            **({"artifact_detail": artifact} if capture_detail else {}),
        }
    except Exception as error:
        code = getattr(error, "code", None)
        result = {
            "outcome": "FAILED",
            "error_type": type(error).__name__,
            "error_code": getattr(code, "value", None),
            "reason_code": getattr(error, "reason_code", None),
            "provider_dispatch_occurred": getattr(
                error, "provider_dispatch_occurred", None
            ),
        }
    finally:
        llm_runtime.capture_structured_output = previous_capture
    calls = llm_runtime.calls[calls_before:]
    result.update(
        {
            "llm_prompt_counts": _prompt_counts(calls),
            "llm_call_count": len(calls),
            "llm_semantic_summaries": [
                {"prompt_id": call["prompt_id"], "summary": call["semantic_summary"]}
                for call in calls
            ],
            "inference_attempts": llm_runtime.attempts[attempts_before:],
            **(
                {"structured_inference_outputs": [
                    {
                        "prompt_id": call["prompt_id"],
                        "prompt_input": call["prompt_input"],
                        "structured_output": call["structured_output"],
                    }
                    for call in calls
                    if "structured_output" in call
                ]}
                if capture_detail
                else {}
            ),
            "provider_dispatch_count": (
                dispatch_count() - dispatches_before if dispatch_count is not None else None
            ),
            "input_tokens": sum(_metric(call["input_tokens"]) for call in calls),
            "output_tokens": sum(_metric(call["output_tokens"]) for call in calls),
            "provider_latency_ms": sum(_metric(call["latency_ms"]) for call in calls),
            "duration_ms": int((time.perf_counter() - started) * 1000),
        }
    )
    if (
        connect_planning_review
        and result["outcome"] == "COMPLETED"
        and output.get("__target__") == "SOLUTION_PLANNING"
    ):
        result["downstream"] = _evaluate_planning_review(
            state=cast(GraphState, output),
            llm_runtime=llm_runtime,
            evidence_store=evidence_store,
            graph_profile=graph_profile,
            replay_id=replay_id,
            scope=scope or {},
            dispatch_count=dispatch_count,
            capture_detail=capture_detail,
        )
    return result


def _work_analysis_input_fingerprint(
    state: GraphState, *, evidence_store: RunScopedEvidenceStore, replay_id: str
) -> str:
    """Identify an exact frozen semantic handoff without logging its contents."""
    retrieval = state.get("retrieval_result")
    refs = retrieval.get("evidence_refs", []) if isinstance(retrieval, Mapping) else []
    projection = {
        "full_graph_state": state,
        "evidence": evidence_store.resolve(run_id=replay_id, evidence_refs=list(refs)),
    }
    serialized = json.dumps(projection, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _compact_fact_evidence(evidence: Sequence[Mapping[str, object]]) -> list[dict[str, object]]:
    """Candidate-only LLM projection; keep citation and resource provenance."""
    compact: list[dict[str, object]] = []
    for item in evidence:
        locator = item.get("locator")
        compact.append(
            {
                "evidence_id": item.get("evidence_id"),
                "resource_handle": item.get("resource_handle"),
                "excerpt": item.get("excerpt"),
                "is_metadata_only": bool(
                    locator.get("is_metadata_only")
                    if isinstance(locator, Mapping)
                    else False
                ),
            }
        )
    return compact


def _evaluate_compact_fact_projection(
    *,
    baseline_trial: Mapping[str, object],
    llm_runtime: _RecordingInferencePort,
    dispatch_count: Callable[[], int] | None,
) -> dict[str, object]:
    details = baseline_trial.get("structured_inference_outputs")
    first = next(
        (
            item
            for item in details
            if isinstance(item, Mapping)
            and item.get("prompt_id") == "work_analysis.extract_work_facts"
        ),
        None,
    ) if isinstance(details, list) else None
    baseline_input = first.get("prompt_input") if isinstance(first, Mapping) else None
    if not isinstance(baseline_input, Mapping):
        return {"outcome": "SKIP_NO_BASELINE_EXTRACT_INPUT"}
    evidence = baseline_input.get("evidence")
    if not isinstance(evidence, list) or not all(isinstance(item, Mapping) for item in evidence):
        return {"outcome": "SKIP_INVALID_BASELINE_EVIDENCE"}
    semantic_input = cast(
        WorkAnalysisSemanticInputV1,
        {
            **baseline_input,
            "evidence": _compact_fact_evidence(cast(list[Mapping[str, object]], evidence)),
        },
    )
    refs = {
        str(item["evidence_id"])
        for item in evidence
        if isinstance(item.get("evidence_id"), str)
    }
    prompt_ref = load_prompt_reference(
        "work_analysis.extract_work_facts",
        default_prompt_manifest_path(),
        execution_scope=DEVELOPMENT_SMOKE,
    )
    calls_before = len(llm_runtime.calls)
    attempts_before = len(llm_runtime.attempts)
    dispatches_before = dispatch_count() if dispatch_count is not None else 0
    previous_capture = llm_runtime.capture_structured_output
    llm_runtime.capture_structured_output = True
    started = time.perf_counter()
    try:
        facts = extract_work_facts(
            semantic_input=semantic_input,
            llm_runtime=llm_runtime,
            prompt_ref=prompt_ref,
            allowed_evidence_refs=refs,
            requested_mode="LOCAL_GPU",
        )
        result: dict[str, object] = {
            "outcome": "COMPLETED",
            "fact_candidates": facts,
        }
    except Exception as error:
        code = getattr(error, "code", None)
        result = {
            "outcome": "FAILED",
            "error_type": type(error).__name__,
            "error_code": getattr(code, "value", None),
            "reason_code": getattr(error, "reason_code", None),
        }
    finally:
        llm_runtime.capture_structured_output = previous_capture
    calls = llm_runtime.calls[calls_before:]
    result.update(
        {
            "inference_outputs": [
                call.get("structured_output") for call in calls
            ],
            "inference_attempts": llm_runtime.attempts[attempts_before:],
            "provider_dispatch_count": (
                dispatch_count() - dispatches_before if dispatch_count is not None else None
            ),
            "llm_call_count": len(calls),
            "input_tokens": sum(_metric(call["input_tokens"]) for call in calls),
            "output_tokens": sum(_metric(call["output_tokens"]) for call in calls),
            "duration_ms": int((time.perf_counter() - started) * 1000),
        }
    )
    return result


def _evaluate_planning_review(
    *,
    state: GraphState,
    llm_runtime: _RecordingInferencePort,
    evidence_store: RunScopedEvidenceStore,
    graph_profile: GraphProfile,
    replay_id: str,
    scope: Mapping[str, object],
    dispatch_count: Callable[[], int] | None,
    capture_detail: bool,
) -> dict[str, object]:
    """Run adjacent consumers only; never enter Domain Validation or WRITE."""
    calls_before = len(llm_runtime.calls)
    attempts_before = len(llm_runtime.attempts)
    dispatches_before = dispatch_count() if dispatch_count is not None else 0
    previous_capture = llm_runtime.capture_structured_output
    llm_runtime.capture_structured_output = capture_detail
    started = time.perf_counter()
    result: dict[str, object]
    try:
        calendar_ids = scope.get("calendar_ids")
        tasklist_ids = scope.get("tasklist_ids")
        default_calendar = (
            calendar_ids[0]
            if isinstance(calendar_ids, (list, tuple)) and len(calendar_ids) == 1
            else None
        )
        default_tasklist = (
            tasklist_ids[0]
            if isinstance(tasklist_ids, (list, tuple)) and len(tasklist_ids) == 1
            else None
        )
        planning = PlanningSubgraph(
            llm_runtime=llm_runtime,
            prompt_manifest_path=None,
            prompt_execution_scope=DEVELOPMENT_SMOKE,
            id_factory=_IdFactory(f"{replay_id}-planning"),
            graph_profile=graph_profile,
            merge_decision=cast(Any, _merge_decision),
            evidence_store=evidence_store,
            confirm_inline=lambda _: (_raise_confirmation_required(), None),
            default_tasklist_id_provider=lambda: default_tasklist,
            default_calendar_id_provider=lambda: default_calendar,
        ).build()
        wrapper = StateGraph(GraphState)
        wrapper.add_node("planning", planning)
        wrapper.add_edge(START, "planning")
        wrapper.add_edge("planning", END)
        planned = wrapper.compile().invoke(state, {"recursion_limit": 100})
        planning_result = planned.get("planning_result")
        result = {
            "planning_outcome": (
                "COMPLETED" if isinstance(planning_result, Mapping) else "NO_RESULT"
            ),
            "planning_next_target": planned.get("__target__"),
            "planning_artifact_kind": (
                "ACTION_PLAN"
                if isinstance(planning_result, Mapping) and "actions" in planning_result
                else "ANSWER"
                if isinstance(planning_result, Mapping) and "answer" in planning_result
                else None
            ),
            "planning_action_count": (
                len(planning_result.get("actions", []))
                if isinstance(planning_result, Mapping)
                and isinstance(planning_result.get("actions"), list)
                else None
            ),
            **({"planning_artifact_detail": planning_result} if capture_detail else {}),
            "review_outcome": "NOT_APPLICABLE",
        }
        if planned.get("__target__") == "PLAN_REVIEW_INSPECT":
            registry = ResumeTargetRegistry(
                node_registry=NodeRegistry(graph_version=RESUME_CONTRACT_VERSION),
                graph_version=RESUME_CONTRACT_VERSION,
            )
            review = ReviewSubgraph(
                llm_runtime=llm_runtime,
                prompt_manifest_path=None,
                prompt_execution_scope=DEVELOPMENT_SMOKE,
                id_factory=_IdFactory(f"{replay_id}-review"),
                graph_profile=graph_profile,
                merge_decision=cast(Any, _merge_decision),
                evidence_store=evidence_store,
                load_persisted_evidence=lambda _: [],
                confirm_inline=lambda _: (_raise_confirmation_required(), None),
                resume_target_registry=registry,
            ).build()
            review_wrapper = StateGraph(GraphState)
            review_wrapper.add_node("review", review)
            review_wrapper.add_edge(START, "review")
            review_wrapper.add_edge("review", END)
            reviewed = review_wrapper.compile().invoke(planned, {"recursion_limit": 100})
            review_result = reviewed.get("plan_review")
            result.update(
                {
                    "review_outcome": (
                        "COMPLETED" if isinstance(review_result, Mapping) else "NO_RESULT"
                    ),
                    "review_status": (
                        review_result.get("status")
                        if isinstance(review_result, Mapping)
                        else None
                    ),
                    "review_next_target": reviewed.get("__target__"),
                    **({"review_artifact_detail": review_result} if capture_detail else {}),
                }
            )
    except Exception as error:
        code = getattr(error, "code", None)
        result = {
            "planning_outcome": "FAILED",
            "error_type": type(error).__name__,
            "error_code": getattr(code, "value", None),
            "reason_code": getattr(error, "reason_code", None),
        }
    finally:
        llm_runtime.capture_structured_output = previous_capture
    calls = llm_runtime.calls[calls_before:]
    result.update(
        {
            "inference_attempts": llm_runtime.attempts[attempts_before:],
            **(
                {
                    "inference_details": [
                        {
                            "prompt_id": call["prompt_id"],
                            "prompt_input": call["prompt_input"],
                            "structured_output": call["structured_output"],
                        }
                        for call in calls
                        if "structured_output" in call
                    ]
                }
                if capture_detail
                else {}
            ),
            "llm_call_count": len(calls),
            "provider_dispatch_count": (
                dispatch_count() - dispatches_before if dispatch_count is not None else None
            ),
            "input_tokens": sum(_metric(call["input_tokens"]) for call in calls),
            "output_tokens": sum(_metric(call["output_tokens"]) for call in calls),
            "duration_ms": int((time.perf_counter() - started) * 1000),
        }
    )
    return result


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
        summary["route_ids"] = (
            [item.get("route_id") for item in queries if isinstance(item, Mapping)]
            if isinstance(queries, list)
            else []
        )
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
    if not isinstance(plan, Mapping):
        return []
    input_plan = plan.get("input_plan")
    routes = input_plan.get("input_routes") if isinstance(input_plan, Mapping) else None
    summaries = acquisition.get("source_summaries") if isinstance(acquisition, Mapping) else []
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
                "route_id": route.get("route_id"),
                "resource_type": route.get("resource_type"),
                "guard_required": bool(route.get("required"))
                and not is_retrieval_dependency_route(cast(InputToolRouteV1, route)),
                "policy_required": bool(route.get("required"))
                and any(
                    isinstance(code, str) and code.startswith("POLICY_")
                    for code in route.get("reason_codes", [])
                ),
                "reason_codes": list(route.get("reason_codes", [])),
                "attempted": bool(matched) if isinstance(acquisition, Mapping) else None,
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
