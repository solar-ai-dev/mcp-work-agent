"""Preserve explicit user-owned search anchors after semantic inference."""

from __future__ import annotations

import re

from google_work_agent.application.agents.request_understanding.contracts.request_intent import (
    ConstraintV1,
    RequestGoalCandidateV1,
    is_fully_qualified_repository,
    is_repository_constraint,
)

_PLACEHOLDER_VALUES = frozenset(
    {
        "n/a",
        "na",
        "none",
        "null",
        "unknown",
        "unspecified",
        "not provided",
        "not specified",
        "미상",
        "알 수 없음",
    }
)
_EXPLICIT_SUBJECT_PATTERNS = (
    re.compile(r"(?:제목)(?:이|가|은|는)?\s*(?:[:：]\s*)?['‘\"](?P<subject>[^'’\"]+)['’\"]"),
    re.compile(r"(?i)(?:subject)\s*(?:is\s*)?(?:[:：]\s*)?['‘\"](?P<subject>[^'’\"]+)['’\"]"),
)
_EXPLICIT_PERIOD_PATTERN = re.compile(
    r"(?<!\d)(?:\d{4}년\s*)?(?:1[0-2]|[1-9])월(?:\s*첫째\s*주)?(?!\s*\d{1,2}\s*일)"
    r"|지난\s*주|이번\s*주|다음\s*주|지난\s*달|이번\s*달|최근|오늘|어제|그제"
)
_EXPLICIT_REPOSITORY_PATTERN = re.compile(
    r"(?<![A-Za-z0-9_.-/])"
    r"(?P<repository>[A-Za-z0-9][A-Za-z0-9-]*/[A-Za-z0-9_.-]*[A-Za-z0-9_-])"
    r"(?![A-Za-z0-9_/-])"
)
_EXPLICIT_GMAIL_DRAFT_ID_PATTERN = re.compile(
    r"(?i)(?:gmail\s*)?(?:초안|draft)\s*(?:id|아이디)\s*[:：]?\s*"
    r"(?P<draft_id>[A-Za-z0-9_-]{3,256})"
)
_SOURCE_OWNED_FIELDS = frozenset(
    {"search_terms", "business_concepts", "person", "sender", "recipient", "subject"}
)


def preserve_explicit_search_anchors(
    candidate: RequestGoalCandidateV1,
    *,
    request_text: str,
    entry_mode: str,
) -> RequestGoalCandidateV1:
    """Keep explicit source anchors without inferring their business meaning."""

    candidate = _preserve_explicit_repository(candidate, request_text=request_text)
    candidate = _preserve_explicit_gmail_draft_id(candidate, request_text=request_text)

    if (
        entry_mode != "AGENT_SEARCH"
        or "READ" not in candidate["requested_effect_hints"]
        or "GMAIL_THREAD" not in candidate["requested_resource_hints"]
    ):
        return candidate

    explicit_periods = _explicit_periods(request_text)
    constraints = _without_unstated_placeholders(candidate["constraints"], request_text)
    constraints = _retain_source_owned_values(constraints, request_text)
    constraints = _restore_source_spelling(constraints, request_text)
    constraints = [
        item
        for item in constraints
        if not (
            item["kind"] == "USER_REQUIREMENT"
            and item["field"] == "original_search_request"
        )
        and item["field"] not in {"subject", "search_criteria_subject"}
        and not (explicit_periods and item["field"] == "period")
    ]
    constraints.append(
        {
            "kind": "USER_REQUIREMENT",
            "field": "original_search_request",
            "value": [request_text],
        }
    )
    if explicit_periods:
        constraints.append({"kind": "DATE", "field": "period", "value": explicit_periods})
    explicit_subjects = _explicit_subjects(request_text)
    if explicit_subjects:
        constraints = [
            item
            for item in constraints
            if item["field"] != "search_terms"
        ]
        constraints.append(
            {"kind": "RESOURCE", "field": "subject", "value": explicit_subjects}
        )
    return {**candidate, "constraints": constraints}


def _preserve_explicit_gmail_draft_id(
    candidate: RequestGoalCandidateV1,
    *,
    request_text: str,
) -> RequestGoalCandidateV1:
    if "GMAIL_DRAFT" not in candidate["requested_resource_hints"]:
        return candidate
    draft_ids = list(
        dict.fromkeys(
            match.group("draft_id")
            for match in _EXPLICIT_GMAIL_DRAFT_ID_PATTERN.finditer(request_text)
        )
    )
    if not draft_ids:
        return candidate
    constraints = [
        constraint
        for constraint in candidate["constraints"]
        if not (
            constraint["kind"] == "RESOURCE" and constraint["field"] == "draft_id"
        )
    ]
    constraints.extend(
        {"kind": "RESOURCE", "field": "draft_id", "value": draft_id}
        for draft_id in draft_ids
    )
    return {**candidate, "constraints": constraints}


def _preserve_explicit_repository(
    candidate: RequestGoalCandidateV1,
    *,
    request_text: str,
) -> RequestGoalCandidateV1:
    if "GITHUB_ISSUE" not in candidate["requested_resource_hints"]:
        return candidate
    repositories = list(
        dict.fromkeys(
            match.group("repository")
            for match in _EXPLICIT_REPOSITORY_PATTERN.finditer(request_text)
            if is_fully_qualified_repository(match.group("repository"))
        )
    )
    if not repositories:
        return candidate
    constraints = [
        constraint
        for constraint in candidate["constraints"]
        if not is_repository_constraint(constraint)
    ]
    constraints.extend(
        {"kind": "RESOURCE", "field": "repository", "value": repository}
        for repository in repositories
    )
    return {**candidate, "constraints": constraints}


def _explicit_subjects(request_text: str) -> list[str]:
    return list(
        dict.fromkeys(
            match.group("subject").strip()
            for pattern in _EXPLICIT_SUBJECT_PATTERNS
            for match in pattern.finditer(request_text)
            if match.group("subject").strip()
        )
    )


def _explicit_periods(request_text: str) -> list[str]:
    outside_literals = request_text
    for pattern in (re.compile(r"'[^']*'"), re.compile(r'"[^"]*"')):
        outside_literals = pattern.sub(" ", outside_literals)
    return list(
        dict.fromkeys(
            match.group(0).strip()
            for match in _EXPLICIT_PERIOD_PATTERN.finditer(outside_literals)
        )
    )


def _without_unstated_placeholders(
    constraints: list[ConstraintV1], request_text: str
) -> list[ConstraintV1]:
    request_normalized = request_text.casefold()
    result: list[ConstraintV1] = []
    for constraint in constraints:
        raw_value = constraint["value"]
        values = raw_value if isinstance(raw_value, list) else [raw_value]
        retained = [
            value
            for value in values
            if value.strip()
            and (
                value.casefold().strip() not in _PLACEHOLDER_VALUES
                or value.casefold().strip() in request_normalized
            )
        ]
        if retained:
            result.append(
                {
                    **constraint,
                    "value": retained if isinstance(raw_value, list) else retained[0],
                }
            )
    return result


def _restore_source_spelling(
    constraints: list[ConstraintV1], request_text: str
) -> list[ConstraintV1]:
    """Restore an inferred value's exact source span when only whitespace differs."""

    restored: list[ConstraintV1] = []
    for constraint in constraints:
        raw_value = constraint["value"]
        values = raw_value if isinstance(raw_value, list) else [raw_value]
        exact_values = [_matching_source_span(value, request_text) or value for value in values]
        restored.append(
            {
                **constraint,
                "value": exact_values if isinstance(raw_value, list) else exact_values[0],
            }
        )
    return restored


def _retain_source_owned_values(
    constraints: list[ConstraintV1], request_text: str
) -> list[ConstraintV1]:
    """Reject inferred anchors/concepts/people that have no current-request source span."""

    retained_constraints: list[ConstraintV1] = []
    for constraint in constraints:
        if constraint["field"] not in _SOURCE_OWNED_FIELDS:
            retained_constraints.append(constraint)
            continue
        raw_value = constraint["value"]
        values = raw_value if isinstance(raw_value, list) else [raw_value]
        retained = [
            value for value in values if _matching_source_span(value, request_text) is not None
        ]
        if retained:
            retained_constraints.append(
                {
                    **constraint,
                    "value": retained if isinstance(raw_value, list) else retained[0],
                }
            )
    return retained_constraints


def _matching_source_span(value: str, request_text: str) -> str | None:
    compact = re.sub(r"\s+", "", value)
    if not compact:
        return None
    pattern = re.compile(r"\s*".join(re.escape(character) for character in compact), re.I)
    matches = list(pattern.finditer(request_text))
    return matches[0].group(0) if len(matches) == 1 else None


__all__ = ["preserve_explicit_search_anchors"]
