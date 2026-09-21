"""Canonical Work Analysis semantic operation: ``assess_information_gaps``."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from copy import deepcopy
from typing import cast

from google_work_agent.application.agents.request_understanding.contracts.request_intent import (
    RequestIntentV3,
)
from google_work_agent.application.agents.work_analysis.contracts.work_analysis_candidates import (
    InformationGapAssessmentV1,
    InformationGapConfirmationResolutionV1,
)
from google_work_agent.application.agents.work_analysis.contracts.work_analysis_result import (
    RouteActionNecessityV1,
    WorkAmbiguityV1,
    WorkFactV1,
)
from google_work_agent.ports.llm.output_schema_validation import validate_output_schema
from google_work_agent.ports.llm.structured_inference_contracts import (
    OutputSchemaDefinition,
    PromptReference,
)
from google_work_agent.ports.llm.structured_inference_port import StructuredInferencePort
from google_work_agent.ports.system.contracts.workflow_handoff import RequestedModeV1

_DISPOSITIONS = (
    "COMPLETE",
    "NEEDS_MORE_DATA",
    "NEEDS_CONFIRMATION",
    "REQUEST_RECONSIDERATION_REQUIRED",
    "ROUTE_RECONSIDERATION_REQUIRED",
    "BLOCKED",
)

ASSESS_INFORMATION_GAPS_OUTPUT_SCHEMA = OutputSchemaDefinition(
    schema_version="information-gap-assessment-v1",
    json_schema={
        "type": "object",
        "required": ["disposition", "ambiguities", "retrieval_needs", "evidence_refs"],
        "additionalProperties": False,
        "properties": {
            "disposition": {"enum": list(_DISPOSITIONS)},
            "ambiguities": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": [
                        "code",
                        "description",
                        "requires_confirmation",
                        "evidence_refs",
                    ],
                    "additionalProperties": False,
                    "properties": {
                        "code": {"type": "string", "minLength": 1},
                        "description": {"type": "string", "minLength": 1},
                        "requires_confirmation": {"type": "boolean"},
                        "evidence_refs": {
                            "type": "array",
                            "items": {"type": "string", "minLength": 1},
                        },
                    },
                },
            },
            "retrieval_needs": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": ["required_information", "reason_codes"],
                    "additionalProperties": False,
                    "properties": {
                        "required_information": {"type": "string", "minLength": 1},
                        "reason_codes": {
                            "type": "array",
                            "minItems": 1,
                            "items": {"type": "string", "minLength": 1},
                        },
                    },
                },
            },
            "evidence_refs": {
                "type": "array",
                "items": {"type": "string", "minLength": 1},
            },
            "question": {"type": "string", "minLength": 1},
            "options": {"type": "array", "items": {"type": "string", "minLength": 1}},
            "reason_codes": {
                "type": "array",
                "items": {"type": "string", "minLength": 1},
            },
        },
    },
)


def assess_information_gaps(
    *,
    request_intent: RequestIntentV3,
    work_facts: Sequence[WorkFactV1],
    evidence: list[dict[str, object]],
    llm_runtime: StructuredInferencePort,
    prompt_ref: PromptReference,
    allowed_evidence_refs: set[str],
    requested_mode: RequestedModeV1,
    confirmation_resolution: InformationGapConfirmationResolutionV1 | None = None,
    source_statuses: Sequence[Mapping[str, object]] = (),
    route_action_necessities: Sequence[RouteActionNecessityV1] = (),
) -> InformationGapAssessmentV1:
    """Identify only missing information and its legal workflow disposition."""

    prompt_input: dict[str, object] = {
        "request_intent": dict(request_intent),
        "work_facts": [dict(fact) for fact in work_facts],
        "evidence": list(evidence),
        "source_statuses": [dict(item) for item in source_statuses],
        "route_action_necessities": [dict(item) for item in route_action_necessities],
    }
    if confirmation_resolution is not None:
        prompt_input["confirmation_resolution"] = dict(confirmation_resolution)
    output_schema = _bound_output_schema(allowed_evidence_refs)

    def validate(value: object) -> object:
        errors = validate_output_schema(value, output_schema.json_schema)
        if errors:
            raise ValueError(f"invalid information-gap schema: {'; '.join(errors)}")
        root = cast(Mapping[str, object], value)
        refs = cast(list[str], root["evidence_refs"])
        if len(refs) != len(set(refs)) or not set(refs).issubset(allowed_evidence_refs):
            raise ValueError("information-gap evidence is outside current RetrievalResultV1")
        for ambiguity in cast(list[Mapping[str, object]], root["ambiguities"]):
            item_refs = cast(list[str], ambiguity["evidence_refs"])
            if len(item_refs) != len(set(item_refs)) or not set(item_refs).issubset(
                allowed_evidence_refs
            ):
                raise ValueError("ambiguity evidence is outside current RetrievalResultV1")
        disposition = root["disposition"]
        needs = cast(list[object], root["retrieval_needs"])
        reason_codes = root.get("reason_codes", [])
        if disposition == "NEEDS_MORE_DATA" and not needs:
            raise ValueError("NEEDS_MORE_DATA requires a RetrievalNeedV1")
        if disposition != "NEEDS_MORE_DATA" and needs:
            raise ValueError("retrieval needs are legal only for NEEDS_MORE_DATA")
        if disposition == "NEEDS_CONFIRMATION" and (
            not root.get("question") or not isinstance(reason_codes, list) or not reason_codes
        ):
            raise ValueError("NEEDS_CONFIRMATION requires question and reason_codes")
        if disposition == "REQUEST_RECONSIDERATION_REQUIRED" and (
            not refs or not isinstance(reason_codes, list) or not reason_codes
        ):
            raise ValueError(
                "REQUEST_RECONSIDERATION_REQUIRED requires evidence and reason_codes"
            )
        return value

    result = llm_runtime.infer(
        requested_mode,
        prompt_ref,
        prompt_input,
        output_schema,
    )
    validated = cast(Mapping[str, object], validate(result.structured_output))
    return cast(InformationGapAssessmentV1, dict(validated))


def combine_information_gap_assessment(
    *,
    assessment: InformationGapAssessmentV1,
    relation_ambiguities: Sequence[WorkAmbiguityV1],
    confirmation_resolution: InformationGapConfirmationResolutionV1 | None = None,
) -> InformationGapAssessmentV1:
    """Combine owner decisions without erasing a newly discovered user choice."""

    resolved_code = (
        confirmation_resolution["reason_code"]
        if confirmation_resolution is not None
        else None
    )
    prior = (
        confirmation_resolution["prior_ambiguities"]
        if confirmation_resolution is not None
        else []
    )
    newly_assessed = [dict(item) for item in assessment["ambiguities"]]
    new_codes = {item["code"] for item in newly_assessed}
    retained = [
        dict(item)
        for item in [*relation_ambiguities, *prior]
        if item["code"] != resolved_code and item["code"] not in new_codes
    ]
    ambiguities = [*retained, *newly_assessed]
    if assessment["disposition"] == "COMPLETE" and any(
        item["requires_confirmation"] for item in ambiguities
    ):
        requiring = next(item for item in ambiguities if item["requires_confirmation"])
        return cast(
            InformationGapAssessmentV1,
            {
                **assessment,
                "ambiguities": ambiguities,
                "disposition": "NEEDS_CONFIRMATION",
                "question": requiring["description"],
                "options": [],
                "reason_codes": [requiring["code"]],
            },
        )
    return cast(InformationGapAssessmentV1, {**assessment, "ambiguities": ambiguities})


def require_resolution_for_undetermined_action(
    *,
    assessment: InformationGapAssessmentV1,
    route_action_necessities: Sequence[RouteActionNecessityV1],
) -> InformationGapAssessmentV1:
    """Route an unresolved owning action decision before Planning consumes it."""

    if (
        not any(item["status"] == "UNDETERMINED" for item in route_action_necessities)
        or assessment["disposition"] != "COMPLETE"
    ):
        return assessment
    return cast(
        InformationGapAssessmentV1,
        {
            **assessment,
            "disposition": "NEEDS_MORE_DATA",
            "retrieval_needs": [
                {
                    "required_information": (
                        "current observations needed to determine requested action applicability"
                    ),
                    "reason_codes": ["ACTION_NECESSITY_UNDETERMINED"],
                }
            ],
            "reason_codes": ["ACTION_NECESSITY_UNDETERMINED"],
        },
    )


def _bound_output_schema(allowed_evidence_refs: set[str]) -> OutputSchemaDefinition:
    """Express current evidence and disposition invariants at the repair boundary."""

    json_schema = cast(
        dict[str, object], deepcopy(ASSESS_INFORMATION_GAPS_OUTPUT_SCHEMA.json_schema)
    )
    properties = cast(dict[str, object], json_schema["properties"])
    evidence_item = {"type": "string", "enum": sorted(allowed_evidence_refs)}
    properties["evidence_refs"] = {
        "type": "array",
        "uniqueItems": True,
        "items": evidence_item,
    }
    ambiguities = cast(dict[str, object], properties["ambiguities"])
    ambiguity = cast(dict[str, object], ambiguities["items"])
    ambiguity_properties = cast(dict[str, object], ambiguity["properties"])
    ambiguity_properties["evidence_refs"] = {
        "type": "array",
        "uniqueItems": True,
        "items": dict(evidence_item),
    }
    branches = [_disposition_schema(json_schema, disposition) for disposition in _DISPOSITIONS]
    return OutputSchemaDefinition(
        schema_version=ASSESS_INFORMATION_GAPS_OUTPUT_SCHEMA.schema_version,
        json_schema={"oneOf": branches},
    )


def _disposition_schema(base_schema: Mapping[str, object], disposition: str) -> dict[str, object]:
    """Build one complete object branch for Ollama's structured-output grammar."""

    branch = cast(dict[str, object], deepcopy(base_schema))
    properties = cast(dict[str, object], branch["properties"])
    properties["disposition"] = {"const": disposition}
    retrieval_needs = cast(dict[str, object], properties["retrieval_needs"])
    retrieval_needs["minItems" if disposition == "NEEDS_MORE_DATA" else "maxItems"] = (
        1 if disposition == "NEEDS_MORE_DATA" else 0
    )
    if disposition in {"NEEDS_CONFIRMATION", "REQUEST_RECONSIDERATION_REQUIRED"}:
        required = cast(list[str], branch["required"])
        required.append("reason_codes")
        if disposition == "NEEDS_CONFIRMATION":
            required.append("question")
            properties["question"] = {"type": "string", "minLength": 1}
        properties["reason_codes"] = {
            "type": "array",
            "minItems": 1,
            "items": {"type": "string", "minLength": 1},
        }
    if disposition == "REQUEST_RECONSIDERATION_REQUIRED":
        evidence_refs = cast(dict[str, object], properties["evidence_refs"])
        evidence_refs["minItems"] = 1
    return branch


__all__ = [
    "ASSESS_INFORMATION_GAPS_OUTPUT_SCHEMA",
    "assess_information_gaps",
    "combine_information_gap_assessment",
    "require_resolution_for_undetermined_action",
]
