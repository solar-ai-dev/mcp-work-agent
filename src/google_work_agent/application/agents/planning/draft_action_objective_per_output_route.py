"""Draft one bounded business objective for each frozen output route."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from copy import deepcopy
from typing import cast

from google_work_agent.application.agents.planning.contracts.planning_semantics import (
    ActionObjectiveCandidateV1,
    ActionTargetSemanticsV1,
    PlanningSemanticInvoker,
)
from google_work_agent.application.agents.planning.materialize_task_create_payload import (
    materialize_task_create_payload,
)
from google_work_agent.ports.llm.structured_inference_contracts import OutputSchemaDefinition

PROMPT_ID = "planning.draft_action_objective_per_output_route"

ACTION_OBJECTIVE_CANDIDATE_OUTPUT_SCHEMA = OutputSchemaDefinition(
    schema_version="planning-action-objective-v1",
    json_schema={
        "type": "object",
        "additionalProperties": False,
        "required": [
            "schema_version",
            "route_id",
            "objective",
            "target_semantics",
            "scope_constraints",
            "evidence_refs",
        ],
        "properties": {
            "schema_version": {"const": 1},
            "route_id": {"type": "string", "minLength": 1},
            "objective": {"type": "string", "minLength": 1},
            "target_semantics": {
                "enum": [
                    "GMAIL_MESSAGE",
                    "GMAIL_THREAD_REPLY",
                    "GMAIL_DRAFT",
                    "TASK",
                    "CALENDAR_EVENT",
                    "GITHUB_ISSUE",
                ]
            },
            "scope_constraints": {
                "type": "array",
                "items": {"type": "string", "minLength": 1},
            },
            "evidence_refs": {
                "type": "array",
                "items": {"type": "string", "minLength": 1},
            },
        },
    },
)


def action_objective_candidate_output_schema(
    prompt_input: Mapping[str, object],
) -> OutputSchemaDefinition:
    """Bind objective citations to evidence supplied for the current route."""

    evidence = prompt_input.get("evidence")
    if not isinstance(evidence, list):
        raise ValueError("action objective requires evidence")
    allowed_refs = sorted(
        {
            ref
            for item in evidence
            if isinstance(item, Mapping)
            for ref in (item.get("evidence_ref") or item.get("evidence_id") or item.get("id"),)
            if isinstance(ref, str) and ref
        }
    )
    schema = deepcopy(ACTION_OBJECTIVE_CANDIDATE_OUTPUT_SCHEMA.json_schema)
    properties = cast(dict[str, object], schema["properties"])
    evidence_refs = cast(dict[str, object], properties["evidence_refs"])
    evidence_refs["uniqueItems"] = True
    evidence_refs["items"] = {
        "type": "string",
        "minLength": 1,
        "enum": allowed_refs,
    }
    if not allowed_refs:
        evidence_refs["maxItems"] = 0
    return OutputSchemaDefinition(
        schema_version=ACTION_OBJECTIVE_CANDIDATE_OUTPUT_SCHEMA.schema_version,
        json_schema=schema,
    )


def draft_action_objective_per_output_route(
    output_routes: Sequence[Mapping[str, object]],
    *,
    user_request: str,
    request_intent: Mapping[str, object],
    work_analysis: Mapping[str, object] | None,
    evidence: Sequence[Mapping[str, object]],
    invoke: PlanningSemanticInvoker,
) -> tuple[ActionObjectiveCandidateV1, ...]:
    if not output_routes:
        raise ValueError("ACTION planning requires at least one output route")
    result: list[ActionObjectiveCandidateV1] = []
    allowed_refs = {
        ref
        for item in evidence
        for ref in (item.get("evidence_ref") or item.get("evidence_id") or item.get("id"),)
        if isinstance(ref, str) and ref
    }
    deterministic_evidence_refs = [
        ref
        for item in evidence
        for ref in (item.get("evidence_ref") or item.get("evidence_id") or item.get("id"),)
        if isinstance(ref, str) and ref
    ]
    seen: set[str] = set()
    for route in output_routes:
        route_id = route.get("route_id")
        if not isinstance(route_id, str) or not route_id or route_id in seen:
            raise ValueError("output route_id must be unique and non-empty")
        seen.add(route_id)
        candidate: Mapping[str, object] | None = _deterministic_create_objective(
            route=route,
            request_intent=request_intent,
        )
        if candidate is not None:
            candidate = {
                **candidate,
                "evidence_refs": list(dict.fromkeys(deterministic_evidence_refs)),
            }
        if candidate is None:
            prompt_input: dict[str, object] = {
                "user_request": user_request,
                "request_intent": dict(request_intent),
                "output_route": dict(route),
                "evidence": [dict(item) for item in evidence],
            }
            if work_analysis is not None:
                prompt_input["work_analysis"] = dict(work_analysis)
            candidate = invoke(PROMPT_ID, prompt_input)
        objective = candidate.get("objective")
        target_semantics = candidate.get("target_semantics")
        scope_constraints = candidate.get("scope_constraints")
        refs = candidate.get("evidence_refs", [])
        if candidate.get("schema_version") != 1:
            raise ValueError("objective candidate requires schema_version 1")
        if candidate.get("route_id") != route_id or not isinstance(objective, str) or not objective:
            raise ValueError("objective candidate escaped its frozen output route")
        if not isinstance(target_semantics, str) or not _matches_route_semantics(
            route=route,
            target_semantics=target_semantics,
        ):
            raise ValueError("objective candidate target_semantics does not match its route")
        if not isinstance(scope_constraints, list) or not all(
            isinstance(item, str) and item for item in scope_constraints
        ):
            raise ValueError("objective candidate scope_constraints must be strings")
        if not isinstance(refs, list) or not all(isinstance(item, str) for item in refs):
            raise ValueError("objective candidate evidence_refs must be strings")
        if len(refs) != len(set(refs)) or not set(refs).issubset(allowed_refs):
            raise ValueError("objective candidate references unavailable evidence")
        result.append(
            {
                "schema_version": 1,
                "route_id": route_id,
                "objective": objective,
                "target_semantics": cast(ActionTargetSemanticsV1, target_semantics),
                "scope_constraints": list(scope_constraints),
                "evidence_refs": list(refs),
            }
        )
    return tuple(result)


def requires_objective_inference(
    route: Mapping[str, object], *, request_intent: Mapping[str, object]
) -> bool:
    return (
        _deterministic_create_objective(
            route=route,
            request_intent=request_intent,
        )
        is None
    )


def _deterministic_create_objective(
    *, route: Mapping[str, object], request_intent: Mapping[str, object]
) -> ActionObjectiveCandidateV1 | None:
    return (
        _deterministic_github_create_objective(
            route=route,
            request_intent=request_intent,
        )
        or _deterministic_calendar_create_objective(
            route=route,
            request_intent=request_intent,
        )
        or _deterministic_task_create_objective(
            route=route,
            request_intent=request_intent,
        )
    )


def _deterministic_github_create_objective(
    *, route: Mapping[str, object], request_intent: Mapping[str, object]
) -> ActionObjectiveCandidateV1 | None:
    route_id, goal = route.get("route_id"), request_intent.get("goal")
    ambiguity, constraints = request_intent.get("ambiguity"), request_intent.get("constraints")
    if (
        route.get("resource_type") != "GITHUB_ISSUE"
        or route.get("effect") != "CREATE"
        or route.get("selected_tool_id") != "github_create_issue"
        or request_intent.get("requested_resource_hints") != ["GITHUB_ISSUE"]
        or request_intent.get("requested_effect_hints") != ["CREATE"]
        or not isinstance(ambiguity, Mapping)
        or ambiguity.get("requires_confirmation") is not False
        or not isinstance(route_id, str)
        or not isinstance(goal, str)
        or not goal
        or not isinstance(constraints, list)
    ):
        return None
    scope: list[str] = []
    for item in constraints:
        if not isinstance(item, Mapping):
            return None
        field, value = item.get("field"), item.get("value")
        if not isinstance(field, str) or not isinstance(value, str):
            return None
        scope.append(f"{field}: {value}")
    return {
        "schema_version": 1,
        "route_id": route_id,
        "objective": goal,
        "target_semantics": "GITHUB_ISSUE",
        "scope_constraints": scope,
        "evidence_refs": [],
    }


def _deterministic_calendar_create_objective(
    *, route: Mapping[str, object], request_intent: Mapping[str, object]
) -> ActionObjectiveCandidateV1 | None:
    route_id = route.get("route_id")
    if (
        route.get("resource_type") != "CALENDAR_EVENT"
        or route.get("effect") != "CREATE"
        or route.get("selected_tool_id") != "calendar_create_event"
        or not isinstance(route_id, str)
        or request_intent.get("requested_resource_hints") != ["CALENDAR_EVENT"]
        or request_intent.get("requested_effect_hints") != ["CREATE"]
    ):
        return None
    ambiguity = request_intent.get("ambiguity")
    if isinstance(ambiguity, Mapping) and ambiguity.get("requires_confirmation") is True:
        return None
    constraints = request_intent.get("constraints")
    if not isinstance(constraints, Sequence) or isinstance(constraints, (str, bytes)):
        return None
    scope_constraints: list[str] = []
    for item in constraints:
        if not isinstance(item, Mapping):
            return None
        field, value = item.get("field"), item.get("value")
        if not isinstance(field, str) or not isinstance(value, str):
            return None
        scope_constraints.append(f"{field}: {value}")
    if not scope_constraints:
        return None
    return {
        "schema_version": 1,
        "route_id": route_id,
        "objective": "Create the exact calendar event specified by the validated request intent.",
        "target_semantics": "CALENDAR_EVENT",
        "scope_constraints": scope_constraints,
        "evidence_refs": [],
    }


def _deterministic_task_create_objective(
    *, route: Mapping[str, object], request_intent: Mapping[str, object]
) -> ActionObjectiveCandidateV1 | None:
    route_id = route.get("route_id")
    if (
        route.get("resource_type") != "TASK"
        or route.get("effect") != "CREATE"
        or route.get("selected_tool_id") != "tasks_create_task"
        or not isinstance(route_id, str)
        or request_intent.get("requested_resource_hints") != ["TASK"]
        or request_intent.get("requested_effect_hints") != ["CREATE"]
    ):
        return None
    payload = materialize_task_create_payload(request_intent)
    if payload is None:
        return None
    return {
        "schema_version": 1,
        "route_id": route_id,
        "objective": "Create the exact task specified by the validated request intent.",
        "target_semantics": "TASK",
        "scope_constraints": [f"{field}: {value}" for field, value in payload.items()],
        "evidence_refs": [],
    }


def _matches_route_semantics(
    *, route: Mapping[str, object], target_semantics: str
) -> bool:
    resource_type = route.get("resource_type")
    if (
        resource_type == "GMAIL_MESSAGE"
        and route.get("effect") == "SEND"
        and route.get("selected_tool_id") == "gmail_send"
    ):
        return target_semantics in {"GMAIL_MESSAGE", "GMAIL_THREAD_REPLY"}
    return target_semantics == resource_type


__all__ = [
    "ACTION_OBJECTIVE_CANDIDATE_OUTPUT_SCHEMA",
    "action_objective_candidate_output_schema",
    "draft_action_objective_per_output_route",
    "requires_objective_inference",
]
