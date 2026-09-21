"""Identify source status after source/output responsibilities are fixed."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Literal, cast

from google_work_agent.application.agents.request_understanding.contracts.request_intent import (
    SOURCE_STATUS_VALUES_BY_RESOURCE,
    ConstraintProvenanceSource,
    ConstraintV1,
    RequestGoalSemanticValidationError,
    ResourceResponsibilitiesV1,
)
from google_work_agent.ports.llm.output_schema_validation import validate_output_schema
from google_work_agent.ports.llm.structured_inference_contracts import (
    OutputSchemaDefinition,
    PromptReference,
)
from google_work_agent.ports.llm.structured_inference_port import StructuredInferencePort

_INTRINSIC_SOURCE_STATUSES: dict[str, frozenset[str]] = {
    "GMAIL_DRAFT": frozenset({"DRAFT"}),
}


def _llm_facing_status_values(resource_type: str) -> list[str]:
    return sorted(
        value
        for value in SOURCE_STATUS_VALUES_BY_RESOURCE.get(resource_type, frozenset())
        if value != "ANY"
        and value not in _INTRINSIC_SOURCE_STATUSES.get(resource_type, frozenset())
    )


def build_identify_source_status_output_schema(
    responsibilities: ResourceResponsibilitiesV1,
) -> OutputSchemaDefinition:
    """Restrict each model-owned status to an already confirmed source type."""

    source_types = list(
        dict.fromkeys(
            source["resource_type"]
            for source in responsibilities["source_reads"]
            if _llm_facing_status_values(source["resource_type"])
        )
    )
    binding_schemas = [
        {
            "type": "object",
            "required": ["value", "source_resource_type", "source", "source_text"],
            "additionalProperties": False,
            "properties": {
                "value": {
                    "enum": _llm_facing_status_values(resource_type)
                },
                "source_resource_type": {"const": resource_type},
                "source": {"enum": ["USER_REQUEST", "CONFIRMATION_RESPONSE"]},
                "source_text": {"type": "string", "minLength": 1},
            },
        }
        for resource_type in source_types
    ]
    item_schema: dict[str, object]
    if not binding_schemas:
        item_schema = {"type": "object", "additionalProperties": False}
    elif len(binding_schemas) == 1:
        item_schema = binding_schemas[0]
    else:
        item_schema = {"oneOf": binding_schemas}
    return OutputSchemaDefinition(
        schema_version="request-source-status-v2",
        json_schema={
            "type": "object",
            "required": ["statuses"],
            "additionalProperties": False,
            "properties": {
                "statuses": {
                    "type": "array",
                    "maxItems": len(source_types),
                    "uniqueItems": True,
                    "items": item_schema,
                }
            },
        },
    )


def identify_source_status(
    *,
    llm_runtime: StructuredInferencePort,
    requested_mode: Literal["AUTO", "LOCAL_GPU", "API_LLM"],
    prompt_ref: PromptReference,
    prompt_input: Mapping[str, object],
    goal_candidate: Mapping[str, object],
    responsibilities: ResourceResponsibilitiesV1,
    candidate_output: object | None = None,
    failure_record: Mapping[str, object] | None = None,
) -> object:
    """Run the source-status-only structured inference."""

    source_types = list(
        dict.fromkeys(source["resource_type"] for source in responsibilities["source_reads"])
    )
    if not any(_llm_facing_status_values(resource_type) for resource_type in source_types):
        return {"statuses": []}
    base_projection: dict[str, object] = {
        "user_request": prompt_input["user_request"],
        "selected_resource_refs": prompt_input["selected_resource_refs"],
        "goal_candidate": dict(goal_candidate),
        "source_reads": list(responsibilities["source_reads"]),
        "outputs": list(responsibilities["outputs"]),
        "allowed_status_values": [
            {
                "resource_type": resource_type,
                "values": _llm_facing_status_values(resource_type),
            }
            for resource_type in source_types
            if _llm_facing_status_values(resource_type)
        ],
    }
    if "confirmation_response" in prompt_input:
        base_projection["confirmation_response"] = prompt_input["confirmation_response"]
    inference_input: Mapping[str, object] = base_projection
    if failure_record is not None:
        inference_input = {
            "base_projection": base_projection,
            "candidate_output": candidate_output,
            "failure_record": dict(failure_record),
        }
    result = llm_runtime.infer(
        requested_mode,
        prompt_ref,
        inference_input,
        build_identify_source_status_output_schema(responsibilities),
    )
    return result.structured_output


def normalize_source_status_constraints(
    value: object,
    *,
    responsibilities: ResourceResponsibilitiesV1,
    provenance_sources: Mapping[ConstraintProvenanceSource, str] | None,
) -> list[ConstraintV1]:
    """Bind source-status candidates to current-Run source text and source roles."""

    schema = build_identify_source_status_output_schema(responsibilities)
    errors = validate_output_schema(value, schema.json_schema)
    if errors:
        raise ValueError(f"source status candidate is invalid: {'; '.join(errors)}")
    root = cast(Mapping[str, object], value)
    bindings = cast(Sequence[Mapping[str, object]], root["statuses"])
    if not bindings:
        return []
    if provenance_sources is None:
        raise ValueError("source status requires current-Run provenance sources")
    source_resource_types = {
        source["resource_type"] for source in responsibilities["source_reads"]
    }
    normalized: list[ConstraintV1] = []
    identities: set[tuple[str, str, str, str]] = set()
    for binding in bindings:
        status = cast(str, binding["value"])
        resource_type = cast(str, binding["source_resource_type"])
        source = cast(ConstraintProvenanceSource, binding["source"])
        source_text = cast(str, binding["source_text"])
        if resource_type not in source_resource_types:
            raise ValueError("source status resource is not present in source reads")
        if status not in SOURCE_STATUS_VALUES_BY_RESOURCE.get(resource_type, frozenset()):
            raise ValueError("source status is not valid for its bound source resource")
        source_value = provenance_sources.get(source)
        if source_value is None:
            raise ValueError("source status provenance source is unavailable")
        start_offset = source_value.find(source_text)
        if start_offset < 0:
            raise RequestGoalSemanticValidationError(
                "source status text has no current-Run source binding",
                reason_code="REQUEST_STATUS_PROVENANCE_MISMATCH",
                affected_field_paths=(
                    "$.source_statuses.statuses[].source",
                    "$.source_statuses.statuses[].source_text",
                ),
            )
        identity = (status, resource_type, source, source_text)
        if identity in identities:
            raise ValueError("source status binding is duplicated")
        identities.add(identity)
        normalized.append(
            ConstraintV1(
                kind="SCOPE",
                field="status",
                value=status,
                source_resource_type=resource_type,
                provenance={
                    "source": source,
                    "start_offset": start_offset,
                    "end_offset": start_offset + len(source_text),
                    "source_text": source_text,
                },
                work_unit_ids=list(
                    dict.fromkeys(
                        unit_id
                        for responsibility in responsibilities["source_reads"]
                        if responsibility["resource_type"] == resource_type
                        for unit_id in responsibility["work_unit_ids"]
                    )
                ),
            )
        )
    return normalized


__all__ = [
    "build_identify_source_status_output_schema",
    "identify_source_status",
    "normalize_source_status_constraints",
]
