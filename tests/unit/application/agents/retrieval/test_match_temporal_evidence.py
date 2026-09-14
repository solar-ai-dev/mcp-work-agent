from typing import cast

import pytest

from google_work_agent.application.agents.retrieval.contracts.query_attempt import QueryAttemptV1
from google_work_agent.application.agents.retrieval.contracts.query_plan import (
    TemporalRangeConstraintV1,
)
from google_work_agent.application.agents.retrieval.contracts.retrieval_result import (
    EvidenceDraftV1,
)
from google_work_agent.application.agents.retrieval.match_temporal_evidence import (
    has_only_reporting_period_dates,
    match_temporal_evidence,
    project_event_date_candidates,
    project_unresolved_event_dates,
)
from google_work_agent.application.agents.retrieval.normalize_segments import SourceSegment


def test_reporting_period__does_not_prove_event__or_hide_separate_event_date() -> None:
    period = "집계 기간은 2026년 9월 1일부터 9월 7일까지입니다."
    assert has_only_reporting_period_dates(period)
    assert not has_only_reporting_period_dates(period + "행사는 9월 4일 열립니다.")
    assert not has_only_reporting_period_dates("행사는 9월 1일부터 9월 7일까지입니다.")


@pytest.mark.parametrize(
    "resource_type, expected",
    [("GMAIL_THREAD", True), ("CALENDAR_EVENT", False)],
)
def test_unresolved_event_year__respects_resource_scope__in_cross_resource_read(
    first_week: TemporalRangeConstraintV1,
    resource_type: str,
    expected: bool,
) -> None:
    evidence = cast(
        EvidenceDraftV1,
        {
            "evidence_id": "e1",
            "resource_handle": "gmail_thread:t",
            "excerpt": "연수는 9월 4일입니다.",
            "reason_codes": ["CONTEXT"],
        },
    )
    attempt = cast(
        QueryAttemptV1,
        {
            "route_id": "route",
            "resource_type": resource_type,
            "operation_kind": "SEARCH",
            "normalized_intent_constraints": [first_week],
        },
    )
    unresolved = project_unresolved_event_dates([evidence], [attempt])
    assert bool(unresolved) is expected
    if expected:
        assert unresolved == [{"evidence_id": "e1", "source_text": "9월 4일"}]


@pytest.fixture
def first_week() -> TemporalRangeConstraintV1:
    return {
        "kind": "TEMPORAL_RANGE",
        "axis": "EVENT_TIME",
        "timezone": "Asia/Seoul",
        "start_local": "2026-09-01T00:00:00",
        "end_local": "2026-09-08T00:00:00",
    }


def test_date_mentions__inside_followup_and_outside_meeting__distinguishes(
    first_week: TemporalRangeConstraintV1,
) -> None:
    text = "회의는 2026년 9월 8일입니다. 후속 업무 예정일은 9월 7일입니다."
    candidates = project_event_date_candidates(text, first_week)
    assert candidates == [
        {
            "source_text": "2026년 9월 8일",
            "candidate_date": "2026-09-08",
            "year_explicit": True,
            "date_intersects_window": False,
        },
        {
            "source_text": "9월 7일",
            "candidate_date": "2026-09-07",
            "year_explicit": False,
            "date_intersects_window": True,
        },
    ]


@pytest.mark.parametrize(
    "day, expected",
    [
        (1, True),
        (3, True),
        (7, True),
        (8, False),
        (30, False),
    ],
)
def test_first_week_dates__day_bounds__matches_deterministically(
    first_week: TemporalRangeConstraintV1, day: int, expected: bool
) -> None:
    text = f"행사는 2026년 9월 {day}일입니다."
    candidates = project_event_date_candidates(text, first_week)
    assert candidates[0]["date_intersects_window"] is expected
    segment = SourceSegment(
        "s", "gmail_thread:t", "GMAIL", "gmail_thread", "t", None, None, {}, text
    )
    assert match_temporal_evidence(segment, first_week) is expected


def test_event_date_candidates__receipt_or_invalid_dates__excludes(
    first_week: TemporalRangeConstraintV1,
) -> None:
    assert (
        project_event_date_candidates(
            "Received: 2026-09-03\nMessage: 09/03\n2026년 2월 30일 행사",
            first_week,
        )
        == []
    )


def test_event_date_candidates__explicit_other_year__does_not_reinterpret(
    first_week: TemporalRangeConstraintV1,
) -> None:
    candidates = project_event_date_candidates("2025년 9월 3일 행사", first_week)
    assert candidates[0]["candidate_date"] == "2025-09-03"
    assert candidates[0]["date_intersects_window"] is False


def test_event_date_candidates__message_time_target__does_not_annotate_body(
    first_week: TemporalRangeConstraintV1,
) -> None:
    message_time = cast(TemporalRangeConstraintV1, {**first_week, "axis": "MESSAGE_TIME"})
    assert (
        project_event_date_candidates(
            "2026년 9월 3일 행사",
            message_time,
        )
        == []
    )


def test_event_date_candidates__date_only_and_noon_end__detects_overlap(
    first_week: TemporalRangeConstraintV1,
) -> None:
    noon_end = cast(
        TemporalRangeConstraintV1,
        {**first_week, "end_local": "2026-09-08T12:00:00"},
    )
    candidates = project_event_date_candidates(
        "2026년 9월 8일 행사",
        noon_end,
    )
    assert candidates[0]["date_intersects_window"] is True
