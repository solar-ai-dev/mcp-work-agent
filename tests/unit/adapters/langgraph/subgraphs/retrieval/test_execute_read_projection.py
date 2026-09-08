from datetime import datetime
from typing import cast
from zoneinfo import ZoneInfo

import pytest

from google_work_agent.adapters.langgraph.subgraphs.retrieval.projections import (
    execute_read_projection,
)
from google_work_agent.application.agents.retrieval.contracts.query_plan import (
    SourceFetchPlanV1,
)
from google_work_agent.application.agents.tool_routing.contracts.tool_route_plan import (
    InputToolRouteV1,
)
from google_work_agent.ports.connector.connector_read_port import ConnectorReadResultV1


def test_freebusy_projection__checkpoint_sanitization__preserves_calendar_ownership() -> None:
    from google_work_agent.application.use_cases.action.calendar_conflict_policy import (
        CalendarWorkHours,
    )
    from google_work_agent.application.use_cases.action.calendar_conflicts import (
        evidence_calendar_conflict_risk,
    )

    plan = cast(SourceFetchPlanV1, {
        "route_id": "freebusy-route", "connector_id": "google_workspace",
        "resource_type": "CALENDAR_FREEBUSY", "query_identity_hash": "a" * 64,
        "effective_constraints": [{
            "kind": "TEMPORAL_RANGE", "axis": "AVAILABILITY_WINDOW",
            "start_local": "2026-09-10T10:00:00", "end_local": "2026-09-10T11:00:00",
            "timezone": "Asia/Seoul",
        }],
    })
    result = ConnectorReadResultV1(1, "calendar_query_freebusy", "request", {
        "calendars": [{"calendar_id": "calendar-1", "intervals": [{
            "start": "2026-09-10T01:00:00Z", "end": "2026-09-10T02:00:00Z", "transparency": "busy",
        }]}],
    }, None, 0)
    acquisition = execute_read_projection.sanitize_acquisition_result(
        execute_read_projection.project_acquisition_result([(plan, result)], remaining_budget={}),
    )
    risk = evidence_calendar_conflict_risk(
        arguments={"calendar_id": "calendar-1", "payload": {
            "start": "2026-09-10T10:00:00+09:00", "end": "2026-09-10T11:00:00+09:00",
        }}, acquisition_result=acquisition, checked_at_ms=123,
        work_hours=CalendarWorkHours(timezone="Asia/Seoul"),
    )
    assert cast(dict[str, object], risk["calendar_conflict"])["decision"] == "HARD_CONFLICT"


def test_failed_read__survives_cache_hydration__without_becoming_empty_success() -> None:
    failed_plan = cast(SourceFetchPlanV1, {
        "route_id": "failed-route", "connector_id": "github", "resource_type": "GITHUB_ISSUE",
    })
    successful_plan = cast(SourceFetchPlanV1, {
        "route_id": "ok-route", "connector_id": "github", "resource_type": "GITHUB_ISSUE",
    })
    successful_read = ConnectorReadResultV1(
        1, "github_list_issues", "request", {"items": []}, None, 0,
    )
    result = execute_read_projection.project_acquisition_result(
        [(successful_plan, successful_read)], remaining_budget={"pages": 2},
        failed_reads=[(failed_plan, "NOT_FOUND")],
    )
    assert result["status"] == "PARTIAL"
    hydrated = execute_read_projection.project_acquisition_result(
        [(successful_plan, successful_read)], remaining_budget={"pages": 2},
        prior_result=execute_read_projection.sanitize_acquisition_result(result),
    )
    assert hydrated["status"] == "PARTIAL"
    by_route = {item["route_id"]: item for item in hydrated["source_summaries"]}
    assert by_route["failed-route"]["error_code"] == "NOT_FOUND"
    assert by_route["failed-route"]["status"] == "FAILED"
    assert by_route["ok-route"]["status"] == "COMPLETE"
    assert len(hydrated["source_summaries"]) == 2


@pytest.mark.parametrize(
    ("match_mode", "expected"),
    [
        ("PHRASE", '"프로젝트 일정"'),
        ("ALL", '"프로젝트" "일정"'),
        ("ANY", '{"프로젝트" "일정"}'),
    ],
)
def test_gmail_keyword_lowering__different_match_modes__produces_distinct_queries(
    match_mode: str, expected: str
) -> None:
    plan = cast(
        SourceFetchPlanV1,
        {
            "route_id": "route-gmail",
            "connector_id": "google_workspace",
            "resource_type": "GMAIL_THREAD",
            "operation_kind": "SEARCH",
            "effective_constraints": [
                {
                    "kind": "KEYWORD",
                    "terms": ["프로젝트", "일정"],
                    "match_mode": match_mode,
                }
            ],
        },
    )
    route = cast(
        InputToolRouteV1,
        {"route_id": "route-gmail", "connector_id": "google_workspace",
         "resource_type": "GMAIL_THREAD", "allowed_read_tool_ids": ["gmail_search_threads"]},
    )

    tool_id, arguments = execute_read_projection.project_connector_call(
        plan, route=route, page_size=20
    )

    assert tool_id == "gmail_search_threads"
    assert arguments["query"] == expected


def test_gmail_draft_search__uses_draft_operation_inside_frozen_route() -> None:
    plan = cast(
        SourceFetchPlanV1,
        {
            "route_id": "route-draft",
            "connector_id": "google_workspace",
            "resource_type": "GMAIL_DRAFT",
            "operation_kind": "SEARCH",
            "effective_constraints": [
                {
                    "kind": "KEYWORD",
                    "terms": ["Quartz 납품 회신 검토"],
                    "match_mode": "PHRASE",
                }
            ],
        },
    )
    route = cast(
        InputToolRouteV1,
        {
            "route_id": "route-draft",
            "connector_id": "google_workspace",
            "resource_type": "GMAIL_DRAFT",
            "allowed_read_tool_ids": ["gmail_get_draft", "gmail_search_drafts"],
        },
    )

    tool_id, arguments = execute_read_projection.project_connector_call(
        plan, route=route, page_size=20
    )

    assert tool_id == "gmail_search_drafts"
    assert arguments == {"query": '"Quartz 납품 회신 검토"', "page_size": 20}


@pytest.mark.parametrize("axis", ["MESSAGE_TIME", "EVENT_TIME"])
def test_gmail_temporal_lowering__event_and_receipt_dates__keeps_axes_distinct(axis: str) -> None:
    plan = cast(
        SourceFetchPlanV1,
        {
            "route_id": "route-gmail",
            "connector_id": "google_workspace",
            "resource_type": "GMAIL_THREAD",
            "operation_kind": "SEARCH",
            "effective_constraints": [
                {"kind": "KEYWORD", "terms": ["체육대회"], "match_mode": "PHRASE"},
                {
                    "kind": "TEMPORAL_RANGE",
                    "axis": axis,
                    "start_local": "2026-09-01T00:00:00",
                    "end_local": "2026-09-08T00:00:00",
                    "timezone": "Asia/Seoul",
                },
            ],
        },
    )
    _, arguments = execute_read_projection.project_connector_call(
        plan,
        route=cast(InputToolRouteV1, {
            "route_id": "route-gmail", "connector_id": "google_workspace",
            "resource_type": "GMAIL_THREAD", "allowed_read_tool_ids": ["gmail_search_threads"],
        }),
        page_size=20,
    )
    expected = '"체육대회"'
    if axis == "MESSAGE_TIME":
        zone = ZoneInfo("Asia/Seoul")
        start = int(datetime(2026, 9, 1, tzinfo=zone).timestamp())
        end = int(datetime(2026, 9, 8, tzinfo=zone).timestamp())
        expected += f" after:{start} before:{end}"
    assert arguments["query"] == expected


@pytest.mark.parametrize("term", ['alpha" OR from:attacker@example.test', "alpha\nbeta", "a\\b"])
def test_gmail_keyword_lowering__query_grammar_escape__rejects_before_provider(term: str) -> None:
    plan = cast(SourceFetchPlanV1, {
        "route_id": "r", "connector_id": "google_workspace", "resource_type": "GMAIL_THREAD",
        "operation_kind": "SEARCH", "effective_constraints": [
            {"kind": "KEYWORD", "terms": [term], "match_mode": "ALL"},
        ],
    })
    with pytest.raises(ValueError):
        execute_read_projection.project_connector_call(
            plan, route=cast(InputToolRouteV1, {
                "route_id": "r", "connector_id": "google_workspace",
                "resource_type": "GMAIL_THREAD", "allowed_read_tool_ids": ["gmail_search_threads"],
            }), page_size=20,
        )
