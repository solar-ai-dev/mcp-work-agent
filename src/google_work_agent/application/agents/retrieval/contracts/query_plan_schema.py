"""Provider-friendly structured-output shape for RetrievalQueryPlanV2."""

from __future__ import annotations

from collections.abc import Collection, Mapping
from copy import deepcopy
from typing import cast

from google_work_agent.application.agents.retrieval.contracts.query_plan import (
    CONCEPT_LITERAL_PATTERN,
    GMAIL_KEYWORD_LITERAL_PATTERN,
    PARTICIPANT_EMAIL_PATTERN,
    PLANNER_CONCEPT_MANIFESTATION_LIMIT,
    RetrievalOperationV2,
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
_CONSTRAINT_SLOT_BY_KIND = {kind: kind.lower() for kind in _CONSTRAINT_KINDS}
_NON_EMPTY_STRING = {"type": "string", "minLength": 1}
_LOCAL_ISO_PATTERN = r"^\d{4}-\d{2}-\d{2}(?:T\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?)?$"


def _unique_constraint_kind_guards() -> list[dict[str, object]]:
    """Keep the canonical list contract fail-closed for direct V2 consumers."""

    return [
        {
            "contains": {
                "type": "object",
                "required": ["kind"],
                "properties": {"kind": {"enum": [kind]}},
            },
            "minContains": 0,
            "maxContains": 1,
        }
        for kind in _CONSTRAINT_KINDS
    ]


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
                    "description": (
                        "One coherent search hypothesis: 1 to 3 short literal source-text terms "
                        "in the user's language. Not invented document titles or descriptions."
                    ),
                    "minItems": 1,
                    "maxItems": PLANNER_CONCEPT_MANIFESTATION_LIMIT,
                    "uniqueItems": True,
                    "items": {
                        "type": "string",
                        "minLength": 1,
                        "pattern": CONCEPT_LITERAL_PATTERN.replace(":", ":,;，；"),
                    },
                },
            },
        },
        {
            "type": "object",
            "additionalProperties": False,
            "required": ["kind", "axis", "start_local", "end_local", "timezone"],
            "if": {"properties": {"start_local": {"type": "null"}}},
            "then": {"properties": {"end_local": {"type": "string"}}},
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


def _constraint_slots_schema(*, require_one: bool) -> dict[str, object]:
    options = cast(list[dict[str, object]], _CONSTRAINT_SCHEMA["oneOf"])
    schemas_by_kind: dict[str, dict[str, object]] = {}
    for option in options:
        option_properties = cast(dict[str, object], option["properties"])
        kind_schema = cast(dict[str, object], option_properties["kind"])
        schemas_by_kind[cast(str, kind_schema["const"])] = option
    return {
        "type": "object",
        "description": (
            "At most one value per semantic constraint kind. Each key is one typed slot; "
            "omit kinds that are not part of this hypothesis."
        ),
        "additionalProperties": False,
        "minProperties": 1 if require_one else 0,
        "properties": {
            slot: deepcopy(schemas_by_kind[kind]) for kind, slot in _CONSTRAINT_SLOT_BY_KIND.items()
        },
    }


_PROVIDER_INITIAL_SEARCH_SPEC = {
    "type": "object",
    "additionalProperties": False,
    "required": ["mode", "constraints"],
    "properties": {
        "mode": {"const": "INITIAL"},
        "constraints": _constraint_slots_schema(require_one=True),
    },
}
_PROVIDER_CHANGED_SEARCH_SPEC = {
    "type": "object",
    "additionalProperties": False,
    "required": ["mode", "constraint_delta"],
    "properties": {
        "mode": {"const": "CHANGED"},
        "constraint_delta": {
            "type": "object",
            "additionalProperties": False,
            "required": ["upsert_constraints", "remove_constraint_kinds"],
            "if": {"properties": {"upsert_constraints": {"minProperties": 1}}},
            "else": {"properties": {"remove_constraint_kinds": {"minItems": 1}}},
            "properties": {
                "upsert_constraints": _constraint_slots_schema(require_one=False),
                "remove_constraint_kinds": {
                    "type": "array",
                    "uniqueItems": True,
                    "items": {"enum": _CONSTRAINT_KINDS},
                },
            },
        },
    },
}

_INITIAL_SEARCH_SPEC = {
    "type": "object",
    "additionalProperties": False,
    "required": ["mode", "constraints"],
    "properties": {
        "mode": {"const": "INITIAL"},
        "constraints": {
            "type": "array",
            "description": (
                "One effective constraint per kind. A search hypothesis therefore has at "
                "most one CONCEPT object; its manifestations express that one primary concept."
            ),
            "minItems": 1,
            "items": _CONSTRAINT_SCHEMA,
            "allOf": _unique_constraint_kind_guards(),
        },
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
            "if": {"properties": {"upsert_constraints": {"maxItems": 0}}},
            "then": {"properties": {"remove_constraint_kinds": {"minItems": 1}}},
            "properties": {
                "upsert_constraints": {
                    "type": "array",
                    "description": (
                        "One replacement per constraint kind. Use at most one CONCEPT object "
                        "for the changed hypothesis."
                    ),
                    "items": _CONSTRAINT_SCHEMA,
                    "allOf": _unique_constraint_kind_guards(),
                },
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
                "description": (
                    "검색 목적과 선택 근거. CHANGED는 이전 관측 → 부족한 사실 → "
                    "이번 단서가 그 부족함을 해결하는 이유를 설명한다. "
                    "동의어를 바꿨다는 설명만으로는 근거가 아니다."
                ),
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
        "required": ["schema_version", "route_queries"],
        "properties": {
            "schema_version": {"type": "integer", "enum": [2]},
            "route_queries": {
                "type": "array",
                "minItems": 1,
                "items": _ROUTE_QUERY_SCHEMA,
            },
        },
    },
)


def bind_retrieval_query_plan_output_schema(
    *,
    base_schema: OutputSchemaDefinition = RETRIEVAL_QUERY_PLAN_V2_OUTPUT_SCHEMA,
    route_ids: Collection[str],
    route_operations: Mapping[str, Collection[RetrievalOperationV2]],
    route_status_values: Mapping[str, Collection[str]] | None = None,
    supported_constraint_kinds: Mapping[str, Collection[str]] | None = None,
    required_constraint_kinds: Mapping[str, Collection[str]] | None = None,
    validated_resource_refs: Mapping[str, Collection[str]] | None = None,
    validated_container_refs: Mapping[str, Collection[str]] | None = None,
    detail_candidate_refs_by_route: Mapping[str, Collection[str]] | None = None,
    is_followup: bool = False,
    resolved_temporal_constraints: Mapping[str, TemporalRangeConstraintV1] | None = None,
    required_temporal_route_ids: Collection[str] = (),
    allowed_participant_identities: Collection[str] | None = None,
    requested_concepts: Mapping[str, Collection[str]] | None = None,
    removable_constraint_kinds: Mapping[str, Collection[str]] | None = None,
    gmail_route_ids: Collection[str] = (),
    next_page_route_ids: Collection[str] | None = None,
) -> OutputSchemaDefinition:
    """Bind planner-generated identities to values validated in the current state."""

    json_schema = deepcopy(base_schema.json_schema)
    properties = cast(dict[str, object], json_schema["properties"])
    properties["schema_version"] = {"type": "integer", "enum": [3]}
    route_queries = cast(dict[str, object], properties["route_queries"])
    allowed_route_ids = sorted(set(route_ids))
    required_temporal_routes = set(required_temporal_route_ids)

    operation_templates = cast(
        list[dict[str, object]], cast(dict[str, object], route_queries["items"])["oneOf"]
    )
    bound_operations: list[dict[str, object]] = []
    for route_id in allowed_route_ids:
        concepts = (requested_concepts or {}).get(route_id, ())
        allowed_operations = set(route_operations.get(route_id, ()))
        for template in operation_templates:
            operation_schema = deepcopy(template)
            fields = cast(dict[str, object], operation_schema["properties"])
            operation = cast(dict[str, object], fields["operation"])["const"]
            if operation not in allowed_operations:
                continue
            if (
                operation == "NEXT_PAGE"
                and next_page_route_ids is not None
                and route_id not in next_page_route_ids
            ):
                continue
            _bind_route_operation(
                operation_schema,
                route_id=route_id,
                is_followup=is_followup,
                detail_candidate_refs=(detail_candidate_refs_by_route or {}).get(route_id, ()),
                allowed_constraint_kinds=set(
                    (supported_constraint_kinds or {}).get(route_id, _CONSTRAINT_KINDS)
                ),
                required_constraint_kinds=set((required_constraint_kinds or {}).get(route_id, ())),
                allowed_resource_refs=sorted((validated_resource_refs or {}).get(route_id, ())),
                allowed_container_refs=sorted((validated_container_refs or {}).get(route_id, ())),
                temporal_constraint=(resolved_temporal_constraints or {}).get(route_id),
                require_temporal_constraint=route_id in required_temporal_routes,
                allowed_participant_identities=allowed_participant_identities,
                removable_constraint_kinds=set(
                    (removable_constraint_kinds or {}).get(route_id, ())
                ),
                gmail_keyword_literals=route_id in gmail_route_ids,
            )
            if route_status_values is not None:
                _bind_status_scope_values(operation_schema, route_status_values.get(route_id, ()))
            if concepts:
                _bind_concept_hypothesis(
                    operation_schema,
                    concepts,
                )
            bound_operations.append(operation_schema)
    route_queries["items"] = {"oneOf": bound_operations}
    return OutputSchemaDefinition(
        schema_version="retrieval-query-plan-candidate-v3",
        json_schema=json_schema,
    )


def normalize_retrieval_query_plan_candidate(value: object) -> object:
    """Project the provider-only v3 constraint slots to canonical RetrievalQueryPlanV2."""

    if not isinstance(value, Mapping) or value.get("schema_version") != 3:
        return value
    normalized = deepcopy(dict(value))
    normalized["schema_version"] = 2
    route_queries = normalized.get("route_queries")
    if not isinstance(route_queries, list):
        return normalized
    for route_query in route_queries:
        if not isinstance(route_query, dict):
            continue
        search_spec = route_query.get("search_spec")
        if not isinstance(search_spec, dict):
            continue
        if search_spec.get("mode") == "INITIAL":
            search_spec["constraints"] = _normalize_constraint_slots(search_spec.get("constraints"))
            continue
        delta = search_spec.get("constraint_delta")
        if isinstance(delta, dict):
            delta["upsert_constraints"] = _normalize_constraint_slots(
                delta.get("upsert_constraints")
            )
    return normalized


def _normalize_constraint_slots(value: object) -> object:
    if not isinstance(value, Mapping):
        return value
    return [
        deepcopy(value[slot]) for kind, slot in _CONSTRAINT_SLOT_BY_KIND.items() if slot in value
    ]


def _bind_concept_hypothesis(
    value: object,
    concepts: Collection[str],
) -> None:
    if isinstance(value, list):
        for item in value:
            _bind_concept_hypothesis(item, concepts)
    elif isinstance(value, dict):
        properties = value.get("properties")
        if isinstance(properties, dict) and properties.get("kind") == {"const": "CONCEPT"}:
            properties["concept"] = {"type": "string", "enum": sorted(concepts)}
        for child in value.values():
            _bind_concept_hypothesis(child, concepts)


def _bind_status_scope_values(value: object, allowed_values: Collection[str]) -> None:
    if isinstance(value, list):
        for child in value:
            _bind_status_scope_values(child, allowed_values)
    elif isinstance(value, dict):
        properties = value.get("properties")
        if isinstance(properties, dict) and properties.get("kind") == {"const": "STATUS_SCOPE"}:
            cast(dict[str, object], properties["values"])["items"] = {
                "type": "string",
                "enum": sorted(allowed_values),
            }
        for child in value.values():
            _bind_status_scope_values(child, allowed_values)


def _bind_route_operation(
    operation_schema: dict[str, object],
    *,
    route_id: str,
    is_followup: bool,
    detail_candidate_refs: Collection[str],
    allowed_constraint_kinds: set[str],
    required_constraint_kinds: set[str],
    allowed_resource_refs: list[str],
    allowed_container_refs: list[str],
    temporal_constraint: TemporalRangeConstraintV1 | None,
    require_temporal_constraint: bool,
    allowed_participant_identities: Collection[str] | None,
    removable_constraint_kinds: set[str],
    gmail_keyword_literals: bool,
) -> None:
    operation_properties = cast(dict[str, object], operation_schema["properties"])
    if allowed_participant_identities is not None and not allowed_participant_identities:
        allowed_constraint_kinds = allowed_constraint_kinds - {"PARTICIPANT"}
    operation_properties["route_id"] = {
        "type": "string",
        "const": route_id,
    }
    operation = cast(dict[str, object], operation_properties["operation"])["const"]
    if operation in {"SEARCH", "FREEBUSY"}:
        operation_properties["search_spec"] = deepcopy(
            _PROVIDER_CHANGED_SEARCH_SPEC if is_followup else _PROVIDER_INITIAL_SEARCH_SPEC
        )
        if operation == "SEARCH" and gmail_keyword_literals and not is_followup:
            search_spec = cast(dict[str, object], operation_properties["search_spec"])
            search_fields = cast(dict[str, object], search_spec["properties"])
            cast(dict[str, object], search_fields["constraints"])["minProperties"] = 0
        if is_followup:
            search_spec = cast(dict[str, object], operation_properties["search_spec"])
            search_fields = cast(dict[str, object], search_spec["properties"])
            delta = cast(dict[str, object], search_fields["constraint_delta"])
            delta_fields = cast(dict[str, object], delta["properties"])
            removal_schema = cast(dict[str, object], delta_fields["remove_constraint_kinds"])
            removal_schema["maxItems"] = len(removable_constraint_kinds)
            removal_schema["items"] = (
                {"type": "string", "enum": sorted(removable_constraint_kinds)}
                if removable_constraint_kinds
                else {"type": "string"}
            )
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
        gmail_keyword_literals=gmail_keyword_literals,
    )
    if require_temporal_constraint and temporal_constraint is not None and not is_followup:
        _require_constraint_slot(operation_properties["search_spec"], "temporal_range")
    if operation in {"SEARCH", "FREEBUSY"} and not is_followup:
        for kind in required_constraint_kinds.intersection(allowed_constraint_kinds):
            _require_constraint_slot(
                operation_properties["search_spec"],
                _CONSTRAINT_SLOT_BY_KIND[kind],
            )


def _require_constraint_slot(value: object, slot: str) -> None:
    if isinstance(value, list):
        for item in value:
            _require_constraint_slot(item, slot)
        return
    if not isinstance(value, dict):
        return
    properties = value.get("properties")
    if isinstance(properties, dict):
        declared_slots = set(properties).intersection(_CONSTRAINT_SLOT_BY_KIND.values())
        if declared_slots and declared_slots == set(properties) and slot in properties:
            required = value.setdefault("required", [])
            if isinstance(required, list) and slot not in required:
                required.append(slot)
    for child in value.values():
        _require_constraint_slot(child, slot)


def _bind_constraint_ref_values(
    value: object,
    *,
    allowed_constraint_kinds: set[str],
    allowed_resource_refs: list[str],
    allowed_container_refs: list[str],
    temporal_constraint: TemporalRangeConstraintV1 | None,
    allowed_participant_identities: Collection[str] | None,
    gmail_keyword_literals: bool,
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
                gmail_keyword_literals=gmail_keyword_literals,
            )
        return
    if not isinstance(value, dict):
        return
    options = value.get("oneOf")
    if isinstance(options, list):
        declared_kinds = [_declared_constraint_kind(item) for item in options]
        if declared_kinds and all(kind is not None for kind in declared_kinds):
            value["oneOf"] = [
                item
                for item, kind in zip(options, declared_kinds, strict=True)
                if kind in allowed_constraint_kinds
            ]
            if len(value["oneOf"]) == 1:
                only_option = value.pop("oneOf")[0]
                value.update(only_option)
    properties = value.get("properties")
    if isinstance(properties, dict):
        declared_slots = set(properties).intersection(_CONSTRAINT_SLOT_BY_KIND.values())
        if declared_slots and declared_slots == set(properties):
            for constraint_kind, slot in _CONSTRAINT_SLOT_BY_KIND.items():
                if constraint_kind not in allowed_constraint_kinds:
                    properties.pop(slot, None)
        kind_schema = properties.get("kind")
        declared_kind = kind_schema.get("const") if isinstance(kind_schema, dict) else None
        if declared_kind == "TEMPORAL_RANGE" and temporal_constraint is not None:
            for field, resolved_value in temporal_constraint.items():
                properties[field] = {"const": resolved_value}
        if declared_kind == "PARTICIPANT":
            participants = cast(dict[str, object], properties["participants"])
            item = cast(dict[str, object], participants["items"])
            fields = cast(dict[str, object], item["properties"])
            fields["identity"] = {
                "type": "string",
                "minLength": 1,
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
        if declared_kind == "KEYWORD" and gmail_keyword_literals:
            terms = cast(dict[str, object], properties["terms"])
            terms["items"] = {
                "type": "string",
                "minLength": 1,
                "pattern": GMAIL_KEYWORD_LITERAL_PATTERN,
            }
        if declared_kind == "RESOURCE_REF" and allowed_resource_refs:
            refs = properties.get("resource_refs")
            if isinstance(refs, dict):
                refs["items"] = {"type": "string", "enum": allowed_resource_refs}
        if declared_kind == "CONTAINER_REF" and allowed_container_refs:
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
            gmail_keyword_literals=gmail_keyword_literals,
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
