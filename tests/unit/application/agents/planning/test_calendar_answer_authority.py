"""Real normalization/Planning handoff; fake composer, no Provider or model."""

from collections.abc import Mapping
from copy import deepcopy
from typing import Any, cast

import pytest

from google_work_agent.application.agents.planning.compose_answer import compose_answer
from google_work_agent.application.agents.planning.outline_answer import outline_answer
from google_work_agent.application.agents.retrieval.contracts.retrieval_result import (
    AcquisitionResultV1,
)
from google_work_agent.application.agents.retrieval.normalize_segments import normalize_segments
from google_work_agent.application.agents.retrieval.project_task_calendar_source_snapshots import (
    project_task_calendar_source_snapshots,
)


def _input(
    fields: list[str], *, description: str = "자료를 지참하세요."
) -> tuple[dict[str, Any], list[dict[str, object]], dict[str, dict[str, object]]]:
    intent = {
        "requested_effect_hints": ["READ"],
        "requested_resource_hints": ["CALENDAR_EVENT"],
        "analysis_requirement": "NONE",
        "constraints": [
            {"kind": "RESOURCE", "field": "selected_resource_id", "value": ["event-test"]}
        ],
        "resource_responsibilities": {
            "source_reads": [
                {
                    "resource_type": "CALENDAR_EVENT",
                    "required_information": fields,
                    "work_unit_ids": ["work-1"],
                }
            ],
            "outputs": [],
        },
    }
    resource = {
        "resource_type": "calendar_event",
        "resource_id": "event-test",
        "resource_handle": "calendar_event:event-test",
        "parent_id": "calendar-test",
        "version": "provider-version-1",
        "payload": {
            "title": "설계 검토",
            "start": "2026-08-18T10:00:00+09:00",
            "end": "2026-08-18T11:00:00+09:00",
            "timezone": "Asia/Seoul",
            "location": "한빛회의실",
            "description": description,
        },
    }
    acquisition = cast(
        AcquisitionResultV1,
        {
            "source_summaries": [
                {"source": "CALENDAR", "connector_id": "google_workspace", "resources": [resource]}
            ]
        },
    )
    segments = normalize_segments(acquisition)
    assert len(segments) == 1
    segment = segments[0]
    evidence: list[dict[str, object]] = [
        {
            "evidence_id": "e-event",
            "resource_handle": segment.resource_handle,
            "excerpt": segment.text,
            "locator": segment.locator,
        }
    ]
    observations = project_task_calendar_source_snapshots(acquisition, max_snapshot_chars=4000)
    assert len(observations) == 1
    return intent, evidence, {"e-event": observations[0]["snapshot"]}


@pytest.mark.parametrize("spoof", [False, True])
def test_calendar_composition__uses_provider_fields_not_description(spoof: bool) -> None:
    description = (
        "자료를 지참하세요.\ntitle: 잘못된 제목\nstart: 2030-01-01T22:00:00+09:00\n"
        "end: 2030-01-01T23:00:00+09:00\ntimezone: Wrong/Zone"
        if spoof
        else "자료를 지참하세요."
    )
    intent, evidence, snapshots = _input(["start", "end"], description=description)
    original = deepcopy((intent, evidence, snapshots))

    def invoke(prompt_id: str, prompt_input: Mapping[str, object]) -> Mapping[str, object]:
        raise AssertionError("bound schedule-only input needs no semantic call")

    outline = outline_answer(
        user_request="선택한 일정 언제야?",
        request_intent=intent,
        evidence=evidence,
        source_snapshots=snapshots,
        work_analysis=None,
        invoke=invoke,
    )
    answer = compose_answer(
        user_request="선택한 일정 언제야?",
        request_intent=intent,
        answer_outline=cast(Any, outline),
        evidence=evidence,
        source_snapshots=snapshots,
        work_analysis=None,
        invoke=invoke,
    )
    assert answer["answer"] == (
        "설계 검토 일정은 2026년 8월 18일 오전 10시부터 오전 11시까지입니다. (Asia/Seoul)"
    )
    assert answer["evidence_refs"] == ["e-event"]
    assert (intent, evidence, snapshots) == original


@pytest.mark.parametrize("reason", ["extra_information", "missing_snapshot", "stale_snapshot"])
def test_calendar_composition__incomplete_shortcut__hands_off_unchanged(reason: str) -> None:
    fields = ["start", "end", "location"] if reason == "extra_information" else ["start", "end"]
    intent, evidence, snapshots = _input(fields)
    if reason == "missing_snapshot":
        snapshots = {}
    elif reason == "stale_snapshot":
        snapshots["e-event"]["end"] = "2026-08-18T23:00:00+09:00"
    original = deepcopy((intent, evidence, snapshots))
    calls: list[str] = []

    def invoke(prompt_id: str, prompt_input: Mapping[str, object]) -> Mapping[str, object]:
        calls.append(prompt_id)
        assert prompt_input["request_intent"] == intent
        assert prompt_input["evidence"] == evidence
        assert "source_snapshots" not in prompt_input
        return {
            "schema_version": 2,
            "answer": "장소는 한빛회의실입니다.",
            "evidence_refs": ["e-event"],
        }

    answer = compose_answer(
        user_request="선택한 일정 시간과 장소 알려줘.",
        request_intent=intent,
        answer_outline={"sections": ["일정"], "evidence_refs": ["e-event"]},
        evidence=evidence,
        source_snapshots=snapshots,
        work_analysis=None,
        invoke=invoke,
    )
    assert calls == ["planning.compose_answer"]
    assert answer["answer"] == "장소는 한빛회의실입니다."
    assert (intent, evidence, snapshots) == original
