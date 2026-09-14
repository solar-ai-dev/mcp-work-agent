from __future__ import annotations

from google_work_agent.adapters.connectors.github.github.mcp_server.credential_provider import (
    GitHubCredentialProvider,
    GitHubCredentialState,
)
from google_work_agent.adapters.connectors.github.github.mcp_server.oauth_device_flow import (
    GitHubDeviceAuthorization,
    GitHubDeviceFlowClient,
    GitHubDeviceFlowStatus,
)


class _OAuthTransport:
    def __init__(self, *responses: dict[str, object]) -> None:
        self.responses = list(responses)
        self.calls: list[tuple[str, dict[str, str]]] = []

    def post_form(self, url: str, *, form: dict[str, str]) -> dict[str, object]:
        self.calls.append((url, form))
        return self.responses.pop(0)


class _SecretStore:
    def __init__(self, initial: bytes | None = None) -> None:
        self.value = initial
        self.put_values: list[bytes] = []

    def put(self, key: str, secret_bytes: bytes) -> None:
        self.value = secret_bytes
        self.put_values.append(secret_bytes)

    def get(self, key: str) -> bytes | None:
        return self.value

    def delete(self, key: str) -> None:
        self.value = None


def test_reconnect__new_authorization_without_refresh__cannot_restore_old_account() -> None:
    store = _SecretStore(initial=b"previous-account-refresh")
    flow = GitHubDeviceFlowClient(
        client_id="client",
        scope="",
        now_ms=lambda: 0,
        transport=_OAuthTransport({"access_token": "new-account-session-access"}),
    )
    provider = GitHubCredentialProvider(keyring=store, device_flow=flow, now_ms=lambda: 0)
    authorization = GitHubDeviceAuthorization(
        "device", "user", "https://github.com/login/device", 10000, 5
    )
    provider.complete_device_flow(authorization)
    assert store.value is None
    assert provider.get_access_token() == "new-account-session-access"
    restarted = GitHubCredentialProvider(keyring=store, device_flow=flow, now_ms=lambda: 0)
    assert restarted.get_connection_status().connected is False


def test_device_flow__start_and_poll__preserve_github_protocol() -> None:
    now = 1_000
    transport = _OAuthTransport(
        {
            "device_code": "device",
            "user_code": "user",
            "verification_uri": "https://github.com/login/device",
            "expires_in": 900,
            "interval": 7,
        },
        {
            "access_token": "access",
            "expires_in": 28_800,
            "refresh_token": "refresh",
            "refresh_token_expires_in": 15_552_000,
            "scope": "repo, read:user",
        },
    )
    client = GitHubDeviceFlowClient(
        client_id="client", scope="repo", now_ms=lambda: now, transport=transport
    )

    authorization = client.start()
    result = client.poll(authorization)

    assert authorization.interval_seconds == 7
    assert result.status is GitHubDeviceFlowStatus.APPROVED
    assert result.access_token == "access"
    assert result.refresh_token == "refresh"
    assert result.granted_scopes == ("repo", "read:user")
    assert transport.calls[1][1]["grant_type"].endswith(":device_code")


def test_credential_provider__persists_only__refresh_token() -> None:
    store = _SecretStore(initial=b"old-refresh")
    transport = _OAuthTransport(
        {
            "access_token": "new-access",
            "expires_in": 100,
            "refresh_token": "new-refresh",
            "scope": "repo",
        }
    )
    flow = GitHubDeviceFlowClient(
        client_id="client", scope="repo", now_ms=lambda: 1_000, transport=transport
    )
    provider = GitHubCredentialProvider(
        keyring=store,
        device_flow=flow,
        now_ms=lambda: 1_000,
        requested_scopes=("repo",),
    )

    assert provider.get_access_token() == "new-access"
    assert store.put_values == [b"new-refresh"]
    assert b"new-access" not in store.put_values
    assert provider.get_connection_status().granted_scopes == ("repo",)
    assert provider.get_connection_status().credential_state is GitHubCredentialState.CONNECTED


def test_disconnect__clears_keyring__and_memory_state() -> None:
    store = _SecretStore(initial=b"refresh")
    flow = GitHubDeviceFlowClient(
        client_id="client", scope="repo", now_ms=lambda: 1_000, transport=_OAuthTransport()
    )
    provider = GitHubCredentialProvider(keyring=store, device_flow=flow, now_ms=lambda: 1_000)

    assert provider.disconnect() is True
    assert store.value is None
    assert provider.get_connection_status().credential_state is GitHubCredentialState.NOT_CONNECTED
