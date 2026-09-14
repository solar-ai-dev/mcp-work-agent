"""Resolve request-owned business concepts for searchable Gmail routes."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from google_work_agent.application.agents.retrieval.extract_requested_business_concepts import (
    extract_requested_business_concepts,
)
from google_work_agent.application.agents.retrieval.is_searchable_gmail_route import (
    is_searchable_gmail_route,
)
from google_work_agent.application.agents.tool_routing.contracts.tool_route_plan import (
    InputToolRouteV1,
)


def resolve_requested_gmail_concepts(
    prompt_input: Mapping[str, object],
    frozen_routes: Sequence[InputToolRouteV1],
) -> dict[str, set[str]]:
    intent = prompt_input.get("request_intent")
    if not isinstance(intent, Mapping):
        return {}
    concepts = extract_requested_business_concepts(intent.get("constraints"))
    return {
        route["route_id"]: concepts
        for route in frozen_routes
        if is_searchable_gmail_route(route) and concepts
    }
