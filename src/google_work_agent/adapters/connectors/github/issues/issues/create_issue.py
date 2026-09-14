"""Create GitHub Issue operation."""

from __future__ import annotations

from google_work_agent.adapters.connectors.github.github.mcp_server.github_api import (
    GitHubApiClient,
)
from google_work_agent.ports.connector.contracts.delivery_certainty import DeliveryCertainty

from .issue_contract import (
    GITHUB_API_BASE,
    GitHubIssueCreateInput,
    GitHubIssueMutationRequest,
    optional_str,
    require_str,
)
from .issue_snapshot import normalize_github_issue, project_issue_snapshot

TOOL_ID = "github_create_issue"
RECOVERY_MARKER_TEMPLATE = "<!-- gwa-recovery-fingerprint:{fingerprint} -->"


def build_issue_create_request(create: GitHubIssueCreateInput) -> GitHubIssueMutationRequest:
    body: dict[str, object] = {"title": create.title}
    issue_body = create.body
    if create.recovery_fingerprint is not None:
        marker = RECOVERY_MARKER_TEMPLATE.format(fingerprint=create.recovery_fingerprint)
        issue_body = marker if issue_body is None else f"{issue_body}\n\n{marker}"
    if issue_body is not None:
        body["body"] = issue_body
    return GitHubIssueMutationRequest(
        method="POST",
        url=f"{GITHUB_API_BASE}/repos/{create.repository}/issues",
        body=body,
    )


class CreateIssueOperation:
    tool_id = TOOL_ID

    def __init__(self, api: GitHubApiClient) -> None:
        self._api = api

    def execute(self, arguments: dict[str, object]) -> dict[str, object]:
        create = GitHubIssueCreateInput(
            repository=require_str(arguments, "repository"),
            title=require_str(arguments, "title"),
            body=optional_str(arguments, "body"),
            recovery_fingerprint=optional_str(arguments, "recovery_fingerprint"),
        )
        raw = self._api.mutate(build_issue_create_request(create))
        snapshot = normalize_github_issue(
            raw,
            repository=create.repository,
            delivery_certainty=DeliveryCertainty.SENT_RESPONSE_LOST,
        )
        return {"item": project_issue_snapshot(snapshot)}
