"""Minimum current-Run projection for review.inspect_goal_and_evidence."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import NotRequired, TypedDict

from google_work_agent.adapters.langgraph.main.state import request_from_state
from google_work_agent.application.agents.project_run_reference_time import (
    RunReferenceTimeV1,
    project_run_reference_time,
)


class InspectGoalAndEvidenceInputV1(TypedDict):
    request_intent: dict[str, object]
    planning_result: dict[str, object]
    evidence: list[dict[str, object]]
    work_analysis: NotRequired[dict[str, object]]
    confirmation_response: NotRequired[dict[str, object]]
    user_action_modifications: NotRequired[list[dict[str, object]]]
    run_reference_time: NotRequired[RunReferenceTimeV1]


def project_inspect_goal_and_evidence_input(
    state: Mapping[str, object],
) -> InspectGoalAndEvidenceInputV1:
    request_intent = _mapping(state, "request_intent")
    planning_result = _mapping(state, "planning_result")
    evidence = _evidence(state.get("evidence", ()))
    result: InspectGoalAndEvidenceInputV1 = {
        "request_intent": dict(request_intent),
        "planning_result": dict(planning_result),
        "evidence": evidence,
    }
    work_analysis = state.get("work_analysis")
    if work_analysis is not None:
        if not isinstance(work_analysis, Mapping):
            raise ValueError("work_analysis must be an object")
        result["work_analysis"] = dict(work_analysis)
    confirmation = state.get("confirmation_response")
    if confirmation is not None:
        if not isinstance(confirmation, Mapping):
            raise ValueError("confirmation_response must be an object")
        result["confirmation_response"] = dict(confirmation)
    modifications = state.get("user_action_modifications")
    if modifications is not None:
        result["user_action_modifications"] = _objects(
            modifications, "user_action_modifications"
        )
    if (
        confirmation is None
        and not result.get("user_action_modifications")
        and _is_event_time_only(request_intent)
    ):
        try:
            request = request_from_state(state)
        except TypeError:
            request = None
        reference_time = (
            None if request is None else project_run_reference_time(request.run_budget)
        )
        if reference_time is not None:
            projected_evidence, separated = _separate_gmail_receipt_metadata(evidence)
            if separated:
                result["evidence"] = projected_evidence
                result["run_reference_time"] = reference_time
    return result


def _is_event_time_only(request_intent: Mapping[str, object]) -> bool:
    constraints = request_intent.get("constraints")
    if not isinstance(constraints, list):
        return False
    axes: set[str] = set()
    for item in constraints:
        if not isinstance(item, Mapping) or item.get("field") != "temporal_axis":
            continue
        value = item.get("value")
        values = value if isinstance(value, list) else [value]
        axes.update(axis for axis in values if isinstance(axis, str))
    return axes == {"EVENT_TIME"}


def _separate_gmail_receipt_metadata(
    evidence: list[dict[str, object]],
) -> tuple[list[dict[str, object]], bool]:
    projected: list[dict[str, object]] = []
    separated = False
    for item in evidence:
        handle = item.get("resource_handle")
        locator = item.get("locator")
        excerpt = item.get("excerpt")
        if (
            not isinstance(handle, str)
            or not handle.startswith("gmail_thread:")
            or not isinstance(locator, Mapping)
            or not isinstance(locator.get("received_at"), str)
            or not isinstance(excerpt, str)
            or not excerpt.startswith("Message:")
            or "Thread messages collected:" not in excerpt
        ):
            projected.append(item)
            continue
        envelope = f"Received: {locator['received_at']}"
        lines = excerpt.splitlines(keepends=True)
        matching = [index for index, line in enumerate(lines) if line.strip() == envelope]
        if len(matching) != 1:
            projected.append(item)
            continue
        projected.append(
            {
                **item,
                "excerpt": "".join(
                    line for index, line in enumerate(lines) if index != matching[0]
                ),
                "locator": {key: value for key, value in locator.items() if key != "received_at"},
            }
        )
        separated = True
    return projected, separated


def _mapping(state: Mapping[str, object], key: str) -> Mapping[str, object]:
    value = state.get(key)
    if not isinstance(value, Mapping):
        raise ValueError(f"{key} is required")
    return value


def _evidence(value: object) -> list[dict[str, object]]:
    if not isinstance(value, Sequence) or isinstance(value, str | bytes):
        raise ValueError("evidence must be a sequence")
    if not all(isinstance(item, Mapping) for item in value):
        raise ValueError("evidence items must be objects")
    return [dict(item) for item in value]


def _objects(value: object, label: str) -> list[dict[str, object]]:
    if not isinstance(value, Sequence) or isinstance(value, str | bytes):
        raise ValueError(f"{label} must be a sequence")
    if not all(isinstance(item, Mapping) for item in value):
        raise ValueError(f"{label} items must be objects")
    return [dict(item) for item in value]


__all__ = ["InspectGoalAndEvidenceInputV1", "project_inspect_goal_and_evidence_input"]
