"""Resolve account-authorized container scopes for frozen Retrieval routes."""

from __future__ import annotations

from collections.abc import Sequence

from google_work_agent.application.agents.retrieval.contracts.query_plan import (
    RetrievalV2ValidationError,
)
from google_work_agent.application.agents.tool_routing.contracts.tool_route_plan import (
    InputToolRouteV1,
)
from google_work_agent.ports.system.contracts.workflow_execution import (
    SelectedResourceRef,
)

_TASK_CONTAINER_RESOURCES = frozenset({"TASK", "TASK_LIST"})
_CALENDAR_CONTAINER_RESOURCES = frozenset(
    {"CALENDAR", "CALENDAR_EVENT", "CALENDAR_FREEBUSY"}
)


def resolve_route_container_scopes(
    *,
    frozen_routes: Sequence[InputToolRouteV1],
    selected_resources: Sequence[SelectedResourceRef],
    authorized_tasklist_ids: Sequence[str],
    authorized_calendar_ids: Sequence[str],
) -> dict[str, list[str]]:
    """Prefer an explicit current-Run container, else retain the full authorized scope."""
    task_scope = _unique_non_empty(authorized_tasklist_ids)
    calendar_scope = _unique_non_empty(authorized_calendar_ids)
    explicit_task = _selected_container_ids(
        selected_resources,
        container_type="TASK_LIST",
        item_type="TASK",
    )
    explicit_calendar = _selected_container_ids(
        selected_resources,
        container_type="CALENDAR",
        item_type="CALENDAR_EVENT",
    )
    result: dict[str, list[str]] = {}
    for route in frozen_routes:
        resource_type = route["resource_type"].upper()
        if resource_type in _TASK_CONTAINER_RESOURCES:
            refs = _validated_scope(
                explicit=explicit_task,
                authorized=task_scope,
                field="$.selected_resources[?(@.resource_type=='TASK')].parent_resource_id",
            )
        elif resource_type in _CALENDAR_CONTAINER_RESOURCES:
            refs = _validated_scope(
                explicit=explicit_calendar,
                authorized=calendar_scope,
                field=(
                    "$.selected_resources[?(@.resource_type=='CALENDAR_EVENT')]"
                    ".parent_resource_id"
                ),
            )
        else:
            continue
        if refs:
            result[route["route_id"]] = refs
    return result


def _selected_container_ids(
    selected_resources: Sequence[SelectedResourceRef],
    *,
    container_type: str,
    item_type: str,
) -> list[str]:
    refs: list[str] = []
    for selected in selected_resources:
        if selected.connector_id != "google_workspace":
            continue
        resource_type = selected.resource_type.upper()
        if resource_type == container_type:
            refs.append(selected.resource_id)
        elif resource_type == item_type:
            if selected.parent_resource_id is None:
                raise RetrievalV2ValidationError(
                    "selected resource has no validated parent container",
                    reason_code="RETRIEVAL_ROUTE_SCOPE_VIOLATION",
                    affected_field_paths=("$.selected_resources[].parent_resource_id",),
                )
            refs.append(selected.parent_resource_id)
    return list(dict.fromkeys(refs))


def _validated_scope(*, explicit: list[str], authorized: list[str], field: str) -> list[str]:
    if not explicit:
        return authorized
    if len(explicit) != 1:
        raise RetrievalV2ValidationError(
            "one frozen route cannot bind multiple explicit containers",
            reason_code="RETRIEVAL_ROUTE_SCOPE_VIOLATION",
            affected_field_paths=(field,),
        )
    if explicit[0] not in authorized:
        raise RetrievalV2ValidationError(
            "explicit container is outside the authorized account scope",
            reason_code="RETRIEVAL_ROUTE_SCOPE_VIOLATION",
            affected_field_paths=(field,),
        )
    return explicit


def _unique_non_empty(values: Sequence[str]) -> list[str]:
    return list(dict.fromkeys(value for value in values if value))


__all__ = ["resolve_route_container_scopes"]
