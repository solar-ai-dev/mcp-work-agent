"""Canonical Work Analysis operation for route-scoped action necessity."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from copy import deepcopy
from typing import cast

from google_work_agent.application.agents.work_analysis.contracts.work_analysis_candidates import (
    ActionNecessityAssessmentV1,
    DuplicateConflictAssessmentV1,
)
from google_work_agent.application.agents.work_analysis.contracts.work_analysis_result import (
    RouteActionNecessityV1,
    WorkFactV1,
)
from google_work_agent.ports.llm.output_schema_validation import validate_output_schema
from google_work_agent.ports.llm.structured_inference_contracts import (
    OutputSchemaDefinition,
    PromptReference,
)
from google_work_agent.ports.llm.structured_inference_port import StructuredInferencePort
from google_work_agent.ports.system.contracts.workflow_handoff import RequestedModeV1

ACTION_NECESSITY_OUTPUT_SCHEMA = OutputSchemaDefinition(
    schema_version="action-necessity-v1",
    json_schema={
        "type": "object",
        "required": ["route_assessments"],
        "additionalProperties": False,
        "properties": {
            "route_assessments": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": [
                        "route_id",
                        "status",
                        "reason",
                        "evidence_refs",
                        "candidate_refs",
                    ],
                    "additionalProperties": False,
                    "properties": {
                        "route_id": {"type": "string", "minLength": 1},
                        "status": {"enum": ["REQUIRED", "NOT_REQUIRED", "UNDETERMINED"]},
                        "reason": {"type": "string", "minLength": 1},
                        "evidence_refs": {
                            "type": "array",
                            "uniqueItems": True,
                            "items": {"type": "string", "minLength": 1},
                        },
                        "candidate_refs": {
                            "type": "array",
                            "uniqueItems": True,
                            "items": {"type": "string", "minLength": 1},
                        },
                    },
                },
            }
        },
    },
)


def assess_action_necessity(
    *,
    request_intent: Mapping[str, object],
    output_routes: Sequence[Mapping[str, object]],
    work_facts: Sequence[WorkFactV1],
    evidence: Sequence[Mapping[str, object]],
    source_statuses: Sequence[Mapping[str, object]],
    task_review_candidates: Sequence[Mapping[str, object]],
    duplicate_conflict_assessment: DuplicateConflictAssessmentV1,
    llm_runtime: StructuredInferencePort,
    prompt_ref: PromptReference,
    allowed_evidence_refs: set[str],
    requested_mode: RequestedModeV1,
) -> ActionNecessityAssessmentV1:
    """Decide applicability per frozen route; the route itself is never proof of necessity."""

    routes = [dict(route) for route in output_routes]
    task_routes = [route for route in routes if _is_task_create(route)]
    if len(task_routes) > 1:
        raise ValueError("Task duplicate review cannot bind multiple CREATE routes")
    if task_routes and duplicate_conflict_assessment["requested_work_status"] == ("NOT_APPLICABLE"):
        raise ValueError("Task CREATE requires the owning duplicate assessment")
    if not routes:
        return {"route_assessments": []}

    derived_task_assessment = (
        _derive_task_route_assessment(
            task_routes[0],
            duplicate_conflict_assessment=duplicate_conflict_assessment,
        )
        if task_routes
        else None
    )
    model_routes = [
        route
        for route in routes
        if derived_task_assessment is None
        or route["route_id"] != derived_task_assessment["route_id"]
    ]
    if not model_routes:
        if derived_task_assessment is None:
            raise AssertionError("a model-free route requires a derived Task assessment")
        return {"route_assessments": [derived_task_assessment]}

    candidate_refs = {
        str(item["candidate_ref"])
        for item in task_review_candidates
        if isinstance(item.get("candidate_ref"), str) and item["candidate_ref"]
    } | set(duplicate_conflict_assessment["matched_candidate_refs"])
    route_ids = {str(route["route_id"]) for route in model_routes}
    output_schema = _bound_output_schema(
        route_ids=route_ids,
        allowed_evidence_refs=allowed_evidence_refs,
        candidate_refs=candidate_refs,
    )
    result = llm_runtime.infer(
        requested_mode,
        prompt_ref,
        {
            "request_intent": dict(request_intent),
            "output_routes": model_routes,
            "work_facts": [dict(item) for item in work_facts],
            "evidence": [dict(item) for item in evidence],
            "source_statuses": [dict(item) for item in source_statuses],
            "task_review_candidates": [dict(item) for item in task_review_candidates],
            "duplicate_conflict_assessment": dict(duplicate_conflict_assessment),
        },
        output_schema,
    )
    errors = validate_output_schema(result.structured_output, output_schema.json_schema)
    if errors:
        raise ValueError(f"invalid action-necessity schema: {'; '.join(errors)}")
    root = cast(Mapping[str, object], result.structured_output)
    assessments = [
        cast(RouteActionNecessityV1, dict(item))
        for item in cast(list[Mapping[str, object]], root["route_assessments"])
    ]
    if {item["route_id"] for item in assessments} != route_ids:
        raise ValueError("action necessity must assess every model-owned output route exactly once")
    for item in assessments:
        if item["status"] == "NOT_REQUIRED" and not (
            item["evidence_refs"] or item["candidate_refs"]
        ):
            raise ValueError("NOT_REQUIRED action necessity requires a current observation")
    if task_routes and derived_task_assessment is None:
        _validate_task_route_assessment(
            next(item for item in assessments if item["route_id"] == task_routes[0]["route_id"]),
            duplicate_conflict_assessment=duplicate_conflict_assessment,
        )
    by_route = {item["route_id"]: item for item in assessments}
    if derived_task_assessment is not None:
        by_route[derived_task_assessment["route_id"]] = derived_task_assessment
    return {"route_assessments": [by_route[str(route["route_id"])] for route in routes]}


def action_necessity_llm_required(
    output_routes: Sequence[Mapping[str, object]],
    *,
    duplicate_conflict_assessment: DuplicateConflictAssessmentV1,
) -> bool:
    return any(
        not _is_task_create(route)
        or duplicate_conflict_assessment["requested_work_status"] == "NOT_SATISFIED"
        for route in output_routes
    )


def _derive_task_route_assessment(
    route: Mapping[str, object],
    *,
    duplicate_conflict_assessment: DuplicateConflictAssessmentV1,
) -> RouteActionNecessityV1 | None:
    status = duplicate_conflict_assessment["requested_work_status"]
    route_id = str(route["route_id"])
    if status == "SATISFIED":
        return cast(
            RouteActionNecessityV1,
            {
                "route_id": route_id,
                "status": "NOT_REQUIRED",
                "reason": "REQUESTED_TASK_ALREADY_SATISFIED",
                "evidence_refs": list(duplicate_conflict_assessment["evidence_refs"]),
                "candidate_refs": list(duplicate_conflict_assessment["matched_candidate_refs"]),
            },
        )
    if status == "UNDETERMINED":
        return cast(
            RouteActionNecessityV1,
            {
                "route_id": route_id,
                "status": "UNDETERMINED",
                "reason": duplicate_conflict_assessment["requested_work_reason"]
                or "TASK_DUPLICATE_REVIEW_UNDETERMINED",
                "evidence_refs": list(duplicate_conflict_assessment["evidence_refs"]),
                "candidate_refs": list(duplicate_conflict_assessment["matched_candidate_refs"]),
            },
        )
    return None


def _validate_task_route_assessment(
    assessment: RouteActionNecessityV1,
    *,
    duplicate_conflict_assessment: DuplicateConflictAssessmentV1,
) -> None:
    status = duplicate_conflict_assessment["requested_work_status"]
    if status == "UNDETERMINED" and assessment["status"] != "UNDETERMINED":
        raise ValueError("undetermined Task duplicate review cannot produce a final necessity")
    if status == "SATISFIED" and assessment["status"] == "REQUIRED":
        matched = set(duplicate_conflict_assessment["matched_candidate_refs"])
        if not matched or not matched.intersection(assessment["candidate_refs"]):
            raise ValueError("Task duplicate override must cite the matched candidate")


def _is_task_create(route: Mapping[str, object]) -> bool:
    return route.get("resource_type") == "TASK" and route.get("effect") == "CREATE"


def _bound_output_schema(
    *,
    route_ids: set[str],
    allowed_evidence_refs: set[str],
    candidate_refs: set[str],
) -> OutputSchemaDefinition:
    schema = deepcopy(ACTION_NECESSITY_OUTPUT_SCHEMA.json_schema)
    properties = cast(dict[str, object], schema["properties"])
    assessments = cast(dict[str, object], properties["route_assessments"])
    assessments["minItems"] = len(route_ids)
    assessments["maxItems"] = len(route_ids)
    item = cast(dict[str, object], assessments["items"])
    item_properties = cast(dict[str, object], item["properties"])
    item_properties["route_id"] = {"type": "string", "enum": sorted(route_ids)}
    item_properties["evidence_refs"] = {
        "type": "array",
        "uniqueItems": True,
        "items": {"type": "string", "enum": sorted(allowed_evidence_refs)},
    }
    item_properties["candidate_refs"] = {
        "type": "array",
        "uniqueItems": True,
        "items": {"type": "string", "enum": sorted(candidate_refs)},
    }
    return OutputSchemaDefinition(
        schema_version=ACTION_NECESSITY_OUTPUT_SCHEMA.schema_version,
        json_schema=schema,
    )


__all__ = [
    "ACTION_NECESSITY_OUTPUT_SCHEMA",
    "action_necessity_llm_required",
    "assess_action_necessity",
]
