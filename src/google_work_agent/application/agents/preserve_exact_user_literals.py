"""Preserve exact user-owned values expressed inside quotation marks."""

from __future__ import annotations

import re
from collections.abc import Sequence

_QUOTED_LITERAL = re.compile(
    r"'(?P<single>[^']*)'|\"(?P<double>[^\"]*)\"|"
    r"‘(?P<left_single>[^’]*)’|“(?P<left_double>[^”]*)”"
)


def quoted_user_literals(text: str) -> list[str]:
    """Return quoted values in source order without their delimiters."""
    return [
        next(value for value in match.groupdict().values() if value is not None)
        for match in _QUOTED_LITERAL.finditer(text)
    ]


def without_quoted_user_literals(text: str) -> str:
    """Remove quoted spans while retaining the surrounding request text."""
    return _QUOTED_LITERAL.sub(" ", text)


def restore_exact_user_literals(text: str, *, source_texts: Sequence[str]) -> str:
    """Restore whitespace-corrupted occurrences of unambiguous quoted source values."""
    literals_by_compact_value: dict[str, set[str]] = {}
    for source_text in source_texts:
        for literal in quoted_user_literals(source_text):
            compact = re.sub(r"\s+", "", literal)
            if compact:
                literals_by_compact_value.setdefault(compact, set()).add(literal)

    restored = text
    unambiguous_literals = (
        next(iter(values))
        for compact, values in sorted(
            literals_by_compact_value.items(), key=lambda item: len(item[0]), reverse=True
        )
        if len(values) == 1
    )
    for literal in unambiguous_literals:
        compact = re.sub(r"\s+", "", literal)
        flexible = re.compile(r"\s*".join(re.escape(character) for character in compact))
        restored = flexible.sub(lambda _, exact=literal: exact, restored)
    return restored


__all__ = [
    "quoted_user_literals",
    "restore_exact_user_literals",
    "without_quoted_user_literals",
]
