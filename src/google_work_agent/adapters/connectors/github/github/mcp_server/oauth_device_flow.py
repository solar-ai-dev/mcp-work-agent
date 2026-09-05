"""GitHub App User Access Token Device Flow protocol."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol, cast
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

GITHUB_DEVICE_CODE_ENDPOINT = "https://github.com/login/device/code"
GITHUB_TOKEN_ENDPOINT = "https://github.com/login/oauth/access_token"
GITHUB_DEVICE_GRANT_TYPE = "urn:ietf:params:oauth:grant-type:device_code"
GITHUB_REQUEST_TIMEOUT_SECONDS = 10
DEFAULT_DEVICE_POLL_INTERVAL_SECONDS = 5


class GitHubOAuthConfigurationError(RuntimeError):
    def __init__(self, safe_code: str) -> None:
        super().__init__(safe_code)
        self.safe_code = safe_code


class GitHubOAuthTransportError(RuntimeError):
    def __init__(self, safe_code: str) -> None:
        super().__init__(safe_code)
        self.safe_code = safe_code


class GitHubReauthenticationRequired(RuntimeError):
    def __init__(self, safe_code: str) -> None:
        super().__init__(safe_code)
        self.safe_code = safe_code


class GitHubDeviceFlowStatus(StrEnum):
    AUTHORIZATION_PENDING = "AUTHORIZATION_PENDING"
    SLOW_DOWN = "SLOW_DOWN"
    APPROVED = "APPROVED"
    EXPIRED = "EXPIRED"
    DENIED = "DENIED"


@dataclass(frozen=True, slots=True)
class GitHubDeviceAuthorization:
    device_code: str
    user_code: str
    verification_uri: str
    expires_at_ms: int
    interval_seconds: int


@dataclass(frozen=True, slots=True)
class GitHubDeviceFlowPollResult:
    status: GitHubDeviceFlowStatus
    interval_seconds: int | None = None
    access_token: str | None = None
    access_token_expires_at_ms: int | None = None
    refresh_token: str | None = None
    refresh_token_expires_at_ms: int | None = None
    granted_scopes: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class GitHubTokenRefreshResult:
    access_token: str
    access_token_expires_at_ms: int | None
    refresh_token: str | None
    refresh_token_expires_at_ms: int | None
    granted_scopes: tuple[str, ...]


class GitHubOAuthTransport(Protocol):
    def post_form(self, url: str, *, form: dict[str, str]) -> dict[str, object]: ...


class UrllibGitHubOAuthTransport:
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
            # nosec B310: URL은 connector가 소유한 고정 GitHub endpoint다.
            with urlopen(request, timeout=GITHUB_REQUEST_TIMEOUT_SECONDS) as response:
                raw_body = response.read().decode("utf-8")
        except HTTPError as error:
            raise GitHubOAuthTransportError("GITHUB_OAUTH_HTTP_ERROR") from error
        except (URLError, TimeoutError) as error:
            raise GitHubOAuthTransportError("GITHUB_OAUTH_UNREACHABLE") from error
        try:
            return cast(dict[str, object], json.loads(raw_body))
        except json.JSONDecodeError as error:
            raise GitHubOAuthTransportError("GITHUB_OAUTH_MALFORMED_RESPONSE") from error


_DEVICE_FLOW_ERROR_STATUS: dict[str, GitHubDeviceFlowStatus] = {
    "authorization_pending": GitHubDeviceFlowStatus.AUTHORIZATION_PENDING,
    "slow_down": GitHubDeviceFlowStatus.SLOW_DOWN,
    "expired_token": GitHubDeviceFlowStatus.EXPIRED,
    "access_denied": GitHubDeviceFlowStatus.DENIED,
}


class GitHubDeviceFlowClient:
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
            granted_scopes=result.granted_scopes,
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
        refresh_token = payload.get("refresh_token")
        refresh_token_expires_in = payload.get("refresh_token_expires_in")
        granted_scopes = _parse_scopes(payload.get("scope"))
        return GitHubDeviceFlowPollResult(
            status=GitHubDeviceFlowStatus.APPROVED,
            access_token=access_token,
            access_token_expires_at_ms=(
                self._now_ms() + expires_in * 1000 if isinstance(expires_in, int) else None
            ),
            refresh_token=refresh_token if isinstance(refresh_token, str) else None,
            refresh_token_expires_at_ms=(
                self._now_ms() + refresh_token_expires_in * 1000
                if isinstance(refresh_token_expires_in, int)
                else None
            ),
            granted_scopes=granted_scopes,
        )


def _parse_scopes(value: object) -> tuple[str, ...]:
    if not isinstance(value, str):
        return ()
    return tuple(dict.fromkeys(scope for scope in value.replace(",", " ").split() if scope))


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
