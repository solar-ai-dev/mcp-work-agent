from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from google_work_agent.application.agents.retrieval.resolve_relative_period import (
    resolve_relative_period,
)


def _now_ms() -> int:
    return int(datetime(2026, 9, 5, 14, 30, tzinfo=ZoneInfo("Asia/Seoul")).timestamp() * 1_000)


def test_relative_periods__resolve_against_user_local_calendar() -> None:
    constraints = [
        {"kind": "DATE", "field": "period", "value": ["지난 주"]},
        {"kind": "TIME", "field": "temporal_axis", "value": "MESSAGE_TIME"},
    ]

    result = resolve_relative_period(
        constraints,
        now_ms=_now_ms(),
        timezone="Asia/Seoul",
    )

    assert result == {
        "kind": "TEMPORAL_RANGE",
        "axis": "MESSAGE_TIME",
        "start_local": "2026-08-24T00:00:00",
        "end_local": "2026-08-31T00:00:00",
        "timezone": "Asia/Seoul",
    }


def test_recent__uses_bounded_thirty_day_window_including_today() -> None:
    result = resolve_relative_period(
        [
            {"kind": "DATE", "field": "period", "value": "최근"},
            {"kind": "TIME", "field": "temporal_axis", "value": "MESSAGE_TIME"},
        ],
        now_ms=_now_ms(),
        timezone="Asia/Seoul",
    )

    assert result is not None
    assert result["start_local"] == "2026-08-06T00:00:00"
    assert result["end_local"] == "2026-09-06T00:00:00"


def test_conflicting_relative_periods__do_not_guess_a_range() -> None:
    assert (
        resolve_relative_period(
            [{"kind": "DATE", "field": "period", "value": ["지난주", "최근"]}],
            now_ms=_now_ms(),
            timezone="Asia/Seoul",
        )
        is None
    )


@pytest.mark.parametrize(
    ("period", "start", "end"),
    [
        ("오늘", "2026-09-05", "2026-09-06"),
        ("어제", "2026-09-04", "2026-09-05"),
        ("이번주", "2026-08-31", "2026-09-07"),
        ("다음주", "2026-09-07", "2026-09-14"),
        ("지난달", "2026-08-01", "2026-09-01"),
        ("이번달", "2026-09-01", "2026-10-01"),
        ("9월", "2026-09-01", "2026-10-01"),
        ("9월 첫째주", "2026-09-01", "2026-09-08"),
        ("2026년 9월 첫째주", "2026-09-01", "2026-09-08"),
        ("2027년 1월 첫째주", "2027-01-01", "2027-01-08"),
    ],
)
@pytest.mark.parametrize("axis", ["MESSAGE_TIME", "EVENT_TIME"])
def test_calendar_bounds_preserve_the_requested_axis(
    period: str, start: str, end: str, axis: str
) -> None:
    result = resolve_relative_period(
        [
            {"kind": "DATE", "field": "period", "value": period},
            {"kind": "TIME", "field": "temporal_axis", "value": axis},
        ],
        now_ms=_now_ms(),
        timezone="Asia/Seoul",
    )
    assert result is not None
    assert result["axis"] == axis
    assert result["start_local"] == start + "T00:00:00"
    assert result["end_local"] == end + "T00:00:00"


def test_legacy_period_without_axis_is_not_silently_treated_as_message_time() -> None:
    assert (
        resolve_relative_period(
            [
                {"kind": "DATE", "field": "period", "value": "9월"},
            ],
            now_ms=_now_ms(),
            timezone="Asia/Seoul",
        )
        is None
    )


@pytest.mark.parametrize(("axis", "now", "period", "expected"), [
    ("MESSAGE_TIME", "2026-01-05", "12월", "2025-12-01"),
    ("EVENT_TIME", "2026-12-25", "1월 첫째주", "2027-01-01"),
    ("EVENT_TIME", "2026-01-05", "12월", "2025-12-01"),
    ("MESSAGE_TIME", "2026-01-05", "2027년 12월", "2027-12-01"),
])
def test_yearless_month__uses_axis_and_run_time__without_current_year_override(
    axis: str, now: str, period: str, expected: str,
) -> None:
    result = resolve_relative_period(
        [
            {"kind": "DATE", "field": "period", "value": period},
            {"kind": "TIME", "field": "temporal_axis", "value": axis},
        ],
        now_ms=int(
            datetime.fromisoformat(now).replace(tzinfo=ZoneInfo("Asia/Seoul")).timestamp() * 1000
        ),
        timezone="Asia/Seoul",
    )
    assert result is not None
    assert result["start_local"] == expected + "T00:00:00"
