"""Identify only explicit user prohibitions over runtime-supported write effects."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from copy import deepcopy
from typing import Literal, cast

from google_work_agent.ports.llm.output_schema_validation import validate_output_schema
from google_work_agent.ports.llm.structured_inference_contracts import (
    OutputSchemaDefinition,
    PromptReference,
)
from google_work_agent.ports.llm.structured_inference_port import StructuredInferencePort

from .contracts.effect_prohibition_decision import (
    EffectProhibitionCandidateV1,
    EffectProhibitionDecisionCandidateV1,
)
from .contracts.output_responsibility_decision import OutputResponsibilityCandidateV1
from .contracts.request_intent import WriteEffectValue
from .contracts.work_unit_binding import work_unit_id_schema

_WRITE_EFFECT_ORDER: tuple[WriteEffectValue, ...] = (
    "CREATE",
    "UPDATE",
    "SEND",
    "DELETE",
)


def build_effect_prohibition_candidates(
    resource_candidates: Sequence[OutputResponsibilityCandidateV1],
) -> tuple[EffectProhibitionCandidateV1, ...]:
    """Project output candidates into the one supported write-effect set."""

    supported_effects = {
        effect
        for candidate in resource_candidates
        for effect in candidate["allowed_output_effects"]
    }
    candidates = tuple(
        EffectProhibitionCandidateV1(effect=effect)
        for effect in _WRITE_EFFECT_ORDER
        if effect in supported_effects
    )
    if not candidates:
        raise ValueError("effect prohibition selection requires a supported write effect")
    return candidates


def build_effect_prohibition_output_schema(
    candidates: Sequence[EffectProhibitionCandidateV1],
    *,
    work_unit_ids: Sequence[str],
) -> OutputSchemaDefinition:
    """Build the exact-set schema for explicit prohibition decisions."""

    effects = [candidate["effect"] for candidate in candidates]
    if not effects or len(effects) != len(set(effects)):
        raise ValueError("effect prohibition candidates must be non-empty and unique")
    return OutputSchemaDefinition(
        schema_version="request-effect-prohibition-decision-v1",
        json_schema={
            "type": "object",
            "additionalProperties": False,
            "required": ["effect_prohibitions"],
            "properties": {
                "effect_prohibitions": {
                    "type": "array",
                    "minItems": len(effects),
                    "maxItems": len(effects),
                    "uniqueItems": True,
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": ["effect", "prohibition", "work_unit_ids"],
                        "properties": {
                            "effect": {"enum": effects},
                            "prohibition": {"enum": ["FORBIDDEN", "NOT_FORBIDDEN"]},
                            "work_unit_ids": work_unit_id_schema(work_unit_ids),
                        },
                    },
                    "allOf": [
                        {
                            "contains": {
                                "type": "object",
                                "properties": {"effect": {"const": effect}},
                                "required": ["effect"],
                            },
                            "minContains": 1,
                            "maxContains": 1,
                        }
                        for effect in effects
                    ],
                }
            },
        },
    )


def identify_effect_prohibitions(
    *,
    llm_runtime: StructuredInferencePort,
    requested_mode: Literal["AUTO", "LOCAL_GPU", "API_LLM"],
    prompt_ref: PromptReference,
    prompt_input: Mapping[str, object],
    goal_candidate: Mapping[str, object],
    effect_candidates: Sequence[EffectProhibitionCandidateV1],
    work_unit_ids: Sequence[str],
    candidate_output: object | None = None,
    failure_record: Mapping[str, object] | None = None,
) -> EffectProhibitionDecisionCandidateV1:
    """Infer explicit prohibitions without taking positive effect authority."""

    base_projection = {
        **prompt_input,
        "goal_candidate": dict(goal_candidate),
        "effect_candidates": [deepcopy(candidate) for candidate in effect_candidates],
    }
    inference_input: Mapping[str, object] = base_projection
    if candidate_output is not None or failure_record is not None:
        if candidate_output is None or failure_record is None:
            raise ValueError("effect prohibition revision requires candidate and failure record")
        inference_input = {
            "base_projection": base_projection,
            "candidate_output": candidate_output,
            "failure_record": dict(failure_record),
        }
    result = llm_runtime.infer(
        requested_mode,
        prompt_ref,
        inference_input,
        build_effect_prohibition_output_schema(
            effect_candidates,
            work_unit_ids=work_unit_ids,
        ),
    )
    return validate_effect_prohibition_candidate(
        result.structured_output,
        effect_candidates=effect_candidates,
        work_unit_ids=work_unit_ids,
    )


def validate_effect_prohibition_candidate(
    value: object,
    *,
    effect_candidates: Sequence[EffectProhibitionCandidateV1],
    work_unit_ids: Sequence[str],
) -> EffectProhibitionDecisionCandidateV1:
    schema = build_effect_prohibition_output_schema(
        effect_candidates,
        work_unit_ids=work_unit_ids,
    )
    errors = validate_output_schema(value, schema.json_schema)
    if errors:
        raise ValueError(f"effect prohibition candidate is invalid: {'; '.join(errors)}")
    root = cast(Mapping[str, object], value)
    decisions = cast(Sequence[Mapping[str, object]], root["effect_prohibitions"])
    expected = [candidate["effect"] for candidate in effect_candidates]
    actual = [cast(WriteEffectValue, decision["effect"]) for decision in decisions]
    if set(actual) != set(expected):
        raise ValueError("effect prohibition decisions must match the candidate exact set")
    return cast(EffectProhibitionDecisionCandidateV1, deepcopy(value))


def prohibited_effects(
    value: EffectProhibitionDecisionCandidateV1,
) -> frozenset[WriteEffectValue]:
    return frozenset(
        decision["effect"]
        for decision in value["effect_prohibitions"]
        if decision["prohibition"] == "FORBIDDEN"
    )


__all__ = [
    "build_effect_prohibition_candidates",
    "build_effect_prohibition_output_schema",
    "identify_effect_prohibitions",
    "prohibited_effects",
    "validate_effect_prohibition_candidate",
]
