"""Project a selected Calendar event schedule from typed evidence."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import NamedTuple

from google_work_agent.application.agents.planning.contracts.planning_semantics import (
    AnswerDraftCandidateV2,
    AnswerOutlineV1,
)
from google_work_agent.application.agents.retrieval.resolve_task_calendar_snapshot import (
    resolve_unique_task_calendar_snapshots,
)


class CalendarEventReadAnswerProjection(NamedTuple):
    outline: AnswerOutlineV1
    draft: AnswerDraftCandidateV2


def project_calendar_event_read_answer(
    *,
    user_request: str,
    request_intent: Mapping[str, object],
    evidence: Sequence[Mapping[str, object]],
    retrieval_result: Mapping[str, object] | None = None,
    source_snapshots: Mapping[str, Mapping[str, object]] | None = None,
) -> CalendarEventReadAnswerProjection | None:
    """Render one exact event's start and end without model regeneration."""
    if (
        request_intent.get("analysis_requirement") != "NONE"
        or set(_strings(request_intent.get("requested_effect_hints"))) != {"READ"}
        or set(_strings(request_intent.get("requested_resource_hints")))
        != {"CALENDAR_EVENT"}
        or not _supports_requested_information(request_intent)
    ):
        return None

    selected_ids = [
        item
        for constraint in _mappings(request_intent.get("constraints"))
        if constraint.get("kind") == "RESOURCE"
        and constraint.get("field") == "selected_resource_id"
        for item in _strings(constraint.get("value"))
    ]
    target_resource_ref: str | None = None
    allow_equivalent_duplicates = False
    if len(selected_ids) == 1:
        target_resource_ref = f"calendar_event:{selected_ids[0]}"
    elif not selected_ids:
        target_resource_ref = _confirmed_retrieval_resource_ref(
            request_intent=request_intent,
            retrieval_result=retrieval_result,
        )
        allow_equivalent_duplicates = target_resource_ref is not None
    if target_resource_ref is None:
        return None

    matching = [
        item
        for item in evidence
        if _resource_handle(item) == target_resource_ref
    ]
    if not matching:
        return None

    if len(matching) != 1 and not allow_equivalent_duplicates:
        return None

    observations = resolve_unique_task_calendar_snapshots(matching, source_snapshots)
    if observations is None or len(observations) != 1:
        return None
    fields = _event_fields(observations[0][1])
    if fields is None:
        return None
    evidence_refs: list[str] = []
    for item in matching:
        evidence_ref = _evidence_ref(item)
        if evidence_ref is None:
            return None
        if evidence_ref not in evidence_refs:
            evidence_refs.append(evidence_ref)
    title, start, end, timezone_name = fields
    korean = any("\uac00" <= character <= "\ud7a3" for character in user_request)
    answer = (
        _render_korean(title, start, end, timezone_name)
        if korean
        else _render_english(title, start, end, timezone_name)
    )
    section = "선택한 일정" if korean else "Selected event schedule"
    return CalendarEventReadAnswerProjection(
        outline={"sections": [section], "evidence_refs": evidence_refs},
        draft={"schema_version": 2, "answer": answer, "evidence_refs": evidence_refs},
    )


def _confirmed_retrieval_resource_ref(
    *,
    request_intent: Mapping[str, object],
    retrieval_result: Mapping[str, object] | None,
) -> str | None:
    if retrieval_result is None or retrieval_result.get("coverage") != "SUFFICIENT":
        return None
    has_confirmation_search_anchor = False
    for constraint in _mappings(request_intent.get("constraints")):
        provenance = constraint.get("provenance")
        if (
            constraint.get("kind") == "USER_REQUIREMENT"
            and constraint.get("field") == "search_terms"
            and isinstance(provenance, Mapping)
            and provenance.get("source") == "CONFIRMATION_RESPONSE"
        ):
            has_confirmation_search_anchor = True
            break
    required_information = {
        item
        for constraint in _mappings(request_intent.get("constraints"))
        if constraint.get("kind") == "USER_REQUIREMENT"
        and constraint.get("field") == "required_information"
        for item in _strings(constraint.get("value"))
    }
    if not has_confirmation_search_anchor or not {"start", "end"}.issubset(
        required_information
    ):
        return None
    source_resource_refs = _strings(retrieval_result.get("source_resource_refs"))
    if len(source_resource_refs) != 1 or not source_resource_refs[0].startswith(
        "calendar_event:"
    ):
        return None
    return source_resource_refs[0]


def _supports_requested_information(request_intent: Mapping[str, object]) -> bool:
    responsibilities = request_intent.get("resource_responsibilities")
    if not isinstance(responsibilities, Mapping):
        return False
    sources = _mappings(responsibilities.get("source_reads"))
    if not sources or any(source.get("resource_type") != "CALENDAR_EVENT" for source in sources):
        return False
    required_information = {
        item for source in sources for item in _strings(source.get("required_information"))
    }
    for constraint in _mappings(request_intent.get("constraints")):
        if (
            constraint.get("kind") == "USER_REQUIREMENT"
            and constraint.get("field") == "required_information"
        ):
            value = constraint.get("value")
            required_information.update([value] if isinstance(value, str) else _strings(value))
    return {"start", "end"}.issubset(required_information) and required_information.issubset(
        {"title", "start", "end", "timezone"}
    )


def _event_fields(
    fields: Mapping[str, str | None],
) -> tuple[str, datetime, datetime, str] | None:
    title = fields.get("title")
    timezone_name = fields.get("timezone")
    start_value, end_value = fields.get("start"), fields.get("end")
    if (
        not isinstance(title, str)
        or not title.strip()
        or not isinstance(timezone_name, str)
        or not timezone_name.strip()
        or not isinstance(start_value, str)
        or not isinstance(end_value, str)
    ):
        return None
    try:
        start = datetime.fromisoformat(start_value.replace("Z", "+00:00"))
        end = datetime.fromisoformat(end_value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if start.tzinfo is None or end.tzinfo is None or end <= start:
        return None
    return title.strip(), start, end, timezone_name.strip()


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
