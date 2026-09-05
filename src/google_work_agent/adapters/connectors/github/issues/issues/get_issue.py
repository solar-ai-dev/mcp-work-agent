"""Get and observe one GitHub Issue operation."""

from __future__ import annotations

from google_work_agent.adapters.connectors.github.github.mcp_server.github_api import (
    GitHubApiClient,
    GitHubProviderError,
)

from .issue_contract import (
    GITHUB_API_BASE,
    GitHubIssueRequest,
    require_issue_number,
    require_str,
    validate_issue_number,
    validate_repository,
)
from .issue_snapshot import (
    GitHubIssueSnapshot,
    normalize_github_issue,
    project_issue_snapshot,
)

TOOL_ID = "github_get_issue"


def build_issue_get_request(*, repository: str, issue_number: int) -> GitHubIssueRequest:
    validate_repository(repository)
    validate_issue_number(issue_number)
    return GitHubIssueRequest(
        url=f"{GITHUB_API_BASE}/repos/{repository}/issues/{issue_number}"
    )


def observe_issue(
    api: GitHubApiClient, *, repository: str, issue_number: int
) -> GitHubIssueSnapshot:
    request = build_issue_get_request(repository=repository, issue_number=issue_number)
    body = api.get(request.url)
    if not isinstance(body, dict):
        raise GitHubProviderError("MALFORMED_RESPONSE")
    return normalize_github_issue(body, repository=repository)


def ensure_target_is_issue(
    api: GitHubApiClient, *, repository: str, issue_number: int
) -> None:
    try:
        observe_issue(api, repository=repository, issue_number=issue_number)
    except GitHubProviderError as error:
        raise GitHubProviderError(error.safe_code) from error


class GetIssueOperation:
    tool_id = TOOL_ID

    def __init__(self, api: GitHubApiClient) -> None:
        self._api = api

    def execute(self, arguments: dict[str, object]) -> dict[str, object]:
        snapshot = observe_issue(
            self._api,
            repository=require_str(arguments, "repository"),
            issue_number=require_issue_number(arguments),
        )
        return {"item": project_issue_snapshot(snapshot)}
