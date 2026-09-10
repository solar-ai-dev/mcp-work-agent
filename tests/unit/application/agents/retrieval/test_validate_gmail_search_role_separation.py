"""Tests for Gmail status and lexical-role validation."""

import pytest

from google_work_agent.application.agents.retrieval.contracts.query_plan import (
    RetrievalV2ValidationError,
)
from google_work_agent.application.agents.retrieval.validate_gmail_search_role_separation import (
    validate_gmail_search_role_separation,
)
from google_work_agent.application.agents.tool_routing.contracts.tool_route_plan import (
    InputToolRouteV1,
)


def test_validate_gmail_search_role_separation__invented_status_keyword__raises_error() -> None:
    route: InputToolRouteV1 = {
        "route_id": "gmail",
        "resource_type": "GMAIL_DRAFT",
        "connector_id": "google_workspace",
        "allowed_read_tool_ids": ["gmail_search_drafts"],
        "required": True,
        "reason_codes": ["USER_REQUEST"],
    }
    prompt_input = {
        "request_intent": {
            "constraints": [
                {"kind": "SCOPE", "field": "status", "value": ["DRAFT"]},
                {"kind": "USER_REQUIREMENT", "field": "search_terms", "value": ["Quartz"]},
            ]
        }
    }
    plan = {
        "route_queries": [
            {
                "route_id": "gmail",
                "operation": "SEARCH",
                "search_spec": {
                    "mode": "INITIAL",
                    "constraints": [
                        {"kind": "STATUS_SCOPE", "values": ["DRAFT"]},
                        {"kind": "KEYWORD", "terms": ["Quartz", "임시보관함"]},
                    ],
                },
            }
        ]
    }

    with pytest.raises(RetrievalV2ValidationError):
        validate_gmail_search_role_separation(plan, prompt_input, [route])
