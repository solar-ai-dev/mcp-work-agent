"""End-to-end MCP tool_call regression coverage for READ + WRITE handlers.

Exercises `github_server.py`'s private handler functions directly (same
pattern as `tests/unit/mcp/test_oauth_server.py` importing `server` and
calling its module-private functions), injecting a fake provider adapter so
no credential/env/network setup is needed.
"""

from __future__ import annotations

from typing import cast

import pytest

from google_work_agent.mcp import github_server
from google_work_agent.mcp.github_auth import GitHubCredentialProvider, GitHubDeviceFlowClient
from google_work_agent.mcp.github_issue_provider import (
    GitHubIssueCreateInput,
    GitHubIssueListQuery,
    GitHubIssueProviderAdapter,
    GitHubIssueQueryError,
    GitHubIssueStateChangeInput,
    GitHubIssueUpdateInput,
    GitHubProviderError,
    GitHubRestResponse,
    build_issue_close_request,
    build_issue_create_request,
    build_issue_get_request,
    build_issue_list_request,
    build_issue_reopen_request,
    build_issue_update_request,
)
from tests.support.fakes.clock import FakeClock
from tests.support.fakes.keyring import FakeKeyring


class _FakeGitHubRestTransport:
    def __init__(self) -> None:
        self._responses: dict[tuple[str, str], GitHubRestResponse] = {}

    def program(self, url: str, response: GitHubRestResponse, *, method: str = "GET") -> None:
        self._responses[(method, url)] = response

    def request(
        self, method: str, url: str, *, access_token: str, body: dict[str, object] | None = None
    ) -> GitHubRestResponse:
        response = self._responses.get((method, url))
        if response is None:
            raise AssertionError(f"no programmed response for {method} {url}")
        return response


def _program_precheck_get(
    transport: _FakeGitHubRestTransport,
    *,
    repository: str,
    issue_number: int,
    is_pull_request: bool = False,
) -> None:
    """update/close/reopen_issue always issue a GET precheck before the PATCH."""

    url = build_issue_get_request(repository=repository, issue_number=issue_number).url
    body: dict[str, object] = {"number": issue_number, "title": "Existing", "state": "open"}
    if is_pull_request:
        body["pull_request"] = {"url": "https://api.github.com/repos/o/r/pulls/1"}
    transport.program(url, GitHubRestResponse(status_code=200, body=body), method="GET")


def _state_with_fake_provider(transport: _FakeGitHubRestTransport) -> github_server._GitHubState:
    state = github_server._GitHubState()
    clock = FakeClock(1_000_000)
    keyring = FakeKeyring()
    keyring.set_secret(service="test/github", account="refresh-token", secret="stored")
    credential_provider = GitHubCredentialProvider(
        keyring=keyring,
        device_flow=GitHubDeviceFlowClient(client_id="Iv1.test-app", scope="", now_ms=clock.now_ms),
        now_ms=clock.now_ms,
        keyring_service="test/github",
        keyring_account="refresh-token",
    )
    credential_provider._adopt_tokens(  # noqa: SLF001 - test seam, avoids a real refresh call
        access_token="valid-access-token",
        access_token_expires_at_ms=clock.now_ms() + 3_600_000,
        refresh_token=None,
    )
    state._issue_provider = GitHubIssueProviderAdapter(  # noqa: SLF001 - injects the fake transport
        credential_provider=credential_provider, transport=transport
    )
    return state


def test_github_get_issue_handler_rejects_a_pull_request() -> None:
    transport = _FakeGitHubRestTransport()
    url = build_issue_get_request(repository="octo-org/octo-repo", issue_number=7).url
    transport.program(
        url,
        GitHubRestResponse(
            status_code=200,
            body={
                "number": 7,
                "title": "Add feature",
                "state": "open",
                "pull_request": {"url": "https://api.github.com/repos/o/r/pulls/7"},
            },
        ),
    )
    state = _state_with_fake_provider(transport)

    with pytest.raises(GitHubProviderError) as captured:
        github_server._github_get_issue(
            state, {"repository": "octo-org/octo-repo", "issue_number": 7}
        )

    assert captured.value.safe_code == "NOT_FOUND"


def test_github_get_issue_handler_normalizes_a_real_issue() -> None:
    transport = _FakeGitHubRestTransport()
    url = build_issue_get_request(repository="octo-org/octo-repo", issue_number=7).url
    transport.program(
        url,
        GitHubRestResponse(
            status_code=200, body={"number": 7, "title": "Add feature", "state": "open"}
        ),
    )
    state = _state_with_fake_provider(transport)

    payload = github_server._github_get_issue(
        state, {"repository": "octo-org/octo-repo", "issue_number": 7}
    )

    assert payload["external_resource_id"] == "octo-org/octo-repo#7"
    assert payload["title"] == "Add feature"


def test_github_list_issues_handler_excludes_pull_requests_from_the_result() -> None:
    transport = _FakeGitHubRestTransport()
    url = build_issue_list_request(GitHubIssueListQuery(repository="octo-org/octo-repo")).url
    transport.program(
        url,
        GitHubRestResponse(
            status_code=200,
            body=[
                {"number": 1, "title": "Real issue", "state": "open"},
                {
                    "number": 2,
                    "title": "A PR",
                    "state": "open",
                    "pull_request": {"url": "https://api.github.com/repos/o/r/pulls/2"},
                },
            ],
        ),
    )
    state = _state_with_fake_provider(transport)

    payload = github_server._github_list_issues(state, {"repository": "octo-org/octo-repo"})

    items = cast(list[dict[str, object]], payload["items"])
    issue_numbers = [item["issue_number"] for item in items]
    assert issue_numbers == [1]


# --- WRITE handlers --------------------------------------------------------


def test_github_create_issue_handler_is_active() -> None:
    transport = _FakeGitHubRestTransport()
    create = GitHubIssueCreateInput(repository="octo-org/octo-repo", title="Bug", body="Steps")
    url = build_issue_create_request(create).url
    transport.program(
        url,
        GitHubRestResponse(status_code=201, body={"number": 9, "title": "Bug", "state": "open"}),
        method="POST",
    )
    state = _state_with_fake_provider(transport)

    payload = github_server._github_create_issue(
        state, {"repository": "octo-org/octo-repo", "title": "Bug", "body": "Steps"}
    )

    assert payload["external_resource_id"] == "octo-org/octo-repo#9"
    assert payload["title"] == "Bug"


def test_github_update_issue_handler_is_active() -> None:
    transport = _FakeGitHubRestTransport()
    update = GitHubIssueUpdateInput(repository="octo-org/octo-repo", issue_number=9, title="New")
    _program_precheck_get(transport, repository="octo-org/octo-repo", issue_number=9)
    url = build_issue_update_request(update).url
    transport.program(
        url,
        GitHubRestResponse(status_code=200, body={"number": 9, "title": "New", "state": "open"}),
        method="PATCH",
    )
    state = _state_with_fake_provider(transport)

    payload = github_server._github_update_issue(
        state, {"repository": "octo-org/octo-repo", "issue_number": 9, "title": "New"}
    )

    assert payload["title"] == "New"


def test_github_update_issue_handler_rejects_empty_mutation() -> None:
    """No title and no body must fail before any REST call -- not become a
    no-op PATCH.
    """

    state = _state_with_fake_provider(_FakeGitHubRestTransport())

    with pytest.raises(GitHubIssueQueryError) as captured:
        github_server._github_update_issue(
            state, {"repository": "octo-org/octo-repo", "issue_number": 9}
        )

    assert captured.value.safe_code == "EMPTY_UPDATE"


def test_github_close_issue_handler_is_active() -> None:
    transport = _FakeGitHubRestTransport()
    change = GitHubIssueStateChangeInput(repository="octo-org/octo-repo", issue_number=9)
    _program_precheck_get(transport, repository="octo-org/octo-repo", issue_number=9)
    url = build_issue_close_request(change).url
    transport.program(
        url,
        GitHubRestResponse(status_code=200, body={"number": 9, "title": "Bug", "state": "closed"}),
        method="PATCH",
    )
    state = _state_with_fake_provider(transport)

    payload = github_server._github_close_issue(
        state, {"repository": "octo-org/octo-repo", "issue_number": 9}
    )

    assert payload["task_state"] == "CLOSED"


def test_github_reopen_issue_handler_is_active() -> None:
    transport = _FakeGitHubRestTransport()
    change = GitHubIssueStateChangeInput(repository="octo-org/octo-repo", issue_number=9)
    _program_precheck_get(transport, repository="octo-org/octo-repo", issue_number=9)
    url = build_issue_reopen_request(change).url
    transport.program(
        url,
        GitHubRestResponse(status_code=200, body={"number": 9, "title": "Bug", "state": "open"}),
        method="PATCH",
    )
    state = _state_with_fake_provider(transport)

    payload = github_server._github_reopen_issue(
        state, {"repository": "octo-org/octo-repo", "issue_number": 9}
    )

    assert payload["task_state"] == "OPEN"


def test_github_close_issue_handler_rejects_a_pull_request_before_dispatching_patch() -> None:
    """A PR can be mutated via the Issues PATCH endpoint too. The Provider
    Adapter's GET precheck must reject it before any PATCH is dispatched --
    if the PATCH were programmed here and actually called, the fake
    transport would raise instead of the expected GitHubProviderError.
    """

    transport = _FakeGitHubRestTransport()
    _program_precheck_get(
        transport, repository="octo-org/octo-repo", issue_number=2, is_pull_request=True
    )
    state = _state_with_fake_provider(transport)

    with pytest.raises(GitHubProviderError) as captured:
        github_server._github_close_issue(
            state, {"repository": "octo-org/octo-repo", "issue_number": 2}
        )

    assert captured.value.safe_code == "NOT_FOUND"
    assert captured.value.dispatch_started is False
