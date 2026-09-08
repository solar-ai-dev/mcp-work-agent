from __future__ import annotations

from google_work_agent.adapters.langgraph.agent_kernel import ensure_llm_call_budget
from google_work_agent.adapters.langgraph.subgraphs.request_understanding.state import (
    RequestUnderstandingStateV2,
)
from google_work_agent.application.agents.request_understanding.identify_goal import (
    identify_goal_with_budget,
)
from google_work_agent.ports.llm.structured_inference_contracts import PromptReference
from google_work_agent.ports.llm.structured_inference_port import StructuredInferencePort

from ..projections.identify_goal_projection import (
    project_identify_goal_input,
)


def identify_goal_node(
    state: RequestUnderstandingStateV2,
    *,
    llm_runtime: StructuredInferencePort,
    prompt_ref: PromptReference | None,
) -> RequestUnderstandingStateV2:
    projection = project_identify_goal_input(state)
    ensure_llm_call_budget(state)
    candidate, retry_budget = identify_goal_with_budget(
        llm_runtime=llm_runtime,
        request=projection["request"],
        retry_budget=state["retry_budget"],
        prompt_ref=prompt_ref,
        confirmation_response=projection.get("confirmation_response"),
    )
    return {
        "goal_candidate": candidate,
        "retry_budget": retry_budget,
    }
