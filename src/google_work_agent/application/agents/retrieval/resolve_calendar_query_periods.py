"""Resolve request periods for Calendar event and availability routes."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from google_work_agent.application.agents.retrieval.contracts.query_plan import (
    TemporalRangeConstraintV1,
)
from google_work_agent.application.agents.retrieval.resolve_relative_period import (
    resolve_relative_period,
)
from google_work_agent.application.agents.tool_routing.contracts.tool_route_plan import (
    InputToolRouteV1,
)


def resolve_calendar_query_periods(
    *,
    prompt_input: Mapping[str, object],
    frozen_routes: Sequence[InputToolRouteV1],
    now_ms: int | None,
    timezone: str | None,
) -> dict[str, TemporalRangeConstraintV1]:
    """Bind one verified request period to Calendar query axes by route role."""

    intent = prompt_input.get("request_intent")
    if not isinstance(intent, Mapping) or now_ms is None or timezone is None:
        return {}
    temporal = resolve_relative_period(
        intent.get("constraints"),
        now_ms=now_ms,
        timezone=timezone,
        default_axis="EVENT_TIME",
    )
    if temporal is None or temporal["axis"] == "MESSAGE_TIME":
        return {}
    result: dict[str, TemporalRangeConstraintV1] = {}
    for route in frozen_routes:
        if route["resource_type"] == "CALENDAR_EVENT":
            result[route["route_id"]] = {**temporal, "axis": "EVENT_TIME"}
        elif route["resource_type"] == "CALENDAR_FREEBUSY":
            result[route["route_id"]] = {**temporal, "axis": "AVAILABILITY_WINDOW"}
    return result


__all__ = ["resolve_calendar_query_periods"]
