"""Project exact Gmail Draft source snapshots outside evidence locators."""

from __future__ import annotations

from collections.abc import Mapping

from google_work_agent.application.agents.retrieval.contracts.retrieval_result import (
    AcquisitionResultV1,
)

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


def project_gmail_draft_source_snapshots(
    acquisition_result: AcquisitionResultV1,
) -> dict[str, dict[str, object]]:
    """Return exact provider fields keyed by the acquisition resource handle."""

    projected: dict[str, dict[str, object]] = {}
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
            snapshot = {name: payload[name] for name in _DRAFT_FIELDS if name in payload}
            existing = projected.get(handle)
            if existing is not None and existing != snapshot:
                raise ValueError("Gmail Draft acquisition snapshots disagree")
            projected[handle] = snapshot
    return projected


__all__ = ["project_gmail_draft_source_snapshots"]
