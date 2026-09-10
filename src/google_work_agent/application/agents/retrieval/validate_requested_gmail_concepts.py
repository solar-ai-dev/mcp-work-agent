"""Validate preservation of request-owned Gmail concept hypotheses."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from google_work_agent.application.agents.retrieval.contracts.query_plan import (
    RetrievalV2ValidationError,
)
from google_work_agent.application.agents.retrieval.resolve_requested_gmail_concepts import (
    resolve_requested_gmail_concepts,
)
from google_work_agent.application.agents.tool_routing.contracts.tool_route_plan import (
    InputToolRouteV1,
)


def validate_requested_gmail_concepts(
    value: object,
    prompt_input: Mapping[str, object],
    frozen_routes: Sequence[InputToolRouteV1],
) -> None:
    """Keep each user-owned concept represented without prescribing its hypotheses."""
    if not isinstance(value, Mapping):
        return
    concepts_by_route = resolve_requested_gmail_concepts(prompt_input, frozen_routes)
    for query in value.get("route_queries", []):
        route_id = query.get("route_id")
        concepts = concepts_by_route.get(route_id, set())
        if not concepts:
            continue
        spec = query.get("search_spec")
        if not isinstance(spec, Mapping) or spec.get("mode") != "INITIAL":
            continue
        constraints = spec.get("constraints", [])
        hypotheses = [
            item
            for item in constraints
            if item.get("kind") == "CONCEPT" and item.get("concept") in concepts
        ]
        if not hypotheses:
            raise RetrievalV2ValidationError(
                "discovery hypothesis must retain a requested business concept",
                reason_code="QUERY_USER_CONSTRAINT_MISSING",
                affected_field_paths=("$.route_queries[].search_spec.constraints",),
            )
