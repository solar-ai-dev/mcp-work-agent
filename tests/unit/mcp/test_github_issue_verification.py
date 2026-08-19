"""Focused tests for the GitHub Issue Verification Observation Adapter.

Two layers, per GITHUB-3B section 12:
  - _FakeReadOnlyProvider: proves the adapter functions are typed/tested
    against a provider that structurally CANNOT expose a mutation method.
  - real GitHubIssueProviderAdapter + fake REST transport: proves the real
    provider satisfies the narrow Protocol and that observation never
    dispatches create/update/close/reopen against it.
"""

from __future__ import annotations

import pytest

from google_work_agent.mcp.github_auth import GitHubCredentialProvider, GitHubDeviceFlowClient
from google_work_agent.mcp.github_issue_provider import (
    GitHubIssueProviderAdapter,
    GitHubIssueTaskState,
    GitHubIssueTaskView,
    GitHubProviderError,
    GitHubRestResponse,
    build_issue_get_request,
)
from google_work_agent.mcp.github_issue_verification import (
    GitHubIssueReadOnlyProvider,
    observe_close_result,
    observe_create_result,
    observe_issue,
    observe_reopen_result,
    observe_update_result,
)
from tests.support.fakes.clock import FakeClock
from tests.support.fakes.keyring import FakeKeyring


class _FakeReadOnlyProvider:
    """Deliberately has ONLY get_issue -- no create/update/close/reopen exist
    on this type at all, so an accidental mutation call is an AttributeError.
    """

    def __init__(
        self, *, response: dict[str, object] | None = None, error: Exception | None = None
    ) -> None:
        self._response = response
        self._error = error
        self.get_issue_calls: list[tuple[str, int]] = []

    def get_issue(self, *, repository: str, issue_number: int) -> dict[str, object]:
        self.get_issue_calls.append((repository, issue_number))
        if self._error is not None:
            raise self._error
        assert self._response is not None
        return self._response


def _issue_body(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "number": 9,
        "title": "Bug",
        "body": "Steps",
        "state": "open",
        "html_url": "https://github.com/octo-org/octo-repo/issues/9",
    }
    base.update(overrides)
    return base


# --- 12-1..12-4: observation shape per WRITE kind -------------------------


def test_observe_create_result_returns_normalized_issue_view() -> None:
    provider = _FakeReadOnlyProvider(response=_issue_body())

    view = observe_create_result(provider, repository="octo-org/octo-repo", issue_number=9)

    assert view.resource_identity.external_resource_id == "octo-org/octo-repo#9"
    assert view.title == "Bug"
    assert view.description == "Steps"
    assert view.task_state is GitHubIssueTaskState.OPEN
    assert provider.get_issue_calls == [("octo-org/octo-repo", 9)]


def test_observe_update_result_returns_current_title_body_state() -> None:
    provider = _FakeReadOnlyProvider(response=_issue_body(title="New title", body="New body"))

    view = observe_update_result(provider, repository="octo-org/octo-repo", issue_number=9)

    assert view.title == "New title"
    assert view.description == "New body"


def test_observe_close_result_observes_closed_state() -> None:
    provider = _FakeReadOnlyProvider(response=_issue_body(state="closed"))

    view = observe_close_result(provider, repository="octo-org/octo-repo", issue_number=9)

    assert view.task_state is GitHubIssueTaskState.CLOSED


def test_observe_reopen_result_observes_open_state() -> None:
    provider = _FakeReadOnlyProvider(response=_issue_body(state="open"))

    view = observe_reopen_result(provider, repository="octo-org/octo-repo", issue_number=9)

    assert view.task_state is GitHubIssueTaskState.OPEN


# --- 12-5: failure propagation (existing Provider error vocabulary) ------


@pytest.mark.parametrize(
    ("safe_code", "dispatch_started"),
    (
        ("NOT_FOUND", True),
        ("REAUTH_REQUIRED", True),
        ("PERMISSION_DENIED", True),
        ("RATE_LIMITED", True),
        ("UPSTREAM_5XX", True),
        ("MCP_UNAVAILABLE", False),
        ("MALFORMED_RESPONSE", True),
    ),
)
def test_observe_issue_propagates_existing_provider_errors_unchanged(
    safe_code: str, dispatch_started: bool
) -> None:
    provider = _FakeReadOnlyProvider(
        error=GitHubProviderError(safe_code, dispatch_started=dispatch_started)
    )

    with pytest.raises(GitHubProviderError) as captured:
        observe_issue(provider, repository="octo-org/octo-repo", issue_number=9)

    assert captured.value.safe_code == safe_code
    assert captured.value.dispatch_started is dispatch_started


def test_observe_issue_rejects_a_pull_request_response() -> None:
    provider = _FakeReadOnlyProvider(
        response=_issue_body(
            pull_request={"url": "https://api.github.com/repos/o/r/pulls/9"}
        )
    )

    with pytest.raises(GitHubProviderError) as captured:
        observe_issue(provider, repository="octo-org/octo-repo", issue_number=9)

    assert captured.value.safe_code == "NOT_FOUND"


# --- 12-6: no workflow decision -------------------------------------------


def test_observation_functions_only_return_a_task_view_or_raise() -> None:
    """The adapter's return type carries no PASS/FAIL/UNKNOWN_RESULT/RETRY
    concept -- it is exactly the same GitHubIssueTaskView READ already
    returns, with no extra verdict field.
    """

    field_names = set(GitHubIssueTaskView.__dataclass_fields__)

    forbidden = {"pass", "fail", "verdict", "unknown_result", "retry", "recovery"}
    assert field_names.isdisjoint(forbidden)


def test_read_only_provider_protocol_has_no_mutation_methods() -> None:
    mutation_methods = {"create_issue", "update_issue", "close_issue", "reopen_issue"}
    protocol_methods = {
        name for name in vars(GitHubIssueReadOnlyProvider) if not name.startswith("_")
    }
    assert protocol_methods.isdisjoint(mutation_methods)
    assert protocol_methods == {"get_issue"}


# --- Real GitHubIssueProviderAdapter: structural fit + mutation isolation -


class _FakeGitHubRestTransport:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []
        self._responses: dict[tuple[str, str], GitHubRestResponse] = {}

    def program(self, url: str, response: GitHubRestResponse, *, method: str = "GET") -> None:
        self._responses[(method, url)] = response

    def request(
        self, method: str, url: str, *, access_token: str, body: dict[str, object] | None = None
    ) -> GitHubRestResponse:
        self.calls.append((method, url))
        response = self._responses.get((method, url))
        if response is None:
            raise AssertionError(f"no programmed response for {method} {url}")
        return response


def _real_provider_with_valid_token(
    transport: _FakeGitHubRestTransport,
) -> GitHubIssueProviderAdapter:
    keyring = FakeKeyring()
    keyring.set_secret(service="test/github", account="refresh-token", secret="stored")
    clock = FakeClock(1_000_000)
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
    return GitHubIssueProviderAdapter(credential_provider=credential_provider, transport=transport)


def test_real_provider_adapter_satisfies_the_read_only_protocol_with_zero_mutations() -> None:
    """A real GitHubIssueProviderAdapter (which DOES have mutation methods)
    must still only be GET-called across all four observation entry points.
    """

    transport = _FakeGitHubRestTransport()
    get_url = build_issue_get_request(repository="octo-org/octo-repo", issue_number=9).url
    transport.program(get_url, GitHubRestResponse(status_code=200, body=_issue_body()))
    provider: GitHubIssueReadOnlyProvider = _real_provider_with_valid_token(transport)

    observe_create_result(provider, repository="octo-org/octo-repo", issue_number=9)
    observe_update_result(provider, repository="octo-org/octo-repo", issue_number=9)
    observe_close_result(provider, repository="octo-org/octo-repo", issue_number=9)
    observe_reopen_result(provider, repository="octo-org/octo-repo", issue_number=9)

    assert transport.calls == [("GET", get_url)] * 4
    mutation_calls = [call for call in transport.calls if call[0] != "GET"]
    assert mutation_calls == []
