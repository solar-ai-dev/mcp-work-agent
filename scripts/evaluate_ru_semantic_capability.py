"""Five natural-language capability controls, not a Product candidate or workflow.

Historical Source FIRSTs are references, not a paired score or new executions.
Only exact request, selected identity and clock reach the unconstrained control.
"""

from __future__ import annotations

import argparse
import json
import time
from collections.abc import Callable
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from scripts import evaluate_source_catalog_projection as shared
from scripts.evaluate_effect_prohibition_sampler import head, write_json
from scripts.ru_observation import metrics, object_hash

existing = shared.existing
ROOT, RESULTS = shared.ROOT, shared.RESULTS
BASELINE, BASELINE_HASH = shared.BASELINE, shared.BASELINE_HASH
BASELINE_PLAN = RESULTS / "064-source-presence-v42-plan/preregistered-plan.json"
BASELINE_PLAN_HASH = "24ea7f3f7629190bacea15fa75ca572ca19b243c6bc338f23b10842f7f4fe3ec"
CASE_IDS = tuple(f"CASE-CORE-{number:03}" for number in (5, 9, 17, 49, 59))
INPUT_FIELDS = ("user_request", "selected_resource_refs", "run_reference_time")
CRITERIA = "evaluation/experiments/071-ru-semantic-capability-criteria.md"
SYSTEM = (
    "사용자 요청의 업무 의미를 해석한다. 요청한 최종 결과, 그 결과에 필요한 자료, "
    "명시된 조건을 간단한 한국어로 설명한다. "
    "실제 조회나 실행을 수행하거나 그 결과를 지어내지 않는다."
)


def build_payload(original: dict[str, Any], source_input: dict[str, Any]) -> dict[str, Any]:
    if (
        original.get("model") != "qwen3.5:9b"
        or original.get("think") is not False
        or original.get("stream") is not False
    ):
        raise ValueError("original fixed 9B non-thinking, non-streaming runtime required")
    if any(key not in source_input for key in INPUT_FIELDS) or not source_input["user_request"]:
        raise ValueError("exact request/selected refs/reference time required")
    payload = deepcopy(original)
    payload.pop("format", None)
    payload["system"] = SYSTEM
    payload["prompt"] = json.dumps(
        {key: source_input[key] for key in INPUT_FIELDS}, ensure_ascii=False
    )
    return payload


def make_plan(model: dict[str, Any]) -> dict[str, Any]:
    if (
        existing.file_hash(BASELINE) != BASELINE_HASH
        or existing.file_hash(BASELINE_PLAN) != BASELINE_PLAN_HASH
    ):
        raise ValueError("historical Source raw/plan bytes changed")
    raw, binding = shared.read_json(BASELINE), shared.read_json(BASELINE_PLAN)
    existing._validate_presence_version(model)
    if raw["binding"] != binding or raw.get("completed") is not True or model != binding["model"]:
        raise ValueError("complete original baseline and identical installed runtime required")
    if binding["dataset_sha256"] != existing.file_hash(existing.DEFAULT_DATASET_PATH) or binding[
        "fixture_sha256"
    ] != existing.file_hash(existing.DEFAULT_PROVIDER_FIXTURE_PATH):
        raise ValueError("Canonical Dataset/Fixture drift")
    canonical, cases = existing.load_cases(), []
    for case_id in CASE_IDS:
        sources = [c for c in binding["cases"] if c["case_id"] == case_id]
        rows = [
            r
            for r in raw["results"]
            if r["case_id"] == case_id and r["arm"] == "schema_constrained"
        ]
        if len(sources) != 1 or len(rows) != 1:
            raise ValueError("exactly one historical FIRST per fixed Core required")
        source, row = sources[0], rows[0]
        call = source["source_call"]
        payload = existing.reconstruct_payload(call)
        if (
            row["state"] != "RETURNED"
            or row["wire_request_count"] != 1
            or row["wire_sha256"] != object_hash(payload)
            or row["input_sha256"] != object_hash(call["input"])
            or row["wire_options"] != payload["options"]
            or row["wire_think"] != payload["think"]
            or row["prompt_ref"] != call["prompt_ref"]
            or row["model"] != model["model_id"]
            or payload["options"]["temperature"] != 0.05
            or "presence_penalty" in payload["options"]
            or source["case_binding"]["case_sha256"] != object_hash(canonical[case_id].raw)
            or canonical[case_id].raw["split"] != "CORE"
            or call["input"]["user_request"] != canonical[case_id].raw["canonical_user_prompt"]
            or existing.validate_response(row["content"], {**source, "owner": "source"})
            != row["validation"]
        ):
            raise ValueError("current Product wire/Case/admission differs from historical Source")
        candidate = build_payload(payload, call["input"])
        cases.append(
            {
                "case_id": case_id,
                "case_binding": deepcopy(source["case_binding"]),
                "source_call": deepcopy(call),
                "source_call_sha256": object_hash(call),
                "baseline_wire_sha256": object_hash(payload),
                "candidate_payload": candidate,
                "candidate_wire_sha256": object_hash(candidate),
                "candidate_input_sha256": object_hash(json.loads(candidate["prompt"])),
                "historical_source_result": {
                    **deepcopy(row),
                    "new_call": False,
                    "origin_row_sha256": object_hash(row),
                },
            }
        )
    paths = set(binding["source_hashes"]) | {
        p.relative_to(ROOT).as_posix() for p in (ROOT / "src").rglob("*.py")
    }
    paths.update(
        (
            "scripts/evaluate_ru_semantic_capability.py",
            "tests/evaluation/test_ru_semantic_capability.py",
            "scripts/evaluate_source_catalog_projection.py",
            CRITERIA,
        )
    )
    return {
        "kind": "RU_NATURAL_LANGUAGE_CAPABILITY_CONTROL_071",
        "head_sha": head(),
        "model": model,
        "cases": cases,
        "system": SYSTEM,
        "input_fields": list(INPUT_FIELDS),
        "baseline_path": BASELINE.as_posix(),
        "baseline_raw_sha256": BASELINE_HASH,
        "baseline_plan_path": BASELINE_PLAN.as_posix(),
        "baseline_plan_sha256": BASELINE_PLAN_HASH,
        "baseline_head": binding["head_sha"],
        "dataset_sha256": binding["dataset_sha256"],
        "fixture_sha256": binding["fixture_sha256"],
        "source_hashes": {p: existing.file_hash(ROOT / p) for p in sorted(paths)},
        "comparison_scope": "NL_CAPABILITY_NOT_PRODUCT_CANDIDATE_OR_SCHEMA_ONLY_ABLATION",
        "policy": {
            "new_calls": 5,
            "historical_reference_calls": 5,
            "trials": 1,
            "concurrency": 1,
            "timeout_seconds": 180,
            "retry": 0,
            "repair": 0,
            "provider_calls": 0,
            "graph_calls": 0,
        },
        "semantic_verdict": "NOT_REVIEWED",
        "business_success": "NOT_EVALUATED",
    }


def _output_directory(output: Path) -> Path:
    output = output.resolve()
    if output == RESULTS.resolve() or not output.is_relative_to(RESULTS.resolve()):
        raise ValueError("dedicated evaluation/results directory required")
    if output.exists() and any(output.iterdir()):
        raise FileExistsError("existing artifact directory cannot be overwritten")
    return output


def execute_plan(plan: dict[str, Any], output: Path, *, plan_sha256: str) -> dict[str, Any]:
    return execute_registered_plan(
        plan,
        output,
        plan_sha256=plan_sha256,
        reconstruct_plan=lambda: make_plan(existing.inspect_diagnostic_model("presence_zero")),
        claim_directory=".ru-capability-trials",
        reference_results=[deepcopy(c["historical_source_result"]) for c in plan["cases"]],
        reference_metric="source_historical_reference",
    )


def execute_registered_plan(
    plan: dict[str, Any],
    output: Path,
    *,
    plan_sha256: str,
    reconstruct_plan: Callable[[], dict[str, Any]],
    claim_directory: str,
    reference_results: list[dict[str, Any]],
    reference_metric: str,
) -> dict[str, Any]:
    """Shared FIRST recorder; each fixed diagnostic owns its full plan reconstruction."""
    if object_hash(plan) != plan_sha256:
        raise ValueError("plan hash mismatch")
    if reconstruct_plan() != plan:
        raise ValueError("HEAD/code/input/model/runtime drift")
    output = _output_directory(output)
    write_json(
        RESULTS / claim_directory / f"{plan_sha256}.json",
        {"output": output.as_posix()},
        exclusive=True,
    )
    raw: dict[str, Any] = {
        "binding": plan,
        "plan_sha256": plan_sha256,
        "calls": [],
        "not_dispatched": [],
        "completed": False,
        "historical_reference_results": deepcopy(reference_results),
        "provider_calls": 0,
        "graph_calls": 0,
        "semantic_verdict": "NOT_REVIEWED",
        "business_success": "NOT_EVALUATED",
    }
    path = output / "raw.json"
    write_json(path, raw, exclusive=True)
    try:
        for index, case in enumerate(plan["cases"]):
            payload = case["candidate_payload"]
            row: dict[str, Any] = {
                "case_id": case["case_id"],
                "stage": "FIRST",
                "state": "DISPATCH_STARTED",
                "payload": payload,
                "wire_sha256": object_hash(payload),
                "wire_request_count": 1,
                "input_sha256": case["candidate_input_sha256"],
                "semantic_verdict": "NOT_REVIEWED",
                "started_at_utc": datetime.now(UTC).isoformat(timespec="milliseconds"),
            }
            raw["calls"].append(row)
            write_json(path, raw)
            start = time.monotonic()
            try:
                response = existing.transport._post_json(
                    endpoint=existing.OLLAMA_FIXED_LOOPBACK_ENDPOINT,
                    path="/api/generate",
                    payload=payload,
                    timeout_seconds=180,
                )
                row.update(
                    state="RETURNED",
                    content=response.get("response"),
                    model=response.get("model"),
                    done=response.get("done"),
                    done_reason=response.get("done_reason"),
                    input_tokens=response.get("prompt_eval_count"),
                    output_tokens=response.get("eval_count"),
                    thinking_present=bool(response.get("thinking")),
                )
                for field, target in (
                    ("total_duration", "latency_ms"),
                    ("load_duration", "load_duration_ms"),
                    ("prompt_eval_duration", "prompt_eval_duration_ms"),
                    ("eval_duration", "eval_duration_ms"),
                ):
                    value = response.get(field)
                    row[target] = value // 1_000_000 if type(value) is int else None
                row["validation"] = (
                    "NONEMPTY_TEXT"
                    if isinstance(row["content"], str) and row["content"].strip()
                    else "INVALID_EMPTY_CONTENT"
                )
                if row["model"] != plan["model"]["model_id"] or row["done"] is not True:
                    raise ValueError("response model/completion differs from registered FIRST")
            except BaseException as error:
                row.update(state="ERROR", error_type=type(error).__name__, error=str(error)[:500])
                raw["circuit_break"] = {
                    "case_id": case["case_id"],
                    "error_type": type(error).__name__,
                }
                raw["not_dispatched"] = [
                    {
                        "case_id": remaining["case_id"],
                        "state": "NOT_DISPATCHED",
                        "reason": "PREVIOUS_DISPATCH_NOT_SAFELY_COMPLETED",
                        "wire_request_count": 0,
                    }
                    for remaining in plan["cases"][index + 1 :]
                ]
                if not isinstance(error, Exception):
                    raise
                break
            finally:
                row["wall_latency_ms"] = int((time.monotonic() - start) * 1000)
                write_json(path, raw)
        else:
            raw["completed"] = True
    finally:
        raw["actual_http_calls"] = len(raw["calls"])
        raw["metrics"] = {
            "control_new": metrics(raw["calls"]),
            reference_metric: metrics(raw["historical_reference_results"]),
        }
        try:
            raw["binding_unchanged"] = reconstruct_plan() == plan
        except Exception as error:
            raw.update(binding_unchanged=False, end_binding_error=str(error)[:500])
        raw["diagnostic_status"] = (
            "RECORDED"
            if raw["completed"]
            and raw["binding_unchanged"]
            and all(
                c["state"] == "RETURNED" and c.get("validation") == "NONEMPTY_TEXT"
                for c in raw["calls"]
            )
            else "FAILED"
        )
        write_json(path, raw)
    return raw


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--prepare", action="store_true")
    mode.add_argument("--execute-plan", type=Path)
    parser.add_argument("--result-dir", type=Path, required=True)
    parser.add_argument("--plan-sha256")
    args = parser.parse_args()
    if args.prepare:
        output = _output_directory(args.result_dir)
        plan = make_plan(existing.inspect_diagnostic_model("presence_zero"))
        path = output / "preregistered-plan.json"
        write_json(path, plan, exclusive=True)
        print(json.dumps({"plan": str(path), "sha256": object_hash(plan), "generation_calls": 0}))
    else:
        if not args.plan_sha256:
            parser.error("--execute-plan requires --plan-sha256")
        raw = execute_plan(
            shared.read_json(args.execute_plan), args.result_dir, plan_sha256=args.plan_sha256
        )
        print(
            json.dumps(
                {
                    key: raw[key]
                    for key in ("diagnostic_status", "actual_http_calls", "semantic_verdict")
                }
            )
        )
        raise SystemExit(0 if raw["diagnostic_status"] == "RECORDED" else 1)


if __name__ == "__main__":
    main()
