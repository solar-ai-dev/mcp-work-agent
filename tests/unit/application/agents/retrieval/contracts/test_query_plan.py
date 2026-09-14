from typing import cast

import pytest

from google_work_agent.application.agents.retrieval.contracts.query_plan import (
    RetrievalV2ValidationError,
    validate_retrieval_query_plan_v2,
)
from google_work_agent.application.agents.tool_routing.contracts.tool_route_plan import (
    InputToolRouteV1,
)


@pytest.mark.parametrize(
    ("resource_type", "operation"),
    [
        ("CALENDAR_FREEBUSY", "SEARCH"),
        ("CALENDAR_EVENT", "FREEBUSY"),
    ],
)
def test_route_operation__when_resource_type_mismatches__rejects_before_adapter(
    resource_type: str,
    operation: str,
) -> None:
    route = cast(
        InputToolRouteV1,
        {
            "route_id": "calendar-route",
            "resource_type": resource_type,
            "connector_id": "google_workspace",
            "allowed_read_tool_ids": ["calendar_query_freebusy", "calendar_list_events"],
            "required": True,
            "reason_codes": ["POLICY_CALENDAR_CONFLICT_CHECK"],
        },
    )

    with pytest.raises(RetrievalV2ValidationError, match="frozen route tools"):
        validate_retrieval_query_plan_v2(
            {
                "schema_version": 2,
                "route_queries": [
                    {
                        "route_id": "calendar-route",
                        "operation": operation,
                        "reason_codes": ["POLICY_CALENDAR_CONFLICT_CHECK"],
                        "search_spec": {"mode": "INITIAL", "constraints": []},
                        "detail_candidate_ref": None,
                    }
                ],
            },
            frozen_routes=[route],
            supported_constraint_kinds={"calendar-route": []},
        )


def test_get_only_message_route__with_search__rejects_before_adapter() -> None:
    route = cast(
        InputToolRouteV1,
        {
            "route_id": "message-detail",
            "resource_type": "GMAIL_MESSAGE",
            "connector_id": "google_workspace",
            "allowed_read_tool_ids": ["gmail_get_message"],
            "required": True,
            "reason_codes": ["USER_REQUEST"],
        },
    )

    with pytest.raises(RetrievalV2ValidationError, match="frozen route tools"):
        validate_retrieval_query_plan_v2(
            {
                "schema_version": 2,
                "route_queries": [
                    {
                        "route_id": "message-detail",
                        "operation": "SEARCH",
                        "reason_codes": ["USER_REQUEST"],
                        "search_spec": {
                            "mode": "INITIAL",
                            "constraints": [
                                {"kind": "KEYWORD", "terms": ["Quartz"], "match_mode": "ANY"}
                            ],
                        },
                        "detail_candidate_ref": None,
                    }
                ],
            },
            frozen_routes=[route],
            supported_constraint_kinds={"message-detail": ["KEYWORD"]},
        )


def test_non_gmail_search__empty_constraints__remains_rejected() -> None:
    route = cast(
        InputToolRouteV1,
        {
            "route_id": "task-route",
            "resource_type": "TASK",
            "connector_id": "google_workspace",
            "allowed_read_tool_ids": ["tasks_list_tasks"],
            "required": True,
            "reason_codes": ["USER_REQUEST"],
        },
    )

    with pytest.raises(RetrievalV2ValidationError, match="constraints must be non-empty"):
        validate_retrieval_query_plan_v2(
            {
                "schema_version": 2,
                "route_queries": [
                    {
                        "route_id": "task-route",
                        "operation": "SEARCH",
                        "reason_codes": ["USER_REQUEST"],
                        "search_spec": {"mode": "INITIAL", "constraints": []},
                        "detail_candidate_ref": None,
                    }
                ],
            },
            frozen_routes=[route],
            supported_constraint_kinds={"task-route": ["STATUS_SCOPE"]},
        )


def test_query_plan__with_duplicate_constraint_kind__reports_rejected_field_path() -> None:
    route = cast(
        InputToolRouteV1,
        {
            "route_id": "gmail-search",
            "resource_type": "GMAIL_THREAD",
            "connector_id": "google_workspace",
            "allowed_read_tool_ids": ["gmail_search_threads"],
            "required": True,
            "reason_codes": ["USER_REQUEST"],
        },
    )

    with pytest.raises(
        RetrievalV2ValidationError, match="effective constraints cannot duplicate a kind"
    ) as caught:
        validate_retrieval_query_plan_v2(
            {
                "schema_version": 2,
                "route_queries": [
                    {
                        "route_id": "gmail-search",
                        "operation": "SEARCH",
                        "reason_codes": ["USER_REQUEST"],
                        "search_spec": {
                            "mode": "INITIAL",
                            "constraints": [
                                {
                                    "kind": "CONCEPT",
                                    "concept": "Maple",
                                    "manifestations": ["Maple"],
                                },
                                {
                                    "kind": "CONCEPT",
                                    "concept": "maintenance",
                                    "manifestations": ["maintenance"],
                                },
                            ],
                        },
                        "detail_candidate_ref": None,
                    }
                ],
            },
            frozen_routes=[route],
            supported_constraint_kinds={"gmail-search": ["CONCEPT"]},
        )

    assert caught.value.affected_field_paths == ("$.route_queries[].search_spec.constraints",)


def test_detail_candidate__from_other_route__is_rejected() -> None:
    routes = [
        cast(
            InputToolRouteV1,
            {
                "route_id": "gmail",
                "resource_type": "GMAIL_THREAD",
                "connector_id": "google_workspace",
                "allowed_read_tool_ids": ["gmail_get_thread"],
                "required": True,
                "reason_codes": ["USER_REQUEST"],
            },
        ),
        cast(
            InputToolRouteV1,
            {
                "route_id": "github",
                "resource_type": "GITHUB_ISSUE",
                "connector_id": "github",
                "allowed_read_tool_ids": ["github_get_issue"],
                "required": True,
                "reason_codes": ["USER_REQUEST"],
            },
        ),
    ]
    candidate = {
        "schema_version": 2,
        "route_queries": [
            {
                "route_id": "gmail",
                "operation": "DETAIL_FETCH",
                "reason_codes": ["MISSING_BODY"],
                "search_spec": None,
                "detail_candidate_ref": "github_issue:acme/repo#7",
            }
        ],
    }

    with pytest.raises(RetrievalV2ValidationError) as raised:
        validate_retrieval_query_plan_v2(
            candidate,
            frozen_routes=routes,
            supported_constraint_kinds={"gmail": [], "github": []},
            detail_candidate_refs=["github_issue:acme/repo#7"],
        )

    assert raised.value.reason_code == "RETRIEVAL_ROUTE_SCOPE_VIOLATION"


def test_gmail_keyword__unsupported_literal__is_typed_before_adapter() -> None:
    route = cast(
        InputToolRouteV1,
        {
            "route_id": "gmail",
            "resource_type": "GMAIL_THREAD",
            "connector_id": "google_workspace",
            "allowed_read_tool_ids": ["gmail_search_threads"],
            "required": True,
            "reason_codes": ["USER_REQUEST"],
        },
    )
    candidate = {
        "schema_version": 2,
        "route_queries": [
            {
                "route_id": "gmail",
                "operation": "SEARCH",
                "reason_codes": ["USER_REQUEST"],
                "search_spec": {
                    "mode": "INITIAL",
                    "constraints": [
                        {
                            "kind": "KEYWORD",
                            "terms": ['Quartz" OR from:other@example.test'],
                            "match_mode": "PHRASE",
                        }
                    ],
                },
                "detail_candidate_ref": None,
            }
        ],
    }

    with pytest.raises(RetrievalV2ValidationError) as raised:
        validate_retrieval_query_plan_v2(
            candidate,
            frozen_routes=[route],
            supported_constraint_kinds={"gmail": ["KEYWORD"]},
        )

    assert raised.value.reason_code == "QUERY_LITERAL_UNSUPPORTED"
