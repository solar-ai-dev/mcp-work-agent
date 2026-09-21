"""Bind exact current-Run resource anchors to direct Retrieval reads."""

from __future__ import annotations

from collections.abc import Sequence
from typing import TypedDict

from google_work_agent.application.agents.request_understanding.contracts.request_intent import (
    RequestIntentV3,
    RequestUnderstandingValidationError,
    validated_gmail_draft_anchor,
)
from google_work_agent.application.agents.retrieval.contracts.query_plan import (
    RetrievalV2ValidationError,
)
from google_work_agent.application.agents.tool_routing.contracts.tool_route_plan import (
    InputToolRouteV1,
)
from google_work_agent.ports.system.contracts.workflow_execution import SelectedResourceRef


class ExactResourceIdentityV1(TypedDict):
    resource_type: str
    resource_id: str
    parent_id: str | None


class ExactResourceBindingsV1(TypedDict):
    refs_by_route: dict[str, list[str]]
    identities_by_ref: dict[str, ExactResourceIdentityV1]


_DIRECT_READ_TOOLS = frozenset(
    {
        "gmail_get_thread",
        "gmail_get_message",
        "gmail_get_draft",
        "gmail_get_attachment",
        "tasks_get_task",
        "calendar_get_event",
        "github_get_issue",
    }
)


def bind_exact_resource_refs(
    *,
    request_intent: RequestIntentV3,
    frozen_routes: Sequence[InputToolRouteV1],
    selected_resources: Sequence[SelectedResourceRef],
) -> ExactResourceBindingsV1:
    """Bind trusted UI selections and explicit Draft anchors without provider inference."""
    refs_by_route: dict[str, list[str]] = {}
    identities_by_ref: dict[str, ExactResourceIdentityV1] = {}
    try:
        draft_anchor = validated_gmail_draft_anchor(request_intent)
    except RequestUnderstandingValidationError as error:
        raise RetrievalV2ValidationError(
            str(error),
            reason_code="RETRIEVAL_ROUTE_SCOPE_VIOLATION",
            affected_field_paths=("$.request_intent.constraints",),
        ) from error

    for route in frozen_routes:
        if not _DIRECT_READ_TOOLS.intersection(route["allowed_read_tool_ids"]):
            continue
        route_type = route["resource_type"].upper()
        route_refs: list[str] = []
        for selected in selected_resources:
            if (
                selected.connector_id != route["connector_id"]
                or selected.resource_type.upper() != route_type
            ):
                continue
            resource_ref = f"{route_type.lower()}:{selected.resource_id}"
            route_refs.append(resource_ref)
            identities_by_ref[resource_ref] = {
                "resource_type": selected.resource_type,
                "resource_id": selected.resource_id,
                "parent_id": selected.parent_resource_id,
            }
        if route_type == "GMAIL_DRAFT" and draft_anchor is not None:
            resource_ref = f"gmail_draft:{draft_anchor}"
            route_refs.append(resource_ref)
            identities_by_ref[resource_ref] = {
                "resource_type": "gmail_draft",
                "resource_id": draft_anchor,
                "parent_id": None,
            }
        route_refs = list(dict.fromkeys(route_refs))
        if len(route_refs) > 1:
            raise RetrievalV2ValidationError(
                "exact resource anchors conflict for one Retrieval route",
                reason_code="RETRIEVAL_ROUTE_SCOPE_VIOLATION",
                affected_field_paths=("$.validated_resource_refs",),
            )
        if route_refs:
            refs_by_route[route["route_id"]] = route_refs
    return {"refs_by_route": refs_by_route, "identities_by_ref": identities_by_ref}


__all__ = ["ExactResourceBindingsV1", "ExactResourceIdentityV1", "bind_exact_resource_refs"]
