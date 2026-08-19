from __future__ import annotations

import pytest

from google_work_agent.mcp.github_issue_provider import (
    GitHubIssueTaskState,
    GitHubProviderError,
    normalize_github_issue,
    normalize_github_issue_list,
)


def _raw_issue(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "number": 1,
        "title": "Something is broken",
        "body": "Steps to reproduce...",
        "state": "open",
        "html_url": "https://github.com/octo-org/octo-repo/issues/1",
        "labels": [{"name": "bug"}, {"name": "p1"}],
        "assignees": [{"login": "octocat"}],
    }
    base.update(overrides)
    return base


def test_normalize_maps_task_semantic_fields() -> None:
    view = normalize_github_issue(_raw_issue(), repository="octo-org/octo-repo")

    assert view.title == "Something is broken"
    assert view.description == "Steps to reproduce..."
    assert view.task_state is GitHubIssueTaskState.OPEN
    assert view.url == "https://github.com/octo-org/octo-repo/issues/1"


def test_normalize_maps_closed_state() -> None:
    view = normalize_github_issue(_raw_issue(state="closed"), repository="octo-org/octo-repo")

    assert view.task_state is GitHubIssueTaskState.CLOSED


def test_normalize_keeps_github_specific_metadata_connector_owned() -> None:
    view = normalize_github_issue(_raw_issue(), repository="octo-org/octo-repo")

    assert view.resource_identity.repository == "octo-org/octo-repo"
    assert view.resource_identity.issue_number == 1
    assert view.labels == ("bug", "p1")
    assert view.assignees == ("octocat",)


def test_normalize_does_not_produce_a_google_task_shape() -> None:
    view = normalize_github_issue(_raw_issue(), repository="octo-org/octo-repo")
    field_names = set(type(view).__dataclass_fields__)

    assert "tasklist_id" not in field_names
    assert "due" not in field_names
    assert "scheduled_date" not in field_names


def test_resource_identity_does_not_collide_across_repositories() -> None:
    view_a = normalize_github_issue(_raw_issue(number=1), repository="octo-org/repo-a")
    view_b = normalize_github_issue(_raw_issue(number=1), repository="octo-org/repo-b")

    id_a = view_a.resource_identity.external_resource_id
    id_b = view_b.resource_identity.external_resource_id
    assert id_a != id_b
    assert view_a.resource_identity.external_resource_id == "octo-org/repo-a#1"
    assert view_b.resource_identity.external_resource_id == "octo-org/repo-b#1"


def test_normalize_rejects_missing_required_fields() -> None:
    with pytest.raises(GitHubProviderError) as captured:
        normalize_github_issue({"title": "no number"}, repository="octo-org/repo")

    assert captured.value.safe_code == "MALFORMED_RESPONSE"


def test_normalize_tolerates_missing_optional_fields() -> None:
    view = normalize_github_issue(
        {"number": 5, "title": "Minimal"}, repository="octo-org/repo"
    )

    assert view.description == ""
    assert view.url == ""
    assert view.labels == ()
    assert view.assignees == ()
    assert view.task_state is GitHubIssueTaskState.OPEN


def test_normalize_rejects_a_pull_request_response() -> None:
    """`/issues/{number}` can resolve to a Pull Request; PRs are out of P0
    scope and must be rejected, not silently normalized as a TASK.
    """

    raw = _raw_issue(pull_request={"url": "https://api.github.com/repos/o/r/pulls/1"})

    with pytest.raises(GitHubProviderError) as captured:
        normalize_github_issue(raw, repository="octo-org/octo-repo")

    assert captured.value.safe_code == "NOT_FOUND"
    assert captured.value.dispatch_started is True


def test_normalize_list_drops_pull_requests() -> None:
    raw_items = [
        _raw_issue(number=1),
        _raw_issue(number=2, pull_request={"url": "https://api.github.com/..."}),
    ]

    views = normalize_github_issue_list(raw_items, repository="octo-org/octo-repo")

    assert [view.resource_identity.issue_number for view in views] == [1]


def test_normalize_list_never_exposes_raw_dto_fields_directly() -> None:
    views = normalize_github_issue_list([_raw_issue()], repository="octo-org/octo-repo")

    assert not hasattr(views[0], "html_url")
    assert not hasattr(views[0], "node_id")
