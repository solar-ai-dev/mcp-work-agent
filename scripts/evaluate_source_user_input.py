"""Sealed USER-only Source envelope comparison, with/without frozen interpretation."""

from __future__ import annotations

import argparse
import json
from copy import deepcopy
from pathlib import Path
from typing import Any

from scripts import evaluate_source_interpretation_handoff as reference
from scripts import ru_source_user_input_candidate as candidate
from scripts.evaluate_effect_prohibition_sampler import write_json
from scripts.ru_observation import metrics, object_hash

control, existing = reference.control, reference.existing
ROOT, RESULTS = reference.ROOT, reference.RESULTS
PREVIOUS_RAW = RESULTS / "074-source-interpretation-handoff-t1/raw.json"
PREVIOUS_HASH = "94c3fadd968a8dd152ac0d9e605af1b8ccd47f44cab62365d39679b322ee61d7"
PREVIOUS_PLAN_HASH = "4293b7bcfd2f58f45a354d2a5db631f79f1a0956452b2fbcd06d014465505b16"
ARMS = ("plain_user_only", "interpretation_user_only")
CRITERIA = "evaluation/experiments/075-source-user-input-criteria.md"


def make_plan(model: dict[str, Any]) -> dict[str, Any]:
    if existing.file_hash(PREVIOUS_RAW) != PREVIOUS_HASH:
        raise ValueError("frozen 074 raw changed")
    previous = control.shared.read_json(PREVIOUS_RAW)
    if (
        previous["plan_sha256"] != PREVIOUS_PLAN_HASH
        or object_hash(previous["binding"]) != PREVIOUS_PLAN_HASH
        or not previous["completed"]
        or not previous["binding_unchanged"]
        or previous["diagnostic_status"] != "RECORDED"
        or previous["actual_http_calls"] != 3
        or previous["binding"]["model"] != model
    ):
        raise ValueError("complete frozen 074 binding required")
    current = reference.make_plan(model)
    cases = []
    for index, source in enumerate(current["cases"]):
        rows = [r for r in previous["calls"] if r["case_id"] == source["case_id"]]
        if len(rows) != 1:
            raise ValueError("one frozen Source response per case required")
        row = rows[0]
        if (
            row["payload"] != source["candidate_payload"]
            or row["wire_sha256"] != object_hash(row["payload"])
            or row["input_sha256"] != source["candidate_input_sha256"]
            or row["state"] != "RETURNED"
            or row["done"] is not True
            or row["wire_request_count"] != 1
            or row["model"] != model["model_id"]
        ):
            raise ValueError("frozen 074 wire differs from current reconstruction")
        original = existing.reconstruct_payload(source["source_call"])
        for arm in ARMS if index != 1 else tuple(reversed(ARMS)):
            interpreted = arm == ARMS[1]
            payload = candidate.build_payload(row["payload"] if interpreted else original)
            cases.append(
                {
                    "case_id": source["case_id"],
                    "arm": arm,
                    "case_binding": deepcopy(source["case_binding"]),
                    "source_call": deepcopy(source["source_call"]),
                    "candidate_payload": payload,
                    "candidate_wire_sha256": object_hash(payload),
                    "candidate_input_sha256": source["candidate_input_sha256"]
                    if interpreted
                    else object_hash(source["source_call"]["input"]),
                    "envelope_variant": "SYSTEM_INPUT_COPY_REMOVED_USER_INPUT_UNCHANGED",
                    "historical_source_result": deepcopy(
                        row if interpreted else source["historical_source_result"]
                    ),
                    "interpretation_result": deepcopy(source["interpretation_result"])
                    if interpreted
                    else None,
                }
            )
    hashes = dict(current["source_hashes"])
    for path in (
        "scripts/evaluate_source_user_input.py",
        "scripts/ru_source_user_input_candidate.py",
        "tests/evaluation/test_source_user_input_candidate.py",
        CRITERIA,
    ):
        hashes[path] = existing.file_hash(ROOT / path)
    return {
        "kind": "SOURCE_USER_ROLE_LOCUS_075",
        "head_sha": current["head_sha"],
        "model": model,
        "cases": cases,
        "source_hashes": hashes,
        "baseline_head": current["source_reference_head"],
        "interpretation_source_head": previous["binding"]["head_sha"],
        "previous_raw_sha256": PREVIOUS_HASH,
        "previous_plan_sha256": PREVIOUS_PLAN_HASH,
        "dataset_sha256": current["dataset_sha256"],
        "fixture_sha256": current["fixture_sha256"],
        "policy": {
            "new_calls": 6,
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


def execute_plan(plan: dict[str, Any], output: Path, *, plan_sha256: str) -> dict[str, Any]:
    raw = control.execute_registered_plan(
        plan,
        output,
        plan_sha256=plan_sha256,
        reconstruct_plan=lambda: make_plan(existing.inspect_diagnostic_model("presence_zero")),
        claim_directory=".source-user-input-trials",
        reference_results=[c["historical_source_result"] for c in plan["cases"]],
        reference_metric="two_distinct_historical_arms_not_single_baseline",
    )
    pairs = list(zip(plan["cases"][: len(raw["calls"])], raw["calls"], strict=True))
    if any(
        c["case_id"] != row["case_id"] or c["candidate_payload"] != row["payload"]
        for c, row in pairs
    ):
        raise ValueError("recorded Source call order/wire differs from plan")
    admission: dict[str, Any] = {
        "raw_sha256": existing.file_hash(output / "raw.json"),
        "cases": [
            {
                "case_id": c["case_id"],
                "arm": c["arm"],
                **reference.admit_source(row.get("content"), c),
            }
            for c, row in pairs
        ],
        "metrics_by_arm": {},
        "cost_scope": "REGISTERED_REPLAY_PLUS_ATTEMPTED_SOURCE_NOT_CONNECTED_EXECUTION",
    }
    for arm in ARMS:
        executed = [r for c, r in pairs if c["arm"] == arm]
        planned = [c for c in plan["cases"] if c["arm"] == arm]
        interpretation = [c["interpretation_result"] for c in planned if c["interpretation_result"]]
        admission["metrics_by_arm"][arm] = {
            "new_source": metrics(executed),
            "historical_source_reference": metrics(
                [c["historical_source_result"] for c in planned]
            ),
            "with_registered_interpretation_cost": metrics(interpretation + executed),
        }
    write_json(output / "source-admission.json", admission, exclusive=True)
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
