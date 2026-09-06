"""GitHub owner-local connector runtime composition."""

from __future__ import annotations

from google_work_agent.adapters.connectors.runtime.connector_runtime_registry import (
    ConnectorRuntimeRegistry,
)
from google_work_agent.adapters.connectors.runtime.mcp_connector_read import (
    McpConnectorReadAdapter,
)
from google_work_agent.adapters.connectors.runtime.mcp_connector_write import (
    McpConnectorWriteAdapter,
)
from google_work_agent.adapters.connectors.runtime.mcp_oauth_credential import (
    McpOAuthCredentialAdapter,
)
from google_work_agent.adapters.connectors.runtime.stdio_mcp_client import (
    MCPArtifactConfig,
    MCPConnectorDescriptor,
    StdioMCPClientAdapter,
)
from google_work_agent.domain.canonical import calculate_canonical_json_hash
from google_work_agent.ports.connector.contracts.validated_connector_tool_binding import (
    ValidatedConnectorToolBindingV1,
)
from google_work_agent.ports.connector.mcp_client_port import MCPToolDescriptorV1
from google_work_agent.ports.system.artifact_signature_verifier import (
    ArtifactSignatureVerifier,
)

GITHUB_CONNECTOR_ID = "github"


def github_internal_read_binding(tool_name: str) -> ValidatedConnectorToolBindingV1:
    if tool_name not in {"search_by_recovery_fingerprint", "github.repositories.list"}:
        raise ValueError(f"unknown GitHub internal capability: {tool_name}")
    contract = {
        "tool_id": tool_name,
        "input": (
            ["cursor"]
            if tool_name == "github.repositories.list"
            else ["repository", "recovery_fingerprint"]
        ),
        "output": (
            ["account_id", "items", "next_cursor"]
            if tool_name == "github.repositories.list"
            else ["items", "coverage_complete", "examined_count"]
        ),
        "version": "v1",
    }
    return ValidatedConnectorToolBindingV1(
        schema_version=1,
        connector_id=GITHUB_CONNECTOR_ID,
        resource_type="internal_capability",
        tool_id=tool_name,
        effect="READ",
        input_schema_ref="v1",
        output_schema_ref="v1",
        registry_entry_hash=calculate_canonical_json_hash(contract),
    )


def build_github_connector_descriptor(
    artifact_config: MCPArtifactConfig,
    *,
    expected_tool_descriptors: tuple[MCPToolDescriptorV1, ...],
) -> MCPConnectorDescriptor:
    return MCPConnectorDescriptor(
        connector_id=GITHUB_CONNECTOR_ID,
        artifact_config=artifact_config,
        expected_tool_descriptors=expected_tool_descriptors,
    )


class GitHubConnector:
    """Own the one GitHub stdio child and its canonical adapters."""

    def __init__(
        self,
        *,
        descriptor: MCPConnectorDescriptor,
        runtime_registry: ConnectorRuntimeRegistry,
        signature_verifier: ArtifactSignatureVerifier | None = None,
    ) -> None:
        if descriptor.connector_id != GITHUB_CONNECTOR_ID:
            raise ValueError("GitHub connector descriptor id mismatch")
        self._descriptor = descriptor
        self._runtime_registry = runtime_registry
        self._signature_verifier = signature_verifier
        self._client: StdioMCPClientAdapter | None = None

    @property
    def connector_id(self) -> str:
        return self._descriptor.connector_id

    @property
    def descriptor(self) -> MCPConnectorDescriptor:
        return self._descriptor

    @property
    def client(self) -> StdioMCPClientAdapter:
        if self._client is None:
            raise RuntimeError("GitHub connector is not started")
        return self._client

    @property
    def read_port(self) -> McpConnectorReadAdapter:
        return McpConnectorReadAdapter(
            runtime_registry=self._runtime_registry,
            mcp_client=self.client,
            internal_bindings=(
                github_internal_read_binding("search_by_recovery_fingerprint"),
                github_internal_read_binding("github.repositories.list"),
            ),
        )

    @property
    def write_port(self) -> McpConnectorWriteAdapter:
        return McpConnectorWriteAdapter(
            runtime_registry=self._runtime_registry,
            mcp_client=self.client,
        )

    @property
    def oauth_port(self) -> McpOAuthCredentialAdapter:
        return McpOAuthCredentialAdapter(
            runtime_registry=self._runtime_registry,
            mcp_client=self.client,
        )

    def start(self) -> StdioMCPClientAdapter:
        if self._client is None:
            self._client = StdioMCPClientAdapter(
                descriptor=self._descriptor,
                runtime_registry=self._runtime_registry,
                signature_verifier=self._signature_verifier,
            )
        return self._client

    def close(self) -> None:
        if self._client is not None:
            self._client.close()
            self._client = None


__all__ = [
    "GITHUB_CONNECTOR_ID",
    "GitHubConnector",
    "build_github_connector_descriptor",
    "github_internal_read_binding",
]
