from __future__ import annotations

from google_work_agent.adapters.langgraph.subgraphs.tool_routing.state import ToolRouteStateV1
from google_work_agent.application.agents.tool_routing.validate_route import validate_route
from google_work_agent.application.tool_registry.signed_tool_registry import SignedToolRegistry
from google_work_agent.application.use_cases.connection.check_connector_prerequisites import (
    CheckConnectorPrerequisitesHandler,
    CheckConnectorPrerequisitesQuery,
)

from ..projections.validate_route_projection import (
    project_validate_route_input,
)


def validate_route_node(
    state: ToolRouteStateV1,
    *,
    tool_catalog: SignedToolRegistry,
    connector_prerequisites: CheckConnectorPrerequisitesHandler | None = None,
) -> ToolRouteStateV1:
    plan = project_validate_route_input(state)["final_route"]
    if plan is not None:
        validate_route(plan, tool_catalog=tool_catalog)
    patch: ToolRouteStateV1 = {
        "tool_route_plan": plan,
        "workflow_signal": state.get("workflow_signal"),
        "prerequisite_message": None,
    }
    if (
        plan is not None
        and connector_prerequisites is not None
        and "admitted_connector_ids" in state
    ):
        connector_ids = {route["connector_id"] for route in plan["input_plan"]["input_routes"]}
        if plan["output_plan"]["output_mode"] == "ACTION":
            connector_ids.update(
                route["connector_id"] for route in plan["output_plan"]["output_routes"]
            )
        prerequisites = connector_prerequisites(
            CheckConnectorPrerequisitesQuery(
                tuple(connector_ids),
                tuple(state["admitted_connector_ids"]),
                state.get("run_id"),
            )
        )
        patch["admitted_connector_ids"] = list(prerequisites.admitted_connector_ids)
        patch["prerequisite_message"] = prerequisites.user_message
    return patch
