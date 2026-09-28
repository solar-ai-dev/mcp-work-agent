"""Bind a Work selector to exact request offsets without changing business meaning."""

from __future__ import annotations

# Unicode White_Space; excludes zero-width/BOM and Python's additional C0 separators.
_SELECTOR_WHITESPACE = frozenset(
    "\t\n\v\f\r \u0085\u00a0\u1680"
    + "".join(chr(value) for value in range(0x2000, 0x200B))
    + "\u2028\u2029\u202f\u205f\u3000"
)


def _unique_occurrence(text: str, selector: str) -> int | None:
    start = text.find(selector)
    if start < 0:
        return None
    if text.find(selector, start + 1) >= 0:
        raise ValueError("requested work span must bind exactly once to current user request")
    return start


def bind_work_request_span(
    selector: str,
    *,
    user_request: str,
    allow_whitespace_selector: bool = False,
) -> tuple[int, int]:
    if allow_whitespace_selector and not any(
        character not in _SELECTOR_WHITESPACE for character in selector
    ):
        raise ValueError("requested work selector cannot contain only whitespace")
    start = _unique_occurrence(user_request, selector)
    if start is not None:
        return start, start + len(selector)
    if not allow_whitespace_selector:
        raise ValueError("requested work span must bind exactly once to current user request")
    offsets = [
        index
        for index, character in enumerate(user_request)
        if character not in _SELECTOR_WHITESPACE
    ]
    source_view = "".join(user_request[index] for index in offsets)
    selector_view = "".join(
        character for character in selector if character not in _SELECTOR_WHITESPACE
    )
    position = _unique_occurrence(source_view, selector_view)
    if position is None:
        raise ValueError("requested work selector has no codepoint-identical source interval")
    return offsets[position], offsets[position + len(selector_view) - 1] + 1
