"""Identify only existing Resource dependencies required by the request."""

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

from .contracts.request_intent import REQUEST_RESOURCE_TYPES
from .contracts.source_dependency_decision import (
    SourceDependencyCandidateV1,
    SourceDependencyDecisionCandidateV1,
)

_NONEMPTY_INFORMATION_SCHEMA = {"type": "string", "minLength": 1}

_OWNED_FACT_KINDS_BY_RESOURCE: dict[str, tuple[str, ...]] = {
    "GMAIL_THREAD": (
        "thread_identity",
        "subject",
        "participants",
        "message_history",
        "timestamps",
    ),
    "GMAIL_MESSAGE": (
        "message_identity",
        "subject",
        "sender",
        "recipients",
        "body",
        "timestamp",
        "labels",
    ),
    "GMAIL_DRAFT": (
        "draft_identity",
        "recipients",
        "subject",
        "body",
        "attachments",
    ),
    "GMAIL_ATTACHMENT": (
        "attachment_identity",
        "filename",
        "mime_type",
        "content",
    ),
    "TASK_LIST": ("task_list_identity", "task_list_title"),
    "TASK": (
        "task_identity",
        "title",
        "notes",
        "due",
        "completion_status",
        "task_list_identity",
    ),
    "CALENDAR": ("calendar_identity", "calendar_title", "calendar_metadata"),
    "CALENDAR_EVENT": (
        "event_identity",
        "title",
        "start",
        "end",
        "location",
        "description",
        "attendees",
        "status",
        "calendar_identity",
    ),
    "CALENDAR_FREEBUSY": ("calendar_identity", "busy_time_ranges"),
    "GITHUB_ISSUE": (
        "issue_identity",
        "repository_identity",
        "title",
        "body",
        "state",
        "labels",
        "assignees",
    ),
}


def resource_identity_fact_kind(resource_type: str) -> str | None:
    """Return the existing candidate metadata's own-Resource identity fact."""

    owned_fact_kinds = _OWNED_FACT_KINDS_BY_RESOURCE.get(resource_type.strip().upper())
    return None if not owned_fact_kinds else owned_fact_kinds[0]


def build_source_dependency_candidates(
    tool_catalog: SignedToolRegistry,
) -> tuple[SourceDependencyCandidateV1, ...]:
    """Project registered READ capabilities into one exact Resource candidate set."""

    known_resource_types = set(REQUEST_RESOURCE_TYPES)
    read_tool_ids_by_resource: dict[str, set[str]] = {}
    for entry in tool_catalog.entries:
        resource_type = entry.resource_type.upper()
        if resource_type not in known_resource_types:
            raise ValueError(f"registered Resource is absent from request catalog: {resource_type}")
        if entry.effect == "READ":
            read_tool_ids_by_resource.setdefault(resource_type, set()).add(entry.tool_id)
    candidates = tuple(
        SourceDependencyCandidateV1(
            resource_type=resource_type,
            read_tool_ids=sorted(read_tool_ids_by_resource[resource_type]),
            owned_fact_kinds=list(_OWNED_FACT_KINDS_BY_RESOURCE[resource_type]),
        )
        for resource_type in REQUEST_RESOURCE_TYPES
        if resource_type in read_tool_ids_by_resource
    )
    if not candidates:
        raise ValueError("source dependency selection requires a registered READ capability")
    return candidates


def build_source_dependency_output_schema(
    candidates: Sequence[SourceDependencyCandidateV1],
    *,
    require_at_least_one_source: bool = False,
) -> OutputSchemaDefinition:
    """Build the exact-set discriminated schema for source dependency decisions."""

    resource_types = [candidate["resource_type"] for candidate in candidates]
    if not resource_types or len(resource_types) != len(set(resource_types)):
        raise ValueError("source dependency candidates must be non-empty and unique")
    for candidate in candidates:
        owned_fact_kinds = candidate["owned_fact_kinds"]
        if not owned_fact_kinds or len(owned_fact_kinds) != len(set(owned_fact_kinds)):
            raise ValueError("source dependency candidates require unique owned fact kinds")
    variants: list[dict[str, object]] = [
        {
            "type": "object",
            "additionalProperties": False,
            "required": ["resource_type", "dependency"],
            "properties": {
                "resource_type": {"enum": resource_types},
                "dependency": {"const": "SOURCE_NOT_REQUIRED"},
            },
        },
        {
            "type": "object",
            "additionalProperties": False,
            "required": ["resource_type", "dependency", "required_information"],
            "properties": {
                "resource_type": {"enum": resource_types},
                "dependency": {"const": "SOURCE_REQUIRED"},
                "required_information": {
                    "type": "array",
                    "minItems": 1,
                    "maxItems": 8,
                    "uniqueItems": True,
                    "items": dict(_NONEMPTY_INFORMATION_SCHEMA),
                },
            },
        },
    ]
    exact_resource_constraints: list[dict[str, object]] = [
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
    ]
    if require_at_least_one_source:
        exact_resource_constraints.append(
            {
                "contains": {
                    "type": "object",
                    "properties": {"dependency": {"const": "SOURCE_REQUIRED"}},
                    "required": ["dependency"],
                },
                "minContains": 1,
            }
        )
    decisions_schema: dict[str, object] = {
        "type": "array",
        "minItems": len(resource_types),
        "maxItems": len(resource_types),
        "uniqueItems": True,
        "items": {"oneOf": variants},
        "allOf": exact_resource_constraints,
    }
    return OutputSchemaDefinition(
        schema_version="request-source-dependency-decision-v2",
        json_schema={
            "type": "object",
            "additionalProperties": False,
            "required": ["source_dependencies"],
            "properties": {"source_dependencies": decisions_schema},
        },
    )


def identify_source_dependencies(
    *,
    llm_runtime: StructuredInferencePort,
    requested_mode: Literal["AUTO", "LOCAL_GPU", "API_LLM"],
    prompt_ref: PromptReference,
    prompt_input: Mapping[str, object],
    goal_candidate: Mapping[str, object],
    source_candidates: Sequence[SourceDependencyCandidateV1],
    require_at_least_one_source: bool = False,
    candidate_output: object | None = None,
    failure_record: Mapping[str, object] | None = None,
) -> SourceDependencyDecisionCandidateV1:
    """Infer source dependencies without taking output-effect authority."""

    base_projection = {
        **prompt_input,
        "goal_candidate": dict(goal_candidate),
        "source_candidates": [deepcopy(candidate) for candidate in source_candidates],
    }
    inference_input: Mapping[str, object] = base_projection
    if candidate_output is not None or failure_record is not None:
        if candidate_output is None or failure_record is None:
            raise ValueError("source dependency revision requires candidate and failure record")
        inference_input = {
            "base_projection": base_projection,
            "candidate_output": candidate_output,
            "failure_record": dict(failure_record),
        }
    result = llm_runtime.infer(
        requested_mode,
        prompt_ref,
        inference_input,
        build_source_dependency_output_schema(
            source_candidates,
            require_at_least_one_source=require_at_least_one_source,
        ),
    )
    return validate_source_dependency_candidate(
        result.structured_output,
        source_candidates=source_candidates,
        require_at_least_one_source=require_at_least_one_source,
    )


def validate_source_dependency_candidate(
    value: object,
    *,
    source_candidates: Sequence[SourceDependencyCandidateV1],
    require_at_least_one_source: bool = False,
) -> SourceDependencyDecisionCandidateV1:
    schema = build_source_dependency_output_schema(
        source_candidates,
        require_at_least_one_source=require_at_least_one_source,
    )
    errors = validate_output_schema(value, schema.json_schema)
    if errors:
        raise ValueError(f"source dependency candidate is invalid: {'; '.join(errors)}")
    root = cast(Mapping[str, object], value)
    decisions = cast(Sequence[Mapping[str, object]], root["source_dependencies"])
    expected = [candidate["resource_type"] for candidate in source_candidates]
    actual = [cast(str, decision["resource_type"]) for decision in decisions]
    if set(actual) != set(expected):
        raise ValueError("source dependency decisions must match the candidate exact set")
    for index, decision in enumerate(decisions):
        for information_index, information in enumerate(
            cast(Sequence[str], decision.get("required_information", []))
        ):
            if not any(
                not character.isspace() and character not in "[]{}" for character in information
            ):
                raise ValueError(
                    "source dependency candidate is invalid: "
                    f"$.source_dependencies[{index}].required_information"
                    f"[{information_index}] has no semantic text"
                )
    return cast(SourceDependencyDecisionCandidateV1, deepcopy(value))


__all__ = [
    "build_source_dependency_candidates",
    "build_source_dependency_output_schema",
    "identify_source_dependencies",
    "resource_identity_fact_kind",
    "validate_source_dependency_candidate",
]
