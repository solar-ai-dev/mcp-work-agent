"""Recognize a fully grounded Task + Calendar Gmail Draft preview."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence

from google_work_agent.application.agents.task_calendar_draft_source import (
    is_task_calendar_draft_source_target,
)

_TEMPORAL_LINE = re.compile(
    r"^(?P<field>due|start|end):\s*(?P<date>\d{4}-\d{2}-\d{2})"
    r"(?:T(?P<time>\d{2}:\d{2}))?",
    re.IGNORECASE,
)


def is_exact_task_calendar_draft_plan(
    *,
    request_intent: Mapping[str, object],
    planning_result: Mapping[str, object],
    evidence: Sequence[Mapping[str, object]],
) -> bool:
    """Return true only when the Preview carries every selected source fact."""

    ambiguity = request_intent.get("ambiguity")
    if (
        not is_task_calendar_draft_source_target(request_intent)
        or not isinstance(ambiguity, Mapping)
        or ambiguity.get("requires_confirmation") is not False
    ):
        return False
    recipients = _requested_recipients(request_intent.get("constraints"))
    if not recipients:
        return False
    actions = planning_result.get("actions")
    if not isinstance(actions, list) or len(actions) != 1 or not isinstance(actions[0], Mapping):
        return False
    action = actions[0]
    arguments = action.get("arguments")
    if (
        action.get("tool_id") != "gmail_create_draft"
        or action.get("effect") != "CREATE"
        or not isinstance(arguments, Mapping)
        or set(arguments) != {"payload"}
    ):
        return False
    payload = arguments.get("payload")
    if not isinstance(payload, Mapping):
        return False
    to = payload.get("to")
    subject = payload.get("subject")
    body = payload.get("body")
    if (
        not isinstance(to, list)
        or {item.casefold() for item in to if isinstance(item, str)} != recipients
        or len(to) != len(recipients)
        or not isinstance(subject, str)
        or not subject.strip()
        or not isinstance(body, str)
        or not body.strip()
    ):
        return False
    action_refs = action.get("evidence_refs")
    if not isinstance(action_refs, list):
        return False
    connector_evidence = [
        item
        for item in evidence
        if isinstance(item.get("resource_handle"), str)
    ]
    resource_types = {
        "TASK"
        if str(item["resource_handle"]).startswith("task:")
        else "CALENDAR_EVENT"
        if str(item["resource_handle"]).startswith("calendar_event:")
        else "OTHER"
        for item in connector_evidence
    }
    if resource_types != {"TASK", "CALENDAR_EVENT"}:
        return False
    body_text = body.casefold()
    for item in connector_evidence:
        evidence_id = item.get("evidence_id")
        excerpt = item.get("excerpt")
        if (
            not isinstance(evidence_id, str)
            or evidence_id not in action_refs
            or not isinstance(excerpt, str)
            or not _contains_source_facts(body_text, excerpt)
        ):
            return False
    return True


def _requested_recipients(value: object) -> set[str]:
    if not isinstance(value, list):
        return set()
    recipients: set[str] = set()
    for item in value:
        if (
            not isinstance(item, Mapping)
            or item.get("kind") != "PERSON"
            or item.get("field") != "recipient"
        ):
            continue
        raw = item.get("value")
        values = raw if isinstance(raw, list) else [raw]
        for candidate in values:
            if isinstance(candidate, str) and "@" in candidate:
                recipients.add(candidate.casefold())
    return recipients


def _contains_source_facts(body: str, excerpt: str) -> bool:
    lines = [line.strip() for line in excerpt.splitlines() if line.strip()]
    title = next(
        (line.split(":", 1)[1].strip() for line in lines if line.casefold().startswith("title:")),
        None,
    )
    normalized_body = _normalize_fact_text(body)
    if not title or not _contains_fact_words(normalized_body, title):
        return False
    status = next(
        (
            line.split(":", 1)[1].strip()
            for line in lines
            if line.casefold().startswith("status:")
        ),
        None,
    )
    if not status or status.casefold() not in body:
        return False
    for line in lines:
        match = _TEMPORAL_LINE.match(line)
        if match is None:
            continue
        if match.group("date") not in body:
            return False
        time_value = match.group("time")
        if match.group("field").casefold() in {"start", "end"} and time_value not in body:
            return False
    notes_index = next(
        (index for index, line in enumerate(lines) if line.casefold() == "notes:"),
        None,
    )
    return not (
        notes_index is not None
        and notes_index + 1 < len(lines)
        and not _contains_fact_words(normalized_body, lines[notes_index + 1])
    )


def _normalize_fact_text(value: str) -> str:
    return "".join(character.casefold() for character in value if character.isalnum())


def _contains_fact_words(normalized_body: str, value: str) -> bool:
    words = re.findall(r"[\w]+", value.casefold(), re.UNICODE)
    return bool(words) and all(_normalize_fact_text(word) in normalized_body for word in words)


__all__ = ["is_exact_task_calendar_draft_plan"]
