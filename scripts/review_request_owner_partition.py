"""Inactive one-call Review representation with artifact-owned findings.

The section, not natural-language code/description, identifies the alleged owner.
Existing v1 receipts close IDs/provenance and build evaluation-only observations;
this module neither corrects meaning nor activates a Production back-edge.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from copy import deepcopy
from pathlib import Path
from typing import Any, cast

from scripts import review_request_reconsideration_candidate as previous

from google_work_agent.application.agents.request_understanding.contracts.work_unit_binding import (
    work_unit_id_schema,
)
from google_work_agent.application.agents.review.contracts.review_findings import (
    review_inspector_output_schema,
)
from google_work_agent.ports.llm.output_schema_validation import validate_output_schema
from google_work_agent.ports.llm.structured_inference_contracts import OutputSchemaDefinition

DIMENSION = previous.DIMENSION
ROLE_PATH = (
    Path(__file__).resolve().parents[1]
    / "evaluation/prompt_candidates/review-request-owner-v2/role.md"
)
REQUEST_ONLY_ROLE_PATH = (
    Path(__file__).resolve().parents[1]
    / "evaluation/prompt_candidates/review-request-owner-v3/role.md"
)
REQUEST_FINDING_CODE = "REQUEST_INTENT_MEANING_CONFLICT"


def build_output_schema(work_unit_ids: Sequence[str]) -> OutputSchemaDefinition:
    ordinary = cast(dict[str, Any], review_inspector_output_schema(DIMENSION).json_schema)
    return OutputSchemaDefinition(
        schema_version="evaluation-review-owner-partition-v2",
        json_schema={
            "type": "object",
            "additionalProperties": False,
            "required": [
                "schema_version",
                "dimension",
                "request_intent_findings",
                "planning_findings",
            ],
            "properties": {
                "schema_version": {"const": 2},
                "dimension": {"const": DIMENSION},
                "request_intent_findings": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": ["work_unit_ids", "semantic_field_paths", "description"],
                        "properties": {
                            "work_unit_ids": work_unit_id_schema(work_unit_ids),
                            "semantic_field_paths": {
                                "type": "array",
                                "minItems": 1,
                                "uniqueItems": True,
                                "items": {"enum": list(previous.SEMANTIC_FIELD_PATHS)},
                            },
                            "description": {"type": "string", "minLength": 1, "pattern": "[가-힣]"},
                        },
                    },
                },
                "planning_findings": deepcopy(ordinary["properties"]["findings"]),
            },
        },
    )


def validate_and_project(
    value: object,
    *,
    current_intent: Mapping[str, Any],
    user_request: str,
    current_plan_ref: Mapping[str, Any],
    known_action_ids: Sequence[str] = (),
    known_route_ids: Sequence[str] = (),
    known_evidence_ids: Sequence[str] = (),
    pre_publication: bool,
) -> dict[str, Any]:
    """Validate supplied allegations, preserving v1 authority and safety limits."""
    context: dict[str, Any] = {
        "current_intent": current_intent,
        "user_request": user_request,
        "current_plan_ref": current_plan_ref,
        "known_action_ids": known_action_ids,
        "known_route_ids": known_route_ids,
        "known_evidence_ids": known_evidence_ids,
        "pre_publication": pre_publication,
    }
    root: dict[str, Any] = {"schema_version": 1, "dimension": DIMENSION, "findings": []}
    # Check provenance/current references before reading Work IDs. Empty findings
    # validate context, not the business interpretation or absence of defects.
    previous.validate_review_candidate(root, **context)
    work_ids = [unit["unit_id"] for unit in current_intent["requested_work"]["work_units"]]
    errors = validate_output_schema(value, build_output_schema(work_ids).json_schema)
    if errors:
        raise ValueError("Review partition schema is invalid: " + "; ".join(errors))
    parsed = cast(dict[str, Any], value)
    root["findings"] = [
        {
            "dimension": DIMENSION,
            "code": REQUEST_FINDING_CODE,
            "finding_kind": previous.REQUEST_SEMANTICS_ISSUE,
            **deepcopy(finding),
            "evidence_refs": [],
            "affected_action_ids": [],
            "affected_route_ids": [],
            "required_information": [],
        }
        for finding in parsed["request_intent_findings"]
    ] + deepcopy(parsed["planning_findings"])
    receipts = previous.validate_review_candidate(root, **context)
    projections = [
        projection
        for receipt in receipts
        if (
            projection := previous.build_request_reconsideration_projection(
                receipt,
                current_intent,
                user_request,
                current_plan_ref,
                pre_publication=pre_publication,
            )
        )
        is not None
    ]
    return {
        "semantic_verdict": "UNREVIEWED",
        "validated_findings": [receipt.finding for receipt in receipts],
        "candidate_projections": projections,
    }


def build_request_only_output_schema(work_unit_ids: Sequence[str]) -> OutputSchemaDefinition:
    """Reuse the exact v2 Request item; no Planning assessment is requested."""
    schema = cast(dict[str, Any], deepcopy(build_output_schema(work_unit_ids).json_schema))
    properties = cast(dict[str, Any], schema["properties"])
    properties["schema_version"] = {"const": 3}
    properties.pop("planning_findings")
    schema["required"] = ["schema_version", "dimension", "request_intent_findings"]
    return OutputSchemaDefinition(
        schema_version="evaluation-review-request-only-v3",
        json_schema=schema,
    )


def validate_request_only_and_project(value: object, **context: Any) -> dict[str, Any]:
    """Use current v1 binding without claiming to have inspected absent Plan data.

    The caller retains Plan metadata solely for local receipt compatibility; it
    is not a model input or a new Product handoff/approval authority.
    """
    previous.validate_review_candidate(
        {"schema_version": 1, "dimension": DIMENSION, "findings": []},
        **context,
    )
    intent = context["current_intent"]
    work_ids = [unit["unit_id"] for unit in intent["requested_work"]["work_units"]]
    errors = validate_output_schema(value, build_request_only_output_schema(work_ids).json_schema)
    if errors:
        raise ValueError("Request-only Review schema is invalid: " + "; ".join(errors))
    parsed = cast(dict[str, Any], value)
    result = validate_and_project(
        {
            "schema_version": 2,
            "dimension": DIMENSION,
            "request_intent_findings": deepcopy(parsed["request_intent_findings"]),
            "planning_findings": [],
        },
        **context,
    )
    return {**result, "planning_semantics": "NOT_EVALUATED"}
