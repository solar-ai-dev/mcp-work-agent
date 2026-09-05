"""Typed GitHub Issue request contract shared by connector-local operations."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

GITHUB_API_BASE = "https://api.github.com"
GITHUB_ISSUE_LIST_PAGE_SIZE = "100"
PRODUCT = "issues"
RESOURCE_TYPE = "github_issue"
SEMANTIC_RESOURCE = "GITHUB_ISSUE"


class GitHubIssueQueryError(RuntimeError):
    def __init__(self, safe_code: str) -> None:
        super().__init__(safe_code)
        self.safe_code = safe_code


class GitHubIssueFilterState(StrEnum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    ALL = "ALL"


@dataclass(frozen=True, slots=True)
class GitHubIssueListQuery:
    repository: str
    state: GitHubIssueFilterState = GitHubIssueFilterState.OPEN
    assignee: str | None = None
    label: str | None = None

    def __post_init__(self) -> None:
        validate_repository(self.repository)
        if self.assignee is not None and not self.assignee.strip():
            raise GitHubIssueQueryError("ASSIGNEE_INVALID")
        if self.label is not None and not self.label.strip():
            raise GitHubIssueQueryError("LABEL_INVALID")


@dataclass(frozen=True, slots=True)
class GitHubIssueCreateInput:
    repository: str
    title: str
    body: str | None = None
    recovery_fingerprint: str | None = None

    def __post_init__(self) -> None:
        validate_repository(self.repository)
        if not self.title.strip():
            raise GitHubIssueQueryError("TITLE_INVALID")
        if self.recovery_fingerprint is not None and not self.recovery_fingerprint.strip():
            raise GitHubIssueQueryError("RECOVERY_FINGERPRINT_INVALID")


@dataclass(frozen=True, slots=True)
class GitHubIssueUpdateInput:
    repository: str
    issue_number: int
    title: str | None = None
    body: str | None = None

    def __post_init__(self) -> None:
        validate_repository(self.repository)
        validate_issue_number(self.issue_number)
        if self.title is None and self.body is None:
            raise GitHubIssueQueryError("EMPTY_UPDATE")
        if self.title is not None and not self.title.strip():
            raise GitHubIssueQueryError("TITLE_INVALID")


@dataclass(frozen=True, slots=True)
class GitHubIssueStateChangeInput:
    repository: str
    issue_number: int

    def __post_init__(self) -> None:
        validate_repository(self.repository)
        validate_issue_number(self.issue_number)


@dataclass(frozen=True, slots=True)
class GitHubIssueRequest:
    url: str


@dataclass(frozen=True, slots=True)
class GitHubIssueMutationRequest:
    method: str
    url: str
    body: dict[str, object]


def validate_repository(repository: str) -> str:
    parts = repository.split("/")
    if len(parts) != 2 or not parts[0].strip() or not parts[1].strip():
        raise GitHubIssueQueryError("REPOSITORY_INVALID")
    return repository


def validate_issue_number(issue_number: int) -> None:
    if issue_number < 1:
        raise GitHubIssueQueryError("ISSUE_NUMBER_INVALID")


def require_str(arguments: dict[str, object], key: str) -> str:
    value = arguments.get(key)
    if not isinstance(value, str) or not value.strip():
        raise GitHubIssueQueryError(f"{key.upper()}_INVALID")
    return value


def require_issue_number(arguments: dict[str, object], key: str = "issue_number") -> int:
    value = arguments.get(key)
    if not isinstance(value, int) or isinstance(value, bool):
        raise GitHubIssueQueryError(f"{key.upper()}_INVALID")
    return value


def optional_str(arguments: dict[str, object], key: str) -> str | None:
    value = arguments.get(key)
    if value is not None and (not isinstance(value, str) or not value.strip()):
        raise GitHubIssueQueryError(f"{key.upper()}_INVALID")
    return value
