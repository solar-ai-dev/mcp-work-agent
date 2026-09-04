"""Connector-local construction and lifecycle for the GitHub MCP process."""

from __future__ import annotations

import os
import secrets
import time
from collections.abc import Callable, Mapping
from typing import Protocol, cast

from google_work_agent.adapters.connectors.github.issues.issues.close_issue import (
    CloseIssueOperation,
)
from google_work_agent.adapters.connectors.github.issues.issues.create_issue import (
    CreateIssueOperation,
)
from google_work_agent.adapters.connectors.github.issues.issues.get_issue import (
    GetIssueOperation,
)
from google_work_agent.adapters.connectors.github.issues.issues.list_issues import (
    ListIssuesOperation,
)
from google_work_agent.adapters.connectors.github.issues.issues.reopen_issue import (
    ReopenIssueOperation,
)
from google_work_agent.adapters.connectors.github.issues.issues.search_by_recovery_fingerprint import (
    SearchByRecoveryFingerprintOperation,
)
from google_work_agent.adapters.connectors.github.issues.issues.update_issue import (
    UpdateIssueOperation,
)
from google_work_agent.adapters.keyring.os_keyring_secret_store import (
    OsKeyringSecretStoreAdapter,
)

from .credential_provider import GITHUB_KEYRING_SERVICE, GitHubCredentialProvider
from .github_api import GitHubApiClient
from .oauth_device_flow import (
    GitHubDeviceAuthorization,
    GitHubDeviceFlowClient,
    GitHubOAuthConfigurationError,
)


class GitHubToolOperation(Protocol):
    tool_id: str

    def execute(self, arguments: dict[str, object]) -> dict[str, object]: ...


class GitHubMcpServerState:
    def __init__(
        self,
        *,
        credential_provider: GitHubCredentialProvider | None = None,
        api_client: GitHubApiClient | None = None,
        operations: Mapping[str, GitHubToolOperation] | None = None,
        now_ms: Callable[[], int] = lambda: int(time.time() * 1000),
    ) -> None:
        self.process_instance_id = f"mcp-{secrets.token_hex(8)}"
        self.service_instance_id: str | None = None
        self.session_key: str | None = None
        self.active_device_authorization: GitHubDeviceAuthorization | None = None
        self.active_device_operation_ref: str | None = None
        self.next_device_poll_at_ms: int | None = None
        self.operational_results: dict[str, dict[str, object]] = {}
        self.used_nonces: set[str] = set()
        self.now_ms = now_ms
        self._credential_provider = credential_provider
        self._api_client = api_client
        self._operations = None if operations is None else dict(operations)
        self._recovery_search: GitHubToolOperation | None = None

    def credential_provider(self) -> GitHubCredentialProvider:
        if self._credential_provider is not None:
            return self._credential_provider
        client_id = os.environ.get("GITHUB_APP_CLIENT_ID", "").strip()
        if not client_id:
            raise GitHubOAuthConfigurationError("GITHUB_APP_CLIENT_ID_MISSING")
        try:
            keyring = OsKeyringSecretStoreAdapter(service_name=GITHUB_KEYRING_SERVICE)
        except RuntimeError as error:
            raise GitHubOAuthConfigurationError("KEYRING_UNAVAILABLE") from error
        device_flow = GitHubDeviceFlowClient(
            client_id=client_id,
            scope=os.environ.get("GITHUB_APP_SCOPE", "").strip(),
            now_ms=self.now_ms,
        )
        self._credential_provider = GitHubCredentialProvider(
            keyring=keyring,
            device_flow=device_flow,
            now_ms=self.now_ms,
        )
        return self._credential_provider

    def api_client(self) -> GitHubApiClient:
        if self._api_client is None:
            self._api_client = GitHubApiClient(
                credential_provider=self.credential_provider()
            )
        return self._api_client

    def operations(self) -> dict[str, GitHubToolOperation]:
        if self._operations is None:
            api = cast(GitHubApiClient, _LazyGitHubApiClient(self))
            operations: tuple[GitHubToolOperation, ...] = (
                ListIssuesOperation(api),
                GetIssueOperation(api),
                CreateIssueOperation(api),
                UpdateIssueOperation(api),
                CloseIssueOperation(api),
                ReopenIssueOperation(api),
            )
            self._operations = {operation.tool_id: operation for operation in operations}
        return self._operations

    def recovery_search(self) -> GitHubToolOperation:
        if self._recovery_search is None:
            self._recovery_search = SearchByRecoveryFingerprintOperation(
                cast(GitHubApiClient, _LazyGitHubApiClient(self))
            )
        return self._recovery_search


class _LazyGitHubApiClient:
    """Defer OAuth/keyring construction until an operation reaches GitHub."""

    def __init__(self, state: GitHubMcpServerState) -> None:
        self._state = state

    def get(self, url: str) -> object:
        return self._state.api_client().get(url)

    def mutate(self, request: object) -> dict[str, object]:
        return self._state.api_client().mutate(request)  # type: ignore[arg-type]
