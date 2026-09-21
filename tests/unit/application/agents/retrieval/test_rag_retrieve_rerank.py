from typing import cast

from google_work_agent.application.agents.request_understanding.contracts.request_intent import (
    RequestIntentV3,
)
from google_work_agent.application.agents.retrieval.normalize_segments import SourceSegment
from google_work_agent.application.agents.retrieval.rag_retrieve_rerank import rag_retrieve_rerank


def test_rag_ranking__is_deterministic__and_prompt_free() -> None:
    intent = cast(
        RequestIntentV3,
        {
            "schema_version": 2,
            "meta": {"artifact_id": "i", "revision": 1, "based_on": []},
            "goal": "alpha",
            "constraints": [],
            "requested_effect_hints": ["READ"],
        },
    )
    segments = [
        SourceSegment("seg_b", "h2", "GMAIL", "gmail_message", "m2", None, None, {}, "alpha"),
        SourceSegment("seg_a", "h1", "GMAIL", "gmail_message", "m1", None, None, {}, "alpha"),
    ]

    assert [
        item["segment_id"] for item in rag_retrieve_rerank(
            segments, request_intent=intent, source_plans=[], top_k=2
        )
    ] == ["seg_a", "seg_b"]


def test_rag_ranking__preserved_original_request__does_not_score_whole_text() -> None:
    intent = cast(
        RequestIntentV3,
        {
            "schema_version": 2,
            "meta": {"artifact_id": "i", "revision": 1, "based_on": []},
            "goal": "find evidence",
            "constraints": [
                {
                    "kind": "USER_REQUIREMENT",
                    "field": "original_search_request",
                    "value": ["회의 관련 메일을 찾아줘"],
                },
                {"kind": "USER_REQUIREMENT", "field": "search_terms", "value": ["회의"]},
            ],
            "requested_effect_hints": ["READ"],
        },
    )
    segments = [
        SourceSegment("seg_mail", "h1", "GMAIL", "gmail_message", "m1", None, None, {}, "메일"),
        SourceSegment("seg_meeting", "h2", "GMAIL", "gmail_message", "m2", None, None, {}, "회의"),
    ]

    result = rag_retrieve_rerank(segments, request_intent=intent, source_plans=[], top_k=2)

    assert result[0]["segment_id"] == "seg_meeting"
    assert result[1]["retrieval_score"] == 0.0


def test_rag_retrieve_rerank__with_cross_resource_draft__keeps_explicit_sources() -> None:
    intent = cast(
        RequestIntentV3,
        {
            "schema_version": 2,
            "meta": {"artifact_id": "i", "revision": 1, "based_on": []},
            "goal": "Orion 준비 상황을 메일 초안으로 작성",
            "constraints": [
                {
                    "kind": "USER_REQUIREMENT",
                    "field": "search_terms",
                    "value": "orion@example.com",
                    "provenance": {"source": "USER_REQUEST", "start_offset": 20},
                },
                {
                    "kind": "USER_REQUIREMENT",
                    "field": "search_terms",
                    "value": "Orion",
                    "provenance": {"source": "USER_REQUEST", "start_offset": 0},
                },
                {
                    "kind": "USER_REQUIREMENT",
                    "field": "search_terms",
                    "value": "제작소 일정 보고",
                    "provenance": {"source": "USER_REQUEST", "start_offset": 6},
                },
            ],
            "requested_effect_hints": ["READ", "CREATE"],
            "resource_responsibilities": {
                "source_reads": [
                    {"resource_type": "TASK", "required_information": ["title"]},
                    {"resource_type": "CALENDAR_EVENT", "required_information": ["start"]},
                ],
                "outputs": [{"resource_type": "GMAIL_DRAFT", "effect": "CREATE"}],
            },
        },
    )
    segments = [
        *[
            SourceSegment(
                f"noise-{index}", f"task:n{index}", "TASKS", "task", f"n{index}",
                None, None, {}, "Orion unrelated",
            )
            for index in range(24)
        ],
        SourceSegment(
            "task-source", "task:t1", "TASKS", "task", "t1", None, None, {},
            "title: Orion 준비",
        ),
        SourceSegment(
            "event-source", "calendar_event:e1", "CALENDAR", "calendar_event", "e1",
            None, None, {}, "title: Orion 제작소 일정",
        ),
    ]

    result = rag_retrieve_rerank(segments, request_intent=intent, source_plans=[], top_k=2)

    assert {item["segment_id"] for item in result} == {"task-source", "event-source"}
    assert all("EXPLICIT_SOURCE_ANCHOR_MATCH" in item["reason_codes"] for item in result)
