"""Compiled Product handoff tests, not new model or end-to-end success trials."""

from copy import deepcopy
from typing import Any

import pytest
from scripts.verify_answer_fact_handoff import replay_case
from tests.support.task_calendar_evidence import bind_task_calendar_snapshots


def _fixture() -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    request = "선택한 작업의 상태와 메모를 알려줘."
    evidence: list[dict[str, object]] = [
        {
            "evidence_id": "e-task",
            "resource_handle": "task:one",
            "excerpt": "선택한 시험 작업의 상태와 메모",
        }
    ]
    snapshots = bind_task_calendar_snapshots(
        evidence,
        {
            "e-task": {
                "title": "시험 작업",
                "status": "needsAction",
                "notes": "장비 항목을 확인할 것.",
            }
        },
    )
    projection = {
        "user_request": request,
        "request_intent": {
            "requested_effect_hints": ["READ"],
            "requested_resource_hints": ["TASK"],
            "analysis_requirement": "NONE",
            "resource_responsibilities": {
                "source_reads": [
                    {
                        "resource_type": "TASK",
                        "target_scope": "SINGULAR",
                        "required_information": ["status", "notes"],
                        "work_unit_ids": ["work-1"],
                    }
                ],
                "outputs": [],
            },
        },
        "answer_outline": {"sections": [request], "evidence_refs": ["e-task"]},
        "evidence": evidence,
        "temporal_constraints": [],
    }
    selection = {
        "items": [{"evidence_ref": "e-task", "field": field} for field in ("status", "notes")]
    }
    return projection, selection, snapshots


def test_replay_case__same_run_snapshot__preserves_answer_through_terminal_owner() -> None:
    projection, selection, snapshots = _fixture()
    before = deepcopy((projection, selection, snapshots))
    result = replay_case(projection, selection, snapshots)
    assert result["component_verdict"] == "PASS", result
    assert result["model_calls"] == result["provider_calls"] == 0
    assert result["terminal_composer_calls"] == 0
    calls = result["semantic_adapter_calls"]
    assert [item["prompt_id"] for item in calls] == ["planning.compose_answer"]
    assert result["final_result"] == calls[0]["materialized_draft"]
    assert result["final_result"]["evidence_refs"] == ["e-task"]
    assert "미완료" in result["final_result"]["answer"]
    assert "장비 항목을 확인할 것" in result["final_result"]["answer"]
    terminal = result["terminal_intent"]
    assert terminal["kind"] == "COMPLETE_ANSWER_ONLY"
    assert terminal["terminal_message"]["content"] == result["final_result"]["answer"]
    assert result["materialized_answer"]["meta"]["artifact_id"] == "082-component-run:answer"
    observations = result["snapshot_resolutions"]
    assert len(observations) == 2  # Actual outline and compose runtime projections.
    assert all(item["resolution"] == "RESOLVED" for item in observations)
    assert all(item["run_id"] == "082-component-run" for item in observations)
    assert result["inputs_unchanged"] and (projection, selection, snapshots) == before
    assert result["semantic_verdict"] == "NOT_EVALUATED"


def test_replay_case__snapshot_in_other_run__actual_store_denies_resolution() -> None:
    projection, selection, snapshots = _fixture()
    result = replay_case(projection, selection, snapshots, stored_run_id="foreign-run")
    assert result["component_verdict"] == "FAIL"
    assert all(row["resolution"] == "DENIED" for row in result["snapshot_resolutions"])
    assert "final_result" not in result and "terminal_intent" not in result
    assert result["inputs_unchanged"]


@pytest.mark.parametrize("condition", ["missing", "stale_version", "hash_mismatch"])
def test_replay_case__unavailable_or_invalid_snapshot__never_uses_unbound_values(
    condition: str,
) -> None:
    projection, selection, snapshots = _fixture()
    if condition == "missing":
        snapshots.clear()
    elif condition == "stale_version":
        projection["evidence"][0]["locator"]["source_version_ref"] = "sha256:stale"
    else:
        snapshots["e-task"]["unexpected"] = "tampered"
    result = replay_case(projection, selection, snapshots)
    assert result["component_verdict"] == "FAIL"
    assert "terminal_intent" not in result
    assert result["inputs_unchanged"]


def test_replay_case__conflicting_versions_for_same_task__rejects_rendering() -> None:
    projection, selection, snapshots = _fixture()
    peer = {**deepcopy(projection["evidence"][0]), "evidence_id": "e-peer"}
    projection["evidence"].append(peer)
    projection["answer_outline"]["evidence_refs"].append("e-peer")
    snapshots.update(
        bind_task_calendar_snapshots(
            [peer],
            {
                "e-peer": {
                    "title": "시험 작업",
                    "status": "completed",
                    "notes": "다른 버전",
                }
            },
        )
    )
    result = replay_case(projection, selection, snapshots)
    assert result["component_verdict"] == "FAIL"
    assert all(row["resolution"] == "RESOLVED" for row in result["snapshot_resolutions"])
    assert "final_result" not in result
    assert result["inputs_unchanged"]


@pytest.mark.parametrize(
    "selection",
    [
        {"items": [{"evidence_ref": "unapproved", "field": "status"}]},
        {"items": [{"evidence_ref": "e-task", "field": "unknown"}]},
        {"items": [{"evidence_ref": "e-task", "field": "status", "value": "completed"}]},
        {"items": [], "answer": "모두 완료했습니다."},
    ],
)
def test_replay_case__unapproved_or_freely_generated_selection__rejects(
    selection: dict[str, Any],
) -> None:
    projection, _, snapshots = _fixture()
    result = replay_case(projection, selection, snapshots)
    assert result["component_verdict"] == "FAIL"
    assert "final_result" not in result
    assert len(result["semantic_adapter_calls"]) == 1
    assert result["model_calls"] == result["provider_calls"] == 0


def test_replay_case__empty_selection__does_not_claim_empty_search_result() -> None:
    projection, _, snapshots = _fixture()
    result = replay_case(projection, {"items": []}, snapshots)
    assert result["component_verdict"] == "FAIL"
    assert "no empty-result inference" in result["error"]
    assert "final_result" not in result


def test_replay_case__one_requested_field_omitted__does_not_equate_structure_with_semantics() -> (
    None
):
    projection, _, snapshots = _fixture()
    selection = {"items": [{"evidence_ref": "e-task", "field": "status"}]}
    result = replay_case(projection, selection, snapshots)
    assert result["component_verdict"] == "PASS", result
    assert result["semantic_verdict"] == "NOT_EVALUATED"
    assert result["final_result"]["answer"] == "상태: 미완료"
    assert "메모" not in result["terminal_intent"]["terminal_message"]["content"]


def test_replay_case__outline_reprojects_saved_input__reports_difference_without_forcing_hash() -> (
    None
):
    projection, selection, snapshots = _fixture()
    projection["answer_outline"]["sections"] = ["별도 저장된 개요"]
    result = replay_case(projection, selection, snapshots)
    assert result["component_verdict"] == "FAIL"
    assert "compiled compose input differs: answer_outline" in result["error"]
    assert "materialized_draft" not in result["semantic_adapter_calls"][0]
    assert result["inputs_unchanged"]
