from __future__ import annotations

from collections.abc import Mapping
from typing import TypedDict, cast

from google_work_agent.application.agents.request_understanding.contracts.request_intent import (
    RequestIntentV2,
)
from google_work_agent.application.agents.retrieval.contracts.query_attempt import QueryAttemptV1
from google_work_agent.application.agents.retrieval.contracts.retrieval_result import (
    EvidenceSelectionResultV2,
    SufficiencyIssueV2,
)
from google_work_agent.application.agents.retrieval.rag_retrieve_rerank import RagCandidateV1


class SelectEvidenceInput(TypedDict):
    request_intent: RequestIntentV2
    rag_candidates: list[RagCandidateV1]
    exclusion_obligation_segment_ids: list[str]
    query_attempts: list[QueryAttemptV1]
    prior_selection: EvidenceSelectionResultV2 | None
    evidence_reassessment_issues: list[SufficiencyIssueV2]


def project_select_evidence_input(state: Mapping[str, object]) -> SelectEvidenceInput:
    request_intent = state.get("request_intent")
    rag_candidates = state.get("rag_candidates")
    exclusions = state.get("exclusion_obligation_segment_ids", [])
    reassessment_issues = state.get("evidence_reassessment_issues", [])
    if not isinstance(request_intent, Mapping):
        raise ValueError("retrieval request_intent is required")
    if not isinstance(rag_candidates, list):
        raise ValueError("retrieval rag_candidates are required")
    if not isinstance(exclusions, list) or not all(isinstance(item, str) for item in exclusions):
        raise ValueError("retrieval exclusion obligations must be list[str]")
    if not isinstance(reassessment_issues, list) or not all(
        isinstance(item, Mapping) for item in reassessment_issues
    ):
        raise ValueError("evidence reassessment issues must be a list of objects")
    return {
        "request_intent": cast(RequestIntentV2, request_intent),
        "rag_candidates": cast(list[RagCandidateV1], rag_candidates),
        "exclusion_obligation_segment_ids": list(exclusions),
        "query_attempts": cast(list[QueryAttemptV1], state.get("query_attempts", [])),
        "prior_selection": cast(EvidenceSelectionResultV2 | None, state.get("evidence_selection")),
        "evidence_reassessment_issues": cast(
            list[SufficiencyIssueV2], reassessment_issues
        ),
    }


__all__ = ["SelectEvidenceInput", "project_select_evidence_input"]
