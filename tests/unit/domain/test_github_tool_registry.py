from google_work_agent.domain import (
    ApprovalRequirement,
    EffectType,
    RecoveryPolicy,
    VerificationPolicy,
)
from google_work_agent.domain.github_tool_registry import build_github_tool_registry


def test_github_tool_registry_contains_only_p0_issue_tools() -> None:
    registry = build_github_tool_registry()

    names = {entry.tool_name for entry in registry.list_entries()}

    assert names == {
        "github_list_issues",
        "github_get_issue",
        "github_create_issue",
        "github_update_issue",
        "github_close_issue",
        "github_reopen_issue",
    }


def test_github_tool_registry_uses_task_resource_type_for_every_tool() -> None:
    registry = build_github_tool_registry()

    for entry in registry.list_entries():
        assert entry.resource_type == "TASK"


def test_github_read_tool_contract_matches_policy() -> None:
    entry = build_github_tool_registry().require("github_get_issue")

    assert entry.effect_type is EffectType.READ
    assert entry.approval_requirement is ApprovalRequirement.NONE
    assert entry.verification_policy is VerificationPolicy.NONE
    assert entry.recovery_policy is RecoveryPolicy.NONE
    assert entry.retryable is True
    assert entry.scope == "issues.read"


def test_github_create_tool_contract_matches_policy() -> None:
    entry = build_github_tool_registry().require("github_create_issue")

    assert entry.effect_type is EffectType.CREATE
    assert entry.approval_requirement is ApprovalRequirement.REQUIRED
    assert entry.verification_policy is VerificationPolicy.GET_COMPARE
    assert entry.recovery_policy is RecoveryPolicy.RESOURCE_SEARCH
    assert entry.retryable is False
    assert entry.scope == "issues.write"


def test_github_update_close_reopen_tools_share_update_contract() -> None:
    registry = build_github_tool_registry()

    for tool_name in ("github_update_issue", "github_close_issue", "github_reopen_issue"):
        entry = registry.require(tool_name)
        assert entry.effect_type is EffectType.UPDATE
        assert entry.approval_requirement is ApprovalRequirement.REQUIRED
        assert entry.verification_policy is VerificationPolicy.GET_COMPARE
        assert entry.recovery_policy is RecoveryPolicy.GET_TARGET
        assert entry.retryable is False


def test_github_tool_registry_does_not_declare_delete_effect() -> None:
    registry = build_github_tool_registry()

    for entry in registry.list_entries():
        assert entry.effect_type is not EffectType.DELETE


def test_github_tool_registry_entries_carry_a_deterministic_schema_hash() -> None:
    registry = build_github_tool_registry()

    for entry in registry.list_entries():
        assert entry.tool_schema_hash
        assert len(entry.tool_schema_hash) == 64
