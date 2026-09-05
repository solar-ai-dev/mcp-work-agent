import pytest

from google_work_agent.application.agents.retrieval.match_temporal_evidence import (
    match_temporal_evidence,
    project_event_date_candidates,
)
from google_work_agent.application.agents.retrieval.normalize_segments import SourceSegment


@pytest.fixture
def first_week():
    return {"kind": "TEMPORAL_RANGE", "axis": "EVENT_TIME", "timezone": "Asia/Seoul",
            "start_local": "2026-09-01T00:00:00", "end_local": "2026-09-08T00:00:00"}


def test_date_mentions_distinguish_inside_followup_and_outside_meeting(first_week):
    text = "회의는 2026년 9월 8일입니다. 후속 업무 예정일은 9월 7일입니다."
    candidates = project_event_date_candidates(text, first_week)
    assert candidates == [
        {"source_text": "2026년 9월 8일", "candidate_date": "2026-09-08",
         "year_explicit": True, "date_intersects_window": False},
        {"source_text": "9월 7일", "candidate_date": "2026-09-07",
         "year_explicit": False, "date_intersects_window": True},
    ]


@pytest.mark.parametrize("day, expected", [
    (1, True), (3, True), (7, True), (8, False), (30, False),
])
def test_first_week_day_bounds_are_deterministic(first_week, day, expected):
    text = f"행사는 2026년 9월 {day}일입니다."
    candidates = project_event_date_candidates(text, first_week)
    assert candidates[0]["date_intersects_window"] is expected
    segment = SourceSegment("s", "gmail_thread:t", "GMAIL", "gmail_thread", "t",
                            None, None, {}, text)
    assert match_temporal_evidence(segment, first_week) is expected


def test_receipt_and_invalid_dates_are_not_body_event_candidates(first_week):
    assert project_event_date_candidates(
        "Received: 2026-09-03\nMessage: 09/03\n2026년 2월 30일 행사", first_week,
    ) == []


def test_explicit_other_year_is_not_reinterpreted_as_target_year(first_week):
    candidates = project_event_date_candidates("2025년 9월 3일 행사", first_week)
    assert candidates[0]["candidate_date"] == "2025-09-03"
    assert candidates[0]["date_intersects_window"] is False


def test_message_time_target_does_not_annotate_body_as_receipt_time(first_week):
    assert project_event_date_candidates(
        "2026년 9월 3일 행사", {**first_week, "axis": "MESSAGE_TIME"},
    ) == []


def test_date_only_mention_can_overlap_a_window_ending_at_noon(first_week):
    candidates = project_event_date_candidates(
        "2026년 9월 8일 행사", {**first_week, "end_local": "2026-09-08T12:00:00"},
    )
    assert candidates[0]["date_intersects_window"] is True
