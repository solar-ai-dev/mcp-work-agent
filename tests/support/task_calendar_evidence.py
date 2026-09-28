"""Bind explicit Provider fields to synthetic Evidence without parsing its text."""

from collections.abc import Mapping

from google_work_agent.application.agents.retrieval.normalize_segments import DEFAULT_CONTEXT_BUDGET
from google_work_agent.application.agents.retrieval.project_task_calendar_source_snapshots import (
    task_calendar_source_snapshot,
)


def bind_task_calendar_snapshots(
    evidence: list[dict[str, object]],
    fields_by_ref: Mapping[str, Mapping[str, object]],
) -> dict[str, dict[str, object]]:
    snapshots: dict[str, dict[str, object]] = {}
    for item in evidence:
        ref = item.get("evidence_id") or item.get("evidence_ref")
        handle = item.get("resource_handle")
        if not isinstance(ref, str) or ref not in fields_by_ref:
            continue
        assert isinstance(handle, str)
        observation = task_calendar_source_snapshot(
            {
                "resource_type": handle.split(":", 1)[0],
                "resource_handle": handle,
                "payload": fields_by_ref[ref],
            },
            max_snapshot_chars=DEFAULT_CONTEXT_BUDGET.max_segment_chars,
        )
        assert observation is not None
        item["locator"] = {"source_version_ref": observation["source_version_ref"]}
        snapshots[ref] = observation["snapshot"]
    return snapshots
