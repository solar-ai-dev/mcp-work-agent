from __future__ import annotations

from urllib.error import URLError

import pytest

from google_work_agent.mcp import github_issue_provider
from google_work_agent.mcp.github_auth import (
    GitHubCredentialProvider,
    GitHubDeviceFlowClient,
)
from google_work_agent.mcp.github_issue_provider import (
    GitHubIssueCreateInput,
    GitHubIssueListQuery,
    GitHubIssueProviderAdapter,
    GitHubIssueStateChangeInput,
    GitHubIssueUpdateInput,
    GitHubProviderError,
    GitHubRestResponse,
    UrllibGitHubRestTransport,
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


def _provider_with_valid_token(keyring: FakeKeyring, clock: FakeClock) -> GitHubCredentialProvider:
    keyring.set_secret(
        service="test/github", account="refresh-token", secret="stored-refresh-token"
    )
    provider = GitHubCredentialProvider(
        keyring=keyring,
        device_flow=GitHubDeviceFlowClient(
            client_id="Iv1.test-app", scope="", now_ms=clock.now_ms
        ),
        now_ms=clock.now_ms,
        keyring_service="test/github",
        keyring_account="refresh-token",
    )
    provider._adopt_tokens(  # noqa: SLF001 - test seam to avoid a real refresh call
        access_token="valid-access-token",
        access_token_expires_at_ms=clock.now_ms() + 3_600_000,
        refresh_token=None,
    )
    return provider


LIST_URL = build_issue_list_request(GitHubIssueListQuery(repository="octo-org/repo")).url
GET_URL = build_issue_get_request(repository="octo-org/repo", issue_number=1).url


def test_list_issues_returns_dict_items_on_success() -> None:
    keyring = FakeKeyring()
    clock = FakeClock(1_000_000)
    provider = _provider_with_valid_token(keyring, clock)
    transport = _FakeGitHubRestTransport()
    transport.program(
        LIST_URL,
        GitHubRestResponse(status_code=200, body=[{"number": 1, "title": "Bug"}]),
    )
    adapter = GitHubIssueProviderAdapter(credential_provider=provider, transport=transport)

    items = adapter.list_issues(GitHubIssueListQuery(repository="octo-org/repo"))

    assert items == [{"number": 1, "title": "Bug"}]


def test_get_issue_returns_dict_on_success() -> None:
    keyring = FakeKeyring()
    clock = FakeClock(1_000_000)
    provider = _provider_with_valid_token(keyring, clock)
    transport = _FakeGitHubRestTransport()
    transport.program(GET_URL, GitHubRestResponse(status_code=200, body={"number": 1}))
    adapter = GitHubIssueProviderAdapter(credential_provider=provider, transport=transport)

    result = adapter.get_issue(repository="octo-org/repo", issue_number=1)

    assert result == {"number": 1}


def test_list_issues_returns_empty_list_for_empty_repository() -> None:
    keyring = FakeKeyring()
    clock = FakeClock(1_000_000)
    provider = _provider_with_valid_token(keyring, clock)
    transport = _FakeGitHubRestTransport()
    transport.program(LIST_URL, GitHubRestResponse(status_code=200, body=[]))
    adapter = GitHubIssueProviderAdapter(credential_provider=provider, transport=transport)

    assert adapter.list_issues(GitHubIssueListQuery(repository="octo-org/repo")) == []


def test_get_issue_maps_404_to_not_found() -> None:
    keyring = FakeKeyring()
    clock = FakeClock(1_000_000)
    provider = _provider_with_valid_token(keyring, clock)
    transport = _FakeGitHubRestTransport()
    transport.program(GET_URL, GitHubRestResponse(status_code=404, body={"message": "Not Found"}))
    adapter = GitHubIssueProviderAdapter(credential_provider=provider, transport=transport)

    with pytest.raises(GitHubProviderError) as captured:
        adapter.get_issue(repository="octo-org/repo", issue_number=1)

    assert captured.value.safe_code == "NOT_FOUND"
    assert captured.value.dispatch_started is True


def test_get_issue_maps_403_to_permission_denied() -> None:
    keyring = FakeKeyring()
    clock = FakeClock(1_000_000)
    provider = _provider_with_valid_token(keyring, clock)
    transport = _FakeGitHubRestTransport()
    transport.program(GET_URL, GitHubRestResponse(status_code=403, body={"message": "Forbidden"}))
    adapter = GitHubIssueProviderAdapter(credential_provider=provider, transport=transport)

    with pytest.raises(GitHubProviderError) as captured:
        adapter.get_issue(repository="octo-org/repo", issue_number=1)

    assert captured.value.safe_code == "PERMISSION_DENIED"


def test_get_issue_maps_401_to_reauth_required_and_invalidates_cached_token() -> None:
    keyring = FakeKeyring()
    clock = FakeClock(1_000_000)
    provider = _provider_with_valid_token(keyring, clock)
    transport = _FakeGitHubRestTransport()
    transport.program(GET_URL, GitHubRestResponse(status_code=401, body={"message": "Bad creds"}))
    adapter = GitHubIssueProviderAdapter(credential_provider=provider, transport=transport)

    with pytest.raises(GitHubProviderError) as captured:
        adapter.get_issue(repository="octo-org/repo", issue_number=1)

    assert captured.value.safe_code == "REAUTH_REQUIRED"
    assert provider._access_token is None  # noqa: SLF001 - proves invalidation happened


def test_get_issue_maps_429_to_rate_limited() -> None:
    keyring = FakeKeyring()
    clock = FakeClock(1_000_000)
    provider = _provider_with_valid_token(keyring, clock)
    transport = _FakeGitHubRestTransport()
    transport.program(GET_URL, GitHubRestResponse(status_code=429, body={"message": "abuse"}))
    adapter = GitHubIssueProviderAdapter(credential_provider=provider, transport=transport)

    with pytest.raises(GitHubProviderError) as captured:
        adapter.get_issue(repository="octo-org/repo", issue_number=1)

    assert captured.value.safe_code == "RATE_LIMITED"


def test_get_issue_maps_5xx_to_upstream_5xx() -> None:
    keyring = FakeKeyring()
    clock = FakeClock(1_000_000)
    provider = _provider_with_valid_token(keyring, clock)
    transport = _FakeGitHubRestTransport()
    transport.program(GET_URL, GitHubRestResponse(status_code=503, body=None))
    adapter = GitHubIssueProviderAdapter(credential_provider=provider, transport=transport)

    with pytest.raises(GitHubProviderError) as captured:
        adapter.get_issue(repository="octo-org/repo", issue_number=1)

    assert captured.value.safe_code == "UPSTREAM_5XX"


def test_get_issue_rejects_malformed_success_body() -> None:
    keyring = FakeKeyring()
    clock = FakeClock(1_000_000)
    provider = _provider_with_valid_token(keyring, clock)
    transport = _FakeGitHubRestTransport()
    transport.program(GET_URL, GitHubRestResponse(status_code=200, body=["not", "an", "object"]))
    adapter = GitHubIssueProviderAdapter(credential_provider=provider, transport=transport)

    with pytest.raises(GitHubProviderError) as captured:
        adapter.get_issue(repository="octo-org/repo", issue_number=1)

    assert captured.value.safe_code == "MALFORMED_RESPONSE"


def test_list_issues_rejects_malformed_success_body() -> None:
    keyring = FakeKeyring()
    clock = FakeClock(1_000_000)
    provider = _provider_with_valid_token(keyring, clock)
    transport = _FakeGitHubRestTransport()
    transport.program(LIST_URL, GitHubRestResponse(status_code=200, body={"not": "a list"}))
    adapter = GitHubIssueProviderAdapter(credential_provider=provider, transport=transport)

    with pytest.raises(GitHubProviderError) as captured:
        adapter.list_issues(GitHubIssueListQuery(repository="octo-org/repo"))

    assert captured.value.safe_code == "MALFORMED_RESPONSE"


# --- WRITE ---------------------------------------------------------------


def test_create_issue_succeeds() -> None:
    keyring = FakeKeyring()
    clock = FakeClock(1_000_000)
    provider = _provider_with_valid_token(keyring, clock)
    transport = _FakeGitHubRestTransport()
    create = GitHubIssueCreateInput(repository="octo-org/repo", title="Bug", body="Steps...")
    url = build_issue_create_request(create).url
    transport.program(
        url, GitHubRestResponse(status_code=201, body={"number": 9, "title": "Bug"}), method="POST"
    )
    adapter = GitHubIssueProviderAdapter(credential_provider=provider, transport=transport)

    result = adapter.create_issue(create)

    assert result == {"number": 9, "title": "Bug"}
    assert transport.calls == [("POST", url)]


def _program_precheck_get(
    transport: _FakeGitHubRestTransport,
    *,
    repository: str,
    issue_number: int,
    is_pull_request: bool = False,
) -> None:
    """Program the GET precheck `update/close/reopen_issue` always issue first."""

    url = build_issue_get_request(repository=repository, issue_number=issue_number).url
    body: dict[str, object] = {
        "number": issue_number,
        "title": "Existing issue",
        "state": "open",
    }
    if is_pull_request:
        body["pull_request"] = {"url": "https://api.github.com/repos/o/r/pulls/1"}
    transport.program(url, GitHubRestResponse(status_code=200, body=body), method="GET")


def test_update_issue_title_succeeds() -> None:
    keyring = FakeKeyring()
    clock = FakeClock(1_000_000)
    provider = _provider_with_valid_token(keyring, clock)
    transport = _FakeGitHubRestTransport()
    update = GitHubIssueUpdateInput(repository="octo-org/repo", issue_number=9, title="New title")
    _program_precheck_get(transport, repository="octo-org/repo", issue_number=9)
    url = build_issue_update_request(update).url
    transport.program(
        url,
        GitHubRestResponse(status_code=200, body={"number": 9, "title": "New title"}),
        method="PATCH",
    )
    adapter = GitHubIssueProviderAdapter(credential_provider=provider, transport=transport)

    result = adapter.update_issue(update)

    assert result == {"number": 9, "title": "New title"}
    get_url = build_issue_get_request(repository="octo-org/repo", issue_number=9).url
    assert transport.calls == [("GET", get_url), ("PATCH", url)]


def test_update_issue_body_succeeds() -> None:
    keyring = FakeKeyring()
    clock = FakeClock(1_000_000)
    provider = _provider_with_valid_token(keyring, clock)
    transport = _FakeGitHubRestTransport()
    update = GitHubIssueUpdateInput(repository="octo-org/repo", issue_number=9, body="Updated body")
    _program_precheck_get(transport, repository="octo-org/repo", issue_number=9)
    url = build_issue_update_request(update).url
    transport.program(
        url,
        GitHubRestResponse(status_code=200, body={"number": 9, "body": "Updated body"}),
        method="PATCH",
    )
    adapter = GitHubIssueProviderAdapter(credential_provider=provider, transport=transport)

    result = adapter.update_issue(update)

    assert result == {"number": 9, "body": "Updated body"}


def test_close_issue_succeeds() -> None:
    keyring = FakeKeyring()
    clock = FakeClock(1_000_000)
    provider = _provider_with_valid_token(keyring, clock)
    transport = _FakeGitHubRestTransport()
    change = GitHubIssueStateChangeInput(repository="octo-org/repo", issue_number=9)
    _program_precheck_get(transport, repository="octo-org/repo", issue_number=9)
    url = build_issue_close_request(change).url
    transport.program(
        url,
        GitHubRestResponse(status_code=200, body={"number": 9, "state": "closed"}),
        method="PATCH",
    )
    adapter = GitHubIssueProviderAdapter(credential_provider=provider, transport=transport)

    result = adapter.close_issue(change)

    assert result == {"number": 9, "state": "closed"}


def test_reopen_issue_succeeds() -> None:
    keyring = FakeKeyring()
    clock = FakeClock(1_000_000)
    provider = _provider_with_valid_token(keyring, clock)
    transport = _FakeGitHubRestTransport()
    change = GitHubIssueStateChangeInput(repository="octo-org/repo", issue_number=9)
    _program_precheck_get(transport, repository="octo-org/repo", issue_number=9)
    url = build_issue_reopen_request(change).url
    transport.program(
        url,
        GitHubRestResponse(status_code=200, body={"number": 9, "state": "open"}),
        method="PATCH",
    )
    adapter = GitHubIssueProviderAdapter(credential_provider=provider, transport=transport)

    result = adapter.reopen_issue(change)

    assert result == {"number": 9, "state": "open"}


# --- PR-target write safety (must reject before any PATCH is dispatched) --


@pytest.mark.parametrize(
    "mutate_method",
    ("close_issue", "reopen_issue"),
)
def test_state_change_rejects_a_pull_request_target_before_dispatching_patch(
    mutate_method: str,
) -> None:
    keyring = FakeKeyring()
    clock = FakeClock(1_000_000)
    provider = _provider_with_valid_token(keyring, clock)
    transport = _FakeGitHubRestTransport()
    change = GitHubIssueStateChangeInput(repository="octo-org/repo", issue_number=2)
    _program_precheck_get(
        transport, repository="octo-org/repo", issue_number=2, is_pull_request=True
    )
    adapter = GitHubIssueProviderAdapter(credential_provider=provider, transport=transport)

    with pytest.raises(GitHubProviderError) as captured:
        getattr(adapter, mutate_method)(change)

    assert captured.value.safe_code == "NOT_FOUND"
    assert captured.value.dispatch_started is False
    patch_calls = [call for call in transport.calls if call[0] == "PATCH"]
    assert patch_calls == []


def test_update_issue_rejects_a_pull_request_target_before_dispatching_patch() -> None:
    keyring = FakeKeyring()
    clock = FakeClock(1_000_000)
    provider = _provider_with_valid_token(keyring, clock)
    transport = _FakeGitHubRestTransport()
    update = GitHubIssueUpdateInput(repository="octo-org/repo", issue_number=2, title="X")
    _program_precheck_get(
        transport, repository="octo-org/repo", issue_number=2, is_pull_request=True
    )
    adapter = GitHubIssueProviderAdapter(credential_provider=provider, transport=transport)

    with pytest.raises(GitHubProviderError) as captured:
        adapter.update_issue(update)

    assert captured.value.safe_code == "NOT_FOUND"
    assert captured.value.dispatch_started is False
    patch_calls = [call for call in transport.calls if call[0] == "PATCH"]
    assert patch_calls == []


def test_state_change_dispatches_exactly_one_mutation_for_a_real_issue() -> None:
    keyring = FakeKeyring()
    clock = FakeClock(1_000_000)
    provider = _provider_with_valid_token(keyring, clock)
    transport = _FakeGitHubRestTransport()
    change = GitHubIssueStateChangeInput(repository="octo-org/repo", issue_number=9)
    _program_precheck_get(transport, repository="octo-org/repo", issue_number=9)
    url = build_issue_close_request(change).url
    transport.program(
        url,
        GitHubRestResponse(status_code=200, body={"number": 9, "state": "closed"}),
        method="PATCH",
    )
    adapter = GitHubIssueProviderAdapter(credential_provider=provider, transport=transport)

    adapter.close_issue(change)

    patch_calls = [call for call in transport.calls if call[0] == "PATCH"]
    assert len(patch_calls) == 1


def test_create_issue_is_exempt_from_the_pr_precheck() -> None:
    """create_issue has no existing target to check -- it must not issue a
    precheck GET at all.
    """

    keyring = FakeKeyring()
    clock = FakeClock(1_000_000)
    provider = _provider_with_valid_token(keyring, clock)
    transport = _FakeGitHubRestTransport()
    create = GitHubIssueCreateInput(repository="octo-org/repo", title="Bug")
    url = build_issue_create_request(create).url
    transport.program(url, GitHubRestResponse(status_code=201, body={"number": 9}), method="POST")
    adapter = GitHubIssueProviderAdapter(credential_provider=provider, transport=transport)

    adapter.create_issue(create)

    assert transport.calls == [("POST", url)]


def test_create_issue_maps_422_to_invalid_argument() -> None:
    keyring = FakeKeyring()
    clock = FakeClock(1_000_000)
    provider = _provider_with_valid_token(keyring, clock)
    transport = _FakeGitHubRestTransport()
    create = GitHubIssueCreateInput(repository="octo-org/repo", title="Bug")
    url = build_issue_create_request(create).url
    transport.program(
        url,
        GitHubRestResponse(status_code=422, body={"message": "Validation Failed"}),
        method="POST",
    )
    adapter = GitHubIssueProviderAdapter(credential_provider=provider, transport=transport)

    with pytest.raises(GitHubProviderError) as captured:
        adapter.create_issue(create)

    assert captured.value.safe_code == "INVALID_ARGUMENT"
    assert captured.value.dispatch_started is True


def test_close_issue_maps_401_on_the_mutation_to_reauth_required_and_invalidates_token() -> None:
    keyring = FakeKeyring()
    clock = FakeClock(1_000_000)
    provider = _provider_with_valid_token(keyring, clock)
    transport = _FakeGitHubRestTransport()
    change = GitHubIssueStateChangeInput(repository="octo-org/repo", issue_number=9)
    _program_precheck_get(transport, repository="octo-org/repo", issue_number=9)
    url = build_issue_close_request(change).url
    transport.program(
        url, GitHubRestResponse(status_code=401, body={"message": "Bad creds"}), method="PATCH"
    )
    adapter = GitHubIssueProviderAdapter(credential_provider=provider, transport=transport)

    with pytest.raises(GitHubProviderError) as captured:
        adapter.close_issue(change)

    assert captured.value.safe_code == "REAUTH_REQUIRED"
    assert captured.value.dispatch_started is True
    assert provider._access_token is None  # noqa: SLF001 - proves invalidation happened


def test_close_issue_maps_401_on_the_precheck_get_to_reauth_required_without_a_patch() -> None:
    keyring = FakeKeyring()
    clock = FakeClock(1_000_000)
    provider = _provider_with_valid_token(keyring, clock)
    transport = _FakeGitHubRestTransport()
    change = GitHubIssueStateChangeInput(repository="octo-org/repo", issue_number=9)
    get_url = build_issue_get_request(repository="octo-org/repo", issue_number=9).url
    transport.program(
        get_url, GitHubRestResponse(status_code=401, body={"message": "Bad creds"}), method="GET"
    )
    adapter = GitHubIssueProviderAdapter(credential_provider=provider, transport=transport)

    with pytest.raises(GitHubProviderError) as captured:
        adapter.close_issue(change)

    assert captured.value.safe_code == "REAUTH_REQUIRED"
    assert captured.value.dispatch_started is False
    patch_calls = [call for call in transport.calls if call[0] == "PATCH"]
    assert patch_calls == []


def test_get_issue_maps_missing_refresh_token_to_reauth_required_without_any_http_call() -> None:
    keyring = FakeKeyring()
    clock = FakeClock(1_000_000)
    provider = GitHubCredentialProvider(
        keyring=keyring,
        device_flow=GitHubDeviceFlowClient(
            client_id="Iv1.test-app", scope="", now_ms=clock.now_ms
        ),
        now_ms=clock.now_ms,
        keyring_service="test/github",
        keyring_account="refresh-token",
    )
    transport = _FakeGitHubRestTransport()
    adapter = GitHubIssueProviderAdapter(credential_provider=provider, transport=transport)

    with pytest.raises(GitHubProviderError) as captured:
        adapter.get_issue(repository="octo-org/repo", issue_number=1)

    assert captured.value.safe_code == "REAUTH_REQUIRED"
    assert transport.calls == []


# --- Transport dispatch_started semantics (write safety, section 9) ------


def test_real_transport_marks_dispatch_started_true_on_network_failure_for_a_mutation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A mutation whose bytes may already be in flight when the network call
    fails must never be reported as safely-not-sent -- callers must not
    blindly retry it.
    """

    def fail(*_: object, **__: object) -> object:
        raise URLError("connection reset")

    monkeypatch.setattr(github_issue_provider, "urlopen", fail)
    transport = UrllibGitHubRestTransport()

    with pytest.raises(GitHubProviderError) as captured:
        transport.request("POST", "https://api.github.com/repos/o/r/issues", access_token="t")

    assert captured.value.safe_code == "MCP_UNAVAILABLE"
    assert captured.value.dispatch_started is True


def test_real_transport_marks_dispatch_started_false_on_network_failure_for_a_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail(*_: object, **__: object) -> object:
        raise URLError("connection reset")

    monkeypatch.setattr(github_issue_provider, "urlopen", fail)
    transport = UrllibGitHubRestTransport()

    with pytest.raises(GitHubProviderError) as captured:
        transport.request("GET", "https://api.github.com/repos/o/r/issues/1", access_token="t")

    assert captured.value.dispatch_started is False
