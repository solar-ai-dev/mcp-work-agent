"""Materialize a grounded Gmail Draft from typed Task and Calendar evidence."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime

from google_work_agent.application.agents.task_calendar_draft_source import (
    is_task_calendar_draft_source_target,
    project_draft_recipients,
    project_task_calendar_source_terms,
)


def materialize_task_calendar_draft_payload(
    *,
    route: Mapping[str, object],
    request_intent: Mapping[str, object] | None,
    evidence: Sequence[Mapping[str, object]],
) -> dict[str, object] | None:
    if (
        not isinstance(request_intent, Mapping)
        or route.get("resource_type") != "GMAIL_DRAFT"
        or route.get("effect") != "CREATE"
        or route.get("selected_tool_id") != "gmail_create_draft"
        or not is_task_calendar_draft_source_target(request_intent)
    ):
        return None
    ambiguity = request_intent.get("ambiguity")
    terms = project_task_calendar_source_terms(request_intent.get("constraints"))
    recipients = project_draft_recipients(request_intent)
    if (
        not isinstance(ambiguity, Mapping)
        or ambiguity.get("requires_confirmation") is not False
        or terms is None
        or not recipients
    ):
        return None
    tasks: list[dict[str, str]] = []
    events: list[dict[str, str]] = []
    for item in evidence:
        handle = item.get("resource_handle")
        if handle is None:
            continue
        if not isinstance(handle, str):
            return None
        excerpt = item.get("excerpt")
        if not isinstance(excerpt, str):
            return None
        facts = _fact_lines(excerpt)
        if handle.startswith("task:"):
            if not {"title", "status", "due"}.issubset(facts):
                return None
            tasks.append(facts)
        elif handle.startswith("calendar_event:"):
            if not {"title", "start", "end", "status"}.issubset(facts):
                return None
            events.append(facts)
        else:
            return None
    if not tasks or not events:
        return None
    project = terms["task_terms"][0]
    request_text = "\n".join(_original_request_texts(request_intent))
    korean = any("\uac00" <= character <= "\ud7a3" for character in request_text)
    body = (
        _korean_body(project=project, tasks=tasks, events=events)
        if korean
        else _english_body(project=project, tasks=tasks, events=events)
    )
    return {
        "to": recipients,
        "subject": (
            f"[{project} 준비 상황] 할 일 및 일정 안내"
            if korean
            else f"[{project} readiness] Tasks and schedule"
        ),
        "body": body,
    }


def _fact_lines(excerpt: str) -> dict[str, str]:
    result: dict[str, str] = {}
    current: str | None = None
    for raw_line in excerpt.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if ":" in line:
            key, value = line.split(":", 1)
            current = key.strip().casefold()
            if value.strip():
                result[current] = value.strip()
            continue
        if current is not None:
            result[current] = " ".join(filter(None, [result.get(current), line]))
    return result


def _original_request_texts(request_intent: Mapping[str, object]) -> list[str]:
    constraints = request_intent.get("constraints")
    if not isinstance(constraints, list):
        return []
    values: list[str] = []
    for item in constraints:
        if not isinstance(item, Mapping) or item.get("field") != "original_search_request":
            continue
        raw = item.get("value")
        candidates = raw if isinstance(raw, list) else [raw]
        values.extend(candidate for candidate in candidates if isinstance(candidate, str))
    return values


def _korean_body(
    *, project: str, tasks: Sequence[Mapping[str, str]], events: Sequence[Mapping[str, str]]
) -> str:
    lines = ["안녕하세요.", "", f"{project} 준비 상황을 공유드립니다.", "", "할 일"]
    for task in tasks:
        lines.extend(
            [
                f"- {task['title']}",
                f"  - 상태: {_status_label(task['status'], korean=True)} ({task['status']})",
                f"  - 기한: {_date_value(task['due'])}",
            ]
        )
        if task.get("notes"):
            lines.append(f"  - 메모: {task['notes']}")
    lines.extend(["", "일정"])
    for event in events:
        lines.extend(
            [
                f"- {event['title']}",
                f"  - 시작: {_datetime_value(event['start'])}",
                f"  - 종료: {_datetime_value(event['end'])}",
                f"  - 상태: {_status_label(event['status'], korean=True)} ({event['status']})",
            ]
        )
        for key, label in (("location", "장소"), ("description", "설명")):
            if event.get(key):
                lines.append(f"  - {label}: {event[key]}")
    lines.extend(["", "확인 부탁드립니다.", "감사합니다."])
    return "\n".join(lines)


def _english_body(
    *, project: str, tasks: Sequence[Mapping[str, str]], events: Sequence[Mapping[str, str]]
) -> str:
    lines = ["Hello,", "", f"Here is the {project} readiness update.", "", "Tasks"]
    for task in tasks:
        lines.extend(
            [
                f"- {task['title']}",
                f"  - Status: {_status_label(task['status'], korean=False)} ({task['status']})",
                f"  - Due: {_date_value(task['due'])}",
            ]
        )
        if task.get("notes"):
            lines.append(f"  - Notes: {task['notes']}")
    lines.extend(["", "Schedule"])
    for event in events:
        lines.extend(
            [
                f"- {event['title']}",
                f"  - Start: {_datetime_value(event['start'])}",
                f"  - End: {_datetime_value(event['end'])}",
                f"  - Status: {_status_label(event['status'], korean=False)} ({event['status']})",
            ]
        )
        for key, label in (("location", "Location"), ("description", "Description")):
            if event.get(key):
                lines.append(f"  - {label}: {event[key]}")
    lines.extend(["", "Please review these details."])
    return "\n".join(lines)


def _date_value(value: str) -> str:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).date().isoformat()
    except ValueError:
        return value


def _datetime_value(value: str) -> str:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return value
    return parsed.isoformat(timespec="minutes")


def _status_label(value: str, *, korean: bool) -> str:
    labels = {
        "needsaction": ("진행 중", "In progress"),
        "completed": ("완료", "Completed"),
        "confirmed": ("확정", "Confirmed"),
        "tentative": ("미확정", "Tentative"),
        "cancelled": ("취소", "Cancelled"),
    }
    pair = labels.get(value.casefold())
    return value if pair is None else pair[0 if korean else 1]


__all__ = ["materialize_task_calendar_draft_payload"]
