from __future__ import annotations

from google_work_agent.adapters.langgraph.agent_kernel import ensure_llm_call_budget
from google_work_agent.adapters.langgraph.subgraphs.request_understanding.state import (
    RequestUnderstandingStateV2,
)
from google_work_agent.application.agents.request_understanding.contracts import (
    resource_role_decision,
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
    effect_prohibition_prompt_ref: PromptReference | None,
    responsibility_prompt_ref: PromptReference | None,
    source_status_prompt_ref: PromptReference | None,
    resource_role_candidates: tuple[resource_role_decision.ResourceRoleCandidateV1, ...],
) -> RequestUnderstandingStateV2:
    projection = project_identify_goal_input(state)
    ensure_llm_call_budget(state, provider_calls_requested=4)
    candidate, retry_budget = identify_goal_with_budget(
        llm_runtime=llm_runtime,
        request=projection["request"],
        retry_budget=state["retry_budget"],
        resource_role_candidates=resource_role_candidates,
        prompt_ref=prompt_ref,
        effect_prohibition_prompt_ref=effect_prohibition_prompt_ref,
        responsibility_prompt_ref=responsibility_prompt_ref,
        source_status_prompt_ref=source_status_prompt_ref,
        confirmation_response=projection.get("confirmation_response"),
        request_reconsideration=projection.get("request_reconsideration"),
    )
    return {
        "goal_candidate": candidate,
        "retry_budget": retry_budget,
    }
