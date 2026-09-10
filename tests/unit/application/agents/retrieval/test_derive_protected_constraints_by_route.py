"""Tests for route-bound protected constraint derivation."""

from google_work_agent.application.agents.retrieval.derive_protected_constraints_by_route import (
    derive_protected_constraints_by_route,
)
from google_work_agent.application.agents.tool_routing.contracts.tool_route_plan import (
    InputToolRouteV1,
)


def test_derive_protected_constraints_by_route__mixed_routes__binds_searchable_gmail() -> None:
    routes: list[InputToolRouteV1] = [
        {
            "route_id": "message",
            "resource_type": "GMAIL_MESSAGE",
            "connector_id": "google_workspace",
            "allowed_read_tool_ids": ["gmail_get_message"],
            "required": True,
            "reason_codes": ["USER_REQUEST"],
        },
        {
            "route_id": "thread",
            "resource_type": "GMAIL_THREAD",
            "connector_id": "google_workspace",
            "allowed_read_tool_ids": ["gmail_search_threads"],
            "required": True,
            "reason_codes": ["USER_REQUEST"],
        },
    ]
    intent = {
        "constraints": [
            {
                "kind": "USER_REQUIREMENT",
                "field": "search_terms",
                "value": ["Nimbus"],
                "provenance": {
                    "source": "USER_REQUEST",
                    "start_offset": 0,
                    "end_offset": 6,
                },
            }
        ]
    }

    protected = derive_protected_constraints_by_route(
        request_intent=intent,
        frozen_routes=routes,
        required_constraint_kinds={route["route_id"]: () for route in routes},
        validated_resource_refs=None,
        validated_container_refs=None,
        now_ms=None,
        timezone=None,
    )

    assert protected == {
        "thread": [{"kind": "KEYWORD", "terms": ["Nimbus"], "match_mode": "PHRASE"}]
    }
