"""Sealed Review owner diagnostic: one historical input + three synthetic controls.

Eight new FIRST calls, no Graph/repair/Provider/approval. This invokes the semantic
inspector directly, including controls its deterministic CREATE shortcut might
otherwise satisfy. Neither structural validity nor a fake control is a score.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import time
from copy import deepcopy
from dataclasses import asdict, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast
from unittest.mock import patch

from evaluation.dataset_v8 import DEFAULT_DATASET_PATH, DEFAULT_PROVIDER_FIXTURE_PATH, load_cases
from scripts import evaluate_output_format_ablation as existing
from scripts import review_request_reconsideration_candidate as candidate
from scripts.evaluate_effect_prohibition_sampler import head, write_json
from scripts.ru_observation import metrics, object_hash

from google_work_agent.application.agents.request_understanding.contracts.request_goal_candidate_schema import (  # noqa: E501
    derive_source_information_constraints,
)
from google_work_agent.application.agents.request_understanding.validate_intent import (
    validate_intent,
)
from google_work_agent.application.agents.review.contracts.review_findings import (
    review_inspector_output_schema,
    validate_review_inspector_result,
)
from google_work_agent.application.prompt_runtime.assemble_prompt import assemble_prompt
from google_work_agent.application.prompt_runtime.prompt_registry import EVALUATION, PromptRegistry
from google_work_agent.ports.llm.output_schema_validation import validate_output_schema

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "evaluation/results"
ORIGIN = RESULTS / "064-core005-main-graph-t2"
ORIGIN_HASHES = {
    "calls.json": "3de5802516e87fcb89393b705b56edf496f356bde1d22b875d250c5e194714f1",
    "raw.json": "e369f9e52489089c7ae8e27be49016a9b3f94b5443f8ec8517666c248d8642f9",
}
SUFFIX = ROOT / "evaluation/prompt_candidates/review-request-owner-v1/instruction-suffix.md"
CRITERIA = ROOT / "evaluation/experiments/065-review-request-reconsideration-criteria.md"
ARMS = ("production", "request_owner")
MAX_CALLS = 8
PROMPT_ID = candidate.DIMENSION


def _read(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("diagnostic artifact must be an object")
    return cast(dict[str, Any], value)


def _context(projection: dict[str, Any], user_request: str) -> dict[str, Any]:
    actions = projection["planning_result"]["actions"]
    meta = projection["planning_result"]["meta"]
    return {
        "current_intent": projection["request_intent"],
        "user_request": user_request,
        "current_plan_ref": {"artifact_id": meta["artifact_id"], "revision": meta["revision"]},
        "known_action_ids": [a["action_id"] for a in actions],
        "known_route_ids": list(dict.fromkeys(a["route_id"] for a in actions)),
        "known_evidence_ids": [e["evidence_id"] for e in projection["evidence"]],
        "pre_publication": True,
    }


def build_payloads(
    projection: dict[str, Any],
    user_request: str,
    runtime: dict[str, Any],
) -> dict[str, Any]:
    """Use Product assembly/transport unchanged, then an explicit evaluation frame."""
    registry = PromptRegistry()
    ref = registry.lookup_for_evaluation(PROMPT_ID)
    schema = review_inspector_output_schema(PROMPT_ID)
    system = assemble_prompt(ref, projection, registry=registry, execution_scope=EVALUATION)
    captured: list[dict[str, Any]] = []

    def capture(**kwargs: Any) -> dict[str, str]:
        captured.append(deepcopy(kwargs))
        return {"response": "{}"}

    with patch.object(existing.transport, "_post_json", capture):
        existing.transport.OllamaHTTPClient().invoke_structured(
            endpoint=existing.OLLAMA_FIXED_LOOPBACK_ENDPOINT,
            model_id=runtime["model"],
            prompt_ref=ref,
            prompt_input=projection,
            output_schema=schema,
            timeout_seconds=existing.TIMEOUT_SECONDS,
            instruction_text=system,
            sampling_temperature=runtime["temperature"],
            sampling_seed=runtime["seed"],
        )
    if len(captured) != 1 or captured[0]["path"] != "/api/generate":
        raise ValueError("one Product generate payload required")
    base = captured[0]["payload"]
    if base["think"] is not False or base["stream"] is not False:
        raise ValueError("bounded nonthinking, nonstreaming Review required")
    role = registry.source_text(PROMPT_ID).rstrip()
    original_json = json.dumps(
        projection, ensure_ascii=False, separators=(",", ":"), sort_keys=True
    )
    original_suffix = original_json + "\n"
    if not system.startswith(role + "\n\n") or not system.endswith(original_suffix):
        raise ValueError("Product FIRST assembly frame changed")
    new_role = role + "\n\n" + SUFFIX.read_text(encoding="utf-8").rstrip()
    new_input = {**deepcopy(projection), "user_request": user_request}
    work_ids = [u["unit_id"] for u in projection["request_intent"]["requested_work"]["work_units"]]
    new_schema = candidate.build_review_output_schema(work_ids)
    new_ref = replace(
        ref,
        prompt_version="evaluation-review-request-owner-v1",
        content_hash=hashlib.sha256(new_role.encode("utf-8")).hexdigest(),
        input_schema_version="evaluation-review-request-owner-v1",
        output_schema_version=new_schema.schema_version,
    )
    frame = system[len(role) : -len(original_suffix)]
    wire = deepcopy(base)
    body = json.loads(base["prompt"])
    body.update(
        input=new_input,
        output_schema=new_schema.json_schema,
        prompt_ref={k: asdict(new_ref)[k] for k in ("prompt_id", "prompt_version", "content_hash")},
    )
    wire["system"] = (
        new_role
        + frame
        + json.dumps(
            new_input,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        + "\n"
    )
    wire["prompt"] = json.dumps(body, ensure_ascii=False, sort_keys=True)
    wire["format"] = deepcopy(new_schema.json_schema)
    # Empty findings test context/closed references only; it is not a semantic verdict.
    candidate.validate_review_candidate(
        {"schema_version": 1, "dimension": PROMPT_ID, "findings": []},
        **_context(projection, user_request),
    )
    return {
        "payloads": {"production": base, "request_owner": wire},
        "prompt_refs": {"production": asdict(ref), "request_owner": asdict(new_ref)},
    }


def synthetic_controls() -> list[dict[str, Any]]:
    """Fully specified, local synthetic artifacts; IDs are not Provider resources."""
    controls = []
    for key, title, update in (
        ("SYNTHETIC-TASK-CREATE", "검수 메모", False),
        ("SYNTHETIC-PLANNING-TITLE", "무관한 메모", False),
        ("SYNTHETIC-MISSING-TARGET", "검수 완료", True),
    ):
        text = (
            '선택한 작업의 제목을 "검수 완료"로 바꿔줘.'
            if update
            else '"검수 메모"라는 작업을 만들어줘.'
        )
        expected_title = "검수 완료" if update else "검수 메모"
        constraints: list[dict[str, Any]] = [
            {
                "kind": "USER_REQUIREMENT",
                "field": "title",
                "value": expected_title,
                "work_unit_ids": ["work-1"],
                "provenance": {
                    "source": "USER_REQUEST",
                    "start_offset": text.index(expected_title),
                    "end_offset": text.index(expected_title) + len(expected_title),
                },
            }
        ]
        if update:
            constraints.append(
                {
                    "kind": "RESOURCE",
                    "field": "selected_resource_id",
                    "value": ["synthetic-task"],
                    "work_unit_ids": ["work-1"],
                }
            )
        intent: dict[str, Any] = {
            "schema_version": 3,
            "goal": text,
            "completion_conditions": [text],
            "constraints": constraints,
            "requested_effect_hints": ["READ", "UPDATE"] if update else ["CREATE"],
            "requested_resource_hints": ["TASK"],
            "analysis_requirement": "NONE",
            "effect_prohibitions": [],
            "requested_work": {
                "work_units": [
                    {
                        "unit_id": "work-1",
                        "request_provenance": [
                            {
                                "source": "USER_REQUEST",
                                "start_offset": 0,
                                "end_offset": len(text),
                                "source_text": text,
                            }
                        ],
                    }
                ],
                "work_relations": [],
            },
            "ambiguity": {"requires_confirmation": False, "reason_codes": [], "missing_fields": []},
            "resource_responsibilities": {
                "source_reads": [
                    {
                        "resource_type": "TASK",
                        "required_information": ["title"],
                        "target_scope": "SINGULAR",
                        "work_unit_ids": ["work-1"],
                    }
                ]
                if update
                else [],
                "outputs": [
                    {
                        "resource_type": "TASK",
                        "effect": "UPDATE" if update else "CREATE",
                        "work_unit_ids": ["work-1"],
                    }
                ],
            },
            "meta": {"artifact_id": "synthetic-intent", "revision": 1, "based_on": []},
        }
        constraints.extend(
            dict(item)
            for item in derive_source_information_constraints(intent["resource_responsibilities"])
        )
        validate_intent(intent, require_meta=True, provenance_sources={"USER_REQUEST": text})
        arguments: dict[str, Any] = {
            "task_list_id": "synthetic-task-list",
            "payload": {"title": title},
        }
        if update:
            arguments["task_id"] = "synthetic-task"
        projection = {
            "request_intent": intent,
            "planning_result": {
                "schema_version": 2,
                "meta": {
                    "artifact_id": "synthetic-plan",
                    "revision": 1,
                    "based_on": [{"artifact_id": "synthetic-intent", "revision": 1}],
                },
                "actions": [
                    {
                        "action_id": "synthetic-action",
                        "route_id": "synthetic-route",
                        "tool_id": "tasks_update_task" if update else "tasks_create_task",
                        "effect": "UPDATE" if update else "CREATE",
                        "arguments": arguments,
                        "evidence_refs": ["synthetic-user-message"],
                        "depends_on_action_ids": [],
                    }
                ],
            },
            "evidence": [
                {
                    "schema_version": 1,
                    "evidence_id": "synthetic-user-message",
                    "origin_type": "USER_MESSAGE",
                    "message_id": "synthetic-user-message",
                    "kind": "USER_REQUEST",
                    "excerpt": text,
                }
            ],
        }
        controls.append(
            {
                "case_id": key,
                "group": "synthetic",
                "input": projection,
                "user_request": text,
                "input_construction": "Local synthetic artifacts; no real account/resource. "
                + (
                    "Selected Task UPDATE has no target snapshot or external Evidence."
                    if update
                    else "CREATE controls share Intent/USER_MESSAGE; only Plan title differs."
                ),
            }
        )
    return controls


def make_plan(model: dict[str, Any], *, origin: Path = ORIGIN) -> dict[str, Any]:
    for name, expected in ORIGIN_HASHES.items():
        if existing.file_hash(origin / name) != expected:
            raise ValueError("historical original file hash changed")
    history = _read(origin / "raw.json")["plan"]
    case = load_cases()["CASE-CORE-005"].raw
    if any(
        (
            history["dataset_sha256"] != existing.file_hash(DEFAULT_DATASET_PATH),
            history["snapshot_sha256"] != existing.file_hash(DEFAULT_PROVIDER_FIXTURE_PATH),
            history["case_sha256"] != object_hash(case),
            model["model_id"] != history["model"]["id"],
            model["model_digest"] != history["model"]["digest"],
        )
    ):
        raise ValueError("Canonical/model binding differs from historical Core input")
    calls = [c for c in _read(origin / "calls.json")["calls"] if c["prompt_id"] == PROMPT_ID]
    if len(calls) != 1:
        raise ValueError("exactly one original Review FIRST required")
    call = calls[0]
    if (
        call["state"] != "RETURNED"
        or call["wire_request_count"] != 1
        or call["wire_path"] != "/api/generate"
        or "base_projection" in call["input"]
        or call["input_sha256"] != object_hash(call["input"])
        or call["runtime_policy"]["local_timeout_seconds"] != existing.TIMEOUT_SECONDS
        or call["temperature"] is not None
        or call["seed"] != 20260923
    ):
        raise ValueError("original Review FIRST/runtime binding changed")
    text = case["canonical_user_prompt"]
    original_user = [
        e["excerpt"] for e in call["input"]["evidence"] if e.get("origin_type") == "USER_MESSAGE"
    ]
    if original_user != [text]:
        raise ValueError("current Canonical request differs from original Run USER_MESSAGE")
    runtime = {"model": call["model"], "temperature": call["temperature"], "seed": call["seed"]}
    cases = [
        {
            "case_id": "CASE-CORE-005",
            "group": "core",
            "input": deepcopy(call["input"]),
            "user_request": text,
            "case_sha256": object_hash(case),
            "input_construction": "Original T2 Review FIRST projection unchanged; no score reused.",
            "origin_call_index": call["call_index"],
            "origin_row_sha256": object_hash(call),
        },
        *synthetic_controls(),
    ]
    for entry in cases:
        entry.update(build_payloads(entry["input"], entry["user_request"], runtime))
        entry["input_sha256"] = object_hash(entry["input"])
        entry["wire_hashes"] = {a: object_hash(p) for a, p in entry["payloads"].items()}
    first = cases[0]
    if (
        first["prompt_refs"]["production"] != call["prompt_ref"]
        or first["wire_hashes"]["production"] != call["wire_sha256"]
        or first["payloads"]["production"]["options"] != call["wire_options"]
        or first["payloads"]["production"]["format"] != call["output_schema"]
    ):
        raise ValueError("current Product Review wire differs from original FIRST")
    dependencies = [
        Path(__file__),
        ROOT / "scripts/review_request_reconsideration_candidate.py",
        ROOT / "scripts/evaluate_output_format_ablation.py",
        ROOT / "scripts/evaluate_effect_prohibition_sampler.py",
        ROOT / "scripts/ru_observation.py",
        ROOT / "evaluation/dataset_v8.py",
        ROOT / "tests/evaluation/test_evaluate_review_request_owner.py",
        SUFFIX,
        CRITERIA,
    ]
    # Includes every Product producer/validator/Prompt dependency without importing a runtime.
    dependencies += [
        p
        for p in (ROOT / "src").rglob("*")
        if p.is_file()
        and p.suffix in {".py", ".json", ".md", ".sql"}
        and "__pycache__" not in p.parts
    ]
    return {
        "schema_version": 1,
        "kind": "REVIEW_REQUEST_OWNER_DIAGNOSTIC",
        "head_sha": head(),
        "model": model,
        "runtime": runtime,
        "origin": origin.resolve().as_posix(),
        "origin_hashes": dict(ORIGIN_HASHES),
        "dataset_sha256": history["dataset_sha256"],
        "fixture_sha256": history["snapshot_sha256"],
        "cases": cases,
        "source_hashes": {
            p.relative_to(ROOT).as_posix(): existing.file_hash(p) for p in sorted(set(dependencies))
        },
        "execution_order": [[c["case_id"], arm] for c in cases for arm in ARMS],
        "policy": {
            "max_http_generation_calls": MAX_CALLS,
            "trials_per_case_arm": 1,
            "concurrency": 1,
            "timeout_seconds": existing.TIMEOUT_SECONDS,
            "repairs": 0,
            "retries": 0,
            "reused_scores": 0,
            "provider_calls": 0,
            "graph_calls": 0,
            "approval_resumes": 0,
        },
        "semantic_verdict": "UNREVIEWED",
        "business_success": "NOT_EVALUATED",
    }


def validate_response(content: object, case: dict[str, Any], arm: str) -> dict[str, Any]:
    result: dict[str, Any] = {"semantic_verdict": "UNREVIEWED"}
    try:
        value = json.loads(content) if isinstance(content, str) else None
        if not isinstance(value, dict):
            raise ValueError("one strict JSON object required")
    except (ValueError, TypeError) as error:
        return {**result, "strict_json": "INVALID", "error": str(error)[:500]}
    result.update(strict_json="VALID", parsed=value)
    errors = list(validate_output_schema(value, case["payloads"][arm]["format"]))
    result["wire_schema"] = "INVALID" if errors else "VALID"
    result["wire_schema_errors"] = errors
    try:
        validate_review_inspector_result(value, expected_dimension=PROMPT_ID)
        result["product_shape"] = "VALID"
    except ValueError as error:
        result.update(product_shape="INVALID", product_shape_error=str(error)[:500])
    try:
        receipts = candidate.validate_review_candidate(
            value, **_context(case["input"], case["user_request"])
        )
        result.update(closed_context="VALID", validated_findings=[r.finding for r in receipts])
        # A wider diagnostic must never admit a finding rejected by its actual
        # wire contract. The projection is hypothetical and candidate-only.
        result["candidate_projections"] = [
            projection
            for receipt in receipts
            if arm == "request_owner" and not errors
            if (
                projection := candidate.build_request_reconsideration_projection(
                    receipt,
                    case["input"]["request_intent"],
                    case["user_request"],
                    _context(case["input"], case["user_request"])["current_plan_ref"],
                    pre_publication=True,
                )
            )
            is not None
        ]
    except ValueError as error:
        result.update(closed_context="INVALID", closed_context_error=str(error)[:500])
    return result


def _output_path(output: Path) -> Path:
    output = output.resolve()
    if output == RESULTS.resolve() or not output.is_relative_to(RESULTS.resolve()):
        raise ValueError("dedicated evaluation/results directory required")
    return output


def execute_plan(plan: dict[str, Any], output: Path, *, plan_sha256: str) -> dict[str, Any]:
    if object_hash(plan) != plan_sha256:
        raise ValueError("sealed plan hash mismatch")
    if (
        make_plan(existing.inspect_diagnostic_model("presence_zero"), origin=Path(plan["origin"]))
        != plan
    ):
        raise ValueError("HEAD/model/code/Prompt/runtime/input/fixture drift")
    output = _output_path(output)
    if output.exists() and any(p.name != "preregistered-plan.json" for p in output.iterdir()):
        raise ValueError("prior partial/failed trial must remain untouched")
    write_json(
        RESULTS / ".review-owner-trials" / f"{plan_sha256}.json",
        {"output": output.as_posix()},
        exclusive=True,
    )
    raw: dict[str, Any] = {
        "binding": plan,
        "calls": [],
        "completed": False,
        "semantic_verdict": "UNREVIEWED",
        "business_success": "NOT_EVALUATED",
        "provider_calls": 0,
        "graph_calls": 0,
    }
    path = output / "raw.json"
    write_json(path, raw, exclusive=True)
    for case_id, arm in plan["execution_order"]:
        if len(raw["calls"]) >= MAX_CALLS:
            raise ValueError("fixed diagnostic call cap reached")
        case = next(c for c in plan["cases"] if c["case_id"] == case_id)
        payload = deepcopy(case["payloads"][arm])
        row = {
            "case_id": case_id,
            "group": case["group"],
            "arm": arm,
            "state": "DISPATCH_STARTED",
            "stage": "FIRST",
            "wire_request_count": 1,
            "payload": payload,
            "wire_sha256": object_hash(payload),
            "input_sha256": object_hash(json.loads(payload["prompt"])["input"]),
            "schema_sha256": object_hash(payload["format"]),
            "prompt_ref": deepcopy(case["prompt_refs"][arm]),
            "runtime": deepcopy(plan["runtime"]),
            "dispatch_started_at_utc": datetime.now(UTC).isoformat(timespec="milliseconds"),
            "semantic_verdict": "UNREVIEWED",
        }
        raw["calls"].append(row)
        write_json(path, raw)
        started = time.monotonic()
        try:
            response = existing.transport._post_json(
                endpoint=existing.OLLAMA_FIXED_LOOPBACK_ENDPOINT,
                path="/api/generate",
                payload=payload,
                timeout_seconds=existing.TIMEOUT_SECONDS,
            )
            row.update(
                state="RETURNED",
                content=response.get("response"),
                model=response.get("model"),
                done=response.get("done"),
                done_reason=response.get("done_reason"),
                input_tokens=response.get("prompt_eval_count"),
                output_tokens=response.get("eval_count"),
            )
            for source, key in (
                ("total_duration", "latency_ms"),
                ("load_duration", "load_duration_ms"),
                ("prompt_eval_duration", "prompt_eval_duration_ms"),
                ("eval_duration", "eval_duration_ms"),
            ):
                duration = response.get(source)
                row[key] = duration // 1_000_000 if type(duration) is int else None
            write_json(path, raw)  # First content survives even if validation raises.
            row["validation"] = validate_response(row["content"], case, arm)
        except Exception as error:
            row.update(state="ERROR", error_type=type(error).__name__, error=str(error)[:500])
        finally:
            row["wall_latency_ms"] = int((time.monotonic() - started) * 1000)
            write_json(path, raw)
    raw.update(
        completed=True,
        actual_http_calls=len(raw["calls"]),
        metrics_by_group={
            group: {
                arm: metrics([r for r in raw["calls"] if r["group"] == group and r["arm"] == arm])
                for arm in ARMS
            }
            for group in ("core", "synthetic")
        },
    )
    write_json(path, raw)
    return raw


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--result-dir", type=Path, required=True)
    parser.add_argument("--execute-plan", type=Path)
    parser.add_argument("--expected-plan-sha256")
    args = parser.parse_args()
    if args.execute_plan:
        if not args.expected_plan_sha256:
            raise ValueError("sealed plan hash required")
        result = execute_plan(
            _read(args.execute_plan), args.result_dir, plan_sha256=args.expected_plan_sha256
        )
        print(
            json.dumps(
                {"actual_http_calls": result["actual_http_calls"], "semantic_verdict": "UNREVIEWED"}
            )
        )
        return
    output = _output_path(args.result_dir)
    plan = make_plan(existing.inspect_diagnostic_model("presence_zero"))
    path = output / "preregistered-plan.json"
    write_json(path, plan, exclusive=True)
    print(json.dumps({"plan": str(path), "sha256": object_hash(plan), "model_calls": 0}))


if __name__ == "__main__":
    main()
