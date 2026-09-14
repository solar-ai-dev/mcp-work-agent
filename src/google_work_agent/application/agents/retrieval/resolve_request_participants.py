"""Resolve exact participant identities supplied by the current request."""

from __future__ import annotations

from collections.abc import Mapping

from google_work_agent.application.agents.retrieval.contracts.query_plan import (
    RetrievalV2ValidationError,
    validate_participant_identity,
)

_PARTICIPANT_FIELDS = frozenset(
    {
        "sender",
        "sender_email",
        "from",
        "recipient",
        "recipient_email",
        "to",
        "search_criteria_sender",
        "search_criteria_recipient",
        "person",
    }
)


def resolve_request_participants(
    prompt_input: Mapping[str, object],
) -> list[str]:
    """Only exact user-owned email values authorize initial hard participant filters."""
    intent = prompt_input.get("request_intent")
    if not isinstance(intent, Mapping):
        return []
    constraints = intent.get("constraints")
    if not isinstance(constraints, list):
        return []
    identities: set[str] = set()
    for constraint in constraints:
        if not isinstance(constraint, Mapping):
            continue
        if str(constraint.get("field", "")).strip().lower() not in _PARTICIPANT_FIELDS:
            continue
        value = constraint.get("value")
        values = value if isinstance(value, list) else [value]
        for item in values:
            try:
                identities.add(validate_participant_identity(item))
            except RetrievalV2ValidationError:
                continue
    return sorted(identities)
