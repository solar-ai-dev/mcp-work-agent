"""Request-goal candidate output schema and validation."""

from __future__ import annotations

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
    "temporal_axis": "TIME",
    "status": "SCOPE",
}

IDENTIFY_GOAL_OUTPUT_SCHEMA = OutputSchemaDefinition(
    schema_version="request-goal-candidate-v2",
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
            "goal": {"type": "string"},
            "completion_conditions": {"type": "array", "items": {"type": "string"}},
            "constraints": {
                "type": "array",
                "description": (
                    "검색 의미를 분리한다: 고유 프로젝트/이름의 원문 anchor는 "
                    "USER_REQUIREMENT.search_terms, 추상 업무는 "
                    "USER_REQUIREMENT.business_concepts, 사람은 PERSON.person, "
                    "기간은 DATE.period, 수신/행사 구분은 TIME.temporal_axis. "
                    "한 문장에 사람·프로젝트·업무·답변 지시를 합쳐 검색어로 만들지 않는다. "
                    "요청에 없는 빈 날짜/상태/시간 필드는 생략한다."
                ),
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
                                {"type": "string"},
                                {"type": "array", "items": {"type": "string"}},
                            ]
                        },
                    },
                },
            },
            "requested_effect_hints": {
                "type": "array",
                "items": {"enum": ["READ", "CREATE", "UPDATE", "SEND", "DELETE"]},
                "description": (
                    "Effects on the requested external resources only. Retrieving, summarizing, "
                    "or analyzing an existing resource is READ; producing an assistant "
                    "answer or summary is never CREATE. CREATE, UPDATE, SEND, and DELETE "
                    "apply only when the user requests that external effect, and an "
                    "explicitly forbidden effect must not appear. Identifying or analyzing "
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
                    "and Google Calendar event work uses CALENDAR_EVENT. Empty only when "
                    "the request needs no Google Workspace resource."
                ),
            },
            "analysis_requirement": {
                "enum": ["NONE", "REQUIRED"],
                "description": (
                    "REQUIRED only for downstream business analysis such as relationships, "
                    "dependencies, conflicts, duplicates, follow-up actions, or operational "
                    "risk. A simple list, lookup, direct fact extraction, read, or summary is "
                    "NONE whether the resource is selected or retrieved. REQUIRED needs an "
                    "explicit request to analyze implications, comparisons, or next actions."
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
    if isinstance(root["constraints"], dict):
        slots = cast(dict[str, list[str]], root["constraints"])
        value = {
            **root,
            "constraints": [
                {"kind": REQUEST_GOAL_SLOT_KINDS[field], "field": field, "value": values}
                for field, values in slots.items()
                if values
            ],
        }
    return cast(RequestGoalCandidateV1, value)


__all__ = [
    "IDENTIFY_GOAL_OUTPUT_SCHEMA",
    "REQUEST_GOAL_SLOT_KINDS",
    "validate_request_goal_candidate",
]
