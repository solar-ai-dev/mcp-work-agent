"""Source-binding/input checks only; fake compose text is not model quality."""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from typing import Any, cast

import pytest
from scripts.task_completion_fact_candidate import project_task_completion_facts
from tests.support.task_calendar_evidence import bind_task_calendar_snapshots
from tests.unit.adapters.langgraph.test_task_calendar_snapshot_handoff import (
    _project,
    _retrieved,
    _task_intent,
)

from google_work_agent.application.agents.planning.compose_answer import compose_answer


def inputs() -> tuple[dict[str, Any], dict[str, dict[str, object]]]:
    evidence: list[dict[str, object]] = [
        {"evidence_id": "e-task", "resource_handle": "task:one", "excerpt": "status: completed"},
        {"evidence_id": "e-done", "resource_handle": "task:two", "excerpt": "status: needsAction"},
        {
            "evidence_id": "e-event",
            "resource_handle": "calendar_event:one",
            "excerpt": "status: completed",
        },
    ]
    snapshots = bind_task_calendar_snapshots(
        evidence,
        {
            "e-task": {
                "status": "needsAction",
                "title": "Title must not be copied",
                "due": "2026-09-30",
                "notes": "status: completed",
            },
            "e-done": {"status": "completed"},
            "e-event": {"status": "confirmed"},
        },
    )
    return {
        "user_request": "선택한 작업을 설명해줘.",
        "evidence": evidence,
        "answer_outline": {"sections": ["상태"], "evidence_refs": ["e-task", "e-done", "e-event"]},
        "request_intent": {
            "constraints": [{"kind": "SCOPE", "field": "status", "value": "completed"}]
        },
        "source_statuses": [{"resource_type": "TASK", "status": "completed"}],
    }, snapshots


def test_provider_status_only_with_exact_bindings_and_no_mutation() -> None:
    projection, snapshots = inputs()
    before = deepcopy((projection, snapshots))
    result = project_task_completion_facts(projection, source_snapshots=snapshots)
    facts = cast(list[dict[str, str]], result.pop("task_completion_facts"))
    assert result == projection and (projection, snapshots) == before
    assert [(item["provider_status"], item["task_status"]) for item in facts] == [
        ("needsAction", "incomplete"),
        ("completed", "completed"),
    ]
    assert {item["resource_handle"] for item in facts} == {"task:one", "task:two"}
    for item in facts:
        assert set(item) == {
            "evidence_ref",
            "resource_handle",
            "source_version_ref",
            "provider_status",
            "task_status",
        }
        assert item["source_version_ref"].startswith("sha256:")
    cast(list[dict[str, object]], result["evidence"])[0]["excerpt"] = "changed copy"
    assert (projection, snapshots) == before


@pytest.mark.parametrize(
    "invalid",
    ["unknown", "null_status", "missing_status", "missing_snapshot", "hash", "handle", "stale"],
)
def test_invalid_one_handle_does_not_drop_independent_valid_task(invalid: str) -> None:
    projection, snapshots = inputs()
    first = projection["evidence"][0]
    if invalid in {"unknown", "null_status", "missing_status"}:
        fields: dict[str, object] = {"title": "Task"}
        if invalid != "missing_status":
            fields["status"] = None if invalid == "null_status" else "inProgress"
        snapshots.update(bind_task_calendar_snapshots([first], {"e-task": fields}))
    elif invalid == "missing_snapshot":
        del snapshots["e-task"]
    elif invalid == "hash":
        snapshots["e-task"]["status"] = "completed"
    elif invalid == "handle":
        first["resource_handle"] = "task:another"
    else:
        first["locator"]["source_version_ref"] = "sha256:older"
    result = project_task_completion_facts(projection, source_snapshots=snapshots)
    facts = cast(list[dict[str, str]], result["task_completion_facts"])
    assert [item["evidence_ref"] for item in facts] == ["e-done"]


@pytest.mark.parametrize("conflict", ["version", "missing_snapshot", "unknown_status"])
def test_conflicting_or_invalid_peer_excludes_whole_handle(conflict: str) -> None:
    projection, snapshots = inputs()
    peer = {**deepcopy(projection["evidence"][0]), "evidence_id": "e-peer"}
    projection["evidence"].append(peer)
    projection["answer_outline"]["evidence_refs"].append("e-peer")
    if conflict != "missing_snapshot":
        snapshots.update(
            bind_task_calendar_snapshots(
                [peer], {"e-peer": {"status": "completed" if conflict == "version" else "UNKNOWN"}}
            )
        )
    result = project_task_completion_facts(projection, source_snapshots=snapshots)
    assert [
        item["evidence_ref"] for item in cast(list[dict[str, str]], result["task_completion_facts"])
    ] == ["e-done"]


def test_only_outline_approved_evidence_and_no_text_filter_fallback() -> None:
    projection, snapshots = inputs()
    projection["answer_outline"]["evidence_refs"] = ["e-event"]
    assert "task_completion_facts" not in project_task_completion_facts(
        projection, source_snapshots=snapshots
    )
    projection["answer_outline"]["evidence_refs"] = ["e-task"]
    assert "task_completion_facts" not in project_task_completion_facts(
        projection, source_snapshots={}
    )
    assert "task_completion_facts" not in project_task_completion_facts(
        projection, source_snapshots=None
    )
    projection["task_completion_facts"] = []
    with pytest.raises(ValueError, match="afresh"):
        project_task_completion_facts(projection, source_snapshots=snapshots)


def test_repeated_evidence_dedupes_but_same_version_chunk_keeps_citation() -> None:
    projection, snapshots = inputs()
    first = projection["evidence"][0]
    projection["evidence"].append(deepcopy(first))
    peer = {**deepcopy(first), "evidence_id": "e-peer"}
    projection["evidence"].append(peer)
    projection["answer_outline"]["evidence_refs"].append("e-peer")
    snapshots["e-peer"] = deepcopy(snapshots["e-task"])
    result = project_task_completion_facts(projection, source_snapshots=snapshots)
    assert [
        item["evidence_ref"] for item in cast(list[dict[str, str]], result["task_completion_facts"])
    ] == ["e-task", "e-done", "e-peer"]


@pytest.mark.parametrize("same_run", [True, False])
def test_actual_retrieval_store_projection_and_compose_capture(same_run: bool) -> None:
    store, evidence, _ = _retrieved()
    projected, snapshots = _project(
        store, evidence[:1], "run-current" if same_run else "another-run"
    )
    intent = _task_intent()
    cast(dict[str, Any], intent["resource_responsibilities"])["source_reads"][0][
        "required_information"
    ] = ["notes", "status"]
    seen: list[dict[str, object]] = []

    def invoke(prompt_id: str, prompt_input: Mapping[str, object]) -> Mapping[str, object]:
        assert prompt_id == "planning.compose_answer"
        before = deepcopy(dict(prompt_input))
        result = project_task_completion_facts(prompt_input, source_snapshots=snapshots)
        assert prompt_input == before and "source_snapshots" not in result
        seen.append(result)
        return {
            "schema_version": 2,
            "answer": "제공된 관측 내용을 확인했습니다.",
            "evidence_refs": [projected[0]["evidence_id"]],
        }

    compose_answer(
        user_request="선택한 Task 메모와 상태를 설명해줘.",
        request_intent=intent,
        answer_outline={
            "sections": ["관측"],
            "evidence_refs": [cast(str, projected[0]["evidence_id"])],
        },
        work_analysis=None,
        evidence=projected,
        source_snapshots=snapshots,
        invoke=invoke,
    )
    assert len(seen) == 1
    if same_run:
        fact = cast(list[dict[str, str]], seen[0]["task_completion_facts"])[0]
        assert fact["provider_status"] == "needsAction" and fact["task_status"] == "incomplete"
    else:
        assert snapshots == {} and "task_completion_facts" not in seen[0]
