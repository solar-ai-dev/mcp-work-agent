"""Inactive 084 ablation: move the union discriminator before its payload only."""

from __future__ import annotations

import argparse
import hashlib
import json
from copy import deepcopy
from pathlib import Path
from typing import Any

from scripts import evaluate_answer_rendering_choice as previous
from scripts.evaluate_effect_prohibition_sampler import head, write_json
from scripts.ru_observation import object_hash

PRIOR = previous.RESULTS / "083-answer-rendering-choice-t1/raw.json"
PRIOR_HASH = "57615df1c764ae283024213069e409bd6a117c2eae77ebcf728c0238589b26ac"
CRITERIA = "evaluation/experiments/084-answer-mode-first-criteria.md"


def transport_hash(payload: dict[str, Any]) -> str:
    """Match Product _post_json bytes, including insertion order and escaping."""
    return hashlib.sha256(json.dumps(payload).encode("utf-8")).hexdigest()


def property_orders(payload: dict[str, Any]) -> list[list[str]]:
    return [list(branch["properties"]) for branch in payload["format"]["oneOf"]]


def mode_first_wire(wire: dict[str, Any]) -> dict[str, Any]:
    payload = deepcopy(wire)
    schema = payload.get("format")
    branches = schema.get("oneOf") if isinstance(schema, dict) else None
    if not isinstance(branches, list) or len(branches) != 2:
        raise ValueError("two closed answer-choice branches required")
    for branch in branches:
        properties = branch.get("properties") if isinstance(branch, dict) else None
        if not isinstance(properties, dict):
            raise ValueError("closed mode const required")
        mode = properties.get("mode")
        if not isinstance(mode, dict) or mode.get("const") not in {"FACT_REFERENCES", "PROSE"}:
            raise ValueError("closed mode const required")
        branch["properties"] = {
            "mode": properties["mode"],
            **{key: value for key, value in properties.items() if key != "mode"},
        }
    if payload != wire:
        raise ValueError("order ablation changed JSON semantics")
    return payload


def verify_wire_seals(plan: dict[str, Any]) -> None:
    for case in plan["cases"]:
        payload = case["candidate_payload"]
        if transport_hash(payload) != case["candidate_transport_sha256"]:
            raise ValueError("transport byte/order drift")
        if property_orders(payload) != case["candidate_property_orders"]:
            raise ValueError("schema property order drift")


def make_plan(model: dict[str, Any]) -> dict[str, Any]:
    if previous.existing.file_hash(PRIOR) != PRIOR_HASH:
        raise ValueError("sealed 083 result changed")
    prior = previous.history.read_json(PRIOR)
    if not prior["completed"] or not prior["binding_unchanged"]:
        raise ValueError("complete sealed 083 required")
    fresh = previous.make_plan(model)
    if prior["binding"]["model"] != model:
        raise ValueError("083 model/runtime drift")
    cases = []
    references = []
    for old, regenerated, row in zip(
        prior["binding"]["cases"], fresh["cases"], prior["calls"], strict=True
    ):
        if old != regenerated or transport_hash(old["candidate_payload"]) != transport_hash(
            regenerated["candidate_payload"]
        ):
            raise ValueError("083 input/schema/wire changed")
        if transport_hash(row["payload"]) != transport_hash(old["candidate_payload"]):
            raise ValueError("083 actual wire differs from sealed plan")
        if old["arm"] != "CHOICE":
            continue
        case = deepcopy(old)
        payload = mode_first_wire(old["candidate_payload"])
        case.update(
            case_id=old["case_id"].replace("-CHOICE-", "-MODE_FIRST-"),
            arm="MODE_FIRST",
            candidate_payload=payload,
            candidate_wire_sha256=object_hash(payload),
            candidate_transport_sha256=transport_hash(payload),
            candidate_property_orders=property_orders(payload),
            original_transport_sha256=transport_hash(old["candidate_payload"]),
            original_property_orders=property_orders(old["candidate_payload"]),
        )
        cases.append(case)
        references.append(deepcopy(row))
    if len(cases) != 6:
        raise ValueError("fixed three inputs times two FIRSTs required")
    hashes = dict(fresh["source_hashes"])
    for path in (
        "scripts/evaluate_answer_mode_first.py",
        "tests/evaluation/test_answer_mode_first.py",
        CRITERIA,
    ):
        hashes[path] = previous.existing.file_hash(previous.ROOT / path)
    plan = {
        "kind": "084_ANSWER_CHOICE_MODE_FIRST_ORDER_ONLY",
        "head_sha": head(),
        "model": model,
        "cases": cases,
        "source_hashes": hashes,
        "history_sha256": PRIOR_HASH,
        "historical_choice": references,
        "canonical_binding": fresh["canonical_binding"],
        "scope": "NODE_DIAGNOSTIC_NOT_AUTOMATIC_ELIGIBILITY_OR_PRODUCT_ACTIVATION",
        "policy": {
            "new_calls": 6,
            "retry": 0,
            "repair": 0,
            "concurrency": 1,
            "timeout_seconds": 180,
        },
        "semantic_verdict": "NOT_REVIEWED",
        "business_success": "NOT_EVALUATED",
    }
    verify_wire_seals(plan)
    return plan


def record_admission(row: dict[str, Any], case: dict[str, Any]) -> None:
    actual = transport_hash(row["payload"])
    if actual != case["candidate_transport_sha256"]:
        raise ValueError("actual dispatch byte/order drift")
    row["wire_bytes_sha256"] = actual
    try:
        value = json.loads(row["content"])
    except (ValueError, TypeError):
        value = None
    row["output_property_order"] = list(value) if isinstance(value, dict) else None
    previous.record_admission(row, case)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--prepare", action="store_true")
    mode.add_argument("--execute-plan", type=Path)
    parser.add_argument("--result-dir", type=Path, required=True)
    parser.add_argument("--plan-sha256")
    args = parser.parse_args()
    if args.prepare:
        directory = previous.recorder._output_directory(args.result_dir)
        plan = make_plan(previous.existing.inspect_diagnostic_model("presence_zero"))
        path = directory / "preregistered-plan.json"
        write_json(path, plan, exclusive=True)
        print(json.dumps({"plan": str(path), "sha256": object_hash(plan), "generation_calls": 0}))
        return
    if not args.plan_sha256:
        parser.error("--execute-plan requires --plan-sha256")
    plan = previous.history.read_json(args.execute_plan)

    def reconstruct() -> dict[str, Any]:
        # Dictionary equality and object_hash deliberately ignore order. Verify
        # the loaded payload bytes as well as the fresh plan's stored seals.
        verify_wire_seals(plan)
        return make_plan(previous.existing.inspect_diagnostic_model("presence_zero"))

    raw = previous.recorder.execute_registered_plan(
        plan,
        args.result_dir,
        plan_sha256=args.plan_sha256,
        reconstruct_plan=reconstruct,
        claim_directory=".answer-mode-first-trials",
        reference_results=plan["historical_choice"],
        reference_metric="083_historical_choice_six_firsts",
        stop_after_response=record_admission,
    )
    print(json.dumps({key: raw[key] for key in ("diagnostic_status", "actual_http_calls")}))
    raise SystemExit(0 if raw["diagnostic_status"] == "RECORDED" else 1)


if __name__ == "__main__":
    main()
