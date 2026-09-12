from typing import cast

import pytest

from google_work_agent.application.agents.retrieval.contracts.query_plan import (
    RetrievalV2ValidationError,
)
from google_work_agent.application.agents.retrieval.resolve_route_container_scopes import (
    resolve_route_container_scopes,
)
from google_work_agent.application.agents.tool_routing.contracts.tool_route_plan import (
    InputToolRouteV1,
)
from google_work_agent.ports.system.contracts.workflow_execution import SelectedResourceRef


def _route(route_id: str, resource_type: str) -> InputToolRouteV1:
    return cast(
        InputToolRouteV1,
        {
            "route_id": route_id,
            "connector_id": "google_workspace",
            "resource_type": resource_type,
            "allowed_read_tool_ids": [],
            "required": True,
            "reason_codes": ["USER_REQUEST"],
        },
    )


def test_container_scopes__retain_all_authorized_task_and_calendar_targets() -> None:
    result = resolve_route_container_scopes(
        frozen_routes=[_route("tasks", "TASK"), _route("events", "CALENDAR_EVENT")],
        selected_resources=[],
        authorized_tasklist_ids=["tasks-a", "tasks-b"],
        authorized_calendar_ids=["calendar-a", "calendar-b"],
    )

    assert result == {
        "tasks": ["tasks-a", "tasks-b"],
        "events": ["calendar-a", "calendar-b"],
    }


@pytest.mark.parametrize(
    ("resource_type", "resource_id", "parent_id", "route_id", "expected"),
    [
        ("TASK_LIST", "tasks-b", None, "tasks", ["tasks-b"]),
        ("TASK", "task-1", "tasks-b", "tasks", ["tasks-b"]),
        ("CALENDAR", "calendar-b", None, "events", ["calendar-b"]),
        ("CALENDAR_EVENT", "event-1", "calendar-b", "events", ["calendar-b"]),
    ],
)
def test_container_scopes__explicit_current_run_target_narrows_authorized_scope(
    resource_type: str,
    resource_id: str,
    parent_id: str | None,
    route_id: str,
    expected: list[str],
) -> None:
    route = _route(route_id, "TASK" if route_id == "tasks" else "CALENDAR_EVENT")
    result = resolve_route_container_scopes(
        frozen_routes=[route],
        selected_resources=[
            SelectedResourceRef(
                "ref-1",
                "google_workspace",
                resource_type,
                resource_id,
                parent_id,
            )
        ],
        authorized_tasklist_ids=["tasks-a", "tasks-b"],
        authorized_calendar_ids=["calendar-a", "calendar-b"],
    )

    assert result == {route_id: expected}


def test_container_scopes__reject_explicit_target_outside_authorized_scope() -> None:
    with pytest.raises(RetrievalV2ValidationError, match="outside the authorized"):
        resolve_route_container_scopes(
            frozen_routes=[_route("tasks", "TASK")],
            selected_resources=[
                SelectedResourceRef(
                    "ref-1", "google_workspace", "TASK", "task-1", "tasks-denied"
                )
            ],
            authorized_tasklist_ids=["tasks-allowed"],
            authorized_calendar_ids=[],
        )
