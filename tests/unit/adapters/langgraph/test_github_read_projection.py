from typing import cast

from google_work_agent.adapters.langgraph.subgraphs.retrieval.projections.execute_read_projection import (
    project_connector_call,
)
from google_work_agent.application.agents.retrieval.contracts.query_plan import SourceFetchPlanV1
from google_work_agent.application.agents.tool_routing.contracts.tool_route_plan import (
    InputToolRouteV1,
)


def test_github_issue_search__projects_repository__and_state() -> None:
    plan = cast(
        SourceFetchPlanV1,
        {
            "schema_version": 1,
            "route_id": "route-1",
            "connector_id": "github",
            "resource_type": "GITHUB_ISSUE",
            "operation_kind": "SEARCH",
            "effective_constraints": [
                {"kind": "CONTAINER_REF", "container_refs": ["acme/repo"]},
                {"kind": "STATUS_SCOPE", "values": ["OPEN"]},
            ],
            "query_identity_hash": "a" * 64,
            "prior_read_result_handle": None,
            "detail_candidate_ref": None,
        },
    )
    route = cast(
        InputToolRouteV1,
        {
            "route_id": "route-1",
            "resource_type": "GITHUB_ISSUE",
            "connector_id": "github",
            "allowed_read_tool_ids": ["github_list_issues", "github_get_issue"],
            "required": True,
            "reason_codes": ["REQUESTED_INPUT"],
        },
    )

    tool_id, arguments = project_connector_call(plan, route=route, page_size=50)

    assert tool_id == "github_list_issues"
    assert arguments == {"repository": "acme/repo", "state": "OPEN"}


def test_github_issue_detail__uses_normalized__composite_identity() -> None:
    plan = cast(
        SourceFetchPlanV1,
        {
            "schema_version": 1,
            "route_id": "route-1",
            "connector_id": "github",
            "resource_type": "GITHUB_ISSUE",
            "operation_kind": "DETAIL_FETCH",
            "effective_constraints": [],
            "query_identity_hash": "a" * 64,
            "prior_read_result_handle": None,
            "detail_candidate_ref": "github_issue:acme/repo#7",
        },
    )
    route = cast(
        InputToolRouteV1,
        {
            "route_id": "route-1",
            "resource_type": "GITHUB_ISSUE",
            "connector_id": "github",
            "allowed_read_tool_ids": ["github_get_issue"],
            "required": True,
            "reason_codes": ["REQUESTED_INPUT"],
        },
    )
    resource = {
        "resource_id": "acme/repo#7",
        "parent_id": "acme/repo",
        "payload": {"repository": "acme/repo", "issue_number": 7},
    }

    tool_id, arguments = project_connector_call(
        plan,
        route=route,
        page_size=1,
        detail_resource=resource,
    )

    assert tool_id == "github_get_issue"
    assert arguments == {"repository": "acme/repo", "issue_number": 7}
