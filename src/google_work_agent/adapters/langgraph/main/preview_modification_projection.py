"""Project the exact user-edited fields of a persisted Action preview."""

from __future__ import annotations

from collections.abc import Mapping
from typing import TypedDict


class UserActionModification(TypedDict):
    action_id: str
    argument_overrides: dict[str, object]


def project_user_action_modification(
    *,
    action_id: str,
    previous_arguments: Mapping[str, object],
    current_arguments: Mapping[str, object],
) -> UserActionModification | None:
    """Identify fields explicitly changed after the original Planning artifact."""

    if not action_id:
        raise ValueError("action_id is required")
    argument_overrides = _changed_argument_overrides(previous_arguments, current_arguments)
    if not argument_overrides:
        return None
    return {
        "action_id": action_id,
        "argument_overrides": argument_overrides,
    }


def _changed_argument_overrides(
    previous: Mapping[str, object],
    current: Mapping[str, object],
    *,
    prefix: str = "",
) -> dict[str, object]:
    changed: dict[str, object] = {}
    for key in sorted(set(previous) | set(current)):
        path = f"{prefix}.{key}" if prefix else key
        if key not in current:
            changed[path] = None
            continue
        if key not in previous:
            changed[path] = current[key]
            continue
        before = previous[key]
        after = current[key]
        if isinstance(before, Mapping) and isinstance(after, Mapping):
            changed.update(_changed_argument_overrides(before, after, prefix=path))
        elif before != after:
            changed[path] = after
    return changed


__all__ = ["UserActionModification", "project_user_action_modification"]
