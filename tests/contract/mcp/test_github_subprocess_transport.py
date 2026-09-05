from __future__ import annotations

import json
import sys
from pathlib import Path

from google_work_agent.adapters.connectors.github.github.composition import (
    build_github_connector_descriptor,
)
from google_work_agent.adapters.connectors.runtime.connector_runtime_registry import (
    ConnectorRuntimeRegistry,
)
from google_work_agent.adapters.connectors.runtime.stdio_mcp_client import (
    MCPArtifactConfig,
    StdioMCPClientAdapter,
    build_manifest_payload_for_descriptors,
    calculate_file_sha256,
)
from google_work_agent.application.tool_registry.load_signed_tool_registry import (
    load_signed_tool_registry,
)

GITHUB_MODULE = (
    "google_work_agent.adapters.connectors.github.github.mcp_server.entrypoint"
)


def test_github_mcp__handshakes_and_advertises__signed_tools(tmp_path: Path) -> None:
    client, registry = _start_client(tmp_path)
    try:
        metadata = client.runtime_metadata()
        assert metadata.process_status == "READY"
        assert metadata.process_instance_id is not None
        assert registry.connector_ids() == ("github",)
        assert {tool.tool_id for tool in client.list_tools("github")} == {
            "github_list_issues",
            "github_get_issue",
            "github_create_issue",
            "github_update_issue",
            "github_close_issue",
            "github_reopen_issue",
        }
    finally:
        registry.close_all()


def test_github_write__rejects_invalid_claim__before_provider_access(tmp_path: Path) -> None:
    client, registry = _start_client(tmp_path)
    try:
        result = client.call_tool(
            "github",
            "github_create_issue",
            {
                "repository": "acme/repo",
                "title": "Issue",
                "claim_context": {"signature": "not-yet-consumed"},
            },
            5_000,
        )

        assert result.transport_status == "ERROR"
        assert result.error_code == "TOOL_REJECTED"
        assert result.payload["delivery_certainty"] == "NOT_SENT"
    finally:
        registry.close_all()


def test_github_control__reports_unavailable__without_client_id(
    tmp_path: Path,
) -> None:
    client, registry = _start_client(tmp_path)
    try:
        result = client.call_tool("github", "github.connection.get", {}, 5_000)

        assert result.transport_status == "OK"
        assert result.payload["connected"] is False
        assert result.payload["credential_state"] == "ERROR"
        assert result.payload["detail_code"] == "GITHUB_APP_CLIENT_ID_MISSING"
        assert "token" not in json.dumps(result.payload).lower()
    finally:
        registry.close_all()


def _start_client(tmp_path: Path) -> tuple[StdioMCPClientAdapter, ConnectorRuntimeRegistry]:
    signed = load_signed_tool_registry()
    descriptors = tuple(signed.descriptor_expectations("github"))
    manifest_path = tmp_path / "github-mcp-manifest.json"
    manifest_path.write_text(
        json.dumps(
            build_manifest_payload_for_descriptors(
                connector_id="github",
                registry_manifest_hash=signed.entries_hash,
                descriptors=descriptors,
            ),
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    executable = Path(sys.executable).resolve()
    descriptor = build_github_connector_descriptor(
        MCPArtifactConfig(
            executable_path=str(executable),
            manifest_path=str(manifest_path.resolve()),
            expected_binary_sha256=calculate_file_sha256(executable),
            expected_manifest_sha256=calculate_file_sha256(manifest_path),
            expected_manifest_version="2026-08-07.p0",
            expected_protocol_version="2026-08-07.p0",
            expected_registry_manifest_hash=signed.entries_hash,
            startup_timeout_ms=5_000,
            request_timeout_ms=5_000,
            max_restart_count=1,
            environment="DEVELOPMENT",
            service_instance_id="service-contract-github",
            module_name=GITHUB_MODULE,
            working_directory=str(Path(__file__).resolve().parents[3]),
            extra_environment={"GITHUB_APP_CLIENT_ID": ""},
        ),
        expected_tool_descriptors=descriptors,
    )
    registry = ConnectorRuntimeRegistry()
    return StdioMCPClientAdapter(descriptor=descriptor, runtime_registry=registry), registry
