from __future__ import annotations

from json import dumps
from types import SimpleNamespace
from typing import Any, cast

import pytest

from google_work_agent.application.tool_registry.load_signed_tool_registry import (
    load_signed_tool_registry,
)
from google_work_agent.application.use_cases.claim._write_preflight import (
    _WritePreflight,
    validate_preflight_target,
)
from google_work_agent.application.use_cases.resource.connector_read_projection import (
    ConnectorReadProjection,
)
from google_work_agent.domain.action.model import PolicyViolationError
from google_work_agent.domain.canonical import calculate_canonical_json_hash
from google_work_agent.domain.resource_ref.model import ResourceRef as ResourceRefRecord
from google_work_agent.ports.connector.contracts.resource_snapshot import (
    ResourceSnapshot,
    ResourceType,
)


def _snapshot(
    *,
    resource_type: ResourceType = ResourceType.TASK,
    resource_id: str = "task-1",
    parent_id: str | None = "list-1",
    version: str = "v2",
) -> ResourceSnapshot:
    return ResourceSnapshot(
        fixture_snapshot_id="fixture-1",
        resource_type=resource_type,
        resource_id=resource_id,
        parent_id=parent_id,
        related_resource_ids=(),
        version=version,
        recovery_fingerprint=None,
        payload={},
    )


def _ref(
    *,
    resource_id: str = "task-1",
    parent_id: str | None = "list-1",
    version_token: str | None = "v2",
) -> ResourceRefRecord:
    return ResourceRefRecord(
        id="ref-1",
        run_id="run-1",
        connector_id="google_workspace",
        resource_type="task",
        resource_id=resource_id,
        parent_resource_id=parent_id,
        canonical_url=None,
        title=None,
        event_time_ms=None,
        version_token=version_token,
        metadata_json="{}",
        captured_at_ms=1,
    )


def test_update_target__requires_persisted__reference() -> None:
    with pytest.raises(PolicyViolationError, match="persisted target reference"):
        validate_preflight_target(
            snapshot=_snapshot(),
            target_ref=None,
            expected_resource_type=ResourceType.TASK,
            expected_parent_id="list-1",
            require_target_ref=True,
            require_version_token=True,
        )


def test_update_target__requires_persisted__version() -> None:
    with pytest.raises(PolicyViolationError, match="persisted target version"):
        validate_preflight_target(
            snapshot=_snapshot(),
            target_ref=_ref(version_token=None),
            expected_resource_type=ResourceType.TASK,
            expected_parent_id="list-1",
            require_target_ref=True,
            require_version_token=True,
        )


def test_update_target__rejects_version__drift() -> None:
    with pytest.raises(PolicyViolationError, match="version mismatch"):
        validate_preflight_target(
            snapshot=_snapshot(version="v3"),
            target_ref=_ref(version_token="v2"),
            expected_resource_type=ResourceType.TASK,
            expected_parent_id="list-1",
            require_target_ref=True,
            require_version_token=True,
        )


def test_update_target__rejects_identity__drift() -> None:
    with pytest.raises(PolicyViolationError, match="identity mismatch"):
        validate_preflight_target(
            snapshot=_snapshot(resource_id="task-2"),
            target_ref=_ref(resource_id="task-1"),
            expected_resource_type=ResourceType.TASK,
            expected_parent_id="list-1",
            require_target_ref=True,
            require_version_token=True,
        )


def test_update_target__rejects_parent__drift() -> None:
    with pytest.raises(PolicyViolationError, match="parent mismatch"):
        validate_preflight_target(
            snapshot=_snapshot(parent_id="list-2"),
            target_ref=_ref(parent_id="list-1"),
            expected_resource_type=ResourceType.TASK,
            expected_parent_id="list-1",
            require_target_ref=True,
            require_version_token=True,
        )


def test_update_target__accepts_same__identity_and_version() -> None:
    validate_preflight_target(
        snapshot=_snapshot(),
        target_ref=_ref(),
        expected_resource_type=ResourceType.TASK,
        expected_parent_id="list-1",
        require_target_ref=True,
        require_version_token=True,
    )


class _GitHubGateway:
    def __init__(self) -> None:
        self.calls: list[tuple[str, int]] = []

    def get_github_issue(self, *, repository: str, issue_number: int) -> ResourceSnapshot:
        self.calls.append((repository, issue_number))
        return ResourceSnapshot(
            fixture_snapshot_id="acme/repo#7",
            resource_type=ResourceType.GITHUB_ISSUE,
            resource_id="acme/repo#7",
            parent_id="acme/repo",
            related_resource_ids=("acme/repo",),
            version="v2",
            recovery_fingerprint=None,
            payload={"title": "issue", "state": "OPEN"},
        )


class _ConnectorReadPortRecorder:
    def __init__(self) -> None:
        self.calls: list[tuple[object, object]] = []

    def execute_read(self, binding: object, arguments: object) -> None:
        self.calls.append((binding, arguments))
        raise AssertionError("ConnectorReadPort must not run for an invalid target")


class _PreflightRepository:
    def __init__(self, value: object | None) -> None:
        self._value = value

    def get(self, _identity: str) -> object | None:
        return self._value


class _PreflightPlans(_PreflightRepository):
    def load_bundle(self, _identity: str) -> object:
        return SimpleNamespace(plan=self._value)


class _PreflightApprovals:
    def __init__(self, approval: object) -> None:
        self._approval = approval

    def get_active_for_action(self, _action_id: str) -> object:
        return self._approval


class _PreflightEvidence:
    def list_for_action(self, _action_id: str) -> tuple[object, ...]:
        return (SimpleNamespace(id="evidence-1", origin_type="USER_MESSAGE"),)


class _PreflightUnitOfWork:
    def __init__(
        self,
        *,
        tool_name: str,
        arguments: dict[str, object],
        recovery_fingerprint: str = "fingerprint-1",
        target_connector_id: str = "github",
        target_resource_type: str = "github_issue",
        target_resource_id: str = "acme/repo#7",
        target_parent_id: str | None = "acme/repo",
        target_version: str | None = "v2",
        approved_arguments: dict[str, object] | None = None,
        approval_source_snapshot: dict[str, object] | None = None,
    ) -> None:
        targeted = tool_name != "github_create_issue"
        arguments_hash = calculate_canonical_json_hash(arguments)
        action = SimpleNamespace(
            id="action-1",
            plan_id="plan-1",
            status="APPROVED",
            connector_id="github",
            tool_name=tool_name,
            arguments_json=dumps(arguments),
            arguments_hash=arguments_hash,
            version=1,
            effect_type="CREATE" if not targeted else "UPDATE",
            target_resource_ref_id="ref-1" if targeted else None,
        )
        target = ResourceRefRecord(
            id="ref-1",
            run_id="run-1",
            connector_id=target_connector_id,
            resource_type=target_resource_type,
            resource_id=target_resource_id,
            parent_resource_id=target_parent_id,
            canonical_url=None,
            title=None,
            event_time_ms=None,
            version_token=target_version,
            metadata_json="{}",
            captured_at_ms=1,
        )
        source_snapshot = approval_source_snapshot or (
            {
                "resource_type": "github_issue",
                "resource_id": target_resource_id,
                "parent_id": target_parent_id,
                "version": target_version,
            }
            if targeted
            else {}
        )
        approval = SimpleNamespace(
            id="approval-1",
            action_version=1,
            canonical_arguments_hash=calculate_canonical_json_hash(
                arguments if approved_arguments is None else approved_arguments
            ),
            source_snapshot_json=dumps(source_snapshot),
            source_snapshot_hash=calculate_canonical_json_hash(source_snapshot),
            recovery_fingerprint=recovery_fingerprint,
        )
        self.actions = _PreflightRepository(action)
        self.plans = _PreflightPlans(SimpleNamespace(id="plan-1", run_id="run-1"))
        self.approvals = _PreflightApprovals(approval)
        self.evidence = _PreflightEvidence()
        self.resource_refs = _PreflightRepository(target if targeted else None)

    def __enter__(self) -> _PreflightUnitOfWork:
        return self

    def __exit__(self, *args: object) -> None:
        return None


@pytest.mark.parametrize(
    "tool_name",
    ("github_update_issue", "github_close_issue", "github_reopen_issue"),
)
def test_github_targeted_write__performs_fresh_get__before_claim(
    tool_name: str,
) -> None:
    arguments: dict[str, object] = {"repository": "acme/repo", "issue_number": 7}
    if tool_name == "github_update_issue":
        arguments["title"] = "updated"
    gateway = _GitHubGateway()
    preflight = _WritePreflight(
        unit_of_work_factory=cast(
            Any,
            lambda: _PreflightUnitOfWork(tool_name=tool_name, arguments=arguments),
        ),
        gateway=cast(Any, gateway),
        tool_registry=load_signed_tool_registry(),
    )

    snapshot = preflight(action_id="action-1")

    assert gateway.calls == [("acme/repo", 7)]
    assert snapshot == {
        "resource_type": "github_issue",
        "resource_id": "acme/repo#7",
        "parent_id": "acme/repo",
        "version": "v2",
    }


@pytest.mark.parametrize(
    ("tool_name", "overrides"),
    [
        (tool_name, {"arguments": {"repository": "other/repo", "issue_number": 7}})
        for tool_name in (
            "github_update_issue",
            "github_close_issue",
            "github_reopen_issue",
        )
    ]
    + [
        ("github_update_issue", {"target_parent_id": "other/repo"}),
        ("github_update_issue", {"target_connector_id": "google_workspace"}),
        ("github_update_issue", {"target_resource_type": "task"}),
    ]
    + [
        ("github_update_issue", {"target_resource_id": resource_id})
        for resource_id in (
            "acme/repo",
            "acme/repo#",
            "#7",
            "acme//repo#7",
            "acme/repo#abc",
        )
    ],
)
def test_github_targeted_write__identity_mismatch__blocks_before_provider_get(
    tool_name: str,
    overrides: dict[str, object],
) -> None:
    arguments = cast(
        dict[str, object],
        overrides.get("arguments", {"repository": "acme/repo", "issue_number": 7}),
    )
    if tool_name == "github_update_issue":
        arguments["title"] = "updated"
    gateway = _GitHubGateway()
    preflight = _WritePreflight(
        unit_of_work_factory=cast(
            Any,
            lambda: _PreflightUnitOfWork(
                tool_name=tool_name,
                arguments=arguments,
                target_connector_id=cast(str, overrides.get("target_connector_id", "github")),
                target_resource_type=cast(
                    str, overrides.get("target_resource_type", "github_issue")
                ),
                target_resource_id=cast(str, overrides.get("target_resource_id", "acme/repo#7")),
                target_parent_id=cast(str | None, overrides.get("target_parent_id", "acme/repo")),
            ),
        ),
        gateway=cast(Any, gateway),
        tool_registry=load_signed_tool_registry(),
    )

    with pytest.raises(PolicyViolationError):
        preflight(action_id="action-1")

    assert gateway.calls == []


def test_github_targeted_write__approval_argument_tampering__blocks_before_provider_get() -> None:
    gateway = _GitHubGateway()
    preflight = _WritePreflight(
        unit_of_work_factory=cast(
            Any,
            lambda: _PreflightUnitOfWork(
                tool_name="github_close_issue",
                arguments={"repository": "other/repo", "issue_number": 9},
                target_resource_id="other/repo#9",
                target_parent_id="other/repo",
                approved_arguments={"repository": "acme/repo", "issue_number": 7},
                approval_source_snapshot={
                    "resource_type": "github_issue",
                    "resource_id": "acme/repo#7",
                    "parent_id": "acme/repo",
                    "version": "v2",
                },
            ),
        ),
        gateway=cast(Any, gateway),
        tool_registry=load_signed_tool_registry(),
    )

    with pytest.raises(PolicyViolationError, match="arguments binding is stale"):
        preflight(action_id="action-1")

    assert gateway.calls == []


@pytest.mark.parametrize(
    "tool_name",
    ("github_update_issue", "github_close_issue", "github_reopen_issue"),
)
def test_github_targeted_write__identity_mismatch__skips_connector_read_port(
    tool_name: str,
) -> None:
    arguments: dict[str, object] = {"repository": "acme/repo", "issue_number": 7}
    if tool_name == "github_update_issue":
        arguments["title"] = "updated"
    connector_reader = _ConnectorReadPortRecorder()
    registry = load_signed_tool_registry()
    preflight = _WritePreflight(
        unit_of_work_factory=cast(
            Any,
            lambda: _PreflightUnitOfWork(
                tool_name=tool_name,
                arguments=arguments,
                target_resource_id="other/repo#7",
            ),
        ),
        gateway=cast(
            Any,
            ConnectorReadProjection(
                connector_reader=cast(Any, connector_reader),
                tool_registry=registry,
            ),
        ),
        tool_registry=registry,
    )

    with pytest.raises(PolicyViolationError):
        preflight(action_id="action-1")

    assert connector_reader.calls == []


def test_github_targeted_write__approval_target_tampering__blocks_before_provider_get() -> None:
    gateway = _GitHubGateway()
    preflight = _WritePreflight(
        unit_of_work_factory=cast(
            Any,
            lambda: _PreflightUnitOfWork(
                tool_name="github_reopen_issue",
                arguments={"repository": "acme/repo", "issue_number": 7},
                target_version="v3",
                approval_source_snapshot={
                    "resource_type": "github_issue",
                    "resource_id": "acme/repo#7",
                    "parent_id": "acme/repo",
                    "version": "v2",
                },
            ),
        ),
        gateway=cast(Any, gateway),
        tool_registry=load_signed_tool_registry(),
    )

    with pytest.raises(PolicyViolationError, match="target binding is stale"):
        preflight(action_id="action-1")

    assert gateway.calls == []


def test_github_create__validates_repository_and_fingerprint__without_mutation() -> None:
    gateway = _GitHubGateway()
    preflight = _WritePreflight(
        unit_of_work_factory=cast(
            Any,
            lambda: _PreflightUnitOfWork(
                tool_name="github_create_issue",
                arguments={"repository": "acme/repo", "title": "new issue"},
            ),
        ),
        gateway=cast(Any, gateway),
        tool_registry=load_signed_tool_registry(),
    )

    assert preflight(action_id="action-1") == {}
    assert gateway.calls == []


def test_github_create_missing_fingerprint__is_blocked__before_mutation() -> None:
    gateway = _GitHubGateway()
    preflight = _WritePreflight(
        unit_of_work_factory=cast(
            Any,
            lambda: _PreflightUnitOfWork(
                tool_name="github_create_issue",
                arguments={"repository": "acme/repo", "title": "new issue"},
                recovery_fingerprint="",
            ),
        ),
        gateway=cast(Any, gateway),
        tool_registry=load_signed_tool_registry(),
    )

    with pytest.raises(PolicyViolationError, match="recovery fingerprint"):
        preflight(action_id="action-1")

    assert gateway.calls == []
