import pytest

from google_work_agent.application.agents.retrieval.format_calendar_freebusy_evidence import (
    format_calendar_freebusy_evidence,
)


def test_format_calendar_freebusy_evidence__empty_busy_intervals__preserves_query_scope() -> None:
    result = format_calendar_freebusy_evidence({
        "time_min": "2026-09-01T00:00:00+09:00",
        "time_max": "2026-09-08T00:00:00+09:00", "busy_intervals": [],
    })
    assert "not an event or a write result" in result
    assert "query_time_min: 2026-09-01T00:00:00+09:00" in result
    assert "busy_intervals: []" in result


def test_format_calendar_freebusy_evidence__missing_busy_intervals__rejects_unknown_availability(
) -> None:
    with pytest.raises(ValueError, match="explicit busy intervals"):
        format_calendar_freebusy_evidence({"time_min": "start", "time_max": "end"})
