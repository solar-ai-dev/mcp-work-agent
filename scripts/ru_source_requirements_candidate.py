"""Inactive Source representation candidate: keep requirement ownership within a Resource.

This module performs no inference, activation or Provider I/O. The current Resource
exact set remains intact; requirement groups project into existing V3 Source items.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from copy import deepcopy
from typing import Any, NotRequired, TypedDict, cast

from google_work_agent.application.agents.request_understanding import (
    identify_source_dependencies as source_ops,
)
from google_work_agent.application.agents.request_understanding import (
    merge_resource_responsibilities as merge_ops,
)
from google_work_agent.application.agents.request_understanding.contracts import (
    output_responsibility_decision as output_contract,
)
from google_work_agent.application.agents.request_understanding.contracts import (
    request_goal_candidate_schema as goal_schema,
)
from google_work_agent.application.agents.request_understanding.contracts import (
    source_dependency_decision as source_contract,
)
from google_work_agent.application.agents.request_understanding.contracts.request_intent import (
    ResourceResponsibilitiesV1,
    TargetScopeValue,
)
from google_work_agent.ports.llm.output_schema_validation import validate_output_schema
from google_work_agent.ports.llm.structured_inference_contracts import OutputSchemaDefinition

CANDIDATE_SCHEMA_VERSION = "evaluation-source-requirements-v1"


class SourceRequirementV1(TypedDict):
    required_information: list[str]
    target_scope: TargetScopeValue
    work_unit_ids: list[str]


class SourceRequirementsDecisionV1(TypedDict):
    resource_type: str
    dependency: source_contract.SourceDependencyValue
    requirements: NotRequired[list[SourceRequirementV1]]


class SourceRequirementsCandidateV1(TypedDict):
    source_dependencies: list[SourceRequirementsDecisionV1]


def build_source_requirements_output_schema(
    candidates: Sequence[source_contract.SourceDependencyCandidateV1],
    *,
    work_unit_ids: Sequence[str],
    require_at_least_one_source: bool = False,
) -> OutputSchemaDefinition:
    """Change only the REQUIRED payload; reuse exact-set and closed WorkUnit schema."""
    product = source_ops.build_source_dependency_output_schema(
        candidates,
        work_unit_ids=work_unit_ids,
        require_at_least_one_source=require_at_least_one_source,
    )
    schema = cast(dict[str, Any], deepcopy(product.json_schema))
    decisions = schema["properties"]["source_dependencies"]
    variants = decisions["items"]["oneOf"]
    required_variants = [
        variant
        for variant in variants
        if variant["properties"]["dependency"] == {"const": "SOURCE_REQUIRED"}
    ]
    if len(required_variants) != 1:
        raise ValueError("candidate requires the current single Product REQUIRED variant")
    required = required_variants[0]
    properties = required["properties"]
    requirement_fields = ("required_information", "target_scope", "work_unit_ids")
    if set(properties) != {"resource_type", "dependency", *requirement_fields}:
        raise ValueError("Product Source payload changed; review the candidate projection")
    requirements = {
        "type": "array",
        "minItems": 1,
        "uniqueItems": True,
        "items": {
            "type": "object",
            "additionalProperties": False,
            "required": list(requirement_fields),
            "properties": {field: properties[field] for field in requirement_fields},
        },
    }
    required["required"] = ["resource_type", "dependency", "requirements"]
    required["properties"] = {
        "resource_type": properties["resource_type"],
        "dependency": properties["dependency"],
        "requirements": requirements,
    }
    return OutputSchemaDefinition(schema_version=CANDIDATE_SCHEMA_VERSION, json_schema=schema)


def validate_source_requirements_candidate(
    value: object,
    *,
    source_candidates: Sequence[source_contract.SourceDependencyCandidateV1],
    work_unit_ids: Sequence[str],
    require_at_least_one_source: bool = False,
) -> SourceRequirementsCandidateV1:
    schema = build_source_requirements_output_schema(
        source_candidates,
        work_unit_ids=work_unit_ids,
        require_at_least_one_source=require_at_least_one_source,
    )
    errors = validate_output_schema(value, schema.json_schema)
    if errors:
        raise ValueError(f"source requirements candidate is invalid: {'; '.join(errors)}")
    validated = cast(SourceRequirementsCandidateV1, deepcopy(value))
    candidates_by_resource = {item["resource_type"]: item for item in source_candidates}
    for decision in validated["source_dependencies"]:
        for product_decision in _product_decision_projections(decision):
            source_ops.validate_source_dependency_candidate(
                product_decision,
                source_candidates=(candidates_by_resource[decision["resource_type"]],),
                work_unit_ids=work_unit_ids,
            )
    return validated


def merge_source_requirements_candidate(
    *,
    source_decisions: object,
    source_candidates: Sequence[source_contract.SourceDependencyCandidateV1],
    work_unit_ids: Sequence[str],
    output_decisions: output_contract.OutputResponsibilityDecisionCandidateV2,
    output_candidates: tuple[output_contract.OutputResponsibilityCandidateV1, ...],
    require_at_least_one_source: bool = False,
) -> ResourceResponsibilitiesV1:
    """Flat-map validated requirement groups through existing Product merge/normalizer."""
    validated = validate_source_requirements_candidate(
        source_decisions,
        source_candidates=source_candidates,
        work_unit_ids=work_unit_ids,
        require_at_least_one_source=require_at_least_one_source,
    )
    candidates_by_resource = {item["resource_type"]: item for item in source_candidates}
    result = merge_ops.merge_resource_responsibilities(
        source_decisions={"source_dependencies": []},
        source_candidates=(),
        output_decisions=output_decisions,
        output_candidates=output_candidates,
    )
    for decision in validated["source_dependencies"]:
        for product_decision in _product_decision_projections(decision):
            partial = merge_ops.merge_resource_responsibilities(
                source_decisions=product_decision,
                source_candidates=(candidates_by_resource[decision["resource_type"]],),
                output_decisions={"output_responsibilities": []},
                output_candidates=(),
            )
            result["source_reads"].extend(partial["source_reads"])
    return goal_schema._validate_resource_responsibilities_shape(result)


def _product_decision_projections(
    decision: SourceRequirementsDecisionV1,
) -> list[source_contract.SourceDependencyDecisionCandidateV1]:
    base = {"resource_type": decision["resource_type"], "dependency": decision["dependency"]}
    payloads: Sequence[Mapping[str, object]] = (
        decision["requirements"] if decision["dependency"] == "SOURCE_REQUIRED" else ({},)
    )
    return [
        cast(
            source_contract.SourceDependencyDecisionCandidateV1,
            {"source_dependencies": [{**base, **payload}]},
        )
        for payload in payloads
    ]
