from google_work_agent.application.agents.retrieval.authorize_evidence_reassessment import (
    authorize_evidence_reassessment,
)
from google_work_agent.application.agents.retrieval.contracts.retrieval_result import (
    EvidenceSelectionResultV2,
    SufficiencyIssueV2,
    SufficiencyResultV2,
)
from google_work_agent.application.agents.retrieval.normalize_segments import SourceSegment
from google_work_agent.application.agents.retrieval.rag_retrieve_rerank import RagCandidateV1
from google_work_agent.application.use_cases.run.guard_run_budget import (
    build_default_run_budget,
)


def test_evidence_reassessment__with_reusable_detail__is_bounded_once() -> None:
    issue = SufficiencyIssueV2(
        slot="requested_fact_support",
        issue_type="MISSING",
        required=True,
        resolution_source="GOOGLE",
        safety_critical=False,
        reason_codes=["NO_SELECTED_EVIDENCE_SUPPORTS_REQUESTED_FACT"],
    )
    sufficiency = SufficiencyResultV2(
        schema_version=2,
        status="PARTIAL",
        issues=[issue],
    )
    selection = EvidenceSelectionResultV2(
        schema_version=2,
        evidence_drafts=[],
        selected_segment_ids=["segment-1"],
        excluded_segment_ids=[],
    )
    candidates = [
        RagCandidateV1(
            segment_id="segment-1",
            resource_ref="gmail_thread:thread-1",
            retrieval_score=1.0,
            reason_codes=[],
        )
    ]
    segments = [
        SourceSegment(
            "segment-1",
            "gmail_thread:thread-1",
            "GMAIL",
            "gmail_message",
            "message-1",
            "thread-1",
            None,
            {"is_metadata_only": False},
            "확인할 상세 본문",
        )
    ]
    budget = build_default_run_budget()

    feedback, revised_budget = authorize_evidence_reassessment(
        sufficiency=sufficiency,
        selection=selection,
        candidates=candidates,
        segments=segments,
        retry_budget=budget,
        can_acquire_new_information=False,
    )
    repeated_feedback, final_budget = authorize_evidence_reassessment(
        sufficiency=sufficiency,
        selection=selection,
        candidates=candidates,
        segments=segments,
        retry_budget=revised_budget,
        can_acquire_new_information=False,
    )

    assert feedback == [issue]
    assert revised_budget["semantic_revisions_used_by_failure"] == {
        "retrieval.select_evidence\x1fEVIDENCE_SELECTION_INSUFFICIENT_AFTER_DETAIL": 1
    }
    assert repeated_feedback == []
    assert final_budget == revised_budget
