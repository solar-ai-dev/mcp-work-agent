"""092: explicit zero temperature on the unchanged full 088 compose FIRST."""

from __future__ import annotations

import argparse
import json
from collections.abc import Callable
from copy import deepcopy
from pathlib import Path
from typing import Any

from scripts import evaluate_answer_assembly_ablation as history
from scripts.evaluate_effect_prohibition_sampler import head, write_json
from scripts.ru_observation import object_hash

existing, recorder, ordered = history.existing, history.recorder, history.ordered
ROOT, RESULTS = history.ROOT, history.RESULTS
CRITERIA = "evaluation/experiments/092-answer-temperature-criteria.md"
ARM = "EXPLICIT_TEMPERATURE_ZERO"


def build_payload(original: dict[str, Any]) -> dict[str, Any]:
    options = original.get("options")
    if not isinstance(options, dict) or "temperature" in options:
        raise ValueError("historical default-temperature wire required")
    result = deepcopy(original)
    result["options"]["temperature"] = 0.0
    return result


def verify_wire_seals(plan: dict[str, Any]) -> None:
    if [(c["group"], c["trial"]) for c in plan["cases"]] != [(g, 1) for g in history.GROUPS]:
        raise ValueError("fixed three inputs and one FIRST each required")
    ordered.verify_wire_seals(plan)
    for case in plan["cases"]:
        original = case["original_payload"]
        if (
            case["arm"] != ARM
            or ordered.transport_hash(original) != case["historical_transport_sha256"]
            or ordered.transport_hash(build_payload(original)) != case["candidate_transport_sha256"]
            or case["prompt_input"] != json.loads(original["prompt"])["input"]
            or object_hash(case["prompt_input"]) != case["candidate_input_sha256"]
        ):
            raise ValueError("temperature-only/full-input wire seal changed")


def make_plan(model: dict[str, Any]) -> dict[str, Any]:
    source = history.make_plan(model)
    cases = []
    for old in source["cases"][:3]:
        payload = build_payload(old["original_payload"])
        case = {
            k: deepcopy(old[k])
            for k in (
                "group",
                "trial",
                "snapshots",
                "upstream",
                "historical_case_id",
                "historical_row_sha256",
                "historical_transport_sha256",
                "original_payload",
                "prompt_input",
            )
        }
        case.update(
            case_id=f"{case['group']}-TEMPERATURE_ZERO-T1",
            arm=ARM,
            candidate_payload=payload,
            candidate_input_sha256=object_hash(case["prompt_input"]),
            candidate_transport_sha256=ordered.transport_hash(payload),
            candidate_property_orders=ordered.property_orders(payload),
            metadata_status="UNCHANGED_HISTORICAL_REF_DIRECT_TRANSPORT_NOT_ROUTER_DISPATCH",
        )
        cases.append(case)
    hashes = dict(source["source_hashes"])
    for path in (
        "scripts/evaluate_answer_temperature.py",
        "tests/evaluation/test_answer_temperature.py",
        CRITERIA,
    ):
        hashes[path] = existing.file_hash(ROOT / path)
    plan = {
        **source,
        "kind": "092_ANSWER_EXPLICIT_TEMPERATURE_ZERO",
        "head_sha": head(),
        "cases": cases,
        "historical_references": source["historical_references"][:3],
        "source_hashes": hashes,
        "scope": "TEMPERATURE_ONLY_DIRECT_TRANSPORT_NOT_REGISTERED_ROUTER_OR_PRODUCT_ACTIVATION",
        "policy": {
            "new_calls": 3,
            "unique_historical_calls": 3,
            "repeat": 0,
            "repair": 0,
            "retry": 0,
            "concurrency": 1,
            "timeout_seconds": 180,
            "maximum_generate_calls": 3,
        },
    }
    verify_wire_seals(plan)
    return plan


def execute_plan(
    plan: dict[str, Any],
    output: Path,
    *,
    plan_sha256: str,
    reconstruct_plan: Callable[[], dict[str, Any]],
) -> dict[str, Any]:
    verify_wire_seals(plan)

    def reconstruct() -> dict[str, Any]:
        verify_wire_seals(plan)
        fresh = reconstruct_plan()
        verify_wire_seals(fresh)
        return fresh

    raw = recorder.execute_registered_plan(
        plan,
        output,
        plan_sha256=plan_sha256,
        reconstruct_plan=reconstruct,
        claim_directory=".answer-temperature-trials",
        reference_results=plan["historical_references"],
        reference_metric="088_historical_three_firsts",
        stop_after_response=ordered.record_admission,
    )
    raw.update(registered_router_calls=0, scope=plan["scope"])
    for row in raw["calls"]:
        row["arm"] = ARM
    write_json(output / "raw.json", raw)
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
        directory = recorder._output_directory(args.result_dir)
        plan = make_plan(existing.inspect_diagnostic_model("presence_zero"))
        path = directory / "preregistered-plan.json"
        write_json(path, plan, exclusive=True)
        print(json.dumps({"plan": str(path), "sha256": object_hash(plan), "generation_calls": 0}))
        return
    if not args.plan_sha256:
        parser.error("--execute-plan requires --plan-sha256")
    raw = execute_plan(
        history.registered._read(args.execute_plan),
        args.result_dir,
        plan_sha256=args.plan_sha256,
        reconstruct_plan=lambda: make_plan(existing.inspect_diagnostic_model("presence_zero")),
    )
    print(json.dumps({k: raw[k] for k in ("diagnostic_status", "actual_http_calls")}))
    raise SystemExit(0 if raw["diagnostic_status"] == "RECORDED" else 1)


if __name__ == "__main__":
    main()
