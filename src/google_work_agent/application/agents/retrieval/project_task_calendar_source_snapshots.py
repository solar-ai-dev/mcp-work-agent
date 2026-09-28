"""Keep bounded Provider fields separate from untrusted Task/Event excerpt text."""

from __future__ import annotations

from collections.abc import Mapping
from typing import TypedDict, cast

from google_work_agent.application.agents.retrieval.contracts.retrieval_result import (
    AcquisitionResultV1,
)
from google_work_agent.application.use_cases.resource.strip_resource_recovery_marker import (
    strip_resource_recovery_marker,
)
from google_work_agent.domain.canonical import calculate_canonical_json_hash

_FIELDS = {
    "task": ("title", "status", "due", "notes"),
    "calendar_event": (
        "title",
        "start",
        "end",
        "timezone",
        "status",
        "location",
        "description",
    ),
}
_BINDING_FIELDS = frozenset(
    {"schema_version", "resource_type", "resource_handle", "parent_id", "provider_version"}
)


class TaskCalendarSourceSnapshotV1(TypedDict):
    resource_handle: str
    source_version_ref: str
    snapshot: dict[str, object]


def task_calendar_source_snapshot(
    resource: Mapping[str, object], *, max_snapshot_chars: int
) -> TaskCalendarSourceSnapshotV1 | None:
    resource_type = resource.get("resource_type")
    if not isinstance(resource_type, str) or resource_type not in _FIELDS:
        return None
    handle, payload = resource.get("resource_handle"), resource.get("payload")
    if (
        not isinstance(handle, str)
        or not handle.startswith(f"{resource_type}:")
        or not isinstance(payload, Mapping)
        or any(
            resource.get(key) is not None and not isinstance(resource.get(key), str)
            for key in ("parent_id", "version")
        )
    ):
        return None
    fields = {name: payload[name] for name in _FIELDS[resource_type] if name in payload}
    if resource_type == "task" and isinstance(fields.get("notes"), str):
        fields["notes"] = strip_resource_recovery_marker(cast(str, fields["notes"]))
    if (
        not fields
        or any(value is not None and not isinstance(value, str) for value in fields.values())
        or sum(len(value) for value in fields.values() if isinstance(value, str))
        > max_snapshot_chars
    ):
        return None
    snapshot: dict[str, object] = {
        "schema_version": 1,
        "resource_type": resource_type,
        "resource_handle": handle,
        "parent_id": resource.get("parent_id"),
        "provider_version": resource.get("version"),
        **fields,
    }
    return {
        "resource_handle": handle,
        "source_version_ref": f"sha256:{calculate_canonical_json_hash(snapshot)}",
        "snapshot": snapshot,
    }


def project_task_calendar_source_snapshots(
    acquisition_result: AcquisitionResultV1, *, max_snapshot_chars: int
) -> list[TaskCalendarSourceSnapshotV1]:
    observations: dict[tuple[str, str], TaskCalendarSourceSnapshotV1] = {}
    for summary in acquisition_result["source_summaries"]:
        resources = summary.get("resources", [])
        if not isinstance(resources, list):
            continue
        for raw in resources:
            if not isinstance(raw, Mapping):
                continue
            observation = task_calendar_source_snapshot(raw, max_snapshot_chars=max_snapshot_chars)
            if observation is not None:
                observations[
                    (observation["resource_handle"], observation["source_version_ref"])
                ] = observation
    return list(observations.values())


def task_calendar_snapshot_fields(
    snapshot: Mapping[str, object], *, resource_handle: str, source_version_ref: str
) -> dict[str, str | None] | None:
    """Reject a stale/misbound snapshot; never recover fields by parsing its excerpt."""
    resource_type = snapshot.get("resource_type")
    if (
        snapshot.get("schema_version") != 1
        or not isinstance(resource_type, str)
        or resource_type not in _FIELDS
        or not resource_handle.startswith(f"{resource_type}:")
        or snapshot.get("resource_handle") != resource_handle
        or not _BINDING_FIELDS.issubset(snapshot)
        or set(snapshot) - _BINDING_FIELDS - set(_FIELDS[resource_type])
        or any(
            value is not None and not isinstance(value, str)
            for key, value in snapshot.items()
            if key != "schema_version"
        )
    ):
        return None
    if source_version_ref != f"sha256:{calculate_canonical_json_hash(dict(snapshot))}":
        return None
    return {
        key: cast(str | None, snapshot[key]) for key in _FIELDS[resource_type] if key in snapshot
    }


__all__ = [
    "TaskCalendarSourceSnapshotV1",
    "project_task_calendar_source_snapshots",
    "task_calendar_snapshot_fields",
    "task_calendar_source_snapshot",
]
