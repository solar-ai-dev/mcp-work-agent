from __future__ import annotations

import pytest

from google_work_agent.mcp.github_auth import (
    GITHUB_KEYRING_SERVICE,
    GITHUB_REFRESH_TOKEN_ACCOUNT,
    GitHubConnectionStatus,
    GitHubCredentialProvider,
    GitHubDeviceAuthorization,
    GitHubDeviceFlowClient,
    GitHubDeviceFlowStatus,
    GitHubOAuthConfigurationError,
    GitHubOAuthTransportError,
    GitHubReauthenticationRequired,
)
from google_work_agent.ports import CredentialState
from tests.support.fakes.clock import FakeClock
from tests.support.fakes.keyring import FakeKeyring


class _FakeGitHubOAuthTransport:
    """Programmable stub for GitHub's two OAuth token endpoints."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, str]]] = []
        self._queued: dict[str, list[dict[str, object]]] = {}

    def queue(self, url: str, response: dict[str, object]) -> None:
        self._queued.setdefault(url, []).append(response)

    def post_form(self, url: str, *, form: dict[str, str]) -> dict[str, object]:
        self.calls.append((url, form))
        queued = self._queued.get(url)
        if not queued:
            raise AssertionError(f"no queued response for {url}")
        return queued.pop(0)


DEVICE_CODE_URL = "https://github.com/login/device/code"
TOKEN_URL = "https://github.com/login/oauth/access_token"


def _client(transport: _FakeGitHubOAuthTransport, clock: FakeClock) -> GitHubDeviceFlowClient:
    return GitHubDeviceFlowClient(
        client_id="Iv1.test-app",
        scope="",
        now_ms=clock.now_ms,
        transport=transport,
    )


# --- Device Flow -------------------------------------------------------


def test_device_flow_start_returns_authorization_from_device_code_response() -> None:
    transport = _FakeGitHubOAuthTransport()
    clock = FakeClock(1_000_000)
    transport.queue(
        DEVICE_CODE_URL,
        {
            "device_code": "devcode-1",
            "user_code": "ABCD-1234",
            "verification_uri": "https://github.com/login/device",
            "expires_in": 900,
            "interval": 5,
        },
    )

    authorization = _client(transport, clock).start()

    assert authorization.user_code == "ABCD-1234"
    assert authorization.verification_uri == "https://github.com/login/device"
    assert authorization.expires_at_ms == 1_000_000 + 900_000
    assert authorization.interval_seconds == 5


def test_device_flow_start_rejects_malformed_response() -> None:
    transport = _FakeGitHubOAuthTransport()
    transport.queue(DEVICE_CODE_URL, {"user_code": "ABCD-1234"})

    with pytest.raises(GitHubOAuthTransportError):
        _client(transport, FakeClock()).start()


def test_device_flow_poll_reports_authorization_pending() -> None:
    transport = _FakeGitHubOAuthTransport()
    transport.queue(TOKEN_URL, {"error": "authorization_pending"})
    authorization = _authorization(expires_at_ms=900_000)

    result = _client(transport, FakeClock()).poll(authorization)

    assert result.status is GitHubDeviceFlowStatus.AUTHORIZATION_PENDING
    assert result.access_token is None


def test_device_flow_poll_reports_slow_down_with_updated_interval() -> None:
    transport = _FakeGitHubOAuthTransport()
    transport.queue(TOKEN_URL, {"error": "slow_down", "interval": 10})
    authorization = _authorization(expires_at_ms=900_000)

    result = _client(transport, FakeClock()).poll(authorization)

    assert result.status is GitHubDeviceFlowStatus.SLOW_DOWN
    assert result.interval_seconds == 10


def test_device_flow_poll_reports_denied() -> None:
    transport = _FakeGitHubOAuthTransport()
    transport.queue(TOKEN_URL, {"error": "access_denied"})
    authorization = _authorization(expires_at_ms=900_000)

    result = _client(transport, FakeClock()).poll(authorization)

    assert result.status is GitHubDeviceFlowStatus.DENIED


def test_device_flow_poll_expires_locally_without_a_provider_call() -> None:
    transport = _FakeGitHubOAuthTransport()
    clock = FakeClock(2_000_000)
    authorization = GitHubDeviceAuthorization(
        device_code="devcode-1",
        user_code="ABCD-1234",
        verification_uri="https://github.com/login/device",
        expires_at_ms=1_000_000,
        interval_seconds=5,
    )

    result = _client(transport, clock).poll(authorization)

    assert result.status is GitHubDeviceFlowStatus.EXPIRED
    assert transport.calls == []


def test_device_flow_poll_succeeds_and_returns_tokens() -> None:
    transport = _FakeGitHubOAuthTransport()
    clock = FakeClock(1_000_000)
    transport.queue(
        TOKEN_URL,
        {
            "access_token": "user-access-token-value",
            "expires_in": 28_800,
            "refresh_token": "refresh-token-value",
            "refresh_token_expires_in": 15_811_200,
        },
    )
    authorization = _authorization(expires_at_ms=2_000_000)

    result = _client(transport, clock).poll(authorization)

    assert result.status is GitHubDeviceFlowStatus.APPROVED
    assert result.access_token == "user-access-token-value"
    assert result.access_token_expires_at_ms == 1_000_000 + 28_800_000
    assert result.refresh_token == "refresh-token-value"
    assert result.refresh_token_expires_at_ms == 1_000_000 + 15_811_200_000


def test_device_flow_poll_rejects_unrecognized_provider_error() -> None:
    transport = _FakeGitHubOAuthTransport()
    transport.queue(TOKEN_URL, {"error": "incorrect_client_credentials"})
    authorization = _authorization(expires_at_ms=900_000)

    with pytest.raises(GitHubOAuthTransportError):
        _client(transport, FakeClock()).poll(authorization)


def _authorization(*, expires_at_ms: int) -> GitHubDeviceAuthorization:
    return GitHubDeviceAuthorization(
        device_code="devcode-1",
        user_code="ABCD-1234",
        verification_uri="https://github.com/login/device",
        expires_at_ms=expires_at_ms,
        interval_seconds=5,
    )


# --- Credential Provider -------------------------------------------------


def test_credential_provider_reports_not_connected_without_stored_refresh_token() -> None:
    provider = _provider(FakeKeyring(), _FakeGitHubOAuthTransport(), FakeClock())

    status = provider.get_connection_status()

    assert status.connected is False
    assert status.credential_state is CredentialState.NOT_CONNECTED
    assert status.reauth_required is False


def test_credential_provider_loads_connected_state_from_existing_keyring_entry() -> None:
    keyring = FakeKeyring()
    keyring.set_secret(
        service=GITHUB_KEYRING_SERVICE,
        account=GITHUB_REFRESH_TOKEN_ACCOUNT,
        secret="existing-refresh-token",
    )
    transport = _FakeGitHubOAuthTransport()
    clock = FakeClock(1_000_000)
    transport.queue(
        TOKEN_URL,
        {"access_token": "fresh-access-token", "expires_in": 28_800},
    )

    status = _provider(keyring, transport, clock).get_connection_status()

    assert status.connected is True
    assert status.credential_state is CredentialState.CONNECTED


def test_credential_provider_caches_access_token_in_memory_without_a_second_refresh() -> None:
    keyring = FakeKeyring()
    keyring.set_secret(
        service=GITHUB_KEYRING_SERVICE,
        account=GITHUB_REFRESH_TOKEN_ACCOUNT,
        secret="existing-refresh-token",
    )
    transport = _FakeGitHubOAuthTransport()
    clock = FakeClock(1_000_000)
    transport.queue(
        TOKEN_URL,
        {"access_token": "fresh-access-token", "expires_in": 28_800},
    )
    provider = _provider(keyring, transport, clock)

    provider.get_connection_status()
    token = provider.get_access_token()

    assert token == "fresh-access-token"
    assert len(transport.calls) == 1


def test_credential_provider_never_persists_the_access_token() -> None:
    keyring = FakeKeyring()
    transport = _FakeGitHubOAuthTransport()
    clock = FakeClock(1_000_000)
    transport.queue(
        DEVICE_CODE_URL,
        {
            "device_code": "devcode-1",
            "user_code": "ABCD-1234",
            "verification_uri": "https://github.com/login/device",
            "expires_in": 900,
            "interval": 5,
        },
    )
    transport.queue(
        TOKEN_URL,
        {
            "access_token": "user-access-token-value",
            "expires_in": 28_800,
            "refresh_token": "rotated-refresh-token",
            "refresh_token_expires_in": 15_811_200,
        },
    )
    provider = _provider(keyring, transport, clock)

    authorization = provider.start_device_flow()
    provider.complete_device_flow(authorization)

    stored_values = list(keyring._secrets.values())  # noqa: SLF001 - isolation assertion
    assert stored_values == ["rotated-refresh-token"]
    assert "user-access-token-value" not in stored_values
    assert provider.get_access_token() == "user-access-token-value"


def test_credential_provider_refresh_failure_maps_to_reauth_required() -> None:
    keyring = FakeKeyring()
    keyring.set_secret(
        service=GITHUB_KEYRING_SERVICE,
        account=GITHUB_REFRESH_TOKEN_ACCOUNT,
        secret="revoked-refresh-token",
    )
    transport = _FakeGitHubOAuthTransport()
    transport.queue(TOKEN_URL, {"error": "access_denied"})
    provider = _provider(keyring, transport, FakeClock())

    status = provider.get_connection_status()

    assert status.connected is False
    assert status.credential_state is CredentialState.REAUTH_REQUIRED
    assert status.reauth_required is True


def test_credential_provider_get_access_token_raises_when_revoked() -> None:
    keyring = FakeKeyring()
    keyring.set_secret(
        service=GITHUB_KEYRING_SERVICE,
        account=GITHUB_REFRESH_TOKEN_ACCOUNT,
        secret="revoked-refresh-token",
    )
    transport = _FakeGitHubOAuthTransport()
    transport.queue(TOKEN_URL, {"error": "access_denied"})
    provider = _provider(keyring, transport, FakeClock())

    with pytest.raises(GitHubReauthenticationRequired):
        provider.get_access_token()


def test_credential_provider_disconnect_clears_keyring_and_memory() -> None:
    keyring = FakeKeyring()
    keyring.set_secret(
        service=GITHUB_KEYRING_SERVICE,
        account=GITHUB_REFRESH_TOKEN_ACCOUNT,
        secret="existing-refresh-token",
    )
    provider = _provider(keyring, _FakeGitHubOAuthTransport(), FakeClock())

    deleted = provider.disconnect()

    assert deleted is True
    assert provider.get_connection_status().credential_state is CredentialState.NOT_CONNECTED


def test_missing_client_id_raises_configuration_error() -> None:
    with pytest.raises(GitHubOAuthConfigurationError):
        GitHubDeviceFlowClient(client_id="", scope="", now_ms=FakeClock().now_ms)


def _provider(
    keyring: FakeKeyring,
    transport: _FakeGitHubOAuthTransport,
    clock: FakeClock,
) -> GitHubCredentialProvider:
    device_flow = _client(transport, clock)
    return GitHubCredentialProvider(keyring=keyring, device_flow=device_flow, now_ms=clock.now_ms)


# --- Secret isolation ----------------------------------------------------


def test_connection_status_never_carries_token_fields() -> None:
    field_names = set(GitHubConnectionStatus.__dataclass_fields__)

    assert "access_token" not in field_names
    assert "refresh_token" not in field_names


def test_reauthentication_error_message_never_contains_the_refresh_token() -> None:
    keyring = FakeKeyring()
    keyring.set_secret(
        service=GITHUB_KEYRING_SERVICE,
        account=GITHUB_REFRESH_TOKEN_ACCOUNT,
        secret="super-secret-refresh-token-value",
    )
    transport = _FakeGitHubOAuthTransport()
    transport.queue(TOKEN_URL, {"error": "access_denied"})
    provider = _provider(keyring, transport, FakeClock())

    with pytest.raises(GitHubReauthenticationRequired) as captured:
        provider.get_access_token()

    assert "super-secret-refresh-token-value" not in str(captured.value)


def test_fake_keyring_access_log_never_contains_secret_values() -> None:
    keyring = FakeKeyring()
    transport = _FakeGitHubOAuthTransport()
    clock = FakeClock(1_000_000)
    transport.queue(
        DEVICE_CODE_URL,
        {
            "device_code": "devcode-1",
            "user_code": "ABCD-1234",
            "verification_uri": "https://github.com/login/device",
            "expires_in": 900,
            "interval": 5,
        },
    )
    transport.queue(
        TOKEN_URL,
        {
            "access_token": "user-access-token-value",
            "expires_in": 28_800,
            "refresh_token": "rotated-refresh-token",
            "refresh_token_expires_in": 15_811_200,
        },
    )
    provider = _provider(keyring, transport, clock)

    authorization = provider.start_device_flow()
    provider.complete_device_flow(authorization)

    for entry in keyring.access_log:
        assert "rotated-refresh-token" not in entry
        assert "user-access-token-value" not in entry
