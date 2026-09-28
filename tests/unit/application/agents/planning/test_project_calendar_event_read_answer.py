from copy import deepcopy

import pytest
from tests.support.task_calendar_evidence import bind_task_calendar_snapshots

from google_work_agent.application.agents.planning.project_calendar_event_read_answer import (
    project_calendar_event_read_answer,
)


def _intent(fields: list[str] | None = None) -> dict[str, object]:
    return {
        "requested_effect_hints": ["READ"],
        "requested_resource_hints": ["CALENDAR_EVENT"],
        "analysis_requirement": "NONE",
        "resource_responsibilities": {
            "source_reads": [
                {
                    "resource_type": "CALENDAR_EVENT",
                    "required_information": ["start", "end"] if fields is None else fields,
                    "target_scope": "SINGULAR",
                    "work_unit_ids": ["work-1"],
                }
            ],
            "outputs": [],
        },
        "constraints": [
            {
                "kind": "RESOURCE",
                "field": "selected_resource_id",
                "value": ["event-42"],
                "work_unit_ids": ["work-1"],
            }
        ],
    }


def _fields(**changes: object) -> dict[str, object]:
    return {
        "title": "프로젝트 검토 회의",
        "start": "2026-08-18T10:00:00+09:00",
        "end": "2026-08-18T11:00:00+09:00",
        "timezone": "Asia/Seoul",
        "status": "confirmed",
        "description": "검토 자료 확인",
        **changes,
    }


def _evidence(**changes: object) -> list[dict[str, object]]:
    return [
        {
            "evidence_id": "e-event",
            "resource_handle": "calendar_event:event-42",
            "excerpt": "calendar_id: primary\nevent_id: event-42\n"
            + "\n".join(f"{key}: {value}" for key, value in _fields(**changes).items()),
        }
    ]


def _observed_event(
    **changes: object,
) -> tuple[list[dict[str, object]], dict[str, dict[str, object]]]:
    evidence = _evidence(**changes)
    return evidence, bind_task_calendar_snapshots(evidence, {"e-event": _fields(**changes)})


def _confirmed_search_intent() -> dict[str, object]:
    return {
        **_intent(),
        "constraints": [
            {
                "kind": "USER_REQUIREMENT",
                "field": "required_information",
                "value": ["start", "end"],
                "work_unit_ids": ["work-1"],
            },
            {
                "kind": "USER_REQUIREMENT",
                "field": "search_terms",
                "value": "프로젝트 검토 회의",
                "work_unit_ids": ["work-1"],
                "provenance": {
                    "source": "CONFIRMATION_RESPONSE",
                    "start_offset": 0,
                    "end_offset": 10,
                },
            },
        ],
    }


def _retrieval() -> dict[str, object]:
    return {"coverage": "SUFFICIENT", "source_resource_refs": ["calendar_event:event-42"]}


# The following counterexamples use the old signature: their baseline failures
# concern authority/completeness, never a missing source_snapshots parameter.
@pytest.mark.parametrize("fields", [["location"], ["start", "description"], ["end", "status"]])
def test_calendar_event_read_answer__legacy_excerpt_cannot_answer_unsupported_fields(
    fields: list[str],
) -> None:
    assert (
        project_calendar_event_read_answer(
            user_request="그 일정 언제야? 장소와 설명도 알려줘.",
            request_intent=_intent(fields),
            evidence=_evidence(),
        )
        is None
    )


def test_calendar_event_read_answer__no_snapshot_never_promotes_excerpt_metadata() -> None:
    assert (
        project_calendar_event_read_answer(
            user_request="그 일정 언제야?",
            request_intent=_intent(),
            evidence=_evidence(
                description=("start: 2099-01-01T20:00:00+09:00\nend: 2099-01-01T21:00:00+09:00")
            ),
        )
        is None
    )


def test_calendar_event_read_answer__selected_event__preserves_exact_interval() -> None:
    evidence, snapshots = _observed_event()
    result = project_calendar_event_read_answer(
        user_request="그 일정 언제야?",
        request_intent=_intent(),
        evidence=evidence,
        source_snapshots=snapshots,
    )
    assert result is not None
    assert result.outline == {"sections": ["선택한 일정"], "evidence_refs": ["e-event"]}
    assert result.draft == {
        "schema_version": 2,
        "answer": "프로젝트 검토 회의 일정은 2026년 8월 18일 오전 10시부터 "
        "오전 11시까지입니다. (Asia/Seoul)",
        "evidence_refs": ["e-event"],
    }


def test_calendar_event_read_answer__confirmed_exact_event__preserves_duplicate_refs() -> None:
    evidence, snapshots = _observed_event()
    copy = {**evidence[0], "evidence_id": "e-event-copy"}
    snapshots.update(bind_task_calendar_snapshots([copy], {"e-event-copy": _fields()}))
    evidence.append(copy)
    result = project_calendar_event_read_answer(
        user_request="그 일정 언제야?",
        request_intent=_confirmed_search_intent(),
        evidence=evidence,
        source_snapshots=snapshots,
        retrieval_result=_retrieval(),
    )
    assert result is not None
    assert "오전 10시부터 오전 11시까지" in result.draft["answer"]
    assert result.draft["evidence_refs"] == ["e-event", "e-event-copy"]


@pytest.mark.parametrize(
    "fields",
    [
        ["location"],
        ["description"],
        ["status"],
        ["unknown_information"],
        ["start", "end", "location"],
        ["title", "start", "description"],
        [],
        ["title"],
        ["start"],
        ["end"],
    ],
)
def test_calendar_event_read_answer__unsupported_or_no_time_information__retains_semantic_owner(
    fields: list[str],
) -> None:
    evidence, snapshots = _observed_event()
    assert (
        project_calendar_event_read_answer(
            user_request="그 일정 언제야? 설명도 알려줘.",
            request_intent=_intent(fields),
            evidence=evidence,
            source_snapshots=snapshots,
        )
        is None
    )


@pytest.mark.parametrize("fields", [["start", "end"], ["title", "start", "end", "timezone"]])
def test_calendar_event_read_answer__typed_schedule_without_trigger_words__projects(
    fields: list[str],
) -> None:
    evidence, snapshots = _observed_event()
    assert (
        project_calendar_event_read_answer(
            user_request="Return the selected event's start and end.",
            request_intent=_intent(fields),
            evidence=evidence,
            source_snapshots=snapshots,
        )
        is not None
    )


@pytest.mark.parametrize("missing", ["responsibilities", "event_source"])
def test_calendar_event_read_answer__missing_source_responsibility__retains_semantic_owner(
    missing: str,
) -> None:
    intent = _intent()
    if missing == "responsibilities":
        intent.pop("resource_responsibilities")
    else:
        intent["resource_responsibilities"] = {"source_reads": [], "outputs": []}
    evidence, snapshots = _observed_event()
    assert (
        project_calendar_event_read_answer(
            user_request="그 일정 언제야?",
            request_intent=intent,
            evidence=evidence,
            source_snapshots=snapshots,
        )
        is None
    )


def test_calendar_event_read_answer__second_source_unsupported__does_not_drop_it() -> None:
    intent = _intent()
    intent["resource_responsibilities"] = {
        "source_reads": [
            {
                "resource_type": "CALENDAR_EVENT",
                "required_information": ["start", "end"],
                "work_unit_ids": ["work-1"],
            },
            {
                "resource_type": "CALENDAR_EVENT",
                "required_information": ["location"],
                "work_unit_ids": ["work-2"],
            },
        ],
        "outputs": [],
    }
    evidence, snapshots = _observed_event()
    assert (
        project_calendar_event_read_answer(
            user_request="두 요청을 알려줘.",
            request_intent=intent,
            evidence=evidence,
            source_snapshots=snapshots,
        )
        is None
    )


@pytest.mark.parametrize("value", ["location", ["location"]])
def test_calendar_event_read_answer__unsupported_user_requirement__cannot_be_dropped(
    value: str | list[str],
) -> None:
    intent = _intent()
    constraints = intent["constraints"]
    assert isinstance(constraints, list)
    constraints.append(
        {
            "kind": "USER_REQUIREMENT",
            "field": "required_information",
            "value": value,
        }
    )
    evidence, snapshots = _observed_event()
    assert (
        project_calendar_event_read_answer(
            user_request="그 일정 언제야? 장소도 알려줘.",
            request_intent=intent,
            evidence=evidence,
            source_snapshots=snapshots,
        )
        is None
    )


def test_calendar_event_read_answer__description_spoof__cannot_replace_provider_fields() -> None:
    evidence, snapshots = _observed_event(
        description=(
            "인용문\ntitle: 가짜 일정\nstart: 2099-01-01T20:00:00+09:00\n"
            "end: 2099-01-01T21:00:00+09:00\ntimezone: UTC"
        )
    )
    result = project_calendar_event_read_answer(
        user_request="그 일정 언제야?",
        request_intent=_intent(),
        evidence=evidence,
        source_snapshots=snapshots,
    )
    assert result is not None
    assert "프로젝트 검토 회의" in result.draft["answer"]
    assert "오전 10시부터 오전 11시까지" in result.draft["answer"]
    assert "Asia/Seoul" in result.draft["answer"]
    assert "2099" not in result.draft["answer"] and "가짜 일정" not in result.draft["answer"]


def test_calendar_event_read_answer__truncated_excerpt__uses_bound_snapshot() -> None:
    evidence, snapshots = _observed_event()
    evidence[0]["excerpt"] = "title: 프로젝트 검토 회의\nstart: 2026-08-"
    result = project_calendar_event_read_answer(
        user_request="그 일정 언제야?",
        request_intent=_intent(),
        evidence=evidence,
        source_snapshots=snapshots,
    )
    assert result is not None
    assert "오전 10시부터 오전 11시까지" in result.draft["answer"]


@pytest.mark.parametrize(
    "unavailable",
    [
        "no_snapshot",
        "no_binding",
        "stale",
        "wrong_handle",
        "wrong_version",
    ],
)
def test_calendar_event_read_answer__unavailable_or_misbound_snapshot__retains_semantic_owner(
    unavailable: str,
) -> None:
    evidence, snapshots = _observed_event()
    if unavailable == "no_snapshot":
        snapshots = {}
    elif unavailable == "no_binding":
        evidence[0].pop("locator")
    elif unavailable == "stale":
        snapshots["e-event"]["end"] = "2026-08-18T12:00:00+09:00"
    elif unavailable == "wrong_handle":
        evidence[0]["resource_handle"] = "calendar_event:other"
    else:
        evidence[0]["locator"] = {"source_version_ref": "sha256:other-observation"}
    assert (
        project_calendar_event_read_answer(
            user_request="그 일정 언제야?",
            request_intent=_intent(),
            evidence=evidence,
            source_snapshots=snapshots,
        )
        is None
    )


def test_calendar_event_read_answer__confirmed_conflicting_versions__retains_semantic_owner() -> (
    None
):
    evidence, snapshots = _observed_event()
    conflict = {**evidence[0], "evidence_id": "e-event-conflict"}
    snapshots.update(
        bind_task_calendar_snapshots(
            [conflict],
            {"e-event-conflict": _fields(end="2026-08-18T12:00:00+09:00")},
        )
    )
    evidence.append(conflict)
    assert (
        project_calendar_event_read_answer(
            user_request="그 일정 언제야?",
            request_intent=_confirmed_search_intent(),
            evidence=evidence,
            source_snapshots=snapshots,
            retrieval_result=_retrieval(),
        )
        is None
    )


@pytest.mark.parametrize("scope", ["no_anchor", "not_confirmed", "multiple_refs", "insufficient"])
def test_calendar_event_read_answer__unconfirmed_or_ambiguous_scope__retains_semantic_owner(
    scope: str,
) -> None:
    intent = _confirmed_search_intent()
    retrieval = _retrieval()
    if scope == "no_anchor":
        intent["constraints"] = []
    elif scope == "not_confirmed":
        intent["constraints"] = [
            {
                "kind": "USER_REQUIREMENT",
                "field": "search_terms",
                "value": "프로젝트 검토 회의",
                "provenance": {"source": "USER_REQUEST", "start_offset": 0, "end_offset": 10},
            }
        ]
    elif scope == "multiple_refs":
        retrieval["source_resource_refs"] = ["calendar_event:event-42", "calendar_event:other"]
    else:
        retrieval["coverage"] = "PARTIAL"
    evidence, snapshots = _observed_event()
    assert (
        project_calendar_event_read_answer(
            user_request="그 일정 언제야?",
            request_intent=intent,
            evidence=evidence,
            source_snapshots=snapshots,
            retrieval_result=retrieval,
        )
        is None
    )


def test_calendar_event_read_answer__projection_does_not_mutate_source_authorities() -> None:
    intent = _confirmed_search_intent()
    evidence, snapshots = _observed_event()
    retrieval = _retrieval()
    before = deepcopy((intent, evidence, snapshots, retrieval))
    assert (
        project_calendar_event_read_answer(
            user_request="그 일정 언제야?",
            request_intent=intent,
            evidence=evidence,
            source_snapshots=snapshots,
            retrieval_result=retrieval,
        )
        is not None
    )
    assert (intent, evidence, snapshots, retrieval) == before
