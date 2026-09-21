from typing import cast

from evaluation.bm25_rank_candidate import bm25_rag_retrieve_rerank

from google_work_agent.application.agents.request_understanding.contracts.request_intent import (
    RequestIntentV3,
)
from google_work_agent.application.agents.retrieval.normalize_segments import SourceSegment


def _segment(segment_id: str, resource_id: str, text: str) -> SourceSegment:
    return SourceSegment(
        segment_id,
        f"gmail_message:{resource_id}",
        "GMAIL",
        "gmail_message",
        resource_id,
        None,
        None,
        {},
        text,
    )


def test_bm25_candidate_scores_frequency_but_keeps_selected_resource() -> None:
    intent = cast(RequestIntentV3, {"goal": "alpha", "constraints": []})
    segments = [
        _segment("repeated", "r1", "alpha alpha"),
        _segment("single", "r2", "alpha"),
        _segment("noise", "r3", "omega"),
    ]

    ranked = bm25_rag_retrieve_rerank(segments, request_intent=intent, source_plans=[], top_k=3)

    assert [item["segment_id"] for item in ranked] == ["repeated", "single", "noise"]
    assert all(item["retrieval_score"] < 15 for item in ranked)
    selected_intent = cast(
        RequestIntentV3,
        {
            "goal": "alpha",
            "constraints": [{"kind": "RESOURCE", "field": "selected_resource", "value": "r3"}],
        },
    )
    selected = bm25_rag_retrieve_rerank(
        segments, request_intent=selected_intent, source_plans=[], top_k=1
    )
    assert [item["segment_id"] for item in selected] == ["noise"]
    assert "EXACT_RESOURCE" in selected[0]["reason_codes"]
