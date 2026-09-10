"""Resolve Gmail constraint kinds eligible for semantic query planning."""

from __future__ import annotations

from collections.abc import Mapping

from google_work_agent.application.agents.retrieval.derive_gmail_search_constraints import (
    derive_gmail_search_constraints,
)
from google_work_agent.application.agents.retrieval.extract_requested_business_concepts import (
    extract_requested_business_concepts,
)


def resolve_gmail_planner_constraint_kinds(
    prompt_input: Mapping[str, object],
) -> set[str] | None:
    """Narrow optional lexical/status filters to current user meaning, not examples."""
    intent = prompt_input.get("request_intent")
    if not isinstance(intent, Mapping):
        return None
    constraints = intent.get("constraints")
    if not isinstance(constraints, list) or not constraints:
        return None
    explicit = derive_gmail_search_constraints(constraints, now_ms=None, timezone=None)
    kinds = {str(item["kind"]) for item in explicit} | {
        "CONTAINER_REF",
        "RESOURCE_REF",
        "PARTICIPANT",
    }
    if extract_requested_business_concepts(constraints):
        kinds.add("CONCEPT")
    if any(
        isinstance(item, Mapping) and item.get("kind") in {"DATE", "TIME"}
        for item in constraints
    ):
        kinds.add("TEMPORAL_RANGE")
    if kinds == {"CONTAINER_REF", "RESOURCE_REF", "PARTICIPANT"}:
        # Missing RU search fields are not evidence that the original request has
        # no lexical meaning. Keep the planner's bounded discovery capability;
        # exact participants, periods and statuses still require their own facts.
        kinds.add("KEYWORD")
    return kinds
