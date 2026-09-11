"""Request-goal candidate output schema and validation."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from copy import deepcopy
from typing import cast

from google_work_agent.application.agents.request_understanding.contracts.request_intent import (
    SOURCE_STATUS_VALUES_BY_RESOURCE,
    WRITE_EFFECT_RESOURCE_TYPES,
    ActionEffectValue,
    ConstraintProvenanceSource,
    ConstraintV1,
    RequestGoalCandidateV1,
    RequestUnderstandingValidationError,
    ResourceResponsibilitiesV1,
)
from google_work_agent.application.agents.request_understanding.validate_intent import (
    validate_resource_responsibilities,
)
from google_work_agent.ports.llm.output_schema_validation import validate_output_schema
from google_work_agent.ports.llm.structured_inference_contracts import OutputSchemaDefinition

REQUEST_GOAL_SLOT_KINDS = {
    "search_terms": "USER_REQUIREMENT",
    "business_concepts": "USER_REQUIREMENT",
    "required_information": "USER_REQUIREMENT",
    "person": "PERSON",
    "sender": "PERSON",
    "recipient": "PERSON",
    "subject": "RESOURCE",
    "period": "DATE",
    "status": "SCOPE",
    "coverage_requirement": "SCOPE",
}
_MODEL_CONSTRAINT_SLOT_KINDS = {
    field: kind
    for field, kind in REQUEST_GOAL_SLOT_KINDS.items()
    if field != "required_information"
}
_RESOURCE_TYPES = [
    "GMAIL_THREAD",
    "GMAIL_MESSAGE",
    "GMAIL_DRAFT",
    "GMAIL_ATTACHMENT",
    "TASK_LIST",
    "TASK",
    "CALENDAR",
    "CALENDAR_EVENT",
    "CALENDAR_FREEBUSY",
    "GITHUB_ISSUE",
]
_NONEMPTY_CONSTRAINT_VALUE_SCHEMA = {
    "type": "string",
    "minLength": 1,
}
_NAMED_SEARCH_CONSTRAINT_PROPERTIES: dict[str, object] = {
    field: {
        "type": "array",
        "maxItems": 8,
        "items": dict(_NONEMPTY_CONSTRAINT_VALUE_SCHEMA),
    }
    for field in _MODEL_CONSTRAINT_SLOT_KINDS
}
for _field, _description in {
    "search_terms": (
        "원문에 명시된 프로젝트·고유명 anchor만 그대로 복사한다. '<고유명> <업무 개념>'이면 "
        "고유명만 두고 업무 개념·사람·기간·답변 지시를 붙이지 않는다."
    ),
    "business_concepts": (
        "사용자가 찾는 업무 대상의 의미만 짧게 보존한다. 프로젝트 고유명과 날짜·담당자·상태 "
        "같은 요청 속성은 제외하며 동의어나 하위 업무를 만들지 않는다."
    ),
    "person": "원문에 명시된 사람 이름·직급·별칭만 둔다. 이름 없는 역할·집합 명사는 제외한다.",
    "sender": "누가 보냈는지 명시된 경우 그 사람 표현만 두고 프로젝트와 합치지 않는다.",
    "recipient": "누가 받았는지 명시된 경우만 두고 본문에 등장하는 사람과 구분한다.",
    "subject": "사용자가 제목이라고 명시한 값만 둔다. 추정 제목을 만들지 않는다.",
    "period": "날짜가 제한하는 대상의 원문 기간을 보존하고 시간축이나 연도를 추측하지 않는다.",
    "status": "원문에 명시된 source Resource의 상태만 둔다.",
    "coverage_requirement": (
        "요청한 collection 범위의 모든 항목을 확인해야 완료되는 경우에만 EXHAUSTIVE를 둔다."
    ),
}.items():
    cast(dict[str, object], _NAMED_SEARCH_CONSTRAINT_PROPERTIES[_field])["description"] = (
        _description
    )
_NAMED_SEARCH_CONSTRAINT_PROPERTIES["status"] = {
    "type": "array",
    "maxItems": 8,
    "uniqueItems": True,
    "description": (
        "원문에 명시된 source Resource 상태만 둔다. normalized value와 원문 표현을 "
        "분리하고 output effect나 완료 후 상태를 source scope로 사용하지 않는다."
    ),
    "items": {
        "type": "object",
        "required": ["value", "source_resource_type", "source", "source_text"],
        "additionalProperties": False,
        "properties": {
            "value": {
                "enum": sorted(
                    {
                        status
                        for statuses in SOURCE_STATUS_VALUES_BY_RESOURCE.values()
                        for status in statuses
                    }
                )
            },
            "source_resource_type": {
                "enum": sorted(SOURCE_STATUS_VALUES_BY_RESOURCE)
            },
            "source": {"enum": ["USER_REQUEST", "CONFIRMATION_RESPONSE"]},
            "source_text": dict(_NONEMPTY_CONSTRAINT_VALUE_SCHEMA),
        },
    },
}
_NAMED_SEARCH_CONSTRAINT_PROPERTIES["coverage_requirement"] = {
    "type": "array",
    "maxItems": 1,
    "uniqueItems": True,
    "items": {"const": "EXHAUSTIVE"},
    "description": (
        "모든 항목 확인이 완료 조건이면 EXHAUSTIVE 하나를, 아니면 빈 배열을 둔다."
    ),
}


class RequestGoalSemanticValidationError(ValueError):
    def __init__(
        self,
        message: str,
        *,
        reason_code: str,
        affected_field_paths: Sequence[str],
    ) -> None:
        super().__init__(message)
        self.reason_code = reason_code
        self.affected_field_paths = tuple(affected_field_paths)
_CONSTRAINT_LIST_SCHEMA = {
    "type": "array",
    "items": {
        "type": "object",
        "required": ["kind", "field", "value"],
        "additionalProperties": False,
        "allOf": [
            {
                "if": {
                    "properties": {
                        "field": {
                            "enum": [
                                "search_terms",
                                "business_concepts",
                                "required_information",
                            ]
                        }
                    }
                },
                "then": {"properties": {"kind": {"const": "USER_REQUIREMENT"}}},
            },
            {
                "if": {
                    "properties": {
                        "kind": {"const": "SCOPE"},
                        "field": {"const": "status"},
                    },
                    "required": ["kind", "field"],
                },
                "then": {
                    "required": ["source_resource_type", "provenance"],
                    "properties": {
                        "value": {
                            "enum": sorted(
                                {
                                    status
                                    for statuses in SOURCE_STATUS_VALUES_BY_RESOURCE.values()
                                    for status in statuses
                                }
                            )
                        },
                        "provenance": {"required": ["source_text"]},
                    },
                },
            },
            {
                "if": {
                    "properties": {"field": {"const": "coverage_requirement"}},
                    "required": ["field"],
                },
                "then": {
                    "properties": {
                        "kind": {"const": "SCOPE"},
                        "value": {"const": "EXHAUSTIVE"},
                    }
                },
            },
        ],
        "properties": {
            "kind": {
                "enum": [
                    "PERSON",
                    "EMAIL",
                    "DATE",
                    "TIME",
                    "RESOURCE",
                    "SCOPE",
                    "USER_REQUIREMENT",
                ]
            },
            "field": {"type": "string", "minLength": 1},
            "value": {
                "oneOf": [
                    dict(_NONEMPTY_CONSTRAINT_VALUE_SCHEMA),
                    {
                        "type": "array",
                        "minItems": 1,
                        "items": dict(_NONEMPTY_CONSTRAINT_VALUE_SCHEMA),
                    },
                ]
            },
            "source_resource_type": {"type": "string", "minLength": 1},
            "provenance": {
                "type": "object",
                "required": ["source", "start_offset", "end_offset"],
                "additionalProperties": False,
                "properties": {
                    "source": {"enum": ["USER_REQUEST", "CONFIRMATION_RESPONSE"]},
                    "start_offset": {"type": "integer", "minimum": 0},
                    "end_offset": {"type": "integer", "minimum": 1},
                    "source_text": dict(_NONEMPTY_CONSTRAINT_VALUE_SCHEMA),
                },
            },
        },
    },
}
_ADDITIONAL_CONSTRAINT_LIST_SCHEMA = deepcopy(_CONSTRAINT_LIST_SCHEMA)
_additional_items = cast(dict[str, object], _ADDITIONAL_CONSTRAINT_LIST_SCHEMA["items"])
_additional_properties = cast(dict[str, object], _additional_items["properties"])
_additional_properties.pop("source_resource_type")
_additional_properties.pop("provenance")
_additional_field = cast(dict[str, object], _additional_properties["field"])
_additional_field["description"] = (
    "명명된 검색 슬롯 밖의 명시적 실행 필드. 예약 슬롯 이름은 허용하지 않는다."
)
_NAMED_SEARCH_CONSTRAINT_PROPERTIES["additional_constraints"] = (
    _ADDITIONAL_CONSTRAINT_LIST_SCHEMA
)
_NAMED_SEARCH_CONSTRAINTS_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": [*_MODEL_CONSTRAINT_SLOT_KINDS, "additional_constraints"],
    "properties": _NAMED_SEARCH_CONSTRAINT_PROPERTIES,
    "description": (
        "검색 의미를 이름 있는 슬롯으로 분리한다. 요청에 없는 슬롯은 빈 배열이며 "
        "그 밖의 명시적 실행 값은 additional_constraints에 둔다."
    ),
}
_RESOURCE_RESPONSIBILITY_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["source_reads", "outputs"],
    "description": (
        "요청의 외부 Resource 의미를 한 번만 표현한다. SOURCE는 Connector가 조회할 "
        "기존 사실/identity, OUTPUT은 사용자가 요청한 외부 Write다. 해당 역할이 없으면 "
        "각 배열은 비워 둔다."
    ),
    "properties": {
        "source_reads": {
            "type": "array",
            "uniqueItems": True,
            "description": (
                "기존 외부 자료에서 읽어야 할 사실이나 identity만 둔다. 새로 CREATE할 "
                "output은 그 output의 기존 상태를 실제로 읽어야 하는 별도 요구가 없는 한 "
                "source_reads에 반복하지 않는다."
            ),
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["resource_type", "required_information"],
                "properties": {
                    "resource_type": {"enum": _RESOURCE_TYPES},
                    "required_information": {
                        "type": "array",
                        "uniqueItems": True,
                        "items": dict(_NONEMPTY_CONSTRAINT_VALUE_SCHEMA),
                    },
                },
            },
        },
        "outputs": {
            "type": "array",
            "uniqueItems": True,
            "description": (
                "사용자가 새로 만들거나 변경·전송·삭제하라고 요청한 외부 결과만 둔다. "
                "그 결과를 작성하는 데 참고할 기존 자료는 source_reads에 둔다."
            ),
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["resource_type", "effect"],
                "allOf": [
                    {
                        "if": {
                            "properties": {"effect": {"const": effect}},
                            "required": ["effect"],
                        },
                        "then": {
                            "properties": {
                                "resource_type": {
                                    "enum": sorted(resource_types),
                                }
                            }
                        },
                    }
                    for effect, resource_types in WRITE_EFFECT_RESOURCE_TYPES.items()
                ],
                "properties": {
                    "resource_type": {"enum": _RESOURCE_TYPES},
                    "effect": {"enum": ["CREATE", "UPDATE", "SEND", "DELETE"]},
                },
            },
        },
    },
}
_DERIVED_EFFECT_HINTS_SCHEMA = {
    "type": "array",
    "uniqueItems": True,
    "items": {"enum": ["READ", "CREATE", "UPDATE", "SEND", "DELETE"]},
}
_DERIVED_RESOURCE_HINTS_SCHEMA = {
    "type": "array",
    "items": {"enum": _RESOURCE_TYPES},
    "uniqueItems": True,
}

IDENTIFY_GOAL_OUTPUT_SCHEMA = OutputSchemaDefinition(
    schema_version="request-goal-candidate-v13",
    json_schema={
        "type": "object",
        "required": [
            "goal",
            "completion_conditions",
            "constraints",
            "analysis_requirement",
        ],
        "additionalProperties": False,
        "properties": {
            "goal": {
                "type": "string",
                "description": (
                    "사용자가 요청한 결과만 기술한다. 자료에 특정 값이 반드시 존재해야 한다는 "
                    "조건이나 원문에 없는 identity를 추가하지 않는다."
                ),
            },
            "completion_conditions": {
                "type": "array",
                "items": {
                    "type": "string",
                    "description": (
                        "사용자 요청과 모순되지 않는 관측 가능한 완료 조건. '없으면 추측하지 "
                        "않음'은 그 값의 존재가 아니라 비추측·한계 표시 조건이다."
                    ),
                },
            },
            "constraints": {
                **_NAMED_SEARCH_CONSTRAINTS_SCHEMA,
                "description": (
                    "검색 의미를 분리한다: 고유 프로젝트/이름의 원문 anchor는 "
                    "USER_REQUIREMENT.search_terms, 추상 업무는 "
                    "USER_REQUIREMENT.business_concepts, 사람은 PERSON.person, "
                    "기간 원문은 DATE.period이며 시간축 판정은 별도 operation이 수행한다. "
                    "한 문장에 사람·프로젝트·업무·답변 지시를 합쳐 검색어로 만들지 않는다. "
                    "요청에 없는 이름 있는 슬롯은 빈 배열로 둔다. Calendar/GitHub 등 "
                    "typed 완료 범위는 coverage_requirement에 두고 그 밖의 명시적 실행 값은 "
                    "additional_constraints에 둔다."
                ),
            },
            "analysis_requirement": {
                "enum": ["NONE", "REQUIRED"],
                "description": (
                    "REQUIRED only for downstream business analysis such as relationships, "
                    "dependencies, conflicts, duplicates, follow-up actions, or operational "
                    "risk. A simple list, lookup, direct fact extraction, read, or summary is "
                    "NONE whether the resource is selected or retrieved. REQUIRED needs an "
                    "explicit request to analyze implications, comparisons, or next actions. "
                    "A question about the meaning or usage of the word 'analysis' is not itself "
                    "a request to analyze business evidence."
                ),
            },
        },
    },
)

IDENTIFY_RESOURCE_RESPONSIBILITIES_OUTPUT_SCHEMA = OutputSchemaDefinition(
    schema_version="request-resource-responsibilities-v1",
    json_schema=deepcopy(_RESOURCE_RESPONSIBILITY_SCHEMA),
)


def validate_request_goal_candidate(
    value: object,
    *,
    resource_responsibilities: object,
    schema: OutputSchemaDefinition = IDENTIFY_GOAL_OUTPUT_SCHEMA,
    provenance_sources: Mapping[ConstraintProvenanceSource, str] | None = None,
) -> RequestGoalCandidateV1:
    errors = validate_output_schema(value, schema.json_schema)
    if errors:
        raise ValueError(f"request goal candidate is invalid: {'; '.join(errors)}")
    root = cast(dict[str, object], value)
    slots = cast(dict[str, object], root["constraints"])
    _validate_semantic_constraint_text(slots)
    normalized_responsibilities = validate_resource_responsibility_candidate(
        resource_responsibilities
    )
    normalized_root = {
        **root,
        "resource_responsibilities": normalized_responsibilities,
    }
    effects, resources, source_information = derive_requested_resource_fields(
        normalized_responsibilities
    )
    additional = cast(list[object], slots["additional_constraints"])
    reserved_additional_fields = [
        str(cast(dict[str, object], constraint)["field"])
        for constraint in additional
        if str(cast(dict[str, object], constraint)["field"]) in REQUEST_GOAL_SLOT_KINDS
    ]
    if reserved_additional_fields:
        raise ValueError(
            "request goal candidate is invalid: additional constraint uses reserved field"
        )
    normalized_constraints = [
        {
            "kind": _MODEL_CONSTRAINT_SLOT_KINDS[field],
            "field": field,
            "value": (
                cast(list[str], values)[0] if field == "coverage_requirement" else values
            ),
        }
        for field, values in slots.items()
        if field in _MODEL_CONSTRAINT_SLOT_KINDS and field != "status" and values
    ]
    if source_information:
        normalized_constraints.append(
            {
                "kind": REQUEST_GOAL_SLOT_KINDS["required_information"],
                "field": "required_information",
                "value": source_information,
            }
        )
    normalized_constraints.extend(
        _normalize_status_constraints(
            slots["status"],
            effects=effects,
            resources=resources,
            provenance_sources=provenance_sources,
        )
    )
    if any(
        constraint["field"] == "repository" for constraint in cast(list[ConstraintV1], additional)
    ) and "GITHUB_ISSUE" not in resources:
        raise ValueError(
            "request goal candidate is invalid: repository constraint requires GITHUB_ISSUE"
        )
    try:
        responsibilities = validate_resource_responsibilities(
            normalized_responsibilities,
            effects=effects,
            resource_hints=resources,
            constraints=cast(list[ConstraintV1], normalized_constraints + additional),
            required=True,
        )
    except RequestUnderstandingValidationError as error:
        raise RequestGoalSemanticValidationError(
            str(error),
            reason_code="REQUEST_RESOURCE_RESPONSIBILITY_MISMATCH",
            affected_field_paths=(
                "$.resource_responsibilities",
            ),
        ) from error
    value = {
        **normalized_root,
        "constraints": normalized_constraints + additional,
        "requested_effect_hints": effects,
        "requested_resource_hints": resources,
        "resource_responsibilities": responsibilities,
    }
    return cast(RequestGoalCandidateV1, value)


def validate_resource_responsibility_candidate(
    value: object,
) -> ResourceResponsibilitiesV1:
    errors = validate_output_schema(
        value,
        IDENTIFY_RESOURCE_RESPONSIBILITIES_OUTPUT_SCHEMA.json_schema,
    )
    if errors:
        raise ValueError(f"resource responsibility candidate is invalid: {'; '.join(errors)}")
    responsibilities = _normalize_source_read_responsibilities(
        cast(Mapping[str, object], value)
    )
    _validate_resource_responsibility_text(responsibilities)
    return responsibilities


def _normalize_source_read_responsibilities(
    responsibilities: Mapping[str, object],
) -> ResourceResponsibilitiesV1:
    source_reads = cast(Sequence[Mapping[str, object]], responsibilities["source_reads"])
    normalized_sources: list[dict[str, object]] = []
    source_index_by_resource_type: dict[str, int] = {}
    for source in source_reads:
        resource_type = cast(str, source["resource_type"])
        information = list(cast(Sequence[str], source["required_information"]))
        source_index = source_index_by_resource_type.get(resource_type)
        if source_index is None:
            source_index_by_resource_type[resource_type] = len(normalized_sources)
            normalized_sources.append(
                {
                    "resource_type": resource_type,
                    "required_information": information,
                }
            )
            continue
        existing_information = cast(
            list[str], normalized_sources[source_index]["required_information"]
        )
        existing_information.extend(
            value for value in information if value not in existing_information
        )
    return cast(
        ResourceResponsibilitiesV1,
        {
            "source_reads": normalized_sources,
            "outputs": deepcopy(responsibilities["outputs"]),
        },
    )


def derive_requested_resource_fields(
    responsibilities: Mapping[str, object],
) -> tuple[list[ActionEffectValue], list[str], list[str]]:
    """Derive the normalized resource hints from the single model-owned meaning."""
    source_reads = cast(Sequence[Mapping[str, object]], responsibilities["source_reads"])
    outputs = cast(Sequence[Mapping[str, object]], responsibilities["outputs"])
    effects: list[ActionEffectValue] = ["READ"] if source_reads else []
    resources: list[str] = []
    source_information: list[str] = []
    for source in source_reads:
        resource_type = cast(str, source["resource_type"])
        if resource_type not in resources:
            resources.append(resource_type)
        for information in cast(Sequence[str], source["required_information"]):
            if information not in source_information:
                source_information.append(information)
    for output in outputs:
        effect = cast(ActionEffectValue, output["effect"])
        resource_type = cast(str, output["resource_type"])
        if effect not in effects:
            effects.append(effect)
        if resource_type not in resources:
            resources.append(resource_type)
    return effects, resources, source_information


def _validate_semantic_constraint_text(
    slots: Mapping[str, object],
) -> None:
    for field in _MODEL_CONSTRAINT_SLOT_KINDS:
        if field == "status":
            continue
        values = cast(list[str], slots[field])
        for index, text_value in enumerate(values):
            _require_semantic_text(text_value, f"$.constraints.{field}[{index}]")

    status_values = cast(list[Mapping[str, object]], slots["status"])
    for index, status_value in enumerate(status_values):
        _require_semantic_text(
            cast(str, status_value["source_text"]),
            f"$.constraints.status[{index}].source_text",
        )

    additional = cast(list[Mapping[str, object]], slots["additional_constraints"])
    for index, additional_value in enumerate(additional):
        constraint_value = additional_value["value"]
        additional_values = (
            [constraint_value]
            if isinstance(constraint_value, str)
            else constraint_value
        )
        for value_index, value in enumerate(cast(Sequence[str], additional_values)):
            _require_semantic_text(
                value,
                f"$.constraints.additional_constraints[{index}].value[{value_index}]",
            )
        provenance = additional_value.get("provenance")
        if isinstance(provenance, Mapping) and "source_text" in provenance:
            _require_semantic_text(
                cast(str, provenance["source_text"]),
                f"$.constraints.additional_constraints[{index}].provenance.source_text",
            )

def _validate_resource_responsibility_text(
    responsibilities: ResourceResponsibilitiesV1,
) -> None:
    source_reads = cast(Sequence[Mapping[str, object]], responsibilities["source_reads"])
    for source_index, source in enumerate(source_reads):
        information = cast(Sequence[str], source["required_information"])
        for information_index, information_value in enumerate(information):
            _require_semantic_text(
                information_value,
                "$.resource_responsibilities.source_reads"
                f"[{source_index}].required_information[{information_index}]",
            )


def _require_semantic_text(value: str, path: str) -> None:
    if not any(not character.isspace() and character not in "[]{}" for character in value):
        raise ValueError(f"request goal candidate is invalid: {path} has no semantic text")


def _normalize_status_constraints(
    value: object,
    *,
    effects: Sequence[str],
    resources: Sequence[str],
    provenance_sources: Mapping[ConstraintProvenanceSource, str] | None,
) -> list[dict[str, object]]:
    bindings = cast(list[Mapping[str, object]], value)
    if not bindings:
        return []
    if provenance_sources is None:
        raise ValueError("source status requires current-Run provenance sources")
    resource_set = set(resources)
    if "READ" not in effects:
        raise ValueError("source status requires a READ effect")
    normalized: list[dict[str, object]] = []
    identities: set[tuple[str, str, str, str]] = set()
    for binding in bindings:
        status = cast(str, binding["value"])
        resource_type = cast(str, binding["source_resource_type"])
        source = cast(ConstraintProvenanceSource, binding["source"])
        source_text = cast(str, binding["source_text"])
        if resource_type not in resource_set:
            raise ValueError("source status resource is not present in requested resource hints")
        if status not in SOURCE_STATUS_VALUES_BY_RESOURCE.get(resource_type, frozenset()):
            raise ValueError("source status is not valid for its bound resource")
        source_value = provenance_sources.get(source)
        if source_value is None:
            raise ValueError("source status provenance source is unavailable")
        start_offset = source_value.find(source_text)
        if start_offset < 0:
            raise RequestGoalSemanticValidationError(
                "source status text has no current-Run source binding",
                reason_code="REQUEST_STATUS_PROVENANCE_MISMATCH",
                affected_field_paths=(
                    "$.constraints.status[].source",
                    "$.constraints.status[].source_text",
                ),
            )
        identity = (status, resource_type, source, source_text)
        if identity in identities:
            raise ValueError("source status binding is duplicated")
        identities.add(identity)
        normalized.append(
            {
                "kind": "SCOPE",
                "field": "status",
                "value": status,
                "source_resource_type": resource_type,
                "provenance": {
                    "source": source,
                    "start_offset": start_offset,
                    "end_offset": start_offset + len(source_text),
                    "source_text": source_text,
                },
            }
        )
    return normalized


def validate_normalized_request_goal_candidate(value: object) -> RequestGoalCandidateV1:
    """Validate the single downstream ConstraintV1 representation after normalization."""

    schema = cast(dict[str, object], deepcopy(IDENTIFY_GOAL_OUTPUT_SCHEMA.json_schema))
    properties = cast(dict[str, object], schema["properties"])
    properties["constraints"] = _CONSTRAINT_LIST_SCHEMA
    properties["resource_responsibilities"] = _RESOURCE_RESPONSIBILITY_SCHEMA
    properties["requested_effect_hints"] = _DERIVED_EFFECT_HINTS_SCHEMA
    properties["requested_resource_hints"] = _DERIVED_RESOURCE_HINTS_SCHEMA
    required = cast(list[str], schema["required"])
    required.extend(
        [
            "resource_responsibilities",
            "requested_effect_hints",
            "requested_resource_hints",
        ]
    )
    errors = validate_output_schema(value, schema)
    if errors:
        raise ValueError(f"normalized request goal candidate is invalid: {'; '.join(errors)}")
    return cast(RequestGoalCandidateV1, value)


__all__ = [
    "IDENTIFY_GOAL_OUTPUT_SCHEMA",
    "IDENTIFY_RESOURCE_RESPONSIBILITIES_OUTPUT_SCHEMA",
    "RequestGoalSemanticValidationError",
    "REQUEST_GOAL_SLOT_KINDS",
    "validate_normalized_request_goal_candidate",
    "validate_request_goal_candidate",
    "validate_resource_responsibility_candidate",
]
