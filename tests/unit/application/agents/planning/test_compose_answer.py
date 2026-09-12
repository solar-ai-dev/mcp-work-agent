from __future__ import annotations

from collections.abc import Mapping
from typing import Any, cast

import pytest

from google_work_agent.application.agents.planning.compose_answer import (
    MAX_USER_VISIBLE_ANSWER_CHARS,
    answer_draft_output_schema,
    answer_semantic_repair_output_schema,
    compose_answer,
)


def test_answer_draft_schema__binds_citations__to_approved_outline() -> None:
    schema = answer_draft_output_schema(["e2", "e1", "e1"])
    properties = cast(dict[str, Any], schema.json_schema)["properties"]

    assert properties["evidence_refs"] == {
        "type": "array",
        "uniqueItems": True,
        "maxItems": 2,
        "items": {"type": "string", "enum": ["e1", "e2"]},
    }
    assert properties["answer"] == {
        "type": "string",
        "description": (
            "Final user-visible prose only. Do not include JSON, XML, objects, arrays, "
            "serialized schemas, or code blocks in this string."
        ),
        "minLength": 1,
        "maxLength": MAX_USER_VISIBLE_ANSWER_CHARS,
    }


def test_answer_semantic_repair_schema__binds_citations__without_answer_field() -> None:
    schema = answer_semantic_repair_output_schema(["e2", "e1", "e1"])
    properties = cast(dict[str, Any], schema.json_schema)["properties"]

    assert "answer" not in properties
    assert properties["evidence_refs"] == {
        "type": "array",
        "uniqueItems": True,
        "maxItems": 2,
        "items": {"type": "string", "enum": ["e1", "e2"]},
    }
    assert cast(dict[str, Any], properties["sections"])["minItems"] == 1


@pytest.mark.parametrize("uncertain", [False, True])
def test_partial_source_answer__preserves_yearless_date__through_answer_prompt(
    uncertain: bool,
) -> None:
    calls: list[str] = []

    def invoke(prompt_id: str, prompt_input: Mapping[str, object]) -> Mapping[str, object]:
        calls.append(prompt_id)
        assert prompt_input["coverage"] == "PARTIAL"
        if uncertain:
            assert prompt_input["unresolved_event_dates"] == retrieval["unresolved_event_dates"]
        return {"schema_version": 2, "answer": "연수는 9월 4일입니다.", "evidence_refs": ["e1"]}

    retrieval: dict[str, object] = {"coverage": "PARTIAL"}
    if uncertain:
        retrieval["unresolved_event_dates"] = [{"evidence_id": "e1", "source_text": "9월 4일"}]
    answer = compose_answer(
        user_request="9월 첫째주 일정",
        request_intent={"requested_effect_hints": ["READ"]},
        answer_outline={"sections": ["확인한 자료"], "evidence_refs": ["e1"]},
        work_analysis=None,
        evidence=[
            {
                "evidence_id": "e1",
                "excerpt": "Received: 2026-08-26T09:00:00+09:00\n연수는 9월 4일입니다.",
            }
        ],
        invoke=invoke,
        retrieval_result=retrieval,
    )
    assert answer["evidence_refs"] == ["e1"]
    assert "연수는 9월 4일입니다." in answer["answer"]
    assert "2026년 9월 4일" not in answer["answer"]
    assert calls == ["planning.compose_answer"]
    assert "Received:" not in answer["answer"]
    assert "확인한 자료 원문" not in answer["answer"]
    assert "부분 결과" in answer["answer"]


def test_compose_uses__approved_outline_and__emits_v2_candidate() -> None:
    captured: dict[str, object] = {}

    def invoke(prompt_id: str, prompt_input: Mapping[str, object]) -> Mapping[str, object]:
        captured.update({"prompt_id": prompt_id, "prompt_input": dict(prompt_input)})
        return {"schema_version": 2, "answer": "Grounded answer", "evidence_refs": ["e1"]}

    result = compose_answer(
        user_request="Summarize.",
        request_intent={
            "goal": "summary",
            "repository_default": {
                "repository": "sample/project",
                "repository_id": 2,
                "account_id": "github:1",
            },
        },
        answer_outline={"sections": ["Conclusion"], "evidence_refs": ["e1"]},
        work_analysis=None,
        evidence=[{"evidence_id": "e1", "excerpt": "fact"}],
        invoke=invoke,
    )

    assert result["schema_version"] == 2
    assert captured["prompt_id"] == "planning.compose_answer"
    prompt_input = captured["prompt_input"]
    assert isinstance(prompt_input, dict)
    assert prompt_input["request_intent"] == {"goal": "summary"}
    assert set(prompt_input) == {
        "user_request",
        "request_intent",
        "answer_outline",
        "evidence",
        "temporal_constraints",
    }


def test_compose_answer__collection_continuation__does_not_force_single_answer_partial() -> None:
    captured: dict[str, object] = {}

    def invoke(prompt_id: str, prompt_input: Mapping[str, object]) -> Mapping[str, object]:
        captured.update({"prompt_id": prompt_id, "prompt_input": dict(prompt_input)})
        return {"schema_version": 2, "answer": "최신 상태는 준비 완료입니다.", "evidence_refs": []}

    result = compose_answer(
        user_request="가장 최근 상태 하나만 알려줘.",
        request_intent={"requested_effect_hints": ["READ"]},
        answer_outline={"sections": ["최신 상태"], "evidence_refs": []},
        work_analysis=None,
        evidence=[],
        invoke=invoke,
        retrieval_result={
            "coverage": "SUFFICIENT",
            "collection_results": [
                {
                    "route_id": "route-1",
                    "resource_type": "gmail_thread",
                    "continuation_status": "HAS_MORE",
                    "items": [
                        {
                            "resource_ref": "gmail_thread:first",
                            "resource_type": "gmail_thread",
                            "title": "최신 상태",
                        }
                    ],
                }
            ],
        },
    )

    projection = cast(dict[str, object], captured["prompt_input"])
    assert projection["collection_results"] == [
        {
            "resource_type": "gmail_thread",
            "continuation_status": "HAS_MORE",
            "items": [{"item_number": 1, "title": "최신 상태"}],
        }
    ]
    assert result["answer"] == "최신 상태는 준비 완료입니다."


def test_compose_collection__accepts_relevant_subset_and_order__without_rewriting_answer() -> None:
    captured: dict[str, object] = {}

    def invoke(prompt_id: str, prompt_input: Mapping[str, object]) -> Mapping[str, object]:
        captured.update({"prompt_id": prompt_id, "prompt_input": dict(prompt_input)})
        return {
            "schema_version": 2,
            "answer": "관련 항목은 C, A 순서입니다.",
            "evidence_refs": [],
        }

    result = compose_answer(
        user_request="관련된 제목만 중요도순으로 알려줘.",
        request_intent={"requested_effect_hints": ["READ"]},
        answer_outline={"sections": ["관련: C", "관련: A"], "evidence_refs": []},
        work_analysis=None,
        evidence=[],
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
        invoke=invoke,
    )

    projection = cast(dict[str, object], captured["prompt_input"])
    collection = cast(list[dict[str, object]], projection["collection_results"])[0]
    assert [item["title"] for item in cast(list[dict[str, object]], collection["items"])] == [
        "A",
        "B",
        "C",
    ]
    assert result["answer"] == "관련 항목은 C, A 순서입니다."


@pytest.mark.parametrize(
    "answer",
    [
        "연수는 2026년 9월 4일입니다.",
        "연수는 2026-09-04T14:00:00+09:00입니다. 연도는 미확정입니다.",
        "연수는 9월 4일 금요일입니다.",
        "연수는 9월 4일(금)입니다.",
    ],
)
def test_compose_answer__promoted_yearless_date__rejects_even_with_disclaimer(answer: str) -> None:
    with pytest.raises(ValueError, match="unresolved event date"):
        compose_answer(
            user_request="연수 일정",
            request_intent={"requested_effect_hints": ["READ"]},
            answer_outline={"sections": ["일정"], "evidence_refs": ["e1"]},
            work_analysis=None,
            evidence=[{"evidence_id": "e1", "excerpt": "9월 4일 연수"}],
            retrieval_result={
                "unresolved_event_dates": [{"evidence_id": "e1", "source_text": "9월 4일"}]
            },
            invoke=lambda *_: {"schema_version": 2, "answer": answer, "evidence_refs": ["e1"]},
        )


def test_compose_answer__yearless_date_in_parentheses__is_not_a_weekday_claim() -> None:
    result = compose_answer(
        user_request="9월 첫째주 연수 날짜",
        request_intent={"requested_effect_hints": ["READ"]},
        answer_outline={"sections": ["연수"], "evidence_refs": ["e1"]},
        work_analysis=None,
        evidence=[{"evidence_id": "e1", "excerpt": "연수는 9월 5일입니다."}],
        retrieval_result={
            "unresolved_event_dates": [{"evidence_id": "e1", "source_text": "9월 5일"}]
        },
        invoke=lambda *_: {
            "schema_version": 2,
            "answer": "연수 일정(9월 5일)은 확인됐지만 연도는 미확정입니다.",
            "evidence_refs": ["e1"],
        },
    )

    assert "9월 5일" in result["answer"]


def test_partial_answer__summarizes_long_sources__without_copying_them() -> None:
    answer = compose_answer(
        user_request="메일 목록",
        request_intent={"requested_effect_hints": ["READ"]},
        answer_outline={"sections": ["자료"], "evidence_refs": ["e1", "e2"]},
        work_analysis=None,
        evidence=[
            {"evidence_id": "e1", "excerpt": "짧은 원문"},
            {"evidence_id": "e2", "excerpt": "긴 원문" * MAX_USER_VISIBLE_ANSWER_CHARS},
        ],
        invoke=lambda *_: {
            "schema_version": 2,
            "answer": "첫 자료에서 확인한 내용입니다.",
            "evidence_refs": ["e1"],
        },
        retrieval_result={"coverage": "PARTIAL"},
    )
    assert "첫 자료에서 확인한 내용" in answer["answer"]
    assert "긴 원문" not in answer["answer"]
    assert answer["evidence_refs"] == ["e1"]
    assert len(answer["answer"]) <= MAX_USER_VISIBLE_ANSWER_CHARS


def test_compose_answer__resource_id_as_sender__omits_diagnostic_without_corrupting_title() -> None:
    result = compose_answer(
        user_request="메일 요약",
        request_intent={},
        answer_outline={"sections": ["메일"], "evidence_refs": ["e1"]},
        work_analysis=None,
        evidence=[
            {
                "evidence_id": "e1",
                "resource_handle": "gmail_thread:fixture1",
                "excerpt": "Release1 연수 안내",
            }
        ],
        invoke=lambda *_: {
            "schema_version": 2,
            "answer": "발신:_fixture1_\nRelease1 연수 안내",
            "evidence_refs": ["e1"],
        },
    )
    assert result["answer"] == "Release1 연수 안내"


def test_confirmed_person__narrows_answer_projection__without_deleting_run_evidence() -> None:
    def invoke(prompt_id: str, prompt_input: Mapping[str, object]) -> Mapping[str, object]:
        assert prompt_input["selected_person_identities"] == {"김대리": "second@example.test"}
        assert prompt_input["answer_outline"] == {"sections": ["메일"], "evidence_refs": ["e2"]}
        assert prompt_input["evidence"] == [
            {"evidence_id": "e2", "segment_id": "s2", "excerpt": "B"}
        ]
        return {"schema_version": 2, "answer": "B", "evidence_refs": ["e2"]}

    evidence = [
        {"evidence_id": "e1", "segment_id": "s1", "excerpt": "A"},
        {"evidence_id": "e2", "segment_id": "s2", "excerpt": "B"},
    ]
    result = compose_answer(
        user_request="김대리 메일",
        request_intent={},
        answer_outline={"sections": ["메일"], "evidence_refs": ["e1", "e2"]},
        work_analysis=None,
        evidence=evidence,
        invoke=invoke,
        retrieval_result={
            "selected_person_identities": {"김대리": "second@example.test"},
            "person_candidates": [
                {
                    "mention": "김대리",
                    "identity": "first@example.test",
                    "source_segment_ids": ["s1"],
                },
                {
                    "mention": "김대리",
                    "identity": "second@example.test",
                    "source_segment_ids": ["s2"],
                },
            ],
        },
    )
    assert result["evidence_refs"] == ["e2"]
    assert len(evidence) == 2


@pytest.mark.parametrize(
    "retrieval",
    [
        None,
        {"temporal_constraints": []},
        {
            "temporal_constraints": [
                {
                    "kind": "TEMPORAL_RANGE",
                    "axis": "EVENT_TIME",
                    "start_local": "2026-09-01T00:00:00",
                    "end_local": "2026-09-08T00:00:00",
                    "timezone": "Asia/Seoul",
                }
            ]
        },
    ],
)
def test_compose_answer__resolved_period__preserves_without_inventing_legacy_bounds(
    retrieval: dict[str, object] | None,
) -> None:
    captured: dict[str, object] = {}

    def invoke(prompt_id: str, prompt_input: Mapping[str, object]) -> Mapping[str, object]:
        del prompt_id
        captured.update(prompt_input)
        return {"schema_version": 2, "answer": "확인한 자료의 일정입니다.", "evidence_refs": ["e1"]}

    compose_answer(
        user_request="9월 첫째주 일정 관련 메일 찾아줘.",
        request_intent={"goal": "일정"},
        answer_outline={"sections": ["일정"], "evidence_refs": ["e1"]},
        work_analysis=None,
        evidence=[{"evidence_id": "e1", "excerpt": "9월 3일 행사"}],
        invoke=invoke,
        retrieval_result=retrieval,
    )
    assert captured["temporal_constraints"] == (
        [] if retrieval is None else retrieval["temporal_constraints"]
    )


def test_compose_answer__with_unapproved_evidence__projects_only_outline_refs() -> None:
    captured: dict[str, object] = {}

    def invoke(prompt_id: str, prompt_input: Mapping[str, object]) -> Mapping[str, object]:
        del prompt_id
        captured.update(prompt_input)
        return {
            "schema_version": 2,
            "answer": "네비게이션바로 확정되었습니다.",
            "evidence_refs": ["e-decision"],
        }

    compose_answer(
        user_request="최신 결정을 알려줘.",
        request_intent={"goal": "latest decision"},
        answer_outline={"sections": ["최신 결정"], "evidence_refs": ["e-decision"]},
        work_analysis=None,
        evidence=[
            {"evidence_id": "e-metadata", "excerpt": "오후 1:51 업무 항목 생성"},
            {"evidence_id": "e-decision", "excerpt": "네비게이션바로 확정"},
        ],
        invoke=invoke,
    )

    assert captured["evidence"] == [{"evidence_id": "e-decision", "excerpt": "네비게이션바로 확정"}]


def test_compose_answer__surrounding_whitespace__normalizes() -> None:
    result = compose_answer(
        user_request="요약해줘.",
        request_intent={"goal": "summary"},
        answer_outline={"sections": ["핵심"], "evidence_refs": ["e1"]},
        work_analysis=None,
        evidence=[{"evidence_id": "e1"}],
        invoke=lambda _prompt_id, _prompt_input: {
            "schema_version": 2,
            "answer": "\n  확인한 메일을 요약했습니다.  \n",
            "evidence_refs": ["e1"],
        },
    )

    assert result["answer"] == "확인한 메일을 요약했습니다."


def test_compose_answer__internal_refs_and_reason_codes__removes() -> None:
    result = compose_answer(
        user_request="메일 근거를 요약해줘.",
        request_intent={"goal": "summary"},
        answer_outline={"sections": ["핵심"], "evidence_refs": ["evidence-seg_deadbeef"]},
        work_analysis=None,
        evidence=[{"evidence_id": "evidence-seg_deadbeef"}],
        invoke=lambda _prompt_id, _prompt_input: {
            "schema_version": 2,
            "answer": (
                "evidence-seg_deadbeef에서 REQUIRED_SOURCE_RETURNED_NO_RESOURCES를 확인했습니다."
            ),
            "evidence_refs": ["evidence-seg_deadbeef"],
        },
    )

    assert result["answer"] == "확인한 자료에서 내부 상태를 확인했습니다."


def test_compose_reference_labels__english_request__preserves_language() -> None:
    result = compose_answer(
        user_request="Summarize the email evidence.",
        request_intent={"goal": "summary"},
        answer_outline={"sections": ["Summary"], "evidence_refs": ["evidence-seg_1"]},
        work_analysis=None,
        evidence=[{"evidence_id": "evidence-seg_1"}],
        invoke=lambda _prompt_id, _prompt_input: {
            "schema_version": 2,
            "answer": "evidence-seg_1 has REQUIRED_SOURCE_EVIDENCE.",
            "evidence_refs": ["evidence-seg_1"],
        },
    )

    assert result["answer"] == "the reviewed material has an internal status."


def test_gmail_read__with_intermediate_analysis__uses_semantic_composition() -> None:
    captured: dict[str, object] = {}

    def invoke(prompt_id: str, prompt_input: Mapping[str, object]) -> Mapping[str, object]:
        captured.update({"prompt_id": prompt_id, "prompt_input": dict(prompt_input)})
        return {
            "schema_version": 2,
            "answer": "근거에서 네비게이션바 확정을 확인했습니다.",
            "evidence_refs": ["e-decision"],
        }

    result = compose_answer(
        user_request="KAN-93 관련 메일 중 최신 결정을 알려줘.",
        request_intent={
            "requested_effect_hints": ["READ"],
            "requested_resource_hints": ["GMAIL_THREAD"],
            "analysis_requirement": "REQUIRED",
        },
        answer_outline={"sections": ["최신 결정"], "evidence_refs": ["e-decision"]},
        work_analysis={"work_facts": [{"fact_id": "fact-internal", "value": "근거 없는 마감일"}]},
        evidence=[{"evidence_id": "e-decision", "excerpt": "네비게이션바로 확정"}],
        invoke=invoke,
    )

    assert captured["prompt_id"] == "planning.compose_answer"
    prompt_input = captured["prompt_input"]
    assert isinstance(prompt_input, dict)
    assert prompt_input["work_analysis"] == {
        "work_facts": [{"fact_id": "fact-internal", "value": "근거 없는 마감일"}]
    }
    assert result["answer"] == "근거에서 네비게이션바 확정을 확인했습니다."


def test_compose_answer__with_internal_fact_terms__removes_them_from_prose() -> None:
    result = compose_answer(
        user_request="메일을 요약해줘.",
        request_intent={"goal": "summary"},
        answer_outline={"sections": ["핵심"], "evidence_refs": ["e1"]},
        work_analysis=None,
        evidence=[{"evidence_id": "e1"}],
        invoke=lambda _prompt_id, _prompt_input: {
            "schema_version": 2,
            "answer": "`fact-deadbeef`와 `work_facts`, `risks`를 확인했습니다.",
            "evidence_refs": ["e1"],
        },
    )

    assert "fact-deadbeef" not in result["answer"]
    assert "work_facts" not in result["answer"]
    assert "risks" not in result["answer"]


def test_korean_answer__with_ungrounded_foreign_script__removes_only_generated_text() -> None:
    result = compose_answer(
        user_request="메일을 한국어로 요약해줘.",
        request_intent={"goal": "summary"},
        answer_outline={"sections": ["핵심"], "evidence_refs": ["e1"]},
        work_analysis=None,
        evidence=[{"evidence_id": "e1", "excerpt": "담당자 王敏, 완료 시점은 미정"}],
        invoke=lambda _prompt_id, _prompt_input: {
            "schema_version": 2,
            "answer": "담당자는 王敏이며 완료 시点是 명시되지 않았습니다.",
            "evidence_refs": ["e1"],
        },
    )

    assert result["answer"] == "담당자는 王敏이며 완료 시 명시되지 않았습니다."


def test_compose_answer__with_internal_thread_id__removes_resource_identity() -> None:
    result = compose_answer(
        user_request="메일을 요약해줘.",
        request_intent={"goal": "summary"},
        answer_outline={"sections": ["핵심"], "evidence_refs": ["e1"]},
        work_analysis=None,
        evidence=[{"evidence_id": "e1"}],
        invoke=lambda _prompt_id, _prompt_input: {
            "schema_version": 2,
            "answer": "선택한 Gmail 스레드 (THREAD ID: abc123) 내용을 요약했습니다.",
            "evidence_refs": ["e1"],
        },
    )

    assert result["answer"] == "선택한 Gmail 스레드 내용을 요약했습니다."


def test_compose_gmail_read__empty_result__uses_observed_state_without_fixed_retry_text() -> None:
    captured: dict[str, object] = {}

    def invoke(prompt_id: str, prompt_input: Mapping[str, object]) -> Mapping[str, object]:
        captured.update({"prompt_id": prompt_id, "prompt_input": dict(prompt_input)})
        return {
            "schema_version": 2,
            "answer": "확인한 범위에서는 관련 메일이 조회되지 않았습니다.",
            "evidence_refs": [],
        }

    result = compose_answer(
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
        answer_outline={"sections": ["검색 결과 없음"], "evidence_refs": []},
        work_analysis=None,
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

    assert captured["prompt_id"] == "planning.compose_answer"
    prompt_input = cast(dict[str, object], captured["prompt_input"])
    assert prompt_input["coverage"] == "PARTIAL"
    assert prompt_input["source_statuses"] == [{"status": "COMPLETE", "failure_kind": None}]
    assert "검색어나 기간을 넓혀" not in result["answer"]
    assert "관련 메일이 조회되지 않았습니다" in result["answer"]


@pytest.mark.parametrize(
    ("coverage", "scope_complete", "expected_notice"),
    [
        (
            "PARTIAL",
            False,
            "조회 범위 2개를 확인했고, 확인한 범위에서는 관련 항목을 찾지 못했습니다. "
            "전체 검색은 완료되지 않았습니다.",
        ),
        (
            "SUFFICIENT",
            True,
            "접근 가능한 전체 범위를 확인했지만 관련 항목을 찾지 못했습니다.",
        ),
    ],
)
def test_compose_empty_result__distinguishes_complete_and_partial_scope(
    coverage: str,
    scope_complete: bool,
    expected_notice: str,
) -> None:
    result = compose_answer(
        user_request="관련 자료를 찾아줘.",
        request_intent={"requested_effect_hints": ["READ"]},
        answer_outline={"sections": ["검색 결과"], "evidence_refs": []},
        work_analysis=None,
        evidence=[],
        retrieval_result={
            "coverage": coverage,
            "source_statuses": [
                {
                    "status": "COMPLETE" if scope_complete else "PARTIAL",
                    "failure_kind": None,
                    "checked_read_count": 2,
                    "known_scope_count": 2 if scope_complete else 3,
                    "observed_resource_count": 0,
                    "scope_complete": scope_complete,
                    "continuation_status": "EXHAUSTED" if scope_complete else "UNKNOWN",
                }
            ],
        },
        invoke=lambda _prompt_id, _prompt_input: {
            "schema_version": 2,
            "answer": "관련 항목이 확인되지 않았습니다.",
            "evidence_refs": [],
        },
    )

    assert expected_notice in result["answer"]


def test_compose_rejects__evidence_not__approved_by_outline() -> None:
    with pytest.raises(ValueError, match="outside") as raised:
        compose_answer(
            user_request="Summarize.",
            request_intent={"goal": "summary"},
            answer_outline={"sections": ["Conclusion"], "evidence_refs": []},
            work_analysis=None,
            evidence=[{"evidence_id": "e1"}],
            invoke=lambda _prompt_id, _prompt_input: {
                "schema_version": 2,
                "answer": "Unsupported",
                "evidence_refs": ["e1"],
            },
        )
    assert raised.value.reason_code == "COMPOSE_ANSWER_EVIDENCE_SCOPE_INVALID"
    assert raised.value.affected_field_paths == ("$.evidence_refs",)


def test_compose_rejects__serialized_internal_object__as_user_answer() -> None:
    with pytest.raises(ValueError, match="user-visible prose"):
        compose_answer(
            user_request="요약해줘.",
            request_intent={"goal": "summary"},
            answer_outline={"sections": ["핵심"], "evidence_refs": ["e1"]},
            work_analysis=None,
            evidence=[{"evidence_id": "e1"}],
            invoke=lambda _prompt_id, _prompt_input: {
                "schema_version": 2,
                "answer": '  {"sections":[],"evidence_refs":["e1"]}',
                "evidence_refs": ["e1"],
            },
        )


def test_compose_answer__prose_failure__renders_one_structured_repair_without_raw_answer() -> None:
    invalid_answer = '{"sections":[],"evidence_refs":["e1"]}'
    projections: list[Mapping[str, object]] = []

    def invoke(_prompt_id: str, prompt_input: Mapping[str, object]) -> Mapping[str, object]:
        projections.append(prompt_input)
        if len(projections) == 1:
            return {
                "schema_version": 2,
                "answer": invalid_answer,
                "evidence_refs": ["e1"],
            }
        return {
            "schema_version": 1,
            "sections": [
                {
                    "heading": "확인 결과",
                    "items": [
                        {"label": "일정", "value": "9월 15일 오후 4시"},
                        {"label": "장소", "value": "3층 회의실 B"},
                        {"label": "요청사항", "value": "분기 보고서 초안 검토"},
                    ],
                }
            ],
            "evidence_refs": ["e1"],
        }

    result = compose_answer(
        user_request="선택한 메일의 핵심 내용을 3줄로 요약해줘",
        request_intent={"goal": "summary"},
        answer_outline={"sections": ["핵심 내용"], "evidence_refs": ["e1"]},
        work_analysis=None,
        evidence=[{"evidence_id": "e1", "excerpt": "회의 일정 안내"}],
        invoke=invoke,
    )

    assert result["answer"] == (
        "## 확인 결과\n- 일정: 9월 15일 오후 4시\n- 장소: 3층 회의실 B\n"
        "- 요청사항: 분기 보고서 초안 검토"
    )
    assert len(projections) == 2
    assert set(projections[1]) == {"base_projection", "candidate_output", "failure_record"}
    assert projections[1]["base_projection"] == projections[0]
    assert projections[1]["candidate_output"] is None
    failure = cast(Mapping[str, object], projections[1]["failure_record"])
    assert failure["failure_reason_code"] == "COMPOSE_ANSWER_PROSE_INVALID"
    assert failure["experiment_disposition"] == "RUN_REVISION"
    assert failure["affected_field_paths"] == ["$.answer"]
    assert invalid_answer not in repr(projections[1])


def test_compose_answer__prose_failure_twice__stops_after_one_revision() -> None:
    calls = 0

    def invoke(_prompt_id: str, _prompt_input: Mapping[str, object]) -> Mapping[str, object]:
        nonlocal calls
        calls += 1
        return {
            "schema_version": 2,
            "answer": '{"sections":[]}',
            "evidence_refs": ["e1"],
        }

    with pytest.raises(ValueError, match="user-visible prose") as raised:
        compose_answer(
            user_request="요약해줘.",
            request_intent={"goal": "summary"},
            answer_outline={"sections": ["핵심"], "evidence_refs": ["e1"]},
            work_analysis=None,
            evidence=[{"evidence_id": "e1"}],
            invoke=invoke,
        )

    assert calls == 2
    assert raised.value.reason_code == "COMPOSE_ANSWER_PROSE_INVALID"


def test_compose_answer__structured_repair__rejects_serialized_item_value() -> None:
    calls = 0

    def invoke(_prompt_id: str, _prompt_input: Mapping[str, object]) -> Mapping[str, object]:
        nonlocal calls
        calls += 1
        if calls == 1:
            return {
                "schema_version": 2,
                "answer": '{"sections":[]}',
                "evidence_refs": ["e1"],
            }
        return {
            "schema_version": 1,
            "sections": [
                {
                    "heading": "",
                    "items": [{"label": "", "value": '{"internal":"object"}'}],
                }
            ],
            "evidence_refs": ["e1"],
        }

    with pytest.raises(ValueError, match="user-visible prose") as raised:
        compose_answer(
            user_request="요약해줘.",
            request_intent={"goal": "summary"},
            answer_outline={"sections": ["핵심"], "evidence_refs": ["e1"]},
            work_analysis=None,
            evidence=[{"evidence_id": "e1"}],
            invoke=invoke,
        )

    assert calls == 2
    assert raised.value.reason_code == "COMPOSE_ANSWER_PROSE_INVALID"


def test_compose_answer__structured_repair__renders_serialized_semantic_collection() -> None:
    calls = 0

    def invoke(_prompt_id: str, _prompt_input: Mapping[str, object]) -> Mapping[str, object]:
        nonlocal calls
        calls += 1
        if calls == 1:
            return {
                "schema_version": 2,
                "answer": '{"sections":[]}',
                "evidence_refs": ["e1"],
            }
        return {
            "schema_version": 1,
            "sections": [
                {
                    "heading": "확인 결과",
                    "items": [
                        {
                            "label": "요약",
                            "value": '[{"항목":"첫 번째"},{"항목":"두 번째"}]',
                        }
                    ],
                }
            ],
            "evidence_refs": ["e1"],
        }

    result = compose_answer(
        user_request="핵심 내용을 알려줘.",
        request_intent={"goal": "내용 확인"},
        answer_outline={"sections": ["핵심"], "evidence_refs": ["e1"]},
        work_analysis=None,
        evidence=[{"evidence_id": "e1"}],
        invoke=invoke,
    )

    assert calls == 2
    assert result == {
        "schema_version": 2,
        "answer": "## 확인 결과\n- 요약: 항목: 첫 번째; 항목: 두 번째",
        "evidence_refs": ["e1"],
    }


def test_compose_answer__structured_repair__omits_serialized_optional_decorations() -> None:
    calls = 0

    def invoke(_prompt_id: str, _prompt_input: Mapping[str, object]) -> Mapping[str, object]:
        nonlocal calls
        calls += 1
        if calls == 1:
            return {
                "schema_version": 2,
                "answer": '{"sections":[]}',
                "evidence_refs": ["e1"],
            }
        return {
            "schema_version": 1,
            "sections": [
                {
                    "heading": '[{"section_title":"internal"}]',
                    "items": [
                        {
                            "label": '{"label":"internal"}',
                            "value": "회의 일정은 9월 15일 오후 4시입니다.",
                        }
                    ],
                }
            ],
            "evidence_refs": ["e1"],
        }

    result = compose_answer(
        user_request="회의 일정을 알려줘.",
        request_intent={"goal": "일정 확인"},
        answer_outline={"sections": ["일정"], "evidence_refs": ["e1"]},
        work_analysis=None,
        evidence=[{"evidence_id": "e1"}],
        invoke=invoke,
    )

    assert calls == 2
    assert result == {
        "schema_version": 2,
        "answer": "- 회의 일정은 9월 15일 오후 4시입니다.",
        "evidence_refs": ["e1"],
    }


def test_compose_answer__structured_repair__reuses_evidence_scope_validation() -> None:
    calls = 0

    def invoke(_prompt_id: str, _prompt_input: Mapping[str, object]) -> Mapping[str, object]:
        nonlocal calls
        calls += 1
        if calls == 1:
            return {
                "schema_version": 2,
                "answer": '{"sections":[]}',
                "evidence_refs": ["e1"],
            }
        return {
            "schema_version": 1,
            "sections": [
                {"heading": "", "items": [{"label": "", "value": "요약 내용"}]}
            ],
            "evidence_refs": ["outside"],
        }

    with pytest.raises(ValueError, match="outside") as raised:
        compose_answer(
            user_request="요약해줘.",
            request_intent={"goal": "summary"},
            answer_outline={"sections": ["핵심"], "evidence_refs": ["e1"]},
            work_analysis=None,
            evidence=[{"evidence_id": "e1"}],
            invoke=invoke,
        )

    assert calls == 2
    assert raised.value.reason_code == "COMPOSE_ANSWER_EVIDENCE_SCOPE_INVALID"


def test_compose_answer__non_prose_validation_failure__does_not_run_revision() -> None:
    calls = 0

    def invoke(_prompt_id: str, _prompt_input: Mapping[str, object]) -> Mapping[str, object]:
        nonlocal calls
        calls += 1
        return {
            "schema_version": 2,
            "answer": "확인한 내용을 요약했습니다.",
            "evidence_refs": ["outside"],
        }

    with pytest.raises(ValueError, match="outside") as raised:
        compose_answer(
            user_request="요약해줘.",
            request_intent={"goal": "summary"},
            answer_outline={"sections": ["핵심"], "evidence_refs": ["e1"]},
            work_analysis=None,
            evidence=[{"evidence_id": "e1"}],
            invoke=invoke,
        )

    assert calls == 1
    assert raised.value.reason_code == "COMPOSE_ANSWER_EVIDENCE_SCOPE_INVALID"


def test_compose_answer__with_nested_section_string__projects_natural_markdown() -> None:
    result = compose_answer(
        user_request="최신 결정을 알려줘.",
        request_intent={"goal": "latest decision"},
        answer_outline={"sections": ["최신 결정"], "evidence_refs": ["e1"]},
        work_analysis=None,
        evidence=[{"evidence_id": "e1"}],
        invoke=lambda _prompt_id, _prompt_input: {
            "schema_version": 2,
            "answer": """{
  \"sections\": [
    {
      \"section_title\": \"최신 결정\",
      \"content\": \"네비게이션바로 확정되었습니다.\n* 좌측: 로고\n* 우측: 알림\"
    }
  ],
  \"evidence_refs\": [\"e1\"]
}""",
            "evidence_refs": ["e1"],
        },
    )

    assert result["answer"] == (
        "## 최신 결정\n\n네비게이션바로 확정되었습니다.\n* 좌측: 로고\n* 우측: 알림"
    )
    assert "evidence_refs" not in result["answer"]


def test_compose_answer__over_visible_limit__rejects() -> None:
    with pytest.raises(ValueError, match="user-visible answer limit"):
        compose_answer(
            user_request="요약해줘.",
            request_intent={"goal": "summary"},
            answer_outline={"sections": ["핵심"], "evidence_refs": ["e1"]},
            work_analysis=None,
            evidence=[{"evidence_id": "e1"}],
            invoke=lambda _prompt_id, _prompt_input: {
                "schema_version": 2,
                "answer": "가" * (MAX_USER_VISIBLE_ANSWER_CHARS + 1),
                "evidence_refs": ["e1"],
            },
        )


def test_compose_task_read__concrete_evidence__projects_without_llm() -> None:
    invoked = False

    def invoke(prompt_id: str, prompt_input: Mapping[str, object]) -> Mapping[str, object]:
        del prompt_id, prompt_input
        nonlocal invoked
        invoked = True
        return {}

    result = compose_answer(
        user_request="Google Tasks 할 일을 목록으로 알려줘.",
        request_intent={
            "requested_effect_hints": ["READ"],
            "requested_resource_hints": ["TASK"],
            "analysis_requirement": "NONE",
        },
        answer_outline={"sections": ["현재 Google Tasks 할 일"], "evidence_refs": ["e1"]},
        work_analysis=None,
        evidence=[
            {
                "evidence_id": "e1",
                "resource_handle": "task:1",
                "excerpt": "보고서 제출",
            }
        ],
        invoke=invoke,
    )

    assert invoked is False
    assert result["answer"].endswith("- 보고서 제출")
