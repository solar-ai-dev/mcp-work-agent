from collections.abc import Mapping
from copy import deepcopy
from typing import cast

import pytest
from tests.support.task_calendar_evidence import bind_task_calendar_snapshots

from google_work_agent.application.agents.planning.compose_answer import compose_answer
from google_work_agent.application.agents.planning.contracts.planning_semantics import (
    AnswerOutlineV1,
)
from google_work_agent.application.agents.planning.outline_answer import outline_answer
from google_work_agent.application.agents.planning.project_task_read_answer import (
    project_task_read_answer,
)
from google_work_agent.application.agents.request_understanding.contracts import (
    request_goal_candidate_schema,
)
from google_work_agent.application.agents.request_understanding.contracts.request_intent import (
    RequestIntentV3,
    ResourceResponsibilitiesV1,
)
from google_work_agent.application.agents.request_understanding.validate_intent import (
    validate_intent,
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


def _bound_intent(
    sources: list[tuple[list[str], list[str]]],
    *,
    request_parts: tuple[str, ...] | None = None,
) -> tuple[str, RequestIntentV3]:
    work_ids = sorted({work_id for _, ids in sources for work_id in ids})
    parts = request_parts or tuple(
        f"{work_id} 작업의 필요한 정보를 알려줘." for work_id in work_ids
    )
    assert len(parts) == len(work_ids)
    request = " ".join(parts)
    responsibilities: ResourceResponsibilitiesV1 = {
        "source_reads": [
            {
                "resource_type": "TASK",
                "required_information": fields,
                "target_scope": "CRITERIA",
                "work_unit_ids": work_ids,
            }
            for fields, work_ids in sources
        ],
        "outputs": [],
    }
    intent = validate_intent(
        {
            "schema_version": 3,
            "meta": {"artifact_id": "task-read", "revision": 1, "based_on": []},
            "goal": request,
            "completion_conditions": ["두 작업의 요청 정보를 안내한다."],
            "constraints": request_goal_candidate_schema.derive_source_information_constraints(
                responsibilities
            ),
            "requested_effect_hints": ["READ"],
            "requested_resource_hints": ["TASK"],
            "analysis_requirement": "NONE",
            "effect_prohibitions": [],
            "resource_responsibilities": responsibilities,
            "requested_work": {
                "work_units": [
                    {
                        "unit_id": work_ids[index],
                        "request_provenance": [
                            {
                                "source": "USER_REQUEST",
                                "start_offset": request.index(part),
                                "end_offset": request.index(part) + len(part),
                                "source_text": part,
                            }
                        ],
                    }
                    for index, part in enumerate(parts)
                ],
                "work_relations": [],
            },
            "ambiguity": {
                "requires_confirmation": False,
                "reason_codes": [],
                "missing_fields": [],
            },
        },
        require_meta=True,
        provenance_sources={"USER_REQUEST": request},
    )
    return request, intent


@pytest.mark.parametrize("same_work,shared_evidence", [(False, False), (False, True), (True, True)])
def test_task_read_answer__heterogeneous_fields__delegates_without_cross_product(
    same_work: bool, shared_evidence: bool,
) -> None:
    request, intent = _bound_intent(
        [(["status"], ["work-1"]), (["due"], ["work-1" if same_work else "work-2"])],
        request_parts=(
            ("첫 작업의 상태만, 다른 작업의 예정일만 알려줘.",)
            if same_work else ("첫 작업의 상태만 알려줘.", "다른 작업의 예정일만 알려줘.")
        ),
    )
    evidence, snapshots = _observed_task()
    second: dict[str, object] = {
        "evidence_id": "e-second",
        "resource_handle": "task:43",
        "excerpt": "untrusted",
    }
    snapshots.update(
        bind_task_calendar_snapshots(
            [second],
            {"e-second": {"title": "두 번째 작업", "due": "2026-08-11T00:00:00Z"}},
        )
    )
    evidence.append(second)
    refs = ["e-task", "e-second"]
    retrieval: dict[str, object] = {
        "evidence_by_work_unit": [{"work_unit_id": "work-1", "evidence_refs": refs}]
        if same_work else [
            {"work_unit_id": "work-1", "evidence_refs": refs if shared_evidence else ["e-task"]},
            {"work_unit_id": "work-2", "evidence_refs": refs if shared_evidence else ["e-second"]},
        ]
    }
    before = deepcopy((intent, evidence, snapshots, retrieval))
    assert (
        project_task_read_answer(
            user_request=request,
            request_intent=intent,
            evidence=evidence,
            source_snapshots=snapshots,
            retrieval_result=retrieval,
        )
        is None
    )
    calls: list[str] = []

    def invoke(prompt_id: str, prompt_input: Mapping[str, object]) -> Mapping[str, object]:
        calls.append(prompt_id)
        assert prompt_input["request_intent"] == intent
        assert prompt_input["evidence_by_work_unit"] == retrieval["evidence_by_work_unit"]
        assert prompt_input["evidence"] == evidence
        assert prompt_input["user_request"] == request
        return {"schema_version": 2, "answer": "작성 owner의 응답", "evidence_refs": refs}

    outline = outline_answer(
        user_request=request,
        request_intent=intent,
        evidence=evidence,
        work_analysis=None,
        source_snapshots=snapshots,
        retrieval_result=retrieval,
        invoke=invoke,
    )
    answer = compose_answer(
        user_request=request,
        request_intent=intent,
        evidence=evidence,
        work_analysis=None,
        answer_outline=cast(AnswerOutlineV1, outline),
        source_snapshots=snapshots,
        retrieval_result=retrieval,
        invoke=invoke,
    )
    assert outline == {"sections": [request], "evidence_refs": refs}
    assert calls == ["planning.compose_answer"]
    assert answer == {"schema_version": 2, "answer": "작성 owner의 응답", "evidence_refs": refs}
    assert (intent, evidence, snapshots, retrieval) == before


@pytest.mark.parametrize(
    "sources",
    [
        [(["status"], ["work-1"]), (["completion_status"], ["work-2"])],
        [(["due"], ["work-1"]), (["scheduled_date"], ["work-2"])],
        [(["status", "due"], ["work-1", "work-2"])],
        [(["status", "due"], ["work-1"])],
        [(["status"], ["work-1"]), (["title", "task_status"], ["work-2"])],
    ],
)
def test_task_read_answer__single_or_equivalent_sources__keeps_deterministic_projection(
    sources: list[tuple[list[str], list[str]]],
) -> None:
    request, intent = _bound_intent(sources)
    evidence, snapshots = _observed_task()
    assert (
        project_task_read_answer(
            user_request=request,
            request_intent=intent,
            evidence=evidence,
            source_snapshots=snapshots,
        )
        is not None
    )


def test_task_read_answer__distinct_work_fields_empty_read__preserves_empty_result() -> None:
    request, intent = _bound_intent([(["status"], ["work-1"]), (["due"], ["work-2"])])
    result = project_task_read_answer(
        user_request=request,
        request_intent=intent,
        evidence=[],
        retrieval_result={
            "coverage": "SUFFICIENT",
            "source_statuses": [
                {
                    "resource_type": "task",
                    "status": "COMPLETE",
                    "failure_kind": None,
                    "checked_read_count": 1,
                    "observed_resource_count": 0,
                    "scope_complete": True,
                    "continuation_status": "EXHAUSTED",
                }
            ],
        },
    )
    assert result is not None
    assert result.draft["answer"] == "Google Tasks에서 현재 표시할 할 일을 찾지 못했습니다."


@pytest.mark.parametrize("legacy", ["missing_responsibility", "missing_sources", "no_binding"])
def test_task_read_answer__legacy_unbound_input__preserves_existing_projection(legacy: str) -> None:
    intent = _intent(["status", "due"])
    if legacy == "missing_responsibility":
        intent.pop("resource_responsibilities")
    elif legacy == "missing_sources":
        intent["resource_responsibilities"] = {"outputs": []}
    evidence, snapshots = _observed_task()
    result = project_task_read_answer(
        user_request="현재 작업을 알려줘.",
        request_intent=intent,
        evidence=evidence,
        source_snapshots=snapshots,
    )
    assert result is not None
    assert "Ion 신입 온보딩 체크리스트" in result.draft["answer"]
    assert ("상태:" in result.draft["answer"]) is (legacy == "no_binding")


@pytest.mark.parametrize("duplicate_task", [False, True])
def test_task_read_answer__uniform_tasks_or_duplicate_chunks__keeps_deterministic_projection(
    duplicate_task: bool,
) -> None:
    sources = (
        [(["status", "due"], ["work-1"])]
        if duplicate_task else [(["status"], ["work-1"]), (["task_status"], ["work-1"])]
    )
    request, intent = _bound_intent(sources)
    evidence, snapshots = _observed_task()
    second = {**deepcopy(evidence[0]), "evidence_id": "e-second"}
    if duplicate_task:
        snapshots["e-second"] = deepcopy(snapshots["e-task"])
    else:
        second["resource_handle"] = "task:43"
        snapshots.update(bind_task_calendar_snapshots([second], {
            "e-second": {"title": "두 번째 작업", "status": "completed"},
        }))
    evidence.append(second)
    before = deepcopy((intent, evidence, snapshots))

    def invoke(prompt_id: str, prompt_input: Mapping[str, object]) -> Mapping[str, object]:
        raise AssertionError("equivalent fields or one unique Task must stay deterministic")

    outline = outline_answer(
        user_request=request, request_intent=intent, evidence=evidence, work_analysis=None,
        source_snapshots=snapshots, invoke=invoke,
    )
    draft = compose_answer(
        user_request=request, request_intent=intent, evidence=evidence, work_analysis=None,
        answer_outline=cast(AnswerOutlineV1, outline), source_snapshots=snapshots, invoke=invoke,
    )
    assert draft["evidence_refs"] == ["e-task", "e-second"]
    assert f"현재 할 일은 {1 if duplicate_task else 2}개" in draft["answer"]
    assert "상태: 미완료" in draft["answer"]
    assert ("예정일:" in draft["answer"]) is duplicate_task
    assert (intent, evidence, snapshots) == before


@pytest.mark.parametrize("duplicate_evidence", [False, True])
def test_task_read_answer__one_observation_for_distinct_sources__does_not_infer_shared_target(
    duplicate_evidence: bool,
) -> None:
    request, intent = _bound_intent(
        [(["status"], ["work-1"]), (["due"], ["work-1"])],
        request_parts=("첫 작업의 상태만, 다른 작업의 예정일만 알려줘.",),
    )
    evidence, snapshots = _observed_task()
    if duplicate_evidence:
        evidence.append({**deepcopy(evidence[0]), "evidence_id": "e-duplicate"})
        snapshots["e-duplicate"] = deepcopy(snapshots["e-task"])
    assert project_task_read_answer(
        user_request=request, request_intent=intent, evidence=evidence,
        source_snapshots=snapshots,
        retrieval_result={"coverage": "PARTIAL", "evidence_by_work_unit": [
            {"work_unit_id": "work-1", "evidence_refs": [
                item["evidence_id"] for item in evidence
            ]},
        ]},
    ) is None


@pytest.mark.parametrize("sources", [
    [(["status"], ["work-1", "work-2"]), (["due"], ["work-1", "work-2"])],
    [(["status"], ["work-1"]), (["due"], ["work-1"]), (["status", "due"], ["work-2"])],
])
def test_task_read_answer__split_sources_with_equal_work_unions__retains_semantic_owner(
    sources: list[tuple[list[str], list[str]]],
) -> None:
    # Equal Work unions and one observation do not prove that Source targets coincide.
    request, intent = _bound_intent(sources)
    evidence, snapshots = _observed_task()
    assert project_task_read_answer(
        user_request=request, request_intent=intent, evidence=evidence,
        source_snapshots=snapshots,
    ) is None
