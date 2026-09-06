from typing import Any, cast

import pytest

from google_work_agent.adapters.connectors.github.github.mcp_server.github_api import (
    GitHubProviderError,
)
from google_work_agent.adapters.connectors.github.github.repositories.list_repositories import (
    ListRepositoriesOperation,
)


class RepositoryApi:
    def __init__(self) -> None:
        self.urls: list[str] = []
        self.installations: list[dict[str, object]] = [{"id": 10}, {"id": 11}]
        self.denied = False

    def get(self, url: str) -> object:
        self.urls.append(url)
        if url.endswith("/user"):
            return {"id": 42}
        if "/repositories?" not in url:
            if self.denied:
                raise GitHubProviderError("PERMISSION_DENIED")
            return {"installations": self.installations}
        return {
            "repositories": [
                {
                    "id": 5,
                    "full_name": "sample/project",
                    "private": True,
                    "description": "not projected",
                }
            ]
        }


def test_repository_list__installation_intersection__uses_only_authenticated_api() -> None:
    api = RepositoryApi()
    result = ListRepositoriesOperation(cast(Any, api)).execute({})
    assert result == {
        "account_id": "github:42",
        "items": [{"repository": "sample/project", "repository_id": 5, "private": True}],
        "next_cursor": "1:1:1",
    }
    assert (
        api.urls[-1]
        == "https://api.github.com/user/installations/10/repositories?per_page=100&page=1"
    )
    result = ListRepositoriesOperation(cast(Any, api)).execute({"cursor": result["next_cursor"]})
    assert result["next_cursor"] is None
    assert "/installations/11/repositories" in api.urls[-1]


def test_repository_list__permission_failure__is_not_empty_result() -> None:
    api = RepositoryApi()
    api.denied = True
    with pytest.raises(GitHubProviderError, match="PERMISSION_DENIED"):
        ListRepositoriesOperation(cast(Any, api)).execute({})
    api.denied = False
    api.installations = []
    assert ListRepositoriesOperation(cast(Any, api)).execute({})["items"] == []


@pytest.mark.parametrize("cursor", ["https://untrusted", "0:0:1", "1:100:1", "1:0:0", "1:../:1"])
def test_repository_list__invalid_cursor__performs_no_provider_call(cursor: str) -> None:
    api = RepositoryApi()
    with pytest.raises(GitHubProviderError, match="INVALID_ARGUMENT"):
        ListRepositoriesOperation(cast(Any, api)).execute({"cursor": cursor})
    assert api.urls == []


@pytest.mark.parametrize("invalid_row", [
    {"id": 0, "full_name": "sample/project", "private": False},
    {"id": True, "full_name": "sample/project", "private": False},
    {"id": 5, "full_name": "sample/project", "private": "false"},
    {"id": 5, "full_name": "sample/..", "private": False},
])
def test_repository_list__invalid_provider_metadata__fails_closed(invalid_row):
    class InvalidApi(RepositoryApi):
        def get(self, url):
            if "/repositories?" in url:
                return {"repositories": [invalid_row]}
            return super().get(url)

    with pytest.raises(GitHubProviderError, match="MALFORMED_RESPONSE"):
        ListRepositoriesOperation(cast(Any, InvalidApi())).execute({})


def test_repository_list__oversized_installation_page__rejects_unbounded_input():
    api = RepositoryApi()
    api.installations = [{"id": item + 1} for item in range(101)]
    with pytest.raises(GitHubProviderError, match="MALFORMED_RESPONSE"):
        ListRepositoriesOperation(cast(Any, api)).execute({})
    assert not any("/repositories?" in url for url in api.urls)
