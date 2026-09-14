"""Project exact Gmail Draft source snapshots outside evidence locators."""

from __future__ import annotations

from collections.abc import Mapping
from typing import TypedDict

from google_work_agent.application.agents.retrieval.contracts.retrieval_result import (
    AcquisitionResultV1,
)
from google_work_agent.domain.canonical import calculate_canonical_json_hash

_DRAFT_FIELDS = (
    "to",
    "cc",
    "bcc",
    "subject",
    "body",
    "thread_id",
    "in_reply_to",
    "references",
    "attachments",
)


class GmailDraftSourceSnapshotV1(TypedDict):
    resource_handle: str
    source_version_ref: str
    snapshot: dict[str, object]


def project_gmail_draft_source_snapshots(
    acquisition_result: AcquisitionResultV1,
) -> list[GmailDraftSourceSnapshotV1]:
    """Return exact, version-bound Draft observations from one acquisition."""

    projected: dict[tuple[str, str], GmailDraftSourceSnapshotV1] = {}
    for summary in acquisition_result["source_summaries"]:
        resources = summary.get("resources", [])
        if not isinstance(resources, list):
            continue
        for raw in resources:
            if not isinstance(raw, Mapping) or raw.get("resource_type") != "gmail_draft":
                continue
            handle = raw.get("resource_handle")
            payload = raw.get("payload")
            if not isinstance(handle, str) or not handle or not isinstance(payload, Mapping):
                raise ValueError("Gmail Draft acquisition snapshot is incomplete")
            missing_fields = set(_DRAFT_FIELDS) - set(payload)
            if missing_fields:
                raise ValueError("Gmail Draft acquisition snapshot is incomplete")
            snapshot = {name: payload[name] for name in _DRAFT_FIELDS}
            source_version_ref = gmail_draft_source_version_ref(raw, snapshot=snapshot)
            key = (handle, source_version_ref)
            candidate: GmailDraftSourceSnapshotV1 = {
                "resource_handle": handle,
                "source_version_ref": source_version_ref,
                "snapshot": snapshot,
            }
            existing = projected.get(key)
            if existing is not None and existing != candidate:
                raise ValueError("Gmail Draft acquisition snapshots disagree")
            projected[key] = candidate
    return list(projected.values())


def gmail_draft_source_version_ref(
    resource: Mapping[str, object],
    *,
    snapshot: Mapping[str, object] | None = None,
) -> str:
    version = resource.get("version")
    if isinstance(version, str) and version:
        return version
    payload = resource.get("payload")
    source = snapshot if snapshot is not None else payload
    if not isinstance(source, Mapping):
        raise ValueError("Gmail Draft source version requires a snapshot")
    missing_fields = set(_DRAFT_FIELDS) - set(source)
    if missing_fields:
        raise ValueError("Gmail Draft source version requires a complete snapshot")
    exact = {name: source[name] for name in _DRAFT_FIELDS}
    return f"sha256:{calculate_canonical_json_hash(exact)}"


__all__ = [
    "GmailDraftSourceSnapshotV1",
    "gmail_draft_source_version_ref",
    "project_gmail_draft_source_snapshots",
]
