from __future__ import annotations

from google_work_agent.adapters.langgraph.subgraphs.work_analysis.state import (
    WorkAnalysisStateV2,
)
from google_work_agent.application.agents.work_analysis.assess_action_necessity import (
    assess_action_necessity,
)
from google_work_agent.ports.llm.structured_inference_contracts import PromptReference
from google_work_agent.ports.llm.structured_inference_port import StructuredInferencePort
from google_work_agent.ports.system.contracts.workflow_handoff import RequestedModeV1

from ..projections.assess_action_necessity_projection import (
    project_assess_action_necessity_input,
)


def assess_action_necessity_node(
    state: dict[str, object],
    *,
    llm_runtime: StructuredInferencePort,
    prompt_ref: PromptReference,
    requested_mode: RequestedModeV1,
) -> WorkAnalysisStateV2:
    assessment = assess_action_necessity(
        **project_assess_action_necessity_input(state),
        llm_runtime=llm_runtime,
        prompt_ref=prompt_ref,
        requested_mode=requested_mode,
    )
    return {"route_action_necessities": list(assessment["route_assessments"])}


__all__ = ["assess_action_necessity_node"]
