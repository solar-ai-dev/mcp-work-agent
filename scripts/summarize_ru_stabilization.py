"""Reproduce 063 accounting and reviewed prefix counts without model calls."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any

from google_work_agent.application.agents.request_understanding import (
    identify_source_dependencies as source_ops,
)
from google_work_agent.application.tool_registry.load_signed_tool_registry import (
    load_development_tool_registry,
)
from google_work_agent.ports.llm.output_schema_validation import validate_output_schema

RUNS = {
    "production": "ru-tool-route-canonical92-20260924-50ff0879",
    "v4": "ru-goal-output-modality-v4-canonical92-trial1-20260924",
    "v6": "063-source-demand-v6-replay-t1",
    "v7": "063-source-needs-v7-replay-t1",
    "v8": "063-joint-roles-v8-core9-t1",
    "v9": "063-keyed-source-v9-replay-t1",
    "v10": "063-format-only-source-v10-replay-t1",
}


def reference(record: dict[str, Any]) -> Any:
    for item in record.get("atomic", []):
        if item["prompt_id"] == "request_understanding.identify_goal":
            base = item["input"].get("base_projection", item["input"])
            return base.get("run_reference_time")
    return None


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise ValueError("preserve existing summary")
    review_path = Path("evaluation/experiments/063-semantic-review.json")
    review = json.loads(review_path.read_text(encoding="utf-8"))
    ids = {item["case_id"] for item in review["connected_core9"]}
    summary: dict[str, Any] = {
        "review_sha256": hashlib.sha256(review_path.read_bytes()).hexdigest(),
        "runs": {},
        "counts": {},
    }
    records = {}
    source_candidates = source_ops.build_source_dependency_candidates(
        load_development_tool_registry()
    )
    for name, directory in RUNS.items():
        path = Path("evaluation/results") / directory / "raw.json"
        content = path.read_bytes()
        raw = json.loads(content)
        rows = [item for item in raw["cases"] if item["case_id"] in ids]
        records[name] = {item["case_id"]: item for item in rows}
        summary["runs"][name] = {
            "path": str(path),
            "sha256": hashlib.sha256(content).hexdigest(),
            "case_count": len(rows),
            "scope": raw["binding"]["scope"],
            "status_counts": dict(Counter(item["status"] for item in rows)),
            "metrics": {
                key: sum(item["llm"].get(key, 0) for item in rows)
                for key in ("calls", "input_tokens", "output_tokens", "reported_latency_ms")
            },
            "transport_observed": all("transport_calls" in item for item in rows),
            "binding": raw["binding"],
        }
        if raw["binding"]["scope"] == "SOURCE_INPUT_REPLAY":
            failures = {}
            for row in rows:
                if "source_output" not in row:
                    failures[row["case_id"]] = [row.get("error", row["status"])]
                    continue
                source_input = row["atomic"][0]["input"]
                base = source_input.get("base_projection", source_input)
                schema = source_ops.build_source_dependency_output_schema(
                    source_candidates,
                    work_unit_ids=[
                        unit["unit_id"] for unit in base["requested_work"]["work_units"]
                    ],
                )
                errors = list(validate_output_schema(row["source_output"], schema.json_schema))
                if errors:
                    failures[row["case_id"]] = errors
            summary["runs"][name]["source_contract_failures"] = failures
            summary["runs"][name]["source_contract_valid"] = len(rows) - len(failures)
    for name in ("production", "v4", "v8"):
        summary["counts"][name] = dict(Counter(item[name] for item in review["connected_core9"]))
    summary["regressions"] = {
        "production_to_v8": [
            item["case_id"]
            for item in review["connected_core9"]
            if item["production"] == "PASS" and item["v8"] != "PASS"
        ],
        "v4_to_v8": [
            item["case_id"]
            for item in review["connected_core9"]
            if item["v4"] == "PASS" and item["v8"] != "PASS"
        ],
    }
    summary["reference_time_differences"] = {
        name: [
            case_id
            for case_id in sorted(ids)
            if reference(records[name][case_id]) != reference(records["v4"][case_id])
        ]
        for name in ("production", "v8")
    }
    summary["new_model_calls"] = sum(
        summary["runs"][name]["metrics"]["calls"] for name in ("v6", "v7", "v8", "v9", "v10")
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {key: value for key, value in summary.items() if key != "runs"},
            ensure_ascii=False,
            indent=2,
        )
    )
    print(json.dumps({name: value["metrics"] for name, value in summary["runs"].items()}, indent=2))
    print(
        json.dumps(
            {
                name: value.get("source_contract_failures")
                for name, value in summary["runs"].items()
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
