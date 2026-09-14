"""Project bounded target facts for user-facing Action previews."""

from __future__ import annotations

from collections.abc import Mapping
from json import JSONDecodeError, loads

from google_work_agent.domain.evidence.model import Evidence
from google_work_agent.domain.resource_ref.model import ResourceRef

_DISPLAY_FIELDS_BY_RESOURCE_TYPE = {
    "calendar_event": frozenset({"title", "start", "end", "timezone"}),
    "task": frozenset({"title", "due", "status"}),
    "github_issue": frozenset({"title", "state"}),
    "gmail_draft": frozenset({"subject"}),
    "gmail_message": frozenset({"subject"}),
    "gmail_thread": frozenset({"subject"}),
}
_TITLE_FIELD_BY_RESOURCE_TYPE = {
    "gmail_draft": "subject",
    "gmail_message": "subject",
    "gmail_thread": "subject",
}
_MAX_DISPLAY_VALUE_CHARS = 500


def project_action_target_display(
    *,
    resource_ref: ResourceRef | None,
    evidence: tuple[Evidence, ...],
) -> dict[str, str]:
    """Return display-only facts without exposing opaque Provider identity."""

    if resource_ref is None:
        return {}
    allowed_fields = _DISPLAY_FIELDS_BY_RESOURCE_TYPE.get(resource_ref.resource_type)
    if allowed_fields is None:
        return {}

    projected: dict[str, str] = {}
    title_field = _TITLE_FIELD_BY_RESOURCE_TYPE.get(resource_ref.resource_type, "title")
    if (
        title_field in allowed_fields
        and resource_ref.title
        and resource_ref.title != resource_ref.resource_id
    ):
        projected[title_field] = resource_ref.title[:_MAX_DISPLAY_VALUE_CHARS]

    try:
        metadata = loads(resource_ref.metadata_json)
    except (JSONDecodeError, TypeError):
        metadata = {}
    if isinstance(metadata, dict):
        _merge_display_values(projected, metadata, allowed_fields)

    for record in evidence:
        if record.resource_ref_id != resource_ref.id:
            continue
        observed = _display_values_from_excerpt(record.excerpt)
        _merge_display_values(projected, observed, allowed_fields)
    return projected


def _display_values_from_excerpt(excerpt: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in excerpt.splitlines():
        key, separator, value = line.partition(":")
        if separator and key.strip() and value.strip():
            values[key.strip()] = value.strip()
    return values


def _merge_display_values(
    projected: dict[str, str],
    values: Mapping[str, object],
    allowed_fields: frozenset[str],
) -> None:
    for field in allowed_fields:
        value = values.get(field)
        if isinstance(value, str) and value:
            projected[field] = value[:_MAX_DISPLAY_VALUE_CHARS]


__all__ = ["project_action_target_display"]
