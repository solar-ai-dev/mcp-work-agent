"""Tests for request-owned Gmail concept validation."""

import pytest

from google_work_agent.application.agents.retrieval.contracts.query_plan import (
    RetrievalV2ValidationError,
)
from google_work_agent.application.agents.retrieval.validate_requested_gmail_concepts import (
    validate_requested_gmail_concepts,
)
from google_work_agent.application.agents.tool_routing.contracts.tool_route_plan import (
    InputToolRouteV1,
)


def test_validate_requested_gmail_concepts__requested_concept_missing__raises_error() -> None:
    route: InputToolRouteV1 = {
        "route_id": "gmail",
        "resource_type": "GMAIL_THREAD",
        "connector_id": "google_workspace",
        "allowed_read_tool_ids": ["gmail_search_threads"],
        "required": True,
        "reason_codes": ["USER_REQUEST"],
    }
    prompt_input = {
        "request_intent": {
            "constraints": [
                {
                    "kind": "USER_REQUIREMENT",
                    "field": "business_concepts",
                    "value": ["출시"],
                }
            ]
        }
    }
    plan = {
        "route_queries": [
            {
                "route_id": "gmail",
                "operation": "SEARCH",
                "search_spec": {"mode": "INITIAL", "constraints": []},
            }
        ]
    }

    with pytest.raises(RetrievalV2ValidationError):
        validate_requested_gmail_concepts(plan, prompt_input, [route])
