"""Compare saved upstream inputs on their fixed synthetic Provider fixtures."""

from __future__ import annotations

import argparse
import hashlib
import json
import traceback
from copy import deepcopy
from pathlib import Path

from scripts.evaluate_retrieval_connected_segment import evaluate
from scripts.evaluate_retrieval_plan_query_node import _load_latest_state

from google_work_agent.application.agents.retrieval import plan_query as planner
from google_work_agent.application.agents.tool_routing.bind_registry_candidates import (
    coarse_resource_category,
)


def _hash(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()


def run(
    database: Path,
    checkpoint_root: Path,
    result_root: Path,
    *,
    variant: str,
    connect_work_analysis: bool = False,
    connect_planning_review: bool = False,
    preflight_only: bool = False,
    diagnostic_correct_source_binding: bool = False,
    case_id: str = "CASE-CORE-023",
) -> dict[str, object]:
    state = _load_latest_state(database)
    intent = deepcopy(state["request_intent"])
    route_plan = deepcopy(state["tool_route_plan"])
    if diagnostic_correct_source_binding:
        for source in intent["resource_responsibilities"]["source_reads"]:
            if source["resource_type"] == "TASK_LIST":
                source["resource_type"] = "TASK"
        intent["requested_resource_hints"] = [
            "TASK" if resource == "TASK_LIST" else resource
            for resource in intent["requested_resource_hints"]
        ]
        for route in route_plan["input_plan"]["input_routes"]:
            if route["resource_type"] == "TASK_LIST":
                route["reason_codes"] = ["RETRIEVAL_TASK_LIST_DISCOVERY"]
            elif route["resource_type"] == "TASK":
                route["reason_codes"] = ["REQUESTED_INPUT"]
    source = checkpoint_root / case_id / "state" / "data" / "google_work_agent.db"
    if not source.is_file():
        raise FileNotFoundError(source)
    if state["__request__"].request_text != _load_latest_state(source)["__request__"].request_text:
        raise ValueError("saved request differs from the fixed case fixture")
    result_root.mkdir(parents=True, exist_ok=True)
    result_path = result_root / f"{variant}.json"
    wrapper = {
        "variant": variant,
        "origin": (
            "SYNTHETIC_CORRECTED_RU_SYNTHETIC_PROVIDER"
            if diagnostic_correct_source_binding
            else "SAVED_BACKEND_UPSTREAM_SYNTHETIC_PROVIDER"
        ),
        "upstream_fingerprint": _hash({"intent": intent, "routes": route_plan}),
        "fixture_case": case_id,
        "result": None,
    }
    wrapper_path = result_root / f"{variant}-status.json"
    wrapper_path.write_text(json.dumps(wrapper, ensure_ascii=False, indent=2), encoding="utf-8")
    if preflight_only:
        return wrapper
    original = planner._prompt_route

    def projected_route(*args: object, **kwargs: object) -> dict[str, object]:
        projected = original(*args, **kwargs)
        resource_type = args[0]["resource_type"]
        projected["resource_type"] = (
            resource_type
            if variant == "exact_candidate"
            else coarse_resource_category(resource_type)
        )
        return projected

    planner._prompt_route = projected_route
    try:
        result = evaluate(
            checkpoint_root=checkpoint_root,
            result_path=result_path,
            case_ids=(case_id,),
            model_id="qwen3.5:9b",
            sampling_temperature=0,
            sampling_seed=1729,
            input_overrides={case_id: (intent, route_plan)},
            connect_work_analysis=connect_work_analysis,
            connect_planning_review=connect_planning_review,
        )
        wrapper["result"] = {
            "summary": result["summary"],
            "case_outcome": result["cases"][0]["outcome"],
        }
    except Exception as exc:
        wrapper["result"] = {
            "error_type": type(exc).__name__,
            "error": str(exc)[:500],
            "traceback": traceback.format_exc(limit=8),
        }
    finally:
        planner._prompt_route = original
        wrapper_path.write_text(
            json.dumps(wrapper, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
        )
    return wrapper


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--checkpoint-root", type=Path, required=True)
    parser.add_argument("--result-root", type=Path, required=True)
    parser.add_argument("--variant", choices=("coarse_baseline", "exact_candidate"), required=True)
    parser.add_argument("--connect-work-analysis", action="store_true")
    parser.add_argument("--connect-planning-review", action="store_true")
    parser.add_argument("--preflight-only", action="store_true")
    parser.add_argument("--diagnostic-correct-source-binding", action="store_true")
    parser.add_argument("--case-id", default="CASE-CORE-023")
    args = parser.parse_args()
    print(
        json.dumps(
            run(
                args.database,
                args.checkpoint_root,
                args.result_root,
                variant=args.variant,
                connect_work_analysis=args.connect_work_analysis,
                connect_planning_review=args.connect_planning_review,
                preflight_only=args.preflight_only,
                diagnostic_correct_source_binding=args.diagnostic_correct_source_binding,
                case_id=args.case_id,
            ),
            ensure_ascii=False,
            default=str,
        ),
        flush=True,
    )
