"""Derive route-bound constraints that semantic query planning must preserve."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from google_work_agent.application.agents.retrieval.contracts.query_plan import (
    ProtectedConstraintsByRouteV1,
    RetrievalConstraintKindV1,
    SemanticRetrievalConstraintV1,
)
from google_work_agent.application.agents.retrieval.derive_gmail_search_constraints import (
    derive_gmail_search_constraints,
)
from google_work_agent.application.agents.retrieval.is_searchable_gmail_route import (
    is_searchable_gmail_route,
)
from google_work_agent.application.agents.tool_routing.contracts.tool_route_plan import (
    InputToolRouteV1,
)


def derive_protected_constraints_by_route(
    *,
    request_intent: Mapping[str, object],
    frozen_routes: Sequence[InputToolRouteV1],
    required_constraint_kinds: Mapping[str, Sequence[RetrievalConstraintKindV1]],
    validated_resource_refs: Mapping[str, Sequence[str]] | None,
    validated_container_refs: Mapping[str, Sequence[str]] | None,
    now_ms: int | None,
    timezone: str | None,
) -> ProtectedConstraintsByRouteV1:
    """Project only verified literals and deterministic route bindings as protected data."""
    constraints = request_intent.get("constraints")
    result: dict[str, list[SemanticRetrievalConstraintV1]] = {}
    for route in frozen_routes:
        route_id = route["route_id"]
        protected: list[SemanticRetrievalConstraintV1] = []
        if is_searchable_gmail_route(route):
            protected.extend(
                derive_gmail_search_constraints(
                    constraints,
                    now_ms=now_ms,
                    timezone=timezone,
                    source_resource_type=route["resource_type"],
                    require_validated_provenance=True,
                )
            )
        required = set(required_constraint_kinds.get(route_id, ()))
        container_refs = list(dict.fromkeys((validated_container_refs or {}).get(route_id, ())))
        if "CONTAINER_REF" in required and container_refs:
            protected.append({"kind": "CONTAINER_REF", "container_refs": container_refs})
        resource_refs = list(dict.fromkeys((validated_resource_refs or {}).get(route_id, ())))
        if "RESOURCE_REF" in required and resource_refs:
            protected.append({"kind": "RESOURCE_REF", "resource_refs": resource_refs})
        if protected:
            result[route_id] = protected
    return result
