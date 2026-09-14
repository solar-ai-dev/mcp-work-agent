"""Stateful evaluation provider for fault paths that must avoid live WRITE."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from copy import deepcopy
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
        self._resources = {
            (str(item["resource_type"]), str(item["resource_id"])): deepcopy(dict(item))
            for item in initial_resources
        }
        self._read_result_factory = read_result_factory or _default_read_result
        self._write_result_factory = write_result_factory or _default_write_result
        self._sequence = 0
        self.read_calls: list[str] = []
        self.write_calls: list[str] = []
        self.effect_counts: dict[str, int] = {}

    def execute_read(self, binding: Any, tool_arguments: dict[str, Any]) -> Any:
        tool_id = _tool_id(binding)
        self.read_calls.append(tool_id)
        resource_type, identity_key = _read_identity(tool_id)
        resource_id = tool_arguments.get(identity_key)
        if not isinstance(resource_id, str) or not resource_id:
            raise ValueError(f"{tool_id} requires {identity_key}")
        item = self._resources.get((resource_type, resource_id))
        output = {
            "item": None if item is None else deepcopy(item),
            "total_count": int(item is not None),
        }
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

    def resource(self, resource_type: str, resource_id: str) -> dict[str, Any] | None:
        item = self._resources.get((resource_type, resource_id))
        return None if item is None else deepcopy(item)

    def _create(self, tool_id: str, arguments: Mapping[str, Any]) -> dict[str, Any]:
        resource_type, identity_key, parent_key = _write_identity(tool_id)
        supplied = arguments.get(identity_key)
        if supplied is not None and (not isinstance(supplied, str) or not supplied):
            raise ValueError(f"{identity_key} must be a non-empty string")
        self._sequence += 1
        resource_id = supplied or f"evaluation-{resource_type}-{self._sequence}"
        key = (resource_type, resource_id)
        if key in self._resources:
            raise ValueError("simulated CREATE target already exists")
        parent_id = arguments.get(parent_key) if parent_key is not None else None
        payload = {
            name: deepcopy(value)
            for name, value in arguments.items()
            if name not in {identity_key, parent_key, "claim_context"}
        }
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
        key = (resource_type, resource_id)
        current = self._resources.get(key)
        if current is None:
            raise LookupError(f"simulated target not found: {resource_type}/{resource_id}")
        updated = deepcopy(current)
        payload = dict(updated.get("payload", {}))
        for name, value in arguments.items():
            if name not in {identity_key, parent_key, "claim_context"}:
                payload[name] = deepcopy(value)
        updated["payload"] = payload
        updated["version"] = str(int(str(updated.get("version", "0"))) + 1)
        self._resources[key] = updated
        return updated


def _tool_id(binding: Any) -> str:
    value = getattr(binding, "tool_id", None)
    if not isinstance(value, str) or not value:
        raise ValueError("connector binding must expose tool_id")
    return value


def _read_identity(tool_id: str) -> tuple[str, str]:
    mapping = {
        "tasks_get_task": ("task", "task_id"),
        "calendar_get_event": ("calendar_event", "event_id"),
        "gmail_get_draft": ("gmail_draft", "draft_id"),
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


def _default_read_result(tool_id: str, output: dict[str, Any], sequence: int) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "tool_id": tool_id,
        "request_id": f"evaluation-read-{sequence}",
        "output": output,
        "next_page_token": None,
        "total_count": output["total_count"],
    }


def _default_write_result(
    tool_id: str, item: dict[str, Any], sequence: int
) -> dict[str, Any]:
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
