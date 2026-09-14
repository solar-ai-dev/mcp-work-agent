"""Project resolved query bounds as search targets, never as source evidence."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from google_work_agent.application.agents.retrieval.contracts.query_plan import (
    TemporalRangeConstraintV1,
    validate_temporal_range_constraint,
)


def project_query_temporal_constraints(
    attempts: Sequence[Mapping[str, object]],
) -> list[TemporalRangeConstraintV1]:
    """Retain the initial search's temporal meaning through changed searches and detail reads."""
    routes: set[str] = set()
    result: list[TemporalRangeConstraintV1] = []
    for attempt in attempts:
        route_id = str(attempt["route_id"])
        if route_id in routes or attempt["operation_kind"] not in {"SEARCH", "FREEBUSY"}:
            continue
        routes.add(route_id)
        constraints = attempt["normalized_intent_constraints"]
        if not isinstance(constraints, list):
            raise ValueError("query attempt constraints must be a list")
        for constraint in constraints:
            if not isinstance(constraint, Mapping) or constraint.get("kind") != "TEMPORAL_RANGE":
                continue
            projected = validate_temporal_range_constraint(constraint)
            if projected not in result:
                result.append(projected)
    return result
