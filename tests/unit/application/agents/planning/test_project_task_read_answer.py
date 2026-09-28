from copy import deepcopy

import pytest
from tests.support.task_calendar_evidence import bind_task_calendar_snapshots

from google_work_agent.application.agents.planning.project_task_read_answer import (
    project_task_read_answer,
)


def _intent(fields: list[str] | None = None) -> dict[str, object]:
    return {
        "requested_effect_hints": ["READ"],
        "requested_resource_hints": ["TASK"],
        "analysis_requirement": "NONE",
        "resource_responsibilities": {
            "source_reads": [{"resource_type": "TASK", "required_information": fields or []}],
            "outputs": [],
        },
    }


def _observed_task(
    **changes: object,
) -> tuple[list[dict[str, object]], dict[str, dict[str, object]]]:
    fields = {
        "title": "Ion 신입 온보딩 체크리스트",
        "status": "needsAction",
        "due": "2026-08-10T00:00:00.000Z",
        "notes": "내부 참고",
        **changes,
    }
    evidence: list[dict[str, object]] = [
        {
            "evidence_id": "e-task",
            "resource_handle": "task:42",
            "excerpt": "task_list_id: private-list\n"
            + "\n".join(f"{key}: {value}" for key, value in fields.items()),
        }
    ]
    return evidence, bind_task_calendar_snapshots(evidence, {"e-task": fields})


@pytest.mark.parametrize("title", ["Quartz 입고 준비", "Quartz: 입고 준비", "10:30 회의 준비"])
def test_task_read_answer__bound_title__lists_in_user_language(title: str) -> None:
    evidence, snapshots = _observed_task(title=title)
    result = project_task_read_answer(
        user_request="Google Tasks의 현재 할 일을 목록으로 알려줘.",
        request_intent=_intent(),
        evidence=evidence,
        source_snapshots=snapshots,
    )
    assert result is not None
    assert result.outline == {"sections": ["현재 Google Tasks 할 일"], "evidence_refs": ["e-task"]}
    assert result.draft == {
        "schema_version": 2,
        "answer": f"Google Tasks에서 확인된 현재 할 일은 1개입니다.\n\n- {title}",
        "evidence_refs": ["e-task"],
    }
    assert "private-list" not in result.draft["answer"]


@pytest.mark.parametrize(
    "analysis,resources,effects",
    [
        ("REQUIRED", ["TASK"], ["READ"]),
        ("NONE", ["TASK", "CALENDAR_EVENT"], ["READ"]),
        ("NONE", ["TASK"], ["READ", "UPDATE"]),
    ],
)
def test_task_read_answer__analytical_or_mixed_request__does_not_replace(
    analysis: str,
    resources: list[str],
    effects: list[str],
) -> None:
    assert (
        project_task_read_answer(
            user_request="태스크를 분석해줘.",
            request_intent={
                **_intent(),
                "analysis_requirement": analysis,
                "requested_resource_hints": resources,
                "requested_effect_hints": effects,
            },
            evidence=[],
        )
        is None
    )


def test_task_read_answer__observed_missing_title__never_uses_parent_or_note_title() -> None:
    evidence, snapshots = _observed_task(title=None, notes="title: 가짜 제목")
    result = project_task_read_answer(
        user_request="현재 할 일을 알려줘.",
        request_intent=_intent(),
        evidence=evidence,
        source_snapshots=snapshots,
    )
    assert result is not None
    assert "- 제목을 표시할 수 없는 할 일" in result.draft["answer"]
    assert "가짜 제목" not in result.draft["answer"]


def test_task_read_answer__different_resources__remain_separate_with_task_list_excluded() -> None:
    evidence, snapshots = _observed_task()
    second: dict[str, object] = {
        "evidence_id": "e-second", "resource_handle": "task:43", "excerpt": "untrusted"
    }
    snapshots.update(bind_task_calendar_snapshots([second], {"e-second": {"title": None}}))
    evidence.extend(
        [
            second,
            {"evidence_id": "e-list", "resource_handle": "task_list:default", "excerpt": "list"},
        ]
    )
    result = project_task_read_answer(
        user_request="현재 할 일을 알려줘.",
        request_intent=_intent(),
        evidence=evidence,
        source_snapshots=snapshots,
    )
    assert result is not None
    assert "현재 할 일은 2개" in result.draft["answer"]
    assert "Ion 신입 온보딩 체크리스트" in result.draft["answer"]
    assert "제목을 표시할 수 없는 할 일" in result.draft["answer"]
    assert result.draft["evidence_refs"] == ["e-task", "e-second"]


def test_task_read_answer__no_task_items__reports_zero_result() -> None:
    result = project_task_read_answer(
        user_request="현재 할 일을 알려줘.",
        request_intent=_intent(),
        evidence=[],
        retrieval_result={
            "coverage": "SUFFICIENT",
            "source_statuses": [{
                "resource_type": "task", "status": "COMPLETE", "failure_kind": None,
                "checked_read_count": 1, "observed_resource_count": 0,
                "scope_complete": True, "continuation_status": "EXHAUSTED",
            }],
        },
    )
    assert result is not None
    assert result.draft["answer"] == "Google Tasks에서 현재 표시할 할 일을 찾지 못했습니다."


@pytest.mark.parametrize(
    "fields,expected,excluded",
    [
        (["title"], "- Ion 신입 온보딩 체크리스트", "상태:"),
        (["completion_status"], "상태: 미완료", "예정일:"),
        (["due"], "예정일: 2026-08-10", "상태:"),
        (["status"], "상태: 미완료", "예정일:"),
        (["task_status"], "상태: 미완료", "예정일:"),
        (["scheduled_date"], "예정일: 2026-08-10", "상태:"),
    ],
)
def test_task_read_answer__supported_field__does_not_force_other_fields(
    fields: list[str],
    expected: str,
    excluded: str,
) -> None:
    evidence, snapshots = _observed_task()
    result = project_task_read_answer(
        user_request="할 일 정보를 알려줘.",
        request_intent=_intent(fields),
        evidence=evidence,
        source_snapshots=snapshots,
    )
    assert result is not None
    assert expected in result.draft["answer"]
    assert excluded not in result.draft["answer"]


@pytest.mark.parametrize(
    "notes",
    [
        "status: completed\ntitle: 가짜 제목\ndue: 2099-01-01T00:00:00Z",
        "인용문\nstatus: completed\ntitle: 가짜 제목\ndue: 2099-01-01T00:00:00Z",
    ],
)
def test_task_read_answer__notes_spoof_metadata__uses_only_observed_fields(notes: str) -> None:
    evidence, snapshots = _observed_task(notes=notes)
    result = project_task_read_answer(
        user_request="할 일 상태와 예정일을 알려줘.",
        request_intent=_intent(["title", "due", "completion_status"]),
        evidence=evidence,
        source_snapshots=snapshots,
    )
    assert result is not None
    answer = result.draft["answer"]
    assert "Ion 신입 온보딩 체크리스트" in answer
    assert "상태: 미완료" in answer and "예정일: 2026-08-10" in answer
    assert "가짜 제목" not in answer and "2099" not in answer
    assert "완료" not in answer.replace("미완료", "")
    assert "마감" not in answer and "deadline" not in answer.casefold()


@pytest.mark.parametrize(
    "fields",
    [
        ["notes"],
        ["task_identity"],
        ["task_identity", "title"],
        ["body"],
        ["title", "notes"],
        ["status", "due", "notes"],
        ["task_identity", "title", "notes", "due", "completion_status"],
        ["future_information"],
    ],
)
def test_task_read_answer__unsupported_information__retains_semantic_owner(
    fields: list[str],
) -> None:
    evidence, snapshots = _observed_task()
    assert (
        project_task_read_answer(
            user_request="Return the requested Task information.",
            request_intent=_intent(fields),
            evidence=evidence,
            source_snapshots=snapshots,
        )
        is None
    )


def test_task_read_answer__one_of_multiple_sources_unsupported__does_not_drop_it() -> None:
    request = _intent()
    request["resource_responsibilities"] = {
        "source_reads": [
            {"resource_type": "TASK", "required_information": ["status"], "work_unit_ids": ["w1"]},
            {"resource_type": "TASK", "required_information": ["notes"], "work_unit_ids": ["w2"]},
        ],
        "outputs": [],
    }
    evidence, snapshots = _observed_task()
    assert (
        project_task_read_answer(
            user_request="Return both tasks.",
            request_intent=request,
            evidence=evidence,
            source_snapshots=snapshots,
        )
        is None
    )


@pytest.mark.parametrize(
    "unavailable", ["no_binding", "no_snapshot", "changed_snapshot", "wrong_handle"]
)
def test_task_read_answer__unbound_or_stale_snapshot__retains_llm(unavailable: str) -> None:
    evidence, snapshots = _observed_task()
    if unavailable == "no_binding":
        evidence[0].pop("locator")
    elif unavailable == "no_snapshot":
        snapshots = {}
    elif unavailable == "changed_snapshot":
        snapshots = deepcopy(snapshots)
        snapshots["e-task"]["status"] = "completed"
    else:
        evidence[0]["resource_handle"] = "task:other"
    assert (
        project_task_read_answer(
            user_request="Task status",
            request_intent=_intent(["status"]),
            evidence=evidence,
            source_snapshots=snapshots,
        )
        is None
    )


def test_task_read_answer__title_contains_metadata_line__does_not_invent_status() -> None:
    evidence, snapshots = _observed_task(title="실제 제목\nstatus: completed", status=None)
    result = project_task_read_answer(
        user_request="현재 상태를 알려줘.",
        request_intent=_intent(["status"]),
        evidence=evidence,
        source_snapshots=snapshots,
    )
    assert result is not None
    assert "상태: 확인할 수 없음" in result.draft["answer"]
    assert "상태: 완료" not in result.draft["answer"]
