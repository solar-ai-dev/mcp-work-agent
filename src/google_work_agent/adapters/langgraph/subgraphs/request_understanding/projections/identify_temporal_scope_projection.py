from __future__ import annotations

from typing import Any, TypedDict, cast

from google_work_agent.adapters.langgraph.main.state import request_from_run_input_state
from google_work_agent.adapters.langgraph.subgraphs.request_understanding.state import (
    RequestUnderstandingStateV2,
)
from google_work_agent.application.agents.request_understanding.contracts.request_intent import (
    RequestGoalCandidateV1,
)
from google_work_agent.ports.system.contracts.workflow_handoff import RequestedModeV1


class IdentifyTemporalScopeProjection(TypedDict):
    request_text: str
    requested_mode: RequestedModeV1
    goal_candidate: RequestGoalCandidateV1


def project_identify_temporal_scope_input(
    state: RequestUnderstandingStateV2,
) -> IdentifyTemporalScopeProjection:
    request = request_from_run_input_state(cast(Any, state))
    candidate = state.get("goal_candidate")
    if candidate is None:
        raise ValueError("request-understanding goal candidate is required")
    return {
        "request_text": request.request_text,
        "requested_mode": request.requested_mode,
        "goal_candidate": candidate,
    }


__all__ = ["IdentifyTemporalScopeProjection", "project_identify_temporal_scope_input"]
