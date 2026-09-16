from copy import deepcopy

import pytest

from google_work_agent.adapters.langgraph.subgraphs.review.projections import (
    inspect_goal_and_evidence_projection,
)
from google_work_agent.ports.system.contracts.workflow_execution import (
    WorkflowCorrelationContext,
    WorkflowStartRequest,
)

project_inspect_goal_and_evidence_input = (
    inspect_goal_and_evidence_projection.project_inspect_goal_and_evidence_input
)


def _state(*, axes: list[str] | None = None) -> dict[str, object]:
    request = WorkflowStartRequest(
        run_id="run-1",
        conversation_id="conversation-1",
        workflow_key="workflow-1",
        entry_mode="AGENT_SEARCH",
        requested_mode="LOCAL_GPU",
        request_text="내일 일정",
        selected_resource_ids=(),
        correlation=WorkflowCorrelationContext("request-1", None, "1"),
        run_budget={"started_at_ms": 1786060803921},
    )
    return {
        "__request__": request,
        "request_intent": {
            "constraints": [
                {"kind": "TIME", "field": "temporal_axis", "value": axes or ["EVENT_TIME"]}
            ]
        },
        "planning_result": {"schema_version": 2, "actions": []},
        "evidence": [
            {
                "evidence_id": "mail-1",
                "resource_handle": "gmail_thread:thread-1",
                "excerpt": (
                    "Message: message-1\nSubject\nThread messages collected: 1/1\n"
                    "Received: 2026-09-07T02:13:22+00:00\n"
                    "업무 날짜는 8월 8일입니다."
                ),
                "locator": {"received_at": "2026-09-07T02:13:22+00:00"},
            }
        ],
    }


def test_initial_event_time_review_separates_receipt_from_content() -> None:
    state = _state()
    original = deepcopy(state["evidence"])

    result = project_inspect_goal_and_evidence_input(state)

    assert result["run_reference_time"]["reference_time"].startswith("2026-08-07")
    assert "Received:" not in result["evidence"][0]["excerpt"]
    assert "업무 날짜는 8월 8일입니다." in result["evidence"][0]["excerpt"]
    assert "received_at" not in result["evidence"][0]["locator"]
    assert state["evidence"] == original


@pytest.mark.parametrize(
    "patch",
    [
        {"axes": ["MESSAGE_TIME"]},
        {"axes": ["EVENT_TIME", "MESSAGE_TIME"]},
        {"user_action_modifications": [{"action_id": "a1", "argument_overrides": {}}]},
        {"confirmation_response": {"response_kind": "OPTION"}},
    ],
)
def test_noninitial_or_message_time_review_preserves_receipt(patch: dict[str, object]) -> None:
    state = _state(axes=patch.get("axes"))
    state.update({key: value for key, value in patch.items() if key != "axes"})

    result = project_inspect_goal_and_evidence_input(state)

    assert "run_reference_time" not in result
    assert result["evidence"] == state["evidence"]


def test_unrecognized_mail_envelope_preserves_original_input() -> None:
    state = _state()
    state["evidence"][0]["locator"]["received_at"] = "different"

    result = project_inspect_goal_and_evidence_input(state)

    assert "run_reference_time" not in result
    assert result["evidence"] == state["evidence"]
