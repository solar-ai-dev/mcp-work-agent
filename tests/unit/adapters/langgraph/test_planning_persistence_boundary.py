from typing import cast

import pytest

from google_work_agent.adapters.langgraph.main.plan_persistence import (
    connector_ids_from_frozen_routes,
    expected_for_action,
)
from google_work_agent.adapters.langgraph.main.state import GraphState
from google_work_agent.application.agents.planning.contracts.action_plan_draft import (
    ActionPlanDraftV2,
    PlannedActionV2,
)
from google_work_agent.application.agents.tool_routing.contracts.tool_route_plan import (
    OutputToolRouteV1,
)


def _action() -> PlannedActionV2:
    return {
        "action_id": "action-1",
        "route_id": "route-1",
        "tool_id": "tasks_create_task",
        "effect": "CREATE",
        "arguments": {
            "task_list_id": "list-1",
            "payload": {"title": "Prepare report", "scheduled_date": "2026-08-20"},
        },
        "evidence_refs": ["evidence-1"],
        "depends_on_action_ids": [],
    }


def _plan() -> ActionPlanDraftV2:
    return {
        "schema_version": 2,
        "meta": {"artifact_id": "plan-1", "revision": 1, "based_on": []},
        "actions": [_action()],
    }


def _state() -> GraphState:
    return cast(
        GraphState,
        {
            "tool_route_plan": {
                "output_plan": {
                    "output_mode": "ACTION",
                    "output_routes": [
                        {
                            "route_id": "route-1",
                            "resource_type": "TASK",
                            "connector_id": "google_workspace",
                            "effect": "CREATE",
                            "selected_tool_id": "tasks_create_task",
                            "reason_codes": ["REQUESTED_OUTPUT"],
                        }
                    ],
                }
            }
        },
    )


def _output_routes(state: GraphState) -> list[OutputToolRouteV1]:
    route_plan = state["tool_route_plan"]
    assert route_plan is not None
    output_plan = route_plan["output_plan"]
    assert output_plan["output_mode"] == "ACTION"
    return output_plan["output_routes"]


def test_current_plan__joins_frozen_route__and_builds_expected() -> None:
    action = _action()

    assert connector_ids_from_frozen_routes(state=_state(), plan=_plan()) == {
        "action-1": "google_workspace"
    }
    assert expected_for_action(action) == {
        "payload": {
            "title": "Prepare report", "due": "2026-08-20", "notes": "",
            "status": "needsAction", "parent_id": "list-1",
        }
    }


def test_current_plan__with_ordered_frozen_route_subset__accepts_projection() -> None:
    state = _state()
    routes = _output_routes(state)
    routes.insert(
        0,
        {
            "route_id": "route-skipped",
            "resource_type": "CALENDAR_EVENT",
            "connector_id": "google_workspace",
            "effect": "CREATE",
            "selected_tool_id": "calendar_create_event",
            "reason_codes": ["REQUESTED_OUTPUT"],
        },
    )

    assert connector_ids_from_frozen_routes(state=state, plan=_plan()) == {
        "action-1": "google_workspace"
    }


def test_current_plan__with_reordered_frozen_route_subset__rejects_projection() -> None:
    state = _state()
    _output_routes(state).append(
        {
            "route_id": "route-2",
            "resource_type": "TASK",
            "connector_id": "google_workspace",
            "effect": "CREATE",
            "selected_tool_id": "tasks_create_task",
            "reason_codes": ["REQUESTED_OUTPUT"],
        }
    )
    first = _action()
    second: PlannedActionV2 = {**_action(), "action_id": "action-2", "route_id": "route-2"}
    plan = _plan()
    plan["actions"] = [second, first]

    with pytest.raises(ValueError, match="preserve frozen output route order"):
        connector_ids_from_frozen_routes(state=state, plan=plan)


def test_current_plan__with_duplicate_frozen_route_identity__fails_closed() -> None:
    state = _state()
    routes = _output_routes(state)
    routes.append(routes[0].copy())

    with pytest.raises(ValueError, match="duplicate frozen output route id"):
        connector_ids_from_frozen_routes(state=state, plan=_plan())


@pytest.mark.parametrize("field", ["route_id", "tool_id", "effect"])
def test_current_plan__fails_closed_on__frozen_route_drift(field: str) -> None:
    plan = _plan()
    plan["actions"][0][field] = "drift"  # type: ignore[literal-required]

    with pytest.raises(ValueError, match="does not match frozen route"):
        connector_ids_from_frozen_routes(state=_state(), plan=plan)
