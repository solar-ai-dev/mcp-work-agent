from __future__ import annotations

from dataclasses import replace
from json import loads
from pathlib import Path

import pytest
from tests.support.checkpoint import sqlite_checkpoint

from google_work_agent.adapters.langgraph.main.state import (
    initial_graph_state,
    request_from_run_input_state,
)
from google_work_agent.adapters.langgraph.profiles.profile_registry import GraphProfile
from google_work_agent.adapters.persistence.connection import connect_sqlite
from google_work_agent.adapters.persistence.migration import apply_migrations
from google_work_agent.adapters.persistence.sqlite.unit_of_work import sqlite_unit_of_work_factory
from google_work_agent.application.tool_registry.load_signed_tool_registry import (
    load_signed_tool_registry,
)
from google_work_agent.application.use_cases.resource.issue_selection_handle import (
    ResourceSelectionHandlePayloadV1,
)
from google_work_agent.application.use_cases.run.complete_answer_only_run import (
    CompleteAnswerOnlyRunCommand,
    CompleteAnswerOnlyRunHandler,
)
from google_work_agent.application.use_cases.run.get_run_snapshot import (
    GetExecutionContextQuery,
    GetRunSnapshotHandler,
)
from google_work_agent.application.use_cases.run.start_analysis import (
    StartAnalysisCommand,
    StartAnalysisHandler,
)
from google_work_agent.application.use_cases.run.start_run import StartRunCommand, StartRunHandler
from google_work_agent.ports.system.contracts.workflow_execution import (
    WorkflowCorrelationContext,
    WorkflowStartRequest,
)
from google_work_agent.ports.system.settings_port import PanelPreferencesV1, SettingsViewV1


def _database(tmp_path: Path) -> Path:
    path = tmp_path / "start-run-input.db"
    with connect_sqlite(path) as connection:
        apply_migrations(connection)
        connection.execute(
            "INSERT INTO google_accounts (id, email, connected_at_ms) "
            "VALUES ('account-1', 'u@example.com', 1)"
        )
        connection.execute(
            "INSERT INTO conversations VALUES ('conversation-1', 'account-1', 'Inbox', 1, 1)"
        )
    return path


def _command() -> StartRunCommand:
    return StartRunCommand(
        command_id="command-1",
        request_hash="a" * 64,
        conversation_id="conversation-1",
        request_text="hello",
        entry_mode="AGENT_SEARCH",
        requested_mode="AUTO",
        api_contract_version="1",
    )


def test_local_request__terminates_once__and_resubmission_creates_new_run(tmp_path: Path):
    path = _database(tmp_path)
    with connect_sqlite(path) as connection:
        connection.execute("UPDATE conversations SET account_id='local-workspace'")
        connection.execute("DELETE FROM google_accounts")
    factory = sqlite_unit_of_work_factory(path)
    identifiers = iter(f"local-{index}" for index in range(30))
    start = StartRunHandler(
        unit_of_work_factory=factory,
        checkpoint_port=sqlite_checkpoint(path),
        now_ms=lambda: 10,
        id_factory=identifiers.__next__,
        graph_profile="SIX_ROLE_BASELINE",
        graph_version="test",
        tool_registry=load_signed_tool_registry(),
    )
    first = start(_command())
    analyzing = StartAnalysisHandler(unit_of_work_factory=factory, now_ms=lambda: 11)(
        StartAnalysisCommand(first.run_id, first.run_version, "analysis", "b" * 64),
    )
    finish = CompleteAnswerOnlyRunHandler(
        unit_of_work_factory=factory,
        now_ms=lambda: 12,
        message_id_factory=identifiers.__next__,
    )
    command = CompleteAnswerOnlyRunCommand(
        command_id="finish",
        conversation_id="conversation-1",
        run_id=first.run_id,
        assistant_message="GitHub 연결 후 요청을 다시 보내주세요.",
        expected_version=analyzing.current_version,
        request_hash="c" * 64,
        result_kind="PARTIAL",
    )
    completed = finish(command)
    replayed = finish(command)
    assert completed.result_kind == "PARTIAL"
    assert completed.assistant_message_id == replayed.assistant_message_id
    second = start(replace(_command(), command_id="new-request", request_hash="d" * 64))
    assert second.applied
    assert first.run_id != second.run_id
    assert first.workflow_key != second.workflow_key
    with connect_sqlite(path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM google_accounts").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM actions").fetchone()[0] == 0
        assert (
            connection.execute(
                "SELECT COUNT(*) FROM messages WHERE run_id=? AND role='ASSISTANT'", (first.run_id,)
            ).fetchone()[0]
            == 1
        )
        assert connection.execute(
            "SELECT status, terminal_result_kind FROM runs WHERE id=?", (first.run_id,)
        ).fetchone()[:] == ("COMPLETED", "PARTIAL")


@pytest.mark.parametrize(
    "command",
    (
        replace(_command(), request_text=""),
        replace(_command(), request_text="가" * 21846),
        replace(_command(), entry_mode="UNKNOWN"),
        replace(_command(), requested_mode="UNKNOWN"),
        replace(_command(), entry_mode="RESOURCE_SELECTED"),
    ),
)
def test_start_run_rejects__noncanonical_input_before__any_durable_write(
    tmp_path: Path, command: StartRunCommand
) -> None:
    database_path = _database(tmp_path)
    handler = StartRunHandler(
        unit_of_work_factory=sqlite_unit_of_work_factory(database_path),
        checkpoint_port=sqlite_checkpoint(database_path),
        now_ms=lambda: 10,
        id_factory=lambda: "must-not-be-used",
        graph_profile="SIX_ROLE_BASELINE",
        graph_version="graph-v1",
        tool_registry=load_signed_tool_registry(),
    )

    with pytest.raises(ValueError):
        handler(command)

    with connect_sqlite(database_path) as connection:
        for table in ("command_receipts", "runs", "messages", "workflow_handoffs"):
            assert connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0


@pytest.mark.parametrize("local_actor", [False, True])
def test_start_run_freezes__current_settings_into__durable_run_budget(
    tmp_path: Path,
    local_actor: bool,
) -> None:
    database_path = _database(tmp_path)
    if local_actor:
        with connect_sqlite(database_path) as connection:
            connection.execute("UPDATE conversations SET account_id='local-workspace'")
            connection.execute("DELETE FROM google_accounts")
    handler = StartRunHandler(
        unit_of_work_factory=sqlite_unit_of_work_factory(database_path),
        checkpoint_port=sqlite_checkpoint(database_path),
        now_ms=lambda: 1234,
        id_factory=iter(("run-1", "message-1", "workflow-1", "handoff-1")).__next__,
        graph_profile="SIX_ROLE_BASELINE",
        graph_version="graph-v1",
        settings_provider=lambda: SettingsViewV1(
            schema_version=1,
            timezone="UTC",
            default_tasklist_id=None,
            default_calendar_id=None,
            preferred_llm_mode="AUTO",
            external_llm_consent=False,
            retention_days=7,
            theme="LIGHT",
            panel_preferences=PanelPreferencesV1(1, False, "CONVERSATIONS"),
            working_day_start_local="09:00",
            working_day_end_local="18:00",
            include_weekends=False,
            calendar_buffer_minutes=0,
            max_run_execution_ms=60_000,
            max_connector_calls_per_run=9,
            max_source_page_calls_per_run=7,
            max_detail_fetches_per_run=11,
            max_context_tokens_per_run=4_000,
            max_retry_attempts_per_run=3,
            circuit_failure_threshold=3,
            circuit_open_duration_ms=30_000,
        ),
        tool_registry=load_signed_tool_registry(),
    )

    result = handler(_command())

    with connect_sqlite(database_path) as connection:
        budget = loads(
            connection.execute(
                "SELECT budget_json FROM runs WHERE id = ?", (result.run_id,)
            ).fetchone()[0]
        )
    assert budget["schema_version"] == 2
    assert budget["started_at_ms"] == 1234
    assert budget["max_execution_ms"] == 60_000
    assert budget["max_connector_calls"] == 9
    assert budget["max_source_page_calls"] == 7
    assert budget["max_detail_fetches"] == 11
    assert budget["max_context_tokens"] == 4_000
    assert budget["max_retry_attempts"] == 3


def test_start_run__preserves_github_selected_identity__through_rehydration(
    tmp_path: Path,
) -> None:
    database_path = _database(tmp_path)
    identifiers = iter(("run-1", "message-1", "workflow-1", "handoff-1", "resource-ref-1"))
    handler = StartRunHandler(
        unit_of_work_factory=sqlite_unit_of_work_factory(database_path),
        checkpoint_port=sqlite_checkpoint(database_path),
        now_ms=lambda: 10,
        id_factory=identifiers.__next__,
        graph_profile="SIX_ROLE_BASELINE",
        graph_version="graph-v1",
        tool_registry=load_signed_tool_registry(),
    )
    command = replace(
        _command(),
        entry_mode="RESOURCE_SELECTED",
        request_text="이 이슈를 확인해줘",
        resolved_resource_selections=(
            ResourceSelectionHandlePayloadV1(
                schema_version=1,
                service_instance_id="service-1",
                session_digest="a" * 64,
                account_id="account-1",
                connector_id="github",
                resource_type="github_issue",
                resource_id="solar-ai-dev/google-work-agent#123",
                parent_resource_id="solar-ai-dev/google-work-agent",
                version_token="v1",
                issued_at_ms=1,
                expires_at_ms=100,
            ),
        ),
    )

    result = handler(command)
    context = GetRunSnapshotHandler(
        unit_of_work_factory=sqlite_unit_of_work_factory(database_path)
    ).execution_context(GetExecutionContextQuery(result.run_id))

    assert context is not None
    selected = context.selected_resources[0]
    assert (
        selected.resource_ref_id,
        selected.connector_id,
        selected.resource_type,
        selected.resource_id,
        selected.parent_resource_id,
    ) == (
        "resource-ref-1",
        "github",
        "github_issue",
        "solar-ai-dev/google-work-agent#123",
        "solar-ai-dev/google-work-agent",
    )

    request = WorkflowStartRequest(
        run_id=context.run_id,
        conversation_id=context.conversation_id,
        workflow_key=context.workflow_key,
        entry_mode=context.entry_mode,
        requested_mode="AUTO",
        request_text=context.request_text,
        selected_resource_ids=context.selected_resource_ids,
        correlation=WorkflowCorrelationContext("request-1", "command-1", "v1"),
        run_budget=context.run_budget,
        selected_resources=context.selected_resources,
    )
    state = initial_graph_state(
        request,
        graph_profile=GraphProfile.SIX_ROLE_BASELINE,
        graph_version="graph-v1",
        initial_target="request.identify_goal",
    )

    assert request_from_run_input_state(state).selected_resources == context.selected_resources
