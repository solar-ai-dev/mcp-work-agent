from typing import cast

from google_work_agent.application.agents.request_understanding.contracts.request_intent import (
    RequestIntentV2,
)
from google_work_agent.application.agents.retrieval.normalize_segments import SourceSegment
from google_work_agent.application.agents.retrieval.prioritize_material_gmail_evidence import (
    prioritize_material_gmail_evidence,
)
from google_work_agent.application.agents.retrieval.rag_retrieve_rerank import RagCandidateV1


def test_prioritize_material_gmail_evidence__bounded_analysis__promotes_material_over_notification(
) -> None:
    segments = [
        SourceSegment(
            segment_id=identifier,
            resource_handle=f"gmail_thread:{identifier}",
            source="GMAIL",
            resource_type="gmail_thread",
            resource_id=identifier,
            parent_id=None,
            version=None,
            locator={},
            text=text,
        )
        for identifier, text in [
            ("notice", "newsletter notification"),
            ("record", "회의록 결정 사항"),
        ]
    ]
    result = prioritize_material_gmail_evidence(
        {"schema_version": 2, "selected_segment_ids": ["notice"],
         "excluded_segment_ids": ["record"], "evidence_drafts": [
             {"segment_id": "notice", "role": "CONTEXT", "relevance_reason": "notification"},
         ]}, request_intent=cast(RequestIntentV2, {
             "analysis_requirement": "REQUIRED", "requested_effect_hints": ["READ"],
             "requested_resource_hints": ["GMAIL_THREAD"], "constraints": [
                 {"kind": "USER_REQUIREMENT", "field": "original_search_request",
                  "value": "회의에서 결정한 내용"},
             ],
         }), rag_candidates=[cast(RagCandidateV1, {
             "segment_id": segment.segment_id, "resource_ref": segment.resource_handle,
         }) for segment in segments], segments=segments, max_evidence=1,
    )
    assert result["selected_segment_ids"] == ["record"]
    assert result["excluded_segment_ids"] == []
    assert result["evidence_drafts"] == [
        {
            "segment_id": "record",
            "role": "SUPPORTS",
            "relevance_reason": "CONTENT_BEARING_WORK_RECORD",
        }
    ]
