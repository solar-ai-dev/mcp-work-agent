import pytest

from google_work_agent.application.agents.planning.materialize_task_calendar_draft_payload import (
    materialize_task_calendar_draft_payload,
)


@pytest.mark.parametrize(
    ("korean", "task_status", "expected_label"),
    [
        (True, "needsAction", "미완료"),
        (False, "needsAction", "Incomplete"),
        (True, "completed", "완료"),
        (False, "completed", "Completed"),
        (True, "unknown-provider-state", "unknown-provider-state"),
        (False, "unknown-provider-state", "unknown-provider-state"),
    ],
)
def test_materialize_task_calendar_draft_payload__with_exact_typed_evidence__returns_payload(
    korean: bool, task_status: str, expected_label: str,
) -> None:
    payload = materialize_task_calendar_draft_payload(
        route={
            "resource_type": "GMAIL_DRAFT",
            "effect": "CREATE",
            "selected_tool_id": "gmail_create_draft",
        },
        request_intent={
            "ambiguity": {"requires_confirmation": False},
            "constraints": [
                {
                    "kind": "USER_REQUIREMENT",
                    "field": "search_terms",
                    "value": "Atlas",
                    "provenance": {"source": "USER_REQUEST", "start_offset": 0},
                },
                {
                    "kind": "USER_REQUIREMENT",
                    "field": "search_terms",
                    "value": "인쇄소 일정",
                    "provenance": {"source": "USER_REQUEST", "start_offset": 10},
                },
                {
                    "kind": "PERSON",
                    "field": "recipient",
                    "value": "owner@example.com",
                },
                {
                    "kind": "USER_REQUIREMENT",
                    "field": "original_search_request",
                    "value": [
                        "Atlas 할 일과 인쇄소 일정을 메일 초안으로 저장해줘."
                        if korean
                        else "Prepare a draft using the project tasks and printing schedule."
                    ],
                },
            ],
            "resource_responsibilities": {
                "source_reads": [
                    {"resource_type": "TASK", "required_information": ["title"]},
                    {
                        "resource_type": "CALENDAR_EVENT",
                        "required_information": ["start"],
                    },
                ],
                "outputs": [{"resource_type": "GMAIL_DRAFT", "effect": "CREATE"}],
            },
        },
        evidence=[
            {
                "resource_handle": "task:t1",
                "excerpt": (
                    f"title: Atlas QR 문구 확정\nstatus: {task_status}\n"
                    "due: 2026-08-16T00:00:00Z\nnotes:\n담당 지민"
                ),
            },
            {
                "resource_handle": "calendar_event:e1",
                "excerpt": (
                    "title: Atlas 인쇄소 슬롯\nstart: 2026-08-13T14:00:00+09:00\n"
                    "end: 2026-08-13T15:00:00+09:00\nstatus: confirmed"
                ),
            },
        ],
    )

    assert payload is not None
    assert payload["to"] == ["owner@example.com"]
    assert f"{expected_label} ({task_status})" in str(payload["body"])
    assert ("확정 (confirmed)" if korean else "Confirmed (confirmed)") in str(payload["body"])
    assert "진행 중" not in str(payload["body"])
    assert "In progress" not in str(payload["body"])
