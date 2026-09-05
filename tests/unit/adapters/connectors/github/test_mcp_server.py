from __future__ import annotations

from dataclasses import dataclass

import pytest
from tests.support.claim_context import sign_claim_context

from google_work_agent.adapters.connectors.github.github.mcp_server.composition import (
    GitHubMcpServerState,
)
from google_work_agent.adapters.connectors.github.github.mcp_server.credential_provider import (
    GitHubCredentialState,
    GitHubConnectionStatus,
)
from google_work_agent.adapters.connectors.github.github.mcp_server.dispatch_tool import (
    ToolNotAvailableError,
    dispatch_control,
    dispatch_github_tool,
)
from google_work_agent.adapters.connectors.github.github.mcp_server.entrypoint import (
    dispatch_request,
)
from google_work_agent.adapters.connectors.github.github.mcp_server.oauth_device_flow import (
    GitHubDeviceAuthorization,
    GitHubDeviceFlowPollResult,
    GitHubDeviceFlowStatus,
)
from google_work_agent.adapters.connectors.github.github.mcp_server.validate_claim_context import (
    GitHubClaimError,
)
from google_work_agent.domain.canonical import calculate_canonical_json_hash


@dataclass
class _Operation:
    tool_id: str
    calls: int = 0

    def execute(self, arguments: dict[str, object]) -> dict[str, object]:
        self.calls += 1
        return {"arguments": arguments}


def _write_state() -> tuple[GitHubMcpServerState, _Operation]:
    operation = _Operation("github_create_issue")
    state = GitHubMcpServerState(
        operations={operation.tool_id: operation},
        now_ms=lambda: 1_000,
    )
    state.service_instance_id = "service-1"
    state.session_key = "11" * 32
    return state, operation


def _write_arguments(state: GitHubMcpServerState, **overrides: object) -> dict[str, object]:
    execution_arguments: dict[str, object] = {
        "repository": "acme/repo",
        "title": "safe issue",
        "recovery_fingerprint": "fingerprint-1",
    }
    claim: dict[str, object] = {
        "claim_version": 2,
        "connector_id": "github",
        "service_instance_id": "service-1",
        "mcp_process_instance_id": state.process_instance_id,
        "action_id": "action-1",
        "approval_id": "approval-1",
        "execution_attempt_id": "attempt-1",
        "tool_name": "github_create_issue",
        "approval_arguments_hash": "a" * 64,
        "execution_arguments_hash": calculate_canonical_json_hash(execution_arguments),
        "issued_at_ms": 900,
        "expires_at_ms": 1_100,
        "nonce": "nonce-1",
        **overrides,
    }
    assert state.session_key is not None
    claim["signature"] = sign_claim_context(state.session_key, claim)
    return {**execution_arguments, "claim_context": claim}


def test_dispatch__is_owned__by_connector_local_operation_map() -> None:
    operation = _Operation("github_get_issue")
    state = GitHubMcpServerState(operations={operation.tool_id: operation})

    result = dispatch_github_tool(
        state,
        tool_name="github_get_issue",
        arguments={"repository": "acme/repo", "issue_number": 7},
    )

    assert result["arguments"]["issue_number"] == 7
    with pytest.raises(ToolNotAvailableError):
        dispatch_github_tool(state, tool_name="google_get_task", arguments={})


def test_entrypoint_protocol_envelope__lists_only__composed_tools() -> None:
    tool_ids = (
        "github_list_issues",
        "github_get_issue",
        "github_create_issue",
        "github_update_issue",
        "github_close_issue",
        "github_reopen_issue",
    )
    state = GitHubMcpServerState(
        operations={tool_id: _Operation(tool_id) for tool_id in tool_ids}
    )

    assert dispatch_request(state, {"type": "list_tools"}) == {
        "tool_names": sorted(tool_ids)
    }


def test_handshake__preserves_process__identity() -> None:
    state = GitHubMcpServerState()
    response = dispatch_request(
        state,
        {
            "type": "handshake",
            "service_instance_id": "service-1",
            "session_key": "00" * 32,
        },
    )

    assert response == {"process_instance_id": state.process_instance_id}
    assert state.service_instance_id == "service-1"


def test_valid_github_claim__mutates_once__and_rejects_nonce_replay() -> None:
    state, operation = _write_state()
    arguments = _write_arguments(state)

    dispatch_github_tool(state, tool_name="github_create_issue", arguments=arguments)
    with pytest.raises(GitHubClaimError, match="CLAIM_TOKEN_REUSED"):
        dispatch_github_tool(state, tool_name="github_create_issue", arguments=arguments)

    assert operation.calls == 1


@pytest.mark.parametrize(
    ("override", "code"),
    [
        ({"connector_id": "google_workspace"}, "CLAIM_CONNECTOR_MISMATCH"),
        ({"mcp_process_instance_id": "other-process"}, "CLAIM_PROCESS_INSTANCE_MISMATCH"),
        ({"service_instance_id": "other-service"}, "CLAIM_SERVICE_INSTANCE_MISMATCH"),
        ({"tool_name": "github_close_issue"}, "CLAIM_TOOL_MISMATCH"),
        ({"action_id": ""}, "CLAIM_MALFORMED"),
        ({"expires_at_ms": 900}, "CLAIM_TTL_EXCEEDED"),
        ({"execution_arguments_hash": "b" * 64}, "CLAIM_ARGUMENTS_MISMATCH"),
    ],
)
def test_invalid_claim_binding__is_rejected__before_mutation(
    override: dict[str, object], code: str
) -> None:
    state, operation = _write_state()

    with pytest.raises(GitHubClaimError, match=code):
        dispatch_github_tool(
            state,
            tool_name="github_create_issue",
            arguments=_write_arguments(state, **override),
        )

    assert operation.calls == 0


def test_invalid_claim_signature__is_rejected__before_mutation() -> None:
    state, operation = _write_state()
    arguments = _write_arguments(state)
    claim = arguments["claim_context"]
    assert isinstance(claim, dict)
    claim["signature"] = "00" * 32

    with pytest.raises(GitHubClaimError, match="CLAIM_INVALID_SIGNATURE"):
        dispatch_github_tool(
            state,
            tool_name="github_create_issue",
            arguments=arguments,
        )

    assert operation.calls == 0


def test_failed_claim_validation__does_not_consume__nonce() -> None:
    state, operation = _write_state()

    with pytest.raises(GitHubClaimError, match="CLAIM_ARGUMENTS_MISMATCH"):
        dispatch_github_tool(
            state,
            tool_name="github_create_issue",
            arguments=_write_arguments(
                state,
                execution_arguments_hash="b" * 64,
            ),
        )

    dispatch_github_tool(
        state,
        tool_name="github_create_issue",
        arguments=_write_arguments(state),
    )
    assert operation.calls == 1


class _DeviceCredentialProvider:
    def __init__(self, now_ms: object) -> None:
        self.now_ms = now_ms
        self.poll_results = [
            GitHubDeviceFlowPollResult(GitHubDeviceFlowStatus.AUTHORIZATION_PENDING),
            GitHubDeviceFlowPollResult(GitHubDeviceFlowStatus.SLOW_DOWN),
            GitHubDeviceFlowPollResult(
                GitHubDeviceFlowStatus.APPROVED,
                access_token="memory-only-token",
            ),
        ]
        self.poll_count = 0
        self.connected = False

    def start_device_flow(self) -> GitHubDeviceAuthorization:
        return GitHubDeviceAuthorization(
            device_code="device",
            user_code="ABCD-EFGH",
            verification_uri="https://github.com/login/device",
            expires_at_ms=900_000,
            interval_seconds=5,
        )

    def complete_device_flow(
        self, _authorization: GitHubDeviceAuthorization
    ) -> GitHubDeviceFlowPollResult:
        result = self.poll_results[self.poll_count]
        self.poll_count += 1
        self.connected = result.status is GitHubDeviceFlowStatus.APPROVED
        return result

    def get_connection_status(self) -> GitHubConnectionStatus:
        return GitHubConnectionStatus(
            connected=self.connected,
            credential_state=(
                GitHubCredentialState.CONNECTED
                if self.connected
                else GitHubCredentialState.NOT_CONNECTED
            ),
            reauth_required=False,
            last_checked_at_ms=0,
            granted_scopes=("repo",),
            missing_required_scopes=(),
        )


def test_device_flow_status_polling__preserves_interval__and_slow_down_backoff() -> None:
    now = [0]
    provider = _DeviceCredentialProvider(lambda: now[0])
    state = GitHubMcpServerState(
        credential_provider=provider,  # type: ignore[arg-type]
        api_client=type(
            "AccountApi",
            (),
            {"get": lambda _self, _url: {"id": 42, "login": "octocat", "email": None}},
        )(),  # type: ignore[arg-type]
        operations={},
        now_ms=lambda: now[0],
    )

    started = dispatch_control(
        state,
        method="github.device_flow.start",
        arguments={"operation_ref": "operation-1"},
    )
    assert started["flow_kind"] == "DEVICE_CODE"

    dispatch_control(state, method="github.connection.get")
    assert provider.poll_count == 0
    now[0] = 5_000
    dispatch_control(state, method="github.connection.get")
    assert provider.poll_count == 1
    now[0] = 10_000
    dispatch_control(state, method="github.connection.get")
    assert provider.poll_count == 2
    now[0] = 19_999
    dispatch_control(state, method="github.connection.get")
    assert provider.poll_count == 2
    now[0] = 20_000
    status = dispatch_control(state, method="github.connection.get")

    assert provider.poll_count == 3
    assert status["connected"] is True
    assert status["account_id"] == "github:42"
    assert status["account_email"] == "octocat"
    assert status["granted_scopes"] == ["repo"]
    assert state.active_device_authorization is None
