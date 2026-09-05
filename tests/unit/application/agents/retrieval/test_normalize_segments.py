import hashlib
import json
from typing import cast

from google_work_agent.application.agents.retrieval.contracts.retrieval_result import (
    AcquisitionResultV1,
)
from google_work_agent.application.agents.retrieval.normalize_segments import normalize_segments


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
        "chunk_schema_version": 1,
        "chunk_ordinal": 0,
        "normalized_content_sha256": hashlib.sha256(title.encode()).hexdigest(),
    }
    canonical = json.dumps(identity, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return "seg_" + hashlib.sha256(canonical.encode()).hexdigest()


def test_segment_id__is_stable__and_content_sensitive() -> None:
    first = normalize_segments(_result("same content"))[0].segment_id
    repeated = normalize_segments(_result("same content"))[0].segment_id
    changed = normalize_segments(_result("changed content"))[0].segment_id

    assert first == repeated
    assert first.startswith("seg_") and len(first) == 68
    assert changed != first


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
