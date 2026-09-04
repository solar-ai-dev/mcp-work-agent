from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest

from google_work_agent.adapters.connectors.runtime.connector_runtime_registry import (
    ConnectorRuntimeRegistry,
)
from google_work_agent.ports.connector.mcp_client_port import (
    MCPRestartResultV1,
    MCPRuntimeMetadata,
    MCPToolCallResultV1,
    MCPToolDescriptorV1,
)


@dataclass
class _Runtime:
    process_id: str = "process-1"
    closed: bool = False

    def runtime_metadata(self) -> MCPRuntimeMetadata:
        return MCPRuntimeMetadata("READY", "1", "1", "1", 0, None, 0, self.process_id)

    def list_tools(self) -> list[MCPToolDescriptorV1]:
        return []

    def call_tool(self, tool_id: str, arguments: Any, timeout_ms: int) -> MCPToolCallResultV1:
        del tool_id, arguments, timeout_ms
        raise AssertionError("tool call is outside this registry test")

    def restart_once(self) -> MCPRestartResultV1:
        return MCPRestartResultV1(1, False, None)

    def sign_claim_context(self, payload: dict[str, object]) -> str:
        return f"{self.process_id}:{payload['claim_id']}"

    def close(self) -> None:
        self.closed = True


def test_registry_rejects__duplicate_authority_and__closes_each_runtime() -> None:
    registry = ConnectorRuntimeRegistry()
    runtime = _Runtime("google-process")
    github_runtime = _Runtime("github-process")
    registry.register("google_workspace", runtime)
    registry.register("github", github_runtime)

    assert registry.resolve("google_workspace") is runtime
    assert registry.resolve("github") is github_runtime
    assert registry.connector_ids() == ("github", "google_workspace")
    assert registry.process_instance_id("google_workspace") == "google-process"
    assert registry.process_instance_id("github") == "github-process"
    assert registry.sign_claim_context("github", {"claim_id": "claim-1"}) == (
        "github-process:claim-1"
    )
    with pytest.raises(ValueError, match="already registered"):
        registry.register("google_workspace", _Runtime())

    registry.close_all()

    assert runtime.closed is True
    assert github_runtime.closed is True
    assert registry.connector_ids() == ()
