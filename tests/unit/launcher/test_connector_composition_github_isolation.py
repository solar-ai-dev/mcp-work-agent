from __future__ import annotations

import sys
from pathlib import Path

import pytest

from google_work_agent.api import composition
from google_work_agent.application.tool_registry.load_signed_tool_registry import (
    load_signed_tool_registry,
)
from google_work_agent.ports.connector.mcp_client_port import (
    MCPRuntimeMetadata,
)


class _RuntimeHandle:
    def __init__(self, connector_id: str) -> None:
        self.connector_id = connector_id

    def runtime_metadata(self) -> MCPRuntimeMetadata:
        return MCPRuntimeMetadata(
            "READY", "1", "1", "1", 0, None, 0, f"{self.connector_id}-process"
        )

    def sign_claim_context(self, payload: dict[str, object]) -> str:
        return f"{self.connector_id}:{payload}"

    def close(self) -> None:
        return None


class _ConnectorWithoutProcess:
    def __init__(self, *, descriptor: object, runtime_registry: object, **_kwargs: object) -> None:
        self.descriptor = descriptor
        self.runtime_registry = runtime_registry
        self.connector_id = descriptor.connector_id  # type: ignore[attr-defined]

    def start(self) -> None:
        self.runtime_registry.register(  # type: ignore[attr-defined]
            self.connector_id,
            _RuntimeHandle(self.connector_id),
        )

    def close(self) -> None:
        return None


def test_build_connectors__registers_google_workspace__and_github(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(composition, "GoogleWorkspaceConnector", _ConnectorWithoutProcess)
    monkeypatch.setattr(composition, "GitHubConnector", _ConnectorWithoutProcess)
    signed = load_signed_tool_registry()
    manifest = composition._write_mcp_manifest(tmp_path, signed)

    bundle = composition._build_connectors(
        mcp_manifest_path=manifest,
        mcp_manifest_version="2026-08-07.p0",
        service_instance_id="service-1",
        attachment_staging_dir=tmp_path / "attachments",
        python_executable=Path(sys.executable).resolve(),
        working_directory=Path(__file__).resolve().parents[3],
        environment="DEVELOPMENT",
        oauth_client_id="unused",
        github_oauth_client_id="github-client-id",
        github_oauth_scope="repo",
        development_tool_registry=signed,
    )

    assert bundle.runtime_registry.connector_ids() == ("github", "google_workspace")
    assert set(bundle.connectors) == {"google_workspace", "github"}
    github_environment = bundle.connectors["github"].descriptor.artifact_config.extra_environment
    assert github_environment == {
        "GITHUB_APP_CLIENT_ID": "github-client-id",
        "GITHUB_APP_SCOPE": "repo",
    }
    assert "GITHUB_TOKEN" not in github_environment
