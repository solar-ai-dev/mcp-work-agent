"""085 adjacent synthetic compose FIRSTs; reuse 065 baselines, generate at most four."""

from __future__ import annotations

import argparse
import json
from copy import deepcopy
from pathlib import Path
from typing import Any

from scripts import evaluate_answer_mode_first as ordered
from scripts import evaluate_read_answer_handoff as handoff
from scripts.evaluate_effect_prohibition_sampler import head, write_json
from scripts.ru_observation import object_hash

from google_work_agent.application.agents.retrieval.resolve_task_calendar_snapshot import (
    resolve_unique_task_calendar_snapshots,
)

choice = ordered.previous
ROOT, RESULTS, existing = handoff.ROOT, handoff.RESULTS, choice.existing
PRIOR = RESULTS / "065-read-answer-handoff-t1/raw.json"
PRIOR_PLAN = PRIOR.with_name("plan.json")
PRIOR_HASH = "607b474471238c2fd77e7b30234a7fa3a3d9360925296c40845532ba313caf7a"
PRIOR_PLAN_HASH = "00fd6f33489da6d33660e204bfafcabf68c9b88780c09da41b372eb64e614fb4"
CRITERIA = "evaluation/experiments/085-answer-choice-adjacent-criteria.md"
CASE_IDS = ("SYNTHETIC_TASK_NOTES", "SYNTHETIC_CALENDAR_LOCATION")


def property_orders(payload: dict[str, Any]) -> list[list[str]]:
    schema = payload["format"]
    return [list(branch["properties"]) for branch in schema.get("oneOf", [schema])]


def build_payload(
    original: dict[str, Any],
    projection: dict[str, Any],
    snapshots: dict[str, Any],
) -> dict[str, Any]:
    payload = choice.choice_wire(original, projection, snapshots)
    if "oneOf" in payload["format"]:
        return ordered.mode_first_wire(payload)
    # 084 intentionally closes a two-branch union. This adjacent no-Task case
    # keeps the existing single PROSE branch; only its property order changes.
    result = deepcopy(payload)
    schema = result["format"]
    properties = schema.get("properties")
    if (
        schema.get("additionalProperties") is not False
        or not isinstance(properties, dict)
        or properties.get("mode") != {"const": "PROSE"}
        or set(properties) != {"mode", "schema_version", "answer", "evidence_refs"}
        or schema.get("required") != ["mode", "schema_version", "answer", "evidence_refs"]
    ):
        raise ValueError("closed single PROSE branch required")
    schema["properties"] = {
        "mode": properties["mode"],
        **{key: value for key, value in properties.items() if key != "mode"},
    }
    if result != payload:
        raise ValueError("property order changed answer-choice semantics")
    return result


def verify_wire_seals(plan: dict[str, Any]) -> None:
    for case in plan["cases"]:
        payload = case["candidate_payload"]
        if (
            ordered.transport_hash(payload) != case["candidate_transport_sha256"]
            or property_orders(payload) != case["candidate_property_orders"]
        ):
            raise ValueError("transport byte/property order drift")


def make_plan(model: dict[str, Any]) -> dict[str, Any]:
    if existing.file_hash(PRIOR) != PRIOR_HASH or existing.file_hash(PRIOR_PLAN) != PRIOR_PLAN_HASH:
        raise ValueError("sealed 065 history changed")
    raw, prior = choice.history.read_json(PRIOR), choice.history.read_json(PRIOR_PLAN)
    if (
        raw["state"] != "FINISHED"
        or raw["source_binding_unchanged"] is not True
        or raw["plan_sha256"] != PRIOR_PLAN_HASH
        or prior["model"] != model
    ):
        raise ValueError("complete same-model 065 history required")
    inputs, references = [], []
    for group in CASE_IDS:
        matches = [item for item in prior["cases"] if item["case_id"] == group]
        rows = [item for item in raw["cases"] if item["case_id"] == group]
        if len(matches) != 1 or len(rows) != 1 or len(rows[0]["calls"]) != 1:
            raise ValueError("exact one historical FIRST per adjacent input required")
        case, row = matches[0], rows[0]
        first, call = case["first"], row["calls"][0]
        pipeline = case["pipeline_input"]
        if (
            case["pipeline_input_sha256"] != object_hash(pipeline)
            or row["pipeline_input_sha256"] != case["pipeline_input_sha256"]
            or row["pipeline_input_unchanged"] is not True
            or row["state"] != "RETURNED"
            or call["state"] != "RETURNED"
            or call["structural_validation"] != "VALID"
            or call["provider_response"]["model"] != model["model_id"]
            or call["provider_response"]["done"] is not True
        ):
            raise ValueError("historical FIRST/snapshot binding differs")
        current = handoff._wire_projection(first["input"])
        if (
            current != first
            or any(call[key] != value for key, value in first.items())
            or ordered.transport_hash(current["wire_payload"])
            != ordered.transport_hash(call["wire_payload"])
        ):
            raise ValueError("current Product compose wire differs; no historical baseline reuse")
        if any(
            pipeline[key] != first["input"][key]
            for key in ("user_request", "request_intent", "evidence")
        ):
            raise ValueError("historical pipeline differs from the recorded compose input")
        snapshots = pipeline["source_snapshots"]
        if resolve_unique_task_calendar_snapshots(first["input"]["evidence"], snapshots) is None:
            raise ValueError("exact version-bound synthetic snapshot required")
        inputs.append((group, first["input"], snapshots, current["wire_payload"]))
        response = call["provider_response"]
        references.append(
            {
                "case_id": group,
                "source_row": deepcopy(row),
                "new_call": False,
                "source_row_sha256": object_hash(row),
                "content": response["response"],
                "input_tokens": response["prompt_eval_count"],
                "output_tokens": response["eval_count"],
                "latency_ms": response["total_duration"] // 1_000_000,
            }
        )
    cases = []
    for trial in (1, 2):
        for group, projection, snapshots, original in inputs:
            payload = build_payload(original, projection, snapshots)
            cases.append(
                {
                    "case_id": f"{group}-MODE_FIRST-T{trial}",
                    "group": group,
                    "arm": "MODE_FIRST",
                    "trial": trial,
                    "prompt_input": deepcopy(projection),
                    "snapshots": deepcopy(snapshots),
                    "original_wire_sha256": object_hash(original),
                    "original_transport_sha256": ordered.transport_hash(original),
                    "candidate_payload": payload,
                    "candidate_wire_sha256": object_hash(payload),
                    "candidate_transport_sha256": ordered.transport_hash(payload),
                    "candidate_property_orders": property_orders(payload),
                    "candidate_input_sha256": object_hash(projection),
                }
            )
    hashes = handoff._bound_files()
    for path in (
        "scripts/evaluate_answer_choice_adjacent.py",
        "scripts/evaluate_answer_mode_first.py",
        "scripts/evaluate_answer_rendering_choice.py",
        "scripts/answer_rendering_choice_candidate.py",
        "scripts/answer_fact_selection_candidate.py",
        "scripts/evaluate_task_completion_fact.py",
        "scripts/evaluate_ru_semantic_capability.py",
        "tests/evaluation/test_answer_choice_adjacent.py",
        CRITERIA,
    ):
        hashes[path] = existing.file_hash(ROOT / path)
    plan = {
        "kind": "085_ANSWER_CHOICE_ADJACENT_FIRST",
        "head_sha": head(),
        "model": model,
        "cases": cases,
        "source_hashes": hashes,
        "history_sha256": PRIOR_HASH,
        "history_plan_sha256": PRIOR_PLAN_HASH,
        "historical_prose": references,
        "scope": "SYNTHETIC_PLANNING_FIRST_NOT_GRAPH_OR_CANONICAL92",
        "policy": {
            "new_calls": 4,
            "historical_calls": 2,
            "retry": 0,
            "repair": 0,
            "concurrency": 1,
            "timeout_seconds": 180,
            "trials_per_input": 2,
        },
        "semantic_verdict": "NOT_REVIEWED",
        "business_success": "NOT_EVALUATED",
    }
    verify_wire_seals(plan)
    return plan


def execute_plan(plan: dict[str, Any], output: Path, *, plan_sha256: str) -> dict[str, Any]:
    def reconstruct() -> dict[str, Any]:
        verify_wire_seals(plan)
        return make_plan(existing.inspect_diagnostic_model("presence_zero"))

    return choice.recorder.execute_registered_plan(
        plan,
        output,
        plan_sha256=plan_sha256,
        reconstruct_plan=reconstruct,
        claim_directory=".answer-choice-adjacent-trials",
        reference_results=plan["historical_prose"],
        reference_metric="065_historical_two_firsts",
        stop_after_response=ordered.record_admission,
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
        directory = choice.recorder._output_directory(args.result_dir)
        plan = make_plan(existing.inspect_diagnostic_model("presence_zero"))
        path = directory / "preregistered-plan.json"
        write_json(path, plan, exclusive=True)
        print(json.dumps({"plan": str(path), "sha256": object_hash(plan), "generation_calls": 0}))
        return
    if not args.plan_sha256:
        parser.error("--execute-plan requires --plan-sha256")
    raw = execute_plan(
        choice.history.read_json(args.execute_plan), args.result_dir, plan_sha256=args.plan_sha256
    )
    print(json.dumps({key: raw[key] for key in ("diagnostic_status", "actual_http_calls")}))
    raise SystemExit(0 if raw["diagnostic_status"] == "RECORDED" else 1)


if __name__ == "__main__":
    main()
