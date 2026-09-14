import pytest

from google_work_agent.application.agents.planning.project_task_read_answer import (
    project_task_read_answer,
)


def test_task_read_answer__concrete_evidence__lists_in_user_language() -> None:
    result = project_task_read_answer(
        user_request="Google Tasks의 현재 할 일을 목록으로 알려줘.",
        request_intent={
            "requested_effect_hints": ["READ"],
            "requested_resource_hints": ["TASK"],
            "analysis_requirement": "NONE",
        },
        evidence=[
            {
                "evidence_id": "e-task",
                "resource_handle": "task:42",
                "excerpt": "[GWA LIVE SMOKE] Task 20260903-3F7A9C2D",
            },
            {
                "evidence_id": "e-list",
                "resource_handle": "task_list:default",
                "excerpt": "내 할 일 목록",
            },
        ],
    )

    assert result is not None
    assert result.outline == {
        "sections": ["현재 Google Tasks 할 일"],
        "evidence_refs": ["e-task"],
    }
    assert result.draft == {
        "schema_version": 2,
        "answer": (
            "Google Tasks에서 확인된 현재 할 일은 1개입니다.\n\n"
            "- [GWA LIVE SMOKE] Task 20260903-3F7A9C2D"
        ),
        "evidence_refs": ["e-task"],
    }


def test_task_read_answer__analytical_or_mixed_request__does_not_replace() -> None:
    assert (
        project_task_read_answer(
            user_request="태스크를 분석해줘.",
            request_intent={
                "requested_effect_hints": ["READ"],
                "requested_resource_hints": ["TASK"],
                "analysis_requirement": "REQUIRED",
            },
            evidence=[],
        )
        is None
    )


def test_task_read_answer__structured_excerpt__uses_title_not_task_list_id() -> None:
    result = project_task_read_answer(
        user_request="현재 할 일을 알려줘.",
        request_intent={
            "requested_effect_hints": ["READ"],
            "requested_resource_hints": ["TASK"],
            "analysis_requirement": "NONE",
        },
        evidence=[
            {
                "evidence_id": "e-task",
                "resource_handle": "task:42",
                "excerpt": (
                    "task_list_id: private-list\n"
                    "title: Quartz 입고 준비\n"
                    "status: needsAction"
                ),
            },
            {
                "evidence_id": "e-task-without-title",
                "resource_handle": "task:43",
                "excerpt": "task_list_id: private-list\nstatus: needsAction",
            },
        ],
    )

    assert result is not None
    assert "- Quartz 입고 준비" in result.draft["answer"]
    assert "- 제목을 표시할 수 없는 할 일" in result.draft["answer"]
    assert "현재 할 일은 2개" in result.draft["answer"]
    assert "private-list" not in result.draft["answer"]


@pytest.mark.parametrize(
    "title",
    [
        "Quartz 입고 준비",
        "Quartz: 입고 준비",
        "10:30 회의 준비",
    ],
)
def test_task_read_answer__plain_title_with_colon__remains_visible(title: str) -> None:
    result = project_task_read_answer(
        user_request="현재 할 일을 알려줘.",
        request_intent={
            "requested_effect_hints": ["READ"],
            "requested_resource_hints": ["TASK"],
            "analysis_requirement": "NONE",
        },
        evidence=[
            {
                "evidence_id": "e-task",
                "resource_handle": "task:42",
                "excerpt": title,
            }
        ],
    )

    assert result is not None
    assert f"- {title}" in result.draft["answer"]


def test_task_read_answer__no_task_items__reports_zero_result() -> None:
    result = project_task_read_answer(
        user_request="현재 할 일을 알려줘.",
        request_intent={
            "requested_effect_hints": ["READ"],
            "requested_resource_hints": ["TASK"],
            "analysis_requirement": "NONE",
        },
        evidence=[],
    )

    assert result is not None
    assert result.draft["answer"] == "Google Tasks에서 현재 표시할 할 일을 찾지 못했습니다."
