"""Replay production Retrieval query planning over persisted synthetic Run states.

This evaluator calls only ``retrieval.plan_query``.  It does not compile the
Product Graph or dispatch connector reads/writes.  Persisted Canonical v8
checkpoints provide the actual upstream RequestIntent and ToolRoute outputs so
one prompt candidate can be measured across many Run inputs without rerunning
the full workflow.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import tempfile
import time
from collections import Counter
from dataclasses import dataclass, fields
from pathlib import Path
from typing import Any, Literal, cast
from uuid import uuid4

from evaluation.dataset_v8 import CanonicalCaseV8, load_cases
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer

from google_work_agent.adapters.langgraph.subgraphs.retrieval.graph import (
    _runtime_route_constraint_policies,
)
from google_work_agent.adapters.llm.ollama.transport import OllamaHTTPClient
from google_work_agent.adapters.llm.runtime.llm_credential_router import (
    SessionMemorySecretStore,
)
from google_work_agent.adapters.system.sqlite_checkpoint import (
    _CHECKPOINT_VALUE_TYPES,
)
from google_work_agent.api.composition import (
    ProductionRuntimeConfig,
    build_production_runtime,
)
from google_work_agent.application.agents.request_understanding.contracts.request_intent import (
    RequestIntentV2,
)
from google_work_agent.application.agents.retrieval.bind_exact_resource_refs import (
    bind_exact_resource_refs,
)
from google_work_agent.application.agents.retrieval.contracts.query_plan_schema import (
    RETRIEVAL_QUERY_PLAN_V2_OUTPUT_SCHEMA,
)
from google_work_agent.application.agents.retrieval.plan_query import (
    RetrievalBudget,
    initial_retrieval_planner_input,
    plan_query,
)
from google_work_agent.application.agents.retrieval.resolve_route_container_scopes import (
    resolve_route_container_scopes,
)
from google_work_agent.application.agents.tool_routing.bind_registry_candidates import (
    is_retrieval_dependency_route,
)
from google_work_agent.application.agents.tool_routing.contracts.tool_route_plan import (
    InputToolRouteV1,
)
from google_work_agent.application.prompt_runtime.prompt_registry import (
    DEVELOPMENT_SMOKE,
    default_prompt_manifest_path,
    load_prompt_reference,
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
from google_work_agent.ports.system.settings_port import SettingsPatchV1

DEFAULT_MODEL_ID = "qwen3.5:9b"
DEFAULT_TIMEZONE = "Asia/Seoul"
SupportedModelId = Literal["qwen3.5:9b", "qwen3.5:4b"]


@dataclass
class _RecordingInferencePort:
    delegate: Any
    results: list[dict[str, object]]

    def infer(self, *args: Any, **kwargs: Any) -> Any:
        result = self.delegate.infer(*args, **kwargs)
        self.results.append(
            {
                "structured_output": result.structured_output,
                "input_tokens": result.input_tokens,
                "output_tokens": result.output_tokens,
                "latency_ms": result.latency_ms,
            }
        )
        return result

    def reset(self) -> None:
        self.results.clear()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--checkpoint-root", type=Path, required=True)
    parser.add_argument("--result-path", type=Path, required=True)
    parser.add_argument("--split", choices=("CORE", "STRESS", "HOLDOUT"), default="CORE")
    parser.add_argument("--case", action="append", default=[])
    parser.add_argument("--limit", type=int)
    parser.add_argument("--model", default=DEFAULT_MODEL_ID)
    parser.add_argument("--sampling-temperature", type=float, default=0.0)
    parser.add_argument("--sampling-seed", type=int, default=1729)
    parser.add_argument("--candidate-id", default="working-tree")
    arguments = parser.parse_args()
    result = evaluate(
        checkpoint_root=arguments.checkpoint_root.resolve(),
        result_path=arguments.result_path.resolve(),
        split=arguments.split,
        case_ids=tuple(arguments.case),
        limit=arguments.limit,
        model_id=arguments.model,
        sampling_temperature=arguments.sampling_temperature,
        sampling_seed=arguments.sampling_seed,
        candidate_id=arguments.candidate_id,
    )
    print(json.dumps(result["summary"], ensure_ascii=False, sort_keys=True), flush=True)


def evaluate(
    *,
    checkpoint_root: Path,
    result_path: Path,
    split: str,
    case_ids: tuple[str, ...],
    limit: int | None,
    model_id: str,
    sampling_temperature: float,
    sampling_seed: int,
    candidate_id: str,
) -> dict[str, object]:
    if model_id not in {"qwen3.5:9b", "qwen3.5:4b"}:
        raise ValueError(f"unsupported local model for node replay: {model_id}")
    supported_model_id = cast(SupportedModelId, model_id)
    cases = load_cases()
    selected = [
        case
        for case in cases.values()
        if case.raw.get("split") == split and (not case_ids or case.case_id in case_ids)
    ]
    if limit is not None:
        selected = selected[:limit]
    if not selected:
        raise ValueError("no Canonical cases matched the requested node corpus")

    manifest_path = default_prompt_manifest_path()
    prompt_ref = load_prompt_reference(
        "retrieval.plan_query",
        manifest_path=manifest_path,
        execution_scope=DEVELOPMENT_SMOKE,
    )
    installed_models = {
        model.model_id: model.digest for model in OllamaHTTPClient().list_installed_models()
    }
    runtime_root = Path(tempfile.mkdtemp(prefix="gwa-retrieval-plan-node-"))
    config = ProductionRuntimeConfig.development(
        runtime_root=runtime_root,
        working_directory=Path(__file__).resolve().parents[1],
        mcp_manifest_version="2026-08-07.p0",
        keyring_store=SessionMemorySecretStore(),
        prompt_manifest_path=manifest_path,
        sampling_temperature=sampling_temperature,
        sampling_seed=sampling_seed,
    )
    container = build_production_runtime(
        **{field.name: getattr(config, field.name) for field in fields(config)},
        bootstrap_secret=uuid4().hex,
        service_instance_id=f"retrieval-plan-node-{uuid4()}",
    )
    runtime = container.structured_inference_port
    update_settings = container.update_settings_handler
    if runtime is None or update_settings is None:
        raise RuntimeError("production LLM runtime is unavailable")
    runtime.run_context_provider = lambda: None
    update_settings(
        UpdateSettingsCommand(
            str(uuid4()),
            SettingsPatchV1(
                schema_version=1,
                preferred_local_model_id=supported_model_id,
                preferred_llm_mode="LOCAL_GPU",
                external_llm_consent=False,
            ),
        )
    )

    provider_dispatch_count = 0
    production_before_dispatch = runtime.before_provider_dispatch

    def count_provider_dispatch() -> None:
        nonlocal provider_dispatch_count
        production_before_dispatch()
        provider_dispatch_count += 1

    runtime.before_provider_dispatch = count_provider_dispatch
    recording_runtime = _RecordingInferencePort(runtime, [])
    records: list[dict[str, object]] = []
    started = time.perf_counter()
    for case in selected:
        before = provider_dispatch_count
        recording_runtime.reset()
        record = _evaluate_case(
            case=case,
            checkpoint_root=checkpoint_root,
            llm_runtime=recording_runtime,
            prompt_ref=prompt_ref,
        )
        provider_calls = provider_dispatch_count - before
        record["provider_call_count"] = provider_calls
        record["llm_inference_count"] = len(recording_runtime.results)
        record["semantic_revision_count"] = max(
            _as_int(record.get("semantic_revision_count", 0)),
            max(0, len(recording_runtime.results) - 1),
        )
        record["input_tokens"] = sum(
            _as_int(result["input_tokens"]) for result in recording_runtime.results
        )
        record["output_tokens"] = sum(
            _as_int(result["output_tokens"]) for result in recording_runtime.results
        )
        record["provider_latency_ms"] = sum(
            _as_int(result["latency_ms"]) for result in recording_runtime.results
        )
        record["first_call_classification"] = _first_call_classification(
            record=record,
            provider_calls=provider_calls,
            inference_results=recording_runtime.results,
        )
        if record["outcome"] == "FIRST_CALL_VALID" and provider_calls > 1:
            record["outcome"] = "SCHEMA_REPAIR_RECOVERED"
        elif record["outcome"] == "VALID_AFTER_RETRY":
            record["outcome"] = "SEMANTIC_REVISION_RECOVERED"
        _classify_policy_coverage(record)
        if record["outcome"] in {
            "FAILED",
            "SCHEMA_REPAIR_RECOVERED",
            "SEMANTIC_REVISION_RECOVERED",
        }:
            record["candidate_outputs"] = [
                result["structured_output"] for result in recording_runtime.results
            ]
        if record["outcome"] == "FAILED":
            record["failure_family"] = _failure_family(record)
        records.append(record)
        public_record = {key: value for key, value in record.items() if key != "candidate_outputs"}
        print(json.dumps(public_record, ensure_ascii=False, sort_keys=True), flush=True)

    summary = _summarize_records(
        records=records,
        split=split,
        duration_ms=int((time.perf_counter() - started) * 1000),
    )
    result: dict[str, object] = {
        "binding": {
            "schema_version": 1,
            "checkpoint_corpus": checkpoint_root.name,
            "prompt_id": prompt_ref.prompt_id,
            "prompt_version": prompt_ref.prompt_version,
            "prompt_hash": prompt_ref.content_hash,
            "model_id": model_id,
            "model_digest": installed_models.get(model_id),
            "sampling_temperature": sampling_temperature,
            "sampling_seed": sampling_seed,
            "candidate_id": candidate_id,
            "connector_dispatch_enabled": False,
            "product_graph_compiled": False,
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


def _summarize_records(
    *, records: list[dict[str, object]], split: str, duration_ms: int
) -> dict[str, object]:
    outcome_counts = Counter(str(record["outcome"]) for record in records)
    eligible = sum(
        count
        for outcome, count in outcome_counts.items()
        if outcome not in {"SKIP_NO_NODE_INPUT", "SKIP_CHECKPOINT_MISSING"}
    )
    deterministic_count = outcome_counts["DETERMINISTIC_VALID"]
    llm_path_count = eligible - deterministic_count
    llm_dispatched_count = sum(
        _as_int(record["provider_call_count"]) > 0 for record in records
    )
    first_call_counts = Counter(
        str(record.get("first_call_classification", "OTHER_FAILED"))
        for record in records
        if record["outcome"]
        not in {
            "DETERMINISTIC_VALID",
            "SKIP_NO_NODE_INPUT",
            "SKIP_CHECKPOINT_MISSING",
        }
    )
    first_call_valid = first_call_counts["SEMANTIC_VALID"]
    failure_family_counts = Counter(
        str(record["failure_family"])
        for record in records
        if record.get("failure_family") is not None
    )
    successful = sum(
        outcome_counts[outcome]
        for outcome in (
            "DETERMINISTIC_VALID",
            "FIRST_CALL_VALID",
            "SCHEMA_REPAIR_RECOVERED",
            "SEMANTIC_REVISION_RECOVERED",
            "POLICY_COMPOSITION_RECOVERED",
        )
    )
    revision_still_failed = sum(
        record["outcome"] in {"FAILED", "POLICY_ROUTE_UNRESOLVED"}
        and _as_int(record.get("semantic_revision_count", 0)) > 0
        for record in records
    )
    revision_attempted = sum(
        _as_int(record.get("semantic_revision_count", 0)) > 0 for record in records
    )
    total_input_tokens = sum(_as_int(record.get("input_tokens", 0)) for record in records)
    total_output_tokens = sum(_as_int(record.get("output_tokens", 0)) for record in records)
    total_provider_latency_ms = sum(
        _as_int(record.get("provider_latency_ms", 0)) for record in records
    )
    return {
        "schema_version": 2,
        "node_id": "retrieval.plan_query",
        "split": split,
        "case_count": len(records),
        "eligible_case_count": eligible,
        "successful_case_count": successful,
        "node_valid_rate": (successful / eligible if eligible else 0.0),
        "deterministic_success_count": deterministic_count,
        "llm_path_case_count": llm_path_count,
        "llm_dispatched_case_count": llm_dispatched_count,
        "first_call_valid_count": first_call_valid,
        "first_call_valid_rate": (first_call_valid / llm_path_count if llm_path_count else 0.0),
        "first_call_dispatched_valid_rate": (
            first_call_valid / llm_dispatched_count if llm_dispatched_count else 0.0
        ),
        "first_call_classification_counts": dict(sorted(first_call_counts.items())),
        "schema_repair_recovered_count": outcome_counts["SCHEMA_REPAIR_RECOVERED"],
        "policy_composition_recovered_count": outcome_counts["POLICY_COMPOSITION_RECOVERED"],
        "semantic_revision_recovered_count": outcome_counts["SEMANTIC_REVISION_RECOVERED"],
        "semantic_revision_attempted_count": revision_attempted,
        "semantic_revision_attempt_rate": (
            revision_attempted / llm_path_count if llm_path_count else 0.0
        ),
        "semantic_revision_still_failed_count": revision_still_failed,
        "failure_family_counts": dict(sorted(failure_family_counts.items())),
        "provider_call_count": sum(
            _as_int(record["provider_call_count"]) for record in records
        ),
        "input_tokens": total_input_tokens,
        "output_tokens": total_output_tokens,
        "mean_input_tokens_per_dispatched_case": (
            total_input_tokens / llm_dispatched_count if llm_dispatched_count else 0.0
        ),
        "mean_output_tokens_per_dispatched_case": (
            total_output_tokens / llm_dispatched_count if llm_dispatched_count else 0.0
        ),
        "provider_latency_ms": total_provider_latency_ms,
        "mean_provider_latency_ms_per_dispatched_case": (
            total_provider_latency_ms / llm_dispatched_count if llm_dispatched_count else 0.0
        ),
        "outcome_counts": dict(sorted(outcome_counts.items())),
        "duration_ms": duration_ms,
    }


def _evaluate_case(
    *,
    case: CanonicalCaseV8,
    checkpoint_root: Path,
    llm_runtime: Any,
    prompt_ref: Any,
) -> dict[str, object]:
    checkpoint_path = checkpoint_root / case.case_id / "state" / "data" / "google_work_agent.db"
    if not checkpoint_path.is_file():
        return {"case_id": case.case_id, "outcome": "SKIP_CHECKPOINT_MISSING"}
    state = _load_latest_state(checkpoint_path)
    request = cast(Any, state.get("__request__"))
    request_intent = state.get("request_intent")
    tool_route_plan = state.get("tool_route_plan")
    input_plan = tool_route_plan.get("input_plan") if isinstance(tool_route_plan, dict) else None
    frozen_routes = input_plan.get("input_routes") if isinstance(input_plan, dict) else None
    if (
        request is None
        or not isinstance(request_intent, dict)
        or not isinstance(frozen_routes, list)
        or not frozen_routes
    ):
        return {"case_id": case.case_id, "outcome": "SKIP_NO_NODE_INPUT"}
    typed_intent = cast(RequestIntentV2, request_intent)
    typed_routes = cast(list[InputToolRouteV1], frozen_routes)

    selected_resources = request.selected_resources
    exact_bindings = bind_exact_resource_refs(
        request_intent=typed_intent,
        frozen_routes=typed_routes,
        selected_resources=selected_resources,
    )
    resource_scope = _authorized_resource_scope(
        checkpoint_path=checkpoint_path,
        fallback=case.google_resource_scope(),
    )
    validated_container_refs = resolve_route_container_scopes(
        frozen_routes=typed_routes,
        selected_resources=selected_resources,
        authorized_tasklist_ids=resource_scope["tasklist_ids"],
        authorized_calendar_ids=resource_scope["calendar_ids"],
    )
    prompt_input = initial_retrieval_planner_input(
        user_request=request.request_text,
        request_intent=typed_intent,
        input_routes=typed_routes,
        retrieval_budget=RetrievalBudget(),
        validated_resource_refs=exact_bindings["refs_by_route"],
        validated_container_refs=validated_container_refs,
    )
    replay_started_at_ms = int(time.time() * 1_000)
    run_budget = build_default_run_budget(started_at_ms=replay_started_at_ms)
    original_started_at_ms = _original_started_at_ms(state, replay_started_at_ms)
    timezone = _case_timezone(case, checkpoint_path=checkpoint_path)
    started = time.perf_counter()
    try:
        with (
            provider_dispatch_execution_scope(
                run_id=f"node-replay-{case.case_id}-{uuid4()}",
                now_ms=lambda: int(time.time() * 1_000),
            ),
            provider_dispatch_budget_scope(run_budget),
        ):
            query_plan, updated_budget, llm_invoked = plan_query(
                llm_runtime=llm_runtime,
                prompt_ref=prompt_ref,
                revision_prompt_ref=prompt_ref,
                output_schema=RETRIEVAL_QUERY_PLAN_V2_OUTPUT_SCHEMA,
                prompt_input=prompt_input,
                requested_mode="LOCAL_GPU",
                frozen_routes=typed_routes,
                route_policies=_runtime_route_constraint_policies(typed_routes),
                retry_budget=run_budget,
                validated_resource_refs=exact_bindings["refs_by_route"],
                validated_container_refs=validated_container_refs,
                now_ms=original_started_at_ms,
                timezone=timezone,
            )
        revision_count = sum(updated_budget["semantic_revisions_used_by_failure"].values())
        inference_results = getattr(llm_runtime, "results", [])
        first_candidate = (
            inference_results[0].get("structured_output")
            if isinstance(inference_results, list) and inference_results
            else None
        )
        return {
            "case_id": case.case_id,
            "outcome": (
                "DETERMINISTIC_VALID"
                if not llm_invoked
                else "FIRST_CALL_VALID"
                if revision_count == 0
                else "VALID_AFTER_RETRY"
            ),
            "llm_invoked": llm_invoked,
            "semantic_revision_count": revision_count,
            "route_query_count": len(query_plan["route_queries"]),
            "first_inference_route_coverage": _route_coverage_summary(
                typed_routes, first_candidate
            ),
            "final_route_coverage": _route_coverage_summary(typed_routes, query_plan),
            "input_route_ids": [route["route_id"] for route in typed_routes],
            "route_resource_types": [route["resource_type"] for route in typed_routes],
            "duration_ms": int((time.perf_counter() - started) * 1000),
        }
    except Exception as error:
        error_code = getattr(getattr(error, "code", None), "value", None)
        revision_count = sum(run_budget["semantic_revisions_used_by_failure"].values())
        inference_results = getattr(llm_runtime, "results", [])
        first_candidate = (
            inference_results[0].get("structured_output")
            if isinstance(inference_results, list) and inference_results
            else None
        )
        return {
            "case_id": case.case_id,
            "outcome": "FAILED",
            "error_type": type(error).__name__,
            "error_message": str(error),
            "error_code": error_code,
            "reason_code": getattr(error, "reason_code", None),
            "validation_stage": getattr(error, "validation_stage", None),
            "affected_field_paths": list(getattr(error, "affected_field_paths", ())),
            "semantic_revision_count": revision_count,
            "first_inference_route_coverage": _route_coverage_summary(
                typed_routes, first_candidate
            ),
            "input_route_ids": [route["route_id"] for route in typed_routes],
            "route_resource_types": [route["resource_type"] for route in typed_routes],
            "duration_ms": int((time.perf_counter() - started) * 1000),
        }


def _route_coverage_summary(
    routes: list[InputToolRouteV1], candidate: object
) -> dict[str, object] | None:
    if not isinstance(candidate, dict):
        return None
    queries = candidate.get("route_queries")
    if not isinstance(queries, list):
        return None
    selected = {
        query.get("route_id")
        for query in queries
        if isinstance(query, dict) and isinstance(query.get("route_id"), str)
    }
    route_types = {
        route["route_id"]: route["resource_type"] for route in routes
    }
    policy = {
        route["route_id"]
        for route in routes
        if route["required"]
        and any(
            reason in {"POLICY_CALENDAR_CONFLICT_CHECK", "POLICY_TASK_DUPLICATE_CHECK"}
            for reason in route["reason_codes"]
        )
    }
    business = {
        route["route_id"]
        for route in routes
        if route["required"]
        and route["route_id"] not in policy
        and not is_retrieval_dependency_route(route)
    }
    return {
        "selected_resource_types": sorted(
            route_types[route_id] for route_id in selected if route_id in route_types
        ),
        "missing_policy_resource_types": sorted(
            route_types[route_id] for route_id in policy - selected
        ),
        "missing_business_resource_types": sorted(
            route_types[route_id] for route_id in business - selected
        ),
    }


def _classify_policy_coverage(record: dict[str, object]) -> None:
    """Keep model completeness separate from deterministic policy recovery."""
    if record.get("first_call_classification") != "SEMANTIC_VALID":
        return
    first = record.get("first_inference_route_coverage")
    if not isinstance(first, dict) or not first.get("missing_policy_resource_types"):
        return
    record["first_call_classification"] = "POLICY_ROUTE_OMITTED"
    final = record.get("final_route_coverage")
    if isinstance(final, dict) and final.get("missing_policy_resource_types"):
        record["outcome"] = "POLICY_ROUTE_UNRESOLVED"
        record["failure_family"] = "POLICY_ROUTE_OMISSION"
    elif record.get("outcome") in {"FIRST_CALL_VALID", "SCHEMA_REPAIR_RECOVERED"}:
        record["outcome"] = "POLICY_COMPOSITION_RECOVERED"


def _first_call_classification(
    *,
    record: dict[str, object],
    provider_calls: int,
    inference_results: list[dict[str, object]],
) -> str:
    if record["outcome"] in {"SKIP_NO_NODE_INPUT", "SKIP_CHECKPOINT_MISSING"}:
        return "NOT_APPLICABLE_SKIPPED"
    if record["outcome"] == "DETERMINISTIC_VALID":
        return "NOT_APPLICABLE_DETERMINISTIC"
    if provider_calls == 0:
        return "PRE_DISPATCH_FAILED"
    if _as_int(record.get("semantic_revision_count", 0)) > 0:
        return "SCHEMA_VALID_SEMANTIC_INVALID"
    reason = str(record.get("reason_code") or record.get("error_code") or "")
    if record["outcome"] == "FAILED":
        if reason == "OUTPUT_SCHEMA_INVALID" or not inference_results:
            return "SCHEMA_INVALID"
        if reason in {
            "QUERY_USER_CONSTRAINT_MISSING",
            "RETRIEVAL_QUERY_PLAN_SEMANTIC_INVALID",
            "RETRIEVAL_ROUTE_SCOPE_VIOLATION",
        }:
            return "SCHEMA_VALID_SEMANTIC_INVALID"
        return "OTHER_FAILED"
    if provider_calls > 1:
        return "SCHEMA_INVALID"
    return "SEMANTIC_VALID"


def _failure_family(record: dict[str, object]) -> str:
    reason = str(record.get("reason_code") or record.get("error_code") or "")
    raw_paths = record.get("affected_field_paths")
    paths = (
        tuple(str(path) for path in raw_paths)
        if isinstance(raw_paths, list | tuple)
        else ()
    )
    candidate_outputs = record.get("candidate_outputs")
    first_output = (
        candidate_outputs[0] if isinstance(candidate_outputs, list) and candidate_outputs else None
    )
    route_queries = first_output.get("route_queries") if isinstance(first_output, dict) else None
    route_ids = (
        [
            str(query.get("route_id"))
            for query in route_queries
            if isinstance(query, dict) and query.get("route_id") is not None
        ]
        if isinstance(route_queries, list)
        else []
    )
    raw_input_route_ids = record.get("input_route_ids")
    input_route_ids = (
        {str(route_id) for route_id in raw_input_route_ids}
        if isinstance(raw_input_route_ids, list | tuple)
        else set()
    )
    if reason == "QUERY_USER_CONSTRAINT_MISSING":
        return "EXPLICIT_ANCHOR_LOSS"
    if any("TEMPORAL_RANGE" in path or "temporal_range" in path for path in paths):
        return "TEMPORAL_LOSS"
    if len(route_ids) != len(set(route_ids)):
        return "OVER_SELECTION"
    if any(route_id not in input_route_ids for route_id in route_ids):
        return "ROUTE_MISMATCH"
    if reason == "RETRIEVAL_ROUTE_SCOPE_VIOLATION":
        return "ROUTE_MISMATCH"
    if reason == "OUTPUT_SCHEMA_INVALID":
        return "OPERATION_FIELD_MISMATCH"
    if reason == "RETRIEVAL_QUERY_PLAN_SEMANTIC_INVALID":
        return "OPERATION_FIELD_MISMATCH"
    return "OTHER"


def _as_int(value: object) -> int:
    if isinstance(value, bool | int):
        return int(value)
    raise TypeError(f"expected integer metric, got {type(value).__name__}")


def _load_latest_state(database_path: Path) -> dict[str, object]:
    connection = sqlite3.connect(
        f"file:{database_path.resolve().as_posix()}?mode=ro",
        uri=True,
    )
    try:
        row = connection.execute(
            "SELECT type, checkpoint FROM checkpoints ORDER BY checkpoint_id DESC LIMIT 1"
        ).fetchone()
    finally:
        connection.close()
    if row is None:
        return {}
    serde = JsonPlusSerializer(
        allowed_json_modules=_CHECKPOINT_VALUE_TYPES,
        allowed_msgpack_modules=_CHECKPOINT_VALUE_TYPES,
        pickle_fallback=False,
    )
    checkpoint = serde.loads_typed((row[0], bytes(row[1])))
    channel_values = checkpoint.get("channel_values")
    return dict(channel_values) if isinstance(channel_values, dict) else {}


def _original_started_at_ms(state: dict[str, object], fallback: int) -> int:
    retry_budget = state.get("retry_budget")
    value = retry_budget.get("started_at_ms") if isinstance(retry_budget, dict) else None
    return value if isinstance(value, int) else fallback


def _authorized_resource_scope(
    *, checkpoint_path: Path, fallback: dict[str, list[str]]
) -> dict[str, list[str]]:
    settings = _checkpoint_settings(checkpoint_path)
    calendar_ids = settings.get("selected_calendar_ids")
    tasklist_ids = settings.get("selected_tasklist_ids")
    return {
        "calendar_ids": (
            list(calendar_ids)
            if isinstance(calendar_ids, list)
            and all(isinstance(item, str) for item in calendar_ids)
            else fallback["calendar_ids"]
        ),
        "tasklist_ids": (
            list(tasklist_ids)
            if isinstance(tasklist_ids, list)
            and all(isinstance(item, str) for item in tasklist_ids)
            else fallback["tasklist_ids"]
        ),
    }


def _case_timezone(case: CanonicalCaseV8, *, checkpoint_path: Path) -> str:
    settings_timezone = _checkpoint_settings(checkpoint_path).get("timezone")
    if isinstance(settings_timezone, str) and settings_timezone:
        return settings_timezone
    context = case.raw.get("evaluation_context")
    timezone = context.get("timezone") if isinstance(context, dict) else None
    return timezone if isinstance(timezone, str) and timezone else DEFAULT_TIMEZONE


def _checkpoint_settings(checkpoint_path: Path) -> dict[str, object]:
    path = checkpoint_path.parents[1] / "settings" / "app-settings.json"
    if not path.is_file():
        return {}
    document = json.loads(path.read_text(encoding="utf-8"))
    settings = document.get("settings") if isinstance(document, dict) else None
    return dict(settings) if isinstance(settings, dict) else {}


if __name__ == "__main__":
    main()
