"""Deterministic terminal edge after canonical Retrieval finalization."""

from __future__ import annotations

from collections.abc import Mapping


def route_after_finalize_retrieval(state: Mapping[str, object]) -> str:
    if state.get("__context_retrieval_retry_confirmation__") is True:
        return "finalize"
    sufficiency = state.get("__context_sufficiency_output__")
    if (
        isinstance(sufficiency, Mapping) and sufficiency.get("status") == "NEEDS_MORE_DATA"
        and state.get("__context_followup_planner_input__") is not None
    ):
        return "plan_query"
    final_result = state.get("final_result")
    if final_result is not None and not isinstance(final_result, Mapping):
        raise ValueError("retrieval final_result is required")
    return "end"


__all__ = ["route_after_finalize_retrieval"]
