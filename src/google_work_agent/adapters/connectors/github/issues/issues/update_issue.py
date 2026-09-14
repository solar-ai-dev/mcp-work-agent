"""Update GitHub Issue operation with Pull Request mutation guard."""

from __future__ import annotations

from google_work_agent.adapters.connectors.github.github.mcp_server.github_api import (
    GitHubApiClient,
)
from google_work_agent.ports.connector.contracts.delivery_certainty import DeliveryCertainty

from .get_issue import ensure_target_is_issue
from .issue_contract import (
    GITHUB_API_BASE,
    GitHubIssueMutationRequest,
    GitHubIssueUpdateInput,
    optional_str,
    require_issue_number,
    require_str,
)
from .issue_snapshot import normalize_github_issue, project_issue_snapshot

TOOL_ID = "github_update_issue"


def build_issue_update_request(update: GitHubIssueUpdateInput) -> GitHubIssueMutationRequest:
    body: dict[str, object] = {}
    if update.title is not None:
        body["title"] = update.title
    if update.body is not None:
        body["body"] = update.body
    return GitHubIssueMutationRequest(
        method="PATCH",
        url=f"{GITHUB_API_BASE}/repos/{update.repository}/issues/{update.issue_number}",
        body=body,
    )


class UpdateIssueOperation:
    tool_id = TOOL_ID

    def __init__(self, api: GitHubApiClient) -> None:
        self._api = api

    def execute(self, arguments: dict[str, object]) -> dict[str, object]:
        update = GitHubIssueUpdateInput(
            repository=require_str(arguments, "repository"),
            issue_number=require_issue_number(arguments),
            title=optional_str(arguments, "title"),
            body=optional_str(arguments, "body"),
        )
        ensure_target_is_issue(
            self._api,
            repository=update.repository,
            issue_number=update.issue_number,
        )
        raw = self._api.mutate(build_issue_update_request(update))
        snapshot = normalize_github_issue(
            raw,
            repository=update.repository,
            delivery_certainty=DeliveryCertainty.SENT_RESPONSE_LOST,
            expected_issue_number=update.issue_number,
        )
        return {"item": project_issue_snapshot(snapshot)}
