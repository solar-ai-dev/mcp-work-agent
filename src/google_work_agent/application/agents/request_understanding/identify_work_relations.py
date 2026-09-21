"""Identify only dependency existence between finalized requested WorkUnits."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Literal, cast

from google_work_agent.application.agents.request_understanding.contracts.request_intent import (
    RequestedWorkDefinitionV1,
    RequestedWorkRelationKind,
    RequestedWorkRelationV1,
)
from google_work_agent.ports.llm.output_schema_validation import validate_output_schema
from google_work_agent.ports.llm.structured_inference_contracts import (
    OutputSchemaDefinition,
    PromptReference,
)
from google_work_agent.ports.llm.structured_inference_port import StructuredInferencePort


def relation_inference_required(requested_work: RequestedWorkDefinitionV1) -> bool:
    return len(requested_work["work_units"]) > 1


def relation_decision_pairs(
    requested_work: RequestedWorkDefinitionV1,
    *,
    output_responsibilities: Sequence[Mapping[str, object]],
) -> list[dict[str, str]]:
    unit_ids = [unit["unit_id"] for unit in requested_work["work_units"]]
    if not unit_ids or len(unit_ids) != len(set(unit_ids)):
        raise ValueError("WorkUnit IDs must be a non-empty closed set")
    output_units = {
        unit_id
        for item in output_responsibilities
        for unit_id in _validated_refs(item.get("work_unit_ids"), known=set(unit_ids))
    }
    return [
        {
            "source_work_unit_id": source,
            "target_work_unit_id": target,
            "allowed_relation_kind": (
                "CONSUMES_PLANNED_SPECIFICATION"
                if source in output_units
                else "CONSUMES_WORK_PRODUCT"
            ),
        }
        for source in unit_ids
        for target in unit_ids
        if source != target
    ]


def relation_decision_output_schema(
    pairs: Sequence[Mapping[str, str]],
) -> OutputSchemaDefinition:
    if not pairs:
        raise ValueError("relation decision schema requires candidate pairs")
    variants = [
        {
            "type": "object",
            "additionalProperties": False,
            "required": [
                "source_work_unit_id",
                "target_work_unit_id",
                "disposition",
            ],
            "properties": {
                "source_work_unit_id": {"const": pair["source_work_unit_id"]},
                "target_work_unit_id": {"const": pair["target_work_unit_id"]},
                "disposition": {
                    "enum": ["NONE", pair["allowed_relation_kind"]],
                },
            },
        }
        for pair in pairs
    ]
    return OutputSchemaDefinition(
        schema_version="requested-work-relation-decisions-v1",
        json_schema={
            "type": "object",
            "additionalProperties": False,
            "required": ["schema_version", "relation_decisions"],
            "properties": {
                "schema_version": {"const": 1},
                "relation_decisions": {
                    "type": "array",
                    "minItems": len(pairs),
                    "maxItems": len(pairs),
                    "uniqueItems": True,
                    "items": {"oneOf": variants},
                    "allOf": [
                        {
                            "contains": {
                                "type": "object",
                                "properties": {
                                    "source_work_unit_id": {
                                        "const": pair["source_work_unit_id"]
                                    },
                                    "target_work_unit_id": {
                                        "const": pair["target_work_unit_id"]
                                    },
                                },
                                "required": [
                                    "source_work_unit_id",
                                    "target_work_unit_id",
                                ],
                            },
                            "minContains": 1,
                            "maxContains": 1,
                        }
                        for pair in pairs
                    ],
                },
            },
        },
    )


def identify_work_relations(
    *,
    llm_runtime: StructuredInferencePort,
    requested_mode: Literal["AUTO", "LOCAL_GPU", "API_LLM"],
    prompt_ref: PromptReference,
    user_request: str,
    requested_work: RequestedWorkDefinitionV1,
    constraints: Sequence[Mapping[str, object]],
    source_responsibilities: Sequence[Mapping[str, object]],
    output_responsibilities: Sequence[Mapping[str, object]],
) -> list[RequestedWorkRelationV1]:
    if not relation_inference_required(requested_work):
        return []
    pairs = relation_decision_pairs(
        requested_work,
        output_responsibilities=output_responsibilities,
    )
    result = llm_runtime.infer(
        requested_mode,
        prompt_ref,
        {
            "user_request": user_request,
            "work_units": requested_work["work_units"],
            "constraints": list(constraints),
            "source_responsibilities": list(source_responsibilities),
            "output_responsibilities": list(output_responsibilities),
            "candidate_pairs": pairs,
        },
        relation_decision_output_schema(pairs),
    )
    return validate_relation_decisions(result.structured_output, pairs=pairs)


def validate_relation_decisions(
    value: object,
    *,
    pairs: Sequence[Mapping[str, str]],
) -> list[RequestedWorkRelationV1]:
    schema = relation_decision_output_schema(pairs)
    errors = validate_output_schema(value, schema.json_schema)
    if errors:
        raise ValueError(f"requested work relation candidate is invalid: {'; '.join(errors)}")
    root = cast(Mapping[str, object], value)
    decisions = cast(Sequence[Mapping[str, object]], root["relation_decisions"])
    allowed_by_pair = {
        (item["source_work_unit_id"], item["target_work_unit_id"]): item[
            "allowed_relation_kind"
        ]
        for item in pairs
    }
    seen: set[tuple[str, str]] = set()
    relations: list[RequestedWorkRelationV1] = []
    for index, decision in enumerate(decisions):
        source = cast(str, decision["source_work_unit_id"])
        target = cast(str, decision["target_work_unit_id"])
        disposition = cast(str, decision["disposition"])
        pair = (source, target)
        allowed = allowed_by_pair.get(pair)
        if source == target or allowed is None or pair in seen:
            raise ValueError(f"relation_decisions[{index}] pair is not exact and unique")
        seen.add(pair)
        if disposition not in {"NONE", allowed}:
            raise ValueError(f"relation_decisions[{index}] rejudges the fixed relation kind")
        if disposition != "NONE":
            relations.append(
                {
                    "source_work_unit_id": source,
                    "target_work_unit_id": target,
                    "kind": cast(RequestedWorkRelationKind, disposition),
                }
            )
    if seen != set(allowed_by_pair):
        raise ValueError("relation decisions must cover every candidate pair exactly once")
    return relations


def _validated_refs(value: object, *, known: set[str]) -> list[str]:
    if not isinstance(value, list) or not value or not all(
        isinstance(item, str) and item in known for item in value
    ):
        raise ValueError("semantic item contains invalid WorkUnit refs")
    refs = cast(list[str], value)
    if len(refs) != len(set(refs)):
        raise ValueError("semantic item contains duplicate WorkUnit refs")
    return refs


__all__ = [
    "identify_work_relations",
    "relation_decision_output_schema",
    "relation_decision_pairs",
    "relation_inference_required",
    "validate_relation_decisions",
]
