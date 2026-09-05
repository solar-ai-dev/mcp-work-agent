"""GitHub Issue provider observation normalization."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import cast

from google_work_agent.adapters.connectors.github.github.mcp_server.github_api import (
    GitHubProviderError,
)
from google_work_agent.ports.connector.contracts.google_workspace import DeliveryCertainty

from .issue_contract import RESOURCE_TYPE


class GitHubIssueState(StrEnum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


@dataclass(frozen=True, slots=True)
class GitHubIssueResourceIdentity:
    repository: str
    issue_number: int

    @property
    def external_resource_id(self) -> str:
        return f"{self.repository}#{self.issue_number}"


@dataclass(frozen=True, slots=True)
class GitHubIssueSnapshot:
    resource_identity: GitHubIssueResourceIdentity
    title: str
    description: str
    state: GitHubIssueState
    url: str
    labels: tuple[str, ...]
    assignees: tuple[str, ...]
    version: str


def normalize_github_issue(
    raw: dict[str, object], *, repository: str,
    delivery_certainty: DeliveryCertainty = DeliveryCertainty.NOT_SENT,
) -> GitHubIssueSnapshot:
    if "pull_request" in raw:
        raise GitHubProviderError("NOT_FOUND", delivery_certainty=delivery_certainty)
    issue_number = raw.get("number")
    title = raw.get("title")
    if not isinstance(issue_number, int) or not isinstance(title, str):
        raise GitHubProviderError(
            "MALFORMED_RESPONSE", delivery_certainty=delivery_certainty
        )
    body = raw.get("body")
    url = raw.get("html_url")
    updated_at = raw.get("updated_at")
    return GitHubIssueSnapshot(
        resource_identity=GitHubIssueResourceIdentity(repository, issue_number),
        title=title,
        description=body if isinstance(body, str) else "",
        state=(
            GitHubIssueState.CLOSED
            if raw.get("state") == "closed"
            else GitHubIssueState.OPEN
        ),
        url=url if isinstance(url, str) else "",
        labels=_normalized_labels(raw),
        assignees=_normalized_assignees(raw),
        version=updated_at if isinstance(updated_at, str) else "",
    )


def normalize_github_issue_list(
    raw_items: list[dict[str, object]], *, repository: str
) -> list[GitHubIssueSnapshot]:
    return [
        normalize_github_issue(item, repository=repository)
        for item in raw_items
        if "pull_request" not in item
    ]


def project_issue_snapshot(snapshot: GitHubIssueSnapshot) -> dict[str, object]:
    identity = snapshot.resource_identity
    return {
        "fixture_snapshot_id": identity.external_resource_id,
        "resource_type": RESOURCE_TYPE,
        "resource_id": identity.external_resource_id,
        "parent_id": identity.repository,
        "related_resource_ids": [identity.repository],
        "version": snapshot.version,
        "recovery_fingerprint": None,
        "payload": {
            "repository": identity.repository,
            "issue_number": identity.issue_number,
            "title": snapshot.title,
            "description": snapshot.description,
            "state": snapshot.state.value,
            "url": snapshot.url,
            "labels": list(snapshot.labels),
            "assignees": list(snapshot.assignees),
        },
    }


def _normalized_labels(raw: dict[str, object]) -> tuple[str, ...]:
    labels = raw.get("labels")
    if not isinstance(labels, list):
        return ()
    return tuple(
        sorted(
            cast(str, label["name"])
            for label in labels
            if isinstance(label, dict) and isinstance(label.get("name"), str)
        )
    )


def _normalized_assignees(raw: dict[str, object]) -> tuple[str, ...]:
    assignees = raw.get("assignees")
    if not isinstance(assignees, list):
        return ()
    return tuple(
        sorted(
            cast(str, assignee["login"])
            for assignee in assignees
            if isinstance(assignee, dict) and isinstance(assignee.get("login"), str)
        )
    )
