"""Tests for Gmail planner constraint-kind resolution."""

from google_work_agent.application.agents.retrieval.resolve_gmail_planner_constraint_kinds import (
    resolve_gmail_planner_constraint_kinds,
)


def test_resolve_gmail_planner_constraint_kinds__explicit_status__includes_status_scope() -> None:
    prompt_input = {
        "request_intent": {
            "constraints": [{"kind": "SCOPE", "field": "status", "value": ["DRAFT"]}]
        }
    }

    kinds = resolve_gmail_planner_constraint_kinds(prompt_input)

    assert kinds is not None and "STATUS_SCOPE" in kinds


def test_resolve_gmail_planner_constraint_kinds__business_concept__allows_planner_expression(
) -> None:
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

    kinds = resolve_gmail_planner_constraint_kinds(prompt_input)

    assert kinds is not None
    assert {"CONCEPT", "KEYWORD"}.issubset(kinds)
