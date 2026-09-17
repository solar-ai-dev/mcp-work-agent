"""Frozen sufficiency-input comparison; no Connector or product Graph calls."""

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

from scripts.evaluate_retrieval_plan_query_node import _load_latest_state

from google_work_agent.adapters.llm.ollama.transport import OllamaHTTPClient
from google_work_agent.adapters.llm.runtime.llm_credential_router import SessionMemorySecretStore
from google_work_agent.api.composition import ProductionRuntimeConfig, build_production_runtime
from google_work_agent.application.agents.retrieval.assess_sufficiency import (
    _latest_scope_summaries,
    _route_summaries,
    _worst_source_status,
    budget_state_prompt_projection,
    selected_evidence_prompt_projection,
    source_statuses_prompt_projection,
    sufficiency_output_schema,
)
from google_work_agent.application.agents.retrieval.contracts.retrieval_result import (
    EvidenceDraftV1,
)
from google_work_agent.application.agents.tool_routing.bind_registry_candidates import (
    is_retrieval_dependency_route,
)
from google_work_agent.application.prompt_runtime.prompt_registry import (
    DEVELOPMENT_SMOKE,
    default_prompt_manifest_path,
    load_prompt_reference,
)
from google_work_agent.application.use_cases.run.guard_run_budget import build_default_run_budget
from google_work_agent.application.use_cases.setting.update_settings import UpdateSettingsCommand
from google_work_agent.ports.system.settings_port import SettingsPatchV1


def _fingerprint(value: object) -> str:
    data = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


def _case_inputs() -> list[dict[str, object]]:
    state = _load_latest_state(
        Path("runtime/review-resolution-live-d59b69d1/state/data/google_work_agent.db")
    )
    actual_evidence = [
        item for item in state["__modify_review_evidence__"] if item.get("resource_handle")
    ]
    actual = {
        "name": "034_saved_actual",
        "origin": "SAVED_BACKEND_RUN_RECONSTRUCTED_EVIDENCE",
        "intent": state["request_intent"],
        "routes": state["tool_route_plan"],
        "acquisition": state["acquisition_result"],
        "evidence": actual_evidence,
        "budget": build_default_run_budget(),
    }
    cases: list[dict[str, object]] = [actual]
    base_routes = state["tool_route_plan"]["input_plan"]["input_routes"]
    task_routes = [r for r in base_routes if r["resource_type"] in {"TASK", "TASK_LIST"}]
    calendar_routes = [
        r for r in base_routes if r["resource_type"] in {"CALENDAR", "CALENDAR_EVENT"}
    ]
    source_summaries = state["acquisition_result"]["source_summaries"]
    task_list_evidence = [
        e for e in actual_evidence if e["resource_handle"].startswith("task_list:")
    ]
    calendar_evidence = [e for e in actual_evidence if e["resource_handle"].startswith("calendar:")]

    def synthetic(
        name: str,
        goal: str,
        required_information: str,
        source_type: str,
        routes: list[dict[str, object]],
        evidence: list[EvidenceDraftV1],
        *,
        extra_summaries: list[dict[str, object]] | None = None,
        choice: bool = False,
    ) -> dict[str, object]:
        intent = deepcopy(state["request_intent"])
        intent["goal"] = goal
        intent["completion_conditions"] = [required_information]
        intent["requested_effect_hints"] = ["READ"]
        intent["requested_resource_hints"] = [source_type]
        intent["analysis_requirement"] = "NONE"
        intent["constraints"] = [
            {
                "kind": "USER_REQUIREMENT",
                "field": "required_information",
                "value": [required_information],
            },
            {"kind": "USER_REQUIREMENT", "field": "original_search_request", "value": [goal]},
        ]
        intent["resource_responsibilities"] = {
            "source_reads": [
                {
                    "resource_type": source_type,
                    "required_information": [required_information],
                    "target_scope": "CRITERIA",
                }
            ],
            "outputs": [],
        }
        intent["ambiguity"] = {
            "requires_confirmation": choice,
            "reason_codes": ["TARGET_CHOICE_REQUIRED"] if choice else [],
            "missing_fields": ["selected_task_list"] if choice else [],
        }
        plan = deepcopy(state["tool_route_plan"])
        plan["input_plan"]["input_routes"] = deepcopy(routes)
        plan["output_plan"] = {
            "schema_version": 1,
            "meta": plan["output_plan"]["meta"],
            "output_mode": "ANSWER",
            "output_routes": [],
        }
        ids = {r["route_id"] for r in routes}
        summaries = [deepcopy(s) for s in source_summaries if s.get("route_id") in ids]
        if extra_summaries is None:
            summaries = [
                s
                for s in summaries
                if s.get("route_id")
                in {r["route_id"] for r in routes if r["resource_type"] == source_type}
            ]
        else:
            summaries = extra_summaries
        acquisition = deepcopy(state["acquisition_result"])
        acquisition["source_summaries"] = summaries
        acquisition["resource_handles"] = list(
            dict.fromkeys(e["resource_handle"] for e in evidence)
        )
        return {
            "name": name,
            "origin": "SYNTHETIC_CONTRAST",
            "intent": intent,
            "routes": plan,
            "acquisition": acquisition,
            "evidence": evidence,
            "budget": build_default_run_budget(),
        }

    cases.append(
        synthetic(
            "list_name_only",
            "Kestrel 작업 목록의 이름을 알려줘.",
            "작업 목록의 이름",
            "TASK_LIST",
            task_routes,
            task_list_evidence,
        )
    )
    cases.append(
        synthetic(
            "task_item_needed",
            "Kestrel 대체 일정 작업의 내용과 마감일을 알려줘.",
            "대체 일정 작업 항목의 내용과 마감일",
            "TASK",
            task_routes,
            task_list_evidence,
        )
    )
    task_route = next(r for r in task_routes if r["resource_type"] == "TASK")
    task_evidence: EvidenceDraftV1 = {
        "schema_version": 1,
        "evidence_id": "synthetic-task-evidence",
        "resource_handle": "task:synthetic-1",
        "segment_id": "synthetic-task-segment",
        "kind": "excerpt",
        "excerpt": "대체 일정: 납품 조정 내용을 확인한다. 마감일 2026-08-12.",
        "locator": {},
        "reason_codes": ["SUPPORTS"],
    }
    complete = synthetic(
        "task_item_complete",
        "Kestrel 대체 일정 작업의 내용과 마감일을 알려줘.",
        "대체 일정 작업 항목의 내용과 마감일",
        "TASK",
        task_routes,
        [*task_list_evidence, task_evidence],
    )
    complete["acquisition"]["source_summaries"] = [
        {
            "route_id": task_route["route_id"],
            "source": "TASKS",
            "status": "COMPLETE",
            "required": True,
            "resource_count": 1,
            "resource_handles": ["task:synthetic-1"],
            "checked_read_count": 1,
            "known_scope_count": 1,
            "scope_complete": True,
            "continuation_status": "EXHAUSTED",
            "resources": [],
        }
    ]
    cases.append(complete)
    missing = synthetic(
        "task_item_not_found",
        "Kestrel 대체 일정 작업이 있는지 확인해줘.",
        "대체 일정 작업 항목의 존재 여부",
        "TASK",
        task_routes,
        task_list_evidence,
    )
    missing["acquisition"]["source_summaries"] = [
        {
            "route_id": task_route["route_id"],
            "source": "TASKS",
            "status": "COMPLETE",
            "required": True,
            "resource_count": 0,
            "resource_handles": [],
            "checked_read_count": 1,
            "known_scope_count": 1,
            "scope_complete": True,
            "continuation_status": "EXHAUSTED",
            "resources": [],
        }
    ]
    cases.append(missing)
    cases.append(
        synthetic(
            "user_choice_needed",
            "두 Kestrel 작업 목록 중 어느 것을 사용할지 정해줘.",
            "사용자가 선택한 작업 목록",
            "TASK_LIST",
            task_routes,
            task_list_evidence,
            choice=True,
        )
    )
    cases.append(
        synthetic(
            "calendar_event_needed",
            "Kestrel 일정의 실제 내용을 알려줘.",
            "캘린더 이벤트의 실제 내용",
            "CALENDAR_EVENT",
            calendar_routes,
            calendar_evidence,
        )
    )
    return cases


def _status_projection(case: dict[str, object], *, candidate: bool) -> list[dict[str, object]]:
    if not candidate:
        return source_statuses_prompt_projection(
            tool_route_plan=case["routes"], acquisition_result=case["acquisition"]
        )
    routes = case["routes"]["input_plan"]["input_routes"]
    projected = []
    for route in routes:
        summaries = _route_summaries(route, routes, case["acquisition"])
        status, failure_kind = (
            _worst_source_status(summaries) if summaries else ("NOT_ATTEMPTED", None)
        )
        checked = sum(int(s.get("checked_read_count", 0)) for s in summaries)
        known = sum(int(s.get("known_scope_count", 0)) for s in summaries)
        latest = _latest_scope_summaries(summaries)
        complete = (
            bool(latest)
            and known > 0
            and all(s.get("scope_complete") is True for s in latest)
            and checked >= known
        )
        continuation = (
            "HAS_MORE"
            if any(s.get("continuation_status") == "HAS_MORE" for s in latest)
            else "EXHAUSTED"
            if complete
            else "UNKNOWN"
        )
        projected.append(
            {
                "route_id": route["route_id"],
                "resource_type": route["resource_type"],
                "route_role": (
                    "RETRIEVAL_DEPENDENCY"
                    if is_retrieval_dependency_route(route)
                    else "BUSINESS_SOURCE"
                ),
                "status": status,
                "failure_kind": failure_kind,
                "checked_read_count": checked,
                "known_scope_count": known,
                "scope_complete": complete,
                "continuation_status": continuation,
            }
        )
    return projected


def _requirement_projection(case: dict[str, object]) -> list[dict[str, object]]:
    statuses = _status_projection(case, candidate=True)
    source_reads = case["intent"].get("resource_responsibilities", {}).get("source_reads", [])
    selected = selected_evidence_prompt_projection(case["evidence"])
    for status in statuses:
        resource_type = status["resource_type"]
        status["required_information"] = [
            information
            for source in source_reads
            if source["resource_type"] == resource_type
            for information in source["required_information"]
        ]
        prefix = resource_type.lower() + ":"
        status["observed_evidence"] = [
            {"evidence_ref": item["evidence_ref"], "role": item["role"]}
            for item in selected
            if item["resource_ref"].startswith(prefix)
        ]
    return statuses


def evaluate(
    result_path: Path, *, preflight_only: bool = False, variant: str = "paired"
) -> dict[str, object]:
    cases = _case_inputs()
    manifest = default_prompt_manifest_path()
    ref = load_prompt_reference(
        "retrieval.assess_sufficiency", manifest_path=manifest, execution_scope=DEVELOPMENT_SMOKE
    )
    prompt_source = Path(
        "src/google_work_agent/application/prompt_runtime/sources/retrieval.assess_sufficiency.md"
    )
    model_digest = next(
        (
            m.digest
            for m in OllamaHTTPClient().list_installed_models()
            if m.model_id == "qwen3.5:9b"
        ),
        None,
    )
    if model_digest is None:
        raise RuntimeError("qwen3.5:9b not installed")
    result = {
        "binding": {
            "baseline_sha": "4d612d6f",
            "model": "qwen3.5:9b",
            "model_digest": model_digest,
            "temperature": 0,
            "seed": 1729,
            "prompt_hash": ref.content_hash,
            "prompt_source_sha256": hashlib.sha256(prompt_source.read_bytes()).hexdigest(),
            "schema_version": "sufficiency-result-v2",
            "provider_reads": 0,
            "provider_writes": 0,
        },
        "cases": [],
    }
    prepared = []
    for case in cases:
        evidence = selected_evidence_prompt_projection(case["evidence"])
        schema = sufficiency_output_schema(case["routes"])
        for label in (
            ("bound",)
            if variant == "bound"
            else ("requirement",)
            if variant == "requirement"
            else ("baseline", "candidate")
        ):
            output_schema = deepcopy(schema)
            if label == "bound":
                issue_schema = output_schema.json_schema["properties"]["issues"]["items"]
                issue_schema["allOf"] = [
                    {
                        "if": {
                            "properties": {"resolution_source": {"enum": ["GOOGLE", "CONNECTOR"]}},
                            "required": ["resolution_source"],
                        },
                        "then": {"required": ["route_id"]},
                    }
                ]
            prompt_input = {
                "request_intent": case["intent"],
                "selected_evidence": evidence,
                "source_statuses": (
                    _requirement_projection(case)
                    if label in {"requirement", "bound"}
                    else _status_projection(case, candidate=label == "candidate")
                ),
                "budget_state": budget_state_prompt_projection(case["budget"]),
                "temporal_constraints": [],
                "read_result_summaries": [],
            }
            record = {
                "case": case["name"],
                "origin": case["origin"],
                "variant": label,
                "fixture_fingerprint": _fingerprint(
                    {k: case[k] for k in ("intent", "routes", "acquisition", "evidence", "budget")}
                ),
                "input_fingerprint": _fingerprint(prompt_input),
                "schema_fingerprint": _fingerprint(output_schema.json_schema),
                "result": None,
            }
            prepared.append((record, prompt_input, output_schema))
            result["cases"].append(record)
    result_path.parent.mkdir(parents=True, exist_ok=True)
    result_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )
    if preflight_only:
        return result
    config = ProductionRuntimeConfig.development(
        runtime_root=Path(tempfile.mkdtemp(prefix="gwa-sufficiency-coverage-")),
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
        service_instance_id=f"suff-coverage-{uuid4()}",
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
    for record, prompt_input, schema in prepared:
        start = time.perf_counter()
        before = dispatches
        try:
            inference = runtime.infer("LOCAL_GPU", ref, prompt_input, schema)
            record["result"] = {
                "structured_output": inference.structured_output,
                "input_tokens": inference.input_tokens,
                "output_tokens": inference.output_tokens,
                "provider_latency_ms": inference.latency_ms,
            }
        except Exception as exc:
            record["result"] = {"error_type": type(exc).__name__, "error": str(exc)[:300]}
        record["provider_dispatches"] = dispatches - before
        record["elapsed_ms"] = int((time.perf_counter() - start) * 1000)
        result_path.write_text(
            json.dumps(result, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
        )
        print(
            record["case"],
            record["variant"],
            record["result"].get("structured_output", record["result"].get("error_type")),
            flush=True,
        )
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--result", type=Path, required=True)
    parser.add_argument("--preflight-only", action="store_true")
    parser.add_argument("--variant", choices=("paired", "requirement", "bound"), default="paired")
    args = parser.parse_args()
    evaluate(args.result, preflight_only=args.preflight_only, variant=args.variant)
