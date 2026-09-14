"""Closed routing after the TERMINAL_COMMIT control boundary."""

from __future__ import annotations

from collections.abc import Callable, Collection, Mapping

ROUTE_AFTER_TERMINAL_COMMIT_SUCCESSORS = frozenset(
    {"finalize", "cancel_resolution", "recovery", "domain_reconcile"}
)


def route_after_terminal_commit(
    state: Mapping[str, object],
    *,
    available_targets: Collection[str],
    should_stop_for_cancel: Callable[[str], bool],
) -> str:
    del should_stop_for_cancel
    target = state.get("__target__")
    if target not in ROUTE_AFTER_TERMINAL_COMMIT_SUCCESSORS:
        raise ValueError("TERMINAL_COMMIT returned an unregistered successor")
    if target not in available_targets:
        raise ValueError("TERMINAL_COMMIT returned an unregistered successor")
    return str(target)


__all__ = [
    "ROUTE_AFTER_TERMINAL_COMMIT_SUCCESSORS",
    "route_after_terminal_commit",
]
