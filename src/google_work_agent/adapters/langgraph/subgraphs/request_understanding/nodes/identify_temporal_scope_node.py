from __future__ import annotations

from google_work_agent.adapters.langgraph.agent_kernel import (
    consume_llm_call_budget,
    ensure_llm_call_budget,
)
from google_work_agent.application.agents.request_understanding.identify_temporal_scope import (
    identify_temporal_scope,
    needs_temporal_scope,
)
from google_work_agent.ports.llm.structured_inference_contracts import PromptReference
from google_work_agent.ports.llm.structured_inference_port import StructuredInferencePort

from ..projections.identify_temporal_scope_projection import (
    project_identify_temporal_scope_input,
)
from ..state import (
    RequestUnderstandingStateV2,
)


def identify_temporal_scope_node(
    state: RequestUnderstandingStateV2,
    *,
    llm_runtime: StructuredInferencePort,
    prompt_ref: PromptReference,
) -> RequestUnderstandingStateV2:
    projection = project_identify_temporal_scope_input(state)
    candidate = projection["goal_candidate"]
    if not needs_temporal_scope(candidate):
        return {"goal_candidate": candidate}
    ensure_llm_call_budget(state)
    return {
        "goal_candidate": identify_temporal_scope(
            llm_runtime=llm_runtime,
            prompt_ref=prompt_ref,
            requested_mode=projection["requested_mode"],
            request_text=projection["request_text"],
            candidate=candidate,
        ),
        "retry_budget": consume_llm_call_budget(state),
    }


__all__ = ["identify_temporal_scope_node"]
