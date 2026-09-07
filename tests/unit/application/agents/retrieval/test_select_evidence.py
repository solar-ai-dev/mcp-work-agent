from collections import deque
from dataclasses import replace
from typing import cast

import pytest
from tests.support.context_retrieval import (
    SELECT_PROMPT_REF,
    FakeLLMRuntime,
    _intent,
    _llm_result,
    _run_budget,
)
from tests.support.evidence_assessment import evidence_assessment_output

from google_work_agent.application.agents.retrieval.contracts.query_attempt import QueryAttemptV1
from google_work_agent.application.agents.retrieval.normalize_segments import (
    ContextBudget,
    SourceSegment,
)
from google_work_agent.application.agents.retrieval.rag_retrieve_rerank import RagCandidateV1
from google_work_agent.application.agents.retrieval.select_evidence import (
    materialize_evidence_drafts,
    select_evidence,
)
from google_work_agent.ports.llm.output_schema_validation import validate_output_schema
from google_work_agent.ports.llm.structured_inference_contracts import OutputSchemaDefinition


def test_evidence_selection__no_candidates__does_not_invoke_model() -> None:
    runtime = FakeLLMRuntime(deque())
    budget = _run_budget(used=0)
    result, returned_budget = select_evidence(
        llm_runtime=runtime,
        prompt_ref=SELECT_PROMPT_REF,
        revision_prompt_ref=SELECT_PROMPT_REF,
        requested_mode="LOCAL_GPU",
        request_intent=_intent(),
        rag_candidates=[],
        segments=[],
        retry_budget=budget,
    )
    assert result == {
        "schema_version": 2,
        "selected_segment_ids": [],
        "excluded_segment_ids": [],
        "evidence_drafts": [],
    }
    assert returned_budget == budget
    assert runtime.calls == []


def test_search_candidate__metadata_only__is_context_not_a_business_fact() -> None:
    intent = _intent()
    intent["analysis_requirement"] = "NONE"
    intent["requested_effect_hints"] = ["READ"]
    runtime = FakeLLMRuntime(deque())
    result, _ = select_evidence(
        llm_runtime=runtime,
        prompt_ref=SELECT_PROMPT_REF,
        revision_prompt_ref=SELECT_PROMPT_REF,
        requested_mode="LOCAL_GPU",
        request_intent=intent,
        rag_candidates=[
            {
                "segment_id": "candidate",
                "resource_ref": "gmail_thread:1",
                "retrieval_score": 0.0,
                "reason_codes": [],
            }
        ],
        segments=[
            SourceSegment(
                "candidate",
                "gmail_thread:1",
                "GMAIL",
                "gmail_thread",
                "1",
                None,
                None,
                {"is_metadata_only": True},
                "unclear title",
            )
        ],
        retry_budget=_run_budget(used=0),
    )
    assert result["selected_segment_ids"] == ["candidate"]
    assert result["evidence_drafts"][0]["role"] == "CONTEXT"
    assert runtime.calls == []


@pytest.mark.parametrize("has_topic", [False, True])
def test_receipt_listing__uses_receipt_not_event_date__unless_content_is_requested(
    has_topic: bool,
) -> None:
    intent = _intent()
    intent["analysis_requirement"] = "NONE"
    intent["constraints"] = []
    if has_topic:
        intent["constraints"] = [
            {"kind": "USER_REQUIREMENT", "field": "search_terms", "value": ["계약"]}
        ]
    segments = [
        SourceSegment(
            "mail",
            "gmail_thread:1",
            "GMAIL",
            "gmail_thread",
            "1",
            None,
            None,
            {"received_at": "2026-09-03T09:00:00+09:00"},
            "행사는 2026년 10월 1일입니다.",
        )
    ]
    runtime = FakeLLMRuntime(
        deque(
            [
                _llm_result(
                    {
                        "schema_version": 3,
                        "segment_assessments": {
                            "mail": {"role": "EXCLUDED", "relevance_reason": "계약 내용이 없음"},
                        },
                    }
                )
            ]
        )
    )
    attempts = [
        cast(
            QueryAttemptV1,
            {
                "route_id": "gmail",
                "resource_type": "GMAIL_THREAD",
                "operation_kind": "SEARCH",
                "normalized_intent_constraints": [
                    {
                        "kind": "TEMPORAL_RANGE",
                        "axis": "MESSAGE_TIME",
                        "timezone": "Asia/Seoul",
                        "start_local": "2026-09-01T00:00:00",
                        "end_local": "2026-09-08T00:00:00",
                    }
                ],
            },
        )
    ]
    result, _ = select_evidence(
        llm_runtime=runtime,
        prompt_ref=SELECT_PROMPT_REF,
        revision_prompt_ref=SELECT_PROMPT_REF,
        requested_mode="LOCAL_GPU",
        request_intent=intent,
        rag_candidates=[
            {
                "segment_id": "mail",
                "resource_ref": "gmail_thread:1",
                "retrieval_score": 20.0,
                "reason_codes": [],
            }
        ],
        segments=segments,
        retry_budget=_run_budget(used=0),
        query_attempts=attempts,
    )
    assert result["selected_segment_ids"] == ([] if has_topic else ["mail"])
    assert len(runtime.calls) == int(has_topic)


@pytest.mark.parametrize(
    "invalid",
    [
        {},
        {"other": {"role": "CONTEXT", "relevance_reason": "존재하지 않는 후보"}},
        {"mail": {"role": "EXCLUDED", "relevance_reason": ""}},
    ],
)
def test_source_assessment__missing_invented_or_unjustified__uses_bounded_repair(
    invalid: dict[str, object],
) -> None:
    draft = {"segment_id": "mail", "role": "CONTEXT", "relevance_reason": "인물 후보"}
    repaired = {
        "schema_version": 2,
        "evidence_drafts": [draft],
        "selected_segment_ids": ["mail"],
        "excluded_segment_ids": [],
    }
    runtime = FakeLLMRuntime(
        deque(
            [
                _llm_result({"schema_version": 3, "segment_assessments": invalid}),
                _llm_result(evidence_assessment_output(repaired)),
            ]
        )
    )
    segment = SourceSegment(
        "mail",
        "gmail_thread:1",
        "GMAIL",
        "gmail_thread",
        "1",
        None,
        None,
        {},
        "김철수 대리의 박람회 참석 안내",
    )
    result, _ = select_evidence(
        llm_runtime=runtime,
        prompt_ref=SELECT_PROMPT_REF,
        revision_prompt_ref=SELECT_PROMPT_REF,
        requested_mode="LOCAL_GPU",
        request_intent=_intent(),
        rag_candidates=[
            {
                "segment_id": "mail",
                "resource_ref": "gmail_thread:1",
                "retrieval_score": 20.0,
                "reason_codes": ["ENTITY_CANDIDATE_MATCH"],
            }
        ],
        segments=[segment],
        retry_budget=_run_budget(used=0),
    )
    assert len(runtime.calls) == 2
    assert result == repaired
    evidence = materialize_evidence_drafts(result, segments=[segment])
    assert len(evidence) == 1
    assert evidence[0]["excerpt"] == segment.text


def test_materialization__inconsistent_legacy_selection__rejects_without_guessing() -> None:
    with pytest.raises(ValueError, match="inconsistent selected segment/evidence binding"):
        materialize_evidence_drafts(
            {
                "schema_version": 2,
                "selected_segment_ids": ["mail"],
                "excluded_segment_ids": [],
                "evidence_drafts": [],
            },
            segments=[],
        )


def test_source_assessment__object_order_changes__preserves_ranked_detail_priority() -> None:
    segments = [
        SourceSegment(
            key,
            f"gmail_thread:{key}",
            "GMAIL",
            "gmail_thread",
            key,
            None,
            None,
            {},
            "박람회 참석 안내",
        )
        for key in ("z-top", "a-low")
    ]
    runtime = FakeLLMRuntime(
        deque(
            [
                _llm_result(
                    {
                        "schema_version": 3,
                        "segment_assessments": {
                            key: {"role": "CONTEXT", "relevance_reason": "관련 행사 후보"}
                            for key in ("a-low", "z-top")
                        },
                    }
                )
            ]
        )
    )
    result, _ = select_evidence(
        llm_runtime=runtime,
        prompt_ref=SELECT_PROMPT_REF,
        revision_prompt_ref=SELECT_PROMPT_REF,
        requested_mode="LOCAL_GPU",
        request_intent=_intent(),
        rag_candidates=[
            {
                "segment_id": item.segment_id,
                "resource_ref": item.resource_handle,
                "retrieval_score": float(2 - i),
                "reason_codes": [],
            }
            for i, item in enumerate(segments)
        ],
        segments=segments,
        retry_budget=_run_budget(used=0),
    )
    assert result["selected_segment_ids"] == ["z-top", "a-low"]
    evidence = materialize_evidence_drafts(result, segments=segments)
    assert [item["resource_handle"] for item in evidence] == [
        "gmail_thread:z-top",
        "gmail_thread:a-low",
    ]


def test_selection_budget__multiple_sources__represents_each_and_binds_visible_schema() -> None:
    segments = [
        SourceSegment(
            f"mail-{n}",
            f"gmail_thread:{n}",
            "GMAIL",
            "gmail_thread",
            str(n),
            None,
            None,
            {},
            "회의 안내",
        )
        for n in range(20)
    ] + [SourceSegment("task", "task:1", "TASK", "task", "1", None, None, {}, "후속 업무")]
    output = {
        "schema_version": 2,
        "selected_segment_ids": ["mail-0", "task"],
        "excluded_segment_ids": [],
        "evidence_drafts": [
            {"segment_id": item, "role": "CONTEXT", "relevance_reason": "관련 자료"}
            for item in ("mail-0", "task")
        ],
    }
    runtime = FakeLLMRuntime(deque([_llm_result(evidence_assessment_output(output))]))
    intent = _intent()
    intent["requested_resource_hints"] = ["GMAIL_THREAD", "TASK"]
    result, _ = select_evidence(
        llm_runtime=runtime,
        prompt_ref=SELECT_PROMPT_REF,
        revision_prompt_ref=SELECT_PROMPT_REF,
        requested_mode="LOCAL_GPU",
        request_intent=intent,
        rag_candidates=[
            {
                "segment_id": item.segment_id,
                "resource_ref": item.resource_handle,
                "retrieval_score": 1.0,
                "reason_codes": [],
            }
            for item in segments
        ],
        segments=segments,
        retry_budget=_run_budget(used=0),
        context_budget=ContextBudget(max_normalized_context_items=2),
    )
    assert result == output
    inputs = cast(dict[str, object], runtime.calls[0]["prompt_input"])
    projected = cast(list[dict[str, object]], inputs["ranked_segments"])
    assert [item["segment_id"] for item in projected] == ["mail-0", "task"]
    assert result["excluded_segment_ids"] == []  # Unseen candidates are not rejected evidence.
    schema = cast(OutputSchemaDefinition, runtime.calls[0]["output_schema"])
    assert validate_output_schema(evidence_assessment_output(output), schema.json_schema) == []
    assert validate_output_schema(
        evidence_assessment_output({**output, "excluded_segment_ids": ["mail-1"]}),
        schema.json_schema,
    )


def test_select_evidence__preserves_stable__exclusion_obligations() -> None:
    runtime = FakeLLMRuntime(
        deque(
            [
                _llm_result(
                    evidence_assessment_output(
                        {
                            "schema_version": 2,
                            "evidence_drafts": [
                                {
                                    "segment_id": "segment-2",
                                    "role": "SUPPORTS",
                                    "relevance_reason": "current evidence",
                                }
                            ],
                            "selected_segment_ids": ["segment-2"],
                            "excluded_segment_ids": [],
                        }
                    )
                )
            ]
        )
    )
    segments = [
        SourceSegment("segment-1", "h1", "GMAIL", "gmail_message", "m1", None, None, {}, "old"),
        SourceSegment("segment-2", "h2", "GMAIL", "gmail_message", "m2", None, None, {}, "new"),
    ]
    candidates: list[RagCandidateV1] = [
        {
            "segment_id": item.segment_id,
            "resource_ref": item.resource_handle,
            "retrieval_score": 1.0,
            "reason_codes": [],
        }
        for item in segments
    ]

    result, _ = select_evidence(
        llm_runtime=runtime,
        prompt_ref=replace(SELECT_PROMPT_REF, prompt_id="retrieval.select_evidence"),
        revision_prompt_ref=replace(
            SELECT_PROMPT_REF, prompt_id="retrieval.select_evidence.revise"
        ),
        requested_mode="AUTO",
        request_intent=_intent(),
        rag_candidates=candidates,
        segments=segments,
        retry_budget=_run_budget(used=0),
        exclusion_obligation_segment_ids=["segment-1"],
    )

    assert result["selected_segment_ids"] == ["segment-2"]
    assert result["excluded_segment_ids"] == ["segment-1"]
    prompt_input = cast(dict[str, object], runtime.calls[0]["prompt_input"])
    projected = cast(list[dict[str, object]], prompt_input["ranked_segments"])
    assert [item["segment_id"] for item in projected] == ["segment-2"]


def test_select_evidence__sole_exact_selected_read__skips_llm() -> None:
    runtime = FakeLLMRuntime()
    intent = _intent()
    intent["analysis_requirement"] = "NONE"
    intent["constraints"] = [
        {"kind": "RESOURCE", "field": "selected_resource_id", "value": ["thread-42"]}
    ]
    segment = SourceSegment(
        "segment-42",
        "gmail_thread:thread-42",
        "GMAIL",
        "gmail_thread",
        "thread-42",
        None,
        None,
        {},
        "From: sender@example.com\nSubject: request\nPlease reply next week.",
    )

    result, _ = select_evidence(
        llm_runtime=runtime,
        prompt_ref=SELECT_PROMPT_REF,
        revision_prompt_ref=SELECT_PROMPT_REF,
        requested_mode="LOCAL_GPU",
        request_intent=intent,
        rag_candidates=[
            {
                "segment_id": segment.segment_id,
                "resource_ref": segment.resource_handle,
                "retrieval_score": 40.0,
                "reason_codes": ["EXACT_RESOURCE"],
            }
        ],
        segments=[segment],
        retry_budget=_run_budget(used=0),
    )

    assert runtime.calls == []
    assert result["selected_segment_ids"] == ["segment-42"]
    assert result["evidence_drafts"][0]["role"] == "SUPPORTS"


def test_search_candidates__all_irrelevant__excludes_without_repair_or_fabrication() -> None:
    output = {
        "schema_version": 2,
        "evidence_drafts": [],
        "selected_segment_ids": [],
        "excluded_segment_ids": ["outside-period"],
    }
    runtime = FakeLLMRuntime(deque([_llm_result(evidence_assessment_output(output))]))
    segment = SourceSegment(
        "outside-period",
        "gmail_thread:old",
        "GMAIL",
        "gmail_thread",
        "old",
        None,
        None,
        {},
        "2026년 7월 3일 종료된 행사 안내",
    )
    result, _ = select_evidence(
        llm_runtime=runtime,
        prompt_ref=SELECT_PROMPT_REF,
        revision_prompt_ref=SELECT_PROMPT_REF,
        requested_mode="LOCAL_GPU",
        request_intent=_intent(),
        rag_candidates=[
            {
                "segment_id": segment.segment_id,
                "resource_ref": segment.resource_handle,
                "retrieval_score": 1.0,
                "reason_codes": [],
            }
        ],
        segments=[segment],
        retry_budget=_run_budget(used=0),
    )
    assert result == output
    assert len(runtime.calls) == 1


def test_exact_selected_read__with_multiple_segments__selects_top_rank_without_llm() -> None:
    runtime = FakeLLMRuntime()
    intent = _intent()
    intent["analysis_requirement"] = "NONE"
    intent["constraints"] = [
        {"kind": "RESOURCE", "field": "selected_resource_id", "value": ["thread-42"]}
    ]
    segments = [
        SourceSegment(
            f"segment-{index}",
            "gmail_thread:thread-42",
            "GMAIL",
            "gmail_thread",
            "thread-42",
            None,
            None,
            {},
            text,
        )
        for index, text in enumerate(
            ["Subject: 보안 알림", "기기: Windows", "Date: 2026-09-04"], start=1
        )
    ]
    candidates: list[RagCandidateV1] = [
        {
            "segment_id": segment.segment_id,
            "resource_ref": segment.resource_handle,
            "retrieval_score": 40.0 - index,
            "reason_codes": ["EXACT_RESOURCE"],
        }
        for index, segment in enumerate(segments)
    ]

    result, _ = select_evidence(
        llm_runtime=runtime,
        prompt_ref=SELECT_PROMPT_REF,
        revision_prompt_ref=SELECT_PROMPT_REF,
        requested_mode="LOCAL_GPU",
        request_intent=intent,
        rag_candidates=candidates,
        segments=segments,
        retry_budget=_run_budget(used=0),
    )

    assert runtime.calls == []
    assert result["selected_segment_ids"] == ["segment-1"]


def test_select_evidence__repairs_container_only_selection__for_task_read() -> None:
    container_only = {
        "schema_version": 2,
        "evidence_drafts": [
            {
                "segment_id": "task-list-segment",
                "role": "CONTEXT",
                "relevance_reason": "Task list container",
            }
        ],
        "selected_segment_ids": ["task-list-segment"],
        "excluded_segment_ids": [],
    }
    concrete_task = {
        "schema_version": 2,
        "evidence_drafts": [
            {
                "segment_id": "task-segment",
                "role": "SUPPORTS",
                "relevance_reason": "Concrete requested task",
            }
        ],
        "selected_segment_ids": ["task-segment"],
        "excluded_segment_ids": ["task-list-segment"],
    }
    runtime = FakeLLMRuntime(
        deque(
            [
                _llm_result(evidence_assessment_output(container_only)),
                _llm_result(evidence_assessment_output(concrete_task)),
            ]
        )
    )
    intent = _intent()
    intent["requested_resource_hints"] = ["TASK"]
    segments = [
        SourceSegment(
            "task-list-segment",
            "task_list:list-1",
            "TASKS",
            "task_list",
            "list-1",
            None,
            None,
            {},
            "내 할 일 목록",
        ),
        SourceSegment(
            "task-segment",
            "task:task-1",
            "TASKS",
            "task",
            "task-1",
            "list-1",
            None,
            {},
            "[GWA LIVE SMOKE] Task 20260903-3F7A9C2D",
        ),
    ]
    candidates: list[RagCandidateV1] = [
        {
            "segment_id": segment.segment_id,
            "resource_ref": segment.resource_handle,
            "retrieval_score": 1.0,
            "reason_codes": [],
        }
        for segment in segments
    ]

    result, budget = select_evidence(
        llm_runtime=runtime,
        prompt_ref=SELECT_PROMPT_REF,
        revision_prompt_ref=replace(
            SELECT_PROMPT_REF, prompt_id="retrieval.select_evidence.revise"
        ),
        requested_mode="LOCAL_GPU",
        request_intent=intent,
        rag_candidates=candidates,
        segments=segments,
        retry_budget=_run_budget(used=0),
    )

    assert result["selected_segment_ids"] == ["task-segment"]
    assert len(runtime.calls) == 2
    assert budget["semantic_revisions_used_by_failure"]


def test_select_evidence__with_keyword_hits__preserves_semantic_assessment() -> None:
    notification_only = {
        "schema_version": 2,
        "evidence_drafts": [
            {
                "segment_id": "notification",
                "role": "SUPPORTS",
                "relevance_reason": "mentions a meeting summary",
            }
        ],
        "selected_segment_ids": ["notification"],
        "excluded_segment_ids": ["minutes", "minutes-typo"],
    }
    runtime = FakeLLMRuntime(deque([_llm_result(evidence_assessment_output(notification_only))]))
    intent = _intent()
    intent["analysis_requirement"] = "REQUIRED"
    intent["requested_effect_hints"] = ["READ"]
    intent["requested_resource_hints"] = ["GMAIL_THREAD"]
    intent["constraints"] = [
        {
            "kind": "USER_REQUIREMENT",
            "field": "original_search_request",
            "value": ["회의 관련 메일을 분석해서 일정 정리해줘"],
        }
    ]
    segments = [
        SourceSegment(
            "notification",
            "gmail_thread:notice",
            "GMAIL",
            "gmail_thread",
            "notice",
            None,
            None,
            {},
            "새 공지: ‘팀별회의 요약’ 알림 설정",
        ),
        SourceSegment(
            "minutes",
            "gmail_thread:minutes",
            "GMAIL",
            "gmail_thread",
            "minutes",
            None,
            None,
            {},
            "[Jira] (KAN-93) 0422 회의록",
        ),
        SourceSegment(
            "minutes-typo",
            "gmail_thread:minutes-typo",
            "GMAIL",
            "gmail_thread",
            "minutes-typo",
            None,
            None,
            {},
            "[Jira] (KAN-93) 0422 회의혹",
        ),
    ]
    candidates: list[RagCandidateV1] = [
        {
            "segment_id": segment.segment_id,
            "resource_ref": segment.resource_handle,
            "retrieval_score": 5.0,
            "reason_codes": ["KEYWORD_MATCH"],
        }
        for segment in segments
    ]

    result, _ = select_evidence(
        llm_runtime=runtime,
        prompt_ref=SELECT_PROMPT_REF,
        revision_prompt_ref=SELECT_PROMPT_REF,
        requested_mode="LOCAL_GPU",
        request_intent=intent,
        rag_candidates=candidates,
        segments=segments,
        retry_budget=_run_budget(used=0),
    )

    assert result == notification_only


def test_select_evidence__with_lineage_keywords__does_not_force_selection() -> None:
    empty_selection = {
        "schema_version": 2,
        "evidence_drafts": [],
        "selected_segment_ids": [],
        "excluded_segment_ids": [],
    }
    empty_selection["excluded_segment_ids"] = [
        "first-body-1",
        "first-body-2",
        "second-metadata",
    ]
    runtime = FakeLLMRuntime(deque([_llm_result(evidence_assessment_output(empty_selection))]))
    intent = _intent()
    intent["analysis_requirement"] = "REQUIRED"
    intent["requested_effect_hints"] = ["READ"]
    intent["requested_resource_hints"] = ["GMAIL_THREAD"]
    intent["constraints"] = [
        {
            "kind": "USER_REQUIREMENT",
            "field": "original_search_request",
            "value": ["KAN-93 관련 메일이 여러 개일 때 최신 결정이 무엇인지 알려줘."],
        },
        {"kind": "USER_REQUIREMENT", "field": "search_terms", "value": ["KAN-93"]},
    ]
    segments = [
        SourceSegment(
            "first-body-1",
            "gmail_thread:first",
            "GMAIL",
            "gmail_thread",
            "first",
            None,
            None,
            {},
            "KAN-93 첫 번째 스레드의 상세 본문 1",
        ),
        SourceSegment(
            "first-body-2",
            "gmail_thread:first",
            "GMAIL",
            "gmail_thread",
            "first",
            None,
            None,
            {},
            "KAN-93 첫 번째 스레드의 상세 본문 2",
        ),
        SourceSegment(
            "second-metadata",
            "gmail_thread:second",
            "GMAIL",
            "gmail_thread",
            "second",
            None,
            None,
            {},
            "[Jira] (KAN-93) 후속 회의록",
        ),
    ]
    candidates: list[RagCandidateV1] = [
        {
            "segment_id": segment.segment_id,
            "resource_ref": segment.resource_handle,
            "retrieval_score": 10.0 - index,
            "reason_codes": ["KEYWORD_MATCH"],
        }
        for index, segment in enumerate(segments)
    ]

    result, _ = select_evidence(
        llm_runtime=runtime,
        prompt_ref=SELECT_PROMPT_REF,
        revision_prompt_ref=SELECT_PROMPT_REF,
        requested_mode="LOCAL_GPU",
        request_intent=intent,
        rag_candidates=candidates,
        segments=segments,
        retry_budget=_run_budget(used=0),
    )

    assert result["selected_segment_ids"] == []
    assert result["excluded_segment_ids"] == [
        "first-body-1",
        "first-body-2",
        "second-metadata",
    ]
    assert len(runtime.calls) == 1


def test_event_time__resource_with_only_explicit_outside_dates__excludes_title_context() -> None:
    output = {
        "schema_version": 2,
        "evidence_drafts": [
            {"segment_id": "title", "role": "CONTEXT", "relevance_reason": "관련 제목"},
            {"segment_id": "body", "role": "CONTRADICTS", "relevance_reason": "기간 밖"},
        ],
        "selected_segment_ids": ["title", "body"],
        "excluded_segment_ids": [],
    }
    runtime = FakeLLMRuntime(deque([_llm_result(evidence_assessment_output(output))]))
    segments = [
        SourceSegment(
            "title",
            "gmail_thread:outside",
            "GMAIL",
            "gmail_thread",
            "outside",
            None,
            None,
            {},
            "오로라 이후 점검",
        ),
        SourceSegment(
            "body",
            "gmail_thread:outside",
            "GMAIL",
            "gmail_thread",
            "outside",
            None,
            None,
            {},
            "점검 일정은 2026년 9월 15일입니다.",
        ),
    ]
    intent = _intent()
    intent["constraints"] = [
        {"kind": "USER_REQUIREMENT", "field": "search_terms", "value": ["오로라"]},
        {"kind": "DATE", "field": "period", "value": ["9월 첫째주"]},
        {"kind": "TIME", "field": "temporal_axis", "value": ["EVENT_TIME"]},
    ]
    attempts = [
        cast(
            QueryAttemptV1,
            {
                "route_id": "gmail",
                "resource_type": "GMAIL_THREAD",
                "operation_kind": "SEARCH",
                "normalized_intent_constraints": [
                    {
                        "kind": "TEMPORAL_RANGE",
                        "axis": "EVENT_TIME",
                        "timezone": "Asia/Seoul",
                        "start_local": "2026-09-01T00:00:00",
                        "end_local": "2026-09-08T00:00:00",
                    }
                ],
            },
        )
    ]

    result, _ = select_evidence(
        llm_runtime=runtime,
        prompt_ref=SELECT_PROMPT_REF,
        revision_prompt_ref=SELECT_PROMPT_REF,
        requested_mode="LOCAL_GPU",
        request_intent=intent,
        rag_candidates=[
            {
                "segment_id": item.segment_id,
                "resource_ref": item.resource_handle,
                "retrieval_score": 1.0,
                "reason_codes": [],
            }
            for item in segments
        ],
        segments=segments,
        retry_budget=_run_budget(used=0),
        query_attempts=attempts,
    )

    assert result["selected_segment_ids"] == []
    assert set(result["excluded_segment_ids"]) == {"title", "body"}


def test_select_evidence__with_detail_assessment__selects_semantic_result() -> None:
    detail_selection = {
        "schema_version": 2,
        "evidence_drafts": [
            {
                "segment_id": "detail",
                "role": "SUPPORTS",
                "relevance_reason": "thread detail",
            },
            {
                "segment_id": "second-status",
                "role": "SUPPORTS",
                "relevance_reason": "work status",
            },
            {
                "segment_id": "decision-without-lineage-in-chunk",
                "role": "SUPPORTS",
                "relevance_reason": "explicit decision detail",
            },
        ],
        "selected_segment_ids": [
            "detail",
            "second-status",
            "decision-without-lineage-in-chunk",
        ],
        "excluded_segment_ids": ["preview", "second-preview"],
    }
    runtime = FakeLLMRuntime(deque([_llm_result(evidence_assessment_output(detail_selection))]))
    intent = _intent()
    intent["analysis_requirement"] = "REQUIRED"
    intent["requested_effect_hints"] = ["READ"]
    intent["requested_resource_hints"] = ["GMAIL_THREAD"]
    intent["constraints"] = [
        {
            "kind": "USER_REQUIREMENT",
            "field": "original_search_request",
            "value": ["KAN-93 관련 메일 중 최신 결정을 알려줘."],
        },
        {"kind": "USER_REQUIREMENT", "field": "search_terms", "value": ["KAN-93"]},
    ]
    segments = [
        SourceSegment(
            "preview",
            "gmail_thread:thread-1",
            "GMAIL",
            "gmail_thread",
            "thread-1",
            None,
            None,
            {},
            "[Jira] (KAN-93) 0422 회의록 최수진 님이 1개 항목을 업데이트했습니다.",
        ),
        SourceSegment(
            "detail",
            "gmail_thread:thread-1",
            "GMAIL",
            "gmail_thread",
            "thread-1",
            None,
            None,
            {},
            "From: 최수진 <jira@example.com>\nDate: 2026-04-22 15:49\n상태: 해야 할 일 → 진행",
        ),
        SourceSegment(
            "second-status",
            "gmail_thread:thread-2",
            "GMAIL",
            "gmail_thread",
            "thread-2",
            None,
            None,
            {},
            "[Jira] (KAN-93) 0422 회의록\nFrom: 최수진\nDate: 2026-04-22\n"
            "상태: 해야 할 일\n담당자: bonggyulim0728\n기한: 2026-04-22",
        ),
        SourceSegment(
            "decision-without-lineage-in-chunk",
            "gmail_thread:thread-2",
            "GMAIL",
            "gmail_thread",
            "thread-2",
            None,
            None,
            {},
            "네비게이션바로 확정. 다음 할 일은 와이어프레임 수정이며 담당자는 박희정입니다.",
        ),
        SourceSegment(
            "second-preview",
            "gmail_thread:thread-2",
            "GMAIL",
            "gmail_thread",
            "thread-2",
            None,
            None,
            {},
            "[Jira] (KAN-93) 0422 회의록",
        ),
    ]
    candidates: list[RagCandidateV1] = [
        {
            "segment_id": segment.segment_id,
            "resource_ref": segment.resource_handle,
            "retrieval_score": 10.0 - index,
            "reason_codes": ["KEYWORD_MATCH"] if "KAN-93" in segment.text else [],
        }
        for index, segment in enumerate(segments)
    ]

    result, _ = select_evidence(
        llm_runtime=runtime,
        prompt_ref=SELECT_PROMPT_REF,
        revision_prompt_ref=SELECT_PROMPT_REF,
        requested_mode="LOCAL_GPU",
        request_intent=intent,
        rag_candidates=candidates,
        segments=segments,
        retry_budget=_run_budget(used=0),
    )

    assert result["selected_segment_ids"][:2] == ["detail", "second-status"]
    assert result["selected_segment_ids"][2] == "decision-without-lineage-in-chunk"
    assert len(runtime.calls) == 1
