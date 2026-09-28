"""V44: one-call Source examples-only diagnostic over seven hash-bound FIRST inputs."""

from __future__ import annotations

import argparse
import json
import time
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from scripts import evaluate_source_membership_boundary as previous
from scripts import ru_source_contrast_candidate as candidate
from scripts.evaluate_effect_prohibition_sampler import head, write_json
from scripts.ru_observation import metrics, object_hash

existing = previous.existing
ROOT = previous.ROOT
RESULTS = previous.RESULTS
CONTROL_BASELINE = RESULTS / "064-source-membership-v43-t1/raw.json"
CONTROL_BASELINE_SHA256 = "b5a6419ec305e213d01d377b6b91eb04310752af923a380de3037fdb442897ac"
CRITERIA = ROOT / "evaluation/experiments/064-source-contrast-v44-criteria.md"
MAX_CALLS = 7


def make_plan(
    model: dict[str, Any],
    *,
    baseline_path: Path = previous.BASELINE,
    control_baseline_path: Path = CONTROL_BASELINE,
) -> dict[str, Any]:
    # Reuse the checked Product assembly/admission, not the v43 two-call candidate.
    prior = previous.make_plan(model, baseline_path=baseline_path)
    control_raw = previous._read(control_baseline_path)
    if (
        existing.file_hash(control_baseline_path) != CONTROL_BASELINE_SHA256
        or control_raw.get("completed") is not True
        or control_raw.get("actual_http_calls") != 15
        or control_raw["binding"]["model"] != model
    ):
        raise ValueError("complete, hash-bound v43 control baseline required")
    cases = []
    for old in prior["cases"]:
        case = deepcopy(old)
        case.pop("membership_payload")
        case.pop("membership_wire_sha256")
        if case["group"] == "synthetic":
            rows = [
                c
                for c in control_raw["calls"]
                if c["case_id"] == case["case_id"] and c["arm"] == "baseline"
            ]
            if len(rows) != 1:
                raise ValueError("exactly one original control baseline required")
            row = rows[0]
            payload = case["payload"]
            if (
                row["state"] != "RETURNED"
                or row["wire_request_count"] != 1
                or row["payload"] != payload
                or row["wire_sha256"] != object_hash(payload)
                or row["input_sha256"] != object_hash(case["source_call"]["input"])
                or existing.validate_response(row["content"], case) != row["validation"]
            ):
                raise ValueError("control baseline wire/input/validation drift")
            case["baseline"] = {
                **deepcopy(row),
                "new_call": False,
                "origin_path": control_baseline_path.resolve().as_posix(),
                "origin_raw_sha256": existing.file_hash(control_baseline_path),
                "origin_row_sha256": object_hash(row),
            }
        case["candidate_payload"] = candidate.build_payload(case["payload"])
        case["candidate_wire_sha256"] = object_hash(case["candidate_payload"])
        cases.append(case)
    if len(cases) != MAX_CALLS:
        raise ValueError("fixed Core5 + separate synthetic2 required")
    dependencies = set(prior["source_hashes"]) | {
        "scripts/evaluate_source_contrast_boundary.py",
        "scripts/ru_source_contrast_candidate.py",
        "tests/evaluation/test_evaluate_source_contrast_boundary.py",
        "tests/evaluation/test_ru_source_contrast_candidate.py",
        "evaluation/prompt_candidates/ru-source-contrast-v44/examples.json",
        CRITERIA.relative_to(ROOT).as_posix(),
    }
    return {
        "kind": "SOURCE_CONTRAST_V44",
        "schema_version": 1,
        "head_sha": head(),
        "model": model,
        "cases": cases,
        "baseline_path": baseline_path.resolve().as_posix(),
        "baseline_sha256": existing.file_hash(baseline_path),
        "control_baseline_path": control_baseline_path.resolve().as_posix(),
        "control_baseline_sha256": existing.file_hash(control_baseline_path),
        "dataset_sha256": prior["dataset_sha256"],
        "fixture_sha256": prior["fixture_sha256"],
        "source_hashes": {p: existing.file_hash(ROOT / p) for p in sorted(dependencies)},
        "execution_order": [c["case_id"] for c in cases],
        "policy": {
            "trials_per_case": 1,
            "max_http_generation_calls": MAX_CALLS,
            "reused_baseline_calls": MAX_CALLS,
            "concurrent_generation_calls": 1,
            "timeout_seconds_per_call": existing.TIMEOUT_SECONDS,
            "repairs": 0,
            "retries": 0,
            "codec_admission": 0,
            "rerun_to_pass": 0,
            "graph_calls": 0,
            "provider_calls": 0,
            "runtime_options": "EXACT_DEFAULT_BASELINE_OPTIONS",
        },
        "baseline_reuse_limit": "NONCONTEMPORANEOUS_LATENCY_NOT_CAUSAL",
        "semantic_verdict": "UNREVIEWED",
        "business_success": "NOT_EVALUATED",
    }


def execute_plan(plan: dict[str, Any], output: Path, *, plan_sha256: str) -> dict[str, Any]:
    if object_hash(plan) != plan_sha256:
        raise ValueError("sealed plan hash mismatch")
    if (
        make_plan(
            existing.inspect_diagnostic_model("presence_zero"),
            baseline_path=Path(plan["baseline_path"]),
            control_baseline_path=Path(plan["control_baseline_path"]),
        )
        != plan
    ):
        raise ValueError("HEAD/model/runtime/Prompt/input/Schema/baseline drift")
    output = output.resolve()
    if output == RESULTS.resolve() or not output.is_relative_to(RESULTS.resolve()):
        raise ValueError("dedicated evaluation/results directory required")
    if output.exists() and any(p.name != "preregistered-plan.json" for p in output.iterdir()):
        raise ValueError("prior partial/failed trial must remain untouched")
    write_json(
        RESULTS / ".source-contrast-trials" / f"{plan_sha256}.json",
        {"output": output.as_posix()},
        exclusive=True,
    )
    raw: dict[str, Any] = {
        "binding": plan,
        "calls": [],
        "completed": False,
        "reused_results": [deepcopy(c["baseline"]) for c in plan["cases"]],
        "semantic_verdict": "UNREVIEWED",
        "business_success": "NOT_EVALUATED",
        "provider_calls": 0,
    }
    path = output / "raw.json"
    write_json(path, raw, exclusive=True)
    for case in plan["cases"]:
        payload = case["candidate_payload"]
        row: dict[str, Any] = {
            "case_id": case["case_id"],
            "group": case["group"],
            "arm": "contrastive",
            "stage": "FIRST",
            "state": "DISPATCH_STARTED",
            "new_call": True,
            "wire_request_count": 1,
            "payload": deepcopy(payload),
            "wire_sha256": object_hash(payload),
            "input_sha256": object_hash(json.loads(payload["prompt"])["input"]),
            "dispatch_started_at_utc": datetime.now(UTC).isoformat(timespec="milliseconds"),
            "semantic_verdict": "UNREVIEWED",
            "business_success": "NOT_EVALUATED",
        }
        raw["calls"].append(row)
        write_json(path, raw)
        start = time.monotonic()
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
                value = response.get(source)
                row[key] = value // 1_000_000 if type(value) is int else None
            write_json(path, raw)
            row["validation"] = existing.validate_response(row["content"], case)
        except Exception as error:
            row.update(state="ERROR", error_type=type(error).__name__, error=str(error)[:500])
        finally:
            row["wall_latency_ms"] = int((time.monotonic() - start) * 1000)
            write_json(path, raw)
    raw.update(
        completed=True,
        actual_http_calls=len(raw["calls"]),
        reused_http_calls=len(raw["reused_results"]),
        metrics_by_group={
            group: {
                "baseline": metrics([c for c in raw["reused_results"] if c["group"] == group]),
                "contrastive": metrics([c for c in raw["calls"] if c["group"] == group]),
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
        raw = execute_plan(
            previous._read(args.execute_plan),
            args.result_dir,
            plan_sha256=args.expected_plan_sha256,
        )
        print(
            json.dumps(
                {"actual_http_calls": raw["actual_http_calls"], "semantic_verdict": "UNREVIEWED"}
            )
        )
        return
    output = args.result_dir.resolve()
    if output == RESULTS.resolve() or not output.is_relative_to(RESULTS.resolve()):
        raise ValueError("dedicated evaluation/results directory required")
    plan = make_plan(existing.inspect_diagnostic_model("presence_zero"))
    path = output / "preregistered-plan.json"
    write_json(path, plan, exclusive=True)
    print(json.dumps({"plan": str(path), "sha256": object_hash(plan), "model_calls": 0}))


if __name__ == "__main__":
    main()
