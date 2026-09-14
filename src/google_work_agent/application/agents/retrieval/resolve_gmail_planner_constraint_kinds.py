"""Resolve Gmail constraint kinds eligible for semantic query planning."""

from __future__ import annotations

from collections.abc import Mapping

from google_work_agent.application.agents.retrieval.contracts.query_plan import (
    RetrievalV2ValidationError,
    validate_participant_identity,
)
from google_work_agent.application.agents.retrieval.extract_requested_business_concepts import (
    extract_requested_business_concepts,
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
_KEYWORD_FIELDS = frozenset({"subject", "search_criteria_subject", "search_terms"})
_GMAIL_STATUS_VALUES = frozenset({"ANY", "DRAFT", "SENT"})


def resolve_gmail_planner_constraint_kinds(
    prompt_input: Mapping[str, object],
) -> set[str] | None:
    """Narrow optional lexical/status filters to current user meaning, not examples."""
    intent = prompt_input.get("request_intent")
    if not isinstance(intent, Mapping):
        return None
    constraints = intent.get("constraints")
    if not isinstance(constraints, list) or not constraints:
        return None
    kinds = {
        "CONTAINER_REF",
        "RESOURCE_REF",
        "PARTICIPANT",
    }
    for constraint in constraints:
        if not isinstance(constraint, Mapping):
            continue
        field = str(constraint.get("field", "")).strip().lower()
        kind = str(constraint.get("kind", "")).upper()
        value = constraint.get("value")
        values = value if isinstance(value, list) else [value]
        if field in _KEYWORD_FIELDS:
            kinds.add("KEYWORD")
        elif field in _PARTICIPANT_FIELDS:
            if any(_is_exact_participant(item) for item in values):
                kinds.add("PARTICIPANT")
            else:
                kinds.add("KEYWORD")
        elif field == "status" and any(
            isinstance(item, str) and "".join(item.split()).upper() in _GMAIL_STATUS_VALUES
            for item in values
        ):
            kinds.add("STATUS_SCOPE")
        if kind in {"DATE", "TIME"}:
            kinds.add("TEMPORAL_RANGE")
    if extract_requested_business_concepts(constraints):
        kinds.update({"CONCEPT", "KEYWORD"})
    if kinds == {"CONTAINER_REF", "RESOURCE_REF", "PARTICIPANT"}:
        # Missing RU search fields are not evidence that the original request has
        # no lexical meaning. Keep the planner's bounded discovery capability;
        # exact participants, periods and statuses still require their own facts.
        kinds.add("KEYWORD")
    return kinds


def _is_exact_participant(value: object) -> bool:
    try:
        validate_participant_identity(value)
    except RetrievalV2ValidationError:
        return False
    return True
