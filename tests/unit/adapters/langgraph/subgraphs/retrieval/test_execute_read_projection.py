from datetime import datetime
from typing import cast
from zoneinfo import ZoneInfo

import pytest

from google_work_agent.adapters.langgraph.subgraphs.retrieval.projections import (
    execute_read_projection,
)
from google_work_agent.application.agents.retrieval.build_query import (
    RouteConstraintPolicy,
    build_query,
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


def test_calendar_event_projection__checkpoint_sanitization__preserves_write_evidence() -> None:
    plan = cast(
        SourceFetchPlanV1,
        {
            "route_id": "calendar-event-route",
            "connector_id": "google_workspace",
            "resource_type": "CALENDAR_EVENT",
        },
    )
    read = ConnectorReadResultV1(
        1,
        "calendar_get_event",
        "request",
        {
            "item": {
                "resource_type": "calendar_event",
                "resource_id": "event-1",
                "parent_id": "calendar-1",
                "version": "etag-1",
                "related_resource_ids": ["calendar-1"],
                "payload": {
                    "title": "현재 일정",
                    "start": "2026-09-14T15:00:00+09:00",
                    "end": "2026-09-14T15:30:00+09:00",
                    "timezone": "Asia/Seoul",
                    "location": "기존 회의실",
                    "description": "현재 설명",
                    "attendees": ["existing@example.com"],
                    "provider_internal": {"must": "not persist"},
                },
            }
        },
        None,
        0,
    )

    acquisition = execute_read_projection.sanitize_acquisition_result(
        execute_read_projection.project_acquisition_result([(plan, read)], remaining_budget={})
    )
    resources = cast(list[dict[str, object]], acquisition["source_summaries"][0]["resources"])

    assert resources[0]["payload"] == {
        "title": "현재 일정",
        "summary": None,
        "start": "2026-09-14T15:00:00+09:00",
        "end": "2026-09-14T15:30:00+09:00",
        "timezone": "Asia/Seoul",
        "status": None,
        "event_kind": None,
        "transparency": None,
        "self_response_status": None,
        "location": "기존 회의실",
        "description": "현재 설명",
        "attendees": ["existing@example.com"],
    }


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


def test_gmail_phrase_lowering__ordered_repeated_terms__preserves_order_and_repetition() -> None:
    route = cast(
        InputToolRouteV1,
        {
            "route_id": "route-gmail",
            "connector_id": "google_workspace",
            "resource_type": "GMAIL_THREAD",
            "allowed_read_tool_ids": ["gmail_search_threads"],
            "required": True,
            "reason_codes": ["USER_REQUEST"],
        },
    )
    plan = build_query(
        {
            "schema_version": 2,
            "route_queries": [
                {
                    "route_id": "route-gmail",
                    "operation": "SEARCH",
                    "reason_codes": ["USER_REQUEST"],
                    "search_spec": {
                        "mode": "INITIAL",
                        "constraints": [
                            {
                                "kind": "KEYWORD",
                                "terms": ["납품", "회신", "검토", "회신"],
                                "match_mode": "PHRASE",
                            }
                        ],
                    },
                    "detail_candidate_ref": None,
                }
            ],
        },
        frozen_routes=[route],
        route_policies={
            "route-gmail": RouteConstraintPolicy(frozenset({"KEYWORD"}))
        },
    )[0]

    _, arguments = execute_read_projection.project_connector_call(plan, route=route, page_size=20)

    assert arguments["query"] == '"납품 회신 검토 회신"'


def test_gmail_draft_search__for_frozen_draft_route__uses_draft_operation() -> None:
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
