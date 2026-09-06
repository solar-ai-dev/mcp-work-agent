from typing import cast

import pytest

from google_work_agent.application.agents.retrieval.plan_query_expansion import plan_query_expansion
from google_work_agent.application.agents.tool_routing.contracts.tool_route_plan import (
    InputToolRouteV1,
)


@pytest.mark.parametrize("exhausted", [False, True])
def test_plan_query_expansion__page_summary__continues_only_unexhausted_route(
    exhausted: bool,
) -> None:
    result = plan_query_expansion(
        prompt_input={
            "current_round_no": 2, "unresolved_sufficiency_issues": [
                {"required": True, "resolution_source": "CONNECTOR", "route_id": "issues"},
            ], "read_result_summaries": [
                {"route_id": "issues", "has_next_page": True, "exhausted": exhausted},
                {"route_id": "issues", "has_next_page": False, "exhausted": False},
            ],
        }, frozen_routes=[cast(InputToolRouteV1, {
            "route_id": "issues", "connector_id": "github", "resource_type": "GITHUB_ISSUE",
            "allowed_read_tool_ids": ["github_list_issues"],
        })],
    )
    if exhausted:
        assert result is None
    else:
        assert result is not None
        assert result["retrieval_order"] == ["issues"]
        assert result["route_queries"][0]["operation"] == "NEXT_PAGE"


def test_plan_query_expansion__no_round_context__does_not_invent_continuation() -> None:
    assert plan_query_expansion(prompt_input={}, frozen_routes=[]) is None
