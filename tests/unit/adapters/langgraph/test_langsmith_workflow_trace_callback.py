from __future__ import annotations

from typing import Any, TypedDict, cast
from uuid import UUID, uuid4

import pytest
from langgraph.errors import GraphInterrupt
from langgraph.graph import END, START, StateGraph

from google_work_agent.adapters.langgraph.invocation import WorkflowInvocationCoordinator
from google_work_agent.adapters.langgraph.langsmith_workflow_io_projection import (
    project_langsmith_workflow_payload,
)
from google_work_agent.adapters.langgraph.langsmith_workflow_trace_callback import (
    LangSmithWorkflowTraceCallback,
    create_langsmith_workflow_trace_callback,
)
from google_work_agent.adapters.langgraph.profiles.profile_registry import GraphProfile
from google_work_agent.ports.llm.structured_inference_contracts import (
    LLMErrorCode,
    LLMInvocationError,
)
from google_work_agent.ports.system.external_call_trace_port import (
    ExternalCallTraceFinishV1,
    ExternalCallTraceStartV1,
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


class _SemanticValidationError(ValueError):
    reason_code = "SEMANTIC_FIELD_INVALID"
    affected_field_paths = ("$.resource_responsibilities.outputs", "unsafe@email")


class _StagedSemanticValidationError(ValueError):
    reason_code = "SEMANTIC_FIELD_INVALID"
    affected_field_paths = ("$.route_queries[].operation",)
    validation_stage = "QUERY_PLAN_VALIDATOR"


def _metadata(**extra: object) -> dict[str, object]:
    return {
        "product_run_id": "run-123",
        "graph_profile": "SIX_ROLE_BASELINE",
        "graph_version": "resume-contract-v2",
        **extra,
    }


def _trace_binding() -> dict[str, str]:
    return {
        "code_sha": "a" * 40,
        "experiment_id": "issue251-read-only-6run",
        "model_digest": "b" * 64,
        "model_id": "qwen3.5:9b",
        "prompt_content_hash": "c" * 64,
        "prompt_id": "request_understanding.identify_goal",
        "prompt_version": "1.0.50",
        "question_id": "Q1",
    }


def test_callback__exports_only_safe_graph_metadata__with_node_hierarchy() -> None:
    client = _Client()
    callback = LangSmithWorkflowTraceCallback(
        client=client,
        project_name="quality-development",
        trace_binding=_trace_binding(),
    )
    graph_run_id = uuid4()
    internal_run_id = uuid4()
    node_run_id = uuid4()

    callback.on_chain_start(
        {"raw": "serialized-secret"},
        {
            "workflow_phase": "REQUEST_ANALYSIS",
            "run_input": {
                "entry_mode": "AGENT_SEARCH",
                "requested_mode": "LOCAL_GPU",
                "user_request": "private-mail-body",
                "selected_resource_refs": [],
            },
        },
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
        {
            "request_intent": {
                "schema_version": 2,
                "goal": "node-secret",
                "ambiguity": {
                    "requires_confirmation": False,
                    "reason_codes": [],
                    "missing_fields": [],
                },
                "requested_effect_hints": ["READ"],
                "requested_resource_hints": ["GMAIL_THREAD"],
                "constraints": [
                    {
                        "kind": "KEYWORD",
                        "field": "subject",
                        "value": "private-search-term",
                    }
                ],
            }
        },
        run_id=node_run_id,
        parent_run_id=internal_run_id,
        metadata=_metadata(
            langgraph_node="request_understanding",
            langgraph_checkpoint_ns="private/checkpoint/namespace",
        ),
        name="request_understanding",
    )
    callback.on_chain_end(
        {
            "request_intent": None,
            "retry_budget": {
                "schema_version": 2,
                "profile": "NORMAL",
                "llm_calls_used": 1,
                "llm_call_limit": 14,
            },
            "structured_output": "private-model-output",
        },
        run_id=node_run_id,
    )
    callback.on_chain_end({}, run_id=internal_run_id)
    callback.on_chain_end({"state": "private-state"}, run_id=graph_run_id)

    assert [entry["name"] for entry in client.created] == [
        "production_langgraph",
        "node:request_understanding",
    ]
    root_trace = client.created[0]
    node_trace = client.created[1]
    assert root_trace["inputs"]["workflow"]["fields"] == {
        "run_input": {
            "entry_mode": "AGENT_SEARCH",
            "has_user_request": True,
            "requested_mode": "LOCAL_GPU",
            "selected_resource_refs": {"count": 0},
        },
        "workflow_phase": "REQUEST_ANALYSIS",
    }
    assert node_trace["inputs"]["workflow"]["fields"]["request_intent"] == {
        "ambiguity": {
            "missing_fields": {"count": 0},
            "reason_codes": {"count": 0, "values": []},
            "requires_confirmation": False,
        },
        "constraints": {"count": 1, "items": [{"field": "subject", "kind": "KEYWORD"}]},
        "requested_effect_hints": {"count": 1, "values": ["READ"]},
        "requested_resource_hints": {"count": 1, "values": ["GMAIL_THREAD"]},
        "schema_version": 2,
    }
    assert root_trace["trace_id"] == graph_run_id
    assert root_trace["parent_run_id"] is None
    assert root_trace["dotted_order"].endswith(str(graph_run_id))
    assert node_trace["dotted_order"].startswith(f"{root_trace['dotted_order']}.")
    assert node_trace["dotted_order"].endswith(str(node_run_id))
    assert client.created[1]["trace_id"] == graph_run_id
    assert client.created[1]["parent_run_id"] == graph_run_id
    node_metadata = client.created[1]["extra"]["metadata"]
    assert node_metadata == {
        "domain_run_id": "run-123",
        **_trace_binding(),
        "graph_profile": "SIX_ROLE_BASELINE",
        "graph_version": "resume-contract-v2",
        "graph_node": "request_understanding",
        "checkpoint_namespace_hash": "cb4b3a2e1644c463",
    }
    exported = repr((client.created, client.updated))
    assert "private-mail-body" not in exported
    assert "private-model-output" not in exported
    assert "private/checkpoint/namespace" not in exported
    node_update = next(update for update in client.updated if update[0] == node_run_id)[1]
    assert node_update["outputs"]["workflow"]["fields"] == {
        "request_intent": {"value_state": "NULL"},
        "retry_budget": {
            "llm_call_limit": 14,
            "llm_calls_used": 1,
            "profile": "NORMAL",
            "schema_version": 2,
        },
    }
    created_dotted_order = {entry["id"]: entry["dotted_order"] for entry in client.created}
    assert all(
        update[1]["dotted_order"] == created_dotted_order[update[0]] for update in client.updated
    )
    created_parent = {entry["id"]: entry["parent_run_id"] for entry in client.created}
    assert all(update[1]["parent_run_id"] == created_parent[update[0]] for update in client.updated)


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
    assert all("workflow" in entry["inputs"] for entry in client.created)
    assert all("workflow" in update[1]["outputs"] for update in client.updated)
    assert "'value': 1" not in repr((client.created, client.updated))


def test_callback__nests_safe_llm_and_connector_dispatches__under_workflow_root() -> None:
    client = _Client()
    callback = LangSmithWorkflowTraceCallback(
        client=client,
        project_name="quality",
        trace_binding=_trace_binding(),
    )
    graph_run_id = uuid4()
    callback.on_chain_start(
        None,
        {},
        run_id=graph_run_id,
        metadata=_metadata(),
        name="CompiledStateGraph",
    )

    llm_handle = callback.begin_external_call(
        ExternalCallTraceStartV1(
            schema_version=1,
            domain_run_id="run-123",
            call_kind="LLM_INFERENCE",
            operation="INFER_STRUCTURED",
            provider="ollama",
            model_id="qwen3.5:9b",
            prompt_id="request_understanding.identify_goal",
            prompt_version="1.0.50",
            prompt_content_hash="d" * 64,
            output_schema_id="request-intent-v2",
            safe_semantic_input={
                "projection_version": 1,
                "selected_resource_count": 0,
                "user_request": "private-request",
            },
        )
    )
    connector_handle = callback.begin_external_call(
        ExternalCallTraceStartV1(
            schema_version=1,
            domain_run_id="run-123",
            call_kind="CONNECTOR_READ",
            operation="CALL_TOOL",
            connector_id="google_workspace",
            tool_id="gmail_search",
            effect="READ",
        )
    )
    assert llm_handle is not None
    assert connector_handle is not None
    callback.finish_external_call(
        llm_handle,
        ExternalCallTraceFinishV1(
            schema_version=1,
            status="COMPLETED",
            duration_ms=17,
            input_tokens=20,
            output_tokens=5,
            total_tokens=25,
            safe_semantic_output={
                "projection_version": 1,
                "missing_information_owner": "USER",
                "missing_fields": {"count": 1, "values": ["target_resource"]},
                "body": "private-body",
            },
        ),
    )
    callback.finish_external_call(
        connector_handle,
        ExternalCallTraceFinishV1(
            schema_version=1,
            status="FAILED",
            duration_ms=11,
            result_count=0,
            has_next_page=False,
            error_type="ConnectorOperationFailure",
            safe_error_code="TIMEOUT",
        ),
    )
    callback.on_chain_end({}, run_id=graph_run_id)

    assert [(entry["name"], entry["run_type"]) for entry in client.created] == [
        ("production_langgraph", "chain"),
        ("llm:structured_inference", "llm"),
        ("connector:read", "tool"),
    ]
    for child in client.created[1:]:
        assert child["trace_id"] == graph_run_id
        assert child["parent_run_id"] == graph_run_id
        assert child["dotted_order"].startswith(f"{client.created[0]['dotted_order']}.")
    assert client.created[1]["inputs"] == {
        "call": {
            "schema_version": 1,
            "call_kind": "LLM_INFERENCE",
            "operation": "INFER_STRUCTURED",
            "provider": "ollama",
            "model_id": "qwen3.5:9b",
            "prompt_id": "request_understanding.identify_goal",
            "prompt_version": "1.0.50",
            "prompt_content_hash": "d" * 64,
            "output_schema_id": "request-intent-v2",
            "semantic_input": {
                "projection_version": 1,
                "selected_resource_count": 0,
            },
        }
    }
    updates = {str(run_id): update for run_id, update in client.updated}
    assert updates[llm_handle.trace_run_id]["outputs"]["call"]["total_tokens"] == 25
    assert updates[llm_handle.trace_run_id]["outputs"]["call"]["semantic_output"] == {
        "projection_version": 1,
        "missing_information_owner": "USER",
        "missing_fields": {"count": 1, "values": ["target_resource"]},
    }
    assert "private-request" not in repr((client.created, client.updated))
    assert "private-body" not in repr((client.created, client.updated))
    connector_update = updates[connector_handle.trace_run_id]
    assert connector_update["error"] == "SAFE_ERROR_TYPE:ConnectorOperationFailure"
    assert connector_update["outputs"]["call"]["safe_error_code"] == "TIMEOUT"
    assert (
        callback.begin_external_call(
            ExternalCallTraceStartV1(
                schema_version=1,
                domain_run_id="run-123",
                call_kind="CONNECTOR_READ",
                operation="CALL_TOOL",
            )
        )
        is None
    )


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
        "domain_run_id": "run-123",
        "graph_profile": "SIX_ROLE_BASELINE",
        "graph_version": "resume-contract-v2",
        "error_type": "LLMInvocationError",
        "safe_error_code": "OUTPUT_SCHEMA_INVALID",
        "provider_dispatch_occurred": True,
        "validation_stage": "POST_INFERENCE_VALIDATION",
        "validation_rule": "OUTPUT_SCHEMA_INVALID",
        "affected_field_paths": ["$.valid[0].field"],
        "affected_field_path_hashes": ["ad9bfb268fcc46b5"],
    }
    assert "private provider output" not in repr(update)
    assert "secret@example.com" not in repr(update)
    assert "$.valid[0].field" in repr(update)


def test_callback__semantic_failure__exports_reason_and_safe_field_hash_only() -> None:
    client = _Client()
    callback = LangSmithWorkflowTraceCallback(client=client, project_name="quality")
    run_id = uuid4()
    callback.on_chain_start(None, {}, run_id=run_id, metadata=_metadata(), name="graph")

    callback.on_chain_error(_SemanticValidationError("private model output"), run_id=run_id)

    update = client.updated[0][1]
    metadata = update["extra"]["metadata"]
    assert metadata["safe_error_code"] == "SEMANTIC_FIELD_INVALID"
    assert metadata["validation_stage"] == "POST_INFERENCE_VALIDATION"
    assert metadata["validation_rule"] == "SEMANTIC_FIELD_INVALID"
    assert metadata["affected_field_paths"] == ["$.resource_responsibilities.outputs"]
    assert metadata["affected_field_path_hashes"] == ["f7d52e4f92f5570b"]
    assert "private model output" not in repr(update)
    assert "unsafe@email" not in repr(update)


def test_callback__with_specific_validation_stage__preserves_stage() -> None:
    client = _Client()
    callback = LangSmithWorkflowTraceCallback(client=client, project_name="quality")
    run_id = uuid4()
    callback.on_chain_start(None, {}, run_id=run_id, metadata=_metadata(), name="graph")

    callback.on_chain_error(_StagedSemanticValidationError("private output"), run_id=run_id)

    metadata = client.updated[0][1]["extra"]["metadata"]
    assert metadata["validation_stage"] == "QUERY_PLAN_VALIDATOR"
    assert metadata["validation_rule"] == "SEMANTIC_FIELD_INVALID"
    assert metadata["affected_field_paths"] == ["$.route_queries[].operation"]


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


def test_callback_factory__safe_projection_client__enables_io_and_idempotent_close(
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
        trace_binding=_trace_binding(),
    )
    built_client = clients[0]
    assert built_client.constructor == {
        "api_url": "https://api.smith.langchain.com",
        "api_key": "secret-key",
        "auto_batch_tracing": True,
        "hide_inputs": False,
        "hide_outputs": False,
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


def test_callback__partial_or_unsafe_trace_binding__is_rejected() -> None:
    with pytest.raises(ValueError, match="complete safe field set"):
        LangSmithWorkflowTraceCallback(
            client=_Client(),
            project_name="quality",
            trace_binding={"question_id": "Q1"},
        )
    with pytest.raises(ValueError, match="safe opaque identifiers"):
        LangSmithWorkflowTraceCallback(
            client=_Client(),
            project_name="quality",
            trace_binding={**_trace_binding(), "question_id": "unsafe value"},
        )


def test_io_projection__safe_payload__keeps_contract_shape_without_business_content() -> None:
    projection = project_langsmith_workflow_payload(
        {
            "workflow_phase": "CONTEXT_RETRIEVAL",
            "query_plan": {
                "schema_version": 2,
                "route_queries": [
                    {
                        "route_id": "private-route-id",
                        "operation": "SEARCH",
                        "reason_codes": ["INITIAL_QUERY"],
                        "search_spec": {
                            "mode": "INITIAL",
                            "constraints": [
                                {
                                    "kind": "CONCEPT",
                                    "concept": "private-concept",
                                    "manifestations": ["private-manifestation"],
                                }
                            ],
                        },
                    }
                ],
            },
            "retrieval_result": {
                "schema_version": 1,
                "coverage": "PARTIAL",
                "evidence_refs": ["private-evidence-id"],
                "source_resource_refs": ["private-resource-id"],
                "source_statuses": [
                    {
                        "route_id": "private-route-id",
                        "resource_type": "GMAIL_THREAD",
                        "status": "COMPLETE",
                        "observed_resource_count": 0,
                        "failure_kind": "NOT_FOUND",
                    }
                ],
            },
            "planning_result": {
                "schema_version": 2,
                "answer": "private-answer",
                "evidence_refs": ["private-evidence-id"],
            },
            "llm_provider_result": {"raw_completion": "private-completion"},
        }
    )

    exported = repr(projection)
    projected_fields = projection["fields"]
    assert isinstance(projected_fields, dict)
    assert projected_fields["query_plan"] == {
        "route_queries": {
            "count": 1,
            "items": [
                {
                    "operation": "SEARCH",
                    "reason_codes": {"count": 1, "values": ["INITIAL_QUERY"]},
                    "search_spec": {
                        "constraints": {"count": 1, "items": [{"kind": "CONCEPT"}]},
                        "mode": "INITIAL",
                    },
                }
            ],
        },
        "schema_version": 2,
    }
    retrieval_result = projected_fields["retrieval_result"]
    assert isinstance(retrieval_result, dict)
    assert retrieval_result["source_statuses"] == {
        "count": 1,
        "items": [
            {
                "failure_kind": "NOT_FOUND",
                "observed_resource_count": 0,
                "resource_type": "GMAIL_THREAD",
                "status": "COMPLETE",
            }
        ],
    }
    assert projected_fields["llm_provider_result"] == {"value_state": "PRESENT"}
    for private_value in (
        "private-route-id",
        "private-concept",
        "private-manifestation",
        "private-evidence-id",
        "private-resource-id",
        "private-answer",
        "private-completion",
    ):
        assert private_value not in exported


def test_io_projection__null_presence__distinguishes_omitted_from_explicit_null() -> None:
    omitted = project_langsmith_workflow_payload({})
    cleared = project_langsmith_workflow_payload({"request_intent": None})

    assert omitted["state_fields"] == []
    assert cleared["state_fields"] == ["request_intent"]
    assert cleared["fields"] == {"request_intent": {"value_state": "NULL"}}


def test_io_projection__keeps_route_and_retrieval_decisions__without_identities() -> None:
    projection = project_langsmith_workflow_payload(
        {
            "ambiguity_candidate": {
                "missing_information_owner": "USER",
                "missing_fields": ["target_resource", "민감한 일정 제목"],
                "requires_confirmation": True,
            },
            "io_resource_candidate": {
                "input_resource_types": ["GMAIL_THREAD"],
                "output_resource_types": [],
                "output_effects": [],
                "disposition": "ROUTE_READY",
            },
            "tool_route_plan": {
                "schema_version": 2,
                "input_plan": {
                    "input_routes": [
                        {
                            "route_id": "private-route",
                            "resource_type": "GMAIL_THREAD",
                            "connector_id": "google_workspace",
                            "allowed_read_tool_ids": ["gmail_search"],
                            "reason_codes": ["REQUESTED_INPUT"],
                        }
                    ]
                },
                "output_plan": {"output_mode": "ANSWER"},
            },
            "rag_candidates": [{"segment_id": "private-segment"}],
            "evidence_selection": {
                "schema_version": 2,
                "evidence_drafts": [{"segment_id": "private-segment"}],
                "selected_segment_ids": ["private-segment"],
                "excluded_segment_ids": [],
            },
            "sufficiency": {
                "schema_version": 2,
                "status": "NEEDS_MORE_DATA",
                "issues": [
                    {
                        "issue_type": "MISSING",
                        "required": True,
                        "resolution_source": "GOOGLE",
                        "safety_critical": False,
                        "reason_codes": ["LATEST_MESSAGE_REQUIRED"],
                    }
                ],
            },
        }
    )

    fields = projection["fields"]
    assert fields["ambiguity_candidate"] == {
        "missing_fields": {"count": 2, "values": ["target_resource"]},
        "missing_information_owner": "USER",
        "requires_confirmation": True,
    }
    assert fields["io_resource_candidate"] == {
        "disposition": "ROUTE_READY",
        "input_resource_types": {"count": 1, "values": ["GMAIL_THREAD"]},
        "output_effects": {"count": 0, "values": []},
        "output_resource_types": {"count": 0, "values": []},
    }
    assert fields["rag_candidates"] == {"count": 1}
    assert fields["evidence_selection"]["selected_segment_ids"] == {"count": 1}
    assert fields["sufficiency"]["status"] == "NEEDS_MORE_DATA"
    assert fields["sufficiency"]["issues"]["count"] == 1
    exported = repr(projection)
    assert "민감한 일정 제목" not in exported
    assert "private-route" not in exported
    assert "private-segment" not in exported
