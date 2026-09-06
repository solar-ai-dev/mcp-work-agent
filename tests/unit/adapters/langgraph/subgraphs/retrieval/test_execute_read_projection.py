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


def test_failed_read__survives_cache_hydration__without_becoming_empty_success():
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
        ("ALL", "프로젝트 일정"),
        ("ANY", "{프로젝트 일정}"),
    ],
)
def test_gmail_keyword_match_mode__lowers_to_distinct_provider_query(
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


@pytest.mark.parametrize("axis", ["MESSAGE_TIME", "EVENT_TIME"])
def test_gmail_temporal_lowering_does_not_confuse_event_and_receipt_dates(axis: str) -> None:
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
