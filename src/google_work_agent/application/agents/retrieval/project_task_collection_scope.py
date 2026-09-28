"""Preserve Task business Source coverage independently of Policy-only pre-reads."""

from collections.abc import Mapping
from typing import Literal

from google_work_agent.application.agents.retrieval.project_route_constraints import (
    project_route_work_constraint_sets,
)
from google_work_agent.application.agents.tool_routing.contracts.tool_route_plan import (
    InputToolRouteV1,
)


def project_task_collection_scope(
    request_intent: Mapping[str, object], route: InputToolRouteV1
) -> Literal["ANY", "INCOMPLETE"]:
    responsibilities = request_intent.get("resource_responsibilities")
    sources = (
        responsibilities.get("source_reads") if isinstance(responsibilities, Mapping) else None
    )
    route_ids = set(route.get("work_unit_ids", ()))
    legacy_unbound = (
        not route_ids
        and request_intent.get("schema_version") != 3
        and "requested_work" not in request_intent
        and "work_unit_ids" not in route
    )
    source_ids: list[str] = []
    legacy_source = False
    for source in sources if isinstance(sources, list) else []:
        if not isinstance(source, Mapping) or source.get("resource_type") != "TASK":
            continue
        ids = source.get("work_unit_ids")
        if isinstance(ids, list):
            source_ids.extend(unit_id for unit_id in ids if unit_id in route_ids)
        elif legacy_unbound:
            legacy_source = True
    if not source_ids and not legacy_source:
        return "INCOMPLETE"
    source_route = (
        {**route, "work_unit_ids": list(dict.fromkeys(source_ids))} if source_ids else route
    )
    consumer_constraints = project_route_work_constraint_sets(
        {"request_intent": request_intent}, source_route
    )
    for constraints in consumer_constraints:
        statuses = {
            constraint.get("value")
            for constraint in constraints
            if constraint.get("kind") == "SCOPE"
            and constraint.get("field") == "status"
            and constraint.get("source_resource_type") == "TASK"
            and isinstance(constraint.get("value"), str)
        }
        if statuses != {"INCOMPLETE"}:
            return "ANY"
    return "INCOMPLETE"
