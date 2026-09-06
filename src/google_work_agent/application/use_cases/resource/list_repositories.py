"""Project a bounded page of repositories accessible to the current GitHub account."""

from dataclasses import dataclass

from google_work_agent.application.use_cases.resource.opaque_continuation_access import (
    LocalResourceContinuationStore,
)
from google_work_agent.ports.connector.connector_failure import (
    ConnectorFailureCode,
    ConnectorOperationFailure,
    normalize_google_workspace_failure,
)
from google_work_agent.ports.connector.connector_read_port import ConnectorReadPort
from google_work_agent.ports.connector.contracts.google_workspace import GoogleWorkspaceGatewayError
from google_work_agent.ports.connector.contracts.validated_connector_tool_binding import (
    ValidatedConnectorToolBindingV1,
)
from google_work_agent.ports.system.settings_port import GitHubRepositoryDefaultV1


@dataclass(frozen=True, slots=True)
class ListRepositoriesQuery:
    session_digest: str
    account_id: str
    cursor: str | None = None

    def __post_init__(self) -> None:
        if (
            len(self.session_digest) != 64
            or any(char not in "0123456789abcdef" for char in self.session_digest)
            or not self.account_id
        ):
            raise ValueError("repository continuation principal is invalid")


@dataclass(frozen=True, slots=True)
class RepositoryContainerItem:
    repository: str
    repository_id: int
    private: bool


@dataclass(frozen=True, slots=True)
class ListRepositoriesResult:
    schema_version: int
    account_id: str
    items: tuple[RepositoryContainerItem, ...]
    next_cursor: str | None


class ListRepositoriesHandler:
    def __init__(
        self,
        *,
        connector_read: ConnectorReadPort,
        binding: ValidatedConnectorToolBindingV1,
        continuation_store: LocalResourceContinuationStore,
    ) -> None:
        self._connector_read = connector_read
        self._binding = binding
        self._continuation_store = continuation_store

    def __call__(self, query: ListRepositoriesQuery) -> ListRepositoriesResult:
        scope = (query.session_digest, query.account_id, "github-repositories")
        try:
            cursor = (
                None
                if query.cursor is None
                else self._continuation_store.resolve(
                    scope=scope,
                    local_handle=query.cursor,
                )
            )
        except GoogleWorkspaceGatewayError as error:
            raise normalize_google_workspace_failure(error) from error
        output = self._connector_read.execute_read(self._binding, {"cursor": cursor}).output
        if output.get("account_id") != query.account_id:
            raise ConnectorOperationFailure(
                code=ConnectorFailureCode.AUTH_REQUIRED,
                detail_code="GITHUB_ACCOUNT_CHANGED",
            )
        raw = output.get("items")
        next_cursor = output.get("next_cursor")
        if (
            not isinstance(raw, list)
            or len(raw) > 100
            or (next_cursor is not None and not isinstance(next_cursor, str))
        ):
            raise _malformed_response()
        items = []
        for row in raw:
            if not isinstance(row, dict):
                raise _malformed_response()
            name, repo_id, private = (
                row.get("repository"),
                row.get("repository_id"),
                row.get("private"),
            )
            if not isinstance(name, str) or type(repo_id) is not int or type(private) is not bool:
                raise _malformed_response()
            try:
                GitHubRepositoryDefaultV1(name, repo_id, query.account_id)
            except ValueError as error:
                raise _malformed_response() from error
            items.append(RepositoryContainerItem(name, repo_id, private))
        return ListRepositoriesResult(
            1,
            query.account_id,
            tuple(items),
            None
            if next_cursor is None
            else self._continuation_store.issue(
                scope=scope,
                provider_page_token=next_cursor,
            ),
        )


def _malformed_response() -> ConnectorOperationFailure:
    return ConnectorOperationFailure(
        code=ConnectorFailureCode.MALFORMED_RESPONSE,
        detail_code="GITHUB_REPOSITORIES_MALFORMED",
    )
