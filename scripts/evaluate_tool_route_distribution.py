"""Classify saved RequestIntent inputs at the Tool Route decision boundary."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import cast

from evaluation.dataset_v8 import load_cases
from scripts.evaluate_retrieval_plan_query_node import _load_latest_state

from google_work_agent.application.agents.request_understanding.contracts.request_intent import (
    RequestIntentV3,
)
from google_work_agent.application.agents.tool_routing.determine_io_resources import (
    determine_io_resources,
    requires_io_resource_inference,
)
from google_work_agent.application.tool_registry.load_signed_tool_registry import (
    load_development_tool_registry,
)
from google_work_agent.application.use_cases.run.guard_run_budget import (
    build_default_run_budget,
)
from google_work_agent.ports.llm.structured_inference_port import StructuredInferencePort
from google_work_agent.ports.system.contracts.workflow_execution import WorkflowStartRequest


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--checkpoint-root", type=Path, required=True)
    parser.add_argument("--result-path", type=Path, required=True)
    parser.add_argument("--split", choices=("CORE", "STRESS", "HOLDOUT"), required=True)
    arguments = parser.parse_args()

    catalog = load_development_tool_registry()
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
        if not database.exists():
            records.append({"case_id": case_id, "outcome": "NO_CHECKPOINT"})
            continue
        state = _load_latest_state(database)
        request = state.get("__request__")
        intent = state.get("request_intent")
        if not isinstance(request, WorkflowStartRequest) or not isinstance(intent, dict):
            records.append({"case_id": case_id, "outcome": "NO_INTENT"})
            continue
        typed_intent = cast(RequestIntentV3, intent)
        if requires_io_resource_inference(request_intent=typed_intent, request=request):
            records.append({"case_id": case_id, "outcome": "LLM_REQUIRED"})
            continue
        try:
            route, _ = determine_io_resources(
                llm_runtime=cast(StructuredInferencePort, None),
                tool_catalog=catalog,
                request_intent=typed_intent,
                request=request,
                retry_budget=build_default_run_budget(),
            )
            records.append(
                {
                    "case_id": case_id,
                    "outcome": "DETERMINISTIC",
                    "input_resource_types": list(route.input_resource_types),
                    "output_pairs": [
                        [resource_type, effect.value]
                        for resource_type, effect in route.output_pairs
                    ],
                    "output_mode": route.output_mode,
                }
            )
        except Exception as error:
            records.append(
                {
                    "case_id": case_id,
                    "outcome": "DETERMINISTIC_FAILED",
                    "error_type": type(error).__name__,
                    "reason_code": getattr(error, "reason_code", None),
                }
            )
    result = {
        "binding": {
            "checkpoint_corpus": arguments.checkpoint_root.name,
            "split": arguments.split,
            "connector_dispatch_enabled": False,
            "llm_dispatch_enabled": False,
        },
        "counts": {
            outcome: sum(record["outcome"] == outcome for record in records)
            for outcome in (
                "NO_CHECKPOINT",
                "NO_INTENT",
                "LLM_REQUIRED",
                "DETERMINISTIC",
                "DETERMINISTIC_FAILED",
            )
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
