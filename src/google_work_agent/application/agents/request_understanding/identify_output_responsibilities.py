"""Identify only requested external Resource write responsibilities."""

from __future__ import annotations

from collections.abc import Collection, Mapping, Sequence
from copy import deepcopy
from typing import Literal, cast

from google_work_agent.application.tool_registry.signed_tool_registry import SignedToolRegistry
from google_work_agent.ports.llm.output_schema_validation import validate_output_schema
from google_work_agent.ports.llm.structured_inference_contracts import (
    OutputSchemaDefinition,
    PromptReference,
)
from google_work_agent.ports.llm.structured_inference_port import StructuredInferencePort

from .contracts.effect_prohibition_decision import EffectProhibitionDecisionCandidateV1
from .contracts.output_responsibility_decision import (
    OutputResponsibilityCandidateV1,
    OutputResponsibilityDecisionCandidateV1,
)
from .contracts.request_intent import (
    REQUEST_RESOURCE_TYPES,
    WRITE_EFFECT_RESOURCE_TYPES,
    RequestGoalSemanticValidationError,
    WriteEffectValue,
)
from .identify_effect_prohibitions import prohibited_effects as resolve_prohibited_effects

_WRITE_EFFECT_ORDER: tuple[WriteEffectValue, ...] = (
    "CREATE",
    "UPDATE",
    "SEND",
    "DELETE",
)


class ProhibitedOutputResponsibilityDecisionError(RequestGoalSemanticValidationError):
    """Carry a prohibited output decision into the bounded revision path."""

    def __init__(self, *, candidate_output: object, affected_field_paths: Sequence[str]) -> None:
        super().__init__(
            "output responsibility selects an explicitly prohibited effect",
            reason_code="REQUEST_PROHIBITED_OUTPUT_EFFECT_SELECTED",
            affected_field_paths=affected_field_paths,
        )
        self.candidate_output = deepcopy(candidate_output)


def build_output_responsibility_candidates(
    tool_catalog: SignedToolRegistry,
) -> tuple[OutputResponsibilityCandidateV1, ...]:
    """Project registered write capabilities into one exact Resource candidate set."""

    known_resource_types = set(REQUEST_RESOURCE_TYPES)
    effects_by_resource: dict[str, set[WriteEffectValue]] = {}
    for entry in tool_catalog.entries:
        resource_type = entry.resource_type.upper()
        if resource_type not in known_resource_types:
            raise ValueError(f"registered Resource is absent from request catalog: {resource_type}")
        if entry.effect == "READ":
            continue
        allowed_resource_types = WRITE_EFFECT_RESOURCE_TYPES.get(entry.effect)
        if allowed_resource_types is None or resource_type not in allowed_resource_types:
            raise ValueError(
                "registered Resource/effect is absent from Request Understanding authority: "
                f"{resource_type}/{entry.effect}"
            )
        effects_by_resource.setdefault(resource_type, set()).add(
            cast(WriteEffectValue, entry.effect)
        )
    candidates = tuple(
        OutputResponsibilityCandidateV1(
            resource_type=resource_type,
            allowed_output_effects=[
                effect
                for effect in _WRITE_EFFECT_ORDER
                if effect in effects_by_resource.get(resource_type, set())
            ],
        )
        for resource_type in REQUEST_RESOURCE_TYPES
        if resource_type in effects_by_resource
    )
    if not candidates:
        raise ValueError("output responsibility selection requires a registered write capability")
    return candidates


def build_output_responsibility_output_schema(
    candidates: Sequence[OutputResponsibilityCandidateV1],
    *,
    prohibited_effects: Collection[WriteEffectValue] = (),
) -> OutputSchemaDefinition:
    """Build the exact-set schema with per-Resource bounded effect choices."""

    resource_types = [candidate["resource_type"] for candidate in candidates]
    if not resource_types or len(resource_types) != len(set(resource_types)):
        raise ValueError("output responsibility candidates must be non-empty and unique")
    prohibited = set(prohibited_effects)
    allowed_by_resource = {
        candidate["resource_type"]: [
            effect for effect in candidate["allowed_output_effects"] if effect not in prohibited
        ]
        for candidate in candidates
    }
    decisions_schema: dict[str, object] = {
        "type": "array",
        "minItems": len(resource_types),
        "maxItems": len(resource_types),
        "uniqueItems": True,
        "items": {
            "type": "object",
            "additionalProperties": False,
            "required": ["resource_type", "effect"],
            "properties": {
                "resource_type": {"enum": resource_types},
                "effect": {
                    "enum": [
                        "NONE",
                        *[
                            effect
                            for effect in _WRITE_EFFECT_ORDER
                            if any(effect in effects for effects in allowed_by_resource.values())
                        ],
                    ]
                },
            },
            "allOf": [
                {
                    "if": {
                        "properties": {"resource_type": {"const": resource_type}},
                        "required": ["resource_type"],
                    },
                    "then": {
                        "properties": {
                            "effect": {"enum": ["NONE", *allowed_by_resource[resource_type]]}
                        }
                    },
                }
                for resource_type in resource_types
            ],
        },
        "allOf": [
            {
                "contains": {
                    "type": "object",
                    "properties": {"resource_type": {"const": resource_type}},
                    "required": ["resource_type"],
                },
                "minContains": 1,
                "maxContains": 1,
            }
            for resource_type in resource_types
        ],
    }
    return OutputSchemaDefinition(
        schema_version="request-output-responsibility-decision-v1",
        json_schema={
            "type": "object",
            "additionalProperties": False,
            "required": ["output_responsibilities"],
            "properties": {"output_responsibilities": decisions_schema},
        },
    )


def identify_output_responsibilities(
    *,
    llm_runtime: StructuredInferencePort,
    requested_mode: Literal["AUTO", "LOCAL_GPU", "API_LLM"],
    prompt_ref: PromptReference,
    prompt_input: Mapping[str, object],
    goal_candidate: Mapping[str, object],
    output_candidates: Sequence[OutputResponsibilityCandidateV1],
    effect_prohibitions: EffectProhibitionDecisionCandidateV1,
    candidate_output: object | None = None,
    failure_record: Mapping[str, object] | None = None,
) -> OutputResponsibilityDecisionCandidateV1:
    """Infer requested outputs without taking source dependency authority."""

    base_projection = {
        **prompt_input,
        "goal_candidate": dict(goal_candidate),
        "output_candidates": [deepcopy(candidate) for candidate in output_candidates],
        "effect_prohibitions": deepcopy(effect_prohibitions["effect_prohibitions"]),
    }
    inference_input: Mapping[str, object] = base_projection
    if candidate_output is not None or failure_record is not None:
        if candidate_output is None or failure_record is None:
            raise ValueError("output responsibility revision requires candidate and failure record")
        inference_input = {
            "base_projection": base_projection,
            "candidate_output": candidate_output,
            "failure_record": dict(failure_record),
        }
    prohibited = resolve_prohibited_effects(effect_prohibitions)
    result = llm_runtime.infer(
        requested_mode,
        prompt_ref,
        inference_input,
        build_output_responsibility_output_schema(
            output_candidates,
            prohibited_effects=prohibited,
        ),
    )
    return validate_output_responsibility_candidate(
        result.structured_output,
        output_candidates=output_candidates,
        prohibited_effects=prohibited,
    )


def validate_output_responsibility_candidate(
    value: object,
    *,
    output_candidates: Sequence[OutputResponsibilityCandidateV1],
    prohibited_effects: Collection[WriteEffectValue] = (),
) -> OutputResponsibilityDecisionCandidateV1:
    conflict_paths = _prohibited_effect_paths(value, prohibited_effects=prohibited_effects)
    if conflict_paths:
        raise ProhibitedOutputResponsibilityDecisionError(
            candidate_output=value,
            affected_field_paths=conflict_paths,
        )
    schema = build_output_responsibility_output_schema(
        output_candidates,
        prohibited_effects=prohibited_effects,
    )
    errors = validate_output_schema(value, schema.json_schema)
    if errors:
        raise ValueError(f"output responsibility candidate is invalid: {'; '.join(errors)}")
    root = cast(Mapping[str, object], value)
    decisions = cast(Sequence[Mapping[str, object]], root["output_responsibilities"])
    expected = [candidate["resource_type"] for candidate in output_candidates]
    actual = [cast(str, decision["resource_type"]) for decision in decisions]
    if set(actual) != set(expected):
        raise ValueError("output responsibility decisions must match the candidate exact set")
    return cast(OutputResponsibilityDecisionCandidateV1, deepcopy(value))


def _prohibited_effect_paths(
    value: object,
    *,
    prohibited_effects: Collection[WriteEffectValue],
) -> tuple[str, ...]:
    prohibited = set(prohibited_effects)
    if not prohibited or not isinstance(value, Mapping):
        return ()
    raw_decisions = value.get("output_responsibilities")
    if not isinstance(raw_decisions, Sequence) or isinstance(raw_decisions, (str, bytes)):
        return ()
    return tuple(
        f"$.output_responsibilities[{index}].effect"
        for index, decision in enumerate(raw_decisions)
        if isinstance(decision, Mapping) and decision.get("effect") in prohibited
    )


__all__ = [
    "ProhibitedOutputResponsibilityDecisionError",
    "build_output_responsibility_candidates",
    "build_output_responsibility_output_schema",
    "identify_output_responsibilities",
    "validate_output_responsibility_candidate",
]
