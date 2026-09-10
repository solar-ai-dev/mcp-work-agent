"""Project bounded Task observations for Work Analysis duplicate review."""

from __future__ import annotations

from collections.abc import Mapping
from typing import cast

from google_work_agent.application.agents.retrieval.contracts.retrieval_result import (
    AcquisitionResultV1,
    TaskReviewCandidateV1,
)
from google_work_agent.application.use_cases.resource.strip_resource_recovery_marker import (
    strip_resource_recovery_marker,
)
from google_work_agent.ports.connector.contracts.resource_snapshot import ResourceType

_MAX_REVIEW_NOTES_CHARS = 1200


def project_task_review_candidates(
    acquisition_result: AcquisitionResultV1,
) -> list[TaskReviewCandidateV1]:
    """Keep one bounded observation per returned Task, including malformed candidates."""

    candidates: dict[str, TaskReviewCandidateV1] = {}
    for summary in acquisition_result["source_summaries"]:
        route_id = summary.get("route_id")
        resources = summary.get("resources")
        if not isinstance(route_id, str) or not isinstance(resources, list):
            continue
        for resource in resources:
            if not isinstance(resource, Mapping) or resource.get("resource_type") != (
                ResourceType.TASK.value
            ):
                continue
            handle = resource.get("resource_handle")
            resource_id = resource.get("resource_id")
            if not isinstance(handle, str) or not handle or not isinstance(resource_id, str):
                continue
            payload = resource.get("payload")
            values = payload if isinstance(payload, Mapping) else {}
            parent_id = resource.get("parent_id")
            notes, notes_truncated = _bounded_notes(values.get("notes"))
            candidate = TaskReviewCandidateV1(
                candidate_ref=handle,
                route_id=route_id,
                resource_id=resource_id,
                task_list_id=parent_id if isinstance(parent_id, str) else None,
                title=_optional_text(values.get("title")),
                status=_optional_text(values.get("status")),
                due=_optional_text(values.get("due")),
                notes=notes,
                notes_truncated=notes_truncated,
                source_version_ref=_optional_text(resource.get("version")),
            )
            prior = candidates.get(handle)
            if prior is not None and prior != candidate:
                raise ValueError("Task review candidate identity has conflicting observations")
            candidates[handle] = candidate
    return list(candidates.values())


def _optional_text(value: object) -> str | None:
    return cast(str, value) if isinstance(value, str) else None


def _bounded_notes(value: object) -> tuple[str | None, bool]:
    if not isinstance(value, str):
        return None, False
    visible = strip_resource_recovery_marker(value)
    if visible is None:
        return None, False
    normalized = visible.strip()
    if not normalized:
        return None, False
    return normalized[:_MAX_REVIEW_NOTES_CHARS], len(normalized) > _MAX_REVIEW_NOTES_CHARS


__all__ = ["project_task_review_candidates"]
