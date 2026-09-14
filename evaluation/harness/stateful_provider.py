"""Stateful evaluation provider for fault paths that must avoid live WRITE."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from copy import deepcopy
from datetime import datetime, timezone
from typing import Any


class StatefulSimulatedProvider:
    """Duck-typed Connector Port implementation with durable in-memory effects.

    It never reads Canonical Gold.  Initial state and caller arguments are the
    only sources for READ results, so a CREATE/UPDATE is observable by a later
    independent READ exactly once.
    """

    def __init__(
        self,
        *,
        initial_resources: Sequence[Mapping[str, Any]] = (),
        read_result_factory: Callable[[str, dict[str, Any], int], Any] | None = None,
        write_result_factory: Callable[[str, dict[str, Any], int], Any] | None = None,
    ) -> None:
        self._resources: dict[tuple[str, str | None, str], dict[str, Any]] = {}
        for raw_item in initial_resources:
            item = deepcopy(dict(raw_item))
            resource_type = str(item["resource_type"])
            resource_id = str(item["resource_id"])
            parent_id = _stored_parent(resource_type, item.get("parent_id"))
            key = (resource_type, parent_id, resource_id)
            if key in self._resources:
                raise ValueError("duplicate simulated resource identity")
            self._resources[key] = item
        self._read_result_factory = read_result_factory or _default_read_result
        self._write_result_factory = write_result_factory or _default_write_result
        self._sequence = 0
        self.read_calls: list[str] = []
        self.write_calls: list[str] = []
        self.effect_counts: dict[str, int] = {}

    def execute_read(self, binding: Any, tool_arguments: dict[str, Any]) -> Any:
        tool_id = _tool_id(binding)
        self.read_calls.append(tool_id)
        if tool_id == "search_by_recovery_fingerprint":
            output = self._search_by_recovery_fingerprint(tool_arguments)
            return self._read_result_factory(tool_id, output, len(self.read_calls))
        if tool_id == "gmail_get_attachment":
            output = self._get_gmail_attachment(tool_arguments)
            return self._read_result_factory(tool_id, output, len(self.read_calls))
        if tool_id == "calendar_query_freebusy":
            output = self._query_freebusy(tool_arguments)
            return self._read_result_factory(tool_id, output, len(self.read_calls))
        list_type = {
            "gmail_search_threads": "gmail_thread",
            "gmail_search_drafts": "gmail_draft",
            "tasks_list_tasklists": "task_list",
            "tasks_list_tasks": "task",
            "calendar_list_calendars": "calendar",
            "calendar_list_events": "calendar_event",
        }.get(tool_id)
        if list_type is not None:
            output = self._list_resources(list_type, tool_arguments)
            return self._read_result_factory(tool_id, output, len(self.read_calls))
        resource_type, identity_key, parent_key = _read_identity(tool_id)
        resource_id = tool_arguments.get(identity_key)
        if not isinstance(resource_id, str) or not resource_id:
            raise ValueError(f"{tool_id} requires {identity_key}")
        parent_id = _required_parent(tool_arguments, parent_key, tool_id)
        item = self._resources.get((resource_type, parent_id, resource_id))
        output = {"item": None if item is None else _project_item(item)}
        return self._read_result_factory(tool_id, output, len(self.read_calls))

    def execute_write(
        self,
        binding: Any,
        tool_arguments: dict[str, Any],
        claim_token: dict[str, Any],
    ) -> Any:
        del claim_token
        tool_id = _tool_id(binding)
        self.write_calls.append(tool_id)
        if tool_id in {"tasks_create_task", "calendar_create_event", "gmail_create_draft"}:
            item = self._create(tool_id, tool_arguments)
        elif tool_id in {"tasks_update_task", "calendar_update_event", "gmail_update_draft"}:
            item = self._update(tool_id, tool_arguments)
        else:
            raise ValueError(f"unsupported simulated WRITE operation: {tool_id}")
        self.effect_counts[tool_id] = self.effect_counts.get(tool_id, 0) + 1
        return self._write_result_factory(tool_id, deepcopy(item), len(self.write_calls))

    def resource(
        self,
        resource_type: str,
        resource_id: str,
        *,
        parent_id: str | None = None,
    ) -> dict[str, Any] | None:
        matches = [
            item
            for (stored_type, stored_parent, stored_id), item in self._resources.items()
            if stored_type == resource_type
            and stored_id == resource_id
            and (parent_id is None or stored_parent == parent_id)
        ]
        if len(matches) > 1:
            raise LookupError("simulated resource identity requires a parent")
        return None if not matches else deepcopy(matches[0])

    def _search_by_recovery_fingerprint(self, arguments: Mapping[str, Any]) -> dict[str, Any]:
        resource_type = arguments.get("resource_type")
        fingerprint = arguments.get("recovery_fingerprint")
        if not isinstance(resource_type, str) or resource_type not in {
            "task",
            "calendar_event",
            "gmail_draft",
            "gmail_message",
        }:
            raise ValueError("search_by_recovery_fingerprint requires a supported resource_type")
        if not isinstance(fingerprint, str) or not fingerprint:
            raise ValueError("search_by_recovery_fingerprint requires recovery_fingerprint")
        parent_key = (
            "task_list_id"
            if resource_type == "task"
            else "calendar_id"
            if resource_type == "calendar_event"
            else None
        )
        parent_id = _required_parent(arguments, parent_key, "search_by_recovery_fingerprint")
        items = [
            _project_item(item)
            for (stored_type, stored_parent, _), item in self._resources.items()
            if stored_type == resource_type
            and stored_parent == parent_id
            and _contains_value(item, fingerprint)
        ]
        return {"items": items, "total_count": len(items)}

    def _list_resources(self, resource_type: str, arguments: Mapping[str, Any]) -> dict[str, Any]:
        parent_key = (
            "task_list_id"
            if resource_type == "task"
            else "calendar_id"
            if resource_type == "calendar_event"
            else None
        )
        parent_id = arguments.get(parent_key) if parent_key is not None else None
        if parent_key is not None and (not isinstance(parent_id, str) or not parent_id):
            raise ValueError(f"{resource_type} list requires {parent_key}")
        items = [
            _project_item(item)
            for (stored_type, stored_parent, _), item in self._resources.items()
            if stored_type == resource_type and (parent_key is None or stored_parent == parent_id)
        ]
        if resource_type == "task" and not bool(arguments.get("show_completed", False)):
            items = [item for item in items if _item_payload(item).get("status") != "completed"]
        if resource_type == "calendar_event":
            items = [item for item in items if _event_in_range(item, arguments)]
        page_size = arguments.get("page_size", 100)
        if not isinstance(page_size, int) or page_size < 1:
            raise ValueError("page_size must be a positive integer")
        return {"items": items[:page_size], "next_page_token": None}

    def _query_freebusy(self, arguments: Mapping[str, Any]) -> dict[str, Any]:
        calendar_ids = arguments.get("calendar_ids")
        if not isinstance(calendar_ids, list) or not all(
            isinstance(item, str) and item for item in calendar_ids
        ):
            raise ValueError("calendar_query_freebusy requires calendar_ids")
        time_min = arguments.get("time_min")
        time_max = arguments.get("time_max")
        if not isinstance(time_min, str) or not isinstance(time_max, str):
            raise ValueError("calendar_query_freebusy requires a temporal range")
        calendars = []
        for calendar_id in calendar_ids:
            intervals = []
            for (stored_type, stored_parent, _), stored in self._resources.items():
                if stored_type != "calendar_event" or stored_parent != calendar_id:
                    continue
                item = _project_item(stored)
                payload = _item_payload(item)
                if (
                    payload.get("status") == "cancelled"
                    or payload.get("transparency") == "transparent"
                    or not _event_in_range(
                        item,
                        {"time_min": time_min, "time_max": time_max},
                    )
                ):
                    continue
                intervals.append(
                    {
                        "start": payload["start"],
                        "end": payload["end"],
                        "transparency": "busy",
                    }
                )
            calendars.append({"calendar_id": calendar_id, "intervals": intervals})
        return {"calendars": calendars}

    def _get_gmail_attachment(self, arguments: Mapping[str, Any]) -> dict[str, Any]:
        message_id = arguments.get("message_id")
        attachment_id = arguments.get("attachment_id")
        if not isinstance(message_id, str) or not isinstance(attachment_id, str):
            raise ValueError("gmail_get_attachment requires message_id and attachment_id")
        for (resource_type, _, _), stored in self._resources.items():
            if resource_type != "gmail_thread":
                continue
            messages = stored.get("payload", {}).get("messages", [])
            if not isinstance(messages, list):
                continue
            for message in messages:
                if not isinstance(message, Mapping) or message.get("message_id") != message_id:
                    continue
                attachments = message.get("attachments", [])
                if not isinstance(attachments, list):
                    continue
                for attachment in attachments:
                    if (
                        isinstance(attachment, Mapping)
                        and attachment.get("attachment_id") == attachment_id
                    ):
                        return deepcopy(dict(attachment))
        raise LookupError("simulated Gmail attachment not found")

    def _create(self, tool_id: str, arguments: Mapping[str, Any]) -> dict[str, Any]:
        resource_type, identity_key, parent_key = _write_identity(tool_id)
        supplied = arguments.get(identity_key)
        if supplied is not None and (not isinstance(supplied, str) or not supplied):
            raise ValueError(f"{identity_key} must be a non-empty string")
        self._sequence += 1
        resource_id = supplied or f"evaluation-{resource_type}-{self._sequence}"
        parent_id = _required_parent(arguments, parent_key, tool_id)
        key = (resource_type, parent_id, resource_id)
        if key in self._resources:
            raise ValueError("simulated CREATE target already exists")
        payload = _business_payload(arguments, identity_key, parent_key)
        item = {
            "resource_type": resource_type,
            "resource_id": resource_id,
            "parent_id": parent_id,
            "version": "1",
            "payload": payload,
        }
        self._resources[key] = item
        return item

    def _update(self, tool_id: str, arguments: Mapping[str, Any]) -> dict[str, Any]:
        resource_type, identity_key, parent_key = _write_identity(tool_id)
        resource_id = arguments.get(identity_key)
        if not isinstance(resource_id, str) or not resource_id:
            raise ValueError(f"{tool_id} requires {identity_key}")
        parent_id = _required_parent(arguments, parent_key, tool_id)
        key = (resource_type, parent_id, resource_id)
        current = self._resources.get(key)
        if current is None:
            target = f"{parent_id}/{resource_id}" if parent_id is not None else resource_id
            raise LookupError(f"simulated target not found: {resource_type}/{target}")
        updated = deepcopy(current)
        payload = dict(updated.get("payload", {}))
        payload.update(_business_payload(arguments, identity_key, parent_key))
        updated["payload"] = payload
        updated["version"] = str(int(str(updated.get("version", "0"))) + 1)
        self._resources[key] = updated
        return updated


def _tool_id(binding: Any) -> str:
    value = getattr(binding, "tool_id", None)
    if not isinstance(value, str) or not value:
        raise ValueError("connector binding must expose tool_id")
    return value


def _read_identity(tool_id: str) -> tuple[str, str, str | None]:
    mapping = {
        "tasks_get_task": ("task", "task_id", "task_list_id"),
        "calendar_get_event": ("calendar_event", "event_id", "calendar_id"),
        "gmail_get_draft": ("gmail_draft", "draft_id", None),
        "gmail_get_thread": ("gmail_thread", "thread_id", None),
    }
    try:
        return mapping[tool_id]
    except KeyError as error:
        raise ValueError(f"unsupported simulated READ operation: {tool_id}") from error


def _write_identity(tool_id: str) -> tuple[str, str, str | None]:
    mapping = {
        "tasks_create_task": ("task", "task_id", "task_list_id"),
        "tasks_update_task": ("task", "task_id", "task_list_id"),
        "calendar_create_event": ("calendar_event", "event_id", "calendar_id"),
        "calendar_update_event": ("calendar_event", "event_id", "calendar_id"),
        "gmail_create_draft": ("gmail_draft", "draft_id", None),
        "gmail_update_draft": ("gmail_draft", "draft_id", None),
    }
    try:
        return mapping[tool_id]
    except KeyError as error:
        raise ValueError(f"unsupported simulated WRITE operation: {tool_id}") from error


def _required_parent(
    arguments: Mapping[str, Any], parent_key: str | None, tool_id: str
) -> str | None:
    if parent_key is None:
        return None
    parent_id = arguments.get(parent_key)
    if not isinstance(parent_id, str) or not parent_id:
        raise ValueError(f"{tool_id} requires {parent_key}")
    return parent_id


def _stored_parent(resource_type: str, value: Any) -> str | None:
    if resource_type not in {"task", "calendar_event"}:
        return None
    if not isinstance(value, str) or not value:
        raise ValueError(f"{resource_type} requires parent_id")
    return value


def _business_payload(
    arguments: Mapping[str, Any], identity_key: str, parent_key: str | None
) -> dict[str, Any]:
    nested = arguments.get("payload")
    payload = deepcopy(dict(nested)) if isinstance(nested, Mapping) else {}
    excluded = {identity_key, parent_key, "claim_context", "payload"}
    payload.update(
        {name: deepcopy(value) for name, value in arguments.items() if name not in excluded}
    )
    return payload


def _contains_value(value: Any, expected: str) -> bool:
    if isinstance(value, str):
        return value == expected
    if isinstance(value, Mapping):
        return any(_contains_value(item, expected) for item in value.values())
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return any(_contains_value(item, expected) for item in value)
    return False


def _project_item(item: Mapping[str, Any]) -> dict[str, Any]:
    payload = item.get("payload")
    resource_type = str(item["resource_type"])
    resource_id = str(item["resource_id"])
    parent_id = item.get("parent_id")
    return {
        "fixture_snapshot_id": resource_id,
        "resource_type": resource_type,
        "resource_id": resource_id,
        "parent_id": parent_id,
        "related_resource_ids": (
            [parent_id] if resource_type in {"task", "calendar_event"} else []
        ),
        "version": str(item.get("version", "1")),
        "recovery_fingerprint": (
            payload.get("recovery_fingerprint") if isinstance(payload, Mapping) else None
        ),
        "payload": deepcopy(dict(payload)) if isinstance(payload, Mapping) else {},
    }


def _item_payload(item: Mapping[str, Any]) -> Mapping[str, Any]:
    payload = item.get("payload")
    return payload if isinstance(payload, Mapping) else item


def _event_in_range(item: Mapping[str, Any], arguments: Mapping[str, Any]) -> bool:
    payload = _item_payload(item)
    start = _temporal_value(payload.get("start"))
    end = _temporal_value(payload.get("end"))
    time_min = arguments.get("time_min")
    time_max = arguments.get("time_max")
    if isinstance(time_min, str) and end is not None and end <= _parse_time(time_min):
        return False
    return not (isinstance(time_max, str) and start is not None and start >= _parse_time(time_max))


def _temporal_value(value: Any) -> datetime | None:
    if isinstance(value, Mapping):
        value = value.get("date_time") or value.get("dateTime") or value.get("date")
    return _parse_time(value) if isinstance(value, str) else None


def _parse_time(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return (
        parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=timezone.utc)  # noqa: UP017 -- Python 3.10 target
    )


def _default_read_result(tool_id: str, output: dict[str, Any], sequence: int) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "tool_id": tool_id,
        "request_id": f"evaluation-read-{sequence}",
        "output": output,
        "next_page_token": None,
        "total_count": output.get("total_count"),
    }


def _default_write_result(tool_id: str, item: dict[str, Any], sequence: int) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "success": True,
        "delivery_certainty": None,
        "provider_request_id": f"evaluation-write-{sequence}",
        "response_metadata": {
            "tool_id": tool_id,
            "resource_type": item["resource_type"],
            "resource_id": item["resource_id"],
            "version": item["version"],
        },
        "error_code": None,
        "safe_error_code": None,
    }


__all__ = ["StatefulSimulatedProvider"]
