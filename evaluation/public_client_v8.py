"""HTTP-only client for the supported local Product API."""

from __future__ import annotations

import json
import time
from http.cookiejar import CookieJar
from typing import Any, cast
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode, urlparse
from urllib.request import HTTPCookieProcessor, Request, build_opener


class PublicProductError(RuntimeError):
    pass


class PublicRunObservationTimeout(PublicProductError):
    def __init__(self, run_id: str, snapshot: dict[str, Any]) -> None:
        super().__init__(f"run observation timeout: {run_id}")
        self.run_id = run_id
        self.snapshot = snapshot


class PublicProductClientV8:
    def __init__(self, base_url: str, *, timeout_seconds: float = 35.0) -> None:
        parsed = urlparse(base_url)
        if parsed.scheme != "http" or parsed.hostname != "127.0.0.1":
            raise ValueError("Canonical evaluation requires a 127.0.0.1 Product origin")
        if parsed.path not in {"", "/"} or parsed.query or parsed.fragment:
            raise ValueError("base_url must be an origin")
        self._base_url = base_url.rstrip("/")
        self._origin = f"{parsed.scheme}://{parsed.netloc}"
        self._timeout_seconds = timeout_seconds
        self._opener = build_opener(HTTPCookieProcessor(CookieJar()))

    def bootstrap(self, bootstrap_secret: str) -> dict[str, Any]:
        return self._request(
            "POST",
            "/api/v1/session/bootstrap",
            {
                "schema_version": 1,
                "bootstrap_secret": bootstrap_secret,
                "frontend_api_contract_version": "1",
            },
        )

    def create_conversation(self, *, command_id: str, title: str) -> dict[str, Any]:
        return self._request(
            "POST",
            "/api/v1/conversations",
            {"schema_version": 1, "command_id": command_id, "title": title},
        )

    def select_local_model(self, *, model_id: str, command_id: str) -> dict[str, Any]:
        return self._request(
            "PUT",
            "/api/v1/settings",
            {
                "schema_version": 1,
                "command_id": command_id,
                "settings_patch": {
                    "schema_version": 1,
                    "preferred_local_model_id": model_id,
                    "preferred_llm_mode": "LOCAL_GPU",
                },
            },
        )

    def bind_google_resource_scope(
        self,
        *,
        calendar_ids: list[str],
        tasklist_ids: list[str],
        command_id: str,
    ) -> dict[str, Any]:
        """Verify fixture containers through public inventory, then save selection."""
        expected = {
            "calendar": set(calendar_ids),
            "tasks": set(tasklist_ids),
        }
        for source, resource_ids in expected.items():
            if not resource_ids:
                continue
            available = self._list_google_container_ids(source)
            missing = sorted(resource_ids - available)
            if missing:
                raise PublicProductError(
                    f"fixture containers are absent from public {source} inventory: {len(missing)}"
                )
        return self._request(
            "PUT",
            "/api/v1/settings",
            {
                "schema_version": 1,
                "command_id": command_id,
                "settings_patch": {
                    "schema_version": 1,
                    "selected_calendar_ids": calendar_ids,
                    "selected_tasklist_ids": tasklist_ids,
                },
            },
        )

    def list_resources(
        self,
        resource_type: str,
        *,
        parent_id: str | None = None,
        page_token: str | None = None,
    ) -> dict[str, Any]:
        path_by_type = {
            "gmail_thread": "/api/v1/resources/gmail",
            "calendar_event": "/api/v1/resources/calendar",
            "task": "/api/v1/resources/tasks",
        }
        try:
            path = path_by_type[resource_type]
        except KeyError as error:
            raise ValueError(
                f"unsupported public selection resource type: {resource_type}"
            ) from error
        query: dict[str, object] = {"page_size": 100}
        if page_token:
            query["page_token"] = page_token
        if parent_id:
            query["calendar_id" if resource_type == "calendar_event" else "task_list_id"] = (
                parent_id
            )
        return self._request("GET", f"{path}?{urlencode(query)}")

    def resolve_selection_handles(self, bindings: list[dict[str, Any]]) -> list[str]:
        handles: list[str] = []
        for binding in bindings:
            resource_id = binding.get("resource_id")
            resource_type = binding.get("resource_type")
            parent_id = binding.get("parent_id")
            if not isinstance(resource_id, str) or not isinstance(resource_type, str):
                raise ValueError("selection binding identity is invalid")
            token: str | None = None
            while True:
                page = self.list_resources(
                    resource_type,
                    parent_id=parent_id if isinstance(parent_id, str) else None,
                    page_token=token,
                )
                items = page.get("items")
                if not isinstance(items, list):
                    raise PublicProductError("resource list response has no items")
                match = next(
                    (
                        item
                        for item in items
                        if isinstance(item, dict) and item.get("resource_id") == resource_id
                    ),
                    None,
                )
                if match is not None:
                    handle = match.get("selection_handle")
                    if not isinstance(handle, str) or not handle:
                        raise PublicProductError("selected resource has no public handle")
                    handles.append(handle)
                    break
                next_token = page.get("next_page_token")
                if not isinstance(next_token, str) or not next_token:
                    raise PublicProductError(
                        f"bound resource is absent from public projection: {resource_type}"
                    )
                token = next_token
        return handles

    def _list_google_container_ids(self, source: str) -> set[str]:
        path, identity_key = {
            "calendar": ("/api/v1/resources/calendars", "calendar_id"),
            "tasks": ("/api/v1/resources/task-lists", "tasklist_id"),
        }[source]
        result: set[str] = set()
        token: str | None = None
        for _ in range(100):
            query: dict[str, object] = {"page_size": 100, "include_unselected": "true"}
            if token:
                query["page_token"] = token
            page = self._request("GET", f"{path}?{urlencode(query)}")
            items = page.get("items")
            if not isinstance(items, list):
                raise PublicProductError(f"public {source} inventory has no items")
            result.update(
                item[identity_key]
                for item in items
                if isinstance(item, dict) and isinstance(item.get(identity_key), str)
            )
            next_token = page.get("next_page_token")
            if not isinstance(next_token, str) or not next_token:
                return result
            token = next_token
        raise PublicProductError(f"public {source} inventory pagination exceeded its bound")

    def start_run(
        self,
        *,
        command_id: str,
        conversation_id: str,
        request_text: str,
        entry_mode: str,
        selected_resource_handles: list[str],
    ) -> dict[str, Any]:
        return self._request(
            "POST",
            "/api/v1/runs",
            {
                "api_contract_version": "1",
                "command_id": command_id,
                "conversation_id": conversation_id,
                "request_text": request_text,
                "entry_mode": entry_mode,
                "selected_resource_handles": selected_resource_handles,
                "requested_mode": "LOCAL_GPU",
            },
        )

    def get_run(self, run_id: str) -> dict[str, Any]:
        return self._request("GET", f"/api/v1/runs/{quote(run_id, safe='')}")

    def approve_action(self, action: dict[str, Any]) -> dict[str, Any]:
        action_id = action.get("action_id")
        version = action.get("version")
        if not isinstance(action_id, str) or not isinstance(version, int):
            raise ValueError("public action projection is invalid")
        acknowledgements = action.get("required_acknowledgements", [])
        return self._request(
            "POST",
            f"/api/v1/actions/{quote(action_id, safe='')}/approve",
            {
                "api_contract_version": "1",
                "command_id": f"eval-approve-{action_id}-{version}",
                "expected_version": version,
                "duplicate_acknowledged": "TASK_DUPLICATE" in acknowledgements,
                "calendar_conflict_acknowledged": "CALENDAR_CONFLICT" in acknowledgements,
            },
        )

    def wait_for_observation(
        self,
        run_id: str,
        *,
        timeout_seconds: float,
        auto_approve: bool,
    ) -> dict[str, Any]:
        deadline = time.monotonic() + timeout_seconds
        approved: set[str] = set()
        latest: dict[str, Any] = {}
        stable_observation_count = 0
        while time.monotonic() < deadline:
            latest = self.get_run(run_id)
            run = latest.get("run")
            status = run.get("status") if isinstance(run, dict) else None
            if status == "WAITING_APPROVAL" and auto_approve:
                pending = [
                    action
                    for action in latest.get("actions", [])
                    if isinstance(action, dict)
                    and action.get("status") in {"PENDING", "WAITING_APPROVAL"}
                    and action.get("action_id") not in approved
                ]
                if pending:
                    for action in pending:
                        self.approve_action(action)
                        approved.add(cast(str, action["action_id"]))
                    stable_observation_count = 0
                    time.sleep(0.2)
                    continue
            observable = status in {
                "BLOCKED",
                "COMPLETED",
                "CANCELLED",
                "FAILED",
                "WAITING_CONFIRMATION",
                "WAITING_APPROVAL",
                "FAILED_RETRYABLE",
                "REAUTH_REQUIRED",
                "RECOVERY_REQUIRED",
            }
            if observable:
                stable_observation_count += 1
                if stable_observation_count >= 2:
                    return latest
            else:
                stable_observation_count = 0
            time.sleep(0.25)
        raise PublicRunObservationTimeout(run_id, latest)

    def _request(
        self, method: str, path: str, payload: dict[str, object] | None = None
    ) -> dict[str, Any]:
        body = None if payload is None else json.dumps(payload).encode("utf-8")
        request = Request(
            self._base_url + path,
            data=body,
            method=method,
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
                "Origin": self._origin,
                "Sec-Fetch-Site": "same-origin",
                "Sec-Fetch-Mode": "cors",
                "Sec-Fetch-Dest": "empty",
                "X-API-Contract-Version": "1",
            },
        )
        try:
            with self._opener.open(request, timeout=self._timeout_seconds) as response:
                value = json.loads(response.read().decode("utf-8"))
        except HTTPError as error:
            safe_body = error.read(4096).decode("utf-8", errors="replace")
            raise PublicProductError(
                f"Product API HTTP {error.code} for {path}: {safe_body}"
            ) from error
        except (URLError, TimeoutError, UnicodeDecodeError, json.JSONDecodeError) as error:
            raise PublicProductError(f"Product API request failed for {path}") from error
        if not isinstance(value, dict):
            raise PublicProductError(f"Product API returned a non-object for {path}")
        return cast(dict[str, Any], value)


__all__ = [
    "PublicProductClientV8",
    "PublicProductError",
    "PublicRunObservationTimeout",
]
