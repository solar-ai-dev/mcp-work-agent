"""Inactive Planning input projection of source-owned Task completion facts.

The caller must obtain snapshots through the existing same-Run Evidence store
projection. A bare snapshot mapping cannot prove its Run, and this helper does
not create that authority. It never parses excerpts or SourceStatus filters.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from copy import deepcopy

from google_work_agent.application.agents.retrieval.resolve_task_calendar_snapshot import (
    resolve_task_calendar_snapshot,
)
from google_work_agent.application.use_cases.resource.list_resources import _task_status_projection

CANDIDATE_ID = "task-completion-fact-v1"


def project_task_completion_facts(
    prompt_input: Mapping[str, object],
    *,
    source_snapshots: Mapping[str, Mapping[str, object]] | None,
) -> dict[str, object]:
    """Copy compose input and add only facts bound to its approved Task Evidence.

    One invalid or conflicting approved observation excludes that handle, not
    unrelated valid Tasks. Multiple chunks of the same version keep their own
    citation identity; identical repeated Evidence does not duplicate a fact.
    """
    if "task_completion_facts" in prompt_input:
        raise ValueError("completion facts must be derived afresh from bound snapshots")
    projected = deepcopy(dict(prompt_input))
    outline = prompt_input.get("answer_outline")
    evidence = prompt_input.get("evidence")
    refs = outline.get("evidence_refs") if isinstance(outline, Mapping) else None
    if (
        not isinstance(refs, Sequence)
        or isinstance(refs, (str, bytes))
        or not isinstance(evidence, Sequence)
        or isinstance(evidence, (str, bytes))
    ):
        return projected
    approved_refs = {ref for ref in refs if isinstance(ref, str) and ref}
    invalid_handles: set[str] = set()
    versions: dict[str, set[str]] = {}
    facts: list[dict[str, str]] = []
    seen: set[tuple[str, str, str]] = set()
    for item in evidence:
        if not isinstance(item, Mapping):
            continue
        ref = item.get("evidence_ref") or item.get("evidence_id") or item.get("id")
        handle = item.get("resource_handle") or item.get("resource_ref")
        if (
            not isinstance(ref, str)
            or ref not in approved_refs
            or not isinstance(handle, str)
            or not handle.startswith("task:")
        ):
            continue
        locator = item.get("locator")
        version = locator.get("source_version_ref") if isinstance(locator, Mapping) else None
        fields = resolve_task_calendar_snapshot(item, source_snapshots)
        status = fields.get("status") if fields is not None else None
        if (
            not isinstance(version, str)
            or not version
            or not isinstance(status, str)
            or status not in {"needsAction", "completed"}
        ):
            invalid_handles.add(handle)
            continue
        task_status = _task_status_projection(status)
        if task_status is None:
            invalid_handles.add(handle)
            continue
        versions.setdefault(handle, set()).add(version)
        key = (ref, handle, version)
        if key not in seen:
            seen.add(key)
            facts.append(
                {
                    "evidence_ref": ref,
                    "resource_handle": handle,
                    "source_version_ref": version,
                    "provider_status": status,
                    "task_status": task_status,
                }
            )
    invalid_handles.update(handle for handle, observed in versions.items() if len(observed) != 1)
    facts = [fact for fact in facts if fact["resource_handle"] not in invalid_handles]
    if facts:
        projected["task_completion_facts"] = facts
    return projected


__all__ = ["CANDIDATE_ID", "project_task_completion_facts"]
