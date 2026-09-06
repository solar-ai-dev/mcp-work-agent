"""Production checkpoint values survive restart without arbitrary type construction."""

from dataclasses import asdict, dataclass
from json import dumps
from pathlib import Path

import pytest
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer

from google_work_agent.adapters.system.sqlite_checkpoint import SqliteCheckpointAdapter
from google_work_agent.ports.system.contracts.workflow_execution import (
    WorkflowCorrelationContext,
    WorkflowStartRequest,
)
from google_work_agent.ports.system.settings_port import GitHubRepositoryDefaultV1


@dataclass
class UnregisteredCheckpointValue:
    value: str


def test_checkpoint__restores_existing_typed_values__after_adapter_restart(tmp_path: Path) -> None:
    request = WorkflowStartRequest(
        "run",
        "conversation",
        "thread",
        "AGENT_SEARCH",
        "AUTO",
        "request",
        (),
        WorkflowCorrelationContext("req", "cmd", "1"),
        default_github_repository=GitHubRepositoryDefaultV1("owner/repo", 1, "github:1"),
    )
    # Previously persisted wire format remains readable; no state reinterpretation.
    encoded = JsonPlusSerializer().dumps_typed({"request": request})
    adapter = SqliteCheckpointAdapter(tmp_path / "checkpoint.db", now_ms=lambda: 1)
    adapter.close()
    restarted = SqliteCheckpointAdapter(tmp_path / "checkpoint.db", now_ms=lambda: 2)
    try:
        restored = restarted.serde.loads_typed(encoded)["request"]
        assert isinstance(restored, WorkflowStartRequest)
        assert restored.correlation == request.correlation
        assert restored.default_github_repository == request.default_github_repository
        assert dumps(asdict(restored), sort_keys=True) == dumps(asdict(request), sort_keys=True)
    finally:
        restarted.close()


def test_checkpoint__blocks_unregistered_constructor__and_pickle(tmp_path: Path) -> None:
    adapter = SqliteCheckpointAdapter(tmp_path / "checkpoint.db", now_ms=lambda: 1)
    try:
        encoded = adapter.serde.dumps_typed(UnregisteredCheckpointValue("safe-data"))
        decoded = adapter.serde.loads_typed(encoded)
        assert not isinstance(decoded, UnregisteredCheckpointValue)
        assert decoded == {"value": "safe-data"}
        with pytest.raises(NotImplementedError):
            adapter.serde.loads_typed(("pickle", b"not-a-pickle"))
    finally:
        adapter.close()
