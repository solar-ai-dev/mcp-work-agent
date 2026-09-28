from copy import deepcopy
from typing import Any, cast

import pytest

from google_work_agent.application.agents.retrieval.contracts.retrieval_result import (
    AcquisitionResultV1,
)
from google_work_agent.application.agents.retrieval.normalize_segments import (
    DEFAULT_CONTEXT_BUDGET,
    ContextBudget,
    normalize_segments,
    rehydrate_normalized_segments,
)
from google_work_agent.application.agents.retrieval.project_task_calendar_source_snapshots import (
    project_task_calendar_source_snapshots,
    task_calendar_snapshot_fields,
    task_calendar_source_snapshot,
)


def _resource(resource_type: str = "task", **fields: object) -> dict[str, object]:
    return {
        "resource_type": resource_type,
        "resource_handle": f"{resource_type}:resource-1",
        "resource_id": "resource-1",
        "parent_id": "parent-1",
        "version": "same-provider-version",
        "payload": {"title": "실제 제목", "status": "needsAction", **fields},
    }


def _acquisition(resource: dict[str, object]) -> AcquisitionResultV1:
    return cast(
        AcquisitionResultV1,
        {
            "source_summaries": [
                {
                    "source": "TASKS" if resource["resource_type"] == "task" else "CALENDAR",
                    "connector_id": "google_workspace",
                    "resources": [resource],
                }
            ],
            "resource_handles": [resource["resource_handle"]],
            "availability_results": [],
        },
    )


def test_snapshot__allowlist_null_empty_omission_and_marker__preserved() -> None:
    resource = _resource(
        due=None,
        notes="사용자 메모\n\n\u200bgwa-recovery-fingerprint:internal",
        credential="must-not-copy",
        body="unrelated-body",
        title="",
    )
    before = deepcopy(resource)
    projected = project_task_calendar_source_snapshots(
        _acquisition(resource), max_snapshot_chars=DEFAULT_CONTEXT_BUDGET.max_segment_chars
    )
    assert len(projected) == 1
    observation = projected[0]
    assert observation["snapshot"]["notes"] == "사용자 메모"
    assert observation["snapshot"]["title"] == ""
    assert observation["snapshot"]["due"] is None
    assert "credential" not in observation["snapshot"] and "body" not in observation["snapshot"]
    assert resource == before
    fields = task_calendar_snapshot_fields(
        observation["snapshot"],
        resource_handle=observation["resource_handle"],
        source_version_ref=observation["source_version_ref"],
    )
    assert fields == {"title": "", "status": "needsAction", "due": None, "notes": "사용자 메모"}
    absent = task_calendar_source_snapshot(_resource(), max_snapshot_chars=4000)
    assert absent is not None and "due" not in absent["snapshot"]


@pytest.mark.parametrize(
    "fields", [{"notes": "x" * 4001}, {"status": []}, {"due": {"date": "today"}}]
)
def test_snapshot__invalid_or_over_budget__does_not_store_partial_fields(
    fields: dict[str, object],
) -> None:
    assert task_calendar_source_snapshot(_resource(**fields), max_snapshot_chars=4000) is None
    assert (
        "source_version_ref" not in normalize_segments(_acquisition(_resource(**fields)))[0].locator
    )


@pytest.mark.parametrize("change", ["parent_id", "resource_handle", "version", "status"])
def test_snapshot_hash__binds_exact_resource_and_observed_content(change: str) -> None:
    original = _resource()
    changed = deepcopy(original)
    if change == "status":
        cast(dict[str, object], changed["payload"])[change] = "completed"
    else:
        changed[change] = "task:other" if change == "resource_handle" else "other"
    first = task_calendar_source_snapshot(original, max_snapshot_chars=4000)
    second = task_calendar_source_snapshot(changed, max_snapshot_chars=4000)
    assert first is not None and second is not None
    assert first["source_version_ref"] != second["source_version_ref"]


@pytest.mark.parametrize("resource_type", ["task", "calendar_event"])
def test_normalize__additive_snapshot_binding__keeps_old_text_segment_ids_and_rehydrate(
    resource_type: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import google_work_agent.application.agents.retrieval.normalize_segments as normalize_module

    resource = (
        _resource(resource_type, notes="메모 " * 80)
        if resource_type == "task"
        else _resource(
            resource_type,
            start="2026-08-01T10:00:00Z",
            end="2026-08-01T11:00:00Z",
            description="설명 " * 80,
        )
    )
    acquisition = _acquisition(resource)
    budget = ContextBudget(chunk_target_tokens=90, chunk_max_tokens=120, chunk_overlap_tokens=20)
    with monkeypatch.context() as old:
        old.setattr(normalize_module, "task_calendar_source_snapshot", lambda *_a, **_kw: None)
        prior = normalize_segments(acquisition, context_budget=budget)
    assert len(prior) > 1
    current = rehydrate_normalized_segments(
        acquisition,
        [segment.segment_id for segment in prior],
        context_budget=budget,
    )
    assert [(item.segment_id, item.text) for item in current] == [
        (item.segment_id, item.text) for item in prior
    ]
    for old_segment, new_segment in zip(prior, current, strict=True):
        locator = dict(new_segment.locator)
        assert cast(str, locator.pop("source_version_ref")).startswith("sha256:")
        assert locator == old_segment.locator


def test_same_excerpt__different_provider_field_boundaries__different_snapshot_authority() -> None:
    ordinary = _resource(title="실제 제목", status="completed")
    spoof = _resource(title="실제 제목\nstatus: completed")
    cast(dict[str, Any], spoof["payload"]).pop("status")
    left, right = (
        normalize_segments(_acquisition(ordinary))[0],
        normalize_segments(_acquisition(spoof))[0],
    )
    assert left.text == right.text and left.segment_id == right.segment_id
    assert left.locator["source_version_ref"] != right.locator["source_version_ref"]
