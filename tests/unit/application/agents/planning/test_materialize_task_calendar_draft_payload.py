from google_work_agent.application.agents.planning.materialize_task_calendar_draft_payload import (
    materialize_task_calendar_draft_payload,
)


def test_materialize_task_calendar_draft_payload__with_exact_typed_evidence__returns_payload(
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
                    "value": ["Atlas 할 일과 인쇄소 일정을 메일 초안으로 저장해줘."],
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
                    "title: Atlas QR 문구 확정\nstatus: needsAction\n"
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
    assert "진행 중 (needsAction)" in str(payload["body"])
    assert "확정 (confirmed)" in str(payload["body"])
