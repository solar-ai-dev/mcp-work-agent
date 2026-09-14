"""Yield a READ subgraph to Main's existing cancellation authority."""

from collections.abc import Callable, Mapping


def route_after_retrieval_boundary(
    state: Mapping[str, object], *, normal_route: Callable[[Mapping[str, object]], str],
    should_stop_for_cancel: Callable[[str], bool],
) -> str:
    run_id = state.get("run_id")
    if not isinstance(run_id, str) or not run_id:
        raise ValueError("retrieval cancellation boundary requires the current Run ID")
    if should_stop_for_cancel(run_id):
        return "end"
    return normal_route(state)
