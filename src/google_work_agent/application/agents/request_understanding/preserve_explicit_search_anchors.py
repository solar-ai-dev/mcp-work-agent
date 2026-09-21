"""Preserve explicit user-owned search anchors after semantic inference."""

from __future__ import annotations

import re
from collections.abc import Mapping
from copy import deepcopy

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
    re.compile(r"(?:제목)(?:이|가|은|는|에)?\s*(?:[:：]\s*)?$"),
    re.compile(r"(?i)(?:subject)\s*(?:is\s*)?(?:[:：]\s*)?$"),
)
_EXPLICIT_SUBJECT_ROLE_PATTERN = re.compile(
    r"(?:제목)(?:이|가|은|는|에)?\b|(?i:subject)\b"
)
_QUOTE_PAIRS = (("'", "'"), ('"', '"'), ("‘", "’"), ("“", "”"))
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
_GMAIL_SOURCE_RESOURCE_HINTS = frozenset(
    {"GMAIL_THREAD", "GMAIL_MESSAGE", "GMAIL_DRAFT"}
)
_EXACT_GMAIL_RESOURCE_FIELDS = frozenset(
    {"draft_id", "thread_id", "message_id", "selected_resource_id"}
)
_GMAIL_SOURCE_SEARCH_FIELDS = frozenset(
    {
        "search_terms",
        "business_concepts",
        "person",
        "sender",
        "recipient",
        "subject",
        "search_criteria_subject",
        "period",
        "status",
    }
)
_EXPLICIT_GMAIL_STATUS_PATTERNS = {
    "DRAFT": re.compile(r"임시\s*보관함|초안|(?i:\bdrafts?\b)"),
    "SENT": re.compile(
        r"보낸\s*(?:편지함|메일|이메일)|보내(?:진|어진)\s*(?:메일|이메일)|발신함"
        r"|(?i:\bsent(?:\s+(?:mail|messages?|emails?))?\b)"
    ),
}
_GMAIL_STATUS_ALIASES = {
    "초안": "DRAFT",
    "임시보관함": "DRAFT",
    "임시 보관함": "DRAFT",
    "보낸편지함": "SENT",
    "보낸 편지함": "SENT",
    "보낸 메일": "SENT",
    "보낸 이메일": "SENT",
    "발신함": "SENT",
}


def project_extractive_source_goal(
    value: object,
    *,
    request_text: str,
) -> dict[str, object]:
    """Project only request-bound meaning into atomic source selection."""

    if not isinstance(value, Mapping):
        raise ValueError("source goal projection requires an object")
    projected = deepcopy(dict(value))
    projected["goal"] = request_text
    projected["completion_conditions"] = []
    raw_constraints = projected.get("constraints")
    if not isinstance(raw_constraints, Mapping):
        return projected
    constraints = dict(raw_constraints)
    for field in _SOURCE_OWNED_FIELDS:
        raw_values = constraints.get(field)
        if not isinstance(raw_values, list):
            continue
        projected_values: list[dict[str, object]] = []
        for item in raw_values:
            if not isinstance(item, Mapping) or not isinstance(item.get("value"), str):
                continue
            exact = _matching_source_span(item["value"], request_text)
            if exact is not None:
                projected_values.append({**item, "value": exact})
        constraints[field] = projected_values
    constraints["additional_constraints"] = []
    projected["constraints"] = constraints
    return projected


def preserve_explicit_search_anchors(
    candidate: RequestGoalCandidateV1,
    *,
    request_text: str,
    entry_mode: str,
) -> RequestGoalCandidateV1:
    """Keep explicit source anchors without inferring their business meaning."""

    candidate = _preserve_explicit_repository(candidate, request_text=request_text)
    candidate = _preserve_explicit_gmail_draft_id(candidate, request_text=request_text)

    if not _requires_gmail_source_search(candidate, entry_mode=entry_mode):
        return candidate
    if _has_exact_gmail_resource(candidate["constraints"]):
        return candidate
    if not any(
        item["field"] in _GMAIL_SOURCE_SEARCH_FIELDS
        for item in candidate["constraints"]
    ) and not (
        "READ" in candidate["requested_effect_hints"]
        and bool(
            set(candidate["requested_resource_hints"])
            & {"GMAIL_THREAD", "GMAIL_MESSAGE"}
        )
    ):
        return candidate

    explicit_periods = _explicit_periods(request_text)
    explicit_subjects = _explicit_subjects(request_text)
    has_explicit_subject_role = _EXPLICIT_SUBJECT_ROLE_PATTERN.search(request_text) is not None
    constraints = _without_unstated_placeholders(candidate["constraints"], request_text)
    constraints = _retain_explicit_gmail_statuses(constraints, request_text)
    has_unbound_business_concept = any(
        constraint["field"] == "business_concepts"
        and any(
            _matching_source_span(value, request_text) is None
            for value in (
                constraint["value"]
                if isinstance(constraint["value"], list)
                else [constraint["value"]]
            )
        )
        for constraint in constraints
    )
    constraints = _retain_source_owned_values(constraints, request_text)
    constraints = _restore_source_spelling(constraints, request_text)
    quoted_search_terms = _quoted_search_terms_from_candidate(constraints, request_text)
    constraints = [
        item
        for item in constraints
        if not (
            item["kind"] == "USER_REQUIREMENT"
            and item["field"] == "original_search_request"
        )
        and (
            has_explicit_subject_role
            or item["field"] not in {"subject", "search_criteria_subject"}
        )
        and not (explicit_periods and item["field"] == "period")
    ]
    if quoted_search_terms and not has_explicit_subject_role:
        constraints = [item for item in constraints if item["field"] != "search_terms"]
        constraints.append(
            {
                "kind": "USER_REQUIREMENT",
                "field": "search_terms",
                "value": quoted_search_terms,
                "work_unit_ids": _applicable_work_unit_ids(
                    candidate, values=quoted_search_terms
                ),
            }
        )
    constraints.append(
        {
            "kind": "USER_REQUIREMENT",
            "field": "original_search_request",
            "value": [request_text],
            "work_unit_ids": _all_work_unit_ids(candidate),
        }
    )
    if explicit_periods:
        constraints.append(
            {
                "kind": "DATE",
                "field": "period",
                "value": explicit_periods,
                "work_unit_ids": _applicable_work_unit_ids(
                    candidate, values=explicit_periods
                ),
            }
        )
    if explicit_subjects:
        constraints = [
            item
            for item in constraints
            if item["field"] not in {"search_terms", "subject", "search_criteria_subject"}
        ]
        constraints.append(
            {
                "kind": "RESOURCE",
                "field": "subject",
                "value": explicit_subjects,
                "work_unit_ids": _applicable_work_unit_ids(
                    candidate, values=explicit_subjects
                ),
            }
        )
    elif has_explicit_subject_role and any(
        item["field"] in {"subject", "search_criteria_subject"} for item in constraints
    ):
        constraints = [item for item in constraints if item["field"] != "search_terms"]
    return {
        **candidate,
        "goal": request_text if has_unbound_business_concept else candidate["goal"],
        "constraints": constraints,
    }


def _requires_gmail_source_search(
    candidate: RequestGoalCandidateV1,
    *,
    entry_mode: str,
) -> bool:
    if entry_mode != "AGENT_SEARCH":
        return False
    resources = set(candidate["requested_resource_hints"])
    effects = set(candidate["requested_effect_hints"])
    source_resources = resources & _GMAIL_SOURCE_RESOURCE_HINTS
    if not source_resources:
        return False
    if effects & {"READ", "UPDATE", "DELETE"}:
        return True
    return "SEND" in effects and bool(source_resources & {"GMAIL_THREAD", "GMAIL_DRAFT"})


def _has_exact_gmail_resource(constraints: list[ConstraintV1]) -> bool:
    return any(
        item["kind"] == "RESOURCE"
        and item["field"] in _EXACT_GMAIL_RESOURCE_FIELDS
        and item["value"]
        for item in constraints
    )


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
        {
            "kind": "RESOURCE",
            "field": "draft_id",
            "value": draft_id,
            "work_unit_ids": _applicable_work_unit_ids(candidate, values=[draft_id]),
        }
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
        {
            "kind": "RESOURCE",
            "field": "repository",
            "value": repository,
            "work_unit_ids": _applicable_work_unit_ids(candidate, values=[repository]),
        }
        for repository in repositories
    )
    return {**candidate, "constraints": constraints}


def _all_work_unit_ids(candidate: RequestGoalCandidateV1) -> list[str]:
    unit_ids = [unit["unit_id"] for unit in candidate["requested_work"]["work_units"]]
    if not unit_ids or len(unit_ids) != len(set(unit_ids)):
        raise ValueError("requested_work contains invalid WorkUnit IDs")
    return unit_ids


def _applicable_work_unit_ids(
    candidate: RequestGoalCandidateV1,
    *,
    values: list[str],
) -> list[str]:
    applicable = [
        unit["unit_id"]
        for unit in candidate["requested_work"]["work_units"]
        if any(
            value in provenance["source_text"]
            for provenance in unit["request_provenance"]
            for value in values
        )
    ]
    return applicable or _all_work_unit_ids(candidate)


def _explicit_subjects(request_text: str) -> list[str]:
    return list(
        dict.fromkeys(
            literal.strip()
            for literal, start, _ in _quoted_literals(request_text)
            if literal.strip()
            and any(
                pattern.search(request_text[max(0, start - 40) : start])
                for pattern in _EXPLICIT_SUBJECT_PATTERNS
            )
        )
    )


def _quoted_search_terms_from_candidate(
    constraints: list[ConstraintV1], request_text: str
) -> list[str]:
    """Restore only quoted values already assigned to the structured search-term role."""

    literals_by_compact_value: dict[str, set[str]] = {}
    for literal, _, _ in _quoted_literals(request_text):
        compact = re.sub(r"\s+", "", literal).casefold()
        if compact:
            literals_by_compact_value.setdefault(compact, set()).add(literal.strip())

    restored: list[str] = []
    for constraint in constraints:
        if constraint["field"] != "search_terms":
            continue
        value = constraint["value"]
        values = value if isinstance(value, list) else [value]
        for item in values:
            normalized = item.strip()
            if len(normalized) >= 2 and (
                normalized[0], normalized[-1]
            ) in _QUOTE_PAIRS:
                normalized = normalized[1:-1]
            matches = literals_by_compact_value.get(
                re.sub(r"\s+", "", normalized).casefold(), set()
            )
            if len(matches) == 1:
                restored.append(next(iter(matches)))
    return list(dict.fromkeys(restored))


def _quoted_literals(request_text: str) -> list[tuple[str, int, int]]:
    literals: list[tuple[str, int, int]] = []
    for opening, closing in _QUOTE_PAIRS:
        pattern = re.compile(
            re.escape(opening) + rf"(?P<literal>[^{re.escape(closing)}]+)" + re.escape(closing)
        )
        literals.extend(
            (match.group("literal"), match.start(), match.end())
            for match in pattern.finditer(request_text)
        )
    return sorted(literals, key=lambda item: item[1])


def _explicit_periods(request_text: str) -> list[str]:
    characters = list(request_text)
    for _, start, end in _quoted_literals(request_text):
        characters[start:end] = " " * (end - start)
    outside_literals = "".join(characters)
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


def _retain_explicit_gmail_statuses(
    constraints: list[ConstraintV1], request_text: str
) -> list[ConstraintV1]:
    """Reject mailbox scopes inferred from verbs that describe the business object."""

    retained: list[ConstraintV1] = []
    for constraint in constraints:
        if constraint["field"] != "status":
            retained.append(constraint)
            continue
        raw_value = constraint["value"]
        values = raw_value if isinstance(raw_value, list) else [raw_value]
        normalized_values = [
            _GMAIL_STATUS_ALIASES.get(value.casefold().strip(), value.upper().strip())
            for value in values
        ]
        if all(
            (pattern := _EXPLICIT_GMAIL_STATUS_PATTERNS.get(value)) is not None
            and pattern.search(request_text) is not None
            for value in normalized_values
        ):
            retained.append(constraint)
    return retained


def _matching_source_span(value: str, request_text: str) -> str | None:
    normalized_value = value.strip()
    if len(normalized_value) >= 2 and (
        normalized_value[0], normalized_value[-1]
    ) in _QUOTE_PAIRS:
        normalized_value = normalized_value[1:-1]
    compact = re.sub(r"\s+", "", normalized_value)
    if not compact:
        return None
    pattern = re.compile(r"\s*".join(re.escape(character) for character in compact), re.I)
    match = pattern.search(request_text)
    return match.group(0) if match is not None else None


__all__ = ["preserve_explicit_search_anchors", "project_extractive_source_goal"]
