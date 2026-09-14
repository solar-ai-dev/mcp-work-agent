from __future__ import annotations

from types import SimpleNamespace
from typing import Any, cast

from google_work_agent.adapters.langgraph.main.workflow import LangGraphWorkflowRuntime
from google_work_agent.ports.llm.structured_inference_contracts import (
    LLMErrorCode,
    LLMInvocationError,
)
from google_work_agent.ports.system.contracts.workflow_execution import (
    WorkflowCorrelationContext,
    WorkflowStartRequest,
)


class _FailingInvocation:
    def __init__(self, error: Exception) -> None:
        self.error = error

    def start(self, _request: WorkflowStartRequest) -> object:
        raise self.error

    def config_for_thread(self, workflow_key: str) -> dict[str, object]:
        return {"configurable": {"thread_id": workflow_key}}

    def result_from_thread(self, *, workflow_key: str, run_id: str) -> tuple[str, str]:
        return workflow_key, run_id


class _Graph:
    def __init__(self) -> None:
        self.updates: list[tuple[dict[str, object], dict[str, object], str]] = []
        self.invocations: list[dict[str, object]] = []

    def get_state(self, _config: dict[str, object]) -> SimpleNamespace:
        return SimpleNamespace(
            next=("request_understanding",),
            values={"retry_budget": {"llm_calls_used": 2}},
        )

    def update_state(
        self,
        config: dict[str, object],
        update: dict[str, object],
        *,
        as_node: str,
    ) -> None:
        self.updates.append((config, update, as_node))

    def invoke(self, _input: object, *, config: dict[str, object]) -> None:
        self.invocations.append(config)


def test_output_schema_failure__uses_existing_terminal_pipeline__without_bypass() -> None:
    runtime = cast(Any, object.__new__(LangGraphWorkflowRuntime))
    runtime._invocation = _FailingInvocation(
        LLMInvocationError(
            LLMErrorCode.OUTPUT_SCHEMA_INVALID,
            "private model output",
            provider_dispatch_occurred=True,
        )
    )
    runtime._graph = _Graph()
    runtime._read_terminal_facts = lambda _run_id: {
        "status": "ANALYZING",
        "action_statuses": [],
    }

    result = runtime.start(_request())

    assert result == ("thread-1", "run-1")
    assert runtime._graph.updates == [
        (
            {"configurable": {"thread_id": "thread-1"}},
            {
                "__logical_target__": "response_synthesis",
                "__target__": "response_synthesis",
                "finalize_intent": {
                    "schema_version": 1,
                    "intent": "BLOCKED",
                    "reason_code": "OUTPUT_SCHEMA_INVALID",
                },
            },
            "request_understanding",
        )
    ]
    assert runtime._graph.invocations == [{"configurable": {"thread_id": "thread-1"}}]


def _request() -> WorkflowStartRequest:
    return WorkflowStartRequest(
        run_id="run-1",
        conversation_id="conversation-1",
        workflow_key="thread-1",
        entry_mode="AGENT_SEARCH",
        requested_mode="LOCAL_GPU",
        request_text="할 일을 만들어 줘",
        selected_resource_ids=(),
        run_budget={},
        correlation=WorkflowCorrelationContext(
            request_id="request-1",
            command_id="command-1",
            api_contract_version="v1",
        ),
    )
