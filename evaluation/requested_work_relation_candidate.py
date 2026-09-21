"""Evaluation-only WorkRelation semantic-owner candidate for #287/#288."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from copy import deepcopy
from typing import Literal, NotRequired, TypedDict, cast

from google_work_agent.ports.llm.structured_inference_contracts import OutputSchemaDefinition

RelationKind = Literal["CONSUMES_WORK_PRODUCT", "CONSUMES_PLANNED_SPECIFICATION"]


class DiagnosticWorkUnitV1(TypedDict):
    unit_id: str
    request_excerpt: str
    request_start: int
    request_end: int


class WorkRelationCandidateV1(TypedDict):
    source_unit_id: str
    target_unit_id: str
    kind: RelationKind


class RelationDecisionPairV1(TypedDict):
    source_unit_id: str
    target_unit_id: str
    allowed_relation_kind: RelationKind


class RelationDiagnosticCaseV1(TypedDict):
    case_id: str
    work_spans: list[tuple[str, str]]
    semantic_items: dict[str, list[dict[str, object]]]
    expected_relations: list[WorkRelationCandidateV1]
    authority_note: str
    allowed_shape: NotRequired[str]


class BoundRelationDiagnosticCaseV1(TypedDict):
    case_id: str
    user_request: str
    work_units: list[DiagnosticWorkUnitV1]
    semantic_items: dict[str, list[dict[str, object]]]
    expected_relations: list[WorkRelationCandidateV1]
    authority_note: str
    allowed_shape: NotRequired[str]


RELATION_KINDS = frozenset({"CONSUMES_WORK_PRODUCT", "CONSUMES_PLANNED_SPECIFICATION"})


def relation_diagnostic_cases() -> list[RelationDiagnosticCaseV1]:
    """Core-only bounded relation cases.

    WorkUnit boundaries are fixed inputs to this experiment.  CORE-054 uses one
    of the two shapes explicitly accepted by the corrected semantic review; the
    experiment does not promote that shape to a unique Canonical decomposition.
    """

    return [
        {
            "case_id": "CASE-CORE-019",
            "work_spans": [
                ("event", "Fjord 고객 워크숍을 다음 주 화요일 오후에 일정으로 잡고"),
                ("draft", "고객에게 보낼 일정 안내 메일 초안도 준비해줘."),
            ],
            "semantic_items": {
                "source_responsibilities": [],
                "output_responsibilities": [
                    _output("CALENDAR_EVENT", "CREATE", "event"),
                    _output("GMAIL_DRAFT", "CREATE", "draft"),
                ],
                "constraints": [
                    _constraint("TEMPORAL", "event_time", "다음 주 화요일 오후", "event")
                ],
            },
            "expected_relations": [_relation("event", "draft", "CONSUMES_PLANNED_SPECIFICATION")],
            "authority_note": "일정 안내 Draft가 승인 전 Event 계획 명세를 참조한다.",
        },
        {
            "case_id": "CASE-CORE-046",
            "work_spans": [
                ("event", "8월 14일 오전 10시에 60분 점검 일정을 만들고"),
                (
                    "draft",
                    "qhdrbdhkdwks@naver.com에 그 일정 안내 메일 초안도 준비해줘.",
                ),
            ],
            "semantic_items": {
                "source_responsibilities": [
                    _source("GMAIL_THREAD", ["event", "draft"]),
                    _source("TASK", ["event", "draft"]),
                    _source("CALENDAR_EVENT", ["event", "draft"]),
                ],
                "output_responsibilities": [
                    _output("CALENDAR_EVENT", "CREATE", "event"),
                    _output("GMAIL_DRAFT", "CREATE", "draft"),
                ],
                "constraints": [
                    _constraint("TEMPORAL", "event_time", "8월 14일 오전 10시에 60분", "event")
                ],
            },
            "expected_relations": [_relation("event", "draft", "CONSUMES_PLANNED_SPECIFICATION")],
            "authority_note": "'그 일정'이 Event 계획 명세를 Draft 입력으로 지칭한다.",
        },
        {
            "case_id": "CASE-CORE-054",
            "work_spans": [
                ("summary", "Grove 결과를 정리해서"),
                ("draft", "qhdrbdhkdwks@naver.com에 답장 초안을 만들어줘."),
            ],
            "semantic_items": {
                "source_responsibilities": [_source("GMAIL_THREAD", ["summary", "draft"])],
                "output_responsibilities": [_output("GMAIL_DRAFT", "CREATE", "draft")],
                "constraints": [],
            },
            "expected_relations": [_relation("summary", "draft", "CONSUMES_WORK_PRODUCT")],
            "authority_note": "정리 결과를 Reply Draft 내용에 사용하는 허용된 두 업무 형태다.",
            "allowed_shape": "derived_summary_then_reply_draft",
        },
        {
            "case_id": "CASE-CORE-047",
            "work_spans": [
                ("task", "기존 검토 작업 기한을 오늘 17시로 바꾸고"),
                ("event", "16시부터 1시간 최종 검토 일정도 준비해줘."),
            ],
            "semantic_items": {
                "source_responsibilities": [
                    _source("GMAIL_THREAD", ["task", "event"]),
                    _source("TASK", ["task", "event"]),
                    _source("CALENDAR_EVENT", ["task", "event"]),
                ],
                "output_responsibilities": [
                    _output("TASK", "UPDATE", "task"),
                    _output("CALENDAR_EVENT", "CREATE", "event"),
                ],
                "constraints": [],
            },
            "expected_relations": [],
            "authority_note": "두 결과는 공통 자료를 쓰지만 서로의 결과를 입력으로 쓰지 않는다.",
        },
        {
            "case_id": "CASE-CORE-048",
            "work_spans": [
                ("task", "작업 메모에 2일 지연을 추가하고"),
                ("event", "8월 8일 10시에 30분 점검 일정"),
                ("draft", "qhdrbdhkdwks@naver.com 회신 메일 초안을 준비해줘."),
            ],
            "semantic_items": {
                "source_responsibilities": [
                    _source("GMAIL_THREAD", ["task", "event", "draft"]),
                    _source("TASK", ["task", "event", "draft"]),
                    _source("CALENDAR_EVENT", ["task", "event", "draft"]),
                ],
                "output_responsibilities": [
                    _output("TASK", "UPDATE", "task"),
                    _output("CALENDAR_EVENT", "CREATE", "event"),
                    _output("GMAIL_DRAFT", "CREATE", "draft"),
                ],
                "constraints": [],
            },
            "expected_relations": [],
            "authority_note": "세 독립 결과의 나열이며 Draft가 다른 계획 결과를 지칭하지 않는다.",
        },
        _single_control("CASE-CORE-001"),
        _single_control("CASE-CORE-041"),
        _single_control("CASE-CORE-056"),
    ]


def bind_relation_case(
    definition: RelationDiagnosticCaseV1,
    *,
    user_request: str,
) -> BoundRelationDiagnosticCaseV1:
    work_units: list[DiagnosticWorkUnitV1] = []
    seen_ids: set[str] = set()
    for unit_id, excerpt in definition["work_spans"]:
        if not unit_id or unit_id in seen_ids:
            raise ValueError("diagnostic WorkUnit IDs must be unique and non-empty")
        start = user_request.find(excerpt)
        if start < 0 or user_request.find(excerpt, start + 1) >= 0:
            raise ValueError(f"{definition['case_id']}: WorkUnit excerpt is not exact and unique")
        seen_ids.add(unit_id)
        work_units.append(
            {
                "unit_id": unit_id,
                "request_excerpt": excerpt,
                "request_start": start,
                "request_end": start + len(excerpt),
            }
        )
    semantic_items = deepcopy(definition["semantic_items"])
    _validate_semantic_item_refs(semantic_items, known_unit_ids=seen_ids)
    expected = validate_relation_candidate(
        {"schema_version": 1, "work_relations": definition["expected_relations"]},
        work_units=work_units,
        semantic_items=semantic_items,
    )
    result: BoundRelationDiagnosticCaseV1 = {
        "case_id": definition["case_id"],
        "user_request": user_request,
        "work_units": work_units,
        "semantic_items": semantic_items,
        "expected_relations": expected,
        "authority_note": definition["authority_note"],
    }
    if "allowed_shape" in definition:
        result["allowed_shape"] = definition["allowed_shape"]
    return result


def relation_inference_required(work_units: Sequence[Mapping[str, object]]) -> bool:
    return len(work_units) > 1


def relation_output_schema(work_units: Sequence[Mapping[str, object]]) -> OutputSchemaDefinition:
    unit_ids = [_text(item.get("unit_id"), "work_units.unit_id") for item in work_units]
    if len(unit_ids) != len(set(unit_ids)) or not unit_ids:
        raise ValueError("WorkUnit IDs must be a non-empty closed set")
    return OutputSchemaDefinition(
        schema_version="requested-work-relations-v1-eval",
        json_schema={
            "type": "object",
            "additionalProperties": False,
            "required": ["schema_version", "work_relations"],
            "properties": {
                "schema_version": {"const": 1},
                "work_relations": {
                    "type": "array",
                    "maxItems": len(unit_ids) * max(0, len(unit_ids) - 1),
                    "uniqueItems": True,
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": ["source_unit_id", "target_unit_id", "kind"],
                        "properties": {
                            "source_unit_id": {"enum": unit_ids},
                            "target_unit_id": {"enum": unit_ids},
                            "kind": {"enum": sorted(RELATION_KINDS)},
                        },
                    },
                },
            },
        },
    )


def relation_decision_pairs(
    work_units: Sequence[Mapping[str, object]],
    *,
    semantic_items: Mapping[str, object],
) -> list[RelationDecisionPairV1]:
    unit_ids = [_text(item.get("unit_id"), "work_units.unit_id") for item in work_units]
    if len(unit_ids) != len(set(unit_ids)) or not unit_ids:
        raise ValueError("WorkUnit IDs must be a non-empty closed set")
    output_units = _output_work_unit_ids(semantic_items, known_unit_ids=set(unit_ids))
    return [
        {
            "source_unit_id": source,
            "target_unit_id": target,
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
    pairs: Sequence[Mapping[str, object]],
) -> OutputSchemaDefinition:
    unit_ids = sorted(
        {
            _text(item.get(field), f"relation pair {field}")
            for item in pairs
            for field in ("source_unit_id", "target_unit_id")
        }
    )
    if not pairs or not unit_ids:
        raise ValueError("relation decision schema requires candidate pairs")
    return OutputSchemaDefinition(
        schema_version="requested-work-relation-decisions-v2-eval",
        json_schema={
            "type": "object",
            "additionalProperties": False,
            "required": ["schema_version", "relation_decisions"],
            "properties": {
                "schema_version": {"const": 2},
                "relation_decisions": {
                    "type": "array",
                    "minItems": len(pairs),
                    "maxItems": len(pairs),
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": [
                            "source_unit_id",
                            "target_unit_id",
                            "disposition",
                        ],
                        "properties": {
                            "source_unit_id": {"enum": unit_ids},
                            "target_unit_id": {"enum": unit_ids},
                            "disposition": {"enum": ["NONE", *sorted(RELATION_KINDS)]},
                        },
                    },
                },
            },
        },
    )


def validate_relation_decisions(
    candidate: Mapping[str, object],
    *,
    pairs: Sequence[Mapping[str, object]],
) -> list[WorkRelationCandidateV1]:
    if set(candidate) != {"schema_version", "relation_decisions"}:
        raise ValueError("relation decision candidate fields are invalid")
    if candidate.get("schema_version") != 2:
        raise ValueError("relation decision schema_version is invalid")
    allowed_by_pair = {
        (
            _text(item.get("source_unit_id"), "pair.source_unit_id"),
            _text(item.get("target_unit_id"), "pair.target_unit_id"),
        ): _text(item.get("allowed_relation_kind"), "pair.allowed_relation_kind")
        for item in pairs
    }
    decisions = _mapping_list(candidate.get("relation_decisions"), "relation_decisions")
    seen: set[tuple[str, str]] = set()
    relations: list[WorkRelationCandidateV1] = []
    for index, item in enumerate(decisions):
        if set(item) != {"source_unit_id", "target_unit_id", "disposition"}:
            raise ValueError(f"relation_decisions[{index}] fields are invalid")
        source = _text(item.get("source_unit_id"), f"relation_decisions[{index}].source")
        target = _text(item.get("target_unit_id"), f"relation_decisions[{index}].target")
        disposition = _text(item.get("disposition"), f"relation_decisions[{index}].disposition")
        pair = (source, target)
        allowed = allowed_by_pair.get(pair)
        if allowed is None or pair in seen:
            raise ValueError(f"relation_decisions[{index}] pair is not exact and unique")
        seen.add(pair)
        if disposition not in {"NONE", allowed}:
            raise ValueError(f"relation_decisions[{index}] rejudges the fixed result kind")
        if disposition != "NONE":
            relations.append(
                {
                    "source_unit_id": source,
                    "target_unit_id": target,
                    "kind": cast(RelationKind, disposition),
                }
            )
    if seen != set(allowed_by_pair):
        raise ValueError("relation decisions must cover every candidate pair exactly once")
    return relations


def validate_relation_candidate(
    candidate: Mapping[str, object],
    *,
    work_units: Sequence[Mapping[str, object]],
    semantic_items: Mapping[str, object],
) -> list[WorkRelationCandidateV1]:
    if set(candidate) != {"schema_version", "work_relations"}:
        raise ValueError("relation candidate fields are invalid")
    if candidate.get("schema_version") != 1:
        raise ValueError("relation candidate schema_version is invalid")
    unit_ids = {_text(item.get("unit_id"), "work_units.unit_id") for item in work_units}
    relations = _mapping_list(candidate.get("work_relations"), "work_relations")
    output_units = _output_work_unit_ids(semantic_items, known_unit_ids=unit_ids)
    result: list[WorkRelationCandidateV1] = []
    seen_pairs: set[tuple[str, str]] = set()
    for index, raw in enumerate(relations):
        if set(raw) != {"source_unit_id", "target_unit_id", "kind"}:
            raise ValueError(f"work_relations[{index}] fields are invalid")
        source = _text(raw.get("source_unit_id"), f"work_relations[{index}].source")
        target = _text(raw.get("target_unit_id"), f"work_relations[{index}].target")
        kind = _text(raw.get("kind"), f"work_relations[{index}].kind")
        if source not in unit_ids or target not in unit_ids:
            raise ValueError(f"work_relations[{index}] endpoint escapes current WorkUnits")
        if source == target:
            raise ValueError(f"work_relations[{index}] self relation is invalid")
        if kind not in RELATION_KINDS:
            raise ValueError(f"work_relations[{index}] kind is invalid")
        pair = (source, target)
        if pair in seen_pairs:
            raise ValueError(f"work_relations[{index}] duplicates an endpoint pair")
        seen_pairs.add(pair)
        expected_kind = (
            "CONSUMES_PLANNED_SPECIFICATION" if source in output_units else "CONSUMES_WORK_PRODUCT"
        )
        if kind != expected_kind:
            raise ValueError(
                f"work_relations[{index}] kind conflicts with fixed output responsibility"
            )
        result.append(
            {
                "source_unit_id": source,
                "target_unit_id": target,
                "kind": cast(RelationKind, kind),
            }
        )
    return result


def semantic_input_sha256(case: Mapping[str, object]) -> str:
    payload = {
        "user_request": case.get("user_request"),
        "work_units": case.get("work_units"),
        "semantic_items": case.get("semantic_items"),
    }
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()


def relation_scores(
    expected: Sequence[Mapping[str, object]],
    actual: Sequence[Mapping[str, object]],
) -> dict[str, object]:
    expected_set = {_relation_identity(item) for item in expected}
    actual_set = {_relation_identity(item) for item in actual}
    true_positive = len(expected_set & actual_set)
    false_positive = len(actual_set - expected_set)
    false_negative = len(expected_set - actual_set)
    precision = (
        1.0
        if not actual_set and not expected_set
        else true_positive / len(actual_set)
        if actual_set
        else 0.0
    )
    recall = true_positive / len(expected_set) if expected_set else 1.0
    return {
        "true_positive": true_positive,
        "false_positive": false_positive,
        "false_negative": false_negative,
        "precision": precision,
        "recall": recall,
        "exact_match": expected_set == actual_set,
        "missing": [list(item) for item in sorted(expected_set - actual_set)],
        "unexpected": [list(item) for item in sorted(actual_set - expected_set)],
    }


def _single_control(case_id: str) -> RelationDiagnosticCaseV1:
    return {
        "case_id": case_id,
        "work_spans": [("only", "__FULL_REQUEST__")],
        "semantic_items": {
            "source_responsibilities": [],
            "output_responsibilities": [],
            "constraints": [],
        },
        "expected_relations": [],
        "authority_note": "단일 WorkUnit control은 relation inference 대상이 아니다.",
    }


def bind_full_request_controls(
    definition: RelationDiagnosticCaseV1, *, user_request: str
) -> RelationDiagnosticCaseV1:
    if definition["work_spans"] == [("only", "__FULL_REQUEST__")]:
        result = deepcopy(definition)
        result["work_spans"] = [("only", user_request)]
        return result
    return definition


def _output(resource_type: str, effect: str, unit_id: str) -> dict[str, object]:
    return {
        "resource_type": resource_type,
        "effect": effect,
        "work_unit_ids": [unit_id],
    }


def _source(resource_type: str, unit_ids: list[str]) -> dict[str, object]:
    return {
        "resource_type": resource_type,
        "required_information": ["fixed upstream requirement"],
        "target_scope": "CRITERIA",
        "work_unit_ids": unit_ids,
    }


def _constraint(kind: str, field: str, value: str, unit_id: str) -> dict[str, object]:
    return {
        "kind": kind,
        "field": field,
        "value": value,
        "work_unit_ids": [unit_id],
    }


def _relation(source: str, target: str, kind: RelationKind) -> WorkRelationCandidateV1:
    return {"source_unit_id": source, "target_unit_id": target, "kind": kind}


def _validate_semantic_item_refs(
    semantic_items: Mapping[str, object], *, known_unit_ids: set[str]
) -> None:
    if set(semantic_items) != {
        "source_responsibilities",
        "output_responsibilities",
        "constraints",
    }:
        raise ValueError("semantic item collections are invalid")
    for collection, raw_items in semantic_items.items():
        for index, item in enumerate(_mapping_list(raw_items, collection)):
            refs = _string_list(item.get("work_unit_ids"), f"{collection}[{index}]")
            if not refs or not set(refs).issubset(known_unit_ids):
                raise ValueError(f"{collection}[{index}] has invalid WorkUnit refs")


def _output_work_unit_ids(
    semantic_items: Mapping[str, object], *, known_unit_ids: set[str]
) -> set[str]:
    _validate_semantic_item_refs(semantic_items, known_unit_ids=known_unit_ids)
    outputs = _mapping_list(
        semantic_items.get("output_responsibilities"), "output_responsibilities"
    )
    return {
        unit_id
        for item in outputs
        for unit_id in _string_list(item.get("work_unit_ids"), "output.work_unit_ids")
    }


def _relation_identity(item: Mapping[str, object]) -> tuple[str, str, str]:
    return (
        _text(item.get("source_unit_id"), "relation.source_unit_id"),
        _text(item.get("target_unit_id"), "relation.target_unit_id"),
        _text(item.get("kind"), "relation.kind"),
    )


def _mapping_list(value: object, path: str) -> list[Mapping[str, object]]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise TypeError(f"{path} must be a sequence")
    if not all(isinstance(item, Mapping) for item in value):
        raise TypeError(f"{path} must contain objects")
    return [cast(Mapping[str, object], item) for item in value]


def _string_list(value: object, path: str) -> list[str]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise TypeError(f"{path} must be a sequence")
    if not all(isinstance(item, str) and item for item in value):
        raise TypeError(f"{path} must contain non-empty strings")
    result = cast(list[str], list(value))
    if len(result) != len(set(result)):
        raise ValueError(f"{path} contains duplicates")
    return result


def _text(value: object, path: str) -> str:
    if not isinstance(value, str) or not value:
        raise TypeError(f"{path} must be a non-empty string")
    return value


__all__ = [
    "bind_full_request_controls",
    "bind_relation_case",
    "relation_diagnostic_cases",
    "relation_decision_output_schema",
    "relation_decision_pairs",
    "relation_inference_required",
    "relation_output_schema",
    "relation_scores",
    "semantic_input_sha256",
    "validate_relation_candidate",
    "validate_relation_decisions",
]
