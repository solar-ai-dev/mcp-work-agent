"""Tests for searchable Gmail route classification."""

from google_work_agent.application.agents.retrieval.is_searchable_gmail_route import (
    is_searchable_gmail_route,
)
from google_work_agent.application.agents.tool_routing.contracts.tool_route_plan import (
    InputToolRouteV1,
)


def test_is_searchable_gmail_route__search_tool_available__returns_true() -> None:
    route: InputToolRouteV1 = {
        "route_id": "gmail",
        "resource_type": "GMAIL_THREAD",
        "connector_id": "google_workspace",
        "allowed_read_tool_ids": ["gmail_get_thread", "gmail_search_threads"],
        "required": True,
        "reason_codes": ["USER_REQUEST"],
    }

    assert is_searchable_gmail_route(route) is True


def test_is_searchable_gmail_route__get_only_route__returns_false() -> None:
    route: InputToolRouteV1 = {
        "route_id": "gmail",
        "resource_type": "GMAIL_MESSAGE",
        "connector_id": "google_workspace",
        "allowed_read_tool_ids": ["gmail_get_message"],
        "required": True,
        "reason_codes": ["USER_REQUEST"],
    }

    assert is_searchable_gmail_route(route) is False
