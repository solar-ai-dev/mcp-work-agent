"""Bounded native-thinking compatibility check on frozen focal Source FIRSTs."""

from __future__ import annotations

import argparse
import json
from copy import deepcopy
from pathlib import Path
from typing import Any

from scripts import evaluate_source_focal as reference
from scripts import evaluate_source_goal_constraint_ablation as frozen
from scripts.evaluate_effect_prohibition_sampler import write_json
from scripts.ru_observation import object_hash

control, existing = reference.control, reference.existing
ROOT, RESULTS = reference.ROOT, reference.RESULTS
CRITERIA = "evaluation/experiments/078-source-focal-reasoning-criteria.md"
KEYS = (
    ("CASE-CORE-049", "TASK"),
    ("CASE-CORE-005", "TASK"),
    ("CASE-CORE-017", "GMAIL_DRAFT"),
    ("SYNTHETIC-DRAFT-UPDATE", "GMAIL_DRAFT"),
)


def build_payload(original: dict[str, Any]) -> dict[str, Any]:
    if original.get("think") is not False or original.get("stream") is not False:
        raise ValueError("frozen non-thinking non-streaming control required")
    payload = deepcopy(original)
    payload["think"] = True
    return payload


def structural_stop(row: dict[str, Any], case: dict[str, Any]) -> str | None:
    admission = reference.candidate.admit_focus(row.get("content"), case["candidate_payload"])
    row["source_admission"] = admission
    status = admission["validation"]["structural_result"]
    return None if status == "VALIDATED" else f"FOCAL_FINAL_{status}"


def make_plan(model: dict[str, Any]) -> dict[str, Any]:
    if existing.file_hash(frozen.PREVIOUS_RAW) != frozen.PREVIOUS_HASH:
        raise ValueError("frozen focal raw changed")
    previous = control.shared.read_json(frozen.PREVIOUS_RAW)
    if (
        object_hash(previous["binding"]) != frozen.PREVIOUS_PLAN_HASH
        or previous["plan_sha256"] != frozen.PREVIOUS_PLAN_HASH
        or not previous["completed"]
        or not previous["binding_unchanged"]
        or previous["diagnostic_status"] != "RECORDED"
        or previous["actual_http_calls"] != 8
        or previous["binding"]["model"] != model
    ):
        raise ValueError("complete focal raw binding required")
    current = reference.make_plan(model)
    pairs = list(zip(previous["binding"]["cases"], previous["calls"], strict=True))
    cases = []
    for key in KEYS:
        source = next(
            c for c in current["cases"] if (c["case_id"], c["focus_resource_type"]) == key
        )
        matches = [(c, r) for c, r in pairs if (c["case_id"], c["focus_resource_type"]) == key]
        if len(matches) != 1:
            raise ValueError("exactly one frozen focal reference required")
        old, row = matches[0]
        if (
            source["candidate_payload"] != old["candidate_payload"]
            or source["candidate_payload"] != row["payload"]
            or row["wire_sha256"] != object_hash(row["payload"])
            or row["input_sha256"] != source["candidate_input_sha256"]
            or row["state"] != "RETURNED"
            or row["done"] is not True
            or row["model"] != model["model_id"]
            or row["wire_request_count"] != 1
        ):
            raise ValueError("frozen focal wire/input/response mismatch")
        payload = build_payload(row["payload"])
        cases.append(
            {
                **deepcopy(source),
                "candidate_payload": payload,
                "candidate_wire_sha256": object_hash(payload),
                "historical_focal_result": {**deepcopy(row), "new_call": False},
            }
        )
    hashes = dict(current["source_hashes"])
    for path in (
        "scripts/evaluate_source_focal_reasoning.py",
        "scripts/evaluate_source_goal_constraint_ablation.py",
        "tests/evaluation/test_source_focal_reasoning.py",
        "tests/evaluation/test_ru_semantic_capability.py",
        CRITERIA,
    ):
        hashes[path] = existing.file_hash(ROOT / path)
    return {
        "kind": "FOCAL_SOURCE_NATIVE_REASONING_078",
        "head_sha": current["head_sha"],
        "model": model,
        "cases": cases,
        "source_hashes": hashes,
        "previous_head": previous["binding"]["head_sha"],
        "previous_raw_sha256": frozen.PREVIOUS_HASH,
        "dataset_sha256": current["dataset_sha256"],
        "fixture_sha256": current["fixture_sha256"],
        "policy": {
            "maximum_new_calls": 4,
            "trials": 1,
            "concurrency": 1,
            "timeout_seconds": 180,
            "retry": 0,
            "repair": 0,
            "provider_calls": 0,
            "graph_calls": 0,
            "stop": "ANY_STRUCTURALLY_INVALID_FINAL_OR_TRANSPORT_FAILURE",
            "semantic_failure_stops_dispatch": False,
        },
        "scope": "PARTIAL_SOURCE_FINAL_RESPONSE_COMPATIBILITY_NOT_COMPLETE_SOURCE",
        "semantic_verdict": "NOT_REVIEWED",
        "business_success": "NOT_EVALUATED",
    }


def execute_plan(plan: dict[str, Any], output: Path, *, plan_sha256: str) -> dict[str, Any]:
    return control.execute_registered_plan(
        plan,
        output,
        plan_sha256=plan_sha256,
        reconstruct_plan=lambda: make_plan(existing.inspect_diagnostic_model("presence_zero")),
        claim_directory=".source-focal-reasoning-trials",
        reference_results=[c["historical_focal_result"] for c in plan["cases"]],
        reference_metric="historical_focal_four_references_not_dispatched_denominator",
        stop_after_response=structural_stop,
    )


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
