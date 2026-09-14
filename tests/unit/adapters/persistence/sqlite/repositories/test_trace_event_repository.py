import sqlite3
from json import loads

from google_work_agent.adapters.persistence.sqlite.repositories.trace_event_repository import (
    SqliteTraceEventRepository,
)
from google_work_agent.domain.trace_event.model import TraceEvent
from google_work_agent.ports.system.contracts.observability import (
    EventCategory,
    ObservabilityContext,
    Severity,
    create_event_envelope,
    serialize_event_envelope,
)


def test_trace_event__repository_sanitizes__lists_and_purges() -> None:
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    connection.execute(
        """CREATE TABLE trace_events (
            id INTEGER PRIMARY KEY, run_id TEXT, action_id TEXT, event_type TEXT,
            status TEXT, duration_ms INTEGER, payload_json TEXT, created_at_ms INTEGER
        )"""
    )
    repository = SqliteTraceEventRepository(
        connection, environment="DEVELOPMENT", release_version="0.1.0-dev",
    )
    repository.append(
        TraceEvent(
            "run-1",
            None,
            "TEST",
            "OK",
            1,
            '{"access_token":"access_abcdefghijklmnopqrstuvwxyz0123456789"}',
            1,
        )
    )

    page = repository.list_page(None, 10)
    assert len(page) == 1
    assert "access_abcdefghijklmnopqrstuvwxyz0123456789" not in page[0].payload_json
    assert loads(page[0].payload_json)["schema_version"] == 1
    assert loads(page[0].payload_json)["environment"] == "DEVELOPMENT"
    assert loads(page[0].payload_json)["release_version"] == "0.1.0-dev"
    assert repository.purge_before(2) == 1


def test_llm_failure_trace__safe_contract_fields__survive_storage_and_query() -> None:
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    connection.execute(
        """CREATE TABLE trace_events (
            id INTEGER PRIMARY KEY, run_id TEXT, action_id TEXT, event_type TEXT,
            status TEXT, duration_ms INTEGER, payload_json TEXT, created_at_ms INTEGER
        )"""
    )
    repository = SqliteTraceEventRepository(
        connection, environment="DEVELOPMENT", release_version="0.1.0-dev"
    )
    envelope = create_event_envelope(
        event_name="LLM_CALL_FAILED",
        event_category=EventCategory.LLM,
        occurred_at_ms=10,
        severity=Severity.ERROR,
        component="llm-runtime",
        environment="DEVELOPMENT",
        release_version="0.1.0-dev",
        correlation=ObservabilityContext(run_id="run-1"),
        attributes={
            "operation": "INFER_STRUCTURED",
            "prompt_id": "request_understanding.identify_goal",
            "prompt_version": "1.0.50",
            "prompt_content_hash": "a" * 64,
            "output_schema_id": "9",
            "error_type": "LLMInvocationError",
            "safe_error_code": "OUTPUT_SCHEMA_INVALID",
            "affected_field_paths": ["$.resource_responsibilities.outputs"],
            "selected_model_id": "qwen3.5:9b",
            "provider_dispatch_occurred": True,
            "raw_completion": "private business content",
        },
        result_code="OUTPUT_SCHEMA_INVALID",
        status="FAILED",
    )
    repository.append(
        TraceEvent(
            "run-1",
            None,
            "LLM_CALL_FAILED",
            "FAILED",
            None,
            serialize_event_envelope(envelope),
            10,
        )
    )

    payload = loads(repository.list_page(None, 10)[0].payload_json)
    attributes = payload["attributes"]
    assert attributes == {
        "affected_field_paths": ["$.resource_responsibilities.outputs"],
        "error_type": "LLMInvocationError",
        "operation": "INFER_STRUCTURED",
        "output_schema_id": "9",
        "prompt_content_hash": "a" * 64,
        "prompt_id": "request_understanding.identify_goal",
        "prompt_version": "1.0.50",
        "provider_dispatch_occurred": True,
        "safe_error_code": "OUTPUT_SCHEMA_INVALID",
        "selected_model_id": "qwen3.5:9b",
    }
    assert "private business content" not in repository.list_page(None, 10)[0].payload_json
