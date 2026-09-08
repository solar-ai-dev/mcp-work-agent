import hashlib
import json
from typing import cast

import pytest

from google_work_agent.application.agents.retrieval.contracts.retrieval_result import (
    AcquisitionResultV1,
)
from google_work_agent.application.agents.retrieval.normalize_segments import (
    ContextBudget,
    normalize_segments,
)
from google_work_agent.application.agents.retrieval.select_evidence import (
    materialize_evidence_drafts,
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


def test_gmail_preview__without_body__preserves_metadata_only_fact() -> None:
    result = _result("known body")
    assert normalize_segments(result)[0].locator["is_metadata_only"] is False
    resources = cast(list[dict[str, object]], result["source_summaries"][0]["resources"])
    resources[0]["payload"] = {"subject": "reference"}
    assert normalize_segments(result)[0].locator["is_metadata_only"] is True


def test_gmail_draft__keeps_full_mutable_payload_in_planning_evidence() -> None:
    result = _result("unused")
    resources = cast(list[dict[str, object]], result["source_summaries"][0]["resources"])
    resources[0] = {
        "resource_handle": "gmail_draft:draft-1",
        "resource_type": "gmail_draft",
        "resource_id": "draft-1",
        "version": "v1",
        "payload": {
            "to": ["recipient@example.com"],
            "cc": [],
            "bcc": [],
            "subject": "Quartz 납품 회신 검토",
            "body": "기존 본문",
            "thread_id": None,
            "in_reply_to": None,
            "references": None,
            "attachments": [],
        },
    }

    text = normalize_segments(result)[0].text

    assert "draft_id: draft-1" in text
    assert 'to: ["recipient@example.com"]' in text
    assert 'subject: "Quartz 납품 회신 검토"' in text
    assert "body:\n기존 본문" in text


def test_github_issue__preserves_observed_metadata__separately_from_description() -> None:
    result = cast(
        AcquisitionResultV1,
        {
            "schema_version": 1,
            "resource_handles": ["github_issue:sample/project#17"],
            "availability_results": [],
            "source_summaries": [
                {
                    "connector_id": "github",
                    "source": "GITHUB",
                    "resources": [
                        {
                            "resource_handle": "github_issue:sample/project#17",
                            "resource_type": "github_issue",
                            "resource_id": "sample/project#17",
                            "version": "v1",
                            "payload": {
                                "repository": "sample/project",
                                "issue_number": 17,
                                "title": "연결 확인",
                                "state": "OPEN",
                                "url": "https://github.com/sample/project/issues/17",
                                "description": "개발 작업이 필요하지 않은 참고 자료입니다.",
                            },
                        }
                    ],
                }
            ],
        },
    )
    segment = normalize_segments(result)[0]
    assert "issue_number: 17" in segment.text
    assert "title: 연결 확인" in segment.text
    assert "state: OPEN" in segment.text
    assert "description:\n개발 작업이 필요하지 않은 참고 자료입니다." in segment.text
    assert segment.resource_handle == "github_issue:sample/project#17"
    assert normalize_segments(result)[0].segment_id == segment.segment_id


def test_task_detail__with_observed_business_fields__preserves_target_and_values() -> None:
    result = cast(
        AcquisitionResultV1,
        {
            "schema_version": 1,
            "resource_handles": ["task:task-1"],
            "availability_results": [],
            "source_summaries": [
                {
                    "connector_id": "google_workspace",
                    "source": "TASKS",
                    "resources": [
                        {
                            "resource_handle": "task:task-1",
                            "resource_type": "task",
                            "resource_id": "task-1",
                            "parent_id": "list-1",
                            "version": "v1",
                            "payload": {
                                "title": "현재 제목",
                                "status": "needsAction",
                                "due": "2026-09-15T00:00:00.000Z",
                                "notes": (
                                    "현재 업무 메모\n\n"
                                    "\u200bgwa-recovery-fingerprint:internal-marker"
                                ),
                            },
                        }
                    ],
                }
            ],
        },
    )

    text = normalize_segments(result)[0].text

    assert "task_list_id: list-1" in text
    assert "title: 현재 제목" in text
    assert "status: needsAction" in text
    assert "due: 2026-09-15T00:00:00.000Z" in text
    assert "notes:\n현재 업무 메모" in text
    assert "recovery-fingerprint" not in text


def test_calendar_event_detail__with_current_fields__preserves_write_evidence() -> None:
    result = cast(
        AcquisitionResultV1,
        {
            "schema_version": 1,
            "resource_handles": ["calendar_event:event-1"],
            "availability_results": [],
            "source_summaries": [
                {
                    "connector_id": "google_workspace",
                    "source": "CALENDAR",
                    "resources": [
                        {
                            "resource_handle": "calendar_event:event-1",
                            "resource_type": "calendar_event",
                            "resource_id": "event-1",
                            "parent_id": "calendar-1",
                            "version": "etag-1",
                            "payload": {
                                "title": "현재 일정",
                                "start": "2026-09-14T15:00:00+09:00",
                                "end": "2026-09-14T15:30:00+09:00",
                                "timezone": "Asia/Seoul",
                                "status": "confirmed",
                                "location": "기존 회의실",
                                "description": "현재 설명",
                                "attendees": [],
                            },
                        }
                    ],
                }
            ],
        },
    )

    text = normalize_segments(result)[0].text

    assert "calendar_id: calendar-1" in text
    assert "event_id: event-1" in text
    assert "title: 현재 일정" in text
    assert "start: 2026-09-14T15:00:00+09:00" in text
    assert "end: 2026-09-14T15:30:00+09:00" in text
    assert "timezone: Asia/Seoul" in text
    assert "location: 기존 회의실" in text
    assert "description: 현재 설명" in text
    assert "attendees: []" in text


@pytest.mark.parametrize("overlap", [0, 20])
def test_source_chunking__long_source__preserves_header_and_line_boundaries(overlap: int) -> None:
    text = (
        "Received: 2026-08-31T12:37:03+00:00\n"
        "Upcoming openings 09/01 ~ 09/07\n\n"
        "Ecology research recruitment\nSchedule 09/01 ~ 09/09\n\n"
        "Design recruitment\nSchedule 09/01 ~ 09/14\n\n"
    ) * 4
    segments = normalize_segments(
        _result(text),
        context_budget=ContextBudget(
            chunk_target_tokens=130,
            chunk_max_tokens=160,
            chunk_overlap_tokens=overlap,
        ),
    )
    assert len(segments) > 1
    assert all(segment.text in text for segment in segments)
    assert any("\n\n" in segment.text for segment in segments)
    assert any("recruitment\nSchedule" in segment.text for segment in segments)
    assert all(len(segment.text.encode("utf-8")) <= 160 for segment in segments)
    flat = normalize_segments(
        _result(" ".join(text.split())),
        context_budget=ContextBudget(
            chunk_target_tokens=130,
            chunk_max_tokens=160,
            chunk_overlap_tokens=overlap,
        ),
    )
    assert {segment.segment_id for segment in segments}.isdisjoint(
        segment.segment_id for segment in flat
    )


def test_search_candidate__sender_metadata__does_not_promote_body_mentions() -> None:
    acquisition = _result("김정우 대리에게 문의하세요")
    resources = cast(list[dict[str, object]], acquisition["source_summaries"][0]["resources"])
    payload = cast(dict[str, object], resources[0]["payload"])
    payload.update(
        {
            "sender_name": "김철수 대리",
            "sender_email": "kim_0728@example.com",
            "received_at": "Thu, 20 Aug 2026 10:00:00 +0900",
        }
    )
    segment = normalize_segments(acquisition)[0]
    assert "Sender name: 김철수 대리" in segment.text
    assert "Sender email: kim_0728@example.com" in segment.text
    assert segment.locator["sender_name"] == "김철수 대리"
    assert segment.locator["sender_email"] == "kim_0728@example.com"
    assert "김정우 대리" not in str(segment.locator)
    assert "message_id" not in segment.locator
    payload["sender_email"] = {"guessed": "identity"}
    with pytest.raises(ValueError, match="invalid Gmail candidate metadata"):
        normalize_segments(acquisition)


def test_detail_growth__acquired_evidence__preserves_identity_on_rebuild() -> None:
    acquisition = _result("\n".join(f"항목 {n}의 날짜와 업무 내용입니다." for n in range(20)))
    budget = ContextBudget(max_segments=4, chunk_target_tokens=70, chunk_max_tokens=100)
    prior = normalize_segments(acquisition, context_budget=budget)
    protected = prior[-1].segment_id
    resources = cast(list[dict[str, object]], acquisition["source_summaries"][0]["resources"])
    resources.extend(
        {
            "resource_handle": f"gmail_thread:new-{n}",
            "resource_type": "gmail_thread",
            "resource_id": f"new-{n}",
            "version": "1",
            "payload": {"body": f"새로운 메일 {n}"},
        }
        for n in range(6)
    )
    resources.append(
        {
            "resource_handle": "task:new",
            "resource_type": "task",
            "resource_id": "new",
            "version": "1",
            "payload": {"title": "확인할 업무"},
        }
    )
    task = resources.pop()
    acquisition["source_summaries"].append(
        {
            "connector_id": "google_workspace",
            "source": "TASKS",
            "resources": [task],
        }
    )
    ordinary = normalize_segments(acquisition, context_budget=budget)
    assert protected not in {segment.segment_id for segment in ordinary}
    kept = normalize_segments(
        acquisition,
        context_budget=budget,
        preferred_segment_ids=[protected],
    )
    assert len(kept) == budget.max_segments
    assert kept[0].segment_id == protected
    assert {segment.source for segment in kept} == {"GMAIL", "TASKS"}
    rebuilt = normalize_segments(
        acquisition,
        context_budget=budget,
        preferred_segment_ids=[segment.segment_id for segment in kept],
    )
    assert rebuilt == kept
    resources[0]["version"] = "2"
    changed = normalize_segments(
        acquisition,
        context_budget=budget,
        preferred_segment_ids=[protected],
    )
    assert protected not in {segment.segment_id for segment in changed}


def test_thread_messages__earlier_signature__keeps_later_decisions() -> None:
    acquisition = _result("unused")
    source = acquisition["source_summaries"][0]
    messages = [
        {
            "message_id": f"m{index}",
            "thread_id": "thread-1",
            "rfc822_message_id": f"<m{index}@example.com>",
            "references": None if index == 0 else "<m0@example.com>",
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
    assert {item.locator["rfc822_message_id"] for item in segments} == {
        "<m0@example.com>",
        "<m1@example.com>",
    }
    assert {item.locator["references"] for item in segments} == {
        None,
        "<m0@example.com>",
    }
    assert all(item.resource_id == "thread-1" for item in segments)
    text = "\n".join(item.text for item in segments)
    assert "최신 결정: 체육대회는 9월 3일" in text
    assert "kim_0728@example.com" in text
    assert "2026-08-20" in text
    assert "old quote" not in text and "김철수 드림" not in text


def test_message_metadata__partial__fails_closed_without_flattened_body() -> None:
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


def test_source_chunks__identical_text_in_two_messages__keeps_distinct_provenance() -> None:
    acquisition = _result("unused")
    messages = [
        {
            "message_id": f"m{index}",
            "thread_id": "thread-1",
            "sender_name": "김철수 대리",
            "sender_email": "kim_0728@example.com",
            "recipients": ["recipient@example.com"],
            "received_at": "2026-08-20T10:00:00Z",
            "subject": "체육대회",
            "body": " ".join(["동일한 본문 내용"] * 100),
            "body_truncated": False,
        }
        for index in range(2)
    ]
    acquisition["source_summaries"][0]["resources"] = [
        {
            "resource_handle": "gmail_thread:thread-1",
            "resource_type": "gmail_thread",
            "resource_id": "thread-1",
            "version": "1",
            "payload": {"messages": messages, "message_count": 2},
        }
    ]
    segments = normalize_segments(
        acquisition,
        context_budget=ContextBudget(
            chunk_target_tokens=30,
            chunk_max_tokens=40,
            chunk_overlap_tokens=0,
        ),
    )
    assert len(segments) > 4
    assert len({segment.segment_id for segment in segments}) == len(segments)
    assert all(segment.locator["sender_email"] == "kim_0728@example.com" for segment in segments)
    assert all(segment.locator["sender_name"] == "김철수 대리" for segment in segments)
    assert all(segment.locator["thread_id"] == "thread-1" for segment in segments)
    assert all(segment.locator["received_at"] == "2026-08-20T10:00:00Z" for segment in segments)
    assert all(segment.locator["recipients"] == ["recipient@example.com"] for segment in segments)
    selected = segments[-2:]
    drafts = materialize_evidence_drafts(
        {
            "schema_version": 2,
            "selected_segment_ids": [segment.segment_id for segment in selected],
            "excluded_segment_ids": [],
            "evidence_drafts": [
                {"segment_id": segment.segment_id, "role": "CONTEXT", "relevance_reason": "후보"}
                for segment in selected
            ],
        },
        segments=segments,
    )
    assert [draft["locator"] for draft in drafts] == [segment.locator for segment in selected]
    assert len({draft["evidence_id"] for draft in drafts}) == 2


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


def test_normalize_segments__multiple_resources__shares_bounded_context() -> None:
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


def _github_result(
    issues: list[tuple[int, str, str]],
) -> AcquisitionResultV1:
    resources = [
        {
            "resource_handle": f"github_issue:acme/repo#{number}",
            "resource_type": "github_issue",
            "resource_id": f"acme/repo#{number}",
            "parent_id": "acme/repo",
            "version": version,
            "connector_id": "github",
            "payload": {"title": title},
        }
        for number, version, title in issues
    ]
    return cast(
        AcquisitionResultV1,
        {
            "schema_version": 1,
            "status": "COMPLETE",
            "resource_handles": [item["resource_handle"] for item in resources],
            "source_summaries": [
                {
                    "route_id": "route-github",
                    "connector_id": "github",
                    "source": "GITHUB",
                    "status": "COMPLETE",
                    "resource_handles": [item["resource_handle"] for item in resources],
                    "resources": resources,
                }
            ],
            "missing_slots": [],
            "remaining_budget": {},
        },
    )


def _expected_github_segment_id(*, number: int, version: str, title: str) -> str:
    identity = {
        "schema_version": 1,
        "connector_id": "github",
        "source_kind": "github",
        "resource_type": "github_issue",
        "resource_id": f"acme/repo#{number}",
        "source_version_ref": version,
        "chunk_schema_version": 5,
        "chunk_ordinal": 0,
        "normalized_content_sha256": hashlib.sha256(f"title: {title}".encode()).hexdigest(),
    }
    canonical = json.dumps(identity, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return "seg_" + hashlib.sha256(canonical.encode()).hexdigest()


def test_github_issues__preserve_exact_identity__with_order_independent_segment_ids() -> None:
    first = normalize_segments(
        _github_result([(7, "v1", "Status seven"), (8, "v2", "Status eight")])
    )
    reordered = normalize_segments(
        _github_result([(8, "v2", "Status eight"), (7, "v1", "Status seven")])
    )

    first_ids = {segment.resource_id: segment.segment_id for segment in first}
    reordered_ids = {segment.resource_id: segment.segment_id for segment in reordered}

    assert {segment.source for segment in first} == {"GITHUB"}
    assert {segment.resource_type for segment in first} == {"github_issue"}
    assert set(first_ids) == {"acme/repo#7", "acme/repo#8"}
    assert first_ids == reordered_ids
    assert first_ids["acme/repo#7"] == _expected_github_segment_id(
        number=7, version="v1", title="Status seven"
    )


def test_github_issue_segment_id__with_version_or_content_change__changes() -> None:
    original = normalize_segments(_github_result([(7, "v1", "Status seven")]))[0].segment_id
    changed_version = normalize_segments(_github_result([(7, "v2", "Status seven")]))[0].segment_id
    changed_content = normalize_segments(_github_result([(7, "v1", "Updated status")]))[
        0
    ].segment_id

    assert len({original, changed_version, changed_content}) == 3


def test_google_source_families__with_same_input__retain_stable_normalization() -> None:
    for source, resource_type in (
        ("GMAIL", "gmail_message"),
        ("TASKS", "task"),
        ("CALENDAR", "calendar_event"),
    ):
        result = _result("same content")
        summary = result["source_summaries"][0]
        summary["source"] = source
        resource = cast(list[dict[str, object]], summary["resources"])[0]
        resource["resource_type"] = resource_type

        assert normalize_segments(result)[0].segment_id == normalize_segments(result)[0].segment_id


def test_mixed_sources__full_preferred_google_budget__still_retains_new_github() -> None:
    google = _result("one two three four five six seven eight nine ten")
    budget = ContextBudget(
        max_segments=2,
        chunk_target_tokens=3,
        chunk_max_tokens=4,
        chunk_overlap_tokens=0,
    )
    prior = normalize_segments(google, context_budget=budget)
    assert len(prior) == 2
    google["source_summaries"].extend(
        _github_result([(7, "v1", "Issue facts")])["source_summaries"]
    )
    mixed = normalize_segments(
        google,
        context_budget=budget,
        preferred_segment_ids=[item.segment_id for item in prior],
    )
    assert {segment.source for segment in mixed} == {"GMAIL", "GITHUB"}
    assert mixed[0].segment_id == prior[0].segment_id


def test_github_acquisition__google_connector_attribution__fails_closed() -> None:
    acquisition = _github_result([(7, "v1", "Issue facts")])
    resources = cast(list[dict[str, object]], acquisition["source_summaries"][0]["resources"])
    resources[0]["connector_id"] = "google_workspace"
    with pytest.raises(ValueError, match="does not match its source"):
        normalize_segments(acquisition)
