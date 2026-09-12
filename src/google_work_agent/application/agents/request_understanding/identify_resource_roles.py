"""Select bounded Resource roles and normalize them to the canonical artifact."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from copy import deepcopy
from typing import Literal, cast

from google_work_agent.application.tool_registry.signed_tool_registry import SignedToolRegistry
from google_work_agent.ports.llm.output_schema_validation import validate_output_schema
from google_work_agent.ports.llm.structured_inference_contracts import (
    OutputSchemaDefinition,
    PromptReference,
)
from google_work_agent.ports.llm.structured_inference_port import StructuredInferencePort

from .contracts.request_intent import (
    REQUEST_RESOURCE_TYPES,
    WRITE_EFFECT_RESOURCE_TYPES,
    OutputResourceResponsibilityV1,
    ResourceResponsibilitiesV1,
    SourceResourceResponsibilityV1,
    WriteEffectValue,
)
from .contracts.resource_role_decision import (
    ResourceRoleCandidateV1,
    ResourceRoleDecisionCandidateV1,
    ResourceRoleValue,
)

_ROLE_ORDER: tuple[ResourceRoleValue, ...] = (
    "NONE",
    "SOURCE",
    "OUTPUT",
    "SOURCE_AND_OUTPUT",
)
_WRITE_EFFECT_ORDER: tuple[WriteEffectValue, ...] = (
    "CREATE",
    "UPDATE",
    "SEND",
    "DELETE",
)
_NONEMPTY_INFORMATION_SCHEMA = {"type": "string", "minLength": 1}


def build_resource_role_candidates(
    tool_catalog: SignedToolRegistry,
) -> tuple[ResourceRoleCandidateV1, ...]:
    """Project the signed Tool Registry into one deterministic Resource choice set."""

    read_resource_types: set[str] = set()
    registered_effects_by_resource: dict[str, set[str]] = {}
    known_resource_types = set(REQUEST_RESOURCE_TYPES)
    for entry in tool_catalog.entries:
        resource_type = entry.resource_type.upper()
        if resource_type not in known_resource_types:
            raise ValueError(f"registered Resource is absent from request catalog: {resource_type}")
        if entry.effect == "READ":
            read_resource_types.add(resource_type)
            continue
        allowed_resource_types = WRITE_EFFECT_RESOURCE_TYPES.get(entry.effect)
        if allowed_resource_types is None or resource_type not in allowed_resource_types:
            raise ValueError(
                "registered Resource/effect is absent from Request Understanding authority: "
                f"{resource_type}/{entry.effect}"
            )
        registered_effects_by_resource.setdefault(resource_type, set()).add(entry.effect)

    candidates: list[ResourceRoleCandidateV1] = []
    for resource_type in REQUEST_RESOURCE_TYPES:
        can_read = resource_type in read_resource_types
        registered_effects = registered_effects_by_resource.get(resource_type, set())
        output_effects = [
            effect
            for effect in _WRITE_EFFECT_ORDER
            if effect in registered_effects and resource_type in WRITE_EFFECT_RESOURCE_TYPES[effect]
        ]
        if not can_read and not output_effects:
            continue
        allowed_roles: list[ResourceRoleValue] = ["NONE"]
        if can_read:
            allowed_roles.append("SOURCE")
        if output_effects:
            allowed_roles.append("OUTPUT")
        if can_read and output_effects:
            allowed_roles.append("SOURCE_AND_OUTPUT")
        candidates.append(
            ResourceRoleCandidateV1(
                resource_type=resource_type,
                allowed_roles=[role for role in _ROLE_ORDER if role in allowed_roles],
                allowed_output_effects=output_effects,
            )
        )
    if not candidates:
        raise ValueError("Resource role selection requires at least one registered capability")
    return tuple(candidates)


def build_resource_role_decision_output_schema(
    candidates: Sequence[ResourceRoleCandidateV1],
) -> OutputSchemaDefinition:
    """Build the bounded role-discriminated schema for the current registry."""

    if not candidates:
        raise ValueError("Resource role candidates are required")
    resource_types = [candidate["resource_type"] for candidate in candidates]
    if len(resource_types) != len(set(resource_types)):
        raise ValueError("Resource role candidates contain duplicate Resource types")

    read_resource_types = [
        candidate["resource_type"]
        for candidate in candidates
        if "SOURCE" in candidate["allowed_roles"]
    ]
    writable_candidates = [
        candidate for candidate in candidates if candidate["allowed_output_effects"]
    ]
    role_variants: list[dict[str, object]] = [
        _decision_variant(
            role="NONE",
            resource_types=resource_types,
            required_information=False,
            output_effects_by_resource={},
        )
    ]
    if read_resource_types:
        role_variants.append(
            _decision_variant(
                role="SOURCE",
                resource_types=read_resource_types,
                required_information=True,
                output_effects_by_resource={},
            )
        )
    if writable_candidates:
        effects_by_resource = {
            candidate["resource_type"]: list(candidate["allowed_output_effects"])
            for candidate in writable_candidates
        }
        output_only_effects_by_resource = {
            resource_type: [
                effect for effect in effects if effect not in {"UPDATE", "DELETE"}
            ]
            for resource_type, effects in effects_by_resource.items()
        }
        output_only_effects_by_resource = {
            resource_type: effects
            for resource_type, effects in output_only_effects_by_resource.items()
            if effects
        }
        if output_only_effects_by_resource:
            role_variants.append(
                _decision_variant(
                    role="OUTPUT",
                    resource_types=list(output_only_effects_by_resource),
                    required_information=False,
                    output_effects_by_resource=output_only_effects_by_resource,
                )
            )
        writable_resource_types = list(effects_by_resource)
        read_and_write_resource_types = [
            resource_type
            for resource_type in writable_resource_types
            if resource_type in read_resource_types
        ]
        if read_and_write_resource_types:
            role_variants.append(
                _decision_variant(
                    role="SOURCE_AND_OUTPUT",
                    resource_types=read_and_write_resource_types,
                    required_information=True,
                    output_effects_by_resource={
                        resource_type: effects_by_resource[resource_type]
                        for resource_type in read_and_write_resource_types
                    },
                )
            )

    resource_decisions_schema: dict[str, object] = {
        "type": "array",
        "minItems": len(candidates),
        "maxItems": len(candidates),
        "uniqueItems": True,
        "items": {"oneOf": role_variants},
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
        schema_version="request-resource-role-decision-candidate-v1",
        json_schema={
            "type": "object",
            "additionalProperties": False,
            "required": ["resource_decisions"],
            "properties": {"resource_decisions": resource_decisions_schema},
        },
    )


def identify_resource_roles(
    *,
    llm_runtime: StructuredInferencePort,
    requested_mode: Literal["AUTO", "LOCAL_GPU", "API_LLM"],
    prompt_ref: PromptReference,
    prompt_input: Mapping[str, object],
    goal_candidate: Mapping[str, object],
    resource_candidates: Sequence[ResourceRoleCandidateV1],
    candidate_output: object | None = None,
    failure_record: Mapping[str, object] | None = None,
) -> tuple[ResourceRoleDecisionCandidateV1, ResourceResponsibilitiesV1]:
    """Infer only roles from the runtime-owned candidate set."""

    base_projection = {
        **prompt_input,
        "goal_candidate": dict(goal_candidate),
        "resource_candidates": [deepcopy(candidate) for candidate in resource_candidates],
    }
    inference_input: Mapping[str, object] = base_projection
    if candidate_output is not None or failure_record is not None:
        if candidate_output is None or failure_record is None:
            raise ValueError("Resource role revision requires candidate output and failure record")
        inference_input = {
            "base_projection": base_projection,
            "candidate_output": candidate_output,
            "failure_record": dict(failure_record),
        }
    result = llm_runtime.infer(
        requested_mode,
        prompt_ref,
        inference_input,
        build_resource_role_decision_output_schema(resource_candidates),
    )
    decisions = validate_resource_role_decision_candidate(
        result.structured_output,
        resource_candidates=resource_candidates,
    )
    return decisions, normalize_resource_role_decisions(
        decisions,
        resource_candidates=resource_candidates,
    )


def validate_resource_role_decision_candidate(
    value: object,
    *,
    resource_candidates: Sequence[ResourceRoleCandidateV1],
) -> ResourceRoleDecisionCandidateV1:
    schema = build_resource_role_decision_output_schema(resource_candidates)
    errors = validate_output_schema(value, schema.json_schema)
    if errors:
        raise ValueError(f"Resource role decision candidate is invalid: {'; '.join(errors)}")
    root = cast(Mapping[str, object], value)
    decisions = cast(Sequence[Mapping[str, object]], root["resource_decisions"])
    expected_resource_types = [candidate["resource_type"] for candidate in resource_candidates]
    actual_resource_types = [cast(str, decision["resource_type"]) for decision in decisions]
    if set(actual_resource_types) != set(expected_resource_types):
        raise ValueError("Resource role decisions must match the candidate exact set")
    for index, decision in enumerate(decisions):
        for information_index, information in enumerate(
            cast(Sequence[str], decision.get("required_information", []))
        ):
            if not any(
                not character.isspace() and character not in "[]{}" for character in information
            ):
                raise ValueError(
                    "Resource role decision candidate is invalid: "
                    f"$.resource_decisions[{index}].required_information"
                    f"[{information_index}] has no semantic text"
                )
    return cast(ResourceRoleDecisionCandidateV1, deepcopy(value))


def normalize_resource_role_decisions(
    value: ResourceRoleDecisionCandidateV1,
    *,
    resource_candidates: Sequence[ResourceRoleCandidateV1],
) -> ResourceResponsibilitiesV1:
    """Project the owner-local decision into the existing canonical shape."""

    decisions_by_resource = {
        decision["resource_type"]: decision for decision in value["resource_decisions"]
    }
    source_reads: list[SourceResourceResponsibilityV1] = []
    outputs: list[OutputResourceResponsibilityV1] = []
    for candidate in resource_candidates:
        decision = decisions_by_resource[candidate["resource_type"]]
        role = decision["role"]
        if role in {"SOURCE", "SOURCE_AND_OUTPUT"}:
            source_reads.append(
                SourceResourceResponsibilityV1(
                    resource_type=decision["resource_type"],
                    required_information=list(decision["required_information"]),
                )
            )
        if role in {"OUTPUT", "SOURCE_AND_OUTPUT"}:
            outputs.append(
                OutputResourceResponsibilityV1(
                    resource_type=decision["resource_type"],
                    effect=decision["effect"],
                )
            )
    return ResourceResponsibilitiesV1(source_reads=source_reads, outputs=outputs)


def _decision_variant(
    *,
    role: ResourceRoleValue,
    resource_types: Sequence[str],
    required_information: bool,
    output_effects_by_resource: Mapping[str, Sequence[WriteEffectValue]],
) -> dict[str, object]:
    properties: dict[str, object] = {
        "resource_type": {"enum": list(resource_types)},
        "role": {"const": role},
    }
    required = ["resource_type", "role"]
    if required_information:
        required.append("required_information")
        properties["required_information"] = {
            "type": "array",
            "maxItems": 8,
            "uniqueItems": True,
            "items": dict(_NONEMPTY_INFORMATION_SCHEMA),
        }
    if output_effects_by_resource:
        required.append("effect")
        properties["effect"] = {
            "enum": [
                effect
                for effect in _WRITE_EFFECT_ORDER
                if any(effect in effects for effects in output_effects_by_resource.values())
            ]
        }
    schema: dict[str, object] = {
        "type": "object",
        "additionalProperties": False,
        "required": required,
        "properties": properties,
    }
    if output_effects_by_resource:
        schema["allOf"] = [
            {
                "if": {
                    "properties": {"resource_type": {"const": resource_type}},
                    "required": ["resource_type"],
                },
                "then": {"properties": {"effect": {"enum": list(effects)}}},
            }
            for resource_type, effects in output_effects_by_resource.items()
        ]
    return schema


__all__ = [
    "build_resource_role_candidates",
    "build_resource_role_decision_output_schema",
    "identify_resource_roles",
    "normalize_resource_role_decisions",
    "validate_resource_role_decision_candidate",
]
