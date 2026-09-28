"""Eight partial Source-owner FIRSTs; unassessed Resources remain unassessed."""

from __future__ import annotations

import argparse
import json
from copy import deepcopy
from pathlib import Path
from typing import Any

from scripts import evaluate_ru_semantic_capability as control
from scripts import ru_source_focal_candidate as candidate
from scripts.evaluate_effect_prohibition_sampler import write_json
from scripts.ru_observation import metrics, object_hash

existing, ROOT, RESULTS = control.existing, control.ROOT, control.RESULTS
CORE_IDS = ("CASE-CORE-017", "CASE-CORE-049", "CASE-CORE-005")
FOCUSES = ("TASK", "GMAIL_DRAFT")
SYNTHETIC_RAW = RESULTS / "064-source-membership-v43-t1/raw.json"
SYNTHETIC_HASH = "b5a6419ec305e213d01d377b6b91eb04310752af923a380de3037fdb442897ac"
CONTROL_IDS = ("SYNTHETIC-DRAFT-UPDATE", "SYNTHETIC-DRAFT-CREATE")
CRITERIA = "evaluation/experiments/076-source-focal-criteria.md"


def make_plan(model: dict[str, Any]) -> dict[str, Any]:
    current = control.make_plan(model)
    cases, references = [], []

    def append(
        source: dict[str, Any],
        payload: dict[str, Any],
        focuses: tuple[str, ...],
        group: str,
        row: dict[str, Any],
    ) -> None:
        references.append({**deepcopy(row), "group": group, "new_call": False})
        for focus in focuses:
            focal_payload = candidate.build_payload(payload, focus)
            cases.append(
                {
                    "case_id": source["case_id"],
                    "group": group,
                    "focus_resource_type": focus,
                    "source_call": deepcopy(source["source_call"]),
                    "case_binding": deepcopy(
                        source.get(
                            "case_binding",
                            {
                                "control_sha256": source.get("control_sha256"),
                                "provider_fixture_claim": False,
                            },
                        )
                    ),
                    "candidate_payload": focal_payload,
                    "candidate_wire_sha256": object_hash(focal_payload),
                    "candidate_input_sha256": object_hash(
                        json.loads(focal_payload["prompt"])["input"]
                    ),
                    "original_wire_sha256": object_hash(payload),
                }
            )

    for case_id in CORE_IDS:
        source = next(c for c in current["cases"] if c["case_id"] == case_id)
        append(
            source,
            existing.reconstruct_payload(source["source_call"]),
            FOCUSES,
            "CORE",
            source["historical_source_result"],
        )
    if existing.file_hash(SYNTHETIC_RAW) != SYNTHETIC_HASH:
        raise ValueError("synthetic frozen raw changed")
    raw = control.shared.read_json(SYNTHETIC_RAW)
    if not raw["completed"] or raw["binding"]["model"] != model:
        raise ValueError("complete synthetic baseline and identical model required")
    for case_id in CONTROL_IDS:
        sources = [c for c in raw["binding"]["cases"] if c["case_id"] == case_id]
        rows = [r for r in raw["calls"] if r["case_id"] == case_id and r["arm"] == "baseline"]
        if len(sources) != 1 or len(rows) != 1:
            raise ValueError("one actual synthetic baseline per control required")
        source, row = sources[0], rows[0]
        payload = existing.reconstruct_payload(
            {
                **source["source_call"],
                "state": row["state"],
                "wire_request_count": row["wire_request_count"],
                "wire_path": "/api/generate",
            }
        )
        if (
            payload != source["payload"]
            or payload != row["payload"]
            or object_hash(payload) != row["wire_sha256"]
            or object_hash(source["source_call"]["input"]) != row["input_sha256"]
            or row["done"] is not True
            or row["model"] != model["model_id"]
            or existing.validate_response(row["content"], {**source, "owner": "source"})
            != row["validation"]
        ):
            raise ValueError("current synthetic wire/owner differs from frozen baseline")
        append(source, payload, ("GMAIL_DRAFT",), "SYNTHETIC", row)
    hashes = dict(current["source_hashes"])
    for path in (
        "scripts/evaluate_source_focal.py",
        "scripts/ru_source_focal_candidate.py",
        "tests/evaluation/test_source_focal_candidate.py",
        "docs/canonical/15-agent-capability-failure-prompt-contract.md",
        CRITERIA,
    ):
        hashes[path] = existing.file_hash(ROOT / path)
    return {
        "kind": "PARTIAL_SOURCE_FOCAL_FIRST_076",
        "head_sha": current["head_sha"],
        "model": model,
        "cases": cases,
        "historical_references": references,
        "source_hashes": hashes,
        "source_reference_head": current["baseline_head"],
        "synthetic_reference_head": raw["binding"]["head_sha"],
        "source_reference_raw_sha256": current["baseline_raw_sha256"],
        "synthetic_raw_sha256": SYNTHETIC_HASH,
        "dataset_sha256": current["dataset_sha256"],
        "fixture_sha256": current["fixture_sha256"],
        "policy": {
            "new_calls": 8,
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
        "scope": "PARTIAL_RESOURCE_DECISIONS_NOT_COMPLETE_SOURCE_RESULT",
    }


def execute_plan(plan: dict[str, Any], output: Path, *, plan_sha256: str) -> dict[str, Any]:
    raw = control.execute_registered_plan(
        plan,
        output,
        plan_sha256=plan_sha256,
        reconstruct_plan=lambda: make_plan(existing.inspect_diagnostic_model("presence_zero")),
        claim_directory=".source-focal-trials",
        reference_results=plan["historical_references"],
        reference_metric="whole_source_reference_not_same_workload",
    )
    pairs = list(zip(plan["cases"][: len(raw["calls"])], raw["calls"], strict=True))
    if any(
        c["case_id"] != r["case_id"] or c["candidate_payload"] != r["payload"] for c, r in pairs
    ):
        raise ValueError("recorded focal order/wire differs from plan")
    admission = {
        "raw_sha256": existing.file_hash(output / "raw.json"),
        "scope": plan["scope"],
        "cases": [
            {
                "case_id": c["case_id"],
                "focus_resource_type": c["focus_resource_type"],
                "group": c["group"],
                **candidate.admit_focus(r.get("content"), r["payload"]),
            }
            for c, r in pairs
        ],
        "metrics_by_group": {
            group: metrics([r for c, r in pairs if c["group"] == group])
            for group in ("CORE", "SYNTHETIC")
        },
        "semantic_verdict": "NOT_REVIEWED",
        "business_success": "NOT_EVALUATED",
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
