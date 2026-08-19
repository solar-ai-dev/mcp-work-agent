"""Local MCP child process skeleton for the GitHub connector.

All six declared Issue tools are wired to the real GitHub Issue Provider
Adapter (`github_issue_provider.py`): reads (`github_list_issues`,
`github_get_issue`) and writes (`github_create_issue`, `github_update_issue`,
`github_close_issue`, `github_reopen_issue`). This module owns argument
parsing, dispatch, and the MCP response/error envelope only -- REST calls,
mutation body assembly, and normalization all live in
`github_issue_provider.py`. Write mutations are not wired to Approval/Claim/
Verification/Recovery; that Runtime integration is a later step. The GitHub
App Device Flow auth boundary (`github_auth.py`) is wired into
`control_call` so the credential lifecycle is reachable through this
process -- but it never leaves process memory: neither `control_call` nor
`tool_call` responses ever carry `access_token`/`refresh_token` values.
"""

from __future__ import annotations

import json
import os
import secrets
import sys
import time
from typing import cast

from google_work_agent.adapters.keyring import OSKeyringSecretStore
from google_work_agent.adapters.mcp.transport import PROTOCOL_VERSION
from google_work_agent.domain.github_tool_registry import build_github_tool_registry
from google_work_agent.mcp.github_auth import (
    GitHubCredentialProvider,
    GitHubDeviceAuthorization,
    GitHubDeviceFlowClient,
    GitHubOAuthConfigurationError,
)
from google_work_agent.mcp.github_issue_provider import (
    GitHubIssueCreateInput,
    GitHubIssueListQuery,
    GitHubIssueProviderAdapter,
    GitHubIssueQueryError,
    GitHubIssueState,
    GitHubIssueStateChangeInput,
    GitHubIssueTaskView,
    GitHubIssueUpdateInput,
    GitHubProviderError,
    normalize_github_issue,
    normalize_github_issue_list,
)
from google_work_agent.ports import SecretStore

_READ_TOOL_NAMES = ("github_list_issues", "github_get_issue")
_WRITE_TOOL_NAMES = (
    "github_create_issue",
    "github_update_issue",
    "github_close_issue",
    "github_reopen_issue",
)
_ACTIVE_TOOL_NAMES = _READ_TOOL_NAMES + _WRITE_TOOL_NAMES


class _ToolNotAvailableError(Exception):
    pass


class _ControlCallError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class _GitHubState:
    def __init__(self) -> None:
        self.process_instance_id = f"mcp-{secrets.token_hex(8)}"
        self.service_instance_id: str | None = None
        self.session_key: str | None = None
        self.active_device_authorization: GitHubDeviceAuthorization | None = None
        self._credential_provider: GitHubCredentialProvider | None = None
        self._issue_provider: GitHubIssueProviderAdapter | None = None

    def credential_provider(self) -> GitHubCredentialProvider:
        if self._credential_provider is not None:
            return self._credential_provider
        client_id = os.environ.get("GITHUB_APP_CLIENT_ID", "").strip()
        if not client_id:
            raise GitHubOAuthConfigurationError("GITHUB_APP_CLIENT_ID_MISSING")
        try:
            keyring = _credential_store_from_environment()
        except RuntimeError as error:
            raise GitHubOAuthConfigurationError("KEYRING_UNAVAILABLE") from error
        scope = os.environ.get("GITHUB_APP_SCOPE", "").strip()
        device_flow = GitHubDeviceFlowClient(client_id=client_id, scope=scope, now_ms=_now_ms)
        self._credential_provider = GitHubCredentialProvider(
            keyring=keyring, device_flow=device_flow, now_ms=_now_ms
        )
        return self._credential_provider

    def issue_provider(self) -> GitHubIssueProviderAdapter:
        if self._issue_provider is None:
            self._issue_provider = GitHubIssueProviderAdapter(
                credential_provider=self.credential_provider()
            )
        return self._issue_provider


def _credential_store_from_environment() -> SecretStore:
    return OSKeyringSecretStore()


def main() -> None:
    state = _GitHubState()
    for raw_line in sys.stdin:
        line = raw_line.strip()
        if not line:
            continue
        request = cast(dict[str, object], json.loads(line))
        request_id = str(request.get("id", ""))
        if str(request.get("type")) == "shutdown":
            break
        try:
            _write({"id": request_id, "payload": _dispatch(state, request)})
        except _ToolNotAvailableError:
            _write(
                {
                    "id": request_id,
                    "error": {
                        "code": "TOOL_REJECTED",
                        "message": "TOOL_NOT_AVAILABLE",
                        "dispatch_started": False,
                    },
                }
            )
        except GitHubOAuthConfigurationError as error:
            _write(
                {
                    "id": request_id,
                    "error": {
                        "code": "CONFIGURATION_ERROR",
                        "message": error.safe_code,
                        "dispatch_started": False,
                    },
                }
            )
        except _ControlCallError as error:
            _write(
                {
                    "id": request_id,
                    "error": {
                        "code": error.code,
                        "message": error.message,
                        "dispatch_started": False,
                    },
                }
            )
        except GitHubIssueQueryError as error:
            _write(
                {
                    "id": request_id,
                    "error": {
                        "code": "TOOL_REJECTED",
                        "message": error.safe_code,
                        "dispatch_started": False,
                    },
                }
            )
        except GitHubProviderError as error:
            _write(
                {
                    "id": request_id,
                    "error": {
                        "code": "TOOL_REJECTED",
                        "message": error.safe_code,
                        "dispatch_started": error.dispatch_started,
                    },
                }
            )
        except Exception:
            _write(
                {
                    "id": request_id,
                    "error": {
                        "code": "MALFORMED_RESPONSE",
                        "message": "MCP request failed.",
                        "dispatch_started": True,
                    },
                }
            )


def _dispatch(state: _GitHubState, request: dict[str, object]) -> dict[str, object]:
    message_type = str(request["type"])
    if message_type == "handshake":
        session_key = str(request["session_key"])
        if len(bytes.fromhex(session_key)) < 32:
            raise ValueError("session key must be at least 256 bits")
        state.service_instance_id = str(request["service_instance_id"])
        state.session_key = session_key
        return {"process_instance_id": state.process_instance_id}
    if message_type == "initialize":
        return {
            "protocol_version": PROTOCOL_VERSION,
            "manifest_version": str(request["manifest_version"]),
            "tool_registry_version": str(request["tool_registry_version"]),
        }
    if message_type == "list_tools":
        return {
            "tool_names": sorted(
                entry.tool_name for entry in build_github_tool_registry().list_entries()
            )
        }
    if message_type == "control_call":
        return _control_call(state, method=str(request["method"]))
    if message_type == "tool_call":
        tool_name = str(request["tool_name"])
        arguments = cast(dict[str, object], request.get("arguments", {}))
        return _tool_call(state, tool_name=tool_name, arguments=arguments)
    raise ValueError("unsupported message type")


def _tool_call(
    state: _GitHubState, *, tool_name: str, arguments: dict[str, object]
) -> dict[str, object]:
    if tool_name not in _ACTIVE_TOOL_NAMES:
        raise _ToolNotAvailableError(tool_name)
    if tool_name == "github_list_issues":
        return _github_list_issues(state, arguments)
    if tool_name == "github_get_issue":
        return _github_get_issue(state, arguments)
    if tool_name == "github_create_issue":
        return _github_create_issue(state, arguments)
    if tool_name == "github_update_issue":
        return _github_update_issue(state, arguments)
    if tool_name == "github_close_issue":
        return _github_close_issue(state, arguments)
    return _github_reopen_issue(state, arguments)


def _github_list_issues(state: _GitHubState, arguments: dict[str, object]) -> dict[str, object]:
    query = _parse_list_issues_arguments(arguments)
    raw_items = state.issue_provider().list_issues(query)
    views = normalize_github_issue_list(raw_items, repository=query.repository)
    return {"items": [_issue_payload(view) for view in views]}


def _github_get_issue(state: _GitHubState, arguments: dict[str, object]) -> dict[str, object]:
    repository = _require_str_argument(arguments, "repository")
    issue_number = _require_int_argument(arguments, "issue_number")
    raw = state.issue_provider().get_issue(repository=repository, issue_number=issue_number)
    view = normalize_github_issue(raw, repository=repository)
    return _issue_payload(view)


def _github_create_issue(state: _GitHubState, arguments: dict[str, object]) -> dict[str, object]:
    repository = _require_str_argument(arguments, "repository")
    title = _require_str_argument(arguments, "title")
    body = _optional_str_argument(arguments, "body")
    create = GitHubIssueCreateInput(repository=repository, title=title, body=body)
    raw = state.issue_provider().create_issue(create)
    view = normalize_github_issue(raw, repository=repository)
    return _issue_payload(view)


def _github_update_issue(state: _GitHubState, arguments: dict[str, object]) -> dict[str, object]:
    repository = _require_str_argument(arguments, "repository")
    issue_number = _require_int_argument(arguments, "issue_number")
    title = _optional_str_argument(arguments, "title")
    body = _optional_str_argument(arguments, "body")
    update = GitHubIssueUpdateInput(
        repository=repository, issue_number=issue_number, title=title, body=body
    )
    raw = state.issue_provider().update_issue(update)
    view = normalize_github_issue(raw, repository=repository)
    return _issue_payload(view)


def _github_close_issue(state: _GitHubState, arguments: dict[str, object]) -> dict[str, object]:
    repository = _require_str_argument(arguments, "repository")
    issue_number = _require_int_argument(arguments, "issue_number")
    change = GitHubIssueStateChangeInput(repository=repository, issue_number=issue_number)
    raw = state.issue_provider().close_issue(change)
    view = normalize_github_issue(raw, repository=repository)
    return _issue_payload(view)


def _github_reopen_issue(state: _GitHubState, arguments: dict[str, object]) -> dict[str, object]:
    repository = _require_str_argument(arguments, "repository")
    issue_number = _require_int_argument(arguments, "issue_number")
    change = GitHubIssueStateChangeInput(repository=repository, issue_number=issue_number)
    raw = state.issue_provider().reopen_issue(change)
    view = normalize_github_issue(raw, repository=repository)
    return _issue_payload(view)


def _parse_list_issues_arguments(arguments: dict[str, object]) -> GitHubIssueListQuery:
    repository = _require_str_argument(arguments, "repository")
    state_value = arguments.get("state")
    issue_state = GitHubIssueState.OPEN
    if state_value is not None:
        if not isinstance(state_value, str):
            raise GitHubIssueQueryError("STATE_INVALID")
        normalized_state = state_value.upper()
        if normalized_state not in GitHubIssueState.__members__:
            raise GitHubIssueQueryError("STATE_INVALID")
        issue_state = GitHubIssueState[normalized_state]
    return GitHubIssueListQuery(
        repository=repository,
        state=issue_state,
        assignee=_optional_str_argument(arguments, "assignee"),
        label=_optional_str_argument(arguments, "label"),
    )


def _issue_payload(view: GitHubIssueTaskView) -> dict[str, object]:
    return {
        "external_resource_id": view.resource_identity.external_resource_id,
        "repository": view.resource_identity.repository,
        "issue_number": view.resource_identity.issue_number,
        "title": view.title,
        "description": view.description,
        "task_state": view.task_state.value,
        "url": view.url,
        "labels": list(view.labels),
        "assignees": list(view.assignees),
    }


def _require_str_argument(arguments: dict[str, object], key: str) -> str:
    value = arguments.get(key)
    if not isinstance(value, str) or not value.strip():
        raise GitHubIssueQueryError(f"{key.upper()}_INVALID")
    return value


def _require_int_argument(arguments: dict[str, object], key: str) -> int:
    value = arguments.get(key)
    if not isinstance(value, int) or isinstance(value, bool):
        raise GitHubIssueQueryError(f"{key.upper()}_INVALID")
    return value


def _optional_str_argument(arguments: dict[str, object], key: str) -> str | None:
    value = arguments.get(key)
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise GitHubIssueQueryError(f"{key.upper()}_INVALID")
    return value


def _control_call(state: _GitHubState, *, method: str) -> dict[str, object]:
    if method == "github.connection.get":
        status = state.credential_provider().get_connection_status()
        return {
            "connected": status.connected,
            "credential_state": status.credential_state.value,
            "reauth_required": status.reauth_required,
            "last_checked_at_ms": status.last_checked_at_ms,
        }
    if method == "github.device_flow.start":
        authorization = state.credential_provider().start_device_flow()
        state.active_device_authorization = authorization
        return {
            "user_code": authorization.user_code,
            "verification_uri": authorization.verification_uri,
            "expires_at_ms": authorization.expires_at_ms,
            "interval_seconds": authorization.interval_seconds,
        }
    if method == "github.device_flow.poll":
        active_authorization = state.active_device_authorization
        if active_authorization is None:
            raise _ControlCallError("NOT_FOUND", "NO_ACTIVE_DEVICE_FLOW")
        result = state.credential_provider().complete_device_flow(active_authorization)
        if result.status.value == "APPROVED":
            state.active_device_authorization = None
        return {
            "status": result.status.value,
            "interval_seconds": result.interval_seconds,
        }
    if method == "github.connection.disconnect":
        deleted = state.credential_provider().disconnect()
        state.active_device_authorization = None
        return {"disconnected": True, "credential_deleted": deleted}
    raise ValueError("unsupported control method")


def _write(payload: dict[str, object]) -> None:
    sys.stdout.write(json.dumps(payload, sort_keys=True) + "\n")
    sys.stdout.flush()


def _now_ms() -> int:
    return int(time.time() * 1000)


if __name__ == "__main__":
    main()
