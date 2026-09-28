"""Carry reviewed route diagnostics without taking Request Intent authority."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from copy import deepcopy
from typing import TypedDict, cast

from google_work_agent.application.agents.request_understanding.contracts.request_intent import (
    RequestIntentV3,
)
from google_work_agent.application.agents.review.contracts.plan_review_result import (
    PlanReviewResultV2,
    ReviewRouteReconsiderationV2,
    RouteIssueV1,
)
from google_work_agent.application.agents.review.validate_review import validate_review
from google_work_agent.application.agents.state_artifact import StateArtifactRefV1
from google_work_agent.application.agents.tool_routing.contracts.route_binding_candidate import (
    BoundOutputRouteCandidateV1,
)
from google_work_agent.application.agents.tool_routing.contracts.tool_route_plan import (
    OutputToolRouteV1,
    ToolRoutePlanV2,
    output_routes,
)
from google_work_agent.application.agents.tool_routing.validate_route import (
    ToolRouteValidationError,
)


class SelectionReconsiderationV1(TypedDict):
    """Invocation-local references copied from already-owned parent artifacts."""

    review: ReviewRouteReconsiderationV2
    previous_route_plan: ToolRoutePlanV2


class ReconsideredSelectionRouteV1(TypedDict):
    route_id: str
    previous_route_id: str
    previous_tool_id: str
    work_unit_ids: list[str]
    issues: list[RouteIssueV1]


class ToolSelectionReconsiderationV1(TypedDict):
    review_ref: StateArtifactRefV1
    previous_output_plan_ref: StateArtifactRefV1
    routes: list[ReconsideredSelectionRouteV1]


def capture_selection_reconsideration(
    *,
    request_intent: RequestIntentV3,
    previous_route_plan: ToolRoutePlanV2 | None,
    review: PlanReviewResultV2 | None,
    workflow_signal: Mapping[str, object] | None,
) -> SelectionReconsiderationV1 | None:
    if (
        workflow_signal is None
        or workflow_signal.get("kind") != "ROUTE_RECONSIDERATION_REQUIRED"
        or review is None
        or review["status"] != "ROUTE_RECONSIDERATION"
    ):
        return None
    validate_review(review)
    if previous_route_plan is None:
        raise ToolRouteValidationError("review reconsideration requires the previous route plan")
    intent_ref = _ref(request_intent["meta"])
    if intent_ref not in previous_route_plan["output_plan"]["meta"]["based_on"]:
        raise ToolRouteValidationError("review reconsideration route plan is stale")
    known_ids = {
        route["route_id"] for route in previous_route_plan["input_plan"]["input_routes"]
    } | {route["route_id"] for route in output_routes(previous_route_plan)}
    if any(
        route_id not in known_ids
        for issue in review["route_issues"]
        for route_id in issue["affected_route_ids"]
    ):
        raise ToolRouteValidationError("review reconsideration affected route is stale")
    context: SelectionReconsiderationV1 = {
        "review": review,
        "previous_route_plan": previous_route_plan,
    }
    return deepcopy(context)


def project_selection_reconsideration(
    *,
    context: SelectionReconsiderationV1 | None,
    candidates: Sequence[BoundOutputRouteCandidateV1],
) -> ToolSelectionReconsiderationV1 | None:
    """Preserve each route's diagnostics inside one capability-level selection."""
    if context is None:
        return None
    previous_routes = output_routes(context["previous_route_plan"])
    issues = context["review"]["route_issues"]
    projected: list[ReconsideredSelectionRouteV1] = []
    for candidate in candidates:
        matches = [route for route in previous_routes if _same_binding(route, candidate)]
        if (
            len(matches) != 1
            or sum(
                _candidate_binding(other) == _candidate_binding(candidate) for other in candidates
            )
            != 1
        ):
            raise ToolRouteValidationError("review reconsideration route binding is not unique")
        previous = matches[0]
        applicable = [
            issue
            for issue in issues
            if not issue["affected_route_ids"]
            or previous["route_id"] in issue["affected_route_ids"]
        ]
        projected.append(
            {
                "route_id": candidate.route_id,
                "previous_route_id": previous["route_id"],
                "previous_tool_id": previous["selected_tool_id"],
                "work_unit_ids": list(candidate.work_unit_ids),
                "issues": deepcopy(applicable),
            }
        )
    if not any(route["issues"] for route in projected):
        return None
    return {
        "review_ref": _ref(context["review"]["meta"]),
        "previous_output_plan_ref": _ref(context["previous_route_plan"]["output_plan"]["meta"]),
        "routes": projected,
    }


def _candidate_binding(candidate: BoundOutputRouteCandidateV1) -> tuple[object, ...]:
    return (
        candidate.connector_id,
        candidate.resource_type,
        candidate.effect,
        frozenset(candidate.work_unit_ids),
    )


def _same_binding(route: OutputToolRouteV1, candidate: BoundOutputRouteCandidateV1) -> bool:
    return (
        route["connector_id"],
        route["resource_type"],
        route["effect"],
        frozenset(route["work_unit_ids"]),
    ) == _candidate_binding(candidate)


def _ref(meta: Mapping[str, object]) -> StateArtifactRefV1:
    return {"artifact_id": cast(str, meta["artifact_id"]), "revision": cast(int, meta["revision"])}
