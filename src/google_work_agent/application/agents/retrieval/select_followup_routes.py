"""Select frozen routes that can resolve required retrieval issues."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from google_work_agent.application.agents.tool_routing.contracts.tool_route_plan import (
    InputToolRouteV1,
)


def select_followup_routes(
    prompt_input: Mapping[str, object], frozen_routes: Sequence[InputToolRouteV1],
) -> list[InputToolRouteV1]:
    """Bind unresolved provider issues to their existing frozen input routes."""

    issues = prompt_input.get("unresolved_sufficiency_issues")
    if not isinstance(issues, list):
        return []
    selected: set[str] = set()
    for issue in issues:
        if not isinstance(issue, Mapping) or issue.get("required") is not True:
            continue
        source = issue.get("resolution_source")
        if source not in {"GOOGLE", "CONNECTOR"}:
            continue
        eligible = [
            route
            for route in frozen_routes
            if (route["connector_id"] == "google_workspace") == (source == "GOOGLE")
        ]
        route_id = issue.get("route_id")
        if route_id is not None:
            selected.update(
                route["route_id"] for route in eligible if route["route_id"] == route_id
            )
        elif len(eligible) == 1:
            # Older checkpoints have unqualified issues; only an unambiguous binding is safe.
            selected.add(eligible[0]["route_id"])
    return [route for route in frozen_routes if route["route_id"] in selected]


__all__ = ["select_followup_routes"]
