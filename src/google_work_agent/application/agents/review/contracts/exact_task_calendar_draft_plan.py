"""Recognize a fully grounded Task + Calendar Gmail Draft preview."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from google_work_agent.application.agents.planning.materialize_task_calendar_draft_payload import (
    materialize_task_calendar_draft_payload,
)
from google_work_agent.application.agents.task_calendar_draft_source import (
    is_task_calendar_draft_source_target,
)


def is_exact_task_calendar_draft_plan(
    *,
    request_intent: Mapping[str, object],
    planning_result: Mapping[str, object],
    evidence: Sequence[Mapping[str, object]],
    source_snapshots: Mapping[str, Mapping[str, object]] | None = None,
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
    connector_evidence = [item for item in evidence if isinstance(item.get("resource_handle"), str)]
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
    for item in connector_evidence:
        evidence_id = item.get("evidence_id")
        if not isinstance(evidence_id, str) or evidence_id not in action_refs:
            return False
    # Word presence cannot prove that a status belongs to the right Resource:
    # the same token can occur in a title or quoted note. Only the complete
    # source-bound deterministic Preview is eligible; other wording is reviewed.
    expected = materialize_task_calendar_draft_payload(
        route={
            "resource_type": "GMAIL_DRAFT",
            "effect": "CREATE",
            "selected_tool_id": "gmail_create_draft",
        },
        request_intent=request_intent,
        evidence=evidence,
        source_snapshots=source_snapshots,
    )
    return expected is not None and dict(payload) == expected


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


__all__ = ["is_exact_task_calendar_draft_plan"]
