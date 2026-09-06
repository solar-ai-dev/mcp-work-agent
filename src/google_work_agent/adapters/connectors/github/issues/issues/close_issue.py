"""Close GitHub Issue operation with Pull Request mutation guard."""

from __future__ import annotations

from google_work_agent.adapters.connectors.github.github.mcp_server.github_api import (
    GitHubApiClient,
)
from google_work_agent.ports.connector.contracts.google_workspace import DeliveryCertainty

from .get_issue import ensure_target_is_issue
from .issue_contract import (
    GITHUB_API_BASE,
    GitHubIssueMutationRequest,
    GitHubIssueStateChangeInput,
    require_issue_number,
    require_str,
)
from .issue_snapshot import normalize_github_issue, project_issue_snapshot

TOOL_ID = "github_close_issue"


def build_issue_close_request(change: GitHubIssueStateChangeInput) -> GitHubIssueMutationRequest:
    return GitHubIssueMutationRequest(
        method="PATCH",
        url=f"{GITHUB_API_BASE}/repos/{change.repository}/issues/{change.issue_number}",
        body={"state": "closed"},
    )


class CloseIssueOperation:
    tool_id = TOOL_ID

    def __init__(self, api: GitHubApiClient) -> None:
        self._api = api

    def execute(self, arguments: dict[str, object]) -> dict[str, object]:
        change = GitHubIssueStateChangeInput(
            repository=require_str(arguments, "repository"),
            issue_number=require_issue_number(arguments),
        )
        ensure_target_is_issue(
            self._api,
            repository=change.repository,
            issue_number=change.issue_number,
        )
        raw = self._api.mutate(build_issue_close_request(change))
        snapshot = normalize_github_issue(
            raw,
            repository=change.repository,
            delivery_certainty=DeliveryCertainty.SENT_RESPONSE_LOST,
            expected_issue_number=change.issue_number,
        )
        return {"item": project_issue_snapshot(snapshot)}
