"""GitHub MCP tool and OAuth control-call dispatch."""

from __future__ import annotations

from dataclasses import replace

from .composition import GitHubMcpServerState
from .oauth_device_flow import GitHubOAuthConfigurationError
from .project_registry import WRITE_TOOL_IDS
from .validate_claim_context import validate_github_claim_context


class ToolNotAvailableError(RuntimeError):
    pass


class ControlCallError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def dispatch_github_tool(
    state: GitHubMcpServerState,
    *,
    tool_name: str,
    arguments: dict[str, object],
) -> dict[str, object]:
    if tool_name == "search_by_recovery_fingerprint":
        return state.recovery_search().execute(arguments)
    operation = state.operations().get(tool_name)
    if operation is None:
        raise ToolNotAvailableError(tool_name)
    if tool_name not in WRITE_TOOL_IDS:
        return operation.execute(arguments)
    claim_context = arguments.get("claim_context")
    execution_arguments = {key: value for key, value in arguments.items() if key != "claim_context"}
    if tool_name == "github_create_issue" and not isinstance(
        execution_arguments.get("recovery_fingerprint"), str
    ):
        from .validate_claim_context import GitHubClaimError

        raise GitHubClaimError("RECOVERY_FINGERPRINT_MISSING")
    validate_github_claim_context(
        state,
        tool_name=tool_name,
        claim_context=claim_context,
        execution_arguments=execution_arguments,
    )
    return operation.execute(execution_arguments)


def dispatch_control(
    state: GitHubMcpServerState,
    *,
    method: str,
    arguments: dict[str, object] | None = None,
) -> dict[str, object]:
    arguments = arguments or {}
    if method == "github.repositories.list":
        return state.repository_listing().execute(arguments)
    if method == "github.connection.get":
        try:
            _poll_active_device_flow(state)
            if state.active_device_authorization is not None:
                # Reauthorization must not refresh an old account/client credential
                # while waiting for the new authorization to complete.
                return {
                    "connected": False,
                    "credential_state": "CONNECTING",
                    "reauth_required": False,
                    "last_checked_at_ms": state.now_ms(),
                    "account_id": None,
                    "account_email": None,
                    "granted_scopes": [],
                    "missing_scopes": [],
                    "authorization_status": state.device_authorization_status,
                }
            status = state.credential_provider().get_connection_status()
        except GitHubOAuthConfigurationError as error:
            return {
                "connected": False,
                "credential_state": "ERROR",
                "reauth_required": False,
                "last_checked_at_ms": state.now_ms(),
                "account_id": None,
                "account_email": None,
                "granted_scopes": [],
                "missing_scopes": [],
                "detail_code": error.safe_code,
            }
        connecting = state.active_device_authorization is not None
        account_id = None
        account_email = None
        if status.connected:
            profile = state.api_client().get("https://api.github.com/user")
            if not isinstance(profile, dict):
                raise ControlCallError("MALFORMED_RESPONSE", "GITHUB_ACCOUNT_INVALID")
            raw_id = profile.get("id")
            login = profile.get("login")
            if not isinstance(raw_id, int) or not isinstance(login, str) or not login:
                raise ControlCallError("MALFORMED_RESPONSE", "GITHUB_ACCOUNT_INVALID")
            account_id = f"github:{raw_id}"
            account_email = login
        return {
            "connected": status.connected,
            "credential_state": ("CONNECTING" if connecting else status.credential_state.value),
            "reauth_required": status.reauth_required,
            "last_checked_at_ms": status.last_checked_at_ms,
            "account_id": account_id,
            "account_email": account_email,
            "granted_scopes": list(status.granted_scopes),
            "missing_scopes": list(status.missing_required_scopes),
            "authorization_status": state.device_authorization_status,
        }
    if method == "github.device_flow.start":
        operation_ref = str(arguments.get("operation_ref", "")).strip()
        if not operation_ref:
            raise ControlCallError("INVALID_ARGUMENT", "OPERATION_REF_REQUIRED")
        authorization = state.credential_provider().start_device_flow()
        state.active_device_authorization = authorization
        state.device_authorization_status = "PENDING"
        state.active_device_operation_ref = operation_ref
        state.next_device_poll_at_ms = state.now_ms() + authorization.interval_seconds * 1000
        payload = {
            "schema_version": 1,
            "flow_kind": "DEVICE_CODE",
            "authorization_url": authorization.verification_uri,
            "callback_id": operation_ref,
            "user_code": authorization.user_code,
            "verification_uri": authorization.verification_uri,
            "expires_at_ms": authorization.expires_at_ms,
            "poll_interval_seconds": authorization.interval_seconds,
        }
        state.operational_results[operation_ref] = payload
        return payload
    if method == "github.device_flow.poll":
        active_authorization = state.active_device_authorization
        if active_authorization is None:
            raise ControlCallError("NOT_FOUND", "NO_ACTIVE_DEVICE_FLOW")
        _poll_active_device_flow(state)
        return {
            "status": state.device_authorization_status or "PENDING",
            "interval_seconds": (
                None
                if state.active_device_authorization is None
                else state.active_device_authorization.interval_seconds
            ),
        }
    if method == "github.device_flow.reconcile_start":
        operation_ref = str(arguments.get("operation_ref", ""))
        bounded_result = state.operational_results.get(operation_ref)
        return {
            "status": "COMPLETED" if bounded_result is not None else "SAFE_TO_RETRY",
            "result_ref": operation_ref if bounded_result is not None else None,
            "bounded_result": bounded_result,
        }
    if method == "github.connection.refresh":
        state.credential_provider().get_access_token()
        return {"access_context_handle": f"{state.process_instance_id}:github"}
    if method == "github.connection.disconnect":
        deleted = state.credential_provider().disconnect()
        state.active_device_authorization = None
        state.active_device_operation_ref = None
        state.next_device_poll_at_ms = None
        state.device_authorization_status = None
        operation_ref = str(arguments.get("operation_ref", ""))
        payload = {
            "revoke_attempted": False,
            "disconnected": True,
            "credential_deleted": deleted,
        }
        if operation_ref:
            state.operational_results[operation_ref] = payload
        return payload
    if method == "github.connection.reconcile_disconnect":
        operation_ref = str(arguments.get("operation_ref", ""))
        bounded_result = state.operational_results.get(operation_ref)
        return {
            "status": "COMPLETED" if bounded_result is not None else "SAFE_TO_RETRY",
            "result_ref": operation_ref if bounded_result is not None else None,
            "bounded_result": bounded_result,
        }
    raise ValueError("unsupported control method")


def _poll_active_device_flow(state: GitHubMcpServerState) -> None:
    authorization = state.active_device_authorization
    if authorization is None:
        return
    if state.now_ms() >= authorization.expires_at_ms:
        _update_poll_state(state, "EXPIRED", None)
        return
    if state.next_device_poll_at_ms is not None and state.now_ms() < state.next_device_poll_at_ms:
        return
    result = state.credential_provider().complete_device_flow(authorization)
    _update_poll_state(state, result.status.value, result.interval_seconds)


def _update_poll_state(
    state: GitHubMcpServerState,
    status: str,
    interval_seconds: int | None,
) -> None:
    authorization = state.active_device_authorization
    if authorization is None:
        return
    state.device_authorization_status = "PENDING" if status == "AUTHORIZATION_PENDING" else status
    if status in {"APPROVED", "EXPIRED", "DENIED"}:
        state.active_device_authorization = None
        state.active_device_operation_ref = None
        state.next_device_poll_at_ms = None
        return
    next_interval = interval_seconds or authorization.interval_seconds
    if status == "SLOW_DOWN" and interval_seconds is None:
        next_interval += 5
    next_interval = max(authorization.interval_seconds, next_interval)
    state.active_device_authorization = replace(authorization, interval_seconds=next_interval)
    state.next_device_poll_at_ms = state.now_ms() + next_interval * 1000
