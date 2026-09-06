"""Deterministically resolve request scope before goal inference."""

from __future__ import annotations

import re
from dataclasses import dataclass

_QUOTED_LITERAL_PATTERNS = (
    re.compile(r"'[^']*'"),
    re.compile(r'"[^"]*"'),
    re.compile(r"‘[^’]*’"),
    re.compile(r"“[^”]*”"),
)
_EXPLICIT_WRITE_MARKERS = (
    "만들",
    "생성",
    "추가",
    "수정",
    "변경",
    "삭제",
    "보내",
    "전송",
    "등록",
    "create",
    "add",
    "update",
    "modify",
    "delete",
    "send",
)
_GENERAL_ANSWER_ONLY_CONTENT_MARKERS = (
    "원칙",
    "방법",
    "팁",
    "조언",
    "개념",
    "기준",
    "principle",
    "guideline",
    "best practice",
    "advice",
    "tip",
    "concept",
)
_GENERAL_ANSWER_ONLY_RESPONSE_MARKERS = (
    "알려",
    "설명",
    "말해",
    "답해",
    "explain",
    "tell",
    "answer",
)
_CURRENT_WORKSPACE_FACT_MARKERS = (
    "내 ",
    "나의",
    "현재",
    "최근",
    "선택한",
    "찾아",
    "읽어",
    "목록",
    "요약",
    "분석",
    "my ",
    "current",
    "recent",
    "selected",
    "find",
    "read",
    "list",
    "summarize",
    "analyse",
    "analyze",
)


@dataclass(frozen=True, slots=True)
class RequestScopeResolution:
    quoted_literals: tuple[str, ...]
    outside_quoted_literals: str
    has_explicit_write_marker: bool
    is_general_answer_only: bool


def resolve_request_scope(request_text: str) -> RequestScopeResolution:
    """Resolve quoted payload, explicit writes, and answer-only scope."""

    outside_quoted_literals = request_text
    quoted_literals: list[str] = []
    for pattern in _QUOTED_LITERAL_PATTERNS:
        quoted_literals.extend(pattern.findall(request_text))
        outside_quoted_literals = pattern.sub(" ", outside_quoted_literals)

    normalized = request_text.casefold()
    outside_values = outside_quoted_literals.casefold()
    outside_values = re.sub(r"[\w.+-]+@[\w.-]+\.[a-z]{2,}", " ", outside_values)
    has_explicit_write_marker = any(
        re.search(rf"\b{marker}\b", outside_values) is not None
        if marker.isascii()
        else marker in outside_values
        for marker in _EXPLICIT_WRITE_MARKERS
    )
    is_general_answer_only = (
        any(marker in normalized for marker in _GENERAL_ANSWER_ONLY_CONTENT_MARKERS)
        and any(marker in normalized for marker in _GENERAL_ANSWER_ONLY_RESPONSE_MARKERS)
        and not any(marker in normalized for marker in _CURRENT_WORKSPACE_FACT_MARKERS)
        and not has_explicit_write_marker
    )
    return RequestScopeResolution(
        quoted_literals=tuple(quoted_literals),
        outside_quoted_literals=outside_quoted_literals,
        has_explicit_write_marker=has_explicit_write_marker,
        is_general_answer_only=is_general_answer_only,
    )


__all__ = ["RequestScopeResolution", "resolve_request_scope"]
