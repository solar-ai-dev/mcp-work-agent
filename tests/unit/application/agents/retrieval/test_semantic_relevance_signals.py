"""Candidate ranking does not turn metadata, names, or dates into resolved facts."""

from typing import cast

import pytest

from google_work_agent.application.agents.request_understanding.contracts.request_intent import (
    RequestIntentV2,
)
from google_work_agent.application.agents.retrieval.contracts.query_plan import (
    SourceFetchPlanV1,
    TemporalRangeConstraintV1,
)
from google_work_agent.application.agents.retrieval.match_person_mention import match_person_mention
from google_work_agent.application.agents.retrieval.match_temporal_evidence import (
    match_temporal_evidence,
)
from google_work_agent.application.agents.retrieval.normalize_segments import SourceSegment
from google_work_agent.application.agents.retrieval.rag_retrieve_rerank import rag_retrieve_rerank

WINDOW: TemporalRangeConstraintV1 = {
    "kind": "TEMPORAL_RANGE", "axis": "EVENT_TIME", "start_local": "2026-09-01T00:00:00",
    "end_local": "2026-09-08T00:00:00", "timezone": "Asia/Seoul",
}


def _segment(key: str, text: str, **locator: object) -> SourceSegment:
    return SourceSegment(key, f"gmail_thread:{key}", "GMAIL", "gmail_thread", key,
                         None, None, dict(locator), text)


@pytest.mark.parametrize(("text", "matches"), [
    ("2026년 9월 3일 체육대회", True), ("2026-09-03 박람회 참석", True),
    ("9월 3일 방문", True), ("2025년 9월 3일 회의", False),
    ("9월 8일 교육", False), ("8월 31일 출장", False),
    ("2026년 9월 31일 행사", False), ("Received: 2026-09-03T10:00:00+09:00", False),
])
def test_event_candidate__receipt_header__does_not_infer_event_date(
    text: str, matches: bool
) -> None:
    assert match_temporal_evidence(
        _segment("a", text, received_at="2026-08-20T10:00:00+09:00"), WINDOW,
    ) is matches


@pytest.mark.parametrize(("received", "matches"), [
    ("2026-08-31T15:00:00+00:00", True), ("2026-09-07T14:59:59+00:00", True),
    ("2026-09-07T15:00:00+00:00", False), ("2026-09-03T10:00:00", False),
    ("Thu, 3 Sep 2026 10:00:00 +0900", True), ("invalid", False), (None, False),
])
def test_receipt_candidate__body_and_provider_timestamp__uses_provider_timestamp(
    received: object, matches: bool,
) -> None:
    assert match_temporal_evidence(
        _segment("a", "2026년 9월 3일 행사", received_at=received),
        {**WINDOW, "axis": "MESSAGE_TIME"},
    ) is matches


@pytest.mark.parametrize(("mention", "display_name", "matches"), [
    ("김대리", "김철수 대리", True), ("김 대리", "김정우 대리", True),
    ("김대리", "이철수 대리", False), ("김대리", "김철수 과장", False),
    ("김철수 대리", "김정우 대리", False), ("김철수 대리", "김철수 대리", True),
    ("이과장", "이서연 과장", True), ("이과장", "김서연 과장", False),
    ("박 팀장", "박지훈 팀장", True), ("박 팀장", "박지훈 대리", False),
    ("정수진 부장", "정수민 부장", False),
    ("김하늘", "김하늘 대리", True), ("김하늘", "김하늘대리", True),
    ("김하늘", "김하늘 과장", True), ("김", "김하늘 대리", False),
    ("하늘", "김하늘 대리", False), ("김하늘", "김하늘빛 대리", False),
    ("Alex Morgan", "Alex Morgan", True), ("Alex Morgan", "Alex Taylor", False),
])
def test_person_match__abbreviated_name__remains_candidate(
    mention: str, display_name: str, matches: bool,
) -> None:
    assert match_person_mention(mention, display_name) is matches


def test_relevance_signals__plan_and_provider_metadata__retains_binding() -> None:
    intent = cast(RequestIntentV2, {
        "goal": "조회", "constraints": [{"kind": "PERSON", "field": "person", "value": "김대리"}],
    })
    plans = [cast(SourceFetchPlanV1, {
        "resource_type": "GMAIL_THREAD", "effective_constraints": [
            WINDOW, {**WINDOW, "axis": "MESSAGE_TIME"},
            {"kind": "KEYWORD", "terms": ["KAN-93"], "match_mode": "PHRASE"},
            {"kind": "CONCEPT", "concept": "일정", "manifestations": ["박람회", "참석"]},
            {"kind": "PARTICIPANT", "participants": [
                {"role": "SENDER", "identity": "kim@example.com"},
            ], "match_mode": "ALL"},
        ],
    })]
    segments = [
        _segment("a", "KAN-93 박람회 참석 2026년 9월 3일", sender_name="김철수 대리",
                 sender_email="kim@example.com", received_at="2026-09-02T09:00:00+09:00"),
        SourceSegment("b", "gmail_message:reply", "GMAIL", "gmail_message", "reply", "a",
                      None, {"thread_id": "a"}, "네 확인했습니다."),
        _segment("c", "김철수 대리 kim@example.com", sender_name="이정우 대리",
                 sender_email="lee@example.com"),
    ]
    ranked = rag_retrieve_rerank(segments, request_intent=intent, source_plans=plans, top_k=3)
    assert [item["segment_id"] for item in ranked] == ["a", "b", "c"]
    assert set(ranked[0]["reason_codes"]) == {
        "EXACT_LEXICAL_ANCHOR", "CONCEPT_MANIFESTATION_MATCH", "ENTITY_CANDIDATE_MATCH",
        "RESOLVED_PARTICIPANT_MATCH", "MESSAGE_TIME_MATCH", "EVENT_TIME_CANDIDATE_MATCH",
    }
    assert ranked[1]["reason_codes"] == ["THREAD_LINEAGE_MATCH"]
    assert ranked[2]["reason_codes"] == []
    assert set(ranked[0]) == {"segment_id", "resource_ref", "retrieval_score", "reason_codes"}


def test_relevance_signals__calendar_window_and_gmail__does_not_confuse_date_or_sender() -> None:
    intent = cast(RequestIntentV2, {"goal": "조회", "constraints": []})
    plan = cast(SourceFetchPlanV1, {
        "resource_type": "CALENDAR_EVENT", "effective_constraints": [WINDOW],
    })
    ranked = rag_retrieve_rerank(
        [_segment("a", "2026-09-03")], request_intent=intent, source_plans=[plan], top_k=1,
    )
    assert ranked[0]["reason_codes"] == []
