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
                "required_information": ["calendar conflicts"],
                "retrieval_order": ["calendar-route"],
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
                "required_information": ["matching message"],
                "retrieval_order": ["message-detail"],
            },
            frozen_routes=[route],
            supported_constraint_kinds={"message-detail": ["KEYWORD"]},
        )
