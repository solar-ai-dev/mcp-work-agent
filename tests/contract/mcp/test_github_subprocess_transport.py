from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from google_work_agent.adapters.connectors.github import build_github_connector_descriptor
from google_work_agent.adapters.mcp import (
    MCPArtifactConfig,
    SubprocessMCPTransport,
    calculate_file_sha256,
)
from google_work_agent.adapters.mcp.transport import build_manifest_payload_for_registry
from google_work_agent.domain.github_tool_registry import build_github_tool_registry
from google_work_agent.ports import MCPTransportError, MCPTransportErrorCode


def test_github_mcp_skeleton_handshakes_and_advertises_registered_tools(tmp_path: Path) -> None:
    manifest_path = _write_manifest(tmp_path)
    descriptor = build_github_connector_descriptor(_artifact_config(manifest_path))

    transport = SubprocessMCPTransport(descriptor=descriptor)
    try:
        runtime = transport.runtime_metadata()
        assert runtime.process_status == "READY"
        assert runtime.process_instance_id is not None
        assert runtime.available_tool_count == len(build_github_tool_registry().list_entries())
    finally:
        transport.close()


@pytest.mark.parametrize(
    "tool_name",
    (
        "github_list_issues",
        "github_get_issue",
        "github_create_issue",
        "github_update_issue",
        "github_close_issue",
        "github_reopen_issue",
    ),
)
def test_github_mcp_skeleton_all_declared_tools_are_active_not_tool_not_available(
    tmp_path: Path, tool_name: str
) -> None:
    """All six P0 tools must reach a real handler (and fail on missing/
    invalid arguments) instead of the GITHUB-1 TOOL_NOT_AVAILABLE
    short-circuit -- GITHUB-3A activates the last four (WRITE).
    """

    manifest_path = _write_manifest(tmp_path)
    descriptor = build_github_connector_descriptor(_artifact_config(manifest_path))

    transport = SubprocessMCPTransport(descriptor=descriptor)
    try:
        with pytest.raises(MCPTransportError) as captured:
            transport.call_tool(tool_name=tool_name, arguments={})

        assert captured.value.code is MCPTransportErrorCode.TOOL_REJECTED
        assert str(captured.value) != "TOOL_NOT_AVAILABLE"
        assert str(captured.value) == "REPOSITORY_INVALID"
    finally:
        transport.close()


def test_github_mcp_skeleton_reports_tool_not_available_for_an_unregistered_tool(
    tmp_path: Path,
) -> None:
    """A tool name outside the P0 scope (e.g. a future comment/milestone
    tool) must still fall through to TOOL_NOT_AVAILABLE, not crash.
    """

    manifest_path = _write_manifest(tmp_path)
    descriptor = build_github_connector_descriptor(_artifact_config(manifest_path))

    transport = SubprocessMCPTransport(descriptor=descriptor)
    try:
        with pytest.raises(MCPTransportError) as captured:
            transport.call_tool(tool_name="github_add_comment", arguments={})

        assert captured.value.code is MCPTransportErrorCode.TOOL_REJECTED
        assert str(captured.value) == "TOOL_NOT_AVAILABLE"
        assert captured.value.dispatch_started is False
    finally:
        transport.close()


def test_github_mcp_skeleton_reports_configuration_error_without_app_client_id(
    tmp_path: Path,
) -> None:
    """The auth control boundary is reachable but safe-by-default: with no
    GITHUB_APP_CLIENT_ID in the child process environment, it must fail
    closed with a CONFIGURATION_ERROR instead of touching the network or the
    OS keyring.
    """

    manifest_path = _write_manifest(tmp_path)
    descriptor = build_github_connector_descriptor(_artifact_config(manifest_path))

    transport = SubprocessMCPTransport(descriptor=descriptor)
    try:
        with pytest.raises(MCPTransportError) as captured:
            transport.call_control(method="github.connection.get", arguments={})

        assert captured.value.code is MCPTransportErrorCode.CONFIGURATION_ERROR
        assert str(captured.value) == "GITHUB_APP_CLIENT_ID_MISSING"
    finally:
        transport.close()


def _write_manifest(tmp_path: Path) -> Path:
    manifest_path = tmp_path / "github-mcp-manifest.json"
    payload = build_manifest_payload_for_registry(build_github_tool_registry())
    manifest_path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
    return manifest_path


def _artifact_config(manifest_path: Path) -> MCPArtifactConfig:
    executable = Path(sys.executable).resolve()
    payload = build_manifest_payload_for_registry(build_github_tool_registry())
    return MCPArtifactConfig(
        executable_path=str(executable),
        manifest_path=str(manifest_path.resolve()),
        expected_binary_sha256=calculate_file_sha256(executable),
        expected_manifest_sha256=calculate_file_sha256(manifest_path.resolve()),
        expected_manifest_version=str(payload["manifest_version"]),
        expected_protocol_version=str(payload["protocol_version"]),
        expected_tool_registry_version=str(payload["tool_registry_version"]),
        startup_timeout_ms=5_000,
        request_timeout_ms=5_000,
        max_restart_count=1,
        environment="DEVELOPMENT",
        service_instance_id="svc-contract-github",
        working_directory=str(Path(__file__).resolve().parents[3]),
        module_name="google_work_agent.mcp.github_server",
    )
