from __future__ import annotations

from google_work_agent.adapters.langgraph.agent_kernel import ensure_llm_call_budget
from google_work_agent.adapters.langgraph.subgraphs.request_understanding.state import (
    RequestUnderstandingStateV2,
)
from google_work_agent.application.agents.request_understanding.contracts import (
    output_responsibility_decision,
    source_dependency_decision,
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
    source_dependency_prompt_ref: PromptReference | None,
    output_responsibility_prompt_ref: PromptReference | None,
    source_status_prompt_ref: PromptReference | None,
    source_dependency_candidates: tuple[
        source_dependency_decision.SourceDependencyCandidateV1, ...
    ],
    output_responsibility_candidates: tuple[
        output_responsibility_decision.OutputResponsibilityCandidateV1, ...
    ],
) -> RequestUnderstandingStateV2:
    projection = project_identify_goal_input(state)
    ensure_llm_call_budget(
        state,
        provider_calls_requested=1 if "prior_goal_candidate" in projection else 5,
    )
    candidate, retry_budget = identify_goal_with_budget(
        llm_runtime=llm_runtime,
        request=projection["request"],
        retry_budget=state["retry_budget"],
        source_dependency_candidates=source_dependency_candidates,
        output_responsibility_candidates=output_responsibility_candidates,
        prompt_ref=prompt_ref,
        effect_prohibition_prompt_ref=effect_prohibition_prompt_ref,
        source_dependency_prompt_ref=source_dependency_prompt_ref,
        output_responsibility_prompt_ref=output_responsibility_prompt_ref,
        source_status_prompt_ref=source_status_prompt_ref,
        confirmation_response=projection.get("confirmation_response"),
        request_reconsideration=projection.get("request_reconsideration"),
        prior_goal_candidate=projection.get("prior_goal_candidate"),
    )
    return {
        "goal_candidate": candidate,
        "retry_budget": retry_budget,
    }
