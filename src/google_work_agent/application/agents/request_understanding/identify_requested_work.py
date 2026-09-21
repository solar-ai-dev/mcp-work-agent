"""Identify user-observable work boundaries before other RU semantics."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from copy import deepcopy
from typing import Literal, cast

from google_work_agent.application.agents.request_understanding.contracts.request_intent import (
    ConstraintProvenanceV1,
    RequestedWorkDefinitionV1,
    RequestedWorkUnitV1,
)
from google_work_agent.ports.llm.output_schema_validation import validate_output_schema
from google_work_agent.ports.llm.structured_inference_contracts import (
    OutputSchemaDefinition,
    PromptReference,
)
from google_work_agent.ports.llm.structured_inference_port import StructuredInferencePort

REQUESTED_WORK_OUTPUT_SCHEMA = OutputSchemaDefinition(
    schema_version="requested-work-boundaries-v1",
    json_schema={
        "type": "object",
        "additionalProperties": False,
        "required": ["schema_version", "work_units"],
        "properties": {
            "schema_version": {"const": 1},
            "work_units": {
                "type": "array",
                "minItems": 1,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["request_spans"],
                    "properties": {
                        "request_spans": {
                            "type": "array",
                            "minItems": 1,
                            "uniqueItems": True,
                            "items": {"type": "string", "minLength": 1},
                        }
                    },
                },
            },
        },
    },
)


def identify_requested_work(
    *,
    llm_runtime: StructuredInferencePort,
    requested_mode: Literal["AUTO", "LOCAL_GPU", "API_LLM"],
    prompt_ref: PromptReference,
    user_request: str,
    candidate_output: object | None = None,
    failure_record: Mapping[str, object] | None = None,
) -> RequestedWorkDefinitionV1:
    base_projection: dict[str, object] = {"user_request": user_request}
    prompt_input: Mapping[str, object] = base_projection
    if candidate_output is not None or failure_record is not None:
        if candidate_output is None or failure_record is None:
            raise ValueError("requested work revision requires candidate and failure record")
        prompt_input = {
            "base_projection": base_projection,
            "candidate_output": candidate_output,
            "failure_record": dict(failure_record),
        }
    result = llm_runtime.infer(
        requested_mode,
        prompt_ref,
        prompt_input,
        REQUESTED_WORK_OUTPUT_SCHEMA,
    )
    return validate_requested_work_candidate(
        result.structured_output,
        user_request=user_request,
    )


def validate_requested_work_candidate(
    value: object,
    *,
    user_request: str,
) -> RequestedWorkDefinitionV1:
    errors = validate_output_schema(value, REQUESTED_WORK_OUTPUT_SCHEMA.json_schema)
    if errors:
        raise ValueError(f"requested work candidate is invalid: {'; '.join(errors)}")
    root = cast(Mapping[str, object], value)
    raw_units = cast(Sequence[Mapping[str, object]], root["work_units"])
    positioned: list[tuple[int, int, list[ConstraintProvenanceV1]]] = []
    occupied: list[tuple[int, int]] = []
    for unit_index, raw_unit in enumerate(raw_units):
        spans = cast(Sequence[str], raw_unit["request_spans"])
        provenance: list[ConstraintProvenanceV1] = []
        for span_index, span in enumerate(spans):
            start = user_request.find(span)
            if start < 0 or user_request.find(span, start + 1) >= 0:
                raise ValueError(
                    "requested work span must bind exactly once to current user request: "
                    f"work_units[{unit_index}].request_spans[{span_index}]"
                )
            end = start + len(span)
            if any(
                start < existing_end and existing_start < end
                for existing_start, existing_end in occupied
            ):
                raise ValueError("requested work spans must not overlap across WorkUnits")
            occupied.append((start, end))
            provenance.append(
                {
                    "source": "USER_REQUEST",
                    "start_offset": start,
                    "end_offset": end,
                    "source_text": span,
                }
            )
        positioned.append(
            (
                min(item["start_offset"] for item in provenance),
                unit_index,
                provenance,
            )
        )
    positioned.sort(key=lambda item: (item[0], item[1]))
    work_units: list[RequestedWorkUnitV1] = [
        {
            "unit_id": f"work-{index}",
            "request_provenance": deepcopy(provenance),
        }
        for index, (_, _, provenance) in enumerate(positioned, start=1)
    ]
    return {"work_units": work_units, "work_relations": []}


def work_unit_ids(requested_work: RequestedWorkDefinitionV1) -> tuple[str, ...]:
    return tuple(unit["unit_id"] for unit in requested_work["work_units"])


__all__ = [
    "REQUESTED_WORK_OUTPUT_SCHEMA",
    "identify_requested_work",
    "validate_requested_work_candidate",
    "work_unit_ids",
]
