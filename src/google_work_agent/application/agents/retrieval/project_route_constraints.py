"""Project existing request constraints by frozen Route WorkUnit ownership."""

from collections.abc import Mapping

from google_work_agent.application.agents.tool_routing.contracts.tool_route_plan import (
    InputToolRouteV1,
)


def project_route_constraints(
    prompt_input: Mapping[str, object],
    route: InputToolRouteV1,
) -> list[Mapping[str, object]]:
    intent = prompt_input.get("request_intent")
    constraints = intent.get("constraints") if isinstance(intent, Mapping) else None
    if not isinstance(constraints, list):
        return []
    route_work_ids = frozenset(route.get("work_unit_ids", ()))
    legacy_unbound = (
        not route_work_ids
        and isinstance(intent, Mapping)
        and intent.get("schema_version") != 3
        and "requested_work" not in intent
        and "work_unit_ids" not in route
    )
    return [
        constraint
        for constraint in constraints
        if isinstance(constraint, Mapping)
        and (
            bool(route_work_ids.intersection(constraint.get("work_unit_ids", ())))
            if isinstance(constraint.get("work_unit_ids"), list)
            else legacy_unbound and "work_unit_ids" not in constraint
        )
    ]


def project_route_work_constraint_sets(
    prompt_input: Mapping[str, object],
    route: InputToolRouteV1,
) -> list[list[Mapping[str, object]]]:
    """Keep each shared READ consumer separate before deriving one common filter."""
    unit_ids = list(dict.fromkeys(route.get("work_unit_ids", ())))
    if not unit_ids:
        return [project_route_constraints(prompt_input, route)]
    return [
        project_route_constraints(prompt_input, {**route, "work_unit_ids": [unit_id]})
        for unit_id in unit_ids
    ]
