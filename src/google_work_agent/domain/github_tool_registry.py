"""GitHub connector-local signed tool registry (skeleton, not production-registered)."""

from __future__ import annotations

from google_work_agent.domain.enums import (
    ApprovalRequirement,
    EffectType,
    RecoveryPolicy,
    VerificationPolicy,
)
from google_work_agent.domain.tool_registry import SignedToolRegistry, ToolRegistryEntry

_ISSUE_RESOURCE_TYPE = "TASK"


def build_github_tool_registry() -> SignedToolRegistry:
    """Build the connector-local GitHub Issue Tool registry (P0 skeleton)."""

    return SignedToolRegistry(
        entries=(
            _read_tool(tool_name="github_list_issues", scope="issues.read"),
            _read_tool(tool_name="github_get_issue", scope="issues.read"),
            _create_tool(tool_name="github_create_issue", scope="issues.write"),
            _update_tool(tool_name="github_update_issue", scope="issues.write"),
            _update_tool(tool_name="github_close_issue", scope="issues.write"),
            _update_tool(tool_name="github_reopen_issue", scope="issues.write"),
        )
    )


def _read_tool(*, tool_name: str, scope: str) -> ToolRegistryEntry:
    return ToolRegistryEntry(
        tool_name=tool_name,
        resource_type=_ISSUE_RESOURCE_TYPE,
        effect_type=EffectType.READ,
        approval_requirement=ApprovalRequirement.NONE,
        verification_policy=VerificationPolicy.NONE,
        recovery_policy=RecoveryPolicy.NONE,
        scope=scope,
        retryable=True,
    )


def _create_tool(*, tool_name: str, scope: str) -> ToolRegistryEntry:
    return ToolRegistryEntry(
        tool_name=tool_name,
        resource_type=_ISSUE_RESOURCE_TYPE,
        effect_type=EffectType.CREATE,
        approval_requirement=ApprovalRequirement.REQUIRED,
        verification_policy=VerificationPolicy.GET_COMPARE,
        recovery_policy=RecoveryPolicy.RESOURCE_SEARCH,
        scope=scope,
        retryable=False,
    )


def _update_tool(*, tool_name: str, scope: str) -> ToolRegistryEntry:
    return ToolRegistryEntry(
        tool_name=tool_name,
        resource_type=_ISSUE_RESOURCE_TYPE,
        effect_type=EffectType.UPDATE,
        approval_requirement=ApprovalRequirement.REQUIRED,
        verification_policy=VerificationPolicy.GET_COMPARE,
        recovery_policy=RecoveryPolicy.GET_TARGET,
        scope=scope,
        retryable=False,
    )
