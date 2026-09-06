from __future__ import annotations

from typing import Any

import pytest

from google_work_agent.adapters.connectors.github.github.mcp_server.credential_provider import (
    GitHubCredentialProvider,
)
from google_work_agent.adapters.connectors.github.github.mcp_server.github_api import (
    GitHubApiClient,
    GitHubProviderError,
    GitHubRestResponse,
)
from google_work_agent.adapters.connectors.github.issues.issues.close_issue import (
    CloseIssueOperation,
    build_issue_close_request,
)
from google_work_agent.adapters.connectors.github.issues.issues.create_issue import (
    CreateIssueOperation,
    build_issue_create_request,
)
from google_work_agent.adapters.connectors.github.issues.issues.get_issue import (
    GetIssueOperation,
    observe_issue,
)
from google_work_agent.adapters.connectors.github.issues.issues.issue_contract import (
    RESOURCE_TYPE,
    GitHubIssueCreateInput,
    GitHubIssueFilterState,
    GitHubIssueListQuery,
    GitHubIssueQueryError,
    GitHubIssueStateChangeInput,
)
from google_work_agent.adapters.connectors.github.issues.issues.list_issues import (
    ListIssuesOperation,
    build_issue_list_request,
)
from google_work_agent.adapters.connectors.github.issues.issues.reopen_issue import (
    ReopenIssueOperation,
)
from google_work_agent.adapters.connectors.github.issues.issues.search_by_recovery_fingerprint import (  # noqa: E501
    SearchByRecoveryFingerprintOperation,
)
from google_work_agent.adapters.connectors.github.issues.issues.update_issue import (
    UpdateIssueOperation,
)
from google_work_agent.ports.connector.contracts.google_workspace import DeliveryCertainty


class _Credentials(GitHubCredentialProvider):
    def __init__(self) -> None:
        self.invalidations = 0

    def get_access_token(self) -> str:
        return "token"

    def invalidate_access_token(self) -> None:
        self.invalidations += 1


class _Transport:
    def __init__(self, *responses: GitHubRestResponse) -> None:
        self.responses = list(responses)
        self.calls: list[tuple[str, str, dict[str, object] | None]] = []

    def request(
        self,
        method: str,
        url: str,
        *,
        access_token: str,
        body: dict[str, object] | None = None,
    ) -> GitHubRestResponse:
        self.calls.append((method, url, body))
        return self.responses.pop(0)


def _issue(number: int = 7, *, state: str = "open") -> dict[str, object]:
    return {
        "number": number,
        "title": "Canonical placement",
        "body": "body",
        "state": state,
        "html_url": f"https://github.com/acme/repo/issues/{number}",
        "updated_at": "2026-09-03T00:00:00Z",
        "labels": [{"name": "b"}, {"name": "a"}],
        "assignees": [{"login": "octocat"}],
    }


def _api(*responses: GitHubRestResponse) -> tuple[GitHubApiClient, _Transport]:
    transport = _Transport(*responses)
    return GitHubApiClient(credential_provider=_Credentials(), transport=transport), transport


def test_list_request__is_typed__and_deterministic() -> None:
    request = build_issue_list_request(
        GitHubIssueListQuery(
            repository="acme/repo",
            state=GitHubIssueFilterState.ALL,
            assignee="octocat",
            label="bug",
        )
    )

    assert request.url == (
        "https://api.github.com/repos/acme/repo/issues?"
        "state=all&per_page=100&assignee=octocat&labels=bug"
    )


@pytest.mark.parametrize(
    "repository", ["acme/repo?x=1", "acme/..", "acme/a#b", "acme/r%2fo", " acme/repo"]
)
@pytest.mark.parametrize(
    "operation",
    [
        ListIssuesOperation,
        GetIssueOperation,
        CreateIssueOperation,
        UpdateIssueOperation,
        CloseIssueOperation,
        ReopenIssueOperation,
    ],
)
def test_issue_operations__invalid_repository__prevents_all_provider_io(
    repository: str,
    operation: type,
) -> None:
    api, transport = _api()
    with pytest.raises(GitHubIssueQueryError, match="REPOSITORY_INVALID"):
        operation(api).execute({"repository": repository, "issue_number": 7, "title": "Title"})
    assert transport.calls == []


@pytest.mark.parametrize(
    "changes",
    [
        {"html_url": "https://github.com/other/repo/issues/7"},
        {"number": 8},
        {"number": True},
        {"state": "unknown"},
    ],
)
def test_issue_precheck__wrong_provider_identity__prevents_mutation(
    changes: dict[str, object],
) -> None:
    api, transport = _api(GitHubRestResponse(200, {**_issue(), **changes}))
    with pytest.raises(GitHubProviderError):
        CloseIssueOperation(api).execute({"repository": "acme/repo", "issue_number": 7})
    assert [call[0] for call in transport.calls] == ["GET"]


def test_issue_create__wrong_response_identity__preserves_unknown_delivery() -> None:
    api, transport = _api(
        GitHubRestResponse(
            201,
            {
                **_issue(),
                "html_url": "https://github.com/other/repo/issues/7",
            },
        )
    )
    with pytest.raises(GitHubProviderError) as error:
        CreateIssueOperation(api).execute({"repository": "acme/repo", "title": "Title"})
    assert error.value.delivery_certainty is DeliveryCertainty.SENT_RESPONSE_LOST
    assert [call[0] for call in transport.calls] == ["POST"]


def test_list__excludes_pull_requests__and_projects_github_issue_identity() -> None:
    pull_request = {**_issue(8), "pull_request": {"url": "pr"}}
    api, _ = _api(GitHubRestResponse(200, [_issue(), pull_request]))

    result: Any = ListIssuesOperation(api).execute({"repository": "acme/repo"})

    assert len(result["items"]) == 1
    item = result["items"][0]
    assert item["resource_type"] == RESOURCE_TYPE
    assert item["resource_id"] == "acme/repo#7"
    assert item["payload"]["labels"] == ["a", "b"]


def test_get_observation__rejects_pull_request__before_projection() -> None:
    api, _ = _api(GitHubRestResponse(200, {**_issue(), "pull_request": {}}))

    with pytest.raises(GitHubProviderError, match="NOT_FOUND"):
        observe_issue(api, repository="acme/repo", issue_number=7)


def test_create__preserves_post_body__without_pr_precheck() -> None:
    request = build_issue_create_request(
        GitHubIssueCreateInput(repository="acme/repo", title="title", body="body")
    )
    api, transport = _api(GitHubRestResponse(201, _issue()))

    result: Any = CreateIssueOperation(api).execute(
        {"repository": "acme/repo", "title": "title", "body": "body"}
    )

    assert request.method == "POST"
    assert request.body == {"title": "title", "body": "body"}
    assert [call[0] for call in transport.calls] == ["POST"]
    assert result["item"]["resource_id"] == "acme/repo#7"


def test_create__injects_exact_recovery_marker__immediately_before_post() -> None:
    api, transport = _api(GitHubRestResponse(201, _issue()))

    CreateIssueOperation(api).execute(
        {
            "repository": "acme/repo",
            "title": "title",
            "body": "body",
            "recovery_fingerprint": "fingerprint-1",
        }
    )

    assert transport.calls == [
        (
            "POST",
            "https://api.github.com/repos/acme/repo/issues",
            {
                "title": "title",
                "body": "body\n\n<!-- gwa-recovery-fingerprint:fingerprint-1 -->",
            },
        )
    ]


def test_recovery_search__is_repo_bounded_and_exact__and_excludes_pull_requests() -> None:
    marker = "<!-- gwa-recovery-fingerprint:fingerprint-1 -->"
    matching = {**_issue(), "body": f"body\n\n{marker}"}
    pr = {**_issue(8), "body": marker, "pull_request": {"url": "pr"}}
    near_match = {**_issue(9), "body": "fingerprint-1"}
    api, transport = _api(
        GitHubRestResponse(
            200,
            {
                "total_count": 3,
                "incomplete_results": False,
                "items": [matching, pr, near_match],
            },
        )
    )

    result: Any = SearchByRecoveryFingerprintOperation(api).execute(
        {"repository": "acme/repo", "recovery_fingerprint": "fingerprint-1"}
    )

    assert [item["resource_id"] for item in result["items"]] == ["acme/repo#7"]
    assert result["coverage_complete"] is True
    assert "repo%3Aacme%2Frepo" in transport.calls[0][1]


@pytest.mark.parametrize(
    ("operation_type", "arguments"),
    [
        (
            UpdateIssueOperation,
            {"repository": "acme/repo", "issue_number": 7, "title": "changed"},
        ),
        (CloseIssueOperation, {"repository": "acme/repo", "issue_number": 7}),
        (ReopenIssueOperation, {"repository": "acme/repo", "issue_number": 7}),
    ],
)
def test_mutation__rejects_pull_request__before_patch(
    operation_type: type[UpdateIssueOperation]
    | type[CloseIssueOperation]
    | type[ReopenIssueOperation],
    arguments: dict[str, object],
) -> None:
    api, transport = _api(GitHubRestResponse(200, {**_issue(), "pull_request": {"url": "pr"}}))

    with pytest.raises(GitHubProviderError) as raised:
        operation_type(api).execute(arguments)

    assert raised.value.dispatch_started is False
    assert [call[0] for call in transport.calls] == ["GET"]


def test_update__prechecks_then_dispatches__typed_patch() -> None:
    changed = {**_issue(), "title": "changed"}
    api, transport = _api(GitHubRestResponse(200, _issue()), GitHubRestResponse(200, changed))

    result: Any = UpdateIssueOperation(api).execute(
        {"repository": "acme/repo", "issue_number": 7, "title": "changed"}
    )

    assert [call[0] for call in transport.calls] == ["GET", "PATCH"]
    assert transport.calls[1][2] == {"title": "changed"}
    assert result["item"]["payload"]["title"] == "changed"


def test_close__prechecks_then_dispatches__exactly_one_patch() -> None:
    closed = _issue(state="closed")
    api, transport = _api(GitHubRestResponse(200, _issue()), GitHubRestResponse(200, closed))

    result: Any = CloseIssueOperation(api).execute({"repository": "acme/repo", "issue_number": 7})

    assert [call[0] for call in transport.calls] == ["GET", "PATCH"]
    assert transport.calls[1][2] == {"state": "closed"}
    assert result["item"]["payload"]["state"] == "CLOSED"
    assert build_issue_close_request(GitHubIssueStateChangeInput("acme/repo", 7)).body == {
        "state": "closed"
    }


def test_reopen__prechecks_then_dispatches__open_patch() -> None:
    api, transport = _api(
        GitHubRestResponse(200, _issue(state="closed")),
        GitHubRestResponse(200, _issue(state="open")),
    )

    result: Any = ReopenIssueOperation(api).execute({"repository": "acme/repo", "issue_number": 7})

    assert [call[0] for call in transport.calls] == ["GET", "PATCH"]
    assert transport.calls[1][2] == {"state": "open"}
    assert result["item"]["payload"]["state"] == "OPEN"


def test_get_operation__maps_401__and_invalidates_access_token() -> None:
    credentials = _Credentials()
    transport = _Transport(GitHubRestResponse(401, {}))
    api = GitHubApiClient(credential_provider=credentials, transport=transport)

    with pytest.raises(GitHubProviderError, match="REAUTH_REQUIRED"):
        GetIssueOperation(api).execute({"repository": "acme/repo", "issue_number": 7})

    assert credentials.invalidations == 1


def test_mutation_http_failures__use_canonical__delivery_certainty() -> None:
    rejected, _ = _api(GitHubRestResponse(422, {}))
    ambiguous, _ = _api(GitHubRestResponse(500, {}))
    request = build_issue_create_request(GitHubIssueCreateInput("acme/repo", "title"))

    with pytest.raises(GitHubProviderError) as rejected_error:
        rejected.mutate(request)
    with pytest.raises(GitHubProviderError) as ambiguous_error:
        ambiguous.mutate(request)

    assert rejected_error.value.delivery_certainty is DeliveryCertainty.NOT_SENT
    assert ambiguous_error.value.delivery_certainty is DeliveryCertainty.MAY_HAVE_BEEN_SENT
