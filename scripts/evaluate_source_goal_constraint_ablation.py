"""Focal Source ablation of generated Goal constraints, never of user requirements."""

from __future__ import annotations

import argparse
import json
from copy import deepcopy
from pathlib import Path
from typing import Any

from scripts import evaluate_source_focal as reference
from scripts.evaluate_effect_prohibition_sampler import write_json
from scripts.ru_observation import metrics, object_hash

control, existing = reference.control, reference.existing
ROOT, RESULTS = reference.ROOT, reference.RESULTS
PREVIOUS_RAW = RESULTS / "076-source-focal-t1/raw.json"
PREVIOUS_HASH = "f59b013d514e5fd5ef805a8c5a086341db1442afff5eef1cef05bcc1fb7131d5"
PREVIOUS_PLAN_HASH = "f4b2b21f6ae0b7ab988d5e3ec481af83788d47dbabda579a9a22c12e176b4a5d"
CRITERIA = "evaluation/experiments/077-source-goal-constraint-criteria.md"
KEYS = (
    ("CASE-CORE-017", "TASK"),
    ("CASE-CORE-049", "TASK"),
    ("CASE-CORE-005", "TASK"),
    ("SYNTHETIC-DRAFT-UPDATE", "GMAIL_DRAFT"),
)


def build_payload(original: dict[str, Any]) -> dict[str, Any]:
    body = json.loads(original["prompt"])
    if not isinstance(body, dict) or set(body) != {"prompt_ref", "input", "output_schema"}:
        raise ValueError("focal FIRST envelope required")
    projection = body["input"]
    if not isinstance(projection, dict) or set(projection) != reference.candidate.INPUT_FIELDS | {
        "assessment_resource_type"
    }:
        raise ValueError("focal FIRST input required")
    goal = projection.get("goal_candidate")
    if not isinstance(goal, dict) or not isinstance(goal.get("constraints"), dict):
        raise ValueError("existing Goal constraints object required")
    suffix = (
        json.dumps(projection, ensure_ascii=False, separators=(",", ":"), sort_keys=True) + "\n"
    )
    if not original["system"].endswith(suffix) or original.get("format") != body["output_schema"]:
        raise ValueError("frozen focal input/schema copies differ")
    if not goal["constraints"]:
        return deepcopy(original)
    payload, candidate_body = deepcopy(original), deepcopy(body)
    candidate_body["input"]["goal_candidate"]["constraints"] = {}
    payload["prompt"] = json.dumps(candidate_body, ensure_ascii=False, sort_keys=True)
    payload["system"] = (
        original["system"][: -len(suffix)]
        + json.dumps(
            candidate_body["input"], ensure_ascii=False, separators=(",", ":"), sort_keys=True
        )
        + "\n"
    )
    return payload


def make_plan(model: dict[str, Any]) -> dict[str, Any]:
    if existing.file_hash(PREVIOUS_RAW) != PREVIOUS_HASH:
        raise ValueError("focal raw changed")
    previous = control.shared.read_json(PREVIOUS_RAW)
    if (
        object_hash(previous["binding"]) != PREVIOUS_PLAN_HASH
        or previous["plan_sha256"] != PREVIOUS_PLAN_HASH
        or not previous["completed"]
        or not previous["binding_unchanged"]
        or previous["diagnostic_status"] != "RECORDED"
        or previous["actual_http_calls"] != 8
        or previous["binding"]["model"] != model
    ):
        raise ValueError("complete focal raw binding required")
    current = reference.make_plan(model)
    old_pairs = list(zip(previous["binding"]["cases"], previous["calls"], strict=True))
    cases = []
    for case_id, focus in KEYS:
        source = next(
            c
            for c in current["cases"]
            if (c["case_id"], c["focus_resource_type"]) == (case_id, focus)
        )
        matches = [
            (c, r)
            for c, r in old_pairs
            if (c["case_id"], c["focus_resource_type"]) == (case_id, focus)
        ]
        if len(matches) != 1:
            raise ValueError("one focal reference per fixed key required")
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
            raise ValueError("focal wire/input/response binding mismatch")
        payload = build_payload(row["payload"])
        cases.append(
            {
                **deepcopy(source),
                "candidate_payload": payload,
                "candidate_wire_sha256": object_hash(payload),
                "candidate_input_sha256": object_hash(json.loads(payload["prompt"])["input"]),
                "historical_focal_result": {**deepcopy(row), "new_call": False},
                "wire_changed": payload != row["payload"],
            }
        )
    hashes = dict(current["source_hashes"])
    for path in (
        "scripts/evaluate_source_goal_constraint_ablation.py",
        "tests/evaluation/test_source_goal_constraint_ablation.py",
        CRITERIA,
    ):
        hashes[path] = existing.file_hash(ROOT / path)
    return {
        "kind": "FOCAL_GOAL_CONSTRAINTS_ABLATION_077",
        "head_sha": current["head_sha"],
        "model": model,
        "cases": cases,
        "source_hashes": hashes,
        "previous_head": previous["binding"]["head_sha"],
        "previous_raw_sha256": PREVIOUS_HASH,
        "dataset_sha256": current["dataset_sha256"],
        "fixture_sha256": current["fixture_sha256"],
        "policy": {
            "new_calls": 4,
            "trials": 1,
            "concurrency": 1,
            "timeout_seconds": 180,
            "retry": 0,
            "repair": 0,
            "provider_calls": 0,
            "graph_calls": 0,
        },
        "scope": "PARTIAL_SOURCE_INPUT_CONTRACT_NOT_PRODUCT_CONSTRAINT_REMOVAL",
        "semantic_verdict": "NOT_REVIEWED",
        "business_success": "NOT_EVALUATED",
    }


def execute_plan(plan: dict[str, Any], output: Path, *, plan_sha256: str) -> dict[str, Any]:
    raw = control.execute_registered_plan(
        plan,
        output,
        plan_sha256=plan_sha256,
        reconstruct_plan=lambda: make_plan(existing.inspect_diagnostic_model("presence_zero")),
        claim_directory=".source-goal-constraint-trials",
        reference_results=[c["historical_focal_result"] for c in plan["cases"]],
        reference_metric="historical_focal_same_four_references",
    )
    pairs = list(zip(plan["cases"][: len(raw["calls"])], raw["calls"], strict=True))
    if any(
        c["case_id"] != r["case_id"] or c["candidate_payload"] != r["payload"] for c, r in pairs
    ):
        raise ValueError("recorded focal order/wire differs from plan")
    write_json(
        output / "source-admission.json",
        {
            "raw_sha256": existing.file_hash(output / "raw.json"),
            "scope": plan["scope"],
            "cases": [
                {
                    "case_id": c["case_id"],
                    "focus_resource_type": c["focus_resource_type"],
                    "group": c["group"],
                    **reference.candidate.admit_focus(r.get("content"), r["payload"]),
                }
                for c, r in pairs
            ],
            "metrics_by_group": {
                group: metrics([r for c, r in pairs if c["group"] == group])
                for group in ("CORE", "SYNTHETIC")
            },
            "semantic_verdict": "NOT_REVIEWED",
            "business_success": "NOT_EVALUATED",
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
