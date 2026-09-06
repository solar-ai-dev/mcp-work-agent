from __future__ import annotations

from collections.abc import Mapping

import pytest

from google_work_agent.application.agents.planning.compose_answer import (
    MAX_USER_VISIBLE_ANSWER_CHARS,
    answer_draft_output_schema,
    compose_answer,
)


def test_answer_draft_schema__binds_citations__to_approved_outline() -> None:
    schema = answer_draft_output_schema(["e2", "e1", "e1"])
    properties = schema.json_schema["properties"]

    assert properties["evidence_refs"] == {
        "type": "array",
        "uniqueItems": True,
        "maxItems": 2,
        "items": {"type": "string", "enum": ["e1", "e2"]},
    }
    assert properties["answer"] == {
        "type": "string",
        "minLength": 1,
        "maxLength": MAX_USER_VISIBLE_ANSWER_CHARS,
    }


@pytest.mark.parametrize("uncertain", [False, True])
def test_partial_source_answer__preserves_yearless_date__without_another_model_call(
    uncertain: bool,
) -> None:
    def forbidden(prompt_id: str, prompt_input: Mapping[str, object]) -> Mapping[str, object]:
        raise AssertionError("a bounded source projection needs no further inference")

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
        invoke=forbidden,
        retrieval_result=retrieval,
    )
    assert answer["evidence_refs"] == ["e1"]
    assert "연수는 9월 4일입니다." in answer["answer"]
    assert "2026년 9월 4일" not in answer["answer"]
    assert "수신 시각:" in answer["answer"]
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
                "repository": "sample/project", "repository_id": 2, "account_id": "github:1",
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
        "user_request", "request_intent", "answer_outline", "evidence", "temporal_constraints",
    }


def test_source_projection__reports_omitted_text__without_citing_invisible_evidence() -> None:
    answer = compose_answer(
        user_request="메일 목록",
        request_intent={"requested_effect_hints": ["READ"]},
        answer_outline={"sections": ["자료"], "evidence_refs": ["e1", "e2"]},
        work_analysis=None,
        evidence=[{"evidence_id": "e1", "excerpt": "짧은 원문"},
                  {"evidence_id": "e2", "excerpt": "긴 원문" * MAX_USER_VISIBLE_ANSWER_CHARS}],
        invoke=lambda *_: pytest.fail("source projection must not call inference"),
        retrieval_result={"coverage": "PARTIAL"},
    )
    assert "일부 원문은 생략" in answer["answer"]
    assert "짧은 원문" in answer["answer"]
    assert answer["evidence_refs"] == ["e1"]
    assert len(answer["answer"]) <= MAX_USER_VISIBLE_ANSWER_CHARS


def test_confirmed_person__narrows_answer_projection__without_deleting_run_evidence() -> None:
    def invoke(prompt_id: str, prompt_input: Mapping[str, object]) -> Mapping[str, object]:
        assert prompt_input["selected_person_identities"] == {"김대리": "second@example.test"}
        assert prompt_input["answer_outline"] == {"sections": ["메일"], "evidence_refs": ["e2"]}
        assert prompt_input["evidence"] == [
            {"evidence_id": "e2", "segment_id": "s2", "excerpt": "B"}
        ]
        return {"schema_version": 2, "answer": "B", "evidence_refs": ["e2"]}

    evidence = [{"evidence_id": "e1", "segment_id": "s1", "excerpt": "A"},
                {"evidence_id": "e2", "segment_id": "s2", "excerpt": "B"}]
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

    def invoke(_prompt_id: str, prompt_input: Mapping[str, object]) -> Mapping[str, object]:
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

    def invoke(_prompt_id: str, prompt_input: Mapping[str, object]) -> Mapping[str, object]:
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


def test_gmail_read__with_intermediate_analysis__omits_it_from_final_prompt() -> None:
    invoked = False

    def invoke(_prompt_id: str, _prompt_input: Mapping[str, object]) -> Mapping[str, object]:
        nonlocal invoked
        invoked = True
        return {}

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

    assert invoked is False
    assert result["answer"] == (
        "관련 Gmail 자료에서 결정 또는 확정으로 명시된 내용은 다음과 같습니다.\n\n"
        "- 네비게이션바로 확정"
    )


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


def test_compose_gmail_read__empty_result__explains_without_llm() -> None:
    invoked = False

    def invoke(_prompt_id: str, _prompt_input: Mapping[str, object]) -> Mapping[str, object]:
        nonlocal invoked
        invoked = True
        return {}

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
            "missing_information": [{"description": "REQUIRED_SOURCE_RETURNED_NO_RESOURCES"}],
        },
        invoke=invoke,
    )

    assert invoked is False
    assert result["answer"] == (
        "'지난주 · 프로젝트 · 일정' 조건으로 Gmail을 검색했지만 관련 자료를 찾지 "
        "못했습니다. 검색어나 기간을 넓혀 다시 요청해 주세요."
    )


def test_compose_rejects__evidence_not__approved_by_outline() -> None:
    with pytest.raises(ValueError, match="outside"):
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

    def invoke(_prompt_id: str, _prompt_input: Mapping[str, object]) -> Mapping[str, object]:
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
