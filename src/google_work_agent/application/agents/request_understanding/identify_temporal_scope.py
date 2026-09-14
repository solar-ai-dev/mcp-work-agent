"""Classify the semantic owner of an explicit Gmail period."""

from __future__ import annotations

from typing import cast

from google_work_agent.ports.llm.output_schema_validation import validate_output_schema
from google_work_agent.ports.llm.structured_inference_contracts import (
    OutputSchemaDefinition,
    PromptReference,
)
from google_work_agent.ports.llm.structured_inference_port import StructuredInferencePort
from google_work_agent.ports.system.contracts.workflow_handoff import RequestedModeV1

from .contracts.request_goal_candidate_schema import (
    validate_normalized_request_goal_candidate,
)
from .contracts.request_intent import (
    RequestGoalCandidateV1,
)

IDENTIFY_TEMPORAL_SCOPE_OUTPUT_SCHEMA = OutputSchemaDefinition(
    schema_version="request-temporal-scope-v1",
    json_schema={
        "type": "object",
        "required": ["temporal_axis"],
        "additionalProperties": False,
        "properties": {
            "temporal_axis": {
                "enum": ["MESSAGE_TIME", "EVENT_TIME"],
                "description": (
                    "MESSAGE_TIME only when the period limits mail receipt/send time; "
                    "EVENT_TIME when mail is the source for a described work or event date."
                ),
            }
        },
    },
)


def needs_temporal_scope(candidate: RequestGoalCandidateV1) -> bool:
    return (
        "READ" in candidate["requested_effect_hints"]
        and bool(
            {"GMAIL_THREAD", "GMAIL_MESSAGE"}.intersection(candidate["requested_resource_hints"])
        )
        and any(
            item["kind"] == "DATE" and item["field"] == "period"
            for item in candidate["constraints"]
        )
        and not any(
            item["kind"] == "TIME" and item["field"] == "temporal_axis"
            for item in candidate["constraints"]
        )
    )


def identify_temporal_scope(
    *,
    llm_runtime: StructuredInferencePort,
    prompt_ref: PromptReference,
    requested_mode: RequestedModeV1,
    request_text: str,
    candidate: RequestGoalCandidateV1,
) -> RequestGoalCandidateV1:
    """Add one LLM-owned temporal axis without parsing request keywords in code."""

    if not needs_temporal_scope(candidate):
        return candidate
    periods = [
        value
        for item in candidate["constraints"]
        if item["kind"] == "DATE" and item["field"] == "period"
        for value in (item["value"] if isinstance(item["value"], list) else [item["value"]])
    ]
    semantic_context = [
        item
        for item in candidate["constraints"]
        if item["field"]
        in {"search_terms", "business_concepts", "required_information", "person", "sender"}
    ]
    result = llm_runtime.infer(
        requested_mode,
        prompt_ref,
        {
            "user_request": request_text,
            "goal": candidate["goal"],
            "periods": periods,
            "semantic_context": semantic_context,
        },
        IDENTIFY_TEMPORAL_SCOPE_OUTPUT_SCHEMA,
    )
    errors = validate_output_schema(
        result.structured_output,
        IDENTIFY_TEMPORAL_SCOPE_OUTPUT_SCHEMA.json_schema,
    )
    if errors:
        raise ValueError(f"request temporal scope is invalid: {'; '.join(errors)}")
    output = cast(dict[str, str], result.structured_output)
    return validate_normalized_request_goal_candidate(
        {
            **candidate,
            "constraints": [
                *candidate["constraints"],
                {
                    "kind": "TIME",
                    "field": "temporal_axis",
                    "value": [output["temporal_axis"]],
                },
            ],
        }
    )


__all__ = [
    "IDENTIFY_TEMPORAL_SCOPE_OUTPUT_SCHEMA",
    "identify_temporal_scope",
    "needs_temporal_scope",
]
