"""Tests for deterministic Gmail constraint derivation."""

from google_work_agent.application.agents.retrieval.derive_gmail_search_constraints import (
    derive_gmail_search_constraints,
)


def test_derive_gmail_search_constraints__validated_literal__returns_keyword_constraint() -> None:
    constraints = [
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

    assert derive_gmail_search_constraints(
        constraints,
        now_ms=None,
        timezone=None,
        require_validated_provenance=True,
    ) == [{"kind": "KEYWORD", "terms": ["Nimbus"], "match_mode": "PHRASE"}]
