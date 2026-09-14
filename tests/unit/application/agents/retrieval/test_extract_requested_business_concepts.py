"""Tests for request-owned business concept extraction."""

from google_work_agent.application.agents.retrieval.extract_requested_business_concepts import (
    extract_requested_business_concepts,
)


def test_extract_requested_business_concepts__explicit_values__returns_unique_concepts() -> None:
    constraints = [
        {
            "kind": "USER_REQUIREMENT",
            "field": "business_concepts",
            "value": ["출시", "출시", "점검"],
        }
    ]

    assert extract_requested_business_concepts(constraints) == {"출시", "점검"}
