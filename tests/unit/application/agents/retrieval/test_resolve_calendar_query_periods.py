from datetime import datetime
from zoneinfo import ZoneInfo

from google_work_agent.application.agents.retrieval.resolve_calendar_query_periods import (
    resolve_calendar_query_periods,
)


def test_calendar_period__event_and_availability_routes__binds_distinct_axes() -> None:
    result = resolve_calendar_query_periods(
        prompt_input={
            "request_intent": {
                "constraints": [
                    {"kind": "DATE", "field": "period", "value": "내일"},
                ]
            }
        },
        frozen_routes=[
            {
                "route_id": "event",
                "connector_id": "google_workspace",
                "resource_type": "CALENDAR_EVENT",
                "allowed_read_tool_ids": ["calendar_search_events"],
                "required": True,
                "reason_codes": ["REQUESTED_INPUT"],
            },
            {
                "route_id": "availability",
                "connector_id": "google_workspace",
                "resource_type": "CALENDAR_FREEBUSY",
                "allowed_read_tool_ids": ["calendar_query_freebusy"],
                "required": True,
                "reason_codes": ["POLICY_CALENDAR_CONFLICT_CHECK"],
            },
        ],
        now_ms=int(datetime(2026, 9, 5, tzinfo=ZoneInfo("Asia/Seoul")).timestamp() * 1_000),
        timezone="Asia/Seoul",
    )

    assert result["event"]["axis"] == "EVENT_TIME"
    assert result["availability"]["axis"] == "AVAILABILITY_WINDOW"
    assert result["event"]["start_local"] == "2026-09-06T00:00:00"
    assert result["availability"]["end_local"] == "2026-09-07T00:00:00"


def test_calendar_period__message_time_axis__does_not_bind_calendar_route() -> None:
    result = resolve_calendar_query_periods(
        prompt_input={
            "request_intent": {
                "constraints": [
                    {"kind": "DATE", "field": "period", "value": "오늘"},
                    {
                        "kind": "TIME",
                        "field": "temporal_axis",
                        "value": ["MESSAGE_TIME"],
                    },
                ]
            }
        },
        frozen_routes=[
            {
                "route_id": "event",
                "connector_id": "google_workspace",
                "resource_type": "CALENDAR_EVENT",
                "allowed_read_tool_ids": ["calendar_search_events"],
                "required": True,
                "reason_codes": ["REQUESTED_INPUT"],
            }
        ],
        now_ms=1,
        timezone="Asia/Seoul",
    )

    assert result == {}
