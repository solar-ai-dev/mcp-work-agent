from __future__ import annotations

from typing import cast

from google_work_agent.adapters.langgraph.subgraphs.work_analysis.state import WorkAnalysisStateV2
from google_work_agent.application.agents.work_analysis.assess_information_gaps import (
    assess_information_gaps,
    combine_information_gap_assessment,
    require_resolution_for_undetermined_action,
)
from google_work_agent.application.agents.work_analysis.contracts.work_analysis_result import (
    WorkAmbiguityV1,
)
from google_work_agent.ports.llm.structured_inference_contracts import PromptReference
from google_work_agent.ports.llm.structured_inference_port import StructuredInferencePort
from google_work_agent.ports.system.contracts.workflow_handoff import RequestedModeV1

from ..projections.assess_information_gaps_projection import (
    project_assess_information_gaps_input,
)


def assess_information_gaps_node(
    state: dict[str, object],
    *,
    llm_runtime: StructuredInferencePort,
    prompt_ref: PromptReference,
    requested_mode: RequestedModeV1,
) -> WorkAnalysisStateV2:
    assessment = assess_information_gaps(
        **(projected := project_assess_information_gaps_input(state)),
        llm_runtime=llm_runtime,
        prompt_ref=prompt_ref,
        requested_mode=requested_mode,
    )
    assessment = combine_information_gap_assessment(
        assessment=assessment,
        relation_ambiguities=cast(
            list[WorkAmbiguityV1], state.get("relation_validation_ambiguities", [])
        ),
        confirmation_resolution=projected["confirmation_resolution"],
    )
    assessment = require_resolution_for_undetermined_action(
        assessment=assessment,
        route_action_necessities=cast(WorkAnalysisStateV2, state)["route_action_necessities"],
    )
    return cast(
        WorkAnalysisStateV2,
        {
            "ambiguity_candidates": list(assessment["ambiguities"]),
            "retrieval_needs": list(assessment["retrieval_needs"]),
            "__analysis_information_gap_assessment__": assessment,
        },
    )


__all__ = ["assess_information_gaps_node"]
