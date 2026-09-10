"""Resolve exact participant identities supplied by the current request."""

from __future__ import annotations

from collections.abc import Mapping
from typing import cast

from google_work_agent.application.agents.retrieval.contracts.query_plan import (
    ParticipantMatchV1,
)
from google_work_agent.application.agents.retrieval.derive_gmail_search_constraints import (
    derive_gmail_search_constraints,
)


def resolve_request_participants(
    prompt_input: Mapping[str, object],
) -> list[str]:
    """Only exact user-owned email values authorize initial hard participant filters."""
    intent = prompt_input.get("request_intent")
    if not isinstance(intent, Mapping):
        return []
    constraints = derive_gmail_search_constraints(
        intent.get("constraints"),
        now_ms=None,
        timezone=None,
    )
    return sorted(
        {
            str(person["identity"])
            for constraint in constraints
            if constraint["kind"] == "PARTICIPANT"
            for person in cast(list[ParticipantMatchV1], constraint["participants"])
        }
    )
