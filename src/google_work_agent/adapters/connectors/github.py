"""GitHub connector composition (skeleton, not production-registered)."""

from __future__ import annotations

from collections.abc import Callable

from google_work_agent.adapters.connectors.runtime import (
    ConnectorMcpRuntime,
    RestartableMCPTransport,
)
from google_work_agent.adapters.mcp.transport import (
    MCPArtifactConfig,
    MCPConnectorDescriptor,
    SubprocessMCPTransport,
)
from google_work_agent.domain.github_tool_registry import build_github_tool_registry
from google_work_agent.domain.tool_registry import SignedToolRegistry
from google_work_agent.ports import MCPRuntimeMetadata, MCPTransport

GITHUB_CONNECTOR_ID = "github"


def build_github_connector_descriptor(
    artifact_config: MCPArtifactConfig,
    *,
    tool_registry: SignedToolRegistry | None = None,
) -> MCPConnectorDescriptor:
    return MCPConnectorDescriptor(
        connector_id=GITHUB_CONNECTOR_ID,
        artifact_config=artifact_config,
        expected_tool_registry=tool_registry or build_github_tool_registry(),
    )


class GitHubConnector:
    """`ConnectorRuntimeHandle` implementation for the GitHub MCP skeleton."""

    def __init__(
        self,
        *,
        descriptor: MCPConnectorDescriptor,
        transport_factory: (
            Callable[[MCPConnectorDescriptor], RestartableMCPTransport] | None
        ) = None,
    ) -> None:
        if descriptor.connector_id != GITHUB_CONNECTOR_ID:
            raise ValueError("GitHub connector descriptor id mismatch")
        self._runtime = ConnectorMcpRuntime(
            descriptor=descriptor,
            transport_factory=transport_factory
            or (lambda value: SubprocessMCPTransport(descriptor=value)),
        )

    @property
    def connector_id(self) -> str:
        return self._runtime.connector_id

    @property
    def descriptor(self) -> MCPConnectorDescriptor:
        return self._runtime.descriptor

    @property
    def transport(self) -> MCPTransport:
        return self._runtime.transport_for_diagnostics

    def start(self) -> MCPTransport:
        return self._runtime.start()

    def health(self) -> MCPRuntimeMetadata:
        return self._runtime.health()

    def restart(self) -> MCPRuntimeMetadata:
        return self._runtime.restart()

    def close(self) -> None:
        self._runtime.close()
