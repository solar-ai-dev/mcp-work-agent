"""Resolve a repository selection against current account/installation access."""

from collections.abc import Callable
from dataclasses import dataclass
from secrets import token_hex

from google_work_agent.application.use_cases.resource.list_repositories import (
    ListRepositoriesHandler,
    ListRepositoriesQuery,
)
from google_work_agent.ports.connector.connector_failure import (
    ConnectorFailureCode,
    ConnectorOperationFailure,
)
from google_work_agent.ports.system.settings_port import GitHubRepositoryDefaultV1


@dataclass(frozen=True, slots=True)
class GetRepositoryAccessQuery:
    repository: str
    expected_default: GitHubRepositoryDefaultV1 | None = None


class GetRepositoryAccessHandler:
    def __init__(
        self,
        *,
        list_repositories: ListRepositoriesHandler,
        current_account_id: Callable[[], str | None],
    ) -> None:
        self._list_repositories = list_repositories
        self._current_account_id = current_account_id

    def __call__(
        self, query: GetRepositoryAccessQuery, *, before_page: Callable[[], None] | None = None
    ) -> GitHubRepositoryDefaultV1:
        account_id = self._current_account_id()
        if account_id is None:
            raise ConnectorOperationFailure(
                code=ConnectorFailureCode.AUTH_REQUIRED,
                detail_code="GITHUB_ACCOUNT_NOT_CONNECTED",
            )
        expected = query.expected_default
        if expected is not None and expected.account_id != account_id:
            raise ConnectorOperationFailure(
                code=ConnectorFailureCode.PERMISSION_DENIED,
                detail_code="GITHUB_DEFAULT_ACCOUNT_CHANGED",
            )
        # A bounded scan must fail closed, never assert no access after incomplete coverage.
        cursor = None
        session_digest = token_hex(32)
        for _ in range(50):
            if before_page is not None:
                before_page()
            page = self._list_repositories(
                ListRepositoriesQuery(session_digest, account_id, cursor)
            )
            for item in page.items:
                if item.repository.casefold() != query.repository.casefold():
                    continue
                if expected is not None and item.repository_id != expected.repository_id:
                    break
                return GitHubRepositoryDefaultV1(item.repository, item.repository_id, account_id)
            cursor = page.next_cursor
            if cursor is None:
                raise ConnectorOperationFailure(
                    code=ConnectorFailureCode.PERMISSION_DENIED,
                    detail_code="GITHUB_REPOSITORY_ACCESS_UNAVAILABLE",
                )
        raise ConnectorOperationFailure(
            code=ConnectorFailureCode.UPSTREAM_UNAVAILABLE,
            detail_code="GITHUB_REPOSITORY_ACCESS_INCOMPLETE",
        )
