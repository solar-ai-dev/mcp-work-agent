"""Task acquisition scope belongs to query identity, not just Connector flags."""

from copy import deepcopy
from typing import Any, cast

import pytest

from google_work_agent.adapters.langgraph.subgraphs.retrieval.projections import (
    execute_read_projection,
)
from google_work_agent.application.agents.retrieval.build_query import (
    QueryUnchangedAfterFailureError,
    RouteConstraintPolicy,
    build_query,
    materialize_container_read_plans,
)
from google_work_agent.application.agents.retrieval.contracts.query_plan import (
    RetrievalV2ValidationError,
)
from google_work_agent.application.agents.tool_routing.contracts.tool_route_plan import (
    InputToolRouteV1,
)

ROUTE = cast(
    InputToolRouteV1,
    {
        "route_id": "task-read",
        "connector_id": "google_workspace",
        "resource_type": "TASK",
        "allowed_read_tool_ids": ["tasks_list_tasks", "tasks_get_task"],
        "required": True,
        "reason_codes": ["REQUESTED_INPUT"],
        "work_unit_ids": ["work-1"],
    },
)


def _plan(operation: str = "SEARCH") -> dict[str, Any]:
    return {
        "schema_version": 2,
        "route_queries": [
            {
                "route_id": "task-read",
                "operation": operation,
                "reason_codes": ["REQUESTED_INPUT"],
                "search_spec": {"mode": "INITIAL", "constraints": []}
                if operation == "SEARCH"
                else None,
                "detail_candidate_ref": None,
            }
        ],
    }


def _policy(scope: str | None) -> dict[str, RouteConstraintPolicy]:
    return {
        "task-read": RouteConstraintPolicy(
            frozenset({"CONTAINER_REF"}),
            frozenset({"CONTAINER_REF"}),
            task_collection_scope=cast(Any, scope),
        )
    }


def _build(scope: str | None, plan: object = None, **kwargs: Any) -> Any:
    return build_query(
        _plan() if plan is None else plan,
        frozen_routes=[ROUTE],
        route_policies=_policy(scope),
        validated_container_refs={"task-read": ["list-a"]},
        **kwargs,
    )[0]


def test_build_query__collection_scope__binds_hash_and_flags_without_changing_route() -> None:
    broad, narrow = _build("ANY"), _build("INCOMPLETE")
    assert broad["query_identity_hash"] != narrow["query_identity_hash"]
    for plan, include_completed in ((broad, True), (narrow, False)):
        assert plan["route_id"] == ROUTE["route_id"]
        tool, arguments = execute_read_projection.project_connector_call(
            plan, route=ROUTE, page_size=20
        )
        assert tool == "tasks_list_tasks"
        assert arguments == {
            "task_list_id": "list-a",
            "page_size": 20,
            "show_completed": include_completed,
            "show_hidden": include_completed,
            "show_deleted": False,
        }


@pytest.mark.parametrize("scope", ["ANY", "INCOMPLETE"])
def test_build_query__next_page__inherits_scope_and_query_identity(scope: str) -> None:
    prior = _build(scope)
    page = _build(
        scope,
        _plan("NEXT_PAGE"),
        prior_plans={"task-read": prior},
        prior_read_result_handles={"task-read": "read-result-1"},
    )
    assert page["effective_constraints"] == prior["effective_constraints"]
    assert page["query_identity_hash"] == prior["query_identity_hash"]
    assert execute_read_projection.project_connector_call(
        page, route=ROUTE, page_size=20
    ) == execute_read_projection.project_connector_call(
        prior,
        route=ROUTE,
        page_size=20,
    )


def test_build_query__legacy_page__retains_its_narrow_scope() -> None:
    prior = _build(None)
    page = _build(
        "ANY",
        _plan("NEXT_PAGE"),
        prior_plans={"task-read": prior},
        prior_read_result_handles={"task-read": "legacy-read"},
    )
    assert page["query_identity_hash"] == prior["query_identity_hash"]
    assert page["effective_constraints"] == prior["effective_constraints"]
    assert execute_read_projection.project_connector_call(
        page, route=ROUTE, page_size=20
    )[1]["show_completed"] is False
    assert _build("ANY")["query_identity_hash"] != page["query_identity_hash"]


def test_build_query__changed_query__rejects_scope_removal_and_noop() -> None:
    prior = _build("ANY")
    changed = _plan()
    changed["route_queries"][0]["search_spec"] = {
        "mode": "CHANGED",
        "constraint_delta": {
            "upsert_constraints": [],
            "remove_constraint_kinds": [],
        },
    }
    with pytest.raises(QueryUnchangedAfterFailureError):
        _build("ANY", changed, prior_plans={"task-read": prior})
    changed["route_queries"][0]["search_spec"]["constraint_delta"]["remove_constraint_kinds"] = [
        "STATUS_SCOPE",
    ]
    with pytest.raises(RetrievalV2ValidationError):
        _build("ANY", changed, prior_plans={"task-read": prior})


def test_build_query__llm_status_override__rejects_unsupported_scope() -> None:
    candidate = _plan()
    candidate["route_queries"][0]["search_spec"]["constraints"] = [
        {"kind": "STATUS_SCOPE", "values": ["INCOMPLETE"]},
    ]
    with pytest.raises(RetrievalV2ValidationError):
        _build("ANY", candidate)


def test_build_query__legacy_incomplete_annotation__is_not_a_new_query() -> None:
    prior = _build(None)
    changed = _plan()
    changed["route_queries"][0]["search_spec"] = {
        "mode": "CHANGED",
        "constraint_delta": {"upsert_constraints": [], "remove_constraint_kinds": []},
    }
    with pytest.raises(QueryUnchangedAfterFailureError):
        _build("INCOMPLETE", changed, prior_plans={"task-read": prior})
    widened = _build("ANY", changed, prior_plans={"task-read": prior})
    assert widened["query_identity_hash"] != prior["query_identity_hash"]


def test_build_query__container_fanout__preserves_scope_and_distinct_hashes() -> None:
    broad = deepcopy(_build("ANY"))
    for constraint in broad["effective_constraints"]:
        if constraint["kind"] == "CONTAINER_REF":
            constraint["container_refs"] = ["list-a", "list-b"]
    plans = materialize_container_read_plans([broad])
    assert len(plans) == 2
    assert len({plan["query_identity_hash"] for plan in plans}) == 2
    assert all(
        {"kind": "STATUS_SCOPE", "values": ["ANY"]} in plan["effective_constraints"]
        for plan in plans
    )
