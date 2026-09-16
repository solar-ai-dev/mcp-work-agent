"""Compare frozen Review inputs with an isolated semantic-role projection."""

from __future__ import annotations

import argparse
import hashlib
import json
import tempfile
import time
from copy import deepcopy
from dataclasses import fields
from pathlib import Path
from typing import Any, cast
from uuid import uuid4

from scripts.evaluate_review_reference_time_node import _candidate_manifest

from google_work_agent.adapters.llm.ollama.transport import OllamaHTTPClient
from google_work_agent.adapters.llm.runtime.llm_credential_router import (
    SessionMemorySecretStore,
)
from google_work_agent.api.composition import (
    ProductionRuntimeConfig,
    build_production_runtime,
)
from google_work_agent.application.agents.project_run_reference_time import (
    project_run_reference_time,
)
from google_work_agent.application.agents.review.contracts.review_findings import (
    review_inspector_output_schema,
    validate_review_inspector_result,
)
from google_work_agent.application.prompt_runtime.prompt_registry import (
    DEVELOPMENT_SMOKE,
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

PROMPT_ID = "review.inspect_goal_and_evidence"
MODEL_ID = "qwen3.5:9b"


def _digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()


def _semantic_roles(prompt_input: dict[str, object], started_at_ms: int) -> dict[str, object]:
    reference = project_run_reference_time({"started_at_ms": started_at_ms})
    if reference is None:
        raise ValueError("frozen current-Run reference time is unavailable")
    evidence_roles: list[dict[str, object]] = []
    for evidence in cast(list[dict[str, object]], prompt_input["evidence"]):
        locator = evidence.get("locator")
        resource_handle = evidence.get("resource_handle")
        metadata_times = (
            [
                {"field": key, "value": value, "role": "RESOURCE_METADATA_TIME"}
                for key, value in locator.items()
                if key.endswith("_at") and isinstance(value, str)
            ]
            if isinstance(locator, dict)
            else []
        )
        evidence_roles.append(
            {
                "evidence_id": evidence["evidence_id"],
                "resource_kind": (
                    resource_handle.split(":", 1)[0]
                    if isinstance(resource_handle, str)
                    else None
                ),
                "origin_type": evidence.get("origin_type"),
                "metadata_times": metadata_times,
            }
        )
    return {
        "decision_stage": "PRE_EXECUTION_PLAN_REVIEW",
        "request_reference_time": reference,
        "evidence_roles": evidence_roles,
    }


def _variants(saved: dict[str, object]) -> list[dict[str, object]]:
    actual: dict[str, dict[str, object]] = {}
    rows: list[dict[str, object]] = []
    for case in cast(list[dict[str, Any]], saved["cases"]):
        captured = [
            detail
            for detail in case["work_analysis"]["downstream"]["inference_details"]
            if detail["prompt_id"] == PROMPT_ID
        ]
        if len(captured) != 1:
            raise ValueError("expected exactly one saved Review prompt input")
        actual[case["case_id"]] = captured[0]["prompt_input"]
        rows.append(
            {
                "label": case["case_id"],
                "origin": "ACTUAL_CONNECTED",
                "started_at_ms": case["reference_started_at_ms"],
                "prompt_input": deepcopy(captured[0]["prompt_input"]),
                "saved_baseline_output": captured[0]["structured_output"],
            }
        )
    if set(actual) != {"CASE-CORE-023", "CASE-CORE-028"}:
        raise ValueError("fixed actual comparison set has changed")
    original = actual["CASE-CORE-023"]
    reference_ms = next(
        cast(int, row["started_at_ms"])
        for row in rows
        if row["label"] == "CASE-CORE-023"
    )

    wrong_date = deepcopy(original)
    wrong_payload = wrong_date["planning_result"]["actions"][0]["arguments"]["payload"]
    wrong_payload["start"] = "2026-08-09T10:00:00+09:00"
    wrong_payload["end"] = "2026-08-09T10:30:00+09:00"
    rows.append(_synthetic("WRONG_ACTION_DATE", wrong_date, reference_ms))

    missing_mail = deepcopy(original)
    removed = {
        item["evidence_id"]
        for item in missing_mail["evidence"]
        if str(item.get("resource_handle", "")).startswith("gmail_thread:")
    }
    missing_mail["evidence"] = [
        item for item in missing_mail["evidence"] if item["evidence_id"] not in removed
    ]
    missing_mail["work_analysis"]["work_facts"] = [
        fact
        for fact in missing_mail["work_analysis"]["work_facts"]
        if not removed.intersection(fact["evidence_refs"])
    ]
    missing_mail["planning_result"]["actions"][0]["evidence_refs"] = [
        ref
        for ref in missing_mail["planning_result"]["actions"][0]["evidence_refs"]
        if ref not in removed
    ]
    rows.append(_synthetic("MISSING_EXTERNAL_MAIL", missing_mail, reference_ms))

    user_edit = deepcopy(original)
    edited_action = user_edit["planning_result"]["actions"][0]
    edited_title = "사용자가 수정한 점검 제목"
    edited_action["arguments"]["payload"]["title"] = edited_title
    user_edit["user_action_modifications"] = [
        {
            "action_id": edited_action["action_id"],
            "argument_overrides": {"payload.title": edited_title},
        }
    ]
    rows.append(_synthetic("USER_PREVIEW_EDIT", user_edit, reference_ms))

    forbidden_invite = deepcopy(original)
    forbidden_invite["request_intent"]["goal"] += " 참석자 초대는 하지 않는다."
    forbidden_invite["request_intent"]["completion_conditions"].append(
        "참석자 초대를 하지 않는다."
    )
    forbidden_invite["request_intent"]["constraints"].append(
        {
            "kind": "USER_REQUIREMENT",
            "field": "effect_prohibition",
            "value": "참석자 초대 금지",
        }
    )
    forbidden_invite["planning_result"]["actions"][0]["arguments"]["payload"][
        "attendees"
    ] = ["unrequested@example.com"]
    rows.append(_synthetic("FORBIDDEN_ATTENDEE", forbidden_invite, reference_ms))

    no_date = deepcopy(original)
    no_date["request_intent"]["goal"] = (
        "Kestrel 지연 메일과 대체 일정 작업을 참고해 후속 확인 작업을 만든다."
    )
    no_date["request_intent"]["completion_conditions"] = [
        "후속 확인 작업을 하나 만든다."
    ]
    no_date["request_intent"]["constraints"] = [
        item
        for item in no_date["request_intent"]["constraints"]
        if item["kind"] not in {"DATE", "TIME"}
        and item["field"] not in {"original_search_request", "due", "period"}
    ]
    no_date["request_intent"]["requested_resource_hints"] = [
        "GMAIL_THREAD",
        "TASK",
    ]
    no_date["request_intent"]["resource_responsibilities"]["outputs"] = [
        {"resource_type": "TASK", "effect": "CREATE"}
    ]
    task_action = no_date["planning_result"]["actions"][0]
    task_action["tool_id"] = "tasks_create_task"
    task_action["arguments"] = {
        "tasklist_id": "synthetic-tasklist",
        "payload": {
            "title": "Kestrel 지연 후속 확인",
            "notes": "지연 메일과 대체 일정 작업 상태를 확인한다.",
        },
    }
    rows.append(_synthetic("DATE_NOT_APPLICABLE", no_date, reference_ms))
    return rows


def _synthetic(
    label: str, prompt_input: dict[str, object], started_at_ms: int
) -> dict[str, object]:
    return {
        "label": label,
        "origin": "SYNTHETIC_REVIEW_INPUT",
        "started_at_ms": started_at_ms,
        "prompt_input": prompt_input,
    }


def evaluate(source_path: Path, output_path: Path) -> dict[str, object]:
    saved = json.loads(source_path.read_text(encoding="utf-8"))
    if saved["binding"]["model_id"] != MODEL_ID:
        raise ValueError("saved model differs from fixed comparison model")
    models = {item.model_id: item.digest for item in OllamaHTTPClient().list_installed_models()}
    if models.get(MODEL_ID) != saved["binding"]["model_digest"]:
        raise ValueError("installed model digest differs from saved actual inputs")
    cases = _variants(saved)
    runtime_root = Path(tempfile.mkdtemp(prefix="gwa-review-roles-"))
    manifest_path = _candidate_manifest(
        runtime_root, optional_field="review_semantic_context"
    )
    config = ProductionRuntimeConfig.development(
        runtime_root=runtime_root,
        working_directory=Path(__file__).resolve().parents[1],
        mcp_manifest_version="2026-08-07.p0",
        keyring_store=SessionMemorySecretStore(),
        prompt_manifest_path=manifest_path,
        sampling_temperature=0.0,
        sampling_seed=1729,
    )
    container = build_production_runtime(
        **{item.name: getattr(config, item.name) for item in fields(config)},
        bootstrap_secret=uuid4().hex,
        service_instance_id=f"review-roles-{uuid4()}",
    )
    runtime = container.structured_inference_port
    settings = container.update_settings_handler
    if runtime is None or settings is None:
        raise RuntimeError("local inference runtime is unavailable")
    runtime.run_context_provider = lambda: None
    settings(
        UpdateSettingsCommand(
            str(uuid4()),
            SettingsPatchV1(
                schema_version=1,
                preferred_local_model_id=MODEL_ID,
                preferred_llm_mode="LOCAL_GPU",
                external_llm_consent=False,
            ),
        )
    )
    reference = load_prompt_reference(
        PROMPT_ID, manifest_path, execution_scope=DEVELOPMENT_SMOKE
    )
    schema = review_inspector_output_schema(PROMPT_ID)
    result: dict[str, object] = {
        "binding": {
            "source_path": str(source_path),
            "source_sha256": hashlib.sha256(source_path.read_bytes()).hexdigest(),
            "baseline_sha": "2523f699",
            "model_id": MODEL_ID,
            "model_digest": models[MODEL_ID],
            "sampling_temperature": 0.0,
            "sampling_seed": 1729,
            "prompt_content_hash": reference.content_hash,
            "new_call_limit": 12,
            "provider_read_enabled": False,
            "provider_write_enabled": False,
        },
        "cases": [],
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    dispatch_count = 0
    before_dispatch = runtime.before_provider_dispatch

    def count_dispatch() -> None:
        nonlocal dispatch_count
        before_dispatch()
        dispatch_count += 1

    runtime.before_provider_dispatch = count_dispatch
    for case in cases:
        started_at_ms = cast(int, case["started_at_ms"])
        original = cast(dict[str, object], case["prompt_input"])
        if "review_semantic_context" in original:
            raise ValueError("frozen baseline already contains candidate input")
        candidate = {
            **original,
            "review_semantic_context": _semantic_roles(original, started_at_ms),
        }
        row: dict[str, object] = {
            "label": case["label"],
            "origin": case["origin"],
            "started_at_ms": started_at_ms,
            "baseline_input_sha256": _digest(original),
            "candidate_input_sha256": _digest(candidate),
            "baseline_input": original,
            "candidate_input": candidate,
            "trials": [],
        }
        if "saved_baseline_output" in case:
            cast(list[dict[str, object]], row["trials"]).append(
                {
                    "arm": "A",
                    "source": "SAVED_012_FIRST_STRUCTURED_OUTPUT",
                    "outcome": "COMPLETED",
                    "structured_output": case["saved_baseline_output"],
                }
            )
        cast(list[dict[str, object]], result["cases"]).append(row)
        arms = (
            [("B", candidate)]
            if "saved_baseline_output" in case
            else [("A", original), ("B", candidate)]
        )
        for arm, input_value in arms:
            started = time.perf_counter()
            dispatches_before = dispatch_count
            trial: dict[str, object] = {"arm": arm, "source": "NEW_LOCAL_INFERENCE"}
            try:
                with (
                    provider_dispatch_execution_scope(
                        run_id=f"review-roles-{case['label']}-{arm}",
                        now_ms=lambda started_at_ms=started_at_ms, started=started: (
                            started_at_ms + int((time.perf_counter() - started) * 1_000)
                        ),
                    ),
                    provider_dispatch_budget_scope(
                        build_default_run_budget(started_at_ms=started_at_ms)
                    ),
                ):
                    inference = runtime.infer("LOCAL_GPU", reference, input_value, schema)
                validated = validate_review_inspector_result(
                    inference.structured_output, expected_dimension=PROMPT_ID
                )
                trial.update(
                    {
                        "outcome": "COMPLETED",
                        "structured_output": validated,
                        "input_tokens": inference.input_tokens,
                        "output_tokens": inference.output_tokens,
                        "provider_latency_ms": inference.latency_ms,
                    }
                )
            except Exception as error:
                code = getattr(error, "code", None)
                trial.update(
                    {
                        "outcome": "FAILED",
                        "error_type": type(error).__name__,
                        "error_code": getattr(code, "value", None),
                    }
                )
            trial["dispatch_count"] = dispatch_count - dispatches_before
            trial["duration_ms"] = int((time.perf_counter() - started) * 1_000)
            cast(list[dict[str, object]], row["trials"]).append(trial)
            print(case["label"], arm, trial["outcome"], trial["duration_ms"], flush=True)
            output_path.write_text(
                json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
            )
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    evaluate(args.input, args.output)


if __name__ == "__main__":
    main()
