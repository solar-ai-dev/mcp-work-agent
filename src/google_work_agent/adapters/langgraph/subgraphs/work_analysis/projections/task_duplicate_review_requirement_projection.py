from __future__ import annotations

from collections.abc import Mapping


def project_task_duplicate_review_requirement(state: Mapping[str, object]) -> bool:
    plan = state.get("tool_route_plan")
    if not isinstance(plan, Mapping):
        return False
    input_plan = plan.get("input_plan")
    if not isinstance(input_plan, Mapping):
        return False
    routes = input_plan.get("input_routes", [])
    if not isinstance(routes, list):
        return False
    return any(
        isinstance(route, Mapping)
        and route.get("required") is True
        and isinstance(route.get("reason_codes"), list)
        and "POLICY_TASK_DUPLICATE_CHECK" in route["reason_codes"]
        for route in routes
    )


__all__ = ["project_task_duplicate_review_requirement"]
