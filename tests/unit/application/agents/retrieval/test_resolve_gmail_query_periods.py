"""Tests for Gmail query period resolution."""

from datetime import datetime
from zoneinfo import ZoneInfo

from google_work_agent.application.agents.retrieval.resolve_gmail_query_periods import (
    resolve_gmail_query_periods,
)
from google_work_agent.application.agents.tool_routing.contracts.tool_route_plan import (
    InputToolRouteV1,
)


def test_resolve_gmail_query_periods__relative_period__binds_searchable_route() -> None:
    route: InputToolRouteV1 = {
        "route_id": "gmail",
        "resource_type": "GMAIL_THREAD",
        "connector_id": "google_workspace",
        "allowed_read_tool_ids": ["gmail_search_threads"],
        "required": True,
        "reason_codes": ["USER_REQUEST"],
    }
    prompt_input = {
        "request_intent": {
            "constraints": [
                {"kind": "DATE", "field": "period", "value": ["이번 주"]},
                {
                    "kind": "TIME",
                    "field": "temporal_axis",
                    "value": ["MESSAGE_TIME"],
                },
            ]
        }
    }

    resolved = resolve_gmail_query_periods(
        prompt_input=prompt_input,
        frozen_routes=[route],
        now_ms=int(datetime(2026, 9, 11, tzinfo=ZoneInfo("Asia/Seoul")).timestamp() * 1000),
        timezone="Asia/Seoul",
    )

    assert set(resolved) == {"gmail"}
