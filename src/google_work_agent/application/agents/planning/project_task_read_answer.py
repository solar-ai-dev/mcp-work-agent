"""Project simple Google Tasks reads directly from selected evidence."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date
from typing import NamedTuple

from google_work_agent.application.agents.planning.contracts.planning_semantics import (
    AnswerDraftCandidateV2,
    AnswerOutlineV1,
)


class TaskReadAnswerProjection(NamedTuple):
    outline: AnswerOutlineV1
    draft: AnswerDraftCandidateV2


def project_task_read_answer(
    *,
    user_request: str,
    request_intent: Mapping[str, object],
    evidence: Sequence[Mapping[str, object]],
) -> TaskReadAnswerProjection | None:
    """Return one grounded projection only for non-analytical Tasks READs."""
    if (
        request_intent.get("analysis_requirement") != "NONE"
        or set(_strings(request_intent.get("requested_effect_hints"))) != {"READ"}
        or set(_strings(request_intent.get("requested_resource_hints"))) != {"TASK"}
    ):
        return None

    task_items = [item for item in evidence if _resource_handle(item).startswith("task:")]
    citation_items = task_items or [
        item for item in evidence if _resource_handle(item).startswith("task_list:")
    ]
    evidence_refs = [ref for item in citation_items if (ref := _evidence_ref(item)) is not None]
    korean = any("\uac00" <= character <= "\ud7a3" for character in user_request)
    requested_fields = _requested_task_fields(request_intent)
    if task_items:
        lead = (
            f"Google Tasks에서 확인된 현재 할 일은 {len(task_items)}개입니다."
            if korean
            else f"I found {len(task_items)} current item(s) in Google Tasks."
        )
        unavailable_title = (
            "제목을 표시할 수 없는 할 일"
            if korean
            else "Task title unavailable"
        )
        answer = f"{lead}\n\n" + "\n".join(
            _task_line(
                item,
                requested_fields=requested_fields,
                unavailable_title=unavailable_title,
                korean=korean,
            )
            for item in task_items
        )
        section = "현재 Google Tasks 할 일" if korean else "Current Google Tasks items"
    else:
        answer = (
            "Google Tasks에서 현재 표시할 할 일을 찾지 못했습니다."
            if korean
            else "I could not find any current items in Google Tasks."
        )
        section = "검색 결과 없음" if korean else "No current tasks found"
    unique_refs = list(dict.fromkeys(evidence_refs))
    return TaskReadAnswerProjection(
        outline={"sections": [section], "evidence_refs": unique_refs},
        draft={"schema_version": 2, "answer": answer, "evidence_refs": unique_refs},
    )


def _strings(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str)]


def _resource_handle(item: Mapping[str, object]) -> str:
    value = item.get("resource_handle") or item.get("resource_ref")
    return value if isinstance(value, str) else ""


def _evidence_ref(item: Mapping[str, object]) -> str | None:
    value = item.get("evidence_ref") or item.get("evidence_id") or item.get("id")
    return value if isinstance(value, str) and value else None


def _requested_task_fields(request_intent: Mapping[str, object]) -> frozenset[str]:
    responsibilities = request_intent.get("resource_responsibilities")
    if not isinstance(responsibilities, Mapping):
        return frozenset({"title"})
    source_reads = responsibilities.get("source_reads")
    if not isinstance(source_reads, list):
        return frozenset({"title"})
    required_information = {
        information
        for source in source_reads
        if isinstance(source, Mapping) and source.get("resource_type") == "TASK"
        for information in _strings(source.get("required_information"))
    }
    fields = {"title"}
    if required_information.intersection({"completion_status", "status", "task_status"}):
        fields.add("status")
    if required_information.intersection({"due", "scheduled_date"}):
        fields.add("scheduled_date")
    return frozenset(fields)


def _task_line(
    item: Mapping[str, object],
    *,
    requested_fields: frozenset[str],
    unavailable_title: str,
    korean: bool,
) -> str:
    fields = _task_fields(item)
    title = fields.get("title") or unavailable_title
    details: list[str] = []
    if "status" in requested_fields:
        status = _task_status(fields.get("status"), korean=korean)
        details.append(
            f"상태: {status or '확인할 수 없음'}"
            if korean
            else f"Status: {status or 'unavailable'}"
        )
    if "scheduled_date" in requested_fields:
        scheduled_date = _scheduled_date(fields.get("due"))
        details.append(
            f"예정일: {scheduled_date or '확인할 수 없음'}"
            if korean
            else f"Scheduled date: {scheduled_date or 'unavailable'}"
        )
    return f"- {title}" if not details else f"- {title} — {'; '.join(details)}"


def _task_status(value: str | None, *, korean: bool) -> str | None:
    return {
        "needsAction": "미완료" if korean else "incomplete",
        "completed": "완료" if korean else "completed",
    }.get(value or "")


def _scheduled_date(value: str | None) -> str | None:
    if value is None or len(value) < 10:
        return None
    candidate = value[:10]
    try:
        return date.fromisoformat(candidate).isoformat()
    except ValueError:
        return None


def _task_fields(item: Mapping[str, object]) -> dict[str, str]:
    excerpt = item.get("excerpt")
    if not isinstance(excerpt, str):
        return {}
    lines = [line.strip() for line in excerpt.splitlines() if line.strip()]
    metadata_keys = {
        "completed",
        "due",
        "notes",
        "position",
        "status",
        "task_id",
        "task_list_id",
        "title",
        "updated",
    }
    structured_fields: dict[str, str] = {
        key.strip(): value.strip()
        for line in lines
        for key, separator, value in (line.partition(":"),)
        if separator and key.strip() in metadata_keys
    }
    if structured_fields:
        return structured_fields
    return {"title": lines[0]} if lines else {}


__all__ = ["TaskReadAnswerProjection", "project_task_read_answer"]
