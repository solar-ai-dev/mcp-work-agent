"""GitHub App (User Access Token, Device Flow) auth boundary -- GitHub MCP-owned only.

Nothing in this module is imported by FastAPI, Application, LangGraph, or
Domain. The refresh token is the only credential ever persisted (via the
injected ``SecretStore`` -- OS Keyring in production); the User Access Token
lives only in this process's memory for the lifetime of the GitHub MCP child
process. No GitHub App client secret is used: Device Flow user-to-server
token issuance and refresh both authenticate with ``client_id`` alone.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol, cast
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from google_work_agent.ports import CredentialState, SecretStore

GITHUB_DEVICE_CODE_ENDPOINT = "https://github.com/login/device/code"
GITHUB_TOKEN_ENDPOINT = "https://github.com/login/oauth/access_token"
GITHUB_DEVICE_GRANT_TYPE = "urn:ietf:params:oauth:grant-type:device_code"
GITHUB_REQUEST_TIMEOUT_SECONDS = 10
DEFAULT_DEVICE_POLL_INTERVAL_SECONDS = 5

GITHUB_KEYRING_SERVICE = "GoogleWorkAgent/GitHub/DEVELOPMENT"
GITHUB_REFRESH_TOKEN_ACCOUNT = "github-app-user-refresh-token"


class GitHubOAuthConfigurationError(RuntimeError):
    """Raised when local GitHub App configuration is incomplete."""

    def __init__(self, safe_code: str) -> None:
        super().__init__(safe_code)
        self.safe_code = safe_code


class GitHubOAuthTransportError(RuntimeError):
    """A network/protocol-level failure talking to GitHub's OAuth endpoints.

    Used for anything that is not one of the well-known Device Flow states
    (unreachable host, malformed body, an unrecognized ``error`` value) so
    callers never have to interpret raw GitHub error strings.
    """

    def __init__(self, safe_code: str) -> None:
        super().__init__(safe_code)
        self.safe_code = safe_code


class GitHubReauthenticationRequired(RuntimeError):
    """Raised when GitHub rejects a stored refresh token (revoked/expired)."""

    def __init__(self, safe_code: str) -> None:
        super().__init__(safe_code)
        self.safe_code = safe_code


class GitHubDeviceFlowStatus(StrEnum):
    """Device Flow states as defined by RFC 8628 / GitHub's implementation."""

    AUTHORIZATION_PENDING = "AUTHORIZATION_PENDING"
    SLOW_DOWN = "SLOW_DOWN"
    APPROVED = "APPROVED"
    EXPIRED = "EXPIRED"
    DENIED = "DENIED"


@dataclass(frozen=True, slots=True)
class GitHubDeviceAuthorization:
    """Result of a device authorization request the user must approve."""

    device_code: str
    user_code: str
    verification_uri: str
    expires_at_ms: int
    interval_seconds: int


@dataclass(frozen=True, slots=True)
class GitHubDeviceFlowPollResult:
    """Result of one poll against the token endpoint during Device Flow."""

    status: GitHubDeviceFlowStatus
    interval_seconds: int | None = None
    access_token: str | None = None
    access_token_expires_at_ms: int | None = None
    refresh_token: str | None = None
    refresh_token_expires_at_ms: int | None = None


@dataclass(frozen=True, slots=True)
class GitHubTokenRefreshResult:
    """A freshly issued User Access Token from the refresh_token grant."""

    access_token: str
    access_token_expires_at_ms: int | None
    refresh_token: str | None
    refresh_token_expires_at_ms: int | None


class GitHubOAuthTransport(Protocol):
    """Minimal boundary for GitHub's OAuth token endpoints (fakeable in tests)."""

    def post_form(self, url: str, *, form: dict[str, str]) -> dict[str, object]:
        """POST an urlencoded form and return the parsed JSON response body."""


class UrllibGitHubOAuthTransport:
    """Real GitHub OAuth transport. The only network calls this module makes."""

    def post_form(self, url: str, *, form: dict[str, str]) -> dict[str, object]:
        request = Request(
            url,
            data=urlencode(form).encode("ascii"),
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "Accept": "application/json",
            },
            method="POST",
        )
        try:
            # nosec B310: fixed GitHub endpoint, not a user-controlled URL.
            with urlopen(request, timeout=GITHUB_REQUEST_TIMEOUT_SECONDS) as response:
                raw_body = response.read().decode("utf-8")
        except HTTPError as error:
            raise GitHubOAuthTransportError("GITHUB_OAUTH_HTTP_ERROR") from error
        except (URLError, TimeoutError) as error:
            raise GitHubOAuthTransportError("GITHUB_OAUTH_UNREACHABLE") from error
        try:
            payload = cast(dict[str, object], json.loads(raw_body))
        except json.JSONDecodeError as error:
            raise GitHubOAuthTransportError("GITHUB_OAUTH_MALFORMED_RESPONSE") from error
        return payload


_DEVICE_FLOW_ERROR_STATUS: dict[str, GitHubDeviceFlowStatus] = {
    "authorization_pending": GitHubDeviceFlowStatus.AUTHORIZATION_PENDING,
    "slow_down": GitHubDeviceFlowStatus.SLOW_DOWN,
    "expired_token": GitHubDeviceFlowStatus.EXPIRED,
    "access_denied": GitHubDeviceFlowStatus.DENIED,
}


class GitHubDeviceFlowClient:
    """Device Flow authorization/polling and refresh_token grant for one GitHub App."""

    def __init__(
        self,
        *,
        client_id: str,
        scope: str,
        now_ms: Callable[[], int],
        transport: GitHubOAuthTransport | None = None,
    ) -> None:
        if not client_id:
            raise GitHubOAuthConfigurationError("GITHUB_APP_CLIENT_ID_MISSING")
        self._client_id = client_id
        self._scope = scope
        self._now_ms = now_ms
        self._transport = transport or UrllibGitHubOAuthTransport()

    def start(self) -> GitHubDeviceAuthorization:
        """Request a device_code/user_code pair the user must approve."""

        payload = self._transport.post_form(
            GITHUB_DEVICE_CODE_ENDPOINT,
            form={"client_id": self._client_id, "scope": self._scope},
        )
        interval = payload.get("interval", DEFAULT_DEVICE_POLL_INTERVAL_SECONDS)
        if not isinstance(interval, int):
            interval = DEFAULT_DEVICE_POLL_INTERVAL_SECONDS
        return GitHubDeviceAuthorization(
            device_code=_require_str(payload, "device_code"),
            user_code=_require_str(payload, "user_code"),
            verification_uri=_require_str(payload, "verification_uri"),
            expires_at_ms=self._now_ms() + _require_int(payload, "expires_in") * 1000,
            interval_seconds=interval,
        )

    def poll(self, authorization: GitHubDeviceAuthorization) -> GitHubDeviceFlowPollResult:
        """Poll once for a completed authorization. Callers own the interval/backoff."""

        if self._now_ms() >= authorization.expires_at_ms:
            return GitHubDeviceFlowPollResult(status=GitHubDeviceFlowStatus.EXPIRED)
        payload = self._transport.post_form(
            GITHUB_TOKEN_ENDPOINT,
            form={
                "client_id": self._client_id,
                "device_code": authorization.device_code,
                "grant_type": GITHUB_DEVICE_GRANT_TYPE,
            },
        )
        return self._interpret_token_response(payload)

    def refresh(self, refresh_token: str) -> GitHubTokenRefreshResult:
        """Exchange a stored refresh token for a new User Access Token."""

        payload = self._transport.post_form(
            GITHUB_TOKEN_ENDPOINT,
            form={
                "client_id": self._client_id,
                "refresh_token": refresh_token,
                "grant_type": "refresh_token",
            },
        )
        result = self._interpret_token_response(payload)
        if result.status is not GitHubDeviceFlowStatus.APPROVED:
            raise GitHubReauthenticationRequired(f"GITHUB_REFRESH_{result.status.value}")
        assert result.access_token is not None
        return GitHubTokenRefreshResult(
            access_token=result.access_token,
            access_token_expires_at_ms=result.access_token_expires_at_ms,
            refresh_token=result.refresh_token,
            refresh_token_expires_at_ms=result.refresh_token_expires_at_ms,
        )

    def _interpret_token_response(self, payload: dict[str, object]) -> GitHubDeviceFlowPollResult:
        error = payload.get("error")
        if isinstance(error, str):
            status = _DEVICE_FLOW_ERROR_STATUS.get(error)
            if status is None:
                raise GitHubOAuthTransportError("GITHUB_OAUTH_UNRECOGNIZED_ERROR")
            interval = payload.get("interval")
            return GitHubDeviceFlowPollResult(
                status=status,
                interval_seconds=interval if isinstance(interval, int) else None,
            )
        access_token = _require_str(payload, "access_token")
        expires_in = payload.get("expires_in")
        access_token_expires_at_ms = (
            self._now_ms() + expires_in * 1000 if isinstance(expires_in, int) else None
        )
        refresh_token = payload.get("refresh_token")
        refresh_token_expires_in = payload.get("refresh_token_expires_in")
        refresh_token_expires_at_ms = (
            self._now_ms() + refresh_token_expires_in * 1000
            if isinstance(refresh_token_expires_in, int)
            else None
        )
        return GitHubDeviceFlowPollResult(
            status=GitHubDeviceFlowStatus.APPROVED,
            access_token=access_token,
            access_token_expires_at_ms=access_token_expires_at_ms,
            refresh_token=refresh_token if isinstance(refresh_token, str) else None,
            refresh_token_expires_at_ms=refresh_token_expires_at_ms,
        )


@dataclass(frozen=True, slots=True)
class GitHubConnectionStatus:
    """Sanitized GitHub connection metadata -- never carries token material."""

    connected: bool
    credential_state: CredentialState
    reauth_required: bool
    last_checked_at_ms: int


class GitHubCredentialProvider:
    """Owns the GitHub App User Access Token lifecycle for the GitHub MCP process.

    The refresh token is the only value persisted, and only through the
    injected ``SecretStore``. The User Access Token is held in this
    instance's memory only and is never returned by ``get_connection_status``.
    """

    def __init__(
        self,
        *,
        keyring: SecretStore,
        device_flow: GitHubDeviceFlowClient,
        now_ms: Callable[[], int],
        keyring_service: str = GITHUB_KEYRING_SERVICE,
        keyring_account: str = GITHUB_REFRESH_TOKEN_ACCOUNT,
    ) -> None:
        self._keyring = keyring
        self._device_flow = device_flow
        self._now_ms = now_ms
        self._keyring_service = keyring_service
        self._keyring_account = keyring_account
        self._access_token: str | None = None
        self._access_token_expires_at_ms: int | None = None
        self._credential_state = (
            CredentialState.CONNECTED
            if self._stored_refresh_token() is not None
            else CredentialState.NOT_CONNECTED
        )
        self._last_checked_at_ms = self._now_ms()

    def start_device_flow(self) -> GitHubDeviceAuthorization:
        return self._device_flow.start()

    def complete_device_flow(
        self, authorization: GitHubDeviceAuthorization
    ) -> GitHubDeviceFlowPollResult:
        """Poll once; adopt and persist tokens only once GitHub reports APPROVED."""

        result = self._device_flow.poll(authorization)
        if result.status is GitHubDeviceFlowStatus.APPROVED:
            assert result.access_token is not None
            self._adopt_tokens(
                access_token=result.access_token,
                access_token_expires_at_ms=result.access_token_expires_at_ms,
                refresh_token=result.refresh_token,
            )
        return result

    def get_access_token(self) -> str:
        """Return a valid User Access Token, refreshing if needed. MCP-internal only."""

        self._ensure_access_token()
        assert self._access_token is not None
        return self._access_token

    def get_connection_status(self) -> GitHubConnectionStatus:
        try:
            self._ensure_access_token()
        except GitHubReauthenticationRequired:
            pass
        self._last_checked_at_ms = self._now_ms()
        return GitHubConnectionStatus(
            connected=self._credential_state is CredentialState.CONNECTED,
            credential_state=self._credential_state,
            reauth_required=self._credential_state is CredentialState.REAUTH_REQUIRED,
            last_checked_at_ms=self._last_checked_at_ms,
        )

    def invalidate_access_token(self) -> None:
        """Discard the cached Access Token after a Provider Adapter sees a live 401.

        Does not touch the stored refresh token or the Keyring -- the next
        ``get_access_token()`` call will simply refresh again.
        """

        self._access_token = None
        self._access_token_expires_at_ms = None

    def disconnect(self) -> bool:
        deleted = self._keyring.delete_secret(
            service=self._keyring_service, account=self._keyring_account
        )
        self._access_token = None
        self._access_token_expires_at_ms = None
        self._credential_state = CredentialState.NOT_CONNECTED
        return deleted

    def _ensure_access_token(self) -> None:
        if self._access_token is not None and (
            self._access_token_expires_at_ms is None
            or self._now_ms() < self._access_token_expires_at_ms
        ):
            return
        refresh_token = self._stored_refresh_token()
        if refresh_token is None:
            self._credential_state = CredentialState.NOT_CONNECTED
            raise GitHubReauthenticationRequired("GITHUB_NOT_CONNECTED")
        try:
            result = self._device_flow.refresh(refresh_token)
        except GitHubReauthenticationRequired:
            self._credential_state = CredentialState.REAUTH_REQUIRED
            self._access_token = None
            self._access_token_expires_at_ms = None
            raise
        self._adopt_tokens(
            access_token=result.access_token,
            access_token_expires_at_ms=result.access_token_expires_at_ms,
            refresh_token=result.refresh_token,
        )

    def _adopt_tokens(
        self,
        *,
        access_token: str,
        access_token_expires_at_ms: int | None,
        refresh_token: str | None,
    ) -> None:
        self._access_token = access_token
        self._access_token_expires_at_ms = access_token_expires_at_ms
        if refresh_token is not None:
            self._keyring.set_secret(
                service=self._keyring_service,
                account=self._keyring_account,
                secret=refresh_token,
            )
        self._credential_state = CredentialState.CONNECTED

    def _stored_refresh_token(self) -> str | None:
        return self._keyring.get_secret(
            service=self._keyring_service, account=self._keyring_account
        )


def _require_str(payload: dict[str, object], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value:
        raise GitHubOAuthTransportError("GITHUB_OAUTH_MALFORMED_RESPONSE")
    return value


def _require_int(payload: dict[str, object], key: str) -> int:
    value = payload.get(key)
    if not isinstance(value, int):
        raise GitHubOAuthTransportError("GITHUB_OAUTH_MALFORMED_RESPONSE")
    return value
