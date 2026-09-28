"""DETAIL_FETCH schema must expose the same exact-ref authority as its consumer."""

from typing import Any, cast

import pytest

from google_work_agent.application.agents.retrieval.contracts.query_plan import (
    RetrievalV2ValidationError,
    validate_retrieval_query_plan_v2,
)
from google_work_agent.application.agents.retrieval.contracts.query_plan_schema import (
    bind_retrieval_query_plan_output_schema,
    normalize_retrieval_query_plan_candidate,
)
from google_work_agent.application.agents.tool_routing.contracts.tool_route_plan import (
    InputToolRouteV1,
)
from google_work_agent.ports.llm.output_schema_validation import validate_output_schema


def _candidate(route_id: str, ref: str) -> dict[str, Any]:
    return {
        "schema_version": 3,
        "route_queries": [
            {
                "route_id": route_id,
                "operation": "DETAIL_FETCH",
                "reason_codes": ["REQUESTED_INPUT"],
                "search_spec": None,
                "detail_candidate_ref": ref,
            }
        ],
    }


def _route(route_id: str, resource_type: str) -> InputToolRouteV1:
    return cast(
        InputToolRouteV1,
        {
            "route_id": route_id,
            "resource_type": resource_type,
            "connector_id": "google_workspace",
            "required": True,
            "reason_codes": ["USER_REQUEST"],
            "work_unit_ids": [route_id + "-work"],
            "allowed_read_tool_ids": [
                {
                    "TASK": "tasks_get_task",
                    "GMAIL_THREAD": "gmail_get_thread",
                }[resource_type]
            ],
        },
    )


@pytest.mark.parametrize(
    "ref,valid",
    [
        ("task:chosen", True),
        ("chosen", False),
        ("task:user-supplied-unbound", False),
        ("gmail_thread:chosen", False),
    ],
)
def test_selected_only_task_detail_schema_closes_exact_ref(ref: str, valid: bool) -> None:
    schema = bind_retrieval_query_plan_output_schema(
        route_ids=["task-read"],
        route_operations={"task-read": ["DETAIL_FETCH"]},
        supported_constraint_kinds={"task-read": []},
        validated_resource_refs={"task-read": ["task:chosen"]},
    )

    assert (not validate_output_schema(_candidate("task-read", ref), schema.json_schema)) is valid


@pytest.mark.parametrize(
    "ref,valid",
    [
        ("gmail_thread:acquired", True),
        ("gmail_thread:unacquired", False),
        ("acquired", False),
    ],
)
def test_followup_candidate_only_gmail_detail_contract_is_unchanged(ref: str, valid: bool) -> None:
    schema = bind_retrieval_query_plan_output_schema(
        route_ids=["mail-read"],
        route_operations={"mail-read": ["DETAIL_FETCH"]},
        supported_constraint_kinds={"mail-read": []},
        is_followup=True,
        detail_candidate_refs_by_route={"mail-read": ["gmail_thread:acquired"]},
    )

    assert (not validate_output_schema(_candidate("mail-read", ref), schema.json_schema)) is valid


@pytest.mark.parametrize(
    "ref,valid",
    [
        ("task:chosen", True),
        ("task:acquired", True),
        ("task:user-supplied-unbound", False),
    ],
)
def test_same_route_exact_and_acquired_refs_match_existing_validator_union(
    ref: str,
    valid: bool,
) -> None:
    selected = {"task-read": ["task:chosen"]}
    acquired = ["task:acquired"]
    schema = bind_retrieval_query_plan_output_schema(
        route_ids=["task-read"],
        route_operations={"task-read": ["DETAIL_FETCH"]},
        supported_constraint_kinds={"task-read": []},
        validated_resource_refs=selected,
        detail_candidate_refs_by_route={"task-read": acquired},
        is_followup=True,
    )
    candidate = _candidate("task-read", ref)
    normalized = normalize_retrieval_query_plan_candidate(candidate)
    consumer_kwargs = {
        "frozen_routes": [_route("task-read", "TASK")],
        "supported_constraint_kinds": {"task-read": []},
        "validated_resource_refs": selected,
        "detail_candidate_refs": acquired,
    }

    # The existing consumer already accepts the union; only its generation
    # schema must be aligned. No natural-language identity inference is added.
    if valid:
        result = validate_retrieval_query_plan_v2(normalized, **cast(Any, consumer_kwargs))
        assert result["route_queries"][0]["detail_candidate_ref"] == ref
    else:
        with pytest.raises(RetrievalV2ValidationError) as raised:
            validate_retrieval_query_plan_v2(normalized, **cast(Any, consumer_kwargs))
        assert raised.value.reason_code == "RETRIEVAL_ROUTE_SCOPE_VIOLATION"
    assert (not validate_output_schema(candidate, schema.json_schema)) is valid
    assert candidate["schema_version"] == 3


def test_two_task_routes_cannot_exchange_their_selected_exact_identity() -> None:
    selected = {"first": ["task:first"], "second": ["task:second"]}
    schema = bind_retrieval_query_plan_output_schema(
        route_ids=["first", "second"],
        route_operations={"first": ["DETAIL_FETCH"], "second": ["DETAIL_FETCH"]},
        supported_constraint_kinds={"first": [], "second": []},
        validated_resource_refs=selected,
    )
    for route_id, other_route in (("first", "second"), ("second", "first")):
        assert (
            validate_output_schema(
                _candidate(route_id, selected[route_id][0]),
                schema.json_schema,
            )
            == []
        )
        foreign = _candidate(route_id, selected[other_route][0])
        with pytest.raises(RetrievalV2ValidationError):
            validate_retrieval_query_plan_v2(
                normalize_retrieval_query_plan_candidate(foreign),
                frozen_routes=[_route("first", "TASK"), _route("second", "TASK")],
                supported_constraint_kinds={"first": [], "second": []},
                validated_resource_refs=selected,
            )
        assert validate_output_schema(foreign, schema.json_schema)


def test_other_resource_route_ref_is_not_in_this_routes_detail_schema() -> None:
    schema = bind_retrieval_query_plan_output_schema(
        route_ids=["task-read", "mail-read"],
        route_operations={"task-read": ["DETAIL_FETCH"], "mail-read": ["DETAIL_FETCH"]},
        supported_constraint_kinds={"task-read": [], "mail-read": []},
        validated_resource_refs={"task-read": ["task:chosen"]},
        detail_candidate_refs_by_route={"mail-read": ["gmail_thread:acquired"]},
    )

    assert validate_output_schema(_candidate("task-read", "task:chosen"), schema.json_schema) == []
    assert (
        validate_output_schema(
            _candidate("mail-read", "gmail_thread:acquired"),
            schema.json_schema,
        )
        == []
    )
    assert validate_output_schema(
        _candidate("task-read", "gmail_thread:acquired"), schema.json_schema
    )
    assert validate_output_schema(_candidate("mail-read", "task:chosen"), schema.json_schema)
