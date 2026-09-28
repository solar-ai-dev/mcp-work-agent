"""Five sealed full-Source FIRSTs with request-local provenance, not a workflow."""

from __future__ import annotations

import argparse
import json
from copy import deepcopy
from pathlib import Path
from typing import Any

from scripts import evaluate_ru_semantic_capability as control
from scripts import ru_source_provenance_candidate as candidate
from scripts.evaluate_effect_prohibition_sampler import write_json
from scripts.ru_observation import object_hash

existing, ROOT, RESULTS = control.existing, control.ROOT, control.RESULTS
CASE_IDS = tuple(f"CASE-CORE-{number:03}" for number in (17, 49, 5, 9, 59))
CRITERIA = "evaluation/experiments/080-source-provenance-criteria.md"


def make_plan(model: dict[str, Any]) -> dict[str, Any]:
    current = control.make_plan(model)
    cases = []
    for case_id in CASE_IDS:
        matches = [item for item in current["cases"] if item["case_id"] == case_id]
        if len(matches) != 1:
            raise ValueError("exactly one historical Source FIRST per fixed Core required")
        source = matches[0]
        original = existing.reconstruct_payload(source["source_call"])
        payload = candidate.build_payload(original)
        original_body, body = json.loads(original["prompt"]), json.loads(payload["prompt"])
        original_input, projection = original_body["input"], body["input"]
        if (
            set(payload) != set(original)
            or any(
                payload[key] != value
                for key, value in original.items()
                if key not in {"system", "prompt", "format"}
            )
            or set(projection) != set(original_input) | {"request_tokens"}
            or any(projection[key] != value for key, value in original_input.items())
            or payload["format"] != body["output_schema"]
        ):
            raise ValueError("candidate changed frozen Source input or runtime authority")
        cases.append(
            {
                "case_id": case_id,
                "case_binding": deepcopy(source["case_binding"]),
                "source_call": deepcopy(source["source_call"]),
                "source_call_sha256": object_hash(source["source_call"]),
                "original_payload": original,
                "original_wire_sha256": object_hash(original),
                "original_input_sha256": object_hash(original_input),
                "candidate_payload": payload,
                "candidate_wire_sha256": object_hash(payload),
                "candidate_input_sha256": object_hash(projection),
                "candidate_schema_sha256": object_hash(body["output_schema"]),
                "historical_source_result": deepcopy(source["historical_source_result"]),
            }
        )
    hashes = dict(current["source_hashes"])
    for path in (
        "scripts/evaluate_source_provenance.py",
        "scripts/ru_source_provenance_candidate.py",
        "scripts/ru_source_focal_candidate.py",
        "evaluation/request_semantic_authority_candidate.py",
        "tests/evaluation/test_source_provenance_candidate.py",
        "docs/canonical/06-agent-workflow.md",
        "docs/canonical/15-agent-capability-failure-prompt-contract.md",
        CRITERIA,
    ):
        hashes[path] = existing.file_hash(ROOT / path)
    return {
        "kind": "SOURCE_REQUEST_PROVENANCE_FIRST_080",
        "head_sha": current["head_sha"],
        "model": model,
        "cases": cases,
        "source_hashes": hashes,
        "source_reference_head": current["baseline_head"],
        "source_reference_path": current["baseline_path"],
        "source_reference_raw_sha256": current["baseline_raw_sha256"],
        "source_reference_plan_sha256": current["baseline_plan_sha256"],
        "dataset_sha256": current["dataset_sha256"],
        "fixture_sha256": current["fixture_sha256"],
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
            "structural_failure_stops_dispatch": False,
            "semantic_failure_stops_dispatch": False,
        },
        "comparison_scope": "HISTORICAL_SOURCE_REFERENCE_NOT_FRESH_PAIRED_RUNTIME",
        "scope": "FULL_SOURCE_OWNER_NOT_RU_ROUTE_OR_BUSINESS_SUCCESS",
        "semantic_verdict": "NOT_REVIEWED",
        "business_success": "NOT_EVALUATED",
    }


def _record_admission(row: dict[str, Any], case: dict[str, Any]) -> None:
    if row["case_id"] != case["case_id"] or row["payload"] != case["candidate_payload"]:
        raise ValueError("recorded Source order/wire differs from plan")
    row["source_admission"] = candidate.admit_source(row.get("content"), row["payload"])
    # The callback records structural failure without selecting which trials survive.
    return None


def execute_plan(plan: dict[str, Any], output: Path, *, plan_sha256: str) -> dict[str, Any]:
    raw = control.execute_registered_plan(
        plan,
        output,
        plan_sha256=plan_sha256,
        reconstruct_plan=lambda: make_plan(existing.inspect_diagnostic_model("presence_zero")),
        claim_directory=".source-provenance-trials",
        reference_results=[c["historical_source_result"] for c in plan["cases"]],
        reference_metric="historical_source_five_not_new_or_fresh_paired",
        stop_after_response=_record_admission,
    )
    write_json(
        output / "source-admission.json",
        {
            "raw_sha256": existing.file_hash(output / "raw.json"),
            "scope": plan["scope"],
            "cases": [
                {
                    "case_id": row["case_id"],
                    "wire_sha256": row["wire_sha256"],
                    "state": row["state"],
                    "source_admission": row.get("source_admission"),
                }
                for row in raw["calls"]
            ],
            "not_dispatched": raw["not_dispatched"],
            "semantic_verdict": "NOT_REVIEWED",
            "business_success": "NOT_EVALUATED",
            "recorded_does_not_mean_structural_or_semantic_pass": True,
        },
        exclusive=True,
    )
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
        output = control._output_directory(args.result_dir)
        plan = make_plan(existing.inspect_diagnostic_model("presence_zero"))
        path = output / "preregistered-plan.json"
        write_json(path, plan, exclusive=True)
        print(json.dumps({"plan": str(path), "sha256": object_hash(plan), "generation_calls": 0}))
    else:
        if not args.plan_sha256:
            parser.error("--execute-plan requires --plan-sha256")
        raw = execute_plan(
            control.shared.read_json(args.execute_plan),
            args.result_dir,
            plan_sha256=args.plan_sha256,
        )
        print(json.dumps({k: raw[k] for k in ("diagnostic_status", "actual_http_calls")}))
        raise SystemExit(0 if raw["diagnostic_status"] == "RECORDED" else 1)


if __name__ == "__main__":
    main()
