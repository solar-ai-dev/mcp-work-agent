"""Identify Gmail input routes that expose the canonical SEARCH operation."""

from google_work_agent.application.agents.retrieval.contracts.query_plan import (
    route_operation_tool_id,
)
from google_work_agent.application.agents.tool_routing.contracts.tool_route_plan import (
    InputToolRouteV1,
)

_GMAIL_SEARCH_RESOURCE_TYPES = frozenset({"GMAIL_THREAD", "GMAIL_MESSAGE", "GMAIL_DRAFT"})


def is_searchable_gmail_route(route: InputToolRouteV1) -> bool:
    return (
        route["resource_type"] in _GMAIL_SEARCH_RESOURCE_TYPES
        and route_operation_tool_id(route, "SEARCH") is not None
    )
