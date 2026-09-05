"""List GitHub Issues operation."""

from __future__ import annotations

from urllib.parse import urlencode

from google_work_agent.adapters.connectors.github.github.mcp_server.github_api import (
    GitHubApiClient,
    GitHubProviderError,
)

from .issue_contract import (
    GITHUB_API_BASE,
    GITHUB_ISSUE_LIST_PAGE_SIZE,
    GitHubIssueFilterState,
    GitHubIssueListQuery,
    GitHubIssueRequest,
    optional_str,
    require_str,
)
from .issue_snapshot import normalize_github_issue_list, project_issue_snapshot

TOOL_ID = "github_list_issues"

_STATE_PARAM_VALUES = {
    GitHubIssueFilterState.OPEN: "open",
    GitHubIssueFilterState.CLOSED: "closed",
    GitHubIssueFilterState.ALL: "all",
}


def build_issue_list_request(query: GitHubIssueListQuery) -> GitHubIssueRequest:
    params = {
        "state": _STATE_PARAM_VALUES[query.state],
        "per_page": GITHUB_ISSUE_LIST_PAGE_SIZE,
    }
    if query.assignee is not None:
        params["assignee"] = query.assignee
    if query.label is not None:
        params["labels"] = query.label
    return GitHubIssueRequest(
        url=f"{GITHUB_API_BASE}/repos/{query.repository}/issues?{urlencode(params)}"
    )


class ListIssuesOperation:
    tool_id = TOOL_ID

    def __init__(self, api: GitHubApiClient) -> None:
        self._api = api

    def execute(self, arguments: dict[str, object]) -> dict[str, object]:
        raw_state = arguments.get("state", GitHubIssueFilterState.OPEN.value)
        if not isinstance(raw_state, str):
            from .issue_contract import GitHubIssueQueryError

            raise GitHubIssueQueryError("STATE_INVALID")
        try:
            state = GitHubIssueFilterState(raw_state.upper())
        except ValueError as error:
            from .issue_contract import GitHubIssueQueryError

            raise GitHubIssueQueryError("STATE_INVALID") from error
        query = GitHubIssueListQuery(
            repository=require_str(arguments, "repository"),
            state=state,
            assignee=optional_str(arguments, "assignee"),
            label=optional_str(arguments, "label"),
        )
        body = self._api.get(build_issue_list_request(query).url)
        if not isinstance(body, list):
            raise GitHubProviderError("MALFORMED_RESPONSE")
        raw_items = [item for item in body if isinstance(item, dict)]
        return {
            "items": [
                project_issue_snapshot(item)
                for item in normalize_github_issue_list(
                    raw_items, repository=query.repository
                )
            ]
        }
