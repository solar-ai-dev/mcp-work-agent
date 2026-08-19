from __future__ import annotations

import pytest

from google_work_agent.mcp.github_issue_provider import (
    GitHubIssueCreateInput,
    GitHubIssueListQuery,
    GitHubIssueQueryError,
    GitHubIssueState,
    GitHubIssueStateChangeInput,
    GitHubIssueUpdateInput,
    build_issue_close_request,
    build_issue_create_request,
    build_issue_get_request,
    build_issue_list_request,
    build_issue_reopen_request,
    build_issue_update_request,
)


def test_list_request_maps_repository_state_assignee_label_deterministically() -> None:
    query = GitHubIssueListQuery(
        repository="octo-org/octo-repo",
        state=GitHubIssueState.OPEN,
        assignee="octocat",
        label="bug",
    )

    request = build_issue_list_request(query)

    assert request.url == (
        "https://api.github.com/repos/octo-org/octo-repo/issues"
        "?state=open&per_page=100&assignee=octocat&labels=bug"
    )


def test_list_request_is_deterministic_for_the_same_input() -> None:
    query = GitHubIssueListQuery(repository="octo-org/octo-repo", state=GitHubIssueState.CLOSED)

    first = build_issue_list_request(query)
    second = build_issue_list_request(query)

    assert first == second


def test_list_request_omits_optional_filters_when_absent() -> None:
    query = GitHubIssueListQuery(repository="octo-org/octo-repo")

    request = build_issue_list_request(query)

    assert "assignee=" not in request.url
    assert "labels=" not in request.url


@pytest.mark.parametrize(
    "state", (GitHubIssueState.OPEN, GitHubIssueState.CLOSED, GitHubIssueState.ALL)
)
def test_list_request_maps_every_supported_state(state: GitHubIssueState) -> None:
    query = GitHubIssueListQuery(repository="octo-org/repo", state=state)

    request = build_issue_list_request(query)

    assert f"state={state.value.lower()}" in request.url


def test_list_query_rejects_repository_without_owner_separator() -> None:
    with pytest.raises(GitHubIssueQueryError):
        GitHubIssueListQuery(repository="octo-repo")


def test_list_query_rejects_empty_repository() -> None:
    with pytest.raises(GitHubIssueQueryError):
        GitHubIssueListQuery(repository="")


def test_list_query_rejects_blank_assignee() -> None:
    with pytest.raises(GitHubIssueQueryError):
        GitHubIssueListQuery(repository="octo-org/repo", assignee="   ")


def test_list_query_rejects_blank_label() -> None:
    with pytest.raises(GitHubIssueQueryError):
        GitHubIssueListQuery(repository="octo-org/repo", label="  ")


def test_get_request_scopes_to_repository_and_issue_number() -> None:
    request = build_issue_get_request(repository="octo-org/octo-repo", issue_number=42)

    assert request.url == "https://api.github.com/repos/octo-org/octo-repo/issues/42"


def test_get_request_rejects_invalid_repository() -> None:
    with pytest.raises(GitHubIssueQueryError):
        build_issue_get_request(repository="not-a-repo", issue_number=1)


def test_get_request_rejects_non_positive_issue_number() -> None:
    with pytest.raises(GitHubIssueQueryError):
        build_issue_get_request(repository="octo-org/repo", issue_number=0)


def test_list_query_has_no_extension_point_for_unsupported_filters() -> None:
    """P0 filter scope is fixed to repository/state/assignee/label -- there is
    no generic ProviderQuery DSL an unsupported filter (e.g. milestone) could
    be smuggled through.
    """

    with pytest.raises(TypeError):
        GitHubIssueListQuery(repository="octo-org/repo", milestone="v1")  # type: ignore[call-arg]


# --- WRITE: create ---------------------------------------------------------


def test_create_request_maps_repository_title_body() -> None:
    create = GitHubIssueCreateInput(
        repository="octo-org/octo-repo", title="Bug found", body="Steps to reproduce"
    )

    request = build_issue_create_request(create)

    assert request.method == "POST"
    assert request.url == "https://api.github.com/repos/octo-org/octo-repo/issues"
    assert request.body == {"title": "Bug found", "body": "Steps to reproduce"}


def test_create_request_omits_body_when_absent() -> None:
    create = GitHubIssueCreateInput(repository="octo-org/octo-repo", title="Bug found")

    request = build_issue_create_request(create)

    assert request.body == {"title": "Bug found"}


def test_create_request_is_deterministic_for_the_same_input() -> None:
    create = GitHubIssueCreateInput(repository="octo-org/octo-repo", title="Bug found")

    assert build_issue_create_request(create) == build_issue_create_request(create)


def test_create_input_rejects_empty_title() -> None:
    with pytest.raises(GitHubIssueQueryError):
        GitHubIssueCreateInput(repository="octo-org/octo-repo", title="   ")


def test_create_input_rejects_invalid_repository() -> None:
    with pytest.raises(GitHubIssueQueryError):
        GitHubIssueCreateInput(repository="not-a-repo", title="Bug")


# --- WRITE: update -----------------------------------------------------


def test_update_request_maps_repository_issue_number_title_body() -> None:
    update = GitHubIssueUpdateInput(
        repository="octo-org/octo-repo", issue_number=42, title="New title", body="New body"
    )

    request = build_issue_update_request(update)

    assert request.method == "PATCH"
    assert request.url == "https://api.github.com/repos/octo-org/octo-repo/issues/42"
    assert request.body == {"title": "New title", "body": "New body"}


def test_update_request_carries_only_title_when_body_absent() -> None:
    update = GitHubIssueUpdateInput(repository="octo-org/octo-repo", issue_number=42, title="X")

    request = build_issue_update_request(update)

    assert request.body == {"title": "X"}


def test_update_request_carries_only_body_when_title_absent() -> None:
    update = GitHubIssueUpdateInput(repository="octo-org/octo-repo", issue_number=42, body="Y")

    request = build_issue_update_request(update)

    assert request.body == {"body": "Y"}


def test_update_input_rejects_empty_mutation() -> None:
    with pytest.raises(GitHubIssueQueryError):
        GitHubIssueUpdateInput(repository="octo-org/octo-repo", issue_number=42)


def test_update_input_rejects_blank_title() -> None:
    with pytest.raises(GitHubIssueQueryError):
        GitHubIssueUpdateInput(repository="octo-org/octo-repo", issue_number=42, title="  ")


def test_update_input_rejects_invalid_repository() -> None:
    with pytest.raises(GitHubIssueQueryError):
        GitHubIssueUpdateInput(repository="not-a-repo", issue_number=42, title="X")


def test_update_input_rejects_non_positive_issue_number() -> None:
    with pytest.raises(GitHubIssueQueryError):
        GitHubIssueUpdateInput(repository="octo-org/octo-repo", issue_number=0, title="X")


# --- WRITE: close / reopen -----------------------------------------------


def test_close_request_sets_state_closed() -> None:
    change = GitHubIssueStateChangeInput(repository="octo-org/octo-repo", issue_number=42)

    request = build_issue_close_request(change)

    assert request.method == "PATCH"
    assert request.url == "https://api.github.com/repos/octo-org/octo-repo/issues/42"
    assert request.body == {"state": "closed"}


def test_reopen_request_sets_state_open() -> None:
    change = GitHubIssueStateChangeInput(repository="octo-org/octo-repo", issue_number=42)

    request = build_issue_reopen_request(change)

    assert request.method == "PATCH"
    assert request.body == {"state": "open"}


def test_state_change_input_rejects_invalid_repository() -> None:
    with pytest.raises(GitHubIssueQueryError):
        GitHubIssueStateChangeInput(repository="not-a-repo", issue_number=1)


def test_state_change_input_rejects_non_positive_issue_number() -> None:
    with pytest.raises(GitHubIssueQueryError):
        GitHubIssueStateChangeInput(repository="octo-org/octo-repo", issue_number=0)
