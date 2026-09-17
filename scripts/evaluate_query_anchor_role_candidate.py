"""Inactive Node experiment: do not promote descriptive search_terms to exact anchors."""

from __future__ import annotations

import argparse
import importlib
import json
from collections.abc import Mapping, Sequence
from pathlib import Path

from scripts.evaluate_retrieval_plan_query_node import evaluate

from google_work_agent.application.agents.retrieval.is_searchable_gmail_route import (
    is_searchable_gmail_route,
)
from google_work_agent.application.agents.tool_routing.contracts.tool_route_plan import (
    InputToolRouteV1,
)


def _current_search_terms(prompt_input: Mapping[str, object]) -> set[str]:
    intent = prompt_input.get("request_intent")
    constraints = intent.get("constraints") if isinstance(intent, Mapping) else None
    if not isinstance(constraints, list):
        return set()
    return {
        value.strip()
        for item in constraints
        if isinstance(item, Mapping)
        and item.get("field") == "search_terms"
        and item.get("kind") == "USER_REQUIREMENT"
        and isinstance(item.get("provenance"), Mapping)
        and item["provenance"].get("source") in {"USER_REQUEST", "CONFIRMATION_RESPONSE"}
        for value in (
            item.get("value") if isinstance(item.get("value"), list) else [item.get("value")]
        )
        if isinstance(value, str) and value.strip()
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--checkpoint-root", type=Path, required=True)
    parser.add_argument("--result-path", type=Path, required=True)
    parser.add_argument("--variant", choices=("role_only", "concept_slot"), required=True)
    arguments = parser.parse_args()
    planner = importlib.import_module("google_work_agent.application.agents.retrieval.plan_query")
    previous = planner._USER_QUERY_ANCHOR_FIELDS
    previous_kinds = planner.resolve_gmail_planner_constraint_kinds
    previous_concepts = planner.resolve_requested_gmail_concepts
    if "search_terms" not in previous:
        raise ValueError("baseline no longer classifies search_terms as exact")
    planner._USER_QUERY_ANCHOR_FIELDS = previous - {"search_terms"}
    if arguments.variant == "concept_slot":

        def role_kinds(prompt_input: Mapping[str, object]) -> set[str] | None:
            kinds = previous_kinds(prompt_input)
            if kinds is None or not _current_search_terms(prompt_input):
                return kinds
            exact, participants, _ = planner._trusted_query_anchors(prompt_input)
            if exact or participants:
                return kinds
            return (kinds - {"KEYWORD"}) | {"CONCEPT"}

        def role_concepts(
            prompt_input: Mapping[str, object], frozen_routes: Sequence[InputToolRouteV1]
        ) -> dict[str, set[str]]:
            concepts = previous_concepts(prompt_input, frozen_routes)
            terms = _current_search_terms(prompt_input)
            if not terms:
                return concepts
            return {
                **concepts,
                **{
                    route["route_id"]: terms
                    for route in frozen_routes
                    if is_searchable_gmail_route(route)
                },
            }

        planner.resolve_gmail_planner_constraint_kinds = role_kinds
        planner.resolve_requested_gmail_concepts = role_concepts
    try:
        result = evaluate(
            checkpoint_root=arguments.checkpoint_root.resolve(),
            result_path=arguments.result_path.resolve(),
            split="CORE",
            case_ids=tuple(f"CASE-CORE-{number:03d}" for number in (6, 7, 8, 10, 15, 23)),
            limit=None,
            model_id="qwen3.5:9b",
            sampling_temperature=0,
            sampling_seed=1729,
            candidate_id=f"041-{arguments.variant}",
        )
    finally:
        planner._USER_QUERY_ANCHOR_FIELDS = previous
        planner.resolve_gmail_planner_constraint_kinds = previous_kinds
        planner.resolve_requested_gmail_concepts = previous_concepts
    print(json.dumps(result["summary"], ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
