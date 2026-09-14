"""Validated Connector READ dispatch through the sole MCP runtime seam."""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Literal, cast

from google_work_agent.adapters.connectors.runtime.connector_runtime_registry import (
    ConnectorRuntimeRegistry,
)
from google_work_agent.ports.connector.connector_failure import (
    ConnectorFailureCode,
    ConnectorOperationFailure,
)
from google_work_agent.ports.connector.connector_read_port import (
    ConnectorReadPort,
    ConnectorReadResultV1,
    JsonValue,
)
from google_work_agent.ports.connector.contracts.validated_connector_tool_binding import (
    ValidatedConnectorToolBindingV1,
)
from google_work_agent.ports.connector.mcp_client_port import MCPClientPort, MCPClientPortError
from google_work_agent.ports.system.external_call_trace_port import (
    ExternalCallTraceFinishV1,
    ExternalCallTraceHandleV1,
    ExternalCallTracePort,
    ExternalCallTraceStartV1,
)


class McpConnectorReadAdapter(ConnectorReadPort):
    def __init__(
        self,
        *,
        runtime_registry: ConnectorRuntimeRegistry,
        mcp_client: MCPClientPort,
        timeout_ms: int = 30_000,
        internal_bindings: tuple[ValidatedConnectorToolBindingV1, ...] = (),
        external_call_trace: ExternalCallTracePort | None = None,
        run_context_provider: Callable[[], str | None] = lambda: None,
    ) -> None:
        self._runtime_registry = runtime_registry
        self._mcp_client = mcp_client
        self._timeout_ms = timeout_ms
        self._internal_bindings = {
            (binding.connector_id, binding.tool_id): binding for binding in internal_bindings
        }
        self._external_call_trace = external_call_trace
        self._run_context_provider = run_context_provider

    def execute_read(
        self,
        binding: ValidatedConnectorToolBindingV1,
        tool_arguments: dict[str, JsonValue],
    ) -> ConnectorReadResultV1:
        if binding.effect != "READ":
            raise ValueError("ConnectorReadPort requires a READ binding")
        self._runtime_registry.resolve(binding.connector_id)
        descriptors = {
            descriptor.tool_id: descriptor
            for descriptor in self._mcp_client.list_tools(binding.connector_id)
        }
        descriptor = descriptors.get(binding.tool_id)
        internal = self._internal_bindings.get((binding.connector_id, binding.tool_id))
        if descriptor is None and binding != internal:
            raise ValueError("validated Connector Tool binding does not match MCP descriptor")
        if descriptor is not None and (
            descriptor.connector_id,
            descriptor.input_schema_ref,
            descriptor.output_schema_ref,
            descriptor.registry_entry_hash,
        ) != (
            binding.connector_id,
            binding.input_schema_ref,
            binding.output_schema_ref,
            binding.registry_entry_hash,
        ):
            raise ValueError("validated Connector Tool binding does not match MCP descriptor")
        trace_started = time.perf_counter()
        trace_handle = self._begin_trace(binding)
        try:
            response = self._mcp_client.call_tool(
                binding.connector_id,
                binding.tool_id,
                tool_arguments,
                self._timeout_ms,
            )
        except Exception as error:
            self._finish_trace(
                trace_handle,
                status="FAILED",
                started=trace_started,
                error=error,
            )
            raise
        output = response.payload if isinstance(response.payload, dict) else None
        response_succeeded = response.transport_status == "OK" and output is not None
        self._finish_trace(
            trace_handle,
            status="COMPLETED" if response_succeeded else "FAILED",
            started=trace_started,
            result_count=(None if output is None else _optional_int(output.get("total_count"))),
            has_next_page=(
                None
                if output is None
                else _optional_string(output.get("next_page_token")) is not None
            ),
            error_type=None if response_succeeded else "ConnectorOperationFailure",
            safe_error_code=(
                None if response_succeeded else response.safe_error_code or response.error_code
            ),
        )
        if not response_succeeded:
            code = {
                "AUTH_REQUIRED": ConnectorFailureCode.AUTH_REQUIRED,
                "PERMISSION_DENIED": ConnectorFailureCode.PERMISSION_DENIED,
                "NOT_FOUND": ConnectorFailureCode.NOT_FOUND,
                "TIMEOUT": ConnectorFailureCode.TIMEOUT,
                "PROCESS_UNAVAILABLE": ConnectorFailureCode.CONNECTION_UNAVAILABLE,
                "CONNECTION_CLOSED": ConnectorFailureCode.CONNECTION_UNAVAILABLE,
                "MALFORMED_RESPONSE": ConnectorFailureCode.MALFORMED_RESPONSE,
                "CONFIGURATION_ERROR": ConnectorFailureCode.CONFIGURATION_ERROR,
                "TOOL_REJECTED": ConnectorFailureCode.INVALID_ARGUMENT,
            }.get(
                response.error_code or "",
                ConnectorFailureCode.UPSTREAM_UNAVAILABLE,
            )
            raise ConnectorOperationFailure(
                code=code,
                detail_code=response.error_code or "CONNECTOR_READ_FAILED",
                retryable=code
                in {
                    ConnectorFailureCode.TIMEOUT,
                    ConnectorFailureCode.CONNECTION_UNAVAILABLE,
                    ConnectorFailureCode.UPSTREAM_UNAVAILABLE,
                },
            )
        output = cast(dict[str, JsonValue], output)
        return ConnectorReadResultV1(
            schema_version=1,
            tool_id=binding.tool_id,
            request_id=str(output.get("request_id", "")),
            output=output,
            next_page_token=_optional_string(output.get("next_page_token")),
            total_count=_optional_int(output.get("total_count")),
        )

    def _begin_trace(
        self, binding: ValidatedConnectorToolBindingV1
    ) -> ExternalCallTraceHandleV1 | None:
        trace = self._external_call_trace
        if trace is None:
            return None
        try:
            return trace.begin_external_call(
                ExternalCallTraceStartV1(
                    schema_version=1,
                    domain_run_id=self._run_context_provider(),
                    call_kind="CONNECTOR_READ",
                    operation="CALL_TOOL",
                    connector_id=binding.connector_id,
                    tool_id=binding.tool_id,
                    effect=binding.effect,
                )
            )
        except Exception:
            return None

    def _finish_trace(
        self,
        handle: ExternalCallTraceHandleV1 | None,
        *,
        status: Literal["COMPLETED", "FAILED"],
        started: float,
        result_count: int | None = None,
        has_next_page: bool | None = None,
        error: Exception | None = None,
        error_type: str | None = None,
        safe_error_code: str | None = None,
    ) -> None:
        trace = self._external_call_trace
        if trace is None or handle is None:
            return
        resolved_error_code = (
            error.code.value if isinstance(error, MCPClientPortError) else safe_error_code
        )
        try:
            trace.finish_external_call(
                handle,
                ExternalCallTraceFinishV1(
                    schema_version=1,
                    status=status,
                    duration_ms=max(0, int((time.perf_counter() - started) * 1000)),
                    result_count=result_count,
                    has_next_page=has_next_page,
                    error_type=(type(error).__name__ if error is not None else error_type),
                    safe_error_code=resolved_error_code,
                ),
            )
        except Exception:
            return


def _optional_string(value: JsonValue) -> str | None:
    return value if isinstance(value, str) and value else None


def _optional_int(value: JsonValue) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


__all__ = ["McpConnectorReadAdapter"]
