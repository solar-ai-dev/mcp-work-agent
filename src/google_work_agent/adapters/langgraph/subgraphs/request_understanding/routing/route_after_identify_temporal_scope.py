from __future__ import annotations

from typing import Literal

from google_work_agent.adapters.langgraph.subgraphs.request_understanding.state import (
    RequestUnderstandingStateV2,
)


def route_after_identify_temporal_scope(
    state: RequestUnderstandingStateV2,
) -> Literal["detect_ambiguity"]:
    if state.get("goal_candidate") is None:
        raise ValueError("request-understanding goal candidate is required")
    return "detect_ambiguity"


__all__ = ["route_after_identify_temporal_scope"]
