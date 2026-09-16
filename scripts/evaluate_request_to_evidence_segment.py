"""Connect current Request Understanding and Tool Route to synthetic Retrieval READs."""

from __future__ import annotations

import argparse
import json
import tempfile
import time
from dataclasses import fields, replace
from pathlib import Path
from typing import Any, cast
from uuid import uuid4

from evaluation.dataset_v8 import load_cases
from scripts.evaluate_request_source_decision_node import _RecordingInferencePort
from scripts.evaluate_retrieval_connected_segment import evaluate as evaluate_retrieval
from scripts.evaluate_retrieval_plan_query_node import _load_latest_state

from google_work_agent.adapters.llm.runtime.llm_credential_router import (
    SessionMemorySecretStore,
)
from google_work_agent.api.composition import ProductionRuntimeConfig, build_production_runtime
from google_work_agent.application.agents.request_understanding import (
    identify_goal as goal_ops,
)
from google_work_agent.application.agents.request_understanding import (
    identify_output_responsibilities as output_ops,
)
from google_work_agent.application.agents.request_understanding import (
    identify_source_dependencies as source_ops,
)
from google_work_agent.application.agents.request_understanding.contracts.request_intent import (
    RequestIntentV2,
)
from google_work_agent.application.agents.request_understanding.detect_ambiguity import (
    detect_ambiguity,
)
from google_work_agent.application.agents.request_understanding.finalize_intent import (
    finalize_intent,
)
from google_work_agent.application.agents.request_understanding.identify_temporal_scope import (
    identify_temporal_scope,
)
from google_work_agent.application.agents.tool_routing.bind_registry_candidates import (
    bind_registry_candidates,
)
from google_work_agent.application.agents.tool_routing.contracts.tool_route_plan import (
    ToolRoutePlanV2,
)
from google_work_agent.application.agents.tool_routing.determine_io_resources import (
    determine_io_resources,
)
from google_work_agent.application.agents.tool_routing.finalize_route import finalize_route
from google_work_agent.application.agents.tool_routing.resolve_policy_preconditions import (
    resolve_policy_preconditions,
)
from google_work_agent.application.agents.tool_routing.select_tool_if_needed import (
    select_tool_if_needed,
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
from google_work_agent.ports.system.contracts.workflow_execution import WorkflowStartRequest
from google_work_agent.ports.system.settings_port import SettingsPatchV1


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--checkpoint-root", type=Path, required=True)
    parser.add_argument("--result-path", type=Path, required=True)
    parser.add_argument("--retrieval-result-path", type=Path, required=True)
    parser.add_argument("--case", action="append", required=True)
    parser.add_argument("--connect-work-analysis", action="store_true")
    arguments = parser.parse_args()
    cases = load_cases()
    if unknown := sorted(set(arguments.case) - set(cases)):
        raise ValueError(f"unknown cases: {unknown}")

    config = ProductionRuntimeConfig.development(
        runtime_root=Path(tempfile.mkdtemp(prefix="gwa-request-evidence-")),
        working_directory=Path(__file__).resolve().parents[1],
        mcp_manifest_version="2026-08-07.p0",
        keyring_store=SessionMemorySecretStore(),
        prompt_manifest_path=default_prompt_manifest_path(),
        sampling_temperature=0.0,
        sampling_seed=1729,
    )
    container = build_production_runtime(
        **{field.name: getattr(config, field.name) for field in fields(config)},
        bootstrap_secret=uuid4().hex,
        service_instance_id=f"request-evidence-{uuid4()}",
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
                preferred_local_model_id="qwen3.5:9b",
                preferred_llm_mode="LOCAL_GPU",
                external_llm_consent=False,
            ),
        )
    )
    recorder = _RecordingInferencePort(runtime)
    catalog = load_development_tool_registry()
    source_candidates = source_ops.build_source_dependency_candidates(catalog)
    output_candidates = output_ops.build_output_responsibility_candidates(catalog)
    prompt_names = (
        "request_understanding.identify_goal",
        "request_understanding.identify_effect_prohibitions",
        "request_understanding.identify_source_dependencies",
        "request_understanding.identify_output_responsibilities",
        "request_understanding.identify_source_status",
        "request_understanding.identify_temporal_scope",
        "request_understanding.detect_ambiguity",
        "tool_routing.determine_io_resources",
        "tool_routing.select_tool_if_needed",
    )
    refs = {
        name: load_prompt_reference(
            name,
            default_prompt_manifest_path(),
            execution_scope=DEVELOPMENT_SMOKE,
        )
        for name in prompt_names
    }
    records: list[dict[str, object]] = []
    overrides: dict[str, tuple[RequestIntentV2, ToolRoutePlanV2]] = {}
    for case_id in arguments.case:
        database = (
            arguments.checkpoint_root
            / case_id
            / "state"
            / "data"
            / "google_work_agent.db"
        )
        state = _load_latest_state(database)
        request = state.get("__request__")
        if not isinstance(request, WorkflowStartRequest):
            records.append({"case_id": case_id, "outcome": "NO_REQUEST"})
            continue
        local_request = replace(request, requested_mode="LOCAL_GPU")
        recorder.calls.clear()
        recorder.status_outputs.clear()
        budget = build_default_run_budget(started_at_ms=int(time.time() * 1_000))
        started = time.perf_counter()
        try:
            with provider_dispatch_execution_scope(
                run_id=f"request-evidence-{case_id}-{uuid4()}",
                now_ms=lambda: int(time.time() * 1_000),
            ):
                goal, budget = goal_ops.identify_goal_with_budget(
                    llm_runtime=recorder,
                    request=local_request,
                    retry_budget=budget,
                    source_dependency_candidates=source_candidates,
                    output_responsibility_candidates=output_candidates,
                    prompt_ref=refs["request_understanding.identify_goal"],
                    effect_prohibition_prompt_ref=refs[
                        "request_understanding.identify_effect_prohibitions"
                    ],
                    source_dependency_prompt_ref=refs[
                        "request_understanding.identify_source_dependencies"
                    ],
                    output_responsibility_prompt_ref=refs[
                        "request_understanding.identify_output_responsibilities"
                    ],
                    source_status_prompt_ref=refs["request_understanding.identify_source_status"],
                )
                with provider_dispatch_budget_scope(budget):
                    goal = identify_temporal_scope(
                        llm_runtime=recorder,
                        prompt_ref=refs["request_understanding.identify_temporal_scope"],
                        requested_mode="LOCAL_GPU",
                        request_text=request.request_text,
                        candidate=goal,
                    )
                ambiguity, budget = detect_ambiguity(
                    llm_runtime=recorder,
                    request=local_request,
                    goal_candidate=goal,
                    prompt_ref=refs["request_understanding.detect_ambiguity"],
                    retry_budget=budget,
                )
                if ambiguity["requires_confirmation"]:
                    records.append({"case_id": case_id, "outcome": "USER_CONFIRMATION_REQUIRED"})
                    continue
                intent = finalize_intent(
                    goal,
                    ambiguity,
                    artifact_id=str(uuid4()),
                    user_request=request.request_text,
                    repository_default=request.default_github_repository,
                )
                route, budget = determine_io_resources(
                    llm_runtime=recorder,
                    tool_catalog=catalog,
                    request_intent=intent,
                    request=local_request,
                    retry_budget=budget,
                    prompt_ref=refs["tool_routing.determine_io_resources"],
                )
                policy = resolve_policy_preconditions(
                    request_intent=intent,
                    candidate=route,
                )
                if policy.workflow_signal is not None:
                    records.append({"case_id": case_id, "outcome": "SCOPE_CONFIRMATION_REQUIRED"})
                    continue
                bound = bind_registry_candidates(
                    candidate=policy.candidate,
                    tool_catalog=catalog,
                    id_factory=lambda: str(uuid4()),
                )
                selected_tools: dict[tuple[str, str], str] = {}
                for candidate in bound.output_candidates:
                    selected, budget = select_tool_if_needed(
                        llm_runtime=recorder,
                        route_id=candidate.route_id,
                        connector_id=candidate.connector_id,
                        resource_type=candidate.resource_type,
                        effect=candidate.effect,
                        eligible_tool_ids=candidate.eligible_tool_ids,
                        request=local_request,
                        retry_budget=budget,
                        prompt_ref=refs["tool_routing.select_tool_if_needed"],
                    )
                    selected_tools[(candidate.resource_type, candidate.effect)] = selected
                route_result = finalize_route(
                    request_intent=intent,
                    binding=bound,
                    selected_tools=selected_tools,
                    tool_catalog=catalog,
                    id_factory=lambda: str(uuid4()),
                )
                plan = route_result["tool_route_plan"]
                if route_result["disposition"] != "ROUTE_READY" or plan is None:
                    records.append(
                        {
                            "case_id": case_id,
                            "outcome": "ROUTE_NOT_READY",
                            "disposition": route_result["disposition"],
                        }
                    )
                    continue
                overrides[case_id] = (intent, plan)
                records.append(
                    {
                        "case_id": case_id,
                        "outcome": "ROUTE_READY",
                        "business_source_types": [
                            item["resource_type"]
                            for item in intent["resource_responsibilities"]["source_reads"]
                        ],
                        "input_route_types": [
                            item["resource_type"] for item in plan["input_plan"]["input_routes"]
                        ],
                        "output_effects": [
                            [item["resource_type"], item["effect"]]
                            for item in intent["resource_responsibilities"]["outputs"]
                        ],
                        "temporal_constraints": [
                            {
                                "kind": item["kind"],
                                "field": item["field"],
                                "value": item["value"],
                            }
                            for item in intent["constraints"]
                            if item["kind"] in {"DATE", "TIME"}
                        ],
                        "request_reference_started_at_ms": request.run_budget.get(
                            "started_at_ms"
                        ),
                        "producer_llm_calls": len(recorder.calls),
                        "producer_input_tokens": sum(
                            cast(int, call["input_tokens"]) for call in recorder.calls
                        ),
                        "producer_output_tokens": sum(
                            cast(int, call["output_tokens"]) for call in recorder.calls
                        ),
                        "producer_latency_ms": sum(
                            cast(int, call["latency_ms"]) for call in recorder.calls
                        ),
                        "producer_duration_ms": int((time.perf_counter() - started) * 1_000),
                    }
                )
        except Exception as error:
            records.append(
                {
                    "case_id": case_id,
                    "outcome": "UPSTREAM_FAILED",
                    "error_type": type(error).__name__,
                    "reason_code": getattr(error, "reason_code", None),
                    "producer_llm_calls": len(recorder.calls),
                }
            )
        print(json.dumps(records[-1], ensure_ascii=False, sort_keys=True), flush=True)

    retrieval_result = evaluate_retrieval(
        checkpoint_root=arguments.checkpoint_root.resolve(),
        result_path=arguments.retrieval_result_path.resolve(),
        case_ids=tuple(overrides),
        model_id="qwen3.5:9b",
        sampling_temperature=0.0,
        sampling_seed=1729,
        input_overrides=overrides,
        emit_case_records=False,
        connect_work_analysis=arguments.connect_work_analysis,
    )
    result: dict[str, Any] = {
        "binding": {
            "checkpoint_corpus": arguments.checkpoint_root.name,
            "execution_scope": (
                "CURRENT_RU_TO_SYNTHETIC_WORK_ANALYSIS"
                if arguments.connect_work_analysis
                else "CURRENT_RU_TO_SYNTHETIC_RETRIEVAL"
            ),
            "connector_read_type": "SYNTHETIC",
            "provider_write_enabled": False,
            "planning_executed": False,
            "work_analysis_requested": arguments.connect_work_analysis,
        },
        "producer_cases": records,
        "retrieval_summary": retrieval_result["summary"],
        "retrieval_case_outcomes": [
            {
                "case_id": item["case_id"],
                "outcome": item["outcome"],
                "coverage": item.get("coverage"),
                "evidence_count": item.get("evidence_count"),
                "connector_read_count": len(cast(list[object], item.get("connector_reads", []))),
                "llm_call_count": item.get("llm_call_count"),
                "provider_dispatch_count": item.get("provider_dispatch_count"),
                "work_analysis_outcome": (
                    item["work_analysis"].get("outcome")
                    if isinstance(item.get("work_analysis"), dict)
                    else None
                ),
            }
            for item in cast(list[dict[str, Any]], retrieval_result["cases"])
        ],
    }
    arguments.result_path.parent.mkdir(parents=True, exist_ok=True)
    arguments.result_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(result["retrieval_summary"], ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
