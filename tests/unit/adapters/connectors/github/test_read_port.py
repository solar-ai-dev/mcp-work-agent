from __future__ import annotations

from typing import Any

from google_work_agent.adapters.connectors.github.github.mcp_server.composition import (
    GitHubMcpServerState,
)
from google_work_agent.adapters.connectors.github.github.mcp_server.entrypoint import (
    dispatch_request,
)
from google_work_agent.adapters.connectors.runtime.connector_runtime_registry import (
    ConnectorRuntimeRegistry,
)
from google_work_agent.adapters.connectors.runtime.mcp_connector_read import (
    McpConnectorReadAdapter,
)
from google_work_agent.application.tool_registry.load_signed_tool_registry import (
    load_signed_tool_registry,
)
from google_work_agent.ports.connector.mcp_client_port import (
    MCPRestartResultV1,
    MCPRuntimeMetadata,
    MCPToolCallResultV1,
    MCPToolDescriptorV1,
)


class _Api:
    def __init__(self) -> None:
        self.urls: list[str] = []

    def get(self, url: str) -> object:
        self.urls.append(url)
        issue = {
            "number": 7,
            "title": "Canonical connector",
            "body": "Read through the port",
            "state": "open",
            "html_url": "https://github.com/acme/repo/issues/7",
            "updated_at": "2026-09-03T00:00:00Z",
            "labels": [],
            "assignees": [],
        }
        return issue if url.endswith("/7") else [issue]


class _Runtime:
    def runtime_metadata(self) -> MCPRuntimeMetadata:
        return MCPRuntimeMetadata("READY", "1", "1", "1", 6, None, 0, "github-mcp")

    def list_tools(self) -> list[MCPToolDescriptorV1]:
        return []

    def call_tool(
        self, tool_id: str, arguments: Any, timeout_ms: int
    ) -> MCPToolCallResultV1:
        raise AssertionError((tool_id, arguments, timeout_ms))

    def restart_once(self) -> MCPRestartResultV1:
        return MCPRestartResultV1(1, False, None)

    def sign_claim_context(self, payload: dict[str, object]) -> str:
        raise AssertionError(payload)

    def close(self) -> None:
        return None


class _InProcessGitHubMcpClient:
    def __init__(self, state: GitHubMcpServerState) -> None:
        self.state = state
        self.calls: list[str] = []

    def list_tools(self, connector_id: str) -> list[MCPToolDescriptorV1]:
        assert connector_id == "github"
        return load_signed_tool_registry().descriptor_expectations("github")

    def call_tool(
        self,
        connector_id: str,
        tool_id: str,
        arguments: object,
        timeout_ms: int,
    ) -> MCPToolCallResultV1:
        assert connector_id == "github"
        assert isinstance(arguments, dict)
        assert timeout_ms == 30_000
        self.calls.append(tool_id)
        payload = dispatch_request(
            self.state,
            {"type": "tool_call", "tool_name": tool_id, "arguments": arguments},
        )
        return MCPToolCallResultV1(1, tool_id, "OK", payload, None)


def test_list_and_get_issue__cross_signed_binding__read_port_and_github_mcp() -> None:
    api = _Api()
    state = GitHubMcpServerState(api_client=api)  # type: ignore[arg-type]
    client = _InProcessGitHubMcpClient(state)
    registry = ConnectorRuntimeRegistry()
    registry.register("github", _Runtime())
    reader = McpConnectorReadAdapter(
        runtime_registry=registry,
        mcp_client=client,  # type: ignore[arg-type]
    )
    signed = load_signed_tool_registry()

    listed = reader.execute_read(
        signed.bind_required("github", "github_list_issues", "READ"),
        {"repository": "acme/repo", "state": "OPEN"},
    )
    fetched = reader.execute_read(
        signed.bind_required("github", "github_get_issue", "READ"),
        {"repository": "acme/repo", "issue_number": 7},
    )

    assert client.calls == ["github_list_issues", "github_get_issue"]
    assert listed.output["items"][0]["resource_id"] == "acme/repo#7"
    assert fetched.output["item"]["parent_id"] == "acme/repo"
    assert api.urls[0].startswith("https://api.github.com/repos/acme/repo/issues?")
    assert api.urls[1].endswith("/repos/acme/repo/issues/7")
