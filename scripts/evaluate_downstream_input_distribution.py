"""Inventory saved Work Analysis, Planning, and Review handoff availability."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import cast

from evaluation.dataset_v8 import load_cases
from scripts.evaluate_retrieval_plan_query_node import _load_latest_state

from google_work_agent.application.agents.request_understanding.contracts.request_intent import (
    RequestIntentV2,
)
from google_work_agent.application.agents.tool_routing.contracts.tool_route_plan import (
    ToolRoutePlanV2,
)
from google_work_agent.application.agents.tool_routing.resolve_policy_preconditions import (
    effective_analysis_required,
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--checkpoint-root", type=Path, required=True)
    parser.add_argument("--result-path", type=Path, required=True)
    parser.add_argument("--split", choices=("CORE", "STRESS", "HOLDOUT"), required=True)
    arguments = parser.parse_args()

    records: list[dict[str, object]] = []
    for case_id, case in load_cases().items():
        if case.raw.get("split") != arguments.split:
            continue
        database = (
            arguments.checkpoint_root
            / case_id
            / "state"
            / "data"
            / "google_work_agent.db"
        )
        if not database.is_file():
            records.append({"case_id": case_id, "outcome": "NO_CHECKPOINT"})
            continue
        state = _load_latest_state(database)
        intent = state.get("request_intent")
        plan = state.get("tool_route_plan")
        retrieval = state.get("retrieval_result")
        analysis = state.get("work_analysis_result")
        planning = state.get("planning_result")
        review = state.get("plan_review")
        has_intent = isinstance(intent, dict)
        has_plan = isinstance(plan, dict)
        has_retrieval = isinstance(retrieval, dict)
        has_analysis = isinstance(analysis, dict)
        has_planning = isinstance(planning, dict)
        has_review = isinstance(review, dict)
        analysis_required = (
            effective_analysis_required(
                request_intent=cast(RequestIntentV2, intent),
                tool_route_plan=cast(ToolRoutePlanV2, plan),
            )
            if has_intent and has_plan
            else None
        )
        work_analysis_input = bool(has_retrieval and analysis_required)
        planning_input = bool(
            has_intent
            and has_plan
            and has_retrieval
            and (not analysis_required or has_analysis)
        )
        record = {
            "case_id": case_id,
            "outcome": "CHECKPOINT_READ",
            "workflow_phase": state.get("workflow_phase"),
            "analysis_required": analysis_required,
            "work_analysis_input": work_analysis_input,
            "planning_input": planning_input,
            "review_input": has_planning,
            "has_work_analysis_result": has_analysis,
            "has_planning_result": has_planning,
            "has_plan_review": has_review,
            "retrieval_rounds": (
                retrieval.get("retrieval_rounds") if isinstance(retrieval, dict) else None
            ),
        }
        records.append(record)
    result = {
        "binding": {
            "checkpoint_corpus": arguments.checkpoint_root.name,
            "split": arguments.split,
            "execution_scope": "SAVED_CHECKPOINT_INVENTORY_ONLY",
            "llm_dispatch_enabled": False,
            "connector_dispatch_enabled": False,
        },
        "counts": {
            "case_count": len(records),
            "checkpoint_count": sum(
                record["outcome"] == "CHECKPOINT_READ" for record in records
            ),
            "work_analysis_input_count": sum(
                record.get("work_analysis_input") is True for record in records
            ),
            "planning_input_count": sum(
                record.get("planning_input") is True for record in records
            ),
            "review_input_count": sum(record.get("review_input") is True for record in records),
            "work_analysis_result_count": sum(
                record.get("has_work_analysis_result") is True for record in records
            ),
            "planning_result_count": sum(
                record.get("has_planning_result") is True for record in records
            ),
            "plan_review_count": sum(
                record.get("has_plan_review") is True for record in records
            ),
        },
        "cases": records,
    }
    arguments.result_path.parent.mkdir(parents=True, exist_ok=True)
    arguments.result_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(result["counts"], sort_keys=True))


if __name__ == "__main__":
    main()
