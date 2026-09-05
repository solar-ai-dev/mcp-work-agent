from google_work_agent.adapters.connectors.github.github.mcp_server.project_registry import (
    github_registry_manifest_hash,
)
from google_work_agent.adapters.connectors.github.github.mcp_server.project_registry import (
    project_github_registry as github_project_registry,
)
from google_work_agent.adapters.connectors.google.workspace.mcp_server.project_registry import (
    project_registry as google_project_registry,
)
from google_work_agent.adapters.connectors.google.workspace.mcp_server.project_registry import (
    registry_manifest_hash as google_registry_manifest_hash,
)
from google_work_agent.application.tool_registry.load_signed_tool_registry import (
    load_signed_tool_registry,
)


def test_mcp_projections__are_exact__signed_registry_subsets() -> None:
    registry = load_signed_tool_registry()

    assert google_project_registry() == tuple(
        registry.descriptor_expectations("google_workspace")
    )
    assert github_project_registry() == tuple(registry.descriptor_expectations("github"))
    assert google_registry_manifest_hash() == registry.entries_hash
    assert github_registry_manifest_hash() == registry.entries_hash
