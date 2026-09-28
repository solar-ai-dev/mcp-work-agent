"""Tests for Gmail planner constraint-kind resolution."""

from google_work_agent.application.agents.retrieval.resolve_gmail_planner_constraint_kinds import (
    resolve_gmail_planner_constraint_kinds,
)
from google_work_agent.application.agents.tool_routing.contracts.tool_route_plan import (
    InputToolRouteV1,
)


def _legacy_route() -> InputToolRouteV1:
    return {
        "route_id": "mail",
        "resource_type": "GMAIL_THREAD",
        "connector_id": "google_workspace",
        "allowed_read_tool_ids": ["gmail_search_threads"],
        "required": True,
        "reason_codes": ["REQUESTED_INPUT"],
    }


def test_resolve_gmail_planner_constraint_kinds__explicit_status__includes_status_scope() -> None:
    prompt_input = {
        "request_intent": {
            "constraints": [{"kind": "SCOPE", "field": "status", "value": ["DRAFT"]}]
        }
    }

    kinds = resolve_gmail_planner_constraint_kinds(prompt_input, route=_legacy_route())

    assert kinds is not None and "STATUS_SCOPE" in kinds


def test_resolve_gmail_planner_constraint_kinds__business_concept__allows_planner_expression() -> (
    None
):
    prompt_input = {
        "request_intent": {
            "constraints": [
                {
                    "kind": "USER_REQUIREMENT",
                    "field": "business_concepts",
                    "value": ["출시 일정"],
                }
            ]
        }
    }

    kinds = resolve_gmail_planner_constraint_kinds(prompt_input, route=_legacy_route())

    assert kinds is not None
    assert {"CONCEPT", "KEYWORD"}.issubset(kinds)
