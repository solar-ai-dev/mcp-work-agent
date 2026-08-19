"""GitHub Issue WRITE Verification Observation Adapter.

Provider-specific observation only: fetches the current GitHub state of an
Issue after a WRITE mutation and normalizes it, so the existing shared
Verification/Recovery Runtime can compare it against an expected value.

This module never:
  - decides PASS/FAIL/UNKNOWN_RESULT,
  - retries or replays a mutation,
  - calls create_issue/update_issue/close_issue/reopen_issue.

Verification strategy is already frozen per-tool in
`domain/github_tool_registry.py` (GITHUB-1): CREATE/UPDATE/CLOSE/REOPEN are
all `verification_policy=GET_COMPARE`, never `GET_ABSENT` -- CLOSE is a
state change, not a deletion. This module supplies the "actual" side of
that comparison; it does not perform the comparison itself.

Runtime wiring into the shared Verification/Recovery framework (feeding
these observations into that framework's expected/actual comparison) is a
later step -- nothing here is imported by that Runtime yet.
"""

from __future__ import annotations

from typing import Protocol

from google_work_agent.mcp.github_issue_provider import (
    GitHubIssueTaskView,
    normalize_github_issue,
)


class GitHubIssueReadOnlyProvider(Protocol):
    """The only Provider capability Verification observation may use.

    Deliberately narrower than `GitHubIssueProviderAdapter`'s full
    interface -- it has no create_issue/update_issue/close_issue/
    reopen_issue methods, so any function typed against this Protocol
    cannot dispatch a mutation even by mistake. `GitHubIssueProviderAdapter`
    already satisfies this structurally; no new REST client is introduced.
    """

    def get_issue(self, *, repository: str, issue_number: int) -> dict[str, object]:
        """Return the raw GitHub Issue DTO for one repository-scoped issue."""


def observe_issue(
    provider: GitHubIssueReadOnlyProvider, *, repository: str, issue_number: int
) -> GitHubIssueTaskView:
    """GET the current Provider state and normalize it -- observation only.

    Raises the existing `GitHubProviderError` vocabulary unchanged
    (NOT_FOUND/REAUTH_REQUIRED/PERMISSION_DENIED/RATE_LIMITED/UPSTREAM_5XX/
    MCP_UNAVAILABLE/MALFORMED_RESPONSE). A Pull Request response is rejected
    the same way a READ would reject it (`normalize_github_issue`'s existing
    PR guard) -- it is never returned as an Issue observation.
    """

    raw = provider.get_issue(repository=repository, issue_number=issue_number)
    return normalize_github_issue(raw, repository=repository)


def observe_create_result(
    provider: GitHubIssueReadOnlyProvider, *, repository: str, issue_number: int
) -> GitHubIssueTaskView:
    """CREATE verification observation (GET_COMPARE) -- the created Issue."""

    return observe_issue(provider, repository=repository, issue_number=issue_number)


def observe_update_result(
    provider: GitHubIssueReadOnlyProvider, *, repository: str, issue_number: int
) -> GitHubIssueTaskView:
    """UPDATE verification observation (GET_COMPARE) -- current title/body/state."""

    return observe_issue(provider, repository=repository, issue_number=issue_number)


def observe_close_result(
    provider: GitHubIssueReadOnlyProvider, *, repository: str, issue_number: int
) -> GitHubIssueTaskView:
    """CLOSE verification observation (GET_COMPARE, expected task_state == CLOSED).

    Never GET_ABSENT -- closing an Issue is a state change, not a deletion.
    """

    return observe_issue(provider, repository=repository, issue_number=issue_number)


def observe_reopen_result(
    provider: GitHubIssueReadOnlyProvider, *, repository: str, issue_number: int
) -> GitHubIssueTaskView:
    """REOPEN verification observation (GET_COMPARE, expected task_state == OPEN)."""

    return observe_issue(provider, repository=repository, issue_number=issue_number)
