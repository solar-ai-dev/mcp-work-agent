"""Tests for request-owned Gmail concept resolution."""

from google_work_agent.application.agents.retrieval.resolve_requested_gmail_concepts import (
    resolve_requested_gmail_concepts,
)
from google_work_agent.application.agents.tool_routing.contracts.tool_route_plan import (
    InputToolRouteV1,
)


def test_resolve_requested_gmail_concepts__searchable_route__binds_concept() -> None:
    route: InputToolRouteV1 = {
        "route_id": "gmail",
        "resource_type": "GMAIL_THREAD",
        "connector_id": "google_workspace",
        "allowed_read_tool_ids": ["gmail_search_threads"],
        "required": True,
        "reason_codes": ["USER_REQUEST"],
    }
    prompt_input = {
        "request_intent": {
            "constraints": [
                {
                    "kind": "USER_REQUIREMENT",
                    "field": "business_concepts",
                    "value": ["출시"],
                }
            ]
        }
    }

    assert resolve_requested_gmail_concepts(prompt_input, [route]) == {"gmail": {"출시"}}
