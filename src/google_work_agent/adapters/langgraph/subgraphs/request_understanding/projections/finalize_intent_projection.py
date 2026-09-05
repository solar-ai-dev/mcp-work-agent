from __future__ import annotations

from typing import NotRequired, TypedDict

from google_work_agent.adapters.langgraph.main.state import request_from_run_input_state
from google_work_agent.adapters.langgraph.subgraphs.request_understanding.state import (
    RequestUnderstandingStateV2,
)
from google_work_agent.application.agents.request_understanding.contracts.request_intent import (
    AmbiguityV1,
    RequestGoalCandidateV1,
)
from google_work_agent.ports.system.contracts.confirmation import (
    ConfirmationResponseProjectionV1,
    validate_confirmation_response_projection_v1,
)
from google_work_agent.ports.system.contracts.workflow_execution import WorkflowStartRequest


class FinalizeIntentInput(TypedDict):
    request: WorkflowStartRequest
    goal_candidate: RequestGoalCandidateV1
    ambiguity_candidate: AmbiguityV1
    confirmation_response: NotRequired[ConfirmationResponseProjectionV1]


def project_finalize_intent_input(state: RequestUnderstandingStateV2) -> FinalizeIntentInput:
    """Project only the same-invocation Request Understanding candidates."""
    goal_candidate = state.get("goal_candidate")
    ambiguity_candidate = state.get("ambiguity_candidate")
    if goal_candidate is None or ambiguity_candidate is None:
        raise ValueError("request-understanding candidates are required")
    projected: FinalizeIntentInput = {
        "request": request_from_run_input_state(state),
        "goal_candidate": goal_candidate,
        "ambiguity_candidate": ambiguity_candidate,
    }
    prompt_context = state.get("prompt_context", {})
    confirmation = prompt_context.get("confirmation_response")
    if confirmation is not None:
        projected["confirmation_response"] = validate_confirmation_response_projection_v1(
            confirmation
        )
    return projected
