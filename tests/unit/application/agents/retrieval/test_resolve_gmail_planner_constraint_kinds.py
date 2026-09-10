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
