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
from google_work_agent.application.agents.retrieval.preserve_gmail_search_semantics import (
    preserve_gmail_search_semantics,
    requested_participant_identities,
)
from google_work_agent.application.agents.tool_routing.contracts.tool_route_plan import (
    InputToolRouteV1,
)
from google_work_agent.ports.llm.output_schema_validation import validate_output_schema

ROUTE: InputToolRouteV1 = {
    "route_id": "g", "resource_type": "GMAIL_THREAD", "connector_id": "google_workspace",
    "allowed_read_tool_ids": ["gmail_search_threads"], "required": True,
    "reason_codes": ["USER_REQUEST"],
}
POLICIES = {"g": RouteConstraintPolicy(frozenset({"KEYWORD", "PARTICIPANT"}))}


def _plan(identity: str) -> dict[str, object]:
    return {
        "schema_version": 2, "required_information": ["관련 메일"], "retrieval_order": ["g"],
        "route_queries": [{
            "route_id": "g", "operation": "SEARCH", "reason_codes": ["USER_REQUEST"],
            "detail_candidate_ref": None, "search_spec": {"mode": "INITIAL", "constraints": [{
                "kind": "PARTICIPANT", "participants": [{"role": "SENDER", "identity": identity}],
                "match_mode": "ALL",
            }]},
        }],
    }


@pytest.mark.parametrize("identity", ["김대리", "김철수 대리", "@default", "primary", 'a"@b.com'])
def test_unresolved_or_unsafe_identity_fails_schema_builder_and_old_checkpoint_lowering(
    identity: str,
) -> None:
    plan = _plan(identity)
    assert validate_output_schema(plan, RETRIEVAL_QUERY_PLAN_V2_OUTPUT_SCHEMA.json_schema)
    with pytest.raises(RetrievalV2ValidationError):
        build_query(plan, frozen_routes=[ROUTE], route_policies=POLICIES)
    legacy = cast(SourceFetchPlanV1, {
        "resource_type": "GMAIL_THREAD", "operation_kind": "SEARCH", "effective_constraints": [{
            "kind": "PARTICIPANT", "participants": [{"role": "SENDER", "identity": identity}],
            "match_mode": "ALL",
        }],
    })
    with pytest.raises(RetrievalV2ValidationError):
        execute_read_projection.project_connector_call(legacy, route=ROUTE, page_size=20)


def test_abbreviated_person_is_discovered_without_inventing_an_email() -> None:
    prompt_input = {"request_intent": {"constraints": [
        {"kind": "PERSON", "field": "person", "value": "김대리"},
        {"kind": "USER_REQUIREMENT", "field": "search_terms", "value": ["박람회"]},
    ]}}
    repaired = preserve_gmail_search_semantics(
        _plan("invented@example.com"), prompt_input=prompt_input, frozen_routes=[ROUTE],
        now_ms=None, timezone=None,
    )
    fetch = build_query(repaired, frozen_routes=[ROUTE], route_policies=POLICIES)[0]
    _, arguments = execute_read_projection.project_connector_call(fetch, route=ROUTE, page_size=20)
    assert arguments["query"] == "대리 박람회"
    assert not any(item["kind"] == "PARTICIPANT" for item in fetch["effective_constraints"])
    assert requested_participant_identities(prompt_input) == []


def test_model_participant_is_bound_to_current_request_email_not_an_invented_email() -> None:
    prompt_input = {"request_intent": {"constraints": [
        {"kind": "EMAIL", "field": "sender", "value": "kim@example.com"},
    ]}}
    schema = bind_retrieval_query_plan_output_schema(
        route_ids=["g"],
        allowed_participant_identities=requested_participant_identities(prompt_input),
    )
    assert validate_output_schema(_plan("kim@example.com"), schema.json_schema) == []
    assert validate_output_schema(_plan("invented@example.com"), schema.json_schema)
    unresolved_schema = bind_retrieval_query_plan_output_schema(
        route_ids=["g"], allowed_participant_identities=[],
    )
    assert validate_output_schema(_plan("invented@example.com"), unresolved_schema.json_schema)


def test_any_participant_search_is_not_a_body_email_keyword() -> None:
    plan = _plan("kim@example.com")
    fetch = build_query(plan, frozen_routes=[ROUTE], route_policies=POLICIES)[0]
    constraint = fetch["effective_constraints"][0]
    assert constraint["kind"] == "PARTICIPANT"
    constraint["participants"][0]["role"] = "ANY"
    _, arguments = execute_read_projection.project_connector_call(fetch, route=ROUTE, page_size=20)
    assert arguments["query"] == "{from:kim@example.com to:kim@example.com}"
