"""List only repositories shared by the authenticated user and this GitHub App."""

from __future__ import annotations

import re

from google_work_agent.adapters.connectors.github.github.mcp_server.github_api import (
    GitHubApiClient,
    GitHubProviderError,
)


class ListRepositoriesOperation:
    """Bounded provider pagination, without widening installation permissions."""

    def __init__(self, api: GitHubApiClient) -> None:
        self._api = api

    def execute(self, arguments: dict[str, object]) -> dict[str, object]:
        cursor = arguments.get("cursor") or "1:0:1"
        if not isinstance(cursor, str) or not re.fullmatch(r"\d{1,4}:\d{1,3}:\d{1,4}", cursor):
            raise GitHubProviderError("INVALID_ARGUMENT")
        installation_page, index, repository_page = map(int, cursor.split(":"))
        if (
            not 1 <= installation_page <= 1000
            or not 0 <= index < 100
            or not 1 <= repository_page <= 1000
        ):
            raise GitHubProviderError("INVALID_ARGUMENT")
        profile = self._api.get("https://api.github.com/user")
        if (
            not isinstance(profile, dict)
            or type(profile.get("id")) is not int
            or profile["id"] < 1
        ):
            raise GitHubProviderError("MALFORMED_RESPONSE")
        account_id = f"github:{profile['id']}"
        payload = self._api.get(
            f"https://api.github.com/user/installations?per_page=100&page={installation_page}"
        )
        if not isinstance(payload, dict) or not isinstance(payload.get("installations"), list):
            raise GitHubProviderError("MALFORMED_RESPONSE")
        installations = payload["installations"]
        if len(installations) > 100:
            raise GitHubProviderError("MALFORMED_RESPONSE")
        if not installations:
            return {"account_id": account_id, "items": [], "next_cursor": None}
        if index >= len(installations):
            raise GitHubProviderError("INVALID_ARGUMENT")
        installation = installations[index]
        if (
            not isinstance(installation, dict)
            or type(installation.get("id")) is not int
            or installation["id"] < 1
        ):
            raise GitHubProviderError("MALFORMED_RESPONSE")
        items: list[dict[str, object]] = []
        repository_count = 0
        if installation.get("suspended_at") is None:
            repositories = self._api.get(
                f"https://api.github.com/user/installations/{installation['id']}/repositories"
                f"?per_page=100&page={repository_page}"
            )
            if not isinstance(repositories, dict) or not isinstance(
                repositories.get("repositories"), list
            ):
                raise GitHubProviderError("MALFORMED_RESPONSE")
            rows = repositories["repositories"]
            repository_count = len(rows)
            if repository_count > 100:
                raise GitHubProviderError("MALFORMED_RESPONSE")
            for row in rows:
                if (
                    not isinstance(row, dict)
                    or type(row.get("id")) is not int
                    or row["id"] < 1
                    or type(row.get("private")) is not bool
                ):
                    raise GitHubProviderError("MALFORMED_RESPONSE")
                name = row.get("full_name")
                if (
                    not isinstance(name, str)
                    or len(name) > 200
                    or name.rsplit("/", 1)[-1] in {".", ".."}
                    or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9-]*/[A-Za-z0-9_.-]+", name)
                ):
                    raise GitHubProviderError("MALFORMED_RESPONSE")
                items.append(
                    {
                        "repository": name,
                        "repository_id": row["id"],
                        "private": row["private"],
                    }
                )
        next_cursor = None
        if repository_count == 100:
            next_cursor = f"{installation_page}:{index}:{repository_page + 1}"
        elif index + 1 < len(installations):
            next_cursor = f"{installation_page}:{index + 1}:1"
        elif len(installations) == 100:
            next_cursor = f"{installation_page + 1}:0:1"
        return {"account_id": account_id, "items": items, "next_cursor": next_cursor}
