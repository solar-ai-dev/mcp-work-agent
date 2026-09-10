"""Validate that Gmail lexical and structured status roles remain separate."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import cast

from google_work_agent.application.agents.retrieval.contracts.query_plan import (
    RetrievalV2ValidationError,
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


def validate_gmail_search_role_separation(
    value: object,
    prompt_input: Mapping[str, object],
    frozen_routes: Sequence[InputToolRouteV1],
) -> None:
    """Reject a lexical over-constraint when status already owns that search role."""
    intent = prompt_input.get("request_intent")
    if not isinstance(intent, Mapping) or not isinstance(value, Mapping):
        return
    gmail_routes = {
        route["route_id"]: route
        for route in frozen_routes
        if is_searchable_gmail_route(route)
    }
    route_queries = value.get("route_queries")
    if not isinstance(route_queries, list):
        return
    for query in route_queries:
        if (
            not isinstance(query, Mapping)
            or query.get("route_id") not in gmail_routes
            or query.get("operation") != "SEARCH"
        ):
            continue
        route = gmail_routes[cast(str, query["route_id"])]
        explicit_constraints = derive_gmail_search_constraints(
            intent.get("constraints"),
            now_ms=None,
            timezone=None,
            source_resource_type=route["resource_type"],
        )
        expected_keywords = next(
            (
                {_normalized_text(term) for term in cast(list[str], item["terms"])}
                for item in explicit_constraints
                if item["kind"] == "KEYWORD"
            ),
            set(),
        )
        expected_statuses = next(
            (
                set(cast(list[str], item["values"]))
                for item in explicit_constraints
                if item["kind"] == "STATUS_SCOPE"
            ),
            set(),
        )
        if not expected_keywords or not expected_statuses:
            continue
        search_spec = query.get("search_spec")
        if not isinstance(search_spec, Mapping) or search_spec.get("mode") != "INITIAL":
            continue
        constraints = search_spec.get("constraints")
        if not isinstance(constraints, list):
            continue
        actual_statuses = {
            status
            for item in constraints
            if isinstance(item, Mapping) and item.get("kind") == "STATUS_SCOPE"
            for status in item.get("values", [])
            if isinstance(status, str)
        }
        actual_keywords = {
            _normalized_text(term)
            for item in constraints
            if isinstance(item, Mapping) and item.get("kind") == "KEYWORD"
            for term in item.get("terms", [])
            if isinstance(term, str)
        }
        if actual_statuses & expected_statuses and actual_keywords - expected_keywords:
            raise RetrievalV2ValidationError(
                "lexical query duplicates or extends a structured Gmail status scope",
                reason_code="RETRIEVAL_QUERY_PLAN_SEMANTIC_INVALID",
                affected_field_paths=(
                    "$.route_queries[].search_spec.constraints[?(@.kind=='KEYWORD')]",
                    "$.route_queries[].search_spec.constraints[?(@.kind=='STATUS_SCOPE')]",
                ),
            )


def _normalized_text(value: str) -> str:
    return "".join(value.split()).casefold()
