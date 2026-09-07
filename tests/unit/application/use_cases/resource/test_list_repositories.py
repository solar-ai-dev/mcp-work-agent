from dataclasses import replace
from types import SimpleNamespace
from typing import Any, cast

import pytest

from google_work_agent.adapters.system.memory.resource_continuation import (
    InMemoryResourceContinuationAdapter,
)
from google_work_agent.application.use_cases.resource.list_repositories import (
    ListRepositoriesHandler,
    ListRepositoriesQuery,
)
from google_work_agent.ports.connector.connector_failure import ConnectorOperationFailure


def test_list_repositories__bounded_metadata__uses_opaque_cursor() -> None:
    output = {
        "account_id": "github:1",
        "items": [
            {"repository": "sample/project", "repository_id": 2, "private": True},
        ],
        "next_cursor": "1:1:1",
    }
    reader = SimpleNamespace(execute_read=lambda *_: SimpleNamespace(output=output))
    handler = ListRepositoriesHandler(
        connector_read=cast(Any, reader),
        binding=cast(Any, None),
        continuation_store=InMemoryResourceContinuationAdapter(),
    )
    query = ListRepositoriesQuery("a" * 64, "github:1")
    result = handler(query)
    assert result.items[0].repository == "sample/project"
    assert result.next_cursor and result.next_cursor != "1:1:1"
    with pytest.raises(ConnectorOperationFailure):
        handler(replace(query, session_digest="b" * 64, cursor=result.next_cursor))
    output["account_id"] = "github:2"
    with pytest.raises(ConnectorOperationFailure, match="GITHUB_ACCOUNT_CHANGED"):
        handler(query)
