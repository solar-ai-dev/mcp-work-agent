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
    IdentifyGoalInput,
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
    provider_calls_requested = _provider_calls_requested(projection)
    if provider_calls_requested:
        ensure_llm_call_budget(
            state,
            provider_calls_requested=provider_calls_requested,
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
        prior_ambiguity_candidate=projection.get("prior_ambiguity_candidate"),
    )
    return {
        "goal_candidate": candidate,
        "retry_budget": retry_budget,
    }


def _provider_calls_requested(projection: IdentifyGoalInput) -> int:
    prior = projection.get("prior_goal_candidate")
    if prior is None:
        return 5
    confirmation = projection.get("confirmation_response")
    ambiguity = projection.get("prior_ambiguity_candidate")
    target_confirmation = (
        confirmation is not None
        and (confirmation["selected_option"] or confirmation["free_text"]) is not None
        and ambiguity is not None
        and "target_resource" in ambiguity["missing_fields"]
    )
    if not target_confirmation:
        return 1
    if projection["request"].selected_resources:
        return 0
    return int(not prior["resource_responsibilities"]["source_reads"])
