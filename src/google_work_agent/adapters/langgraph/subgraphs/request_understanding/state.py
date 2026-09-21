"""Canonical owner-local state and parent patch for Request Understanding."""

# LangGraph resolves inherited TypedDict annotations in this module namespace.

from __future__ import annotations

from typing import Literal

from google_work_agent.adapters.langgraph.main.state import RunInputV1
from google_work_agent.adapters.langgraph.subgraph_state import (
    AgentSubgraphInputEnvelope,
)
from google_work_agent.application.agents.request_understanding.contracts.request_intent import (
    AmbiguityV1,
    RequestGoalCandidateV1,
    RequestIntentV3,
)
from google_work_agent.application.use_cases.run.guard_run_budget import (
    RunBudgetV2,
)
from google_work_agent.application.use_cases.run.policy_confirmation_receipt import (
    PolicyConfirmationReceiptV1,
)
from google_work_agent.application.use_cases.run.terminal_contract import FinalizeIntentV1
from google_work_agent.ports.system.contracts.confirmation import (
    UserInterruptV1,
)
from google_work_agent.ports.system.contracts.workflow_execution import (
    SelectedResourceRef,
    WorkflowStartRequest,
)
from google_work_agent.ports.system.contracts.workflow_signal import (
    RequestReconsiderationRequiredV1,
)

_TYPE_HINT_NAMESPACE = (RunBudgetV2, WorkflowStartRequest)


class RequestUnderstandingInputState(AgentSubgraphInputEnvelope, total=False):
    """Parent projection owned by Request Understanding."""

    run_input: RunInputV1
    admitted_connector_ids: list[str]
    user_interrupt: UserInterruptV1 | None
    policy_confirmation_receipts: list[PolicyConfirmationReceiptV1]
    request_intent: RequestIntentV3 | None
    request_reconsideration: RequestReconsiderationRequiredV1 | None


class RequestUnderstandingStateV2(RequestUnderstandingInputState, total=False):
    """The exact 06-owned local fields plus the allowed parent patch channels."""

    request_text: str
    entry_mode: Literal["AGENT_SEARCH", "RESOURCE_SELECTED"]
    selected_resource_refs: list[SelectedResourceRef]
    goal_candidate: RequestGoalCandidateV1 | None
    ambiguity_candidate: AmbiguityV1 | None
    final_intent: RequestIntentV3 | None
    prerequisite_message: str | None
    finalize_intent: FinalizeIntentV1 | None


class RequestUnderstandingParentOutputState(AgentSubgraphInputEnvelope, total=False):
    """Only fields that Request Understanding may project back to Main."""

    request_intent: RequestIntentV3 | None
    request_reconsideration: RequestReconsiderationRequiredV1 | None
    admitted_connector_ids: list[str]
    finalize_intent: FinalizeIntentV1 | None
    user_interrupt: UserInterruptV1 | None
    policy_confirmation_receipts: list[PolicyConfirmationReceiptV1]


__all__ = [
    "RequestUnderstandingInputState",
    "RequestUnderstandingParentOutputState",
    "RequestUnderstandingStateV2",
]
