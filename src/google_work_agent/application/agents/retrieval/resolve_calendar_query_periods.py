"""Resolve request periods for Calendar event and availability routes."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime, time

from google_work_agent.application.agents.retrieval.contracts.query_plan import (
    TemporalRangeConstraintV1,
)
from google_work_agent.application.agents.retrieval.project_route_constraints import (
    project_route_work_constraint_sets,
)
from google_work_agent.application.agents.retrieval.resolve_relative_period import (
    ResolvedTemporalRange,
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
    route_types = {route["resource_type"] for route in frozen_routes}
    bind_explicit_window = (
        len(route_types & {"CALENDAR_EVENT", "CALENDAR_FREEBUSY"}) == 1
        and route_types <= {"CALENDAR", "CALENDAR_EVENT", "CALENDAR_FREEBUSY"}
    )
    result: dict[str, TemporalRangeConstraintV1] = {}
    for route in frozen_routes:
        if route["resource_type"] not in {"CALENDAR_EVENT", "CALENDAR_FREEBUSY"}:
            continue
        periods: list[ResolvedTemporalRange | None] = []
        for constraints in project_route_work_constraint_sets(prompt_input, route):
            period = resolve_relative_period(
                constraints, now_ms=now_ms, timezone=timezone, default_axis="EVENT_TIME"
            )
            if period is not None and period["axis"] == "MESSAGE_TIME":
                period = None
            if period is not None and bind_explicit_window:
                period = _bind_explicit_time_window(constraints, period)
            periods.append(period)
        temporal = periods[0] if periods else None
        if temporal is None or any(period != temporal for period in periods):
            continue
        if route["resource_type"] == "CALENDAR_EVENT":
            result[route["route_id"]] = {**temporal, "axis": "EVENT_TIME"}
        elif route["resource_type"] == "CALENDAR_FREEBUSY":
            result[route["route_id"]] = {**temporal, "axis": "AVAILABILITY_WINDOW"}
    return result


def _bind_explicit_time_window(
    constraints: object,
    period: ResolvedTemporalRange,
) -> ResolvedTemporalRange | None:
    """Narrow one resolved day only when both explicit time boundaries exist."""

    if not isinstance(constraints, list):
        return period
    values: dict[str, str] = {}
    for item in constraints:
        if not isinstance(item, Mapping) or item.get("kind") != "TIME":
            continue
        field = item.get("field")
        value = item.get("value")
        if field not in {"start_time", "end_time"} or not isinstance(value, str):
            continue
        if field in values:
            return None
        values[field] = value
    if not values:
        return period
    if set(values) != {"start_time", "end_time"}:
        return None
    try:
        period_start = datetime.fromisoformat(period["start_local"])
        period_end = datetime.fromisoformat(period["end_local"])
        start = _local_datetime(values["start_time"], period_start)
        end = _local_datetime(values["end_time"], period_start)
    except ValueError:
        return None
    if not period_start <= start < end <= period_end:
        return None
    return {
        **period,
        "start_local": start.isoformat(),
        "end_local": end.isoformat(),
    }


def _local_datetime(value: str, period_start: datetime) -> datetime:
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        parsed = datetime.combine(period_start.date(), time.fromisoformat(value))
    if parsed.tzinfo is not None:
        raise ValueError("Calendar local boundary must not carry an offset")
    return parsed


__all__ = ["resolve_calendar_query_periods"]
