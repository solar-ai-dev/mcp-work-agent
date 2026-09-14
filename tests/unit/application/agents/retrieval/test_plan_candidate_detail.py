from typing import cast

from google_work_agent.application.agents.retrieval.plan_candidate_detail import (
    plan_candidate_detail,
)
from google_work_agent.application.agents.tool_routing.contracts.tool_route_plan import (
    InputToolRouteV1,
)


def test_plan_candidate_detail__attempted_and_other_resource_candidates__selects_unread_only(
) -> None:
    route = cast(InputToolRouteV1, {
        "route_id": "mail", "connector_id": "google_workspace", "resource_type": "GMAIL_THREAD",
        "allowed_read_tool_ids": ["gmail_search_threads", "gmail_get_thread"],
    })
    prompt_input: dict[str, object] = {
        "current_round_no": 2, "unresolved_sufficiency_issues": [
            {"required": True, "resolution_source": "GOOGLE", "route_id": "mail"},
        ],
    }
    candidates = ["task:other", "gmail_thread:seen", "gmail_thread:new"]
    result = plan_candidate_detail(
        prompt_input=prompt_input, frozen_routes=[route], detail_candidate_refs=candidates,
        attempted_detail_candidate_refs=["gmail_thread:seen"],
    )
    assert result is not None
    assert result["route_queries"] == [{
        "route_id": "mail", "operation": "DETAIL_FETCH",
        "reason_codes": ["CANDIDATE_DETAIL_REQUIRED"],
        "search_spec": None, "detail_candidate_ref": "gmail_thread:new",
    }]
    assert plan_candidate_detail(
        prompt_input=prompt_input, frozen_routes=[route], detail_candidate_refs=candidates,
        attempted_detail_candidate_refs=["gmail_thread:seen", "gmail_thread:new"],
    ) is None
