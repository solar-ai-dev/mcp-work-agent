"""Request-goal candidate output schema and validation."""

from __future__ import annotations

from copy import deepcopy
from typing import cast

from google_work_agent.application.agents.request_understanding.contracts.request_intent import (
    RequestGoalCandidateV1,
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
}
_NONEMPTY_CONSTRAINT_VALUE_SCHEMA = {
    "type": "string",
    "minLength": 1,
    "pattern": r".*[^\s\[\]{}].*",
}
_NAMED_SEARCH_CONSTRAINT_PROPERTIES: dict[str, object] = {
    field: {
        "type": "array",
        "maxItems": 8,
        "items": dict(_NONEMPTY_CONSTRAINT_VALUE_SCHEMA),
    }
    for field in REQUEST_GOAL_SLOT_KINDS
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
    "required_information": (
        "답변에서 자료로 확인할 사실이나 속성만 둔다. '없으면 추측하지 마', '명시된 경우만', "
        "'수신일과 구분' 같은 근거·표현 제약을 반드시 존재해야 할 사실로 바꾸지 않는다."
    ),
    "person": "원문에 명시된 사람 이름·직급·별칭만 둔다. 이름 없는 역할·집합 명사는 제외한다.",
    "sender": "누가 보냈는지 명시된 경우 그 사람 표현만 두고 프로젝트와 합치지 않는다.",
    "recipient": "누가 받았는지 명시된 경우만 두고 본문에 등장하는 사람과 구분한다.",
    "subject": "사용자가 제목이라고 명시한 값만 둔다. 추정 제목을 만들지 않는다.",
    "period": "날짜가 제한하는 대상의 원문 기간을 보존하고 시간축이나 연도를 추측하지 않는다.",
    "status": "원문에 명시된 대상 Resource의 상태만 둔다.",
}.items():
    cast(dict[str, object], _NAMED_SEARCH_CONSTRAINT_PROPERTIES[_field])["description"] = (
        _description
    )
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
        },
    },
}
_NAMED_SEARCH_CONSTRAINT_PROPERTIES["additional_constraints"] = _CONSTRAINT_LIST_SCHEMA
_NAMED_SEARCH_CONSTRAINTS_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": [*REQUEST_GOAL_SLOT_KINDS, "additional_constraints"],
    "properties": _NAMED_SEARCH_CONSTRAINT_PROPERTIES,
    "description": (
        "검색 의미를 이름 있는 슬롯으로 분리한다. 요청에 없는 슬롯은 빈 배열이며 "
        "그 밖의 명시적 실행 값은 additional_constraints에 둔다."
    ),
}

IDENTIFY_GOAL_OUTPUT_SCHEMA = OutputSchemaDefinition(
    schema_version="request-goal-candidate-v4",
    json_schema={
        "type": "object",
        "required": [
            "goal",
            "completion_conditions",
            "constraints",
            "requested_effect_hints",
            "requested_resource_hints",
            "analysis_requirement",
        ],
        "additionalProperties": False,
        "allOf": [
            {
                "if": {
                    "properties": {"requested_effect_hints": {"type": "array", "minItems": 1}},
                    "required": ["requested_effect_hints"],
                },
                "then": {
                    "properties": {"requested_resource_hints": {"type": "array", "minItems": 1}}
                },
            },
            {
                "if": {
                    "properties": {"requested_resource_hints": {"type": "array", "minItems": 1}},
                    "required": ["requested_resource_hints"],
                },
                "then": {
                    "properties": {"requested_effect_hints": {"type": "array", "minItems": 1}}
                },
            },
        ],
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
                    "그 밖의 명시적 실행 값은 additional_constraints에 둔다."
                ),
            },
            "requested_effect_hints": {
                "type": "array",
                "items": {"enum": ["READ", "CREATE", "UPDATE", "SEND", "DELETE"]},
                "description": (
                    "Effects on the requested external resources only. Retrieving, summarizing, "
                    "or analyzing an existing resource is READ; producing an assistant "
                    "answer or summary is never CREATE. CREATE, UPDATE, SEND, and DELETE "
                    "apply only when the user requests that external effect, and an "
                    "explicitly forbidden effect must not appear. Quoted, hypothetical, negated, "
                    "or metalinguistic discussion of an operation does not request that effect. "
                    "Identifying or analyzing "
                    "follow-up actions from existing material is READ unless the user also "
                    "explicitly asks to apply a write to that resource."
                ),
            },
            "requested_resource_hints": {
                "type": "array",
                "items": {
                    "enum": [
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
                },
                "uniqueItems": True,
                "description": (
                    "Semantic resource concepts explicitly named or necessarily targeted. "
                    "Gmail or email lookup uses GMAIL_THREAD, Google Tasks work uses TASK, "
                    "and Google Calendar event work uses CALENDAR_EVENT. A resource mentioned "
                    "only inside an example, quotation, hypothetical, negation, or explanation is "
                    "not a target. Empty when the request needs no external Connector resource."
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


def validate_request_goal_candidate(
    value: object,
    *,
    schema: OutputSchemaDefinition = IDENTIFY_GOAL_OUTPUT_SCHEMA,
) -> RequestGoalCandidateV1:
    errors = validate_output_schema(value, schema.json_schema)
    if errors:
        raise ValueError(f"request goal candidate is invalid: {'; '.join(errors)}")
    root = cast(dict[str, object], value)
    slots = cast(dict[str, object], root["constraints"])
    additional = cast(list[object], slots["additional_constraints"])
    normalized_constraints = [
        {"kind": REQUEST_GOAL_SLOT_KINDS[field], "field": field, "value": values}
        for field, values in slots.items()
        if field in REQUEST_GOAL_SLOT_KINDS and values
    ]
    value = {
        **root,
        "constraints": normalized_constraints + additional,
    }
    return cast(RequestGoalCandidateV1, value)


def validate_normalized_request_goal_candidate(value: object) -> RequestGoalCandidateV1:
    """Validate the single downstream ConstraintV1 representation after normalization."""

    schema = cast(dict[str, object], deepcopy(IDENTIFY_GOAL_OUTPUT_SCHEMA.json_schema))
    properties = cast(dict[str, object], schema["properties"])
    properties["constraints"] = _CONSTRAINT_LIST_SCHEMA
    schema["allOf"] = cast(list[object], schema["allOf"])[:2]
    errors = validate_output_schema(value, schema)
    if errors:
        raise ValueError(f"normalized request goal candidate is invalid: {'; '.join(errors)}")
    return cast(RequestGoalCandidateV1, value)


__all__ = [
    "IDENTIFY_GOAL_OUTPUT_SCHEMA",
    "REQUEST_GOAL_SLOT_KINDS",
    "validate_normalized_request_goal_candidate",
    "validate_request_goal_candidate",
]
