"""Unresolved people are discovery targets, not hard provider identities."""

from typing import cast

import pytest

from google_work_agent.adapters.langgraph.subgraphs.retrieval.projections import (
    execute_read_projection,
)
from google_work_agent.application.agents.retrieval.build_query import (
    RouteConstraintPolicy,
    build_query,
)
from google_work_agent.application.agents.retrieval.contracts.query_plan import (
    RetrievalV2ValidationError,
    SourceFetchPlanV1,
)
from google_work_agent.application.agents.retrieval.contracts.query_plan_schema import (
    RETRIEVAL_QUERY_PLAN_V2_OUTPUT_SCHEMA,
    bind_retrieval_query_plan_output_schema,
)
from google_work_agent.application.agents.retrieval.resolve_request_participants import (
    resolve_request_participants,
)
from google_work_agent.application.agents.tool_routing.contracts.tool_route_plan import (
    InputToolRouteV1,
)
from google_work_agent.ports.llm.output_schema_validation import validate_output_schema

ROUTE: InputToolRouteV1 = {
    "route_id": "g",
    "resource_type": "GMAIL_THREAD",
    "connector_id": "google_workspace",
    "allowed_read_tool_ids": ["gmail_search_threads"],
    "required": True,
    "reason_codes": ["USER_REQUEST"],
}
POLICIES = {"g": RouteConstraintPolicy(frozenset({"KEYWORD", "PARTICIPANT"}))}


def _plan(identity: str) -> dict[str, object]:
    return {
        "schema_version": 2,
        "route_queries": [
            {
                "route_id": "g",
                "operation": "SEARCH",
                "reason_codes": ["USER_REQUEST"],
                "detail_candidate_ref": None,
                "search_spec": {
                    "mode": "INITIAL",
                    "constraints": [
                        {
                            "kind": "PARTICIPANT",
                            "participants": [{"role": "SENDER", "identity": identity}],
                            "match_mode": "ALL",
                        }
                    ],
                },
            }
        ],
    }


def _provider_candidate(identity: str) -> dict[str, object]:
    return {
        "schema_version": 3,
        "route_queries": [
            {
                "route_id": "g",
                "operation": "SEARCH",
                "reason_codes": ["USER_REQUEST"],
                "detail_candidate_ref": None,
                "search_spec": {
                    "mode": "INITIAL",
                    "constraints": {
                        "participant": {
                            "kind": "PARTICIPANT",
                            "participants": [{"role": "SENDER", "identity": identity}],
                            "match_mode": "ALL",
                        }
                    },
                },
            }
        ],
    }


@pytest.mark.parametrize("identity", ["김대리", "김철수 대리", "@default", "primary", 'a"@b.com'])
def test_participant_validation__unresolved_or_unsafe__rejects_schema_builder_and_checkpoint(
    identity: str,
) -> None:
    plan = _plan(identity)
    assert validate_output_schema(plan, RETRIEVAL_QUERY_PLAN_V2_OUTPUT_SCHEMA.json_schema)
    with pytest.raises(RetrievalV2ValidationError):
        build_query(plan, frozen_routes=[ROUTE], route_policies=POLICIES)
    legacy = cast(
        SourceFetchPlanV1,
        {
            "resource_type": "GMAIL_THREAD",
            "operation_kind": "SEARCH",
            "effective_constraints": [
                {
                    "kind": "PARTICIPANT",
                    "participants": [{"role": "SENDER", "identity": identity}],
                    "match_mode": "ALL",
                }
            ],
        },
    )
    with pytest.raises(RetrievalV2ValidationError):
        execute_read_projection.project_connector_call(legacy, route=ROUTE, page_size=20)


@pytest.mark.parametrize(
    ("mention", "terms", "discovery_query"),
    [
        ("김대리", ["대리", "박람회"], '"대리" "박람회"'),
        ("이과장", ["과장", "박람회"], '"과장" "박람회"'),
        ("박 팀장", ["박람회", "팀장"], '"박람회" "팀장"'),
        ("정수진 부장", ["박람회", "정수진"], '"박람회" "정수진"'),
        ("Alex Morgan", ["Alex Morgan", "박람회"], '"Alex Morgan" "박람회"'),
    ],
)
def test_person_discovery__planner_keyword__does_not_invent_email(
    mention: str,
    terms: list[str],
    discovery_query: str,
) -> None:
    prompt_input = {
        "request_intent": {
            "constraints": [
                {"kind": "PERSON", "field": "person", "value": mention},
                {"kind": "USER_REQUIREMENT", "field": "search_terms", "value": ["박람회"]},
            ]
        }
    }
    planner_output = {
        "schema_version": 2,
        "route_queries": [
            {
                "route_id": "g",
                "operation": "SEARCH",
                "reason_codes": ["USER_REQUEST"],
                "detail_candidate_ref": None,
                "search_spec": {
                    "mode": "INITIAL",
                    "constraints": [
                        {"kind": "KEYWORD", "terms": terms, "match_mode": "ALL"}
                    ],
                },
            }
        ],
    }
    fetch = build_query(planner_output, frozen_routes=[ROUTE], route_policies=POLICIES)[0]
    _, arguments = execute_read_projection.project_connector_call(fetch, route=ROUTE, page_size=20)
    assert arguments["query"] == discovery_query
    assert not any(item["kind"] == "PARTICIPANT" for item in fetch["effective_constraints"])
    assert resolve_request_participants(prompt_input) == []


def test_model_participant__current_request_email__rejects_invented_email() -> None:
    prompt_input = {
        "request_intent": {
            "constraints": [
                {"kind": "EMAIL", "field": "sender", "value": "kim@example.com"},
            ]
        }
    }
    schema = bind_retrieval_query_plan_output_schema(
        route_ids=["g"],
        route_operations={"g": ["SEARCH"]},
        allowed_participant_identities=resolve_request_participants(prompt_input),
    )
    assert validate_output_schema(_provider_candidate("kim@example.com"), schema.json_schema) == []
    assert validate_output_schema(_provider_candidate("invented@example.com"), schema.json_schema)
    unresolved_schema = bind_retrieval_query_plan_output_schema(
        route_ids=["g"],
        route_operations={"g": ["SEARCH"]},
        allowed_participant_identities=[],
    )
    assert validate_output_schema(
        _provider_candidate("invented@example.com"), unresolved_schema.json_schema
    )


def test_participant_search__any_role__does_not_use_body_keyword() -> None:
    plan = _plan("kim@example.com")
    fetch = build_query(plan, frozen_routes=[ROUTE], route_policies=POLICIES)[0]
    constraint = fetch["effective_constraints"][0]
    assert constraint["kind"] == "PARTICIPANT"
    constraint["participants"][0]["role"] = "ANY"
    _, arguments = execute_read_projection.project_connector_call(fetch, route=ROUTE, page_size=20)
    assert arguments["query"] == "{from:kim@example.com to:kim@example.com}"
