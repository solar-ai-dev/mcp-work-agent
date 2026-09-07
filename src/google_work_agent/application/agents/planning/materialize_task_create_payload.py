"""Materialize exact direct Task CREATE values from validated request intent."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date

_TASK_FIELD_KINDS = {
    "title": "RESOURCE",
    "notes": "RESOURCE",
    "scheduled_date": "DATE",
    "business_deadline": "DATE",
    "status": "SCOPE",
}
_NON_PAYLOAD_FIELDS = frozenset(
    {
        "search_terms",
        "task_list",
        "task_list_label",
    }
)
_REQUIRES_SEMANTIC_COMPOSITION = frozenset(
    {"business_concepts", "required_information", "original_search_request"}
)


def materialize_task_create_payload(
    request_intent: Mapping[str, object],
) -> dict[str, object] | None:
    """Return a payload only when every Task business value is exact and supported."""

    ambiguity = request_intent.get("ambiguity")
    constraints = request_intent.get("constraints")
    if (
        not isinstance(ambiguity, Mapping)
        or ambiguity.get("requires_confirmation") is not False
        or not isinstance(constraints, Sequence)
        or isinstance(constraints, (str, bytes))
        or request_intent.get("requested_effect_hints") != ["CREATE"]
        or request_intent.get("requested_resource_hints") != ["TASK"]
    ):
        return None

    values: dict[str, str] = {}
    for constraint in constraints:
        if not isinstance(constraint, Mapping):
            return None
        field = constraint.get("field")
        if not isinstance(field, str):
            return None
        value = _single_string(constraint.get("value"))
        if field in _REQUIRES_SEMANTIC_COMPOSITION:
            return None
        if field in _NON_PAYLOAD_FIELDS:
            continue
        expected_kind = _TASK_FIELD_KINDS.get(field)
        if expected_kind is None or constraint.get("kind") != expected_kind or value is None:
            return None
        prior = values.get(field)
        if prior is not None and prior != value:
            return None
        values[field] = value

    title = values.get("title")
    if not title:
        return None
    for field in ("scheduled_date", "business_deadline"):
        value = values.get(field)
        if value is not None and _iso_date(value) is None:
            return None
    status = values.get("status")
    if status is not None and status not in {"needsAction", "completed"}:
        return None
    return {
        field: values[field]
        for field in ("title", "notes", "scheduled_date", "business_deadline", "status")
        if field in values
    }


def _single_string(value: object) -> str | None:
    if isinstance(value, str):
        return value
    if isinstance(value, list) and len(value) == 1 and isinstance(value[0], str):
        return value[0]
    return None


def _iso_date(value: str) -> str | None:
    try:
        return date.fromisoformat(value).isoformat()
    except ValueError:
        return None


__all__ = ["materialize_task_create_payload"]
