"""Owner-local intermediate contracts for atomic Work Analysis operations."""

from __future__ import annotations

from typing import Literal, NotRequired, TypedDict

from google_work_agent.application.agents.work_analysis.contracts.work_analysis_result import (
    WorkAmbiguityV1,
    WorkRelationV1,
    WorkRiskV1,
)
from google_work_agent.ports.system.contracts.workflow_signal import (
    RetrievalNeedV1,
)


class WorkAnalysisSemanticInputV1(TypedDict):
    user_request: str
    request_intent: dict[str, object]
    evidence: list[dict[str, object]]
    availability_results: NotRequired[list[dict[str, object]]]
    confirmation_response: NotRequired[dict[str, object]]
    task_duplicate_review_required: NotRequired[bool]


class DuplicateConflictAssessmentV1(TypedDict):
    relation_candidates: list[WorkRelationV1]
    requested_work_status: Literal["NOT_APPLICABLE", "SATISFIED", "NOT_SATISFIED", "UNDETERMINED"]
    requested_work_reason: str | None
    matched_fact_ids: list[str]
    evidence_refs: list[str]


class InformationGapAssessmentV1(TypedDict):
    disposition: Literal[
        "COMPLETE",
        "NEEDS_MORE_DATA",
        "NEEDS_CONFIRMATION",
        "ROUTE_RECONSIDERATION_REQUIRED",
        "BLOCKED",
    ]
    ambiguities: list[WorkAmbiguityV1]
    retrieval_needs: list[RetrievalNeedV1]
    evidence_refs: list[str]
    question: NotRequired[str]
    options: NotRequired[list[str]]
    reason_codes: NotRequired[list[str]]


class OperationalRiskAssessmentV1(TypedDict):
    risks: list[WorkRiskV1]
    evidence_refs: list[str]
