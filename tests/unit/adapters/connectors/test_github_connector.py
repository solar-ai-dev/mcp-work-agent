from pathlib import Path

import pytest

from google_work_agent.adapters.connectors.github.github import composition
from google_work_agent.adapters.connectors.github.github.composition import (
    GITHUB_CONNECTOR_ID,
    GitHubConnector,
    build_github_connector_descriptor,
)
from google_work_agent.adapters.connectors.runtime.connector_runtime_registry import (
    ConnectorRuntimeRegistry,
)
from google_work_agent.adapters.connectors.runtime.stdio_mcp_client import (
    MCPArtifactConfig,
    MCPConnectorDescriptor,
)
from google_work_agent.application.tool_registry.load_signed_tool_registry import (
    load_signed_tool_registry,
)


def test_github_connector_descriptor__uses_signed__registry_subset() -> None:
    expected = tuple(load_signed_tool_registry().descriptor_expectations("github"))

    descriptor = build_github_connector_descriptor(
        _artifact_config(),
        expected_tool_descriptors=expected,
    )

    assert descriptor.connector_id == GITHUB_CONNECTOR_ID
    assert descriptor.expected_tool_descriptors == expected


def test_github_connector__rejects_descriptor__with_wrong_connector_id() -> None:
    descriptor = MCPConnectorDescriptor(
        connector_id="not_github",
        artifact_config=_artifact_config(),
        expected_tool_descriptors=(),
    )

    with pytest.raises(ValueError, match="descriptor id mismatch"):
        GitHubConnector(
            descriptor=descriptor,
            runtime_registry=ConnectorRuntimeRegistry(),
        )


def test_github_connector__owns_one__client_lifecycle(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clients: list[_FakeClient] = []

    def build_client(**_kwargs: object) -> _FakeClient:
        client = _FakeClient()
        clients.append(client)
        return client

    monkeypatch.setattr(composition, "StdioMCPClientAdapter", build_client)
    connector = GitHubConnector(
        descriptor=build_github_connector_descriptor(
            _artifact_config(),
            expected_tool_descriptors=tuple(
                load_signed_tool_registry().descriptor_expectations("github")
            ),
        ),
        runtime_registry=ConnectorRuntimeRegistry(),
    )

    assert connector.start() is connector.start()
    assert len(clients) == 1

    connector.close()

    assert clients[0].closed is True


class _FakeClient:
    def __init__(self) -> None:
        self.closed = False

    def close(self) -> None:
        self.closed = True


def _artifact_config() -> MCPArtifactConfig:
    return MCPArtifactConfig(
        executable_path=str(Path("unused.exe")),
        manifest_path=str(Path("unused.json")),
        expected_binary_sha256="0" * 64,
        expected_manifest_sha256="0" * 64,
        expected_manifest_version="2026-08-07.p0",
        expected_protocol_version="2026-08-07.p0",
        expected_registry_manifest_hash="0" * 64,
        startup_timeout_ms=1,
        request_timeout_ms=1,
        max_restart_count=1,
        environment="TEST",
        service_instance_id="service-1",
    )
