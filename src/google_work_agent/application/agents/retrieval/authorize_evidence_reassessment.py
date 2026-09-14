"""Authorize one evidence reassessment after observed insufficiency."""

from __future__ import annotations

from collections.abc import Sequence

from google_work_agent.application.agents.retrieval.contracts.retrieval_result import (
    EvidenceSelectionResultV2,
    SufficiencyIssueV2,
    SufficiencyResultV2,
)
from google_work_agent.application.agents.retrieval.normalize_segments import SourceSegment
from google_work_agent.application.agents.retrieval.rag_retrieve_rerank import RagCandidateV1
from google_work_agent.application.use_cases.run.guard_run_budget import (
    BudgetDecision,
    RunBudgetV2,
    approve_semantic_revision,
    build_semantic_failure_signature_v1,
)

_FAILURE_REASON = "EVIDENCE_SELECTION_INSUFFICIENT_AFTER_DETAIL"


def authorize_evidence_reassessment(
    *,
    sufficiency: SufficiencyResultV2,
    selection: EvidenceSelectionResultV2,
    candidates: Sequence[RagCandidateV1],
    segments: Sequence[SourceSegment],
    retry_budget: RunBudgetV2,
    can_acquire_new_information: bool,
) -> tuple[list[SufficiencyIssueV2], RunBudgetV2]:
    """Return feedback for one bounded reassessment of already-read detail."""

    if (
        sufficiency["status"] != "PARTIAL"
        or can_acquire_new_information
        or not any(
            issue["required"]
            and issue["resolution_source"] in {"GOOGLE", "CONNECTOR"}
            for issue in sufficiency["issues"]
        )
    ):
        return [], retry_budget

    visible_ids = {candidate["segment_id"] for candidate in candidates}
    assessed_ids = set(selection["selected_segment_ids"]) | set(
        selection["excluded_segment_ids"]
    )
    has_reassessable_detail = any(
        segment.segment_id in visible_ids
        and segment.segment_id in assessed_ids
        and (
            segment.locator.get("message_id") is not None
            or segment.locator.get("is_metadata_only") is False
        )
        for segment in segments
    )
    if not has_reassessable_detail:
        return [], retry_budget

    decision = approve_semantic_revision(
        retry_budget,
        signature=build_semantic_failure_signature_v1(
            node_id="retrieval.select_evidence",
            failure_reason_codes=[_FAILURE_REASON],
        ),
    )
    if decision["decision"] == BudgetDecision.DENY.value:
        return [], decision["run_budget"]
    return list(sufficiency["issues"]), decision["run_budget"]


__all__ = ["authorize_evidence_reassessment"]
