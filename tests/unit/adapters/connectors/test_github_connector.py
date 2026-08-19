from typing import Any

import pytest

from google_work_agent.adapters.connectors.github import (
    GITHUB_CONNECTOR_ID,
    GitHubConnector,
    build_github_connector_descriptor,
)
from google_work_agent.adapters.mcp import MCPArtifactConfig, MCPConnectorDescriptor
from google_work_agent.domain.github_tool_registry import build_github_tool_registry
from google_work_agent.ports import MCPControlResponse, MCPRuntimeMetadata, MCPToolResponse


class _Transport:
    def __init__(self) -> None:
        self.restart_count = 0
        self.closed = False

    def call_tool(self, *, tool_name: str, arguments: dict[str, Any]) -> MCPToolResponse:
        return MCPToolResponse(payload={}, request_id="req-fake-1")

    def call_control(self, *, method: str, arguments: dict[str, Any]) -> MCPControlResponse:
        return MCPControlResponse(payload={}, request_id="req-fake-1")

    def runtime_metadata(self) -> MCPRuntimeMetadata:
        return _metadata(restart_count=self.restart_count)

    def restart(self) -> MCPRuntimeMetadata:
        self.restart_count += 1
        return self.runtime_metadata()

    def close(self) -> None:
        self.closed = True


def test_github_connector_id_matches_frozen_contract() -> None:
    assert GITHUB_CONNECTOR_ID == "github"


def test_build_github_connector_descriptor_uses_github_tool_registry() -> None:
    descriptor = build_github_connector_descriptor(_artifact_config())

    assert descriptor.connector_id == GITHUB_CONNECTOR_ID
    assert descriptor.expected_tool_registry.list_entries() == (
        build_github_tool_registry().list_entries()
    )


def test_github_connector_rejects_descriptor_with_wrong_connector_id() -> None:
    wrong_descriptor = MCPConnectorDescriptor(
        connector_id="not_github",
        artifact_config=_artifact_config(),
        expected_tool_registry=build_github_tool_registry(),
    )

    with pytest.raises(ValueError, match="descriptor id mismatch"):
        GitHubConnector(descriptor=wrong_descriptor)


def test_github_connector_owns_start_health_restart_and_close() -> None:
    transport = _Transport()
    connector = GitHubConnector(
        descriptor=build_github_connector_descriptor(_artifact_config()),
        transport_factory=lambda _descriptor: transport,
    )

    assert connector.connector_id == GITHUB_CONNECTOR_ID
    assert connector.start() is transport
    assert connector.health().process_status == "READY"
    assert connector.restart().restart_count == 1

    connector.close()

    assert transport.closed


def _artifact_config() -> MCPArtifactConfig:
    return MCPArtifactConfig(
        executable_path="unused",
        manifest_path="unused",
        expected_binary_sha256="unused",
        expected_manifest_sha256="unused",
        expected_manifest_version="v1",
        expected_protocol_version="v1",
        expected_tool_registry_version="v1",
        startup_timeout_ms=1,
        request_timeout_ms=1,
        max_restart_count=1,
        environment="TEST",
        service_instance_id="svc-test",
        module_name="google_work_agent.mcp.github_server",
    )


def _metadata(*, restart_count: int) -> MCPRuntimeMetadata:
    return MCPRuntimeMetadata(
        process_status="READY",
        protocol_version="v1",
        manifest_version="v1",
        tool_registry_version="v1",
        available_tool_count=6,
        last_safe_error_code=None,
        restart_count=restart_count,
        process_instance_id="mcp-1",
    )
