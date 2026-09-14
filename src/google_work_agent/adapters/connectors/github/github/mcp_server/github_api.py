"""Shared authenticated GitHub REST transport and safe error mapping."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import NoReturn, Protocol
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from google_work_agent.ports.connector.contracts.delivery_certainty import DeliveryCertainty

from .credential_provider import GitHubCredentialProvider
from .oauth_device_flow import GitHubReauthenticationRequired

GITHUB_API_VERSION = "2022-11-28"
GITHUB_API_TIMEOUT_SECONDS = 30


class GitHubProviderError(RuntimeError):
    def __init__(
        self,
        safe_code: str,
        *,
        delivery_certainty: DeliveryCertainty = DeliveryCertainty.NOT_SENT,
    ) -> None:
        super().__init__(safe_code)
        self.safe_code = safe_code
        self.delivery_certainty = delivery_certainty

    @property
    def dispatch_started(self) -> bool:
        return self.delivery_certainty is not DeliveryCertainty.NOT_SENT


@dataclass(frozen=True, slots=True)
class GitHubRestResponse:
    status_code: int
    body: object


class GitHubRestTransport(Protocol):
    def request(
        self,
        method: str,
        url: str,
        *,
        access_token: str,
        body: dict[str, object] | None = None,
    ) -> GitHubRestResponse: ...


class GitHubMutationRequest(Protocol):
    @property
    def method(self) -> str: ...

    @property
    def url(self) -> str: ...

    @property
    def body(self) -> dict[str, object]: ...


class UrllibGitHubRestTransport:
    def request(
        self,
        method: str,
        url: str,
        *,
        access_token: str,
        body: dict[str, object] | None = None,
    ) -> GitHubRestResponse:
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": GITHUB_API_VERSION,
        }
        data: bytes | None = None
        if body is not None:
            data = json.dumps(body).encode("utf-8")
            headers["Content-Type"] = "application/json"
        request = Request(url, data=data, headers=headers, method=method)
        try:
            # nosec B310: URL은 typed operation이 만드는 고정 GitHub API host다.
            with urlopen(request, timeout=GITHUB_API_TIMEOUT_SECONDS) as response:
                return GitHubRestResponse(
                    status_code=response.status,
                    body=_parse_json_or_none(response.read()),
                )
        except HTTPError as error:
            return GitHubRestResponse(
                status_code=error.code,
                body=_parse_json_or_none(error.read()),
            )
        except (URLError, TimeoutError) as error:
            raise GitHubProviderError(
                "MCP_UNAVAILABLE",
                delivery_certainty=(
                    DeliveryCertainty.MAY_HAVE_BEEN_SENT
                    if method != "GET"
                    else DeliveryCertainty.NOT_SENT
                ),
            ) from error


class GitHubApiClient:
    def __init__(
        self,
        *,
        credential_provider: GitHubCredentialProvider,
        transport: GitHubRestTransport | None = None,
    ) -> None:
        self._credential_provider = credential_provider
        self._transport = transport or UrllibGitHubRestTransport()

    def get(self, url: str) -> object:
        response = self._transport.request("GET", url, access_token=self._access_token())
        if response.status_code == 200:
            return response.body
        self._raise_response_error(response.status_code)

    def mutate(self, request: GitHubMutationRequest) -> dict[str, object]:
        response = self._transport.request(
            request.method,
            request.url,
            access_token=self._access_token(),
            body=request.body,
        )
        if response.status_code in (200, 201):
            if not isinstance(response.body, dict):
                raise GitHubProviderError(
                    "MALFORMED_RESPONSE",
                    delivery_certainty=DeliveryCertainty.SENT_RESPONSE_LOST,
                )
            return response.body
        certainty = (
            DeliveryCertainty.MAY_HAVE_BEEN_SENT
            if response.status_code >= 500
            else DeliveryCertainty.NOT_SENT
        )
        self._raise_response_error(response.status_code, delivery_certainty=certainty)

    def _access_token(self) -> str:
        try:
            return self._credential_provider.get_access_token()
        except GitHubReauthenticationRequired as error:
            raise GitHubProviderError("REAUTH_REQUIRED") from error

    def _raise_response_error(
        self,
        status_code: int,
        *,
        delivery_certainty: DeliveryCertainty = DeliveryCertainty.NOT_SENT,
    ) -> NoReturn:
        if status_code == 401:
            self._credential_provider.invalidate_access_token()
        raise GitHubProviderError(
            _safe_code_for_status(status_code),
            delivery_certainty=delivery_certainty,
        )


def _parse_json_or_none(raw: bytes) -> object:
    if not raw:
        return None
    try:
        return json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None


_STATUS_CODE_SAFE_CODES: dict[int, str] = {
    401: "REAUTH_REQUIRED",
    403: "PERMISSION_DENIED",
    404: "NOT_FOUND",
    422: "INVALID_ARGUMENT",
    429: "RATE_LIMITED",
}


def _safe_code_for_status(status_code: int) -> str:
    if status_code in _STATUS_CODE_SAFE_CODES:
        return _STATUS_CODE_SAFE_CODES[status_code]
    if status_code >= 500:
        return "UPSTREAM_5XX"
    return "GITHUB_REQUEST_FAILED"
