from __future__ import annotations

from collections.abc import Mapping
from typing import TypedDict, cast

from google_work_agent.application.agents.request_understanding.contracts.request_intent import (
    RequestIntentV2,
)
from google_work_agent.application.agents.work_analysis.contracts.work_analysis_candidates import (
    InformationGapConfirmationResolutionV1,
)
from google_work_agent.application.agents.work_analysis.contracts.work_analysis_result import (
    RouteActionNecessityV1,
    WorkFactV1,
)

from .retrieval_source_statuses_projection import project_retrieval_source_statuses


class AssessInformationGapsInput(TypedDict):
    request_intent: RequestIntentV2
    work_facts: list[WorkFactV1]
    evidence: list[dict[str, object]]
    allowed_evidence_refs: set[str]
    confirmation_resolution: InformationGapConfirmationResolutionV1 | None
    source_statuses: list[dict[str, object]]
    route_action_necessities: list[RouteActionNecessityV1]


def project_assess_information_gaps_input(
    state: Mapping[str, object],
) -> AssessInformationGapsInput:
    required = (
        "request_intent",
        "fact_candidates",
        "evidence",
        "evidence_refs",
        "route_action_necessities",
    )
    if any(key not in state for key in required):
        raise ValueError("missing typed input projection for analysis.assess_information_gaps")
    resolution = state.get("information_gap_confirmation_resolution")
    return {
        "request_intent": cast(RequestIntentV2, state["request_intent"]),
        "work_facts": cast(list[WorkFactV1], state["fact_candidates"]),
        "evidence": [dict(item) for item in cast(list[dict[str, object]], state["evidence"])],
        "allowed_evidence_refs": set(cast(list[str], state["evidence_refs"])),
        "confirmation_resolution": (
            cast(InformationGapConfirmationResolutionV1, dict(resolution))
            if isinstance(resolution, Mapping)
            else None
        ),
        "source_statuses": project_retrieval_source_statuses(state),
        "route_action_necessities": cast(
            list[RouteActionNecessityV1], state["route_action_necessities"]
        ),
    }


__all__ = ["AssessInformationGapsInput", "project_assess_information_gaps_input"]
