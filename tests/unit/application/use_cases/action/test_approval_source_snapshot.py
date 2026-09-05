from __future__ import annotations

from json import dumps
from types import SimpleNamespace
from typing import Any, cast

import pytest

from google_work_agent.application.use_cases.action.approval_source_snapshot import (
    build_approval_source_snapshot,
)
from google_work_agent.domain.action.model import PolicyViolationError
from google_work_agent.domain.canonical import calculate_canonical_json_hash
from google_work_agent.domain.resource_ref.model import ResourceRef


def _action(tool_name: str, arguments: dict[str, object]) -> Any:
    return SimpleNamespace(
        connector_id="github",
        tool_name=tool_name,
        effect_type="UPDATE",
        arguments_json=dumps(arguments),
        target_resource_ref_id="ref-1",
    )


def _target(**changes: object) -> ResourceRef:
    values: dict[str, object] = {
        "id": "ref-1",
        "run_id": "run-1",
        "connector_id": "github",
        "resource_type": "github_issue",
        "resource_id": "acme/repo#7",
        "parent_resource_id": "acme/repo",
        "canonical_url": None,
        "title": "Issue",
        "event_time_ms": None,
        "version_token": "v2",
        "metadata_json": "{}",
        "captured_at_ms": 1,
    }
    values.update(changes)
    return ResourceRef(**cast(Any, values))


@pytest.mark.parametrize(
    "tool_name",
    ("github_update_issue", "github_close_issue", "github_reopen_issue"),
)
def test_github_existing_target__approval_snapshot__binds_exact_identity(
    tool_name: str,
) -> None:
    arguments: dict[str, object] = {"repository": "acme/repo", "issue_number": 7}
    if tool_name == "github_update_issue":
        arguments["title"] = "updated"

    snapshot = build_approval_source_snapshot(
        action=_action(tool_name, arguments),
        plan_run_id="run-1",
        resource_ref=_target(),
    )

    assert snapshot == {
        "resource_type": "github_issue",
        "resource_id": "acme/repo#7",
        "parent_id": "acme/repo",
        "version": "v2",
    }
    assert calculate_canonical_json_hash(snapshot)


@pytest.mark.parametrize(
    "changes",
    (
        {"connector_id": "google_workspace"},
        {"resource_type": "task"},
        {"resource_id": "other/repo#7"},
        {"parent_resource_id": "other/repo"},
        {"resource_id": "acme/repo#abc"},
    ),
)
def test_github_existing_target__approval__rejects_mismatched_authority(
    changes: dict[str, object],
) -> None:
    with pytest.raises(PolicyViolationError):
        build_approval_source_snapshot(
            action=_action(
                "github_update_issue",
                {"repository": "acme/repo", "issue_number": 7, "title": "updated"},
            ),
            plan_run_id="run-1",
            resource_ref=_target(**changes),
        )
