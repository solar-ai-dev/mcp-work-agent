from google_work_agent.application.agents.planning.project_calendar_event_read_answer import (
    project_calendar_event_read_answer,
)


def _intent() -> dict[str, object]:
    return {
        "requested_effect_hints": ["READ"],
        "requested_resource_hints": ["CALENDAR_EVENT"],
        "analysis_requirement": "NONE",
        "constraints": [
            {
                "kind": "RESOURCE",
                "field": "selected_resource_id",
                "value": ["event-42"],
            }
        ],
    }


def _evidence() -> list[dict[str, object]]:
    return [
        {
            "evidence_id": "e-event",
            "resource_handle": "calendar_event:event-42",
            "excerpt": (
                "calendar_id: primary\n"
                "event_id: event-42\n"
                "title: 프로젝트 검토 회의\n"
                "start: 2026-08-18T10:00:00+09:00\n"
                "end: 2026-08-18T11:00:00+09:00\n"
                "timezone: Asia/Seoul\n"
                "status: confirmed"
            ),
        }
    ]


def test_calendar_event_read_answer__selected_event__preserves_exact_interval() -> None:
    result = project_calendar_event_read_answer(
        user_request="그 일정 언제야?",
        request_intent=_intent(),
        evidence=_evidence(),
    )

    assert result is not None
    assert result.outline == {"sections": ["선택한 일정"], "evidence_refs": ["e-event"]}
    assert result.draft == {
        "schema_version": 2,
        "answer": (
            "프로젝트 검토 회의 일정은 2026년 8월 18일 오전 10시부터 "
            "오전 11시까지입니다. (Asia/Seoul)"
        ),
        "evidence_refs": ["e-event"],
    }


def test_calendar_event_read_answer__different_or_ambiguous_scope__falls_back() -> None:
    assert (
        project_calendar_event_read_answer(
            user_request="일정을 요약해줘.",
            request_intent=_intent(),
            evidence=_evidence(),
        )
        is None
    )
    intent = _intent()
    intent["constraints"] = []
    assert (
        project_calendar_event_read_answer(
            user_request="그 일정 언제야?",
            request_intent=intent,
            evidence=_evidence(),
        )
        is None
    )


def test_calendar_event_read_answer__malformed_or_unselected_evidence__falls_back() -> None:
    evidence = _evidence()
    evidence[0]["resource_handle"] = "calendar_event:other"
    assert (
        project_calendar_event_read_answer(
            user_request="그 일정 언제야?",
            request_intent=_intent(),
            evidence=evidence,
        )
        is None
    )
