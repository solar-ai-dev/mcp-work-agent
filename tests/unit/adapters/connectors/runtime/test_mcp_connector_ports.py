from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest

from google_work_agent.adapters.connectors.google.workspace.composition import (
    google_workspace_internal_read_binding,
)
from google_work_agent.adapters.connectors.runtime.connector_runtime_registry import (
    ConnectorRuntimeRegistry,
)
from google_work_agent.adapters.connectors.runtime.mcp_connector_read import McpConnectorReadAdapter
from google_work_agent.adapters.connectors.runtime.mcp_connector_write import (
    McpConnectorWriteAdapter,
)
from google_work_agent.application.tool_registry.load_signed_tool_registry import (
    load_signed_tool_registry,
)
from google_work_agent.ports.connector.connector_read_port import JsonValue
from google_work_agent.ports.connector.contracts.delivery_certainty import DeliveryCertainty
from google_work_agent.ports.connector.mcp_client_port import (
    MCPClientPortError,
    MCPClientPortErrorCode,
    MCPRestartResultV1,
    MCPRuntimeMetadata,
    MCPToolCallResultV1,
    MCPToolDescriptorV1,
)
from google_work_agent.ports.system.external_call_trace_port import (
    ExternalCallTraceFinishV1,
    ExternalCallTraceHandleV1,
    ExternalCallTraceStartV1,
)


@dataclass
class _Client:
    response: MCPToolCallResultV1
    process_id: str = "process-1"
    calls: list[tuple[str, str, Any, int]] = field(default_factory=list)
    sign_calls: int = 0

    def list_tools(self, connector_id: str) -> list[MCPToolDescriptorV1]:
        return load_signed_tool_registry().descriptor_expectations(connector_id)

    def call_tool(
        self, connector_id: str, tool_id: str, arguments: Any, timeout_ms: int
    ) -> MCPToolCallResultV1:
        self.calls.append((connector_id, tool_id, arguments, timeout_ms))
        return self.response

    def restart_once(self, connector_id: str) -> MCPRestartResultV1:
        return MCPRestartResultV1(1, True, connector_id)

    def process_instance_id(self, connector_id: str) -> str:
        assert connector_id == "google_workspace"
        return self.process_id

    def sign_claim_context(self, connector_id: str, payload: dict[str, object]) -> str:
        self.sign_calls += 1
        assert connector_id == "google_workspace"
        assert payload["mcp_process_instance_id"] == self.process_id
        return "signature-1"

    def close(self) -> None:
        pass


@dataclass
class _Runtime:
    client: _Client

    def runtime_metadata(self) -> MCPRuntimeMetadata:
        return MCPRuntimeMetadata("READY", "1", "1", "1", 1, None, 0, "process-1")

    def list_tools(self) -> list[MCPToolDescriptorV1]:
        return self.client.list_tools("google_workspace")

    def call_tool(self, tool_id: str, arguments: Any, timeout_ms: int) -> MCPToolCallResultV1:
        return self.client.call_tool("google_workspace", tool_id, arguments, timeout_ms)

    def restart_once(self) -> MCPRestartResultV1:
        return self.client.restart_once("google_workspace")

    def sign_claim_context(self, payload: dict[str, object]) -> str:
        return self.client.sign_claim_context("google_workspace", payload)

    def close(self) -> None:
        self.client.close()


@dataclass
class _ExternalCallTrace:
    starts: list[ExternalCallTraceStartV1] = field(default_factory=list)
    finishes: list[tuple[ExternalCallTraceHandleV1, ExternalCallTraceFinishV1]] = field(
        default_factory=list
    )

    def begin_external_call(
        self, command: ExternalCallTraceStartV1
    ) -> ExternalCallTraceHandleV1:
        self.starts.append(command)
        return ExternalCallTraceHandleV1(1, f"trace-{len(self.starts)}")

    def finish_external_call(
        self,
        handle: ExternalCallTraceHandleV1,
        result: ExternalCallTraceFinishV1,
    ) -> None:
        self.finishes.append((handle, result))


def _registry(client: _Client) -> ConnectorRuntimeRegistry:
    registry = ConnectorRuntimeRegistry()
    registry.register("google_workspace", _Runtime(client))
    return registry


def test_read_adapter_requires__signed_binding_and__projects_bounded_output() -> None:
    client = _Client(MCPToolCallResultV1(1, "gmail_get_thread", "OK", {"request_id": "r1"}, None))
    binding = load_signed_tool_registry().bind_required(
        "google_workspace", "gmail_get_thread", "READ"
    )

    result = McpConnectorReadAdapter(
        runtime_registry=_registry(client), mcp_client=client
    ).execute_read(binding, {"thread_id": "thread-1"})

    assert result.request_id == "r1"
    assert client.calls[0][1] == "gmail_get_thread"


def test_read_adapter__actual_mcp_dispatch__excludes_arguments_and_payload() -> None:
    client = _Client(
        MCPToolCallResultV1(
            1,
            "gmail_search_threads",
            "OK",
            {
                "request_id": "private-request-id",
                "items": [{"body": "private-mail-body"}],
                "total_count": 1,
                "next_page_token": "private-page-token",
            },
            None,
        )
    )
    binding = load_signed_tool_registry().bind_required(
        "google_workspace", "gmail_search_threads", "READ"
    )
    trace = _ExternalCallTrace()

    result = McpConnectorReadAdapter(
        runtime_registry=_registry(client),
        mcp_client=client,
        external_call_trace=trace,
        run_context_provider=lambda: "run-1",
    ).execute_read(binding, {"query": "private-search-term"})

    assert result.total_count == 1
    assert trace.starts == [
        ExternalCallTraceStartV1(
            schema_version=1,
            domain_run_id="run-1",
            call_kind="CONNECTOR_READ",
            operation="CALL_TOOL",
            connector_id="google_workspace",
            tool_id="gmail_search_threads",
            effect="READ",
        )
    ]
    assert len(trace.finishes) == 1
    finish = trace.finishes[0][1]
    assert finish.status == "COMPLETED"
    assert finish.result_count == 1
    assert finish.has_next_page is True
    exported = repr((trace.starts, trace.finishes))
    assert "private-search-term" not in exported
    assert "private-mail-body" not in exported
    assert "private-page-token" not in exported


def test_read_adapter_accepts__only_an_explicit__internal_capability_binding() -> None:
    binding = google_workspace_internal_read_binding("search_by_recovery_fingerprint")
    client = _Client(
        MCPToolCallResultV1(
            1,
            binding.tool_id,
            "OK",
            {"request_id": "recovery-1", "items": []},
            None,
        )
    )

    result = McpConnectorReadAdapter(
        runtime_registry=_registry(client),
        mcp_client=client,
        internal_bindings=(binding,),
    ).execute_read(
        binding,
        {"resource_type": "task", "recovery_fingerprint": "f" * 64},
    )

    assert result.request_id == "recovery-1"
    assert client.calls[0][1] == "search_by_recovery_fingerprint"


def test_write_adapter__forwards_application__signed_claim_unchanged() -> None:
    client = _Client(MCPToolCallResultV1(1, "gmail_send", "OK", {"request_id": "r1"}, None))
    binding = load_signed_tool_registry().bind_required("google_workspace", "gmail_send", "SEND")

    claim: dict[str, JsonValue] = {
        "claim_id": "claim-1",
        "connector_id": "google_workspace",
        "mcp_process_instance_id": "process-1",
        "signature": "application-signature",
    }
    result = McpConnectorWriteAdapter(
        runtime_registry=_registry(client), mcp_client=client
    ).execute_write(binding, {"draft_id": "draft-1"}, claim)

    sent = client.calls[0][2]
    assert isinstance(sent, dict)
    assert sent["claim_context"] == claim
    assert result.success is True
    assert client.sign_calls == 0


def test_write_adapter__normalizes_raised__transport_certainty() -> None:
    class _FailingClient(_Client):
        def call_tool(
            self, connector_id: str, tool_id: str, arguments: Any, timeout_ms: int
        ) -> MCPToolCallResultV1:
            self.calls.append((connector_id, tool_id, arguments, timeout_ms))
            raise MCPClientPortError(
                code=MCPClientPortErrorCode.TIMEOUT,
                message="response lost",
                delivery_certainty=DeliveryCertainty.SENT_RESPONSE_LOST,
                request_id="request-1",
            )

    client = _FailingClient(MCPToolCallResultV1(1, "gmail_send", "OK", {}, None))
    binding = load_signed_tool_registry().bind_required("google_workspace", "gmail_send", "SEND")

    result = McpConnectorWriteAdapter(
        runtime_registry=_registry(client), mcp_client=client
    ).execute_write(
        binding,
        {"draft_id": "draft-1"},
        {
            "connector_id": "google_workspace",
            "mcp_process_instance_id": "process-1",
            "signature": "application-signature",
        },
    )

    assert result.success is False
    assert result.delivery_certainty == "SENT_RESPONSE_LOST"
    assert result.provider_request_id == "request-1"


def test_write_adapter__with_structured_mcp_error__preserves_validation_code() -> None:
    client = _Client(
        MCPToolCallResultV1(
            1,
            "gmail_send",
            "ERROR",
            {"request_id": "request-1", "delivery_certainty": "NOT_SENT"},
            "TOOL_REJECTED",
            "CLAIM_TOKEN_REUSED",
        )
    )
    binding = load_signed_tool_registry().bind_required(
        "google_workspace", "gmail_send", "SEND"
    )

    result = McpConnectorWriteAdapter(
        runtime_registry=_registry(client), mcp_client=client
    ).execute_write(
        binding,
        {"payload": {"to": ["a@example.com"], "subject": "Hi", "body": "Body"}},
        {
            "connector_id": "google_workspace",
            "mcp_process_instance_id": "process-1",
            "signature": "application-signature",
        },
    )

    assert result.success is False
    assert result.error_code == "TOOL_REJECTED"
    assert result.safe_error_code == "CLAIM_TOKEN_REUSED"
    assert result.delivery_certainty == "NOT_SENT"


def test_read_and__write_adapters_reject__cross_effect_binding() -> None:
    client = _Client(MCPToolCallResultV1(1, "unused", "OK", {}, None))
    registry = _registry(client)
    signed = load_signed_tool_registry()

    with pytest.raises(ValueError, match="READ binding"):
        McpConnectorReadAdapter(runtime_registry=registry, mcp_client=client).execute_read(
            signed.bind_required("google_workspace", "gmail_send", "SEND"), {}
        )
    with pytest.raises(ValueError, match="WRITE binding"):
        McpConnectorWriteAdapter(runtime_registry=registry, mcp_client=client).execute_write(
            signed.bind_required("google_workspace", "gmail_get_thread", "READ"), {}, {}
        )
