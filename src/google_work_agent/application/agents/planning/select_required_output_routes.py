"""Consume Work Analysis route applicability without re-deciding its meaning."""

from __future__ import annotations

from collections.abc import Mapping


def select_required_output_routes(
    output_plan: Mapping[str, object],
    *,
    work_analysis: Mapping[str, object] | None,
) -> dict[str, object]:
    if output_plan.get("output_mode") != "ACTION":
        return dict(output_plan)
    raw_routes = output_plan.get("output_routes")
    if not isinstance(raw_routes, list) or not all(
        isinstance(item, Mapping) for item in raw_routes
    ):
        raise ValueError("ACTION output routes must be objects")
    routes = [dict(item) for item in raw_routes]
    if work_analysis is None or "route_action_necessities" not in work_analysis:
        return {**output_plan, "output_routes": routes}
    raw_assessments = work_analysis["route_action_necessities"]
    if not isinstance(raw_assessments, list) or not all(
        isinstance(item, Mapping) for item in raw_assessments
    ):
        raise ValueError("route action necessities must be objects")
    assessments = {str(item.get("route_id")): item for item in raw_assessments}
    route_ids = {str(route.get("route_id")) for route in routes}
    if len(assessments) != len(raw_assessments) or set(assessments) != route_ids:
        raise ValueError("route action necessities must exactly cover the frozen output routes")
    if any(
        item.get("status") not in {"REQUIRED", "NOT_REQUIRED", "UNDETERMINED"}
        for item in assessments.values()
    ):
        raise ValueError("route action necessity status is invalid")
    if any(item.get("status") == "UNDETERMINED" for item in assessments.values()):
        raise ValueError("Planning cannot consume an undetermined action necessity")
    selected = [
        route for route in routes if assessments[str(route["route_id"])].get("status") == "REQUIRED"
    ]
    return {**output_plan, "output_routes": selected}


__all__ = ["select_required_output_routes"]
