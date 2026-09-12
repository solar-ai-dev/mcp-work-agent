"""Identify whether completion requires exhaustive collection coverage."""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from typing import Literal, cast

from google_work_agent.ports.llm.output_schema_validation import validate_output_schema
from google_work_agent.ports.llm.structured_inference_contracts import (
    OutputSchemaDefinition,
    PromptReference,
)
from google_work_agent.ports.llm.structured_inference_port import StructuredInferencePort

from .contracts.coverage_requirement_decision import (
    CoverageRequirementDecisionV1,
    normalize_coverage_requirement_constraint,
)

IDENTIFY_COVERAGE_REQUIREMENT_OUTPUT_SCHEMA = OutputSchemaDefinition(
    schema_version="request-coverage-requirement-v1",
    json_schema={
        "type": "object",
        "additionalProperties": False,
        "required": ["coverage_requirement"],
        "properties": {
            "coverage_requirement": {
                "type": "array",
                "maxItems": 1,
                "uniqueItems": True,
                "items": {"const": "EXHAUSTIVE"},
            }
        },
    },
)


def identify_coverage_requirement(
    *,
    llm_runtime: StructuredInferencePort,
    requested_mode: Literal["AUTO", "LOCAL_GPU", "API_LLM"],
    prompt_ref: PromptReference,
    prompt_input: Mapping[str, object],
    goal_candidate: Mapping[str, object],
) -> CoverageRequirementDecisionV1:
    """Classify only whether the requested collection must be fully covered."""

    result = llm_runtime.infer(
        requested_mode,
        prompt_ref,
        {
            "user_request": prompt_input["user_request"],
            "goal": goal_candidate["goal"],
            "completion_conditions": deepcopy(goal_candidate["completion_conditions"]),
        },
        IDENTIFY_COVERAGE_REQUIREMENT_OUTPUT_SCHEMA,
    )
    return validate_coverage_requirement_decision(result.structured_output)


def validate_coverage_requirement_decision(
    value: object,
) -> CoverageRequirementDecisionV1:
    errors = validate_output_schema(
        value,
        IDENTIFY_COVERAGE_REQUIREMENT_OUTPUT_SCHEMA.json_schema,
    )
    if errors:
        raise ValueError(f"coverage requirement candidate is invalid: {'; '.join(errors)}")
    return cast(CoverageRequirementDecisionV1, deepcopy(value))


__all__ = [
    "IDENTIFY_COVERAGE_REQUIREMENT_OUTPUT_SCHEMA",
    "identify_coverage_requirement",
    "normalize_coverage_requirement_constraint",
    "validate_coverage_requirement_decision",
]
