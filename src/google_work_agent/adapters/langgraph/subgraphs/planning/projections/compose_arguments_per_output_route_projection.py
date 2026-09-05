"""Exact input projection for per-route Tool argument composition."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import NotRequired, TypedDict, cast

from google_work_agent.adapters.langgraph.main.state import request_from_state
from google_work_agent.application.agents.request_understanding.contracts.request_intent import (
    RequestIntentV2,
)
from google_work_agent.ports.system.contracts.workflow_execution import SelectedResourceRef


class ComposeArgumentsInputV1(TypedDict):
    output_routes: list[dict[str, object]]
    objectives: list[dict[str, object]]
    evidence: list[dict[str, object]]
    request_intent: RequestIntentV2
    selected_resources: list[SelectedResourceRef]
    work_analysis: NotRequired[dict[str, object]]
    confirmation_response: NotRequired[dict[str, object]]


def project_compose_arguments_per_output_route_input(
    state: Mapping[str, object],
) -> ComposeArgumentsInputV1:
    output_plan = state.get("output_plan")
    objectives = state.get("action_objective_candidates")
    if not isinstance(output_plan, Mapping):
        raise ValueError("output_plan is required")
    routes = _objects(output_plan.get("output_routes"), "output_routes")
    objective_items = _objects(objectives, "objectives")
    request_intent = state.get("request_intent")
    if not isinstance(request_intent, Mapping):
        raise ValueError("request_intent is required")
    evidence = state.get("evidence", ())
    if not isinstance(evidence, Sequence) or isinstance(evidence, (str, bytes)):
        raise ValueError("evidence must be a sequence")
    evidence_items = [dict(item) for item in evidence if isinstance(item, Mapping)]
    if len(evidence_items) != len(evidence):
        raise ValueError("evidence items must be objects")
    result: ComposeArgumentsInputV1 = {
        "output_routes": routes,
        "objectives": objective_items,
        "evidence": evidence_items,
        "request_intent": cast(RequestIntentV2, request_intent),
        "selected_resources": _selected_resources(state),
    }
    work_analysis = state.get("work_analysis")
    confirmation = state.get("confirmation_response")
    if work_analysis is not None:
        if not isinstance(work_analysis, Mapping):
            raise ValueError("work_analysis must be an object")
        result["work_analysis"] = dict(work_analysis)
    if confirmation is not None:
        if not isinstance(confirmation, Mapping):
            raise ValueError("confirmation_response must be an object")
        result["confirmation_response"] = dict(confirmation)
    return result


def _objects(value: object, name: str) -> list[dict[str, object]]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise ValueError(f"{name} must be a sequence")
    if not all(isinstance(item, Mapping) for item in value):
        raise ValueError(f"{name} items must be objects")
    return [dict(cast(Mapping[str, object], item)) for item in value]


def _selected_resources(state: Mapping[str, object]) -> list[SelectedResourceRef]:
    try:
        return list(request_from_state(state).selected_resources)
    except TypeError:
        return []


__all__ = ["ComposeArgumentsInputV1", "project_compose_arguments_per_output_route_input"]
