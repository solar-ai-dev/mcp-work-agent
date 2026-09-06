"""Verification-owner-local Expected projections for write verification.

Planning owns approved business arguments, not a fabricated provider snapshot.
This module converts those approved arguments into the bounded fields that a
post-write verification read can actually compare. Provider-generated ids,
versions, etags and timestamps are deliberately absent.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from email.utils import getaddresses
from typing import cast

from google_work_agent.application.use_cases.resource.strip_resource_recovery_marker import (
    strip_resource_recovery_marker,
)


def build_expected_verification_projection(
    *,
    tool_name: str,
    arguments: Mapping[str, object],
) -> dict[str, object]:
    """Build the deterministic expected subset for one approved write.

    Only fields exposed by the current verification READ projection belong in
    Expected.  A business argument that the Connector verification snapshot
    cannot currently observe must not be fabricated into Expected, otherwise a
    correct write would be forced into MISMATCH for a field Actual can never
    contain.
    """

    args = dict(arguments)
    if tool_name in {"github_create_issue", "github_update_issue"}:
        return {key: args[key] for key in ("title", "body") if key in args}
    if tool_name in {"github_close_issue", "github_reopen_issue"}:
        return {"state": "CLOSED" if tool_name == "github_close_issue" else "OPEN"}
    if tool_name in {"calendar_delete_event", "tasks_delete_task"}:
        # DELETE verification owns its explicit absent projection in
        # VerifyWriteActionService; no provider-generated Expected is needed.
        return {"absent": True}
    if tool_name in {"gmail_create_draft", "gmail_update_draft", "gmail_send"}:
        payload = _mapping(args.get("payload"), "payload")
        expected_payload: dict[str, object] = {
            "to": _string_list(payload.get("to"), "payload.to"),
            "cc": _string_list(payload.get("cc", []), "payload.cc"),
            "bcc": _string_list(payload.get("bcc", []), "payload.bcc"),
            "subject": _required_string(payload, "subject"),
            "body": _required_string(payload, "body"),
            "in_reply_to": payload.get("in_reply_to"),
            "references": payload.get("references"),
            "attachments": payload.get("attachments", []),
        }
        if payload.get("thread_id") is not None:
            expected_payload["thread_id"] = payload["thread_id"]
        if tool_name == "gmail_send":
            expected_payload["sent"] = True
        return {"payload": expected_payload}
    if tool_name in {"tasks_create_task", "tasks_update_task"}:
        payload = _mapping(args.get("payload"), "payload")
        task_expected_payload: dict[str, object] = {
            "parent_id": _required_string(args, "task_list_id"),
        }
        if tool_name == "tasks_create_task":
            task_expected_payload.update({"notes": "", "due": None, "status": "needsAction"})
        for name in ("title", "notes", "status"):
            if name in payload:
                task_expected_payload[name] = payload[name]
        if "scheduled_date" in payload:
            task_expected_payload["due"] = payload["scheduled_date"]
        return {"payload": task_expected_payload}
    if tool_name in {"calendar_create_event", "calendar_update_event"}:
        payload = _mapping(args.get("payload"), "payload")
        event_expected_payload: dict[str, object] = {
            "parent_id": _required_string(args, "calendar_id"),
        }
        if tool_name == "calendar_create_event":
            event_expected_payload.update(
                {
                    "description": "",
                    "attendees": [],
                    "status": "confirmed",
                }
            )
        # Calendar GET exposes these approved fields. Missing or altered values
        # must fail comparison, including lost attendees or description.
        for argument_name in ("title", "start", "end", "description", "attendees"):
            if argument_name in payload:
                event_expected_payload[argument_name] = payload[argument_name]
        return {"payload": event_expected_payload}
    raise LookupError(f"unsupported write tool for expected verification: {tool_name}")


def calculate_verification_subset_diff(
    expected: object,
    actual: object,
    *,
    path: str = "$",
) -> list[dict[str, object]]:
    """Compare only fields declared by Expected; extra Actual fields are benign.

    Lists remain exact/order-sensitive because recipient/attendee ordering and
    cardinality are business-visible unless a Tool-specific normalizer changes
    them before this function is called.
    """

    if isinstance(expected, dict):
        if not isinstance(actual, dict):
            return [{"path": path, "expected": expected, "actual": actual}]
        expected_map = cast(dict[str, object], expected)
        actual_map = cast(dict[str, object], actual)
        diffs: list[dict[str, object]] = []
        for key in sorted(expected_map):
            if key not in actual_map:
                diffs.append(
                    {
                        "path": f"{path}.{key}",
                        "expected": expected_map[key],
                        "actual": "<missing>",
                    }
                )
                continue
            diffs.extend(
                calculate_verification_subset_diff(
                    expected_map[key],
                    actual_map[key],
                    path=f"{path}.{key}",
                )
            )
        return diffs
    if isinstance(expected, list):
        if not isinstance(actual, list) or expected != actual:
            return [{"path": path, "expected": expected, "actual": actual}]
        return []
    if expected != actual:
        return [{"path": path, "expected": expected, "actual": actual}]
    return []


def normalize_actual_verification_projection(
    *,
    tool_name: str,
    actual: Mapping[str, object],
) -> dict[str, object]:
    """Normalize Connector execution metadata before subset comparison."""

    normalized = _deep_mapping_copy(actual)
    payload_value = normalized.get("payload")
    if not isinstance(payload_value, dict):
        return normalized
    payload = cast(dict[str, object], payload_value)
    if tool_name in {"gmail_create_draft", "gmail_update_draft", "gmail_send"}:
        for field in ("to", "cc", "bcc"):
            recipients = payload.get(field)
            if isinstance(recipients, str):
                recipients = [recipients]
            if isinstance(recipients, list) and all(isinstance(item, str) for item in recipients):
                payload[field] = sorted(address for _, address in getaddresses(recipients))
        body = payload.get("body")
        if isinstance(body, str):
            content = strip_resource_recovery_marker(body) or ""
            payload["body"] = content.replace("\r\n", "\n").strip()
        attachments = payload.get("attachments")
        if isinstance(attachments, list):
            payload["attachments"] = [
                {key: item.get(key) for key in ("filename", "mime_type", "size_bytes")}
                for item in attachments
                if isinstance(item, dict)
            ]
    if tool_name in {"tasks_create_task", "tasks_update_task"}:
        due = payload.get("due")
        if isinstance(due, str) and len(due) >= 10:
            payload["due"] = due[:10]
        notes = payload.get("notes")
        if isinstance(notes, str):
            payload["notes"] = strip_resource_recovery_marker(notes)
        elif "notes" in payload and notes is None:
            payload["notes"] = ""
    if tool_name in {"calendar_create_event", "calendar_update_event"}:
        for field_name in ("start", "end"):
            value = payload.get(field_name)
            if isinstance(value, str):
                payload[field_name] = _canonical_calendar_instant(value)
        description = payload.get("description")
        if isinstance(description, str):
            payload["description"] = strip_resource_recovery_marker(description)
        elif "description" in payload and description is None:
            payload["description"] = ""
        attendees = payload.get("attendees")
        if isinstance(attendees, list):
            payload["attendees"] = sorted(str(item) for item in attendees)
    return normalized


def _canonical_calendar_instant(value: str) -> str:
    candidate = f"{value[:-1]}+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError:
        return value
    if parsed.tzinfo is None:
        return value
    return parsed.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _mapping(value: object, path: str) -> dict[str, object]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{path} must be an object")
    return {str(key): item for key, item in value.items()}


def _required_string(value: Mapping[str, object], name: str) -> str:
    if name not in value:
        raise ValueError(f"{name} is required")
    return _string(value[name], name)


def _string(value: object, path: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{path} must be text")
    return value


def _string_list(value: object, path: str) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ValueError(f"{path} must be a string list")
    return list(cast(list[str], value))


def _deep_mapping_copy(value: Mapping[str, object]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, item in value.items():
        if isinstance(item, Mapping):
            result[str(key)] = _deep_mapping_copy(cast(Mapping[str, object], item))
        elif isinstance(item, list):
            result[str(key)] = list(item)
        else:
            result[str(key)] = item
    return result


__all__ = [
    "build_expected_verification_projection",
    "calculate_verification_subset_diff",
    "normalize_actual_verification_projection",
]
