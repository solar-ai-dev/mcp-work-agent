from __future__ import annotations

from typing import NotRequired, TypedDict

from google_work_agent.adapters.langgraph.main.state import request_from_run_input_state
from google_work_agent.adapters.langgraph.subgraphs.request_understanding.state import (
    RequestUnderstandingStateV2,
)
from google_work_agent.ports.system.contracts.confirmation import (
    ConfirmationResponseProjectionV1,
    validate_confirmation_response_projection_v1,
)
from google_work_agent.ports.system.contracts.workflow_execution import WorkflowStartRequest
from google_work_agent.ports.system.contracts.workflow_signal import (
    RequestReconsiderationRequiredV1,
)


class IdentifyGoalInput(TypedDict):
    request: WorkflowStartRequest
    confirmation_response: NotRequired[ConfirmationResponseProjectionV1]
    request_reconsideration: NotRequired[RequestReconsiderationRequiredV1]


def project_identify_goal_input(state: RequestUnderstandingStateV2) -> IdentifyGoalInput:
    """Project only current-Run fields allowed by the identify-goal prompt contract."""
    request = request_from_run_input_state(state)
    projected: IdentifyGoalInput = {"request": request}
    prompt_context = state.get("prompt_context", {})
    confirmation = prompt_context.get("confirmation_response")
    if confirmation is not None:
        projected["confirmation_response"] = validate_confirmation_response_projection_v1(
            confirmation
        )
    reconsideration = state.get("request_reconsideration")
    if reconsideration is not None:
        current_intent = state.get("request_intent")
        if current_intent is None or reconsideration["based_on_request_intent"] != (
            current_intent["meta"]
        ):
            raise ValueError("request reconsideration is not bound to current intent")
        if not reconsideration["observations"]:
            raise ValueError("request reconsideration requires observations")
        projected["request_reconsideration"] = reconsideration
    return projected
