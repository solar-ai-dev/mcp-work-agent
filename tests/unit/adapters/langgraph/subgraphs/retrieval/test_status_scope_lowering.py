"""A status allow-set must not become an intersection or an arbitrary member."""

from typing import cast

import pytest

from google_work_agent.adapters.langgraph.subgraphs.retrieval.projections import (
    execute_read_projection,
)
from google_work_agent.application.agents.retrieval.contracts.query_plan import SourceFetchPlanV1
from google_work_agent.application.agents.tool_routing.contracts.tool_route_plan import (
    InputToolRouteV1,
)


def _arguments(
    resource: str, tool: str, statuses: list[str], *, keyword: str | None = None
) -> dict[str, object]:
    connector = "github" if resource == "GITHUB_ISSUE" else "google_workspace"
    plan = cast(SourceFetchPlanV1, {
        "route_id": "shared-read",
        "connector_id": connector,
        "resource_type": resource,
        "operation_kind": "SEARCH",
        "effective_constraints": [
            *([{"kind": "KEYWORD", "terms": [keyword], "match_mode": "PHRASE"}]
              if keyword is not None else []),
            {"kind": "STATUS_SCOPE", "values": statuses},
            *([{"kind": "CONTAINER_REF", "container_refs": ["owner/repository"]}]
              if resource == "GITHUB_ISSUE" else []),
        ],
    })
    route = cast(InputToolRouteV1, {
        "route_id": "shared-read",
        "connector_id": connector,
        "resource_type": resource,
        "allowed_read_tool_ids": [tool],
        "work_unit_ids": ["work-1", "work-2"],
    })
    selected_tool, arguments = execute_read_projection.project_connector_call(
        plan, route=route, page_size=20
    )
    assert selected_tool == tool
    assert route["work_unit_ids"] == ["work-1", "work-2"]
    return arguments


@pytest.mark.parametrize("statuses,expected", [
    (["OPEN"], "OPEN"),
    (["CLOSED"], "CLOSED"),
    (["OPEN", "CLOSED"], "ALL"),
    (["CLOSED", "OPEN"], "ALL"),
    (["ANY"], "ALL"),
    (["ANY", "CLOSED"], "ALL"),
    (["OPEN", "OPEN"], "OPEN"),
])
def test_github_status_scope_keeps_every_allowed_state(statuses: list[str], expected: str) -> None:
    arguments = _arguments("GITHUB_ISSUE", "github_list_issues", statuses)
    assert arguments == {"repository": "owner/repository", "state": expected}


@pytest.mark.parametrize("statuses,expected", [
    (["DRAFT"], "in:drafts"),
    (["SENT"], "in:sent"),
    (["DRAFT", "SENT"], "{in:drafts in:sent}"),
    (["SENT", "DRAFT"], "{in:sent in:drafts}"),
    (["ANY"], ""),
    (["ANY", "SENT"], ""),
    (["DRAFT", "DRAFT"], "in:drafts"),
])
def test_gmail_status_scope_is_one_alternative_group(statuses: list[str], expected: str) -> None:
    arguments = _arguments("GMAIL_THREAD", "gmail_search_threads", statuses)
    assert arguments == {"query": expected, "page_size": 20, "include_thread_metadata": True}


def test_alternative_status_does_not_widen_the_other_search_constraints() -> None:
    arguments = _arguments(
        "GMAIL_THREAD", "gmail_search_threads", ["DRAFT", "SENT"], keyword="release review"
    )
    assert arguments["query"] == '"release review" {in:drafts in:sent}'
