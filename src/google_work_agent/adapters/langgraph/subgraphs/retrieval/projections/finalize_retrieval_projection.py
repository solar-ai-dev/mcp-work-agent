from __future__ import annotations

from collections.abc import Mapping
from typing import TypedDict, cast

from google_work_agent.application.agents.request_understanding.contracts.request_intent import (
    RequestIntentV2,
)
from google_work_agent.application.agents.retrieval.contracts.query_attempt import QueryAttemptV1
from google_work_agent.application.agents.retrieval.contracts.retrieval_result import (
    EvidenceSelectionResultV2,
    PersonCandidateV1,
    SufficiencyResultV2,
)
from google_work_agent.application.agents.retrieval.resolve_availability import AvailableIntervalV1


class FinalizeRetrievalInput(TypedDict):
    request_intent: RequestIntentV2
    selection_result: EvidenceSelectionResultV2
    sufficiency_result: SufficiencyResultV2
    availability_results: list[AvailableIntervalV1]
    exclusion_obligation_segment_ids: list[str]
    query_attempts: list[QueryAttemptV1]
    person_candidates: list[PersonCandidateV1]
    selected_person_identities: dict[str, str]


def project_finalize_retrieval_input(state: Mapping[str, object]) -> FinalizeRetrievalInput:
    request_intent = state.get("request_intent")
    selection = state.get("evidence_selection")
    sufficiency = state.get("sufficiency")
    availability = state.get("availability_results", [])
    exclusions = state.get("exclusion_obligation_segment_ids", [])
    if not isinstance(request_intent, Mapping):
        raise ValueError("retrieval request_intent is required")
    if not isinstance(selection, Mapping):
        raise ValueError("retrieval evidence_selection is required")
    if not isinstance(sufficiency, Mapping):
        raise ValueError("retrieval sufficiency is required")
    if not isinstance(availability, list):
        raise ValueError("retrieval availability_results must be a list")
    if not isinstance(exclusions, list) or not all(isinstance(item, str) for item in exclusions):
        raise ValueError("retrieval exclusion obligations must be list[str]")
    return {
        "request_intent": cast(RequestIntentV2, request_intent),
        "selection_result": cast(EvidenceSelectionResultV2, selection),
        "sufficiency_result": cast(SufficiencyResultV2, sufficiency),
        "availability_results": cast(list[AvailableIntervalV1], availability),
        "exclusion_obligation_segment_ids": list(exclusions),
        "query_attempts": cast(list[QueryAttemptV1], state.get("query_attempts", [])),
        "person_candidates": cast(list[PersonCandidateV1], state.get("person_candidates", [])),
        "selected_person_identities": cast(
            dict[str, str], state.get("selected_person_identities", {}),
        ),
    }


__all__ = ["FinalizeRetrievalInput", "project_finalize_retrieval_input"]
