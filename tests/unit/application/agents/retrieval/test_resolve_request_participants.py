"""Tests for exact request participant resolution."""

from google_work_agent.application.agents.retrieval.resolve_request_participants import (
    resolve_request_participants,
)


def test_resolve_request_participants__exact_email__returns_identity() -> None:
    prompt_input = {
        "request_intent": {
            "constraints": [
                {
                    "kind": "EMAIL",
                    "field": "sender",
                    "value": ["person@example.com"],
                }
            ]
        }
    }

    assert resolve_request_participants(prompt_input) == ["person@example.com"]
