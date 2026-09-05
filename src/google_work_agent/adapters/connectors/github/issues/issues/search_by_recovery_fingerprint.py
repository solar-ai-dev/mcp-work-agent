"""Bounded internal lookup for uncertain GitHub Issue creation."""

from __future__ import annotations

from urllib.parse import urlencode

from google_work_agent.adapters.connectors.github.github.mcp_server.github_api import (
    GitHubApiClient,
    GitHubProviderError,
)

from .create_issue import RECOVERY_MARKER_TEMPLATE
from .issue_contract import GITHUB_API_BASE, require_str, validate_repository
from .issue_snapshot import normalize_github_issue, project_issue_snapshot

TOOL_ID = "search_by_recovery_fingerprint"
MAX_SEARCH_PAGES = 3
PAGE_SIZE = 100


class SearchByRecoveryFingerprintOperation:
    tool_id = TOOL_ID

    def __init__(self, api: GitHubApiClient) -> None:
        self._api = api

    def execute(self, arguments: dict[str, object]) -> dict[str, object]:
        repository = validate_repository(require_str(arguments, "repository"))
        fingerprint = require_str(arguments, "recovery_fingerprint")
        marker = RECOVERY_MARKER_TEMPLATE.format(fingerprint=fingerprint)
        matches: list[dict[str, object]] = []
        examined = 0
        total_count: int | None = None
        incomplete = False
        exhausted = False
        for page in range(1, MAX_SEARCH_PAGES + 1):
            query = urlencode(
                {
                    "q": f'repo:{repository} is:issue in:body "{marker}"',
                    "per_page": PAGE_SIZE,
                    "page": page,
                }
            )
            raw = self._api.get(f"{GITHUB_API_BASE}/search/issues?{query}")
            if not isinstance(raw, dict) or not isinstance(raw.get("items"), list):
                raise GitHubProviderError("MALFORMED_RESPONSE")
            raw_total = raw.get("total_count")
            if isinstance(raw_total, int) and not isinstance(raw_total, bool):
                total_count = raw_total
            incomplete = incomplete or raw.get("incomplete_results") is True
            items = raw["items"]
            examined += len(items)
            for item in items:
                if (
                    isinstance(item, dict)
                    and "pull_request" not in item
                    and marker in str(item.get("body") or "")
                ):
                    matches.append(
                        project_issue_snapshot(
                            normalize_github_issue(item, repository=repository)
                        )
                    )
            if len(items) < PAGE_SIZE:
                exhausted = True
                break
        coverage_complete = (
            not incomplete
            and (exhausted or (total_count is not None and examined >= total_count))
        )
        return {
            "items": matches,
            "coverage_complete": coverage_complete,
            "examined_count": examined,
        }


__all__ = ["SearchByRecoveryFingerprintOperation"]
