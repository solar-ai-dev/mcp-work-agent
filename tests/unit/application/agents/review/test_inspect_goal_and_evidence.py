from __future__ import annotations

from collections.abc import Mapping
from typing import cast

import pytest

from google_work_agent.application.agents.review.contracts.review_findings import (
    ReviewSemanticInvoker,
)
from google_work_agent.application.agents.review.inspect_goal_and_evidence import (
    inspect_goal_and_evidence,
)

DIMENSION = "review.inspect_goal_and_evidence"


def _result(*, dimension: str = DIMENSION) -> dict[str, object]:
    return {
        "schema_version": 1,
        "dimension": dimension,
        "findings": [
            {
                "dimension": dimension,
                "code": "UNSUPPORTED_CLAIM",
                "finding_kind": "ISSUE",
                "description": "The conclusion is not grounded.",
                "evidence_refs": ["ev-1"],
                "affected_action_ids": [],
                "affected_route_ids": [],
                "required_information": [],
            }
        ],
    }


def test_inspect_goal_and__evidence_uses_only__its_minimum_projection() -> None:
    calls: list[tuple[str, dict[str, object]]] = []

    def invoke(prompt_id: str, prompt_input: Mapping[str, object]) -> Mapping[str, object]:
        calls.append((prompt_id, dict(prompt_input)))
        return _result()

    result = inspect_goal_and_evidence(
        request_intent={"goal": "answer"},
        planning_result={"schema_version": 2, "answer": "draft"},
        evidence=[{"evidence_ref": "ev-1"}],
        work_analysis={"facts": []},
        invoke=invoke,
    )

    assert result["dimension"] == DIMENSION
    assert set(calls[0][1]) == {
        "request_intent",
        "planning_result",
        "evidence",
        "work_analysis",
    }
    assert "status" not in result


def test_inspect_goal_and_evidence_passes_optional_run_reference_time() -> None:
    calls: list[dict[str, object]] = []

    def invoke(prompt_id: str, prompt_input: Mapping[str, object]) -> Mapping[str, object]:
        assert prompt_id == DIMENSION
        calls.append(dict(prompt_input))
        return {"schema_version": 1, "dimension": DIMENSION, "findings": []}

    inspect_goal_and_evidence(
        request_intent={"goal": "create event"},
        planning_result={"schema_version": 2, "actions": []},
        evidence=[],
        run_reference_time={
            "reference_time": "2026-08-07T09:00:03+09:00",
            "timezone": "Asia/Seoul",
        },
        invoke=invoke,
    )

    assert calls[0]["run_reference_time"] == {
        "reference_time": "2026-08-07T09:00:03+09:00",
        "timezone": "Asia/Seoul",
    }


def test_inspect_goal_and_evidence__passes_current_preview_edit__as_user_authority() -> None:
    calls: list[dict[str, object]] = []

    def invoke(prompt_id: str, prompt_input: Mapping[str, object]) -> Mapping[str, object]:
        del prompt_id
        calls.append(dict(prompt_input))
        return {"schema_version": 1, "dimension": DIMENSION, "findings": []}

    inspect_goal_and_evidence(
        request_intent={"goal": "original"},
        planning_result={"schema_version": 2, "actions": []},
        evidence=[],
        user_action_modifications=[
            {
                "action_id": "action-1",
                "argument_overrides": {"subject": "After", "body": "After body"},
            }
        ],
        invoke=cast(ReviewSemanticInvoker, invoke),
    )

    assert calls[0]["user_action_modifications"] == [
        {
            "action_id": "action-1",
            "argument_overrides": {"subject": "After", "body": "After body"},
        }
    ]


@pytest.mark.parametrize("dimension", ["GOAL_EVIDENCE", "review.unknown"])
def test_inspect_goal__and_evidence__rejects_noncanonical_dimension(dimension: str) -> None:
    with pytest.raises(ValueError, match="invalid dimension"):
        inspect_goal_and_evidence(
            request_intent={},
            planning_result={},
            evidence=[],
            invoke=lambda _prompt_id, _input: _result(dimension=dimension),
        )


def test_inspect_goal__and_evidence_rejects__final_disposition_field() -> None:
    candidate = _result()
    candidate["status"] = "REVISE"
    with pytest.raises(ValueError, match="keys do not match"):
        inspect_goal_and_evidence(
            request_intent={},
            planning_result={},
            evidence=[],
            invoke=lambda _prompt_id, _input: candidate,
        )


def test_cross_resource_draft__fully_grounded_preview__skips_semantic_review() -> None:
    calls: list[object] = []
    def invoke(*_args: object) -> dict[str, object]:
        calls.append(object())
        return _result()

    result = inspect_goal_and_evidence(
        request_intent={
            "ambiguity": {"requires_confirmation": False},
            "constraints": [
                {"kind": "PERSON", "field": "recipient", "value": "owner@example.com"}
            ],
            "resource_responsibilities": {
                "source_reads": [
                    {"resource_type": "TASK", "required_information": ["title", "due"]},
                    {
                        "resource_type": "CALENDAR_EVENT",
                        "required_information": ["title", "start", "end"],
                    },
                ],
                "outputs": [{"resource_type": "GMAIL_DRAFT", "effect": "CREATE"}],
            },
        },
        planning_result={
            "actions": [
                {
                    "route_id": "draft",
                    "tool_id": "gmail_create_draft",
                    "effect": "CREATE",
                    "arguments": {
                        "payload": {
                            "to": ["owner@example.com"],
                            "subject": "Orion 준비 상황",
                            "body": (
                                "Orion 준비 상황\nQR 확정 (담당자: 수진) 2026-09-16\n"
                                "상태: 진행 중 (needsAction)\n"
                                "Orion 제작소 일정 2026-09-13 14:00~15:00\n"
                                "상태: 확정 (confirmed)"
                            ),
                        }
                    },
                    "evidence_refs": ["e-task", "e-event", "user-message"],
                }
            ]
        },
        evidence=[
            {
                "evidence_id": "e-task",
                "resource_handle": "task:t1",
                "excerpt": (
                    "title: Orion QR 확정\nstatus: needsAction\n"
                    "due: 2026-09-16T00:00:00Z\n"
                    "notes:\n담당 수진"
                ),
            },
            {
                "evidence_id": "e-event",
                "resource_handle": "calendar_event:e1",
                "excerpt": (
                    "title: Orion 제작소 일정\n"
                    "start: 2026-09-13T14:00:00+09:00\n"
                    "end: 2026-09-13T15:00:00+09:00\nstatus: confirmed"
                ),
            },
            {
                "evidence_id": "user-message",
                "origin_type": "USER_MESSAGE",
                "excerpt": "메일 초안으로 저장해줘",
            },
        ],
        invoke=cast(ReviewSemanticInvoker, invoke),
    )

    assert result == {"schema_version": 1, "dimension": DIMENSION, "findings": []}
    assert calls == []


@pytest.mark.parametrize(
    "gap", ["recipient", "title", "date", "status", "reference", "other_source"]
)
def test_cross_resource_draft__incomplete_preview__retains_semantic_review(gap: str) -> None:
    intent: dict[str, object] = {
        "ambiguity": {"requires_confirmation": False},
        "constraints": [
            {"kind": "PERSON", "field": "recipient", "value": "owner@example.com"}
        ],
        "resource_responsibilities": {
            "source_reads": [
                {"resource_type": "TASK", "required_information": ["title"]},
                {"resource_type": "CALENDAR_EVENT", "required_information": ["start"]},
            ],
            "outputs": [{"resource_type": "GMAIL_DRAFT", "effect": "CREATE"}],
        },
    }
    body = (
        "Orion QR 확정 2026-09-16 상태: 진행 중 (needsAction)\n"
        "Orion 제작소 일정 2026-09-13 14:00~15:00 상태: 확정 (confirmed)"
    )
    action: dict[str, object] = {
        "tool_id": "gmail_create_draft",
        "effect": "CREATE",
        "arguments": {
            "payload": {
                "to": ["owner@example.com"],
                "subject": "Orion 준비 상황",
                "body": body,
            }
        },
        "evidence_refs": ["e-task", "e-event"],
    }
    evidence: list[dict[str, object]] = [
        {
            "evidence_id": "e-task",
            "resource_handle": "task:t1",
            "excerpt": (
                "title: Orion QR 확정\nstatus: needsAction\ndue: 2026-09-16T00:00:00Z"
            ),
        },
        {
            "evidence_id": "e-event",
            "resource_handle": "calendar_event:e1",
            "excerpt": (
                "title: Orion 제작소 일정\nstart: 2026-09-13T14:00:00+09:00\n"
                "end: 2026-09-13T15:00:00+09:00\nstatus: confirmed"
            ),
        },
    ]
    if gap == "recipient":
        action["arguments"] = {
            "payload": {"to": ["other@example.com"], "subject": "Orion", "body": body}
        }
    elif gap == "title":
        evidence[0]["excerpt"] = (
            "title: Orion 포장 확인\nstatus: needsAction\ndue: 2026-09-16T00:00:00Z"
        )
    elif gap == "date":
        evidence[0]["excerpt"] = (
            "title: Orion QR 확정\nstatus: needsAction\ndue: 2026-09-17T00:00:00Z"
        )
    elif gap == "status":
        evidence[0]["excerpt"] = (
            "title: Orion QR 확정\nstatus: completed\ndue: 2026-09-16T00:00:00Z"
        )
    elif gap == "reference":
        action["evidence_refs"] = ["e-event"]
    else:
        evidence.append(
            {"evidence_id": "e-mail", "resource_handle": "gmail_thread:m1", "excerpt": "x"}
        )
    calls: list[object] = []

    def invoke(*_args: object) -> dict[str, object]:
        calls.append(object())
        return _result()

    inspect_goal_and_evidence(
        request_intent=intent,
        planning_result={"actions": [action]},
        evidence=evidence,
        invoke=cast(ReviewSemanticInvoker, invoke),
    )

    assert len(calls) == 1
