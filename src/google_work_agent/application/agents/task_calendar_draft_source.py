"""Shared deterministic semantics for a Task + Calendar grounded Gmail Draft."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import TypedDict


class TaskCalendarSourceTerms(TypedDict):
    task_terms: list[str]
    calendar_provider_terms: list[str]
    calendar_evidence_terms: list[str]


_CALENDAR_NOUN = re.compile(
    r"일정|캘린더\s*이벤트|\bcalendar\s+events?\b|\bevents?\b",
    re.IGNORECASE,
)
_CALENDAR_SUFFIX = re.compile(
    r"(?:\s*(?:일정|캘린더\s*이벤트|calendar\s+events?|events?))+(?:\s*보고)?$",
    re.IGNORECASE,
)
_TASK_NOUN = re.compile(r"할\s*일|태스크|\bto-?do\b|\btasks?\b", re.IGNORECASE)
_TASK_SUFFIX = re.compile(
    r"(?:\s*(?:할\s*일|태스크|to-?do|tasks?))+$",
    re.IGNORECASE,
)


def is_task_calendar_draft_source_target(request_intent: Mapping[str, object]) -> bool:
    responsibilities = request_intent.get("resource_responsibilities")
    if not isinstance(responsibilities, Mapping):
        return False
    source_reads = responsibilities.get("source_reads")
    outputs = responsibilities.get("outputs")
    if not isinstance(source_reads, list) or not isinstance(outputs, list):
        return False
    source_resources = {
        item.get("resource_type")
        for item in source_reads
        if isinstance(item, Mapping)
    }
    return source_resources == {"TASK", "CALENDAR_EVENT"} and any(
        isinstance(item, Mapping)
        and item.get("resource_type") == "GMAIL_DRAFT"
        and item.get("effect") == "CREATE"
        for item in outputs
    )


def project_task_calendar_source_terms(value: object) -> TaskCalendarSourceTerms | None:
    if not isinstance(value, list):
        return None
    unqualified: list[tuple[int, str]] = []
    task_specific: list[tuple[int, str]] = []
    calendar_specific: list[tuple[int, str]] = []
    for constraint in value:
        if (
            not isinstance(constraint, Mapping)
            or constraint.get("kind") != "USER_REQUIREMENT"
            or constraint.get("field") != "search_terms"
        ):
            continue
        provenance = constraint.get("provenance")
        raw = constraint.get("value")
        if (
            not isinstance(provenance, Mapping)
            or provenance.get("source") != "USER_REQUEST"
            or not isinstance(raw, str)
            or not raw.strip()
        ):
            continue
        literal = raw.strip()
        offset = provenance.get("start_offset")
        position = offset if isinstance(offset, int) and not isinstance(offset, bool) else 2**31
        if _CALENDAR_NOUN.search(literal):
            calendar_specific.append(
                (position, _CALENDAR_SUFFIX.sub("", literal).strip() or literal)
            )
        elif _TASK_NOUN.search(literal):
            task_specific.append((position, _TASK_SUFFIX.sub("", literal).strip() or literal))
        elif "@" not in literal:
            unqualified.append((position, literal))
    recovered = _project_source_bound_business_terms(value)
    if recovered is not None and not task_specific:
        return recovered
    project_term = next((value for _, value in sorted(unqualified)), None)
    task_values = [value for _, value in sorted(task_specific)]
    calendar_values = [value for _, value in sorted(calendar_specific)]
    task_terms = _unique([project_term, *task_values])
    calendar_provider_terms = _unique(
        calendar_values or ([project_term] if project_term else [])
    )
    calendar_evidence_terms = _unique([project_term, *calendar_values])
    if not task_terms or not calendar_provider_terms or not calendar_evidence_terms:
        return None
    return {
        "task_terms": task_terms,
        "calendar_provider_terms": calendar_provider_terms,
        "calendar_evidence_terms": calendar_evidence_terms,
    }


def _project_source_bound_business_terms(
    constraints: Sequence[object],
) -> TaskCalendarSourceTerms | None:
    source_texts = [
        text
        for constraint in constraints
        if isinstance(constraint, Mapping)
        and constraint.get("kind") == "USER_REQUIREMENT"
        and constraint.get("field") == "original_search_request"
        for text in _strings(constraint.get("value"))
    ]
    if not source_texts:
        return None
    task_terms: list[str] = []
    calendar_terms: list[str] = []
    for constraint in constraints:
        if not (
            isinstance(constraint, Mapping)
            and constraint.get("kind") == "USER_REQUIREMENT"
            and constraint.get("field") == "business_concepts"
        ):
            continue
        for concept in _strings(constraint.get("value")):
            if _CALENDAR_NOUN.search(concept):
                term = _CALENDAR_SUFFIX.sub("", concept).strip()
                if term and any(term in source_text for source_text in source_texts):
                    calendar_terms.append(term)
            elif _TASK_NOUN.search(concept):
                term = _TASK_SUFFIX.sub("", concept).strip()
                if term and any(term in source_text for source_text in source_texts):
                    task_terms.append(term)
    task_terms = _unique(task_terms)
    calendar_terms = _unique(calendar_terms)
    if not task_terms or not calendar_terms:
        return None
    return {
        "task_terms": task_terms,
        "calendar_provider_terms": calendar_terms,
        "calendar_evidence_terms": _unique([*task_terms, *calendar_terms]),
    }


def _strings(value: object) -> list[str]:
    values = value if isinstance(value, list) else [value]
    return [item.strip() for item in values if isinstance(item, str) and item.strip()]


def project_draft_recipients(request_intent: Mapping[str, object]) -> list[str]:
    constraints = request_intent.get("constraints")
    if not isinstance(constraints, list):
        return []
    recipients: list[str] = []
    for item in constraints:
        if (
            not isinstance(item, Mapping)
            or item.get("kind") != "PERSON"
            or item.get("field") != "recipient"
        ):
            continue
        raw = item.get("value")
        values = raw if isinstance(raw, list) else [raw]
        recipients.extend(
            candidate.strip()
            for candidate in values
            if isinstance(candidate, str) and "@" in candidate and candidate.strip()
        )
    return list(dict.fromkeys(recipients))


def _unique(values: Sequence[str | None]) -> list[str]:
    return list(dict.fromkeys(value for value in values if value))


__all__ = [
    "TaskCalendarSourceTerms",
    "is_task_calendar_draft_source_target",
    "project_draft_recipients",
    "project_task_calendar_source_terms",
]
