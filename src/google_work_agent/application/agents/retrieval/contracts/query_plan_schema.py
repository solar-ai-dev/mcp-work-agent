"""Provider-friendly structured-output shape for RetrievalQueryPlanV2."""

from __future__ import annotations

from collections.abc import Collection, Mapping
from copy import deepcopy
from typing import cast

from google_work_agent.application.agents.retrieval.contracts.query_plan import (
    CONCEPT_LITERAL_PATTERN,
    CONCEPT_MANIFESTATION_LIMIT,
    PARTICIPANT_EMAIL_PATTERN,
    TemporalRangeConstraintV1,
)
from google_work_agent.ports.llm.structured_inference_contracts import OutputSchemaDefinition

_CONSTRAINT_KINDS = [
    "TEMPORAL_RANGE",
    "PARTICIPANT",
    "KEYWORD",
    "CONCEPT",
    "RESOURCE_REF",
    "CONTAINER_REF",
    "STATUS_SCOPE",
]
_NON_EMPTY_STRING = {"type": "string", "minLength": 1}
_LOCAL_ISO_PATTERN = (
    r"^\d{4}-\d{2}-\d{2}(?:T\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?)?$"
)

_CONSTRAINT_SCHEMA = {
    "oneOf": [
        {
            "type": "object",
            "additionalProperties": False,
            "required": ["kind", "concept", "manifestations"],
            "properties": {
                "kind": {"const": "CONCEPT"},
                "concept": _NON_EMPTY_STRING,
                "manifestations": {
                    "type": "array",
                    "minItems": 1,
                    "maxItems": CONCEPT_MANIFESTATION_LIMIT,
                    "uniqueItems": True,
                    "items": {
                        "type": "string", "minLength": 1,
                        "pattern": CONCEPT_LITERAL_PATTERN,
                    },
                },
            },
        },
        {
            "type": "object",
            "additionalProperties": False,
            "required": ["kind", "axis", "start_local", "end_local", "timezone"],
            "properties": {
                "kind": {"const": "TEMPORAL_RANGE"},
                "axis": {
                    "enum": [
                        "MESSAGE_TIME",
                        "TASK_SCHEDULED_DATE",
                        "EVENT_TIME",
                        "AVAILABILITY_WINDOW",
                    ]
                },
                "start_local": {"type": ["string", "null"], "pattern": _LOCAL_ISO_PATTERN},
                "end_local": {"type": ["string", "null"], "pattern": _LOCAL_ISO_PATTERN},
                "timezone": _NON_EMPTY_STRING,
            },
        },
        {
            "type": "object",
            "additionalProperties": False,
            "required": ["kind", "participants", "match_mode"],
            "properties": {
                "kind": {"const": "PARTICIPANT"},
                "participants": {
                    "type": "array",
                    "minItems": 1,
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": ["role", "identity"],
                        "properties": {
                            "role": {"enum": ["ANY", "SENDER", "RECIPIENT", "ATTENDEE"]},
                            "identity": {"type": "string", "pattern": PARTICIPANT_EMAIL_PATTERN},
                        },
                    },
                },
                "match_mode": {"enum": ["ANY", "ALL"]},
            },
        },
        {
            "type": "object",
            "additionalProperties": False,
            "required": ["kind", "terms", "match_mode"],
            "properties": {
                "kind": {"const": "KEYWORD"},
                "terms": {"type": "array", "minItems": 1, "items": _NON_EMPTY_STRING},
                "match_mode": {"enum": ["ANY", "ALL", "PHRASE"]},
            },
        },
        {
            "type": "object",
            "additionalProperties": False,
            "required": ["kind", "resource_refs"],
            "properties": {
                "kind": {"const": "RESOURCE_REF"},
                "resource_refs": {
                    "type": "array",
                    "minItems": 1,
                    "items": _NON_EMPTY_STRING,
                },
            },
        },
        {
            "type": "object",
            "additionalProperties": False,
            "required": ["kind", "container_refs"],
            "properties": {
                "kind": {"const": "CONTAINER_REF"},
                "container_refs": {
                    "type": "array",
                    "minItems": 1,
                    "items": _NON_EMPTY_STRING,
                },
            },
        },
        {
            "type": "object",
            "additionalProperties": False,
            "required": ["kind", "values"],
            "properties": {
                "kind": {"const": "STATUS_SCOPE"},
                "values": {
                    "type": "array",
                    "minItems": 1,
                    "items": {
                        "enum": [
                            "ANY",
                            "INCOMPLETE",
                            "COMPLETED",
                            "OPEN",
                            "CLOSED",
                            "DRAFT",
                            "SENT",
                            "CANCELLED",
                            "CONFIRMED",
                            "TENTATIVE",
                        ]
                    },
                },
            },
        },
    ]
}

_INITIAL_SEARCH_SPEC = {
    "type": "object",
    "additionalProperties": False,
    "required": ["mode", "constraints"],
    "properties": {
        "mode": {"const": "INITIAL"},
        "constraints": {"type": "array", "minItems": 1, "items": _CONSTRAINT_SCHEMA},
    },
}
_CHANGED_SEARCH_SPEC = {
    "type": "object",
    "additionalProperties": False,
    "required": ["mode", "constraint_delta"],
    "properties": {
        "mode": {"const": "CHANGED"},
        "constraint_delta": {
            "type": "object",
            "additionalProperties": False,
            "required": ["upsert_constraints", "remove_constraint_kinds"],
            "oneOf": [
                {
                    "type": "object",
                    "required": ["upsert_constraints"],
                    "properties": {
                        "upsert_constraints": {"type": "array", "minItems": 1}
                    },
                },
                {
                    "type": "object",
                    "required": ["upsert_constraints", "remove_constraint_kinds"],
                    "properties": {
                        "upsert_constraints": {"type": "array", "maxItems": 0},
                        "remove_constraint_kinds": {"type": "array", "minItems": 1},
                    }
                },
            ],
            "properties": {
                "upsert_constraints": {"type": "array", "items": _CONSTRAINT_SCHEMA},
                "remove_constraint_kinds": {
                    "type": "array",
                    "uniqueItems": True,
                    "items": {"enum": _CONSTRAINT_KINDS},
                },
            },
        },
    },
}


def _route_query_schema(
    operation: str,
    *,
    search_spec: Mapping[str, object],
    detail_candidate_ref: Mapping[str, object],
) -> dict[str, object]:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "route_id",
            "operation",
            "reason_codes",
            "search_spec",
            "detail_candidate_ref",
        ],
        "properties": {
            "route_id": _NON_EMPTY_STRING,
            "operation": {"const": operation},
            "reason_codes": {
                "type": "array",
                "minItems": 1,
                "uniqueItems": True,
                "items": _NON_EMPTY_STRING,
            },
            "search_spec": search_spec,
            "detail_candidate_ref": detail_candidate_ref,
        },
    }


_SEARCH_SPEC = {"oneOf": [_INITIAL_SEARCH_SPEC, _CHANGED_SEARCH_SPEC]}
_NULL = {"type": "null"}
_ROUTE_QUERY_SCHEMA = {
    "oneOf": [
        _route_query_schema("SEARCH", search_spec=_SEARCH_SPEC, detail_candidate_ref=_NULL),
        _route_query_schema("FREEBUSY", search_spec=_SEARCH_SPEC, detail_candidate_ref=_NULL),
        _route_query_schema("NEXT_PAGE", search_spec=_NULL, detail_candidate_ref=_NULL),
        _route_query_schema(
            "DETAIL_FETCH",
            search_spec=_NULL,
            detail_candidate_ref=_NON_EMPTY_STRING,
        ),
    ]
}

RETRIEVAL_QUERY_PLAN_V2_OUTPUT_SCHEMA = OutputSchemaDefinition(
    schema_version="retrieval-query-plan-v2",
    json_schema={
        "type": "object",
        "additionalProperties": False,
        "required": ["schema_version", "route_queries", "required_information", "retrieval_order"],
        "properties": {
            "schema_version": {"type": "integer", "enum": [2]},
            "route_queries": {
                "type": "array",
                "minItems": 1,
                "items": _ROUTE_QUERY_SCHEMA,
            },
            "required_information": {
                "type": "array",
                "minItems": 1,
                "items": _NON_EMPTY_STRING,
            },
            "retrieval_order": {
                "type": "array",
                "minItems": 1,
                "uniqueItems": True,
                "items": _NON_EMPTY_STRING,
            },
        },
    },
)


def bind_retrieval_query_plan_output_schema(
    *,
    base_schema: OutputSchemaDefinition = RETRIEVAL_QUERY_PLAN_V2_OUTPUT_SCHEMA,
    route_ids: Collection[str],
    route_status_values: Mapping[str, Collection[str]] | None = None,
    supported_constraint_kinds: Mapping[str, Collection[str]] | None = None,
    validated_resource_refs: Mapping[str, Collection[str]] | None = None,
    validated_container_refs: Mapping[str, Collection[str]] | None = None,
    detail_candidate_refs: Collection[str] = (),
    is_followup: bool = False,
    resolved_temporal_constraints: Mapping[str, TemporalRangeConstraintV1] | None = None,
    allowed_participant_identities: Collection[str] | None = None,
) -> OutputSchemaDefinition:
    """Bind planner-generated identities to values validated in the current state."""

    json_schema = deepcopy(base_schema.json_schema)
    properties = cast(dict[str, object], json_schema["properties"])
    route_queries = cast(dict[str, object], properties["route_queries"])
    retrieval_order = cast(dict[str, object], properties["retrieval_order"])
    allowed_route_ids = sorted(set(route_ids))
    retrieval_order["items"] = {"type": "string", "enum": allowed_route_ids}

    operation_templates = cast(
        list[dict[str, object]], cast(dict[str, object], route_queries["items"])["oneOf"]
    )
    bound_operations: list[dict[str, object]] = []
    for route_id in allowed_route_ids:
        for template in operation_templates:
            operation_schema = deepcopy(template)
            _bind_route_operation(
                operation_schema,
                route_id=route_id,
                is_followup=is_followup,
                detail_candidate_refs=detail_candidate_refs,
                allowed_constraint_kinds=set(
                    (supported_constraint_kinds or {}).get(route_id, _CONSTRAINT_KINDS)
                ),
                allowed_resource_refs=sorted((validated_resource_refs or {}).get(route_id, ())),
                allowed_container_refs=sorted((validated_container_refs or {}).get(route_id, ())),
                temporal_constraint=(resolved_temporal_constraints or {}).get(route_id),
                allowed_participant_identities=allowed_participant_identities,
            )
            if route_status_values is not None:
                _bind_status_scope_values(
                    operation_schema, route_status_values.get(route_id, ())
                )
            bound_operations.append(operation_schema)
    route_queries["items"] = {"oneOf": bound_operations}
    return OutputSchemaDefinition(
        schema_version=base_schema.schema_version,
        json_schema=json_schema,
    )


def _bind_status_scope_values(value: object, allowed_values: Collection[str]) -> None:
    if isinstance(value, list):
        for child in value:
            _bind_status_scope_values(child, allowed_values)
    elif isinstance(value, dict):
        properties = value.get("properties")
        if isinstance(properties, dict) and properties.get("kind") == {"const": "STATUS_SCOPE"}:
            cast(dict[str, object], properties["values"])["items"] = {
                "type": "string", "enum": sorted(allowed_values),
            }
        for child in value.values():
            _bind_status_scope_values(child, allowed_values)


def _bind_route_operation(
    operation_schema: dict[str, object], *, route_id: str, is_followup: bool,
    detail_candidate_refs: Collection[str], allowed_constraint_kinds: set[str],
    allowed_resource_refs: list[str], allowed_container_refs: list[str],
    temporal_constraint: TemporalRangeConstraintV1 | None,
    allowed_participant_identities: Collection[str] | None,
) -> None:
    operation_properties = cast(dict[str, object], operation_schema["properties"])
    if allowed_participant_identities is not None and not allowed_participant_identities:
        allowed_constraint_kinds = allowed_constraint_kinds - {"PARTICIPANT"}
    operation_properties["route_id"] = {
        "type": "string",
        "const": route_id,
    }
    operation = cast(dict[str, object], operation_properties["operation"])["const"]
    if is_followup and operation in {"SEARCH", "FREEBUSY"}:
        operation_properties["search_spec"] = deepcopy(_CHANGED_SEARCH_SPEC)
    if operation == "DETAIL_FETCH":
        candidates = sorted(set(detail_candidate_refs))
        if candidates:
            operation_properties["detail_candidate_ref"] = {
                "type": "string",
                "enum": candidates,
            }
    _bind_constraint_ref_values(
        operation_properties["search_spec"],
        allowed_constraint_kinds=allowed_constraint_kinds,
        allowed_resource_refs=allowed_resource_refs,
        allowed_container_refs=allowed_container_refs,
        temporal_constraint=temporal_constraint,
        allowed_participant_identities=allowed_participant_identities,
    )


def _bind_constraint_ref_values(
    value: object,
    *,
    allowed_constraint_kinds: set[str],
    allowed_resource_refs: list[str],
    allowed_container_refs: list[str],
    temporal_constraint: TemporalRangeConstraintV1 | None,
    allowed_participant_identities: Collection[str] | None,
) -> None:
    if isinstance(value, list):
        for item in value:
            _bind_constraint_ref_values(
                item,
                allowed_constraint_kinds=allowed_constraint_kinds,
                allowed_resource_refs=allowed_resource_refs,
                allowed_container_refs=allowed_container_refs,
                temporal_constraint=temporal_constraint,
                allowed_participant_identities=allowed_participant_identities,
            )
        return
    if not isinstance(value, dict):
        return
    options = value.get("oneOf")
    if isinstance(options, list) and allowed_constraint_kinds:
        declared_kinds = [_declared_constraint_kind(item) for item in options]
        if declared_kinds and all(kind is not None for kind in declared_kinds):
            value["oneOf"] = [
                item
                for item, kind in zip(options, declared_kinds, strict=True)
                if kind in allowed_constraint_kinds
            ]
    properties = value.get("properties")
    if isinstance(properties, dict):
        kind_schema = properties.get("kind")
        kind = kind_schema.get("const") if isinstance(kind_schema, dict) else None
        if kind == "TEMPORAL_RANGE" and temporal_constraint is not None:
            for field, resolved_value in temporal_constraint.items():
                properties[field] = {"const": resolved_value}
        if kind == "PARTICIPANT":
            participants = cast(dict[str, object], properties["participants"])
            item = cast(dict[str, object], participants["items"])
            fields = cast(dict[str, object], item["properties"])
            fields["identity"] = {
                "type": "string", "minLength": 1,
                "pattern": PARTICIPANT_EMAIL_PATTERN,
                "description": (
                    "An exact requested email or evidence-resolved email only. "
                    "Names and job titles are discovery needs, not participant identities."
                ),
            }
            if allowed_participant_identities is not None:
                cast(dict[str, object], fields["identity"])["enum"] = sorted(
                    set(allowed_participant_identities)
                )
        if kind == "RESOURCE_REF" and allowed_resource_refs:
            refs = properties.get("resource_refs")
            if isinstance(refs, dict):
                refs["items"] = {"type": "string", "enum": allowed_resource_refs}
        if kind == "CONTAINER_REF" and allowed_container_refs:
            refs = properties.get("container_refs")
            if isinstance(refs, dict):
                refs["items"] = {"type": "string", "enum": allowed_container_refs}
    for child in value.values():
        _bind_constraint_ref_values(
            child,
            allowed_constraint_kinds=allowed_constraint_kinds,
            allowed_resource_refs=allowed_resource_refs,
            allowed_container_refs=allowed_container_refs,
            temporal_constraint=temporal_constraint,
            allowed_participant_identities=allowed_participant_identities,
        )


def _declared_constraint_kind(value: object) -> str | None:
    if not isinstance(value, dict):
        return None
    properties = value.get("properties")
    if not isinstance(properties, dict):
        return None
    kind_schema = properties.get("kind")
    if not isinstance(kind_schema, dict):
        return None
    kind = kind_schema.get("const")
    return kind if isinstance(kind, str) else None
