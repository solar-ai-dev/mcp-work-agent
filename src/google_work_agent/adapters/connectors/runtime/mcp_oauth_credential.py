"""Connector OAuth boundary implemented through connector-owned MCP controls."""

from dataclasses import dataclass
from typing import Literal, cast

from google_work_agent.adapters.connectors.runtime.connector_runtime_registry import (
    ConnectorRuntimeRegistry,
)
from google_work_agent.ports.connector.connector_failure import (
    ConnectorFailureCode,
    ConnectorOperationFailure,
)
from google_work_agent.ports.connector.mcp_client_port import JsonValue, MCPClientPort
from google_work_agent.ports.connector.oauth_credential_port import (
    OAuthAuthorizationStart,
    OAuthConnectionMetadata,
    OAuthEnvironment,
    OAuthRevokeResult,
)
from google_work_agent.ports.system.contracts.operational_command_replay import (
    OperationalReconcileResultV1,
)


class McpOAuthCredentialAdapter:
    def __init__(
        self,
        *,
        runtime_registry: ConnectorRuntimeRegistry,
        mcp_client: MCPClientPort,
        timeout_ms: int = 30_000,
    ) -> None:
        self._runtime_registry = runtime_registry
        self._mcp_client = mcp_client
        self._timeout_ms = timeout_ms

    def start_authorization(
        self,
        connector_id: str,
        environment: OAuthEnvironment,
        requested_scopes: tuple[str, ...],
        operation_ref: str,
    ) -> OAuthAuthorizationStart:
        _require_connector_id(connector_id)
        if any(not scope.strip() for scope in requested_scopes) or (
            connector_id == "google_workspace" and not requested_scopes
        ):
            raise ValueError("requested_scopes must contain nonblank values")
        _require_operation_ref(operation_ref)
        controls = _controls(connector_id)
        payload = self._call(
            connector_id,
            controls.start,
            {
                "environment": environment.value,
                "requested_scopes": list(requested_scopes),
                "operation_ref": operation_ref,
            },
        )
        return OAuthAuthorizationStart(
            schema_version=1,
            authorization_url=str(payload["authorization_url"]),
            callback_id=str(payload.get("callback_id", payload.get("flow_id", ""))),
            flow_kind=(
                "DEVICE_CODE" if payload.get("flow_kind") == "DEVICE_CODE" else "AUTHORIZATION_CODE"
            ),
            verification_uri=_optional_string(payload.get("verification_uri")),
            user_code=_optional_string(payload.get("user_code")),
            expires_at_ms=_optional_int(payload.get("expires_at_ms")),
            poll_interval_seconds=_optional_int(payload.get("poll_interval_seconds")),
        )

    def reconcile_authorization_start(
        self, connector_id: str, operation_ref: str
    ) -> OperationalReconcileResultV1:
        _require_connector_id(connector_id)
        _require_operation_ref(operation_ref)
        return self._reconcile(
            connector_id,
            _controls(connector_id).reconcile_start,
            {"operation_ref": operation_ref},
        )

    def refresh_access(self, connector_id: str, account_id: str) -> str:
        _require_connector_id(connector_id)
        _require_account_id(account_id)
        payload = self._call(
            connector_id,
            _controls(connector_id).refresh,
            {"account_id": account_id},
        )
        return str(payload["access_context_handle"])

    def get_connection_status(self, connector_id: str) -> OAuthConnectionMetadata:
        _require_connector_id(connector_id)
        return self._status(
            connector_id,
            self._call(connector_id, _controls(connector_id).status, {}),
        )

    def revoke_connection(
        self,
        connector_id: str,
        account_id: str,
        operation_ref: str,
    ) -> OAuthRevokeResult:
        _require_connector_id(connector_id)
        _require_account_id(account_id)
        _require_operation_ref(operation_ref)
        payload = self._call(
            connector_id,
            _controls(connector_id).disconnect,
            {"account_id": account_id, "operation_ref": operation_ref},
        )
        return OAuthRevokeResult(
            schema_version=1,
            revocation_attempted=bool(payload["revoke_attempted"]),
            local_credential_deleted=bool(payload["credential_deleted"]),
            connection_status=("DISCONNECTED" if bool(payload["disconnected"]) else "UNAVAILABLE"),
        )

    def reconcile_revoke_connection(
        self,
        connector_id: str,
        account_id: str,
        operation_ref: str,
    ) -> OperationalReconcileResultV1:
        _require_connector_id(connector_id)
        _require_account_id(account_id)
        _require_operation_ref(operation_ref)
        return self._reconcile(
            connector_id,
            _controls(connector_id).reconcile_disconnect,
            {"account_id": account_id, "operation_ref": operation_ref},
        )

    def _call(
        self, connector_id: str, method: str, arguments: dict[str, JsonValue]
    ) -> dict[str, JsonValue]:
        self._runtime_registry.resolve(connector_id)
        response = self._mcp_client.call_tool(
            connector_id,
            method,
            arguments,
            self._timeout_ms,
        )
        if response.transport_status != "OK" or not isinstance(response.payload, dict):
            code = {
                "AUTH_REQUIRED": ConnectorFailureCode.AUTH_REQUIRED,
                "PERMISSION_DENIED": ConnectorFailureCode.PERMISSION_DENIED,
                "NOT_FOUND": ConnectorFailureCode.NOT_FOUND,
                "TIMEOUT": ConnectorFailureCode.TIMEOUT,
                "PROCESS_UNAVAILABLE": ConnectorFailureCode.CONNECTION_UNAVAILABLE,
                "CONNECTION_CLOSED": ConnectorFailureCode.CONNECTION_UNAVAILABLE,
                "MALFORMED_RESPONSE": ConnectorFailureCode.MALFORMED_RESPONSE,
                "CONFIGURATION_ERROR": ConnectorFailureCode.CONFIGURATION_ERROR,
            }.get(response.error_code or "", ConnectorFailureCode.UPSTREAM_UNAVAILABLE)
            raise ConnectorOperationFailure(
                code=code,
                detail_code=response.error_code or "OAUTH_MCP_CALL_FAILED",
                retryable=code
                in {
                    ConnectorFailureCode.TIMEOUT,
                    ConnectorFailureCode.CONNECTION_UNAVAILABLE,
                    ConnectorFailureCode.UPSTREAM_UNAVAILABLE,
                },
            )
        return cast(dict[str, JsonValue], response.payload)

    @staticmethod
    def _status(connector_id: str, payload: dict[str, JsonValue]) -> OAuthConnectionMetadata:
        raw_state = str(payload["credential_state"])
        status: Literal[
            "CONNECTING", "CONNECTED", "DISCONNECTED", "REAUTH_REQUIRED", "UNAVAILABLE"
        ] = (
            "CONNECTING"
            if raw_state == "CONNECTING"
            else "CONNECTED"
            if bool(payload["connected"])
            else "REAUTH_REQUIRED"
            if bool(payload["reauth_required"])
            else "UNAVAILABLE"
            if raw_state in {"KEYRING_UNAVAILABLE", "ERROR"}
            else "CONNECTING"
            if raw_state == "CONNECTING"
            else "DISCONNECTED"
        )
        return OAuthConnectionMetadata(
            schema_version=1,
            connector_id=connector_id,
            account_id=_optional_string(payload.get("account_id")),
            display_email=_optional_string(payload.get("account_email")),
            connection_status=status,
            granted_scopes=tuple(
                str(item) for item in cast(list[object], payload.get("granted_scopes", []))
            ),
            missing_required_scopes=tuple(
                str(item) for item in cast(list[object], payload.get("missing_scopes", []))
            ),
            authorization_status=cast(
                Literal["PENDING", "SLOW_DOWN", "APPROVED", "EXPIRED", "DENIED"] | None,
                payload.get("authorization_status")
                if isinstance(payload.get("authorization_status"), str)
                and payload.get("authorization_status")
                in {"PENDING", "SLOW_DOWN", "APPROVED", "EXPIRED", "DENIED"}
                else None,
            ),
            detail_code=_optional_string(payload.get("detail_code")),
        )

    def _reconcile(
        self, connector_id: str, method: str, arguments: dict[str, JsonValue]
    ) -> OperationalReconcileResultV1:
        payload = self._call(connector_id, method, arguments)
        raw_status = str(payload.get("status", ""))
        if raw_status not in {"COMPLETED", "SAFE_TO_RETRY", "UNCERTAIN"}:
            raise RuntimeError("OAUTH_RECONCILE_RESULT_INVALID")
        return OperationalReconcileResultV1(
            status=cast(Literal["COMPLETED", "SAFE_TO_RETRY", "UNCERTAIN"], raw_status),
            result_ref=_optional_string(payload.get("result_ref")),
            bounded_result=payload.get("bounded_result"),
        )


def _optional_string(value: JsonValue) -> str | None:
    return value if isinstance(value, str) and value else None


def _optional_int(value: JsonValue) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


@dataclass(frozen=True, slots=True)
class _OAuthControlMethods:
    start: str
    reconcile_start: str
    refresh: str
    status: str
    disconnect: str
    reconcile_disconnect: str


_CONTROL_METHODS = {
    "google_workspace": _OAuthControlMethods(
        start="google.oauth.start",
        reconcile_start="google.oauth.reconcile_start",
        refresh="google.connection.refresh",
        status="google.connection.get",
        disconnect="google.connection.disconnect",
        reconcile_disconnect="google.connection.reconcile_disconnect",
    ),
    "github": _OAuthControlMethods(
        start="github.device_flow.start",
        reconcile_start="github.device_flow.reconcile_start",
        refresh="github.connection.refresh",
        status="github.connection.get",
        disconnect="github.connection.disconnect",
        reconcile_disconnect="github.connection.reconcile_disconnect",
    ),
}


def _controls(connector_id: str) -> _OAuthControlMethods:
    try:
        return _CONTROL_METHODS[connector_id]
    except KeyError as error:
        raise LookupError(
            f"OAuth controls are not registered for connector: {connector_id}"
        ) from error


def _require_connector_id(value: str) -> None:
    if not value.strip():
        raise ValueError("connector_id is required")


def _require_account_id(value: str) -> None:
    if not value.strip():
        raise ValueError("account_id is required")


def _require_operation_ref(value: str) -> None:
    if not value.strip():
        raise ValueError("operation_ref is required")


__all__ = ["McpOAuthCredentialAdapter"]
