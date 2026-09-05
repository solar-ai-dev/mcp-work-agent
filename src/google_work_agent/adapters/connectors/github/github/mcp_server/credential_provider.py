"""GitHub refresh-token persistence and in-memory access-token lifecycle."""

from __future__ import annotations

from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass
from enum import StrEnum

from google_work_agent.ports.keyring.secret_store_port import SecretStorePort

from .oauth_device_flow import (
    GitHubDeviceAuthorization,
    GitHubDeviceFlowClient,
    GitHubDeviceFlowPollResult,
    GitHubDeviceFlowStatus,
    GitHubReauthenticationRequired,
)

GITHUB_REFRESH_TOKEN_ACCOUNT = "github-app-user-refresh-token"


class GitHubCredentialState(StrEnum):
    NOT_CONNECTED = "NOT_CONNECTED"
    CONNECTED = "CONNECTED"
    REAUTH_REQUIRED = "REAUTH_REQUIRED"


@dataclass(frozen=True, slots=True)
class GitHubConnectionStatus:
    connected: bool
    credential_state: GitHubCredentialState
    reauth_required: bool
    last_checked_at_ms: int
    granted_scopes: tuple[str, ...] = ()
    missing_required_scopes: tuple[str, ...] = ()


class GitHubCredentialProvider:
    def __init__(
        self,
        *,
        keyring: SecretStorePort,
        device_flow: GitHubDeviceFlowClient,
        now_ms: Callable[[], int],
        keyring_account: str = GITHUB_REFRESH_TOKEN_ACCOUNT,
        requested_scopes: tuple[str, ...] = (),
    ) -> None:
        self._keyring = keyring
        self._device_flow = device_flow
        self._now_ms = now_ms
        self._keyring_account = keyring_account
        self._requested_scopes = requested_scopes
        self._granted_scopes: tuple[str, ...] = ()
        self._access_token: str | None = None
        self._access_token_expires_at_ms: int | None = None
        self._credential_state = (
            GitHubCredentialState.CONNECTED
            if self._stored_refresh_token() is not None
            else GitHubCredentialState.NOT_CONNECTED
        )
        self._last_checked_at_ms = self._now_ms()

    def start_device_flow(self) -> GitHubDeviceAuthorization:
        return self._device_flow.start()

    def complete_device_flow(
        self, authorization: GitHubDeviceAuthorization
    ) -> GitHubDeviceFlowPollResult:
        result = self._device_flow.poll(authorization)
        if result.status is GitHubDeviceFlowStatus.APPROVED:
            assert result.access_token is not None
            self._adopt_tokens(
                access_token=result.access_token,
                access_token_expires_at_ms=result.access_token_expires_at_ms,
                refresh_token=result.refresh_token,
                granted_scopes=result.granted_scopes,
            )
        return result

    def get_access_token(self) -> str:
        self._ensure_access_token()
        assert self._access_token is not None
        return self._access_token

    def get_connection_status(self) -> GitHubConnectionStatus:
        with suppress(GitHubReauthenticationRequired):
            self._ensure_access_token()
        self._last_checked_at_ms = self._now_ms()
        return GitHubConnectionStatus(
            connected=self._credential_state is GitHubCredentialState.CONNECTED,
            credential_state=self._credential_state,
            reauth_required=self._credential_state is GitHubCredentialState.REAUTH_REQUIRED,
            last_checked_at_ms=self._last_checked_at_ms,
            granted_scopes=self._granted_scopes,
            missing_required_scopes=tuple(
                scope for scope in self._requested_scopes if scope not in self._granted_scopes
            ),
        )

    def invalidate_access_token(self) -> None:
        self._access_token = None
        self._access_token_expires_at_ms = None

    def disconnect(self) -> bool:
        deleted = self._stored_refresh_token() is not None
        self._keyring.delete(self._keyring_account)
        self._access_token = None
        self._access_token_expires_at_ms = None
        self._credential_state = GitHubCredentialState.NOT_CONNECTED
        self._granted_scopes = ()
        return deleted

    def _ensure_access_token(self) -> None:
        if self._access_token is not None and (
            self._access_token_expires_at_ms is None
            or self._now_ms() < self._access_token_expires_at_ms
        ):
            return
        refresh_token = self._stored_refresh_token()
        if refresh_token is None:
            self._credential_state = GitHubCredentialState.NOT_CONNECTED
            raise GitHubReauthenticationRequired("GITHUB_NOT_CONNECTED")
        try:
            result = self._device_flow.refresh(refresh_token)
        except GitHubReauthenticationRequired:
            self._credential_state = GitHubCredentialState.REAUTH_REQUIRED
            self._access_token = None
            self._access_token_expires_at_ms = None
            raise
        self._adopt_tokens(
            access_token=result.access_token,
            access_token_expires_at_ms=result.access_token_expires_at_ms,
            refresh_token=result.refresh_token,
            granted_scopes=result.granted_scopes,
        )

    def _adopt_tokens(
        self,
        *,
        access_token: str,
        access_token_expires_at_ms: int | None,
        refresh_token: str | None,
        granted_scopes: tuple[str, ...],
    ) -> None:
        self._access_token = access_token
        self._access_token_expires_at_ms = access_token_expires_at_ms
        self._granted_scopes = granted_scopes
        if refresh_token is not None:
            self._keyring.put(self._keyring_account, refresh_token.encode("utf-8"))
        self._credential_state = GitHubCredentialState.CONNECTED

    def _stored_refresh_token(self) -> str | None:
        stored = self._keyring.get(self._keyring_account)
        return None if stored is None else stored.decode("utf-8")
