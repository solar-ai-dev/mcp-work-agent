from __future__ import annotations

from collections.abc import Mapping
from typing import Any, cast

import pytest

from google_work_agent.application.agents.planning.contracts.planning_semantics import (
    PlanningAnswerConfirmationV1,
    PlanningSemanticInvoker,
)
from google_work_agent.application.agents.planning.outline_answer import (
    answer_outline_output_schema,
    outline_answer,
)


def test_answer_outline_schema__binds_citations__to_current_evidence() -> None:
    schema = answer_outline_output_schema(
        ["e2", "e1", "e1"],
        confirmation_allowed=True,
    )
    json_schema = cast(dict[str, Any], schema.json_schema)
    answer_schema = json_schema["oneOf"][0]

    assert answer_schema["properties"]["evidence_refs"] == {
        "type": "array",
        "uniqueItems": True,
        "items": {"type": "string", "enum": ["e1", "e2"]},
    }


def test_answer_outline_schema__disallows_confirmation__for_actionable_intent() -> None:
    schema = answer_outline_output_schema(["e1"], confirmation_allowed=False)

    json_schema = cast(dict[str, Any], schema.json_schema)
    assert len(json_schema["oneOf"]) == 1
    assert json_schema["oneOf"][0]["required"] == ["sections", "evidence_refs"]


def test_outline_rejects__confirmation__for_actionable_intent() -> None:
    with pytest.raises(ValueError, match="not permitted"):
        outline_answer(
            user_request="Summarize.",
            request_intent={
                "goal": "summary",
                "ambiguity": {"requires_confirmation": False},
            },
            work_analysis={"ambiguities": []},
            evidence=[{"evidence_id": "e1", "excerpt": "fact"}],
            invoke=lambda _prompt_id, _prompt_input: {
                "disposition": "NEEDS_CONFIRMATION",
                "question": "Search again?",
                "options": ["yes", "no"],
                "reason_codes": ["MORE_DATA"],
            },
        )


def test_outline_allows__confirmation__from_current_work_analysis_ambiguity() -> None:
    result = outline_answer(
        user_request="Summarize after resolving the conflicting owner.",
        request_intent={"ambiguity": {"requires_confirmation": False}},
        work_analysis={
            "ambiguities": [
                {
                    "code": "owner_conflict",
                    "description": "Two current owners conflict.",
                    "requires_confirmation": True,
                    "evidence_refs": ["e1"],
                }
            ]
        },
        evidence=[{"evidence_id": "e1", "excerpt": "conflicting owners"}],
        invoke=lambda _prompt_id, _prompt_input: {
            "disposition": "NEEDS_CONFIRMATION",
            "question": "Which owner should be used?",
            "options": ["A", "B"],
            "reason_codes": ["OWNER_CONFLICT"],
        },
    )

    confirmation = cast(PlanningAnswerConfirmationV1, result)
    assert confirmation["disposition"] == "NEEDS_CONFIRMATION"


def test_outline_uses__distinct_prompt__and_minimum_projection() -> None:
    captured: dict[str, object] = {}

    def invoke(prompt_id: str, prompt_input: Mapping[str, object]) -> Mapping[str, object]:
        captured.update({"prompt_id": prompt_id, "prompt_input": dict(prompt_input)})
        return {"sections": ["Conclusion", "Uncertainty"], "evidence_refs": ["e1"]}

    result = outline_answer(
        user_request="Summarize the current facts.",
        request_intent={
            "goal": "summary",
            "repository_default": {
                "repository": "sample/project",
                "repository_id": 2,
                "account_id": "github:1",
            },
        },
        work_analysis={"action_necessity": "NOT_REQUIRED"},
        evidence=[{"evidence_id": "e1", "excerpt": "fact"}],
        invoke=invoke,
    )

    assert result == {"sections": ["Conclusion", "Uncertainty"], "evidence_refs": ["e1"]}
    assert captured["prompt_id"] == "planning.outline_answer"
    prompt_input = captured["prompt_input"]
    assert isinstance(prompt_input, dict)
    assert prompt_input["request_intent"] == {"goal": "summary"}
    assert set(prompt_input) == {
        "user_request",
        "request_intent",
        "work_analysis",
        "evidence",
    }


def test_outline_rejects__evidence_outside__current_projection() -> None:
    with pytest.raises(ValueError, match="outside"):
        outline_answer(
            user_request="Summarize.",
            request_intent={"goal": "summary"},
            work_analysis={},
            evidence=[],
            invoke=lambda _prompt_id, _prompt_input: {
                "sections": ["Conclusion"],
                "evidence_refs": ["previous-run"],
            },
        )


def test_outline_collection__allows_relevant_subset_and_order__without_rewriting_output() -> None:
    captured: dict[str, object] = {}

    def invoke(prompt_id: str, prompt_input: Mapping[str, object]) -> Mapping[str, object]:
        captured.update({"prompt_id": prompt_id, "prompt_input": dict(prompt_input)})
        return {"sections": ["관련: C", "관련: A"], "evidence_refs": ["e-c"]}

    result = outline_answer(
        user_request="관련된 제목만 중요도순으로 알려줘.",
        request_intent={"requested_effect_hints": ["READ"]},
        work_analysis={},
        evidence=[
            {
                "evidence_id": "e-c",
                "resource_handle": "gmail_thread:c",
                "excerpt": "관련 제목 C",
            }
        ],
        retrieval_result={
            "collection_results": [
                {
                    "route_id": "route-1",
                    "resource_type": "gmail_thread",
                    "continuation_status": "EXHAUSTED",
                    "items": [
                        {"resource_ref": "gmail_thread:a", "title": "A"},
                        {"resource_ref": "gmail_thread:b", "title": "B"},
                        {"resource_ref": "gmail_thread:c", "title": "C"},
                    ],
                }
            ]
        },
        invoke=cast(PlanningSemanticInvoker, invoke),
    )

    projection = cast(dict[str, object], captured["prompt_input"])
    collection = cast(list[dict[str, object]], projection["collection_results"])[0]
    assert [item["title"] for item in cast(list[dict[str, object]], collection["items"])] == [
        "A",
        "B",
        "C",
    ]
    assert result == {"sections": ["관련: C", "관련: A"], "evidence_refs": ["e-c"]}


def test_outline__does_not_replace__invalid_evidence_identity() -> None:
    with pytest.raises(ValueError, match="outside"):
        outline_answer(
            user_request="Summarize.",
            request_intent={"goal": "summary"},
            work_analysis={},
            evidence=[{"evidence_id": "evidence-only", "excerpt": "fact"}],
            invoke=lambda _prompt_id, _prompt_input: {
                "sections": ["Conclusion"],
                "evidence_refs": ["invented-reference"],
            },
        )


def test_outline_task_read__concrete_task__selects_without_llm() -> None:
    invoked = False

    def invoke(prompt_id: str, prompt_input: Mapping[str, object]) -> Mapping[str, object]:
        del prompt_id, prompt_input
        nonlocal invoked
        invoked = True
        return {}

    result = outline_answer(
        user_request="Google Tasks 할 일을 목록으로 알려줘.",
        request_intent={
            "requested_effect_hints": ["READ"],
            "requested_resource_hints": ["TASK"],
            "analysis_requirement": "NONE",
        },
        work_analysis=None,
        evidence=[
            {
                "evidence_id": "e-task",
                "resource_handle": "task:1",
                "excerpt": "보고서 제출",
            },
            {
                "evidence_id": "e-list",
                "resource_handle": "task_list:default",
                "excerpt": "내 할 일 목록",
            },
        ],
        invoke=invoke,
    )

    assert invoked is False
    assert result == {
        "sections": ["현재 Google Tasks 할 일"],
        "evidence_refs": ["e-task"],
    }


def test_outline_gmail_read__empty_evidence__passes_observed_state_to_answer_agent() -> None:
    captured: dict[str, object] = {}

    def invoke(prompt_id: str, prompt_input: Mapping[str, object]) -> Mapping[str, object]:
        captured.update({"prompt_id": prompt_id, "prompt_input": dict(prompt_input)})
        return {"sections": ["확인된 검색 결과 없음"], "evidence_refs": []}

    result = outline_answer(
        user_request="지난주 프로젝트 일정 메일을 찾아줘.",
        request_intent={
            "requested_effect_hints": ["READ"],
            "requested_resource_hints": ["GMAIL_THREAD"],
            "constraints": [
                {"kind": "DATE", "field": "period", "value": ["지난주"]},
                {
                    "kind": "USER_REQUIREMENT",
                    "field": "search_terms",
                    "value": ["프로젝트", "일정"],
                },
            ],
        },
        work_analysis={"ambiguities": []},
        evidence=[],
        retrieval_result={
            "coverage": "PARTIAL",
            "source_statuses": [{"status": "COMPLETE", "failure_kind": None}],
            "missing_information": [
                {
                    "code": "required_source_evidence",
                    "description": "검색 결과가 없습니다.",
                    "required_for": "RETRIEVAL",
                    "reason_codes": ["REQUIRED_SOURCE_RETURNED_NO_RESOURCES"],
                }
            ],
        },
        invoke=invoke,
    )

    assert captured["prompt_id"] == "planning.outline_answer"
    prompt_input = cast(dict[str, object], captured["prompt_input"])
    assert prompt_input["coverage"] == "PARTIAL"
    assert prompt_input["source_statuses"] == [{"status": "COMPLETE", "failure_kind": None}]
    assert prompt_input["missing_information"] == [
        {
            "code": "required_source_evidence",
            "description": "검색 결과가 없습니다.",
            "required_for": "RETRIEVAL",
            "reason_codes": ["REQUIRED_SOURCE_RETURNED_NO_RESOURCES"],
        }
    ]
    assert result == {"sections": ["확인된 검색 결과 없음"], "evidence_refs": []}


def test_outline_analysis_read__current_work_facts__preserves_for_composition() -> None:
    result = outline_answer(
        user_request="회의 메일을 분석해 일정과 후속 작업을 정리해줘.",
        request_intent={"goal": "회의 분석", "analysis_requirement": "REQUIRED"},
        work_analysis={
            "work_facts": [
                {
                    "fact_id": "f-time",
                    "kind": "TIME",
                    "subject": "1차 회의 시작",
                    "value": "오전 11시 14분",
                    "derivation": "EXPLICIT",
                    "evidence_refs": ["e-time"],
                },
                {
                    "fact_id": "f-action",
                    "kind": "TASK",
                    "subject": "후속 작업",
                    "value": "박희정이 와이어프레임을 삽입하고 검토한다",
                    "derivation": "EXPLICIT",
                    "evidence_refs": ["e-action"],
                },
            ],
            "ambiguities": [],
        },
        evidence=[{"evidence_id": "e-time"}, {"evidence_id": "e-action"}],
        invoke=lambda _prompt_id, _prompt_input: {
            "sections": ["결론"],
            "evidence_refs": ["e-time"],
        },
    )

    assert result == {
        "sections": [
            "결론",
            "확인된 업무 사실 — 1차 회의 시작: 오전 11시 14분",
            "확인된 업무 사실 — 후속 작업: 박희정이 와이어프레임을 삽입하고 검토한다",
        ],
        "evidence_refs": ["e-time", "e-action"],
    }


def test_gmail_read__with_required_information__uses_semantic_outline() -> None:
    captured: dict[str, object] = {}

    def invoke(prompt_id: str, prompt_input: Mapping[str, object]) -> Mapping[str, object]:
        captured.update({"prompt_id": prompt_id, "prompt_input": dict(prompt_input)})
        return {"sections": ["명시된 결정과 정정"], "evidence_refs": ["e-decision"]}

    result = outline_answer(
        user_request="KAN-93 관련 메일 중 최신 결정을 알려줘.",
        request_intent={
            "requested_effect_hints": ["READ"],
            "requested_resource_hints": ["GMAIL_THREAD"],
            "constraints": [
                {
                    "kind": "USER_REQUIREMENT",
                    "field": "required_information",
                    "value": ["최신 결정"],
                }
            ],
            "analysis_requirement": "REQUIRED",
        },
        work_analysis={"work_facts": [{"fact_id": "fact-internal"}]},
        evidence=[
            {"evidence_id": "e-status", "excerpt": "상태: 해야 할 일 → 진행"},
            {"evidence_id": "e-decision", "excerpt": "네비게이션바로 확정"},
        ],
        invoke=invoke,
    )

    assert captured["prompt_id"] == "planning.outline_answer"
    assert result == {
        "sections": ["명시된 결정과 정정"],
        "evidence_refs": ["e-decision"],
    }


def test_gmail_lookup__unrequested_timeline__does_not_require_analysis() -> None:
    invoked = False

    def invoke(
        _prompt_id: str, _prompt_input: Mapping[str, object]
    ) -> Mapping[str, object]:
        nonlocal invoked
        invoked = True
        return {"sections": ["찾은 메일"], "evidence_refs": ["e-mail"]}

    result = outline_answer(
        user_request="김대리 일정 관련 메일 찾아줘.",
        request_intent={
            "requested_effect_hints": ["READ"],
            "requested_resource_hints": ["GMAIL_THREAD"],
            "analysis_requirement": "NONE",
            "constraints": [],
        },
        work_analysis=None,
        evidence=[{"evidence_id": "e-mail", "excerpt": "김철수 대리의 박람회 참석 안내"}],
        invoke=cast(PlanningSemanticInvoker, invoke),
    )
    assert invoked is False
    assert result == {
        "sections": ["김대리 일정 관련 메일 찾아줘."],
        "evidence_refs": ["e-mail"],
    }
