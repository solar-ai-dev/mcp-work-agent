"""Replay one saved backend Query input with coarse/exact route projections."""

from __future__ import annotations

import argparse
import hashlib
import json
import tempfile
import time
from copy import deepcopy
from dataclasses import fields
from pathlib import Path
from uuid import uuid4

from scripts.evaluate_retrieval_plan_query_node import (
    _checkpoint_settings,
    _load_latest_state,
    _RecordingInferencePort,
)

from google_work_agent.adapters.langgraph.subgraphs.retrieval.graph import (
    _runtime_route_constraint_policies,
)
from google_work_agent.adapters.llm.runtime.llm_credential_router import SessionMemorySecretStore
from google_work_agent.api.composition import ProductionRuntimeConfig, build_production_runtime
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
    coarse_resource_category,
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
from google_work_agent.application.use_cases.run.guard_run_budget import build_default_run_budget
from google_work_agent.application.use_cases.setting.update_settings import UpdateSettingsCommand
from google_work_agent.ports.system.settings_port import SettingsPatchV1


def _fingerprint(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=False, default=str).encode("utf-8")
    ).hexdigest()


def evaluate(
    database: Path,
    result_path: Path,
    *,
    preflight_only: bool = False,
    case_name: str = "034_actual",
) -> dict[str, object]:
    state = _load_latest_state(database)
    request = state["__request__"]
    intent = deepcopy(state["request_intent"])
    routes = deepcopy(state["tool_route_plan"]["input_plan"]["input_routes"])
    user_request = request.request_text
    if case_name != "034_actual":
        resource_type, dependency_type, needed, user_request = {
            "task_list_only": (
                "TASK_LIST",
                "TASK",
                "작업 목록의 이름",
                "Kestrel 작업 목록 이름을 알려줘.",
            ),
            "calendar_only": (
                "CALENDAR",
                "CALENDAR_EVENT",
                "캘린더 이름",
                "Kestrel 캘린더 이름을 알려줘.",
            ),
        }[case_name]
        routes = [
            route for route in routes if route["resource_type"] in {resource_type, dependency_type}
        ]
        for route in routes:
            route["reason_codes"] = (
                ["REQUESTED_INPUT"]
                if route["resource_type"] == resource_type
                else [
                    "RETRIEVAL_TASK_DETAIL"
                    if dependency_type == "TASK"
                    else "RETRIEVAL_CALENDAR_EVENT_DETAIL"
                ]
            )
        intent["goal"] = user_request
        intent["completion_conditions"] = [needed]
        intent["requested_effect_hints"] = ["READ"]
        intent["requested_resource_hints"] = [resource_type]
        intent["analysis_requirement"] = "NONE"
        intent["resource_responsibilities"] = {
            "source_reads": [
                {
                    "resource_type": resource_type,
                    "required_information": [needed],
                    "target_scope": "CRITERIA",
                }
            ],
            "outputs": [],
        }
        intent["constraints"] = [
            {"kind": "USER_REQUIREMENT", "field": "required_information", "value": [needed]},
            {
                "kind": "USER_REQUIREMENT",
                "field": "original_search_request",
                "value": [user_request],
            },
        ]
    settings = _checkpoint_settings(database)
    exact = bind_exact_resource_refs(
        request_intent=intent, frozen_routes=routes, selected_resources=request.selected_resources
    )
    containers = resolve_route_container_scopes(
        frozen_routes=routes,
        selected_resources=request.selected_resources,
        authorized_tasklist_ids=settings.get("selected_tasklist_ids", []),
        authorized_calendar_ids=settings.get("selected_calendar_ids", []),
    )
    manifest = default_prompt_manifest_path()
    ref = load_prompt_reference(
        "retrieval.plan_query", manifest_path=manifest, execution_scope=DEVELOPMENT_SMOKE
    )
    inputs = []
    result: dict[str, object] = {
        "binding": {
            "baseline_sha": "4d612d6f",
            "saved_run_id": state["run_id"],
            "case_name": case_name,
            "origin": "SAVED_BACKEND" if case_name == "034_actual" else "SYNTHETIC_CONTRAST",
            "model": "qwen3.5:9b",
            "temperature": 0,
            "seed": 1729,
            "prompt_hash": ref.content_hash,
            "schema_fingerprint": _fingerprint(RETRIEVAL_QUERY_PLAN_V2_OUTPUT_SCHEMA.json_schema),
            "connector_reads": 0,
            "provider_writes": 0,
        },
        "cases": [],
    }
    for label in ("coarse_baseline", "exact_candidate"):
        prompt_input = initial_retrieval_planner_input(
            user_request=user_request,
            request_intent=intent,
            input_routes=routes,
            retrieval_budget=RetrievalBudget(),
            validated_resource_refs=exact["refs_by_route"],
            validated_container_refs=containers,
        )
        by_id = {route["route_id"]: route["resource_type"] for route in routes}
        for route in prompt_input["input_routes"]:
            route["resource_type"] = (
                by_id[route["route_id"]]
                if label == "exact_candidate"
                else coarse_resource_category(by_id[route["route_id"]])
            )
        record = {
            "variant": label,
            "input_fingerprint": _fingerprint(prompt_input),
            "route_types": [
                (route["route_id"], route["resource_type"])
                for route in prompt_input["input_routes"]
            ],
            "result": None,
        }
        inputs.append((record, prompt_input))
        result["cases"].append(record)
    result_path.parent.mkdir(parents=True, exist_ok=True)
    result_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )
    if preflight_only:
        return result
    config = ProductionRuntimeConfig.development(
        runtime_root=Path(tempfile.mkdtemp(prefix="gwa-saved-query-routes-")),
        working_directory=Path(__file__).resolve().parents[1],
        mcp_manifest_version="2026-08-07.p0",
        keyring_store=SessionMemorySecretStore(),
        prompt_manifest_path=manifest,
        sampling_temperature=0,
        sampling_seed=1729,
    )
    container = build_production_runtime(
        **{field.name: getattr(config, field.name) for field in fields(config)},
        bootstrap_secret=uuid4().hex,
        service_instance_id=f"saved-query-{uuid4()}",
    )
    runtime = container.structured_inference_port
    runtime.run_context_provider = lambda: None
    container.update_settings_handler(
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
    dispatches = 0
    original_dispatch = runtime.before_provider_dispatch

    def count_dispatch() -> None:
        nonlocal dispatches
        original_dispatch()
        dispatches += 1

    runtime.before_provider_dispatch = count_dispatch
    recording = _RecordingInferencePort(runtime, [])
    for record, prompt_input in inputs:
        recording.reset()
        before = dispatches
        start = time.perf_counter()
        try:
            budget = build_default_run_budget(started_at_ms=int(time.time() * 1000))
            with (
                provider_dispatch_execution_scope(
                    run_id=f"saved-query-replay-{uuid4()}", now_ms=lambda: int(time.time() * 1000)
                ),
                provider_dispatch_budget_scope(budget),
            ):
                plan, updated, llm_invoked = plan_query(
                    llm_runtime=recording,
                    prompt_ref=ref,
                    revision_prompt_ref=ref,
                    output_schema=RETRIEVAL_QUERY_PLAN_V2_OUTPUT_SCHEMA,
                    prompt_input=prompt_input,
                    requested_mode="LOCAL_GPU",
                    frozen_routes=routes,
                    route_policies=_runtime_route_constraint_policies(routes),
                    retry_budget=budget,
                    validated_resource_refs=exact["refs_by_route"],
                    validated_container_refs=containers,
                    now_ms=state["retry_budget"]["started_at_ms"],
                    timezone=settings.get("timezone", "Asia/Seoul"),
                )
            record["result"] = {
                "route_ids": [q["route_id"] for q in plan["route_queries"]],
                "first_output": (
                    recording.results[0]["structured_output"] if recording.results else None
                ),
                "llm_invoked": llm_invoked,
                "semantic_revisions": sum(updated["semantic_revisions_used_by_failure"].values()),
            }
        except Exception as exc:
            record["result"] = {
                "error_type": type(exc).__name__,
                "error": str(exc)[:300],
                "first_output": (
                    recording.results[0]["structured_output"] if recording.results else None
                ),
            }
        record["provider_dispatches"] = dispatches - before
        record["input_tokens"] = sum(x["input_tokens"] for x in recording.results)
        record["output_tokens"] = sum(x["output_tokens"] for x in recording.results)
        record["provider_latency_ms"] = sum(x["latency_ms"] for x in recording.results)
        record["elapsed_ms"] = int((time.perf_counter() - start) * 1000)
        result_path.write_text(
            json.dumps(result, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
        )
        print(
            label if (label := record["variant"]) else "",
            record["result"].get("route_ids", record["result"].get("error_type")),
            flush=True,
        )
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--result", type=Path, required=True)
    parser.add_argument("--preflight-only", action="store_true")
    parser.add_argument(
        "--case-name",
        choices=("034_actual", "task_list_only", "calendar_only"),
        default="034_actual",
    )
    args = parser.parse_args()
    evaluate(
        args.database, args.result, preflight_only=args.preflight_only, case_name=args.case_name
    )
