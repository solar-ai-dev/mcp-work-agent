from typing import Any, cast

import pytest

from google_work_agent.adapters.langgraph.subgraphs.retrieval.projections import (
    execute_read_projection,
)
from google_work_agent.adapters.system.memory.run_retrieval_cache import (
    InMemoryRunRetrievalCache,
)
from google_work_agent.application.agents.retrieval.build_query import (
    RouteConstraintPolicy,
    build_query,
)
from google_work_agent.application.agents.retrieval.contracts.query_plan import (
    RetrievalQueryPlanV2,
    RetrievalV2ValidationError,
    SourceFetchPlanV1,
)
from google_work_agent.application.agents.retrieval.execute_read import execute_read
from google_work_agent.application.agents.tool_routing.contracts.tool_route_plan import (
    InputToolRouteV1,
)
from google_work_agent.application.use_cases.run.guard_run_budget import build_default_run_budget
from google_work_agent.ports.connector.connector_read_port import ConnectorReadResultV1
from google_work_agent.ports.connector.contracts.validated_connector_tool_binding import (
    ValidatedConnectorToolBindingV1,
)


class _RecordingReadPort:
    def __init__(self) -> None:
        self.calls: list[tuple[ValidatedConnectorToolBindingV1, dict[str, Any]]] = []

    def execute_read(
        self,
        binding: ValidatedConnectorToolBindingV1,
        arguments: dict[str, Any],
    ) -> ConnectorReadResultV1:
        self.calls.append((binding, arguments))
        return ConnectorReadResultV1(
            schema_version=1,
            tool_id=binding.tool_id,
            request_id="request-1",
            output={"items": []},
            next_page_token=None,
            total_count=0,
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

    tool_id, arguments = execute_read_projection.project_connector_call(
        plan, route=route, page_size=50
    )

    assert tool_id == "github_list_issues"
    assert arguments == {"repository": "acme/repo", "state": "OPEN"}


@pytest.mark.parametrize("has_payload", [False, True])
def test_github_issue_detail__uses_normalized__composite_identity(has_payload: bool) -> None:
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
    resource: dict[str, Any] = {
        "resource_id": "acme/repo#7",
        "parent_id": "acme/repo",
        "connector_id": "github",
    }
    if has_payload:
        resource["payload"] = {"repository": "acme/repo", "issue_number": 7}

    tool_id, arguments = execute_read_projection.project_connector_call(
        plan,
        route=route,
        page_size=1,
        detail_resource=resource,
    )

    assert tool_id == "github_get_issue"
    assert arguments == {"repository": "acme/repo", "issue_number": 7}

    for change in (
        {"connector_id": "google"},
        {"parent_id": "other/repo"},
        {"resource_id": "acme/repo#07"},
        {"payload": {"repository": "other/repo", "issue_number": 7}},
        {"payload": {"repository": "acme/repo", "issue_number": 8}},
    ):
        with pytest.raises(ValueError, match="identity"):
            execute_read_projection.project_connector_call(
                plan, route=route, page_size=1, detail_resource={**resource, **change}
            )


def test_github_issue_search__materializes_validated_repository__without_route_change() -> None:
    route = _github_search_route()

    plans = build_query(
        _github_search_plan([]),
        frozen_routes=[route],
        route_policies={"route-1": _github_policy()},
        validated_container_refs={"route-1": ["acme/repo"]},
    )

    assert len(plans) == 1
    assert plans[0]["connector_id"] == route["connector_id"]
    assert plans[0]["resource_type"] == route["resource_type"]
    assert plans[0]["route_id"] == route["route_id"]
    assert plans[0]["effective_constraints"] == [
        {"kind": "CONTAINER_REF", "container_refs": ["acme/repo"]}
    ]
    tool_id, arguments = execute_read_projection.project_connector_call(
        plans[0], route=route, page_size=50
    )
    assert tool_id == "github_list_issues"
    assert arguments == {"repository": "acme/repo", "state": "ALL"}
    reader = _RecordingReadPort()
    binding = ValidatedConnectorToolBindingV1(
        schema_version=1,
        connector_id="github",
        resource_type="github_issue",
        tool_id=tool_id,
        effect="READ",
        input_schema_ref="schema://github-list-issues-input",
        output_schema_ref="schema://github-list-issues-output",
        registry_entry_hash="a" * 64,
    )

    execution = execute_read(
        run_budget=build_default_run_budget(),
        now_ms=1_000,
        prior_query_attempts=[],
        plan=plans[0],
        run_id="run-1",
        binding=binding,
        tool_arguments=arguments,
        connector_reader=reader,
        read_result_cache=InMemoryRunRetrievalCache(),
        read_result_handle="read-1",
    )

    assert execution.provider_called is True
    assert reader.calls == [(binding, {"repository": "acme/repo", "state": "ALL"})]


def test_github_issue_search__missing_or_forged_repository__fails_before_read() -> None:
    route = _github_search_route()
    reader = _RecordingReadPort()
    with pytest.raises(RetrievalV2ValidationError, match="validated container authority"):
        plans = build_query(
            _github_search_plan([]),
            frozen_routes=[route],
            route_policies={"route-1": _github_policy()},
        )
        _execute_first(plans, route=route, reader=reader)
    with pytest.raises(RetrievalV2ValidationError, match="validated for route"):
        plans = build_query(
            _github_search_plan([{"kind": "CONTAINER_REF", "container_refs": ["evil/repo"]}]),
            frozen_routes=[route],
            route_policies={"route-1": _github_policy()},
            validated_container_refs={"route-1": ["acme/repo"]},
        )
        _execute_first(plans, route=route, reader=reader)

    assert reader.calls == []


def _github_search_route() -> InputToolRouteV1:
    return {
        "route_id": "route-1",
        "resource_type": "GITHUB_ISSUE",
        "connector_id": "github",
        "allowed_read_tool_ids": ["github_list_issues"],
        "required": True,
        "reason_codes": ["REQUESTED_INPUT"],
    }


def _github_policy() -> RouteConstraintPolicy:
    return RouteConstraintPolicy(
        supported_kinds=frozenset({"CONTAINER_REF", "STATUS_SCOPE"}),
        required_kinds=frozenset({"CONTAINER_REF"}),
    )


def _github_search_plan(constraints: list[dict[str, object]]) -> RetrievalQueryPlanV2:
    return cast(
        RetrievalQueryPlanV2,
        {
            "schema_version": 2,
            "route_queries": [
                {
                    "route_id": "route-1",
                    "operation": "SEARCH",
                    "reason_codes": ["USER_REQUEST"],
                    "search_spec": {"mode": "INITIAL", "constraints": constraints},
                    "detail_candidate_ref": None,
                }
            ],
        },
    )


def _execute_first(
    plans: list[SourceFetchPlanV1],
    *,
    route: InputToolRouteV1,
    reader: _RecordingReadPort,
) -> None:
    tool_id, arguments = execute_read_projection.project_connector_call(
        plans[0], route=route, page_size=50
    )
    execute_read(
        run_budget=build_default_run_budget(),
        now_ms=1_000,
        prior_query_attempts=[],
        plan=plans[0],
        run_id="run-1",
        binding=ValidatedConnectorToolBindingV1(
            schema_version=1,
            connector_id="github",
            resource_type="github_issue",
            tool_id=tool_id,
            effect="READ",
            input_schema_ref="input",
            output_schema_ref="output",
            registry_entry_hash="a" * 64,
        ),
        tool_arguments=arguments,
        connector_reader=reader,
        read_result_cache=InMemoryRunRetrievalCache(),
        read_result_handle="read-1",
    )
