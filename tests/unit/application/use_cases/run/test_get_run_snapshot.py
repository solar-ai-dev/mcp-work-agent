from __future__ import annotations

from json import dumps
from pathlib import Path

import pytest

from google_work_agent.adapters.persistence.connection import connect_sqlite
from google_work_agent.adapters.persistence.migration import apply_migrations
from google_work_agent.adapters.persistence.sqlite.unit_of_work import sqlite_unit_of_work_factory
from google_work_agent.application.use_cases.run.get_run_snapshot import (
    GetRunSnapshotHandler,
    GetRunSnapshotQuery,
)
from google_work_agent.domain.trace_event.model import TraceEvent


@pytest.mark.parametrize(
    ("runtimes", "expected"),
    [
        ((), None),
        (("LOCAL_GPU",), "LOCAL_GPU"),
        (("API_LLM",), "API_LLM"),
        (("LOCAL_GPU", "API_LLM", "LOCAL_GPU"), "MIXED"),
        (("unknown",), None),
    ],
)
def test_run_snapshot_projects__durable_terminal_kind_and__run_messages_after_restart(
    tmp_path: Path,
    runtimes: tuple[str, ...],
    expected: str | None,
) -> None:
    database_path = tmp_path / "snapshot.db"
    with connect_sqlite(database_path) as connection:
        apply_migrations(connection)
        connection.execute(
            "INSERT INTO google_accounts (id, email, connected_at_ms) "
            "VALUES ('account-1', 'u@example.com', 1)"
        )
        connection.execute(
            "INSERT INTO conversations VALUES ('conversation-1', 'account-1', 'Inbox', 1, 3)"
        )
        connection.execute(
            """INSERT INTO runs (
                id, conversation_id, entry_mode, status, langgraph_thread_id,
                requested_mode, budget_json, version, started_at_ms, finished_at_ms,
                terminal_result_kind
            ) VALUES ('run-1', 'conversation-1', 'AGENT_SEARCH', 'COMPLETED',
                      'thread-1', 'AUTO', '{}', 5, 1, 3, 'SUCCESS')"""
        )
        connection.execute(
            "INSERT INTO messages VALUES "
            "('m-1', 'conversation-1', 'run-1', 'USER', 'request', 1), "
            "('m-2', 'conversation-1', 'run-1', 'ASSISTANT', 'done', 3)"
        )

    factory = sqlite_unit_of_work_factory(database_path)
    with factory() as uow:
        for runtime in runtimes:
            uow.traces.append(
                TraceEvent(
                    "run-1",
                    None,
                    "LLM_CALL_COMPLETED",
                    "OK",
                    1,
                    dumps({"actual_runtime": runtime, "model": "fixture-model"}),
                    3,
                )
            )
        uow.traces.append(
            TraceEvent(
                "run-1",
                None,
                "LLM_CALL_FAILED",
                "ERROR",
                1,
                dumps({"actual_runtime": "API_LLM"}),
                3,
            )
        )
        uow.commit()

    result = GetRunSnapshotHandler(unit_of_work_factory=factory)(GetRunSnapshotQuery("run-1"))

    assert result is not None
    assert result.run.run_id == "run-1"
    assert result.run.status == "COMPLETED"
    assert result.run.actual_runtime == expected
    with factory() as uow:
        durable = uow.runs.get("run-1")
    assert durable is not None and durable.version == 5 and durable.actual_runtime is None
    assert [item.content for item in result.messages] == ["request", "done"]
    assert result.current_plan is None
    assert result.context_preview is None
    assert result.pending_interrupt is None
    assert result.recovery is None
    assert result.error is None
    assert result.terminal_result_kind == "SUCCESS"
    assert result.projection_version == 1
