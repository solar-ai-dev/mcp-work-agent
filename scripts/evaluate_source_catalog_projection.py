"""Sealed three-FIRST Source catalog projection diagnostic, not Product evaluation."""

from __future__ import annotations

import argparse
import json
import time
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

from scripts import evaluate_output_format_ablation as existing
from scripts import ru_source_catalog_projection_candidate as candidate
from scripts.evaluate_effect_prohibition_sampler import head, write_json
from scripts.ru_observation import metrics, object_hash

ROOT = existing.ROOT
RESULTS = existing.RESULTS
BASELINE = RESULTS / "064-source-presence-v42-t1/raw.json"
BASELINE_HASH = "f5b40bd0d4e36e0f7d9138d00d9d0bdd45cbebc5cd954a110ced1d3a50c6ee52"
CASE_IDS = ("CASE-CORE-009", "CASE-CORE-049", "CASE-CORE-059")
CRITERIA = "evaluation/experiments/066-source-catalog-projection-v45.md"


def read_json(path: Path) -> dict[str, Any]:
    return cast(dict[str, Any], json.loads(path.read_text(encoding="utf-8")))


def make_plan(model: dict[str, Any]) -> dict[str, Any]:
    if existing.file_hash(BASELINE) != BASELINE_HASH:
        raise ValueError("original v42 baseline bytes changed")
    raw = read_json(BASELINE)
    binding = raw["binding"]
    existing._validate_presence_version(model)
    if model != binding["model"] or raw.get("completed") is not True:
        raise ValueError("complete baseline and matching installed runtime required")
    if binding["dataset_sha256"] != existing.file_hash(existing.DEFAULT_DATASET_PATH) or binding[
        "fixture_sha256"
    ] != existing.file_hash(existing.DEFAULT_PROVIDER_FIXTURE_PATH):
        raise ValueError("Canonical Dataset/Fixture changed")
    canonical = existing.load_cases()
    cases = []
    for case_id in CASE_IDS:
        source = next(c for c in binding["cases"] if c["case_id"] == case_id)
        rows = [
            r
            for r in raw["results"]
            if r["case_id"] == case_id and r["arm"] == "schema_constrained"
        ]
        if len(rows) != 1:
            raise ValueError("exactly one fixed baseline FIRST required")
        row = rows[0]
        call = source["source_call"]
        # File history may differ, but the current actual assembler, transport,
        # schema and admission must reproduce the original complete wire/result.
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
            or existing.validate_response(row["content"], source) != row["validation"]
        ):
            raise ValueError("current wire/Case/admission differs from baseline")
        transformed = candidate.build_payload(payload)
        cases.append(
            {
                "case_id": case_id,
                "owner": "source",
                "source_call": deepcopy(call),
                "case_binding": deepcopy(source["case_binding"]),
                "payload": payload,
                "candidate_payload": transformed,
                "candidate_wire_sha256": object_hash(transformed),
                "baseline": {
                    **deepcopy(row),
                    "new_call": False,
                    "origin_row_sha256": object_hash(row),
                },
            }
        )
    paths = set(binding["source_hashes"]) | {
        "scripts/evaluate_source_catalog_projection.py",
        "scripts/ru_source_catalog_projection_candidate.py",
        "tests/evaluation/test_source_catalog_projection_runner.py",
        "tests/evaluation/test_ru_source_catalog_projection_candidate.py",
        "docs/canonical/15-agent-capability-failure-prompt-contract.md",
        CRITERIA,
    }
    hashes = {p: existing.file_hash(ROOT / p) for p in sorted(paths)}
    return {
        "kind": candidate.CANDIDATE_ID,
        "candidate_input_contract": candidate.INPUT_CONTRACT,
        "head_sha": head(),
        "model": model,
        "cases": cases,
        "baseline_sha": binding["head_sha"],
        "baseline_path": BASELINE.as_posix(),
        "baseline_raw_sha256": BASELINE_HASH,
        "source_hashes": hashes,
        "historical_file_differences": {
            p: {"historical": digest, "current": hashes[p]}
            for p, digest in binding["source_hashes"].items()
            if digest != hashes[p]
        },
        "baseline_reuse_basis": "CURRENT_WIRE_SCHEMA_VALIDATION_EQUIVALENCE_NOT_SAME_SHA",
        "dataset_sha256": binding["dataset_sha256"],
        "fixture_sha256": binding["fixture_sha256"],
        "policy": {
            "trials": 1,
            "max_calls": 3,
            "concurrency": 1,
            "repair": 0,
            "retry": 0,
            "codec": 0,
            "rerun_to_pass": 0,
            "provider_calls": 0,
        },
        "semantic_verdict": "UNREVIEWED",
        "business_success": "NOT_EVALUATED",
    }


def execute_plan(plan: dict[str, Any], output: Path, *, plan_sha256: str) -> dict[str, Any]:
    if object_hash(plan) != plan_sha256:
        raise ValueError("plan hash mismatch")
    if make_plan(existing.inspect_diagnostic_model("presence_zero")) != plan:
        raise ValueError("HEAD/code/input/model/runtime drift")
    return execute_registered_firsts(
        plan, output, plan_sha256=plan_sha256, claim_directory=".source-catalog-trials"
    )


def execute_registered_firsts(
    plan: dict[str, Any],
    output: Path,
    *,
    plan_sha256: str,
    claim_directory: str,
    response_model: str | None = None,
) -> dict[str, Any]:
    """Execute a preflight-validated, fixed plan; callers own reconstruction checks."""
    output = output.resolve()
    if output == RESULTS.resolve() or not output.is_relative_to(RESULTS.resolve()):
        raise ValueError("dedicated evaluation/results directory required")
    if output.exists() and any(output.iterdir()):
        raise ValueError("previous trial cannot be overwritten")
    write_json(
        RESULTS / claim_directory / f"{plan_sha256}.json",
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
            "stage": "FIRST",
            "state": "DISPATCH_STARTED",
            "wire_request_count": 1,
            "wire_sha256": object_hash(payload),
            "payload": payload,
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
            for source, target in (
                ("total_duration", "latency_ms"),
                ("load_duration", "load_duration_ms"),
                ("prompt_eval_duration", "prompt_eval_duration_ms"),
                ("eval_duration", "eval_duration_ms"),
            ):
                value = response.get(source)
                row[target] = value // 1_000_000 if type(value) is int else None
            write_json(path, raw)
            if response_model is not None:
                row["response_model_matches"] = row["model"] == response_model
                if not row["response_model_matches"]:
                    raise ValueError("actual response model differs from registered model")
            row["validation"] = existing.validate_response(row["content"], case)
        except Exception as error:
            row.update(state="ERROR", error_type=type(error).__name__, error=str(error)[:500])
        finally:
            row["wall_latency_ms"] = int((time.monotonic() - start) * 1000)
            write_json(path, raw)
    raw.update(
        completed=True,
        actual_http_calls=len(raw["calls"]),
        metrics={
            "baseline_reused": metrics(raw["reused_results"]),
            "candidate_new": metrics(raw["calls"]),
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
        raw = execute_plan(
            read_json(args.execute_plan), args.result_dir, plan_sha256=args.expected_plan_sha256
        )
        print(json.dumps({"calls": raw["actual_http_calls"], "semantic_verdict": "UNREVIEWED"}))
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
