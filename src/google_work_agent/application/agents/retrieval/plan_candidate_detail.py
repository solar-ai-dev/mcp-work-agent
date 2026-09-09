"""Deterministically plan candidate detail reads after metadata search."""

from __future__ import annotations

from collections.abc import Collection, Mapping, Sequence
from typing import cast

from google_work_agent.application.agents.retrieval.contracts.query_plan import (
    RetrievalQueryPlanV2,
    route_operation_tool_id,
)
from google_work_agent.application.agents.retrieval.select_followup_routes import (
    select_followup_routes,
)
from google_work_agent.application.agents.tool_routing.contracts.tool_route_plan import (
    InputToolRouteV1,
)


def plan_candidate_detail(
    *,
    prompt_input: Mapping[str, object],
    frozen_routes: Sequence[InputToolRouteV1],
    detail_candidate_refs: Collection[str],
    attempted_detail_candidate_refs: Collection[str] = (),
) -> RetrievalQueryPlanV2 | None:
    """Choose one unread candidate per route when more Google evidence is required.

    Search result metadata establishes the candidate set. Selecting a candidate
    already judged relevant for a provider detail read is therefore a bounded
    deterministic continuation, not a new semantic query-planning decision.
    """

    if "current_round_no" not in prompt_input:
        return None
    attempted = set(attempted_detail_candidate_refs)
    candidates = tuple(dict.fromkeys(detail_candidate_refs))
    route_queries: list[dict[str, object]] = []
    retrieval_order: list[str] = []
    for route in select_followup_routes(prompt_input, frozen_routes):
        if route_operation_tool_id(route, "DETAIL_FETCH") is None:
            continue
        prefix = f"{route['resource_type'].lower()}:"
        candidate = next(
            (item for item in candidates if item.startswith(prefix) and item not in attempted),
            None,
        )
        if candidate is None:
            continue
        route_queries.append(
            {
                "route_id": route["route_id"],
                "operation": "DETAIL_FETCH",
                "reason_codes": ["CANDIDATE_DETAIL_REQUIRED"],
                "search_spec": None,
                "detail_candidate_ref": candidate,
            }
        )
        retrieval_order.append(route["route_id"])
    if not route_queries:
        return None
    return cast(
        RetrievalQueryPlanV2,
        {
            "schema_version": 2,
            "route_queries": route_queries,
            "required_information": ["candidate resource detail required by sufficiency"],
            "retrieval_order": retrieval_order,
        },
    )


__all__ = ["plan_candidate_detail"]
