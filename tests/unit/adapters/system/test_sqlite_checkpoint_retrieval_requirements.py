import json
import sqlite3
from collections.abc import Mapping
from pathlib import Path

import pytest

from google_work_agent.adapters.system.sqlite_checkpoint import (
    SqliteCheckpointAdapter,
    _retrieval_requirements_from_checkpoint,
)
from google_work_agent.application.use_cases.run.guard_run_budget import build_default_run_budget
from google_work_agent.ports.system.contracts.workflow_handoff import (
    MainControlResumeTargetV2,
    WorkflowExecutionAdmissionV1,
    WorkflowExecutionBindingV1,
)


def test_retrieval_cache__requirements_project__only_bounded_bindings() -> None:
    requirements = _retrieval_requirements_from_checkpoint(
        {
            "channel_values": {
                "__context_read_result_handles__": ["read-1", "read-1"],
                "__context_read_bindings__": {
                    "read-1": {
                        "route_id": "route-1",
                        "query_identity_hash": "a" * 64,
                        "raw_result": "must-not-project",
                    }
                },
            }
        }
    )

    assert requirements is not None
    assert len(requirements) == 1
    assert requirements[0].read_result_handle == "read-1"
    assert requirements[0].route_id == "route-1"
    assert requirements[0].query_identity_hash == "a" * 64


def test_nested_retrieval__requirements_overlay_latest__root_resume_checkpoint(
    tmp_path: Path,
) -> None:
    checkpoint = SqliteCheckpointAdapter(tmp_path / "checkpoint.db", now_ms=lambda: 10)
    admission = WorkflowExecutionAdmissionV1(
        schema_version=1,
        admission_id="admission-1",
        handoff_id="handoff-1",
        handoff_run_sequence=1,
        submission_kind="NORMAL_HANDOFF",
        effective_binding=WorkflowExecutionBindingV1(
            schema_version=1,
            execution_kind="START",
            run_id="run-1",
            langgraph_thread_id="thread-1",
            graph_profile="SIX_ROLE_BASELINE",
            graph_version="v1",
            requested_mode="AUTO",
            checkpoint_id=None,
            checkpoint_generation=0,
            resume_target=None,
        ),
        expected_run_version=0,
    )
    target = MainControlResumeTargetV2(
        kind="MAIN_CONTROL",
        stage_id="RETRIEVAL_ENTRY",
        graph_profile="SIX_ROLE_BASELINE",
        graph_version="v1",
    )
    base_checkpoint = {
        "v": 4,
        "ts": "2026-09-04T00:00:00+00:00",
        "channel_versions": {},
        "versions_seen": {},
        "updated_channels": [],
    }

    try:
        with checkpoint.execution_scope(
            admission,
            applied_handoff_id="handoff-1",
            owner_scope="RETRIEVAL",
            resume_target=target,
        ):
            checkpoint.put(
                {"configurable": {"thread_id": "thread-1", "checkpoint_ns": ""}},
                {**base_checkpoint, "id": "root-1", "channel_values": {}},
                {},
                {},
            )
            checkpoint.put(
                {
                    "configurable": {
                        "thread_id": "thread-1",
                        "checkpoint_ns": "context_retriever:task-1",
                    }
                },
                {
                    **base_checkpoint,
                    "id": "nested-1",
                    "channel_values": {
                        "__context_read_result_handles__": ["read-1"],
                        "__context_read_bindings__": {
                            "read-1": {
                                "route_id": "route-1",
                                "query_identity_hash": "a" * 64,
                            }
                        },
                    },
                },
                {},
                {},
            )

        loaded = checkpoint.load_same_run_checkpoint("run-1", "thread-1")
    finally:
        checkpoint.close()

    assert loaded is not None
    assert loaded.checkpoint_id == "root-1"
    assert loaded.checkpoint_generation == 1
    assert len(loaded.retrieval_cache_requirements) == 1
    assert loaded.retrieval_cache_requirements[0].read_result_handle == "read-1"


@pytest.mark.parametrize(
    ("run_status", "handoff_status", "has_admission", "allowed"),
    [
        ("WAITING_APPROVAL", None, False, True),
        ("EXECUTING", None, False, False),
        ("EXECUTING", "CONSUMED", True, True),
        ("CREATED", "CONSUMED", False, True),
        ("EXECUTING", "PENDING", False, False),
        ("RECOVERY_REQUIRED", "CONSUMED", False, False),
        ("COMPLETED", "CONSUMED", False, False),
    ],
)
def test_run_budget__updates_only_budget__for_settled_or_active_execution(
    tmp_path: Path,
    run_status: str,
    handoff_status: str | None,
    has_admission: bool,
    allowed: bool,
) -> None:
    path = tmp_path / "paused.db"
    adapter = SqliteCheckpointAdapter(path, now_ms=lambda: 0)
    budget = build_default_run_budget()
    native = {
        "id": "checkpoint",
        "v": 4,
        "ts": "2026-09-06T00:00:00Z",
        "channel_values": {"retry_budget": budget, "evidence": ["keep"]},
        "channel_versions": {},
        "versions_seen": {},
        "updated_channels": [],
    }
    kind, blob = adapter.serde.dumps_typed(native)
    with sqlite3.connect(path) as db:
        db.execute(
            "CREATE TABLE runs (id TEXT PRIMARY KEY, status TEXT, budget_json TEXT)"
        )
        db.execute(
            "CREATE TABLE workflow_handoffs "
            "(run_id TEXT, status TEXT, execution_admission_json TEXT, "
            "applied_checkpoint_id TEXT, applied_checkpoint_generation INTEGER)"
        )
        db.execute(
            "INSERT INTO runs VALUES ('run', ?, ?)",
            (run_status, json.dumps(budget, sort_keys=True)),
        )
        if handoff_status is not None:
            db.execute(
                "INSERT INTO workflow_handoffs VALUES ('run', ?, ?, ?, ?)",
                (
                    handoff_status,
                    "{}" if has_admission else None,
                    "checkpoint" if handoff_status == "CONSUMED" else None,
                    1 if handoff_status == "CONSUMED" else None,
                ),
            )
        db.execute(
            "INSERT INTO checkpoints VALUES ('thread', '', 'checkpoint', NULL, ?, ?, '{}')",
            (kind, blob),
        )
        db.execute("""INSERT INTO workflow_checkpoint_envelopes (
            langgraph_thread_id, checkpoint_id, checkpoint_generation, run_id,
            graph_profile, graph_version, owner_scope,
            retrieval_cache_requirements_json, created_at_ms
        ) VALUES ('thread', 'checkpoint', 1, 'run', 'SIX_ROLE_BASELINE', 'v1', 'MAIN', '[]', 0)""")
    calls: list[Mapping[str, object]] = []

    def update(current: Mapping[str, object]) -> Mapping[str, object]:
        calls.append(current)
        llm_calls_used = current["llm_calls_used"]
        assert isinstance(llm_calls_used, int)
        return {**current, "llm_calls_used": llm_calls_used + 1}

    try:
        if not allowed:
            with pytest.raises(ValueError):
                adapter.update_run_budget("run", update)
            assert calls == []
        else:
            first = adapter.update_run_budget("run", update)
            second = adapter.update_run_budget("run", update)
            assert len(calls) == 2
            assert first["llm_calls_used"] == 1
            assert second["llm_calls_used"] == 2
    finally:
        adapter.close()
    reopened = SqliteCheckpointAdapter(path, now_ms=lambda: 0)
    try:
        restored = reopened.get_tuple({"configurable": {"thread_id": "thread"}}).checkpoint
        assert restored == {
            **native,
            "channel_values": {
                "retry_budget": {**budget, "llm_calls_used": 2 if allowed else 0},
                "evidence": ["keep"],
            },
        }
        envelope = reopened.load_same_run_checkpoint("run", "thread")
        assert envelope is not None
        assert envelope.checkpoint_generation == 1
        assert envelope.checkpoint_id == "checkpoint"
        with sqlite3.connect(path) as db:
            persisted_budget = json.loads(
                db.execute("SELECT budget_json FROM runs WHERE id='run'").fetchone()[0]
            )
        assert persisted_budget["llm_calls_used"] == (2 if allowed else 0)
    finally:
        reopened.close()
