from types import SimpleNamespace
from typing import Any, cast

import pytest

from google_work_agent.application.use_cases.resource.get_repository_access import (
    GetRepositoryAccessHandler,
    GetRepositoryAccessQuery,
)
from google_work_agent.application.use_cases.resource.list_repositories import (
    ListRepositoriesHandler,
)
from google_work_agent.application.use_cases.resource.opaque_continuation_access import (
    LocalResourceContinuationStore,
)
from google_work_agent.ports.connector.connector_failure import ConnectorOperationFailure
from google_work_agent.ports.system.settings_port import GitHubRepositoryDefaultV1


@pytest.mark.parametrize(
    "expected", [None, GitHubRepositoryDefaultV1("sample/project", 2, "github:1")]
)
def test_repository_access__current_identity__rejects_stale_default(
    expected: GitHubRepositoryDefaultV1 | None,
) -> None:
    output = {
        "account_id": "github:1",
        "items": [
            {"repository": "sample/project", "repository_id": 2, "private": False},
        ],
        "next_cursor": None,
    }
    reader = SimpleNamespace(execute_read=lambda *_: SimpleNamespace(output=output))
    listing = ListRepositoriesHandler(
        connector_read=cast(Any, reader),
        binding=cast(Any, None),
        continuation_store=LocalResourceContinuationStore(),
    )
    handler = GetRepositoryAccessHandler(
        list_repositories=listing, current_account_id=lambda: "github:1"
    )
    assert handler(
        GetRepositoryAccessQuery("Sample/Project", expected)
    ) == GitHubRepositoryDefaultV1("sample/project", 2, "github:1")
    with pytest.raises(ConnectorOperationFailure, match="ACCESS_UNAVAILABLE"):
        handler(GetRepositoryAccessQuery("sample/missing"))
    with pytest.raises(ConnectorOperationFailure, match="ACCOUNT_CHANGED"):
        handler(
            GetRepositoryAccessQuery(
                "sample/project", GitHubRepositoryDefaultV1("sample/project", 2, "github:3")
            )
        )
    with pytest.raises(ConnectorOperationFailure, match="ACCESS_UNAVAILABLE"):
        handler(
            GetRepositoryAccessQuery(
                "sample/project", GitHubRepositoryDefaultV1("sample/project", 3, "github:1")
            )
        )
