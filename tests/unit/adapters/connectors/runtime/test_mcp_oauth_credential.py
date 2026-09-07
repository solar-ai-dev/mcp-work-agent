from google_work_agent.adapters.connectors.runtime.connector_runtime_registry import (
    ConnectorRuntimeRegistry,
)
from google_work_agent.adapters.connectors.runtime.mcp_oauth_credential import (
    McpOAuthCredentialAdapter,
)
from google_work_agent.adapters.connectors.runtime.stdio_mcp_client import (
    is_control_operation_id,
)
from google_work_agent.ports.connector.connector_failure import (
    ConnectorFailureCode,
    ConnectorOperationFailure,
)
from google_work_agent.ports.connector.mcp_client_port import MCPToolCallResultV1
from google_work_agent.ports.connector.oauth_credential_port import OAuthEnvironment


class _RuntimeHandle:
    pass


class _Client:
    def call_tool(
        self,
        connector_id: str,
        tool_id: str,
        arguments: object,
        timeout_ms: int,
    ) -> MCPToolCallResultV1:
        assert connector_id == "google_workspace"
        assert tool_id == "google.connection.get"
        assert arguments == {}
        assert timeout_ms == 30_000
        return MCPToolCallResultV1(
            schema_version=1,
            tool_id=tool_id,
            transport_status="OK",
            payload={
                "connected": True,
                "credential_state": "CONNECTED",
                "account_id": "google-subject",
                "account_email": "user@example.com",
                "granted_scopes": ["openid"],
                "missing_scopes": [],
                "reauth_required": False,
            },
            error_code=None,
        )


def test_connection_status__preserves_opaque__provider_account_id() -> None:
    registry = ConnectorRuntimeRegistry()
    registry.register("google_workspace", _RuntimeHandle())  # type: ignore[arg-type]
    adapter = McpOAuthCredentialAdapter(
        runtime_registry=registry,
        mcp_client=_Client(),  # type: ignore[arg-type]
    )

    status = adapter.get_connection_status("google_workspace")

    assert status.connection_status == "CONNECTED"
    assert status.account_id == "google-subject"
    assert status.display_email == "user@example.com"


class _GitHubClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, object]] = []

    def call_tool(
        self,
        connector_id: str,
        tool_id: str,
        arguments: object,
        timeout_ms: int,
    ) -> MCPToolCallResultV1:
        assert timeout_ms == 30_000
        self.calls.append((connector_id, tool_id, arguments))
        return MCPToolCallResultV1(
            schema_version=1,
            tool_id=tool_id,
            transport_status="OK",
            payload={
                "schema_version": 1,
                "flow_kind": "DEVICE_CODE",
                "authorization_url": "https://github.com/login/device",
                "verification_uri": "https://github.com/login/device",
                "user_code": "ABCD-EFGH",
                "callback_id": "operation-1",
                "expires_at_ms": 901_000,
                "poll_interval_seconds": 5,
            },
            error_code=None,
        )


def test_github_authorization__uses_device_flow_control__without_token_projection() -> None:
    registry = ConnectorRuntimeRegistry()
    registry.register("github", _RuntimeHandle())  # type: ignore[arg-type]
    client = _GitHubClient()
    adapter = McpOAuthCredentialAdapter(
        runtime_registry=registry,
        mcp_client=client,  # type: ignore[arg-type]
    )

    result = adapter.start_authorization(
        "github",
        OAuthEnvironment.DEVELOPMENT,
        (),
        "operation-1",
    )

    assert result.flow_kind == "DEVICE_CODE"
    assert result.user_code == "ABCD-EFGH"
    assert result.verification_uri == "https://github.com/login/device"
    assert result.poll_interval_seconds == 5
    assert client.calls[0][0:2] == ("github", "github.device_flow.start")
    assert client.calls[0][2] == {
        "environment": "DEVELOPMENT",
        "requested_scopes": [],
        "operation_ref": "operation-1",
    }
    assert "access_token" not in result.__dataclass_fields__


def test_control_operation_classification__is_provider__neutral() -> None:
    assert is_control_operation_id("google.oauth.start") is True
    assert is_control_operation_id("github.device_flow.start") is True
    assert is_control_operation_id("github.connection.get") is True
    assert is_control_operation_id("github_get_issue") is False


class _FailedControlClient:
    def call_tool(
        self,
        connector_id: str,
        tool_id: str,
        arguments: object,
        timeout_ms: int,
    ) -> MCPToolCallResultV1:
        return MCPToolCallResultV1(
            schema_version=1,
            tool_id=tool_id,
            transport_status="ERROR",
            payload=None,
            error_code="CONFIGURATION_ERROR",
        )


def test_oauth_control_failure__configuration_error__raises_typed_connector_failure() -> None:
    registry = ConnectorRuntimeRegistry()
    registry.register("github", _RuntimeHandle())  # type: ignore[arg-type]
    adapter = McpOAuthCredentialAdapter(
        runtime_registry=registry,
        mcp_client=_FailedControlClient(),  # type: ignore[arg-type]
    )

    try:
        adapter.get_connection_status("github")
    except ConnectorOperationFailure as error:
        assert error.code is ConnectorFailureCode.CONFIGURATION_ERROR
        assert error.detail_code == "CONFIGURATION_ERROR"
        assert error.retryable is False
    else:
        raise AssertionError("typed Connector failure was not raised")
