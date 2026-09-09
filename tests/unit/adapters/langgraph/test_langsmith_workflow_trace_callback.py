from __future__ import annotations

from typing import Any, TypedDict, cast
from uuid import UUID, uuid4

import pytest
from langgraph.errors import GraphInterrupt
from langgraph.graph import END, START, StateGraph

from google_work_agent.adapters.langgraph.invocation import WorkflowInvocationCoordinator
from google_work_agent.adapters.langgraph.langsmith_workflow_trace_callback import (
    LangSmithWorkflowTraceCallback,
    create_langsmith_workflow_trace_callback,
)
from google_work_agent.adapters.langgraph.profiles.profile_registry import GraphProfile
from google_work_agent.ports.llm.structured_inference_contracts import (
    LLMErrorCode,
    LLMInvocationError,
)


class _Client:
    def __init__(self, *, fail: bool = False, **constructor: Any) -> None:
        self.fail = fail
        self.constructor = constructor
        self.created: list[dict[str, Any]] = []
        self.updated: list[tuple[UUID, dict[str, Any]]] = []
        self.flush_count = 0
        self.close_count = 0

    def create_run(
        self,
        name: str,
        inputs: dict[str, Any],
        run_type: str,
        *,
        project_name: str | None = None,
        **kwargs: Any,
    ) -> None:
        if self.fail:
            raise RuntimeError("client unavailable with secret-content")
        self.created.append(
            {
                "name": name,
                "inputs": inputs,
                "run_type": run_type,
                "project_name": project_name,
                **kwargs,
            }
        )

    def update_run(self, run_id: UUID, **kwargs: Any) -> None:
        if self.fail:
            raise RuntimeError("client unavailable with secret-content")
        self.updated.append((run_id, kwargs))

    def flush(self, timeout: float | None = None) -> None:
        del timeout
        self.flush_count += 1
        if self.fail:
            raise RuntimeError("client unavailable with secret-content")

    def close(self, timeout: float | None = None) -> None:
        del timeout
        self.close_count += 1
        if self.fail:
            raise RuntimeError("client unavailable with secret-content")


class _GraphState(TypedDict):
    value: int


def _metadata(**extra: object) -> dict[str, object]:
    return {
        "product_run_id": "run-123",
        "graph_profile": "SIX_ROLE_BASELINE",
        "graph_version": "resume-contract-v2",
        **extra,
    }


def test_callback__exports_only_safe_graph_metadata__with_node_hierarchy() -> None:
    client = _Client()
    callback = LangSmithWorkflowTraceCallback(
        client=client,
        project_name="quality-development",
    )
    graph_run_id = uuid4()
    internal_run_id = uuid4()
    node_run_id = uuid4()

    callback.on_chain_start(
        {"raw": "serialized-secret"},
        {"messages": ["private-mail-body"]},
        run_id=graph_run_id,
        metadata=_metadata(),
        name="CompiledStateGraph",
    )
    callback.on_chain_start(
        None,
        {"raw": "nested-secret"},
        run_id=internal_run_id,
        parent_run_id=graph_run_id,
        metadata=_metadata(),
        name="RunnableSequence",
    )
    callback.on_chain_start(
        None,
        {"raw": "node-secret"},
        run_id=node_run_id,
        parent_run_id=internal_run_id,
        metadata=_metadata(
            langgraph_node="request_understanding",
            langgraph_checkpoint_ns="private/checkpoint/namespace",
        ),
        name="request_understanding",
    )
    callback.on_chain_end(
        {"structured_output": "private-model-output"},
        run_id=node_run_id,
    )
    callback.on_chain_end({}, run_id=internal_run_id)
    callback.on_chain_end({"state": "private-state"}, run_id=graph_run_id)

    assert [entry["name"] for entry in client.created] == [
        "production_langgraph",
        "node:request_understanding",
    ]
    assert all(entry["inputs"] == {} for entry in client.created)
    assert client.created[1]["trace_id"] == graph_run_id
    assert client.created[1]["parent_run_id"] == graph_run_id
    node_metadata = client.created[1]["extra"]["metadata"]
    assert node_metadata == {
        "product_run_id": "run-123",
        "graph_profile": "SIX_ROLE_BASELINE",
        "graph_version": "resume-contract-v2",
        "graph_node": "request_understanding",
        "checkpoint_namespace_hash": "cb4b3a2e1644c463",
    }
    exported = repr((client.created, client.updated))
    assert "private-mail-body" not in exported
    assert "private-model-output" not in exported
    assert "private/checkpoint/namespace" not in exported
    assert all(update[1]["outputs"] == {} for update in client.updated)


def test_callback__receives_metadata_from_compiled_langgraph__without_state_payload() -> None:
    client = _Client()
    callback = LangSmithWorkflowTraceCallback(client=client, project_name="quality")
    builder = StateGraph(_GraphState)
    builder.add_node("request_understanding", lambda state: {"value": state["value"] + 1})
    builder.add_edge(START, "request_understanding")
    builder.add_edge("request_understanding", END)

    result = builder.compile().invoke(
        {"value": 1},
        {
            "callbacks": [callback],
            "metadata": {
                "product_run_id": "run-123",
                "graph_profile": "SIX_ROLE_BASELINE",
                "graph_version": "resume-contract-v2",
            },
        },
    )

    assert result == {"value": 2}
    assert [entry["name"] for entry in client.created] == [
        "production_langgraph",
        "node:request_understanding",
    ]
    assert all(entry["inputs"] == {} for entry in client.created)
    assert all(update[1]["outputs"] == {} for update in client.updated)
    assert "'value': 1" not in repr((client.created, client.updated))


def test_callback__exports_typed_failure_code__without_error_message() -> None:
    client = _Client()
    callback = LangSmithWorkflowTraceCallback(client=client, project_name="quality")
    run_id = uuid4()
    callback.on_chain_start(None, {}, run_id=run_id, metadata=_metadata(), name="graph")

    callback.on_chain_error(
        LLMInvocationError(
            LLMErrorCode.OUTPUT_SCHEMA_INVALID,
            "private provider output and email secret@example.com",
            affected_field_paths=("$.valid[0].field", "$.bad@email"),
            provider_dispatch_occurred=True,
        ),
        run_id=run_id,
    )

    update = client.updated[0][1]
    assert update["error"] == "SAFE_ERROR_TYPE:LLMInvocationError"
    assert update["extra"]["metadata"] == {
        **_metadata(),
        "error_type": "LLMInvocationError",
        "safe_error_code": "OUTPUT_SCHEMA_INVALID",
        "provider_dispatch_occurred": True,
        "affected_field_path_hashes": ["ad9bfb268fcc46b5"],
    }
    assert "private provider output" not in repr(update)
    assert "secret@example.com" not in repr(update)
    assert "$.valid[0].field" not in repr(update)


def test_callback__records_interrupt_without_failure__and_never_breaks_workflow() -> None:
    client = _Client()
    callback = LangSmithWorkflowTraceCallback(client=client, project_name="quality")
    run_id = uuid4()
    callback.on_chain_start(None, {}, run_id=run_id, metadata=_metadata(), name="graph")
    callback.on_chain_error(GraphInterrupt(), run_id=run_id)

    assert client.updated[0][1]["error"] is None
    assert client.updated[0][1]["extra"]["metadata"]["outcome"] == "INTERRUPTED"

    unavailable = LangSmithWorkflowTraceCallback(
        client=_Client(fail=True),
        project_name="quality",
    )
    unavailable.on_chain_start(None, {}, run_id=uuid4(), metadata=_metadata(), name="graph")
    unavailable.flush()
    unavailable.close()


def test_callback_factory__payload_hiding_and_idempotent_close__are_forced(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clients: list[_Client] = []

    def build_client(**kwargs: Any) -> _Client:
        client = _Client(**kwargs)
        clients.append(client)
        return client

    monkeypatch.setattr(
        "google_work_agent.adapters.langgraph.langsmith_workflow_trace_callback.Client",
        build_client,
    )

    callback = create_langsmith_workflow_trace_callback(
        api_key=" secret-key ",
        project_name="quality",
    )
    built_client = clients[0]
    assert built_client.constructor == {
        "api_url": "https://api.smith.langchain.com",
        "api_key": "secret-key",
        "auto_batch_tracing": True,
        "hide_inputs": True,
        "hide_outputs": True,
        "omit_traced_runtime_info": True,
    }
    callback.close()
    callback.close()
    assert built_client.flush_count == 1
    assert built_client.close_count == 1


def test_invocation_config__product_run_correlation__excludes_thread_key() -> None:
    coordinator = WorkflowInvocationCoordinator(
        graph=object(),
        graph_profile=GraphProfile.SIX_ROLE_BASELINE,
        graph_version="graph-v1",
        start_node="initialize",
        initial_state=lambda request: cast(Any, {}),
        current_run_status=lambda run_id: "RUNNING",
        latest_unknown_action=lambda run_id: None,
        recovery_node=lambda state: state,
        has_executed_action=lambda run_id: False,
        recover_executed_actions=lambda state, run_id: state,
        mark_stalled_claims_as_unknown=lambda run_id: False,
        cancel_signal_lock=object(),
        cancel_signals=set(),
    )

    config = coordinator.config_for_thread("private-workflow-key", product_run_id="run-123")

    assert config["configurable"] == {"thread_id": "private-workflow-key"}
    assert config["metadata"] == {
        "product_run_id": "run-123",
        "graph_profile": "SIX_ROLE_BASELINE",
        "graph_version": "graph-v1",
    }
    assert "private-workflow-key" not in repr(config["metadata"])
