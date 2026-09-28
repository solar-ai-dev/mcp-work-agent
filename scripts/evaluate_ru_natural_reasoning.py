"""Three short NL controls: only think=True differs from the sealed 071 wire."""

from __future__ import annotations

import argparse
import json
from copy import deepcopy
from pathlib import Path
from typing import Any

from scripts import evaluate_ru_semantic_capability as control
from scripts.evaluate_effect_prohibition_sampler import write_json
from scripts.ru_observation import object_hash

existing, ROOT, RESULTS = control.existing, control.ROOT, control.RESULTS
BASELINE = RESULTS / "071-ru-semantic-capability-t1/raw.json"
BASELINE_HASH = "fe18703f5bc62bdd7b0be56f615d248d22df1fd81f4abb0ff4a99d853796c9df"
BASELINE_PLAN = RESULTS / "071-ru-semantic-capability-plan/preregistered-plan.json"
BASELINE_PLAN_HASH = "08a4c6ca4326da251e0272b381244557ed1a89ad7a1e32bc90d5c5443bdf9414"
CASE_IDS = ("CASE-CORE-017", "CASE-CORE-049", "CASE-CORE-005")
CRITERIA = "evaluation/experiments/072-ru-natural-reasoning-criteria.md"


def build_payload(original: dict[str, Any]) -> dict[str, Any]:
    if (
        original.get("think") is not False
        or original.get("stream") is not False
        or "format" in original
    ):
        raise ValueError("sealed non-thinking NL wire required")
    candidate = deepcopy(original)
    candidate["think"] = True
    return candidate


def make_plan(model: dict[str, Any]) -> dict[str, Any]:
    if (
        existing.file_hash(BASELINE) != BASELINE_HASH
        or existing.file_hash(BASELINE_PLAN) != BASELINE_PLAN_HASH
    ):
        raise ValueError("closed 071 raw/plan bytes changed")
    raw, original = control.shared.read_json(BASELINE), control.shared.read_json(BASELINE_PLAN)
    if (
        raw["binding"] != original
        or raw["plan_sha256"] != object_hash(original)
        or raw["completed"] is not True
        or raw["binding_unchanged"] is not True
        or raw["diagnostic_status"] != "RECORDED"
        or raw["actual_http_calls"] != 5
        or original["model"] != model
    ):
        raise ValueError("complete 071 authority and identical model/runtime required")
    current = control.make_plan(model)  # Metadata/reconstruction only, no generation.
    for path, digest in original["source_hashes"].items():
        if path.startswith("src/") and current["source_hashes"].get(path) != digest:
            raise ValueError("Product source changed since 071")
    cases = []
    for case_id in CASE_IDS:
        sources = [c for c in original["cases"] if c["case_id"] == case_id]
        rebuilt = [c for c in current["cases"] if c["case_id"] == case_id]
        rows = [r for r in raw["calls"] if r["case_id"] == case_id]
        if len(sources) != 1 or len(rebuilt) != 1 or len(rows) != 1:
            raise ValueError("exactly one FIRST per registered Core required")
        source, now, row = sources[0], rebuilt[0], rows[0]
        payload = source["candidate_payload"]
        if (
            now["candidate_payload"] != payload
            or row["payload"] != payload
            or source["source_call_sha256"] != now["source_call_sha256"]
            or source["case_binding"] != now["case_binding"]
            or row["wire_sha256"] != object_hash(payload)
            or source["candidate_wire_sha256"] != object_hash(payload)
            or row["input_sha256"] != object_hash(json.loads(payload["prompt"]))
            or row["input_sha256"] != source["candidate_input_sha256"]
            or row["state"] != "RETURNED"
            or row["wire_request_count"] != 1
            or row["validation"] != "NONEMPTY_TEXT"
            or row["done"] is not True
            or row["model"] != model["model_id"]
            or not isinstance(row["content"], str)
            or not row["content"].strip()
        ):
            raise ValueError("071 exact input/wire/response binding mismatch")
        candidate = build_payload(payload)
        cases.append(
            {
                "case_id": case_id,
                "case_binding": deepcopy(source["case_binding"]),
                "candidate_payload": candidate,
                "candidate_wire_sha256": object_hash(candidate),
                "candidate_input_sha256": row["input_sha256"],
                "baseline_wire_sha256": row["wire_sha256"],
                "historical_nl_result": {
                    **deepcopy(row),
                    "new_call": False,
                    "origin_row_sha256": object_hash(row),
                },
            }
        )
    hashes = dict(current["source_hashes"])
    hashes.update(
        {
            p: existing.file_hash(ROOT / p)
            for p in (
                "scripts/evaluate_ru_natural_reasoning.py",
                "tests/evaluation/test_ru_natural_reasoning.py",
                CRITERIA,
            )
        }
    )
    return {
        "kind": "RU_NL_THINK_ONLY_CONTROL_072",
        "head_sha": current["head_sha"],
        "model": model,
        "cases": cases,
        "baseline_head": original["head_sha"],
        "baseline_path": BASELINE.as_posix(),
        "baseline_raw_sha256": BASELINE_HASH,
        "baseline_plan_path": BASELINE_PLAN.as_posix(),
        "baseline_plan_sha256": BASELINE_PLAN_HASH,
        "source_hashes": hashes,
        "historical_file_differences": {
            p: {"historical": digest, "current": hashes.get(p)}
            for p, digest in original["source_hashes"].items()
            if digest != hashes.get(p)
        },
        "dataset_sha256": current["dataset_sha256"],
        "fixture_sha256": current["fixture_sha256"],
        "comparison_scope": "NL_THINK_TOGGLE_NOT_PRODUCT_OR_FINE_TUNING_EVIDENCE",
        "policy": {
            "new_calls": 3,
            "historical_reference_calls": 3,
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
    return control.execute_registered_plan(
        plan,
        output,
        plan_sha256=plan_sha256,
        reconstruct_plan=lambda: make_plan(existing.inspect_diagnostic_model("presence_zero")),
        claim_directory=".ru-natural-reasoning-trials",
        reference_results=[deepcopy(c["historical_nl_result"]) for c in plan["cases"]],
        reference_metric="natural_language_historical_reference",
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
