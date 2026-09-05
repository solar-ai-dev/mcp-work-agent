from typing import cast

import pytest

from google_work_agent.application.agents.retrieval.contracts.retrieval_result import (
    AcquisitionResultV1,
)
from google_work_agent.application.agents.retrieval.normalize_segments import (
    ContextBudget,
    normalize_segments,
)


def _result(text: str) -> AcquisitionResultV1:
    return cast(
        AcquisitionResultV1,
        {
            "schema_version": 1,
            "source_summaries": [
                {
                    "connector_id": "google_workspace",
                    "source": "GMAIL",
                    "resources": [
                        {
                            "resource_handle": "ephemeral-handle",
                            "resource_type": "gmail_message",
                            "resource_id": "m1",
                            "version": "v1",
                            "payload": {"body": text},
                        }
                    ],
                }
            ],
            "resource_handles": ["ephemeral-handle"],
            "availability_results": [],
        },
    )


def test_segment_id__is_stable__and_content_sensitive() -> None:
    first = normalize_segments(_result("same content"))[0].segment_id
    repeated = normalize_segments(_result("same content"))[0].segment_id
    changed = normalize_segments(_result("changed content"))[0].segment_id

    assert first == repeated
    assert first.startswith("seg_") and len(first) == 68
    assert changed != first


def test_thread_messages_keep_later_decisions_after_an_earlier_signature() -> None:
    acquisition = _result("unused")
    source = acquisition["source_summaries"][0]
    messages = [
        {
            "message_id": f"m{index}",
            "thread_id": "thread-1",
            "sender_name": "김철수 대리",
            "sender_email": "kim_0728@example.com",
            "recipients": ["user@example.com"],
            "received_at": "2026-08-20T01:00:00+00:00",
            "subject": "체육대회 안내",
            "body": body,
            "body_truncated": False,
        }
        for index, body in enumerate(
            [
                "초안은 9월 2일입니다.\n-- \n김철수 드림",
                "최신 결정: 체육대회는 9월 3일입니다.\nOn someone wrote:\nold quote",
            ]
        )
    ]
    source["resources"] = [
        {
            "resource_handle": "gmail_thread:thread-1",
            "resource_type": "gmail_thread",
            "resource_id": "thread-1",
            "version": "9",
            "payload": {
                "body": "legacy flattened text",
                "messages": messages,
                "message_count": 2,
            },
        }
    ]
    segments = normalize_segments(acquisition)
    assert len(segments) == 2
    assert {item.locator["message_id"] for item in segments} == {"m0", "m1"}
    assert all(item.resource_id == "thread-1" for item in segments)
    text = "\n".join(item.text for item in segments)
    assert "최신 결정: 체육대회는 9월 3일" in text
    assert "kim_0728@example.com" in text
    assert "2026-08-20" in text
    assert "old quote" not in text and "김철수 드림" not in text


def test_partial_message_metadata_fails_closed_instead_of_using_flattened_body() -> None:
    acquisition = _result("unused")
    acquisition["source_summaries"][0]["resources"] = [
        {
            "resource_handle": "gmail_thread:thread-1",
            "resource_type": "gmail_thread",
            "resource_id": "thread-1",
            "version": "9",
            "payload": {
                "body": "Do not silently use this",
                "messages": [{"message_id": "partial"}],
            },
        }
    ]
    with pytest.raises(ValueError, match="incomplete Gmail message evidence"):
        normalize_segments(acquisition)


@pytest.mark.parametrize(
    "busy",
    [
        [],
        [{"start": "2026-09-08T14:00:00+09:00", "end": "2026-09-08T14:30:00+09:00"}],
    ],
)
def test_freebusy_evidence__preserves_intervals_without__implying_an_event(
    busy: list[dict[str, str]],
) -> None:
    acquisition = _result("unused")
    source = acquisition["source_summaries"][0]
    source["source"] = "CALENDAR"
    source["resources"] = [
        {
            "resource_handle": "calendar_freebusy:primary",
            "resource_type": "calendar_freebusy",
            "resource_id": "primary",
            "version": "1",
            "payload": {
                "time_min": "2026-09-08T14:00:00+09:00",
                "time_max": "2026-09-08T14:30:00+09:00",
                "busy_intervals": busy,
            },
        }
    ]
    text = normalize_segments(acquisition)[0].text
    assert "not an event or a write result" in text
    assert "query_time_min: 2026-09-08T14:00:00+09:00" in text
    assert "query_time_max: 2026-09-08T14:30:00+09:00" in text
    assert "busy_intervals:" in text
    if busy:
        assert '"start": "2026-09-08T14:00:00+09:00"' in text
    else:
        assert "busy_intervals: []" in text


def test_normalize_segments__shares_bounded_context_across_resources() -> None:
    acquisition = _result("unused")
    acquisition["source_summaries"][0]["resources"] = [
        {
            "resource_handle": handle,
            "resource_type": "gmail_thread",
            "resource_id": handle,
            "version": "v1",
            "payload": {"body": " ".join(f"{handle}-{index}" for index in range(20))},
        }
        for handle in ("gmail_thread:first", "gmail_thread:second")
    ]

    segments = normalize_segments(
        acquisition,
        context_budget=ContextBudget(
            max_segments=4,
            chunk_target_tokens=12,
            chunk_max_tokens=16,
            chunk_overlap_tokens=0,
        ),
    )

    assert [segment.resource_handle for segment in segments] == [
        "gmail_thread:first",
        "gmail_thread:second",
        "gmail_thread:first",
        "gmail_thread:second",
    ]
