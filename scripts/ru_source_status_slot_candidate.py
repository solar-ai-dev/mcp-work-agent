"""Inactive SourceStatus slot representation; model-owned NO_FILTER is explicit.

Slots are request-local schema addresses of confirmed Resource/WorkUnit pairs,
not new semantic artifacts. No Source/WorkUnit selection or status inference is
performed here. Existing v26 normalization owns current-Run provenance checks.
"""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from typing import cast

from scripts.ru_work_bound_source_status_candidate import (
    _source_work_bindings,
    normalize_work_bound_source_statuses,
)

from google_work_agent.application.agents.request_understanding.contracts.request_intent import (
    ConstraintProvenanceSource,
    ConstraintV1,
    RequestedWorkDefinitionV1,
    ResourceResponsibilitiesV1,
)
from google_work_agent.application.agents.request_understanding.identify_source_status import (
    _llm_facing_status_values,
)
from google_work_agent.ports.llm.output_schema_validation import validate_output_schema
from google_work_agent.ports.llm.structured_inference_contracts import OutputSchemaDefinition


def source_status_slots(
    responsibilities: ResourceResponsibilitiesV1,
    requested_work: RequestedWorkDefinitionV1,
) -> dict[str, tuple[str, str]]:
    pairs = [
        (resource, unit_id)
        for resource, refs in _source_work_bindings(responsibilities, requested_work).items()
        for unit_id in refs
    ]
    return {f"slot_{index}": pair for index, pair in enumerate(pairs, start=1)}


def build_slot_source_status_schema(
    responsibilities: ResourceResponsibilitiesV1,
    requested_work: RequestedWorkDefinitionV1,
) -> OutputSchemaDefinition:
    properties: dict[str, object] = {}
    for slot, (resource, unit_id) in source_status_slots(responsibilities, requested_work).items():
        status_values = _llm_facing_status_values(resource)
        properties[slot] = {
            "description": f"source_resource_type={resource}; work_unit_id={unit_id}",
            "oneOf": [
                {
                    "type": "object",
                    "required": ["decision"],
                    "additionalProperties": False,
                    "properties": {"decision": {"const": "NO_FILTER"}},
                },
                {
                    "type": "object",
                    "required": ["decision", "predicates"],
                    "additionalProperties": False,
                    "properties": {
                        "decision": {"const": "STATUS_FILTER"},
                        "predicates": {
                            "type": "array",
                            "minItems": 1,
                            "maxItems": len(status_values),
                            "uniqueItems": True,
                            "items": {
                                "type": "object",
                                "required": ["value", "source", "source_text"],
                                "additionalProperties": False,
                                "properties": {
                                    "value": {"enum": status_values},
                                    "source": {"enum": ["USER_REQUEST", "CONFIRMATION_RESPONSE"]},
                                    "source_text": {"type": "string", "minLength": 1},
                                },
                            },
                        },
                    },
                },
            ],
        }
    return OutputSchemaDefinition(
        "request-source-status-slot-v1",
        {
            "type": "object",
            "required": ["source_status_slots"],
            "additionalProperties": False,
            "properties": {
                "source_status_slots": {
                    "type": "object",
                    "required": list(properties),
                    "additionalProperties": False,
                    "properties": properties,
                }
            },
        },
    )


def project_slot_source_statuses(
    value: object,
    *,
    responsibilities: ResourceResponsibilitiesV1,
    requested_work: RequestedWorkDefinitionV1,
) -> dict[str, object]:
    schema = build_slot_source_status_schema(responsibilities, requested_work)
    errors = validate_output_schema(value, schema.json_schema)
    if errors:
        raise ValueError(f"source status slots are invalid: {'; '.join(errors)}")
    decisions = cast(
        dict[str, dict[str, object]], cast(dict[str, object], value)["source_status_slots"]
    )
    statuses: list[dict[str, object]] = []
    for slot, (resource, unit_id) in source_status_slots(responsibilities, requested_work).items():
        decision = decisions[slot]
        if decision["decision"] == "NO_FILTER":
            continue
        for predicate in cast(list[dict[str, object]], decision["predicates"]):
            statuses.append(
                {
                    **deepcopy(predicate),
                    "source_resource_type": resource,
                    "work_unit_ids": [unit_id],
                }
            )
    return {"statuses": statuses}


def normalize_slot_source_statuses(
    value: object,
    *,
    responsibilities: ResourceResponsibilitiesV1,
    requested_work: RequestedWorkDefinitionV1,
    provenance_sources: Mapping[ConstraintProvenanceSource, str] | None,
) -> list[ConstraintV1]:
    return normalize_work_bound_source_statuses(
        project_slot_source_statuses(
            value, responsibilities=responsibilities, requested_work=requested_work
        ),
        responsibilities=responsibilities,
        requested_work=requested_work,
        provenance_sources=provenance_sources,
    )


def slot_source_status_instruction(instruction: str) -> str:
    """Align only the Product instruction's output shape, not its examples/rules."""
    marker = "Allowed current-Run input projection (JSON):\n"
    prefix, separator, projection = instruction.partition(marker)
    if not separator:
        raise ValueError("expected the existing assembled input projection boundary")
    replacements = {
        "`statuses`에 둔다.": "해당 slot의 `STATUS_FILTER.predicates`에 둔다.",
        "상태를 요구하지 않았다면 빈 배열을 반환한다.": (
            "상태를 요구하지 않았다면 해당 slot에서 `NO_FILTER`를 반환한다."
        ),
        "`statuses=[]`": "해당 slot은 `NO_FILTER`",
        (
            "각 status는 supplied schema가 허용한 `source_resource_type`, `value`, "
            "`source`, `source_text`를 사용한다."
        ): (
            "`source_status_slots`의 각 key는 schema description에 결속된 기존 Resource와 "
            "WorkUnit 조합이다. 각 slot에서 `NO_FILTER` 또는 `STATUS_FILTER`를 선택한다. "
            "`STATUS_FILTER.predicates`는 supplied schema가 허용한 `value`, `source`, "
            "`source_text`를 사용한다."
        ),
    }
    for before, after in replacements.items():
        if before not in prefix:
            raise ValueError(f"Product instruction shape changed: {before}")
        prefix = prefix.replace(before, after)
    return prefix + separator + projection
