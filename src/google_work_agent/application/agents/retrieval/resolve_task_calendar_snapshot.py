"""Resolve source-owned Task/Event snapshots for deterministic downstream consumers."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from google_work_agent.application.agents.retrieval.project_task_calendar_source_snapshots import (
    task_calendar_snapshot_fields,
)


def resolve_task_calendar_snapshot(
    evidence: Mapping[str, object],
    source_snapshots: Mapping[str, Mapping[str, object]] | None,
) -> dict[str, str | None] | None:
    ref = evidence.get("evidence_ref") or evidence.get("evidence_id") or evidence.get("id")
    handle = evidence.get("resource_handle") or evidence.get("resource_ref")
    locator = evidence.get("locator")
    version = locator.get("source_version_ref") if isinstance(locator, Mapping) else None
    snapshot = source_snapshots.get(ref) if source_snapshots and isinstance(ref, str) else None
    if (
        not isinstance(snapshot, Mapping)
        or not isinstance(handle, str)
        or not isinstance(version, str)
        or not version
    ):
        return None
    return task_calendar_snapshot_fields(
        snapshot, resource_handle=handle, source_version_ref=version
    )


def resolve_unique_task_calendar_snapshots(
    evidence: Sequence[Mapping[str, object]],
    source_snapshots: Mapping[str, Mapping[str, object]] | None,
) -> list[tuple[str, dict[str, str | None]]] | None:
    """One observed Resource is not multiple tasks merely because it has multiple chunks."""
    versions: dict[str, str] = {}
    result: list[tuple[str, dict[str, str | None]]] = []
    for item in evidence:
        fields = resolve_task_calendar_snapshot(item, source_snapshots)
        handle = item.get("resource_handle") or item.get("resource_ref")
        locator = item.get("locator")
        version = locator.get("source_version_ref") if isinstance(locator, Mapping) else None
        if fields is None or not isinstance(handle, str) or not isinstance(version, str):
            return None
        if handle in versions:
            if versions[handle] != version:
                return None
            continue
        versions[handle] = version
        result.append((handle, fields))
    return result
