"""Project a selected Calendar event schedule from typed evidence."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import NamedTuple

from google_work_agent.application.agents.planning.contracts.planning_semantics import (
    AnswerDraftCandidateV2,
    AnswerOutlineV1,
)


class CalendarEventReadAnswerProjection(NamedTuple):
    outline: AnswerOutlineV1
    draft: AnswerDraftCandidateV2


def project_calendar_event_read_answer(
    *,
    user_request: str,
    request_intent: Mapping[str, object],
    evidence: Sequence[Mapping[str, object]],
) -> CalendarEventReadAnswerProjection | None:
    """Render one selected event's exact start and end without model regeneration."""
    if (
        request_intent.get("analysis_requirement") != "NONE"
        or set(_strings(request_intent.get("requested_effect_hints"))) != {"READ"}
        or set(_strings(request_intent.get("requested_resource_hints")))
        != {"CALENDAR_EVENT"}
        or not _asks_for_schedule(user_request)
    ):
        return None

    selected_ids = [
        item
        for constraint in _mappings(request_intent.get("constraints"))
        if constraint.get("kind") == "RESOURCE"
        and constraint.get("field") == "selected_resource_id"
        for item in _strings(constraint.get("value"))
    ]
    if len(selected_ids) != 1:
        return None

    matching = [
        item
        for item in evidence
        if (handle := _resource_handle(item)).startswith("calendar_event:")
        and handle.partition(":")[2] == selected_ids[0]
    ]
    if len(matching) != 1:
        return None

    fields = _event_fields(matching[0])
    evidence_ref = _evidence_ref(matching[0])
    if fields is None or evidence_ref is None:
        return None
    title, start, end, timezone_name = fields
    korean = any("\uac00" <= character <= "\ud7a3" for character in user_request)
    answer = (
        _render_korean(title, start, end, timezone_name)
        if korean
        else _render_english(title, start, end, timezone_name)
    )
    section = "선택한 일정" if korean else "Selected event schedule"
    return CalendarEventReadAnswerProjection(
        outline={"sections": [section], "evidence_refs": [evidence_ref]},
        draft={"schema_version": 2, "answer": answer, "evidence_refs": [evidence_ref]},
    )


def _asks_for_schedule(user_request: str) -> bool:
    normalized = user_request.casefold()
    if any(token in normalized for token in ("언제", "몇 시", "시간", "날짜")):
        return True
    return re.search(r"\b(when|what time|date|schedule)\b", normalized) is not None


def _event_fields(
    item: Mapping[str, object],
) -> tuple[str, datetime, datetime, str] | None:
    excerpt = item.get("excerpt")
    if not isinstance(excerpt, str):
        return None
    fields = {
        key.strip(): value.strip()
        for line in excerpt.splitlines()
        for key, separator, value in (line.partition(":"),)
        if separator and key.strip() in {"title", "start", "end", "timezone"}
    }
    title = fields.get("title", "").strip()
    timezone_name = fields.get("timezone", "").strip()
    if not title or not timezone_name:
        return None
    try:
        start = datetime.fromisoformat(fields["start"].replace("Z", "+00:00"))
        end = datetime.fromisoformat(fields["end"].replace("Z", "+00:00"))
    except (KeyError, ValueError):
        return None
    if start.tzinfo is None or end.tzinfo is None or end <= start:
        return None
    return title, start, end, timezone_name


def _render_korean(title: str, start: datetime, end: datetime, timezone_name: str) -> str:
    date = f"{start.year}년 {start.month}월 {start.day}일"
    start_value = _korean_time(start)
    end_value = _korean_time(end)
    if start.date() == end.date():
        interval = f"{date} {start_value}부터 {end_value}까지"
    else:
        end_date = f"{end.year}년 {end.month}월 {end.day}일"
        interval = f"{date} {start_value}부터 {end_date} {end_value}까지"
    return f"{title} 일정은 {interval}입니다. ({timezone_name})"


def _korean_time(value: datetime) -> str:
    period = "오전" if value.hour < 12 else "오후"
    hour = value.hour % 12 or 12
    minute = "" if value.minute == 0 else f" {value.minute}분"
    return f"{period} {hour}시{minute}"


def _render_english(title: str, start: datetime, end: datetime, timezone_name: str) -> str:
    months = (
        "January", "February", "March", "April", "May", "June",
        "July", "August", "September", "October", "November", "December",
    )
    date = f"{months[start.month - 1]} {start.day}, {start.year}"
    start_value = start.strftime("%I:%M %p").lstrip("0")
    end_value = end.strftime("%I:%M %p").lstrip("0")
    if start.date() == end.date():
        interval = f"{date}, from {start_value} to {end_value}"
    else:
        end_date = f"{months[end.month - 1]} {end.day}, {end.year}"
        interval = f"{date}, {start_value} to {end_date}, {end_value}"
    return f"The {title} event is scheduled for {interval} ({timezone_name})."


def _mappings(value: object) -> list[Mapping[str, object]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, Mapping)]


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


__all__ = ["CalendarEventReadAnswerProjection", "project_calendar_event_read_answer"]
