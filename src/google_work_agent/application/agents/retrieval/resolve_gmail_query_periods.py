"""Resolve request-relative periods for searchable Gmail routes."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from google_work_agent.application.agents.retrieval.contracts.query_plan import (
    TemporalRangeConstraintV1,
)
from google_work_agent.application.agents.retrieval.is_searchable_gmail_route import (
    is_searchable_gmail_route,
)
from google_work_agent.application.agents.retrieval.resolve_relative_period import (
    resolve_relative_period,
)
from google_work_agent.application.agents.tool_routing.contracts.tool_route_plan import (
    InputToolRouteV1,
)


def resolve_gmail_query_periods(
    *,
    prompt_input: Mapping[str, object],
    frozen_routes: Sequence[InputToolRouteV1],
    now_ms: int | None,
    timezone: str | None,
) -> dict[str, TemporalRangeConstraintV1]:
    """Bind the existing period resolver to Gmail routes, never Calendar policy reads."""
    intent = prompt_input.get("request_intent")
    if not isinstance(intent, Mapping) or now_ms is None or timezone is None:
        return {}
    temporal = resolve_relative_period(intent.get("constraints"), now_ms=now_ms, timezone=timezone)
    if temporal is None:
        return {}
    bound: TemporalRangeConstraintV1 = {**temporal}
    return {
        route["route_id"]: bound
        for route in frozen_routes
        if is_searchable_gmail_route(route)
    }
