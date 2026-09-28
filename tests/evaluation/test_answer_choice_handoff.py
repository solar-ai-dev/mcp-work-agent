"""Model-free 084 replay gates; no automatic answer-meaning PASS."""

from copy import deepcopy
from typing import Any

import pytest
from scripts import verify_answer_choice_handoff as gate
from tests.evaluation.test_answer_fact_handoff import _fixture


def _case(mode: str) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    projection, selection, snapshots = _fixture()
    if mode == "PROSE":
        selection = {
            "schema_version": 2,
            "answer": "확인할 항목: 장비 항목.",
            "evidence_refs": ["e-task"],
        }
    return projection, {"mode": mode, **selection}, snapshots


@pytest.mark.parametrize("mode", ["FACT_REFERENCES", "PROSE"])
def test_replay_case__both_saved_modes__preserves_compiled_and_terminal_draft(mode: str) -> None:
    projection, selection, snapshots = _case(mode)
    before = deepcopy((projection, selection, snapshots))
    original = gate.existing.materialize_fact_selection
    result = gate.replay_case(projection, selection, snapshots, component_run_id="086-test")
    assert result["component_verdict"] == "PASS", result
    assert result["semantic_verdict"] == "NOT_EVALUATED"
    assert result["model_calls"] == result["provider_calls"] == 0
    assert result["terminal_composer_calls"] == 0
    assert len(result["semantic_adapter_calls"]) == 1
    assert result["final_result"] == result["semantic_adapter_calls"][0]["materialized_draft"]
    assert (
        result["terminal_intent"]["terminal_message"]["content"]
        == (result["final_result"]["answer"])
    )
    assert result["materialized_answer"]["meta"]["artifact_id"] == "086-test:answer"
    assert all(row["run_id"] == "086-test" for row in result["snapshot_resolutions"])
    assert all(row["resolution"] == "RESOLVED" for row in result["snapshot_resolutions"])
    assert (projection, selection, snapshots) == before and result["inputs_unchanged"]
    assert gate.existing.materialize_fact_selection is original


@pytest.mark.parametrize("mode", ["FACT_REFERENCES", "PROSE"])
@pytest.mark.parametrize("condition", ["foreign_run", "missing", "stale", "tampered"])
def test_replay_case__invalid_snapshot_provenance__does_not_fabricate_read(
    mode: str,
    condition: str,
) -> None:
    projection, selection, snapshots = _case(mode)
    if condition == "missing":
        snapshots.clear()
    elif condition == "stale":
        projection["evidence"][0]["locator"]["source_version_ref"] = "sha256:stale"
    elif condition == "tampered":
        snapshots["e-task"]["notes"] = "forged notes"
    result = gate.replay_case(
        projection,
        selection,
        snapshots,
        stored_run_id="foreign-run" if condition == "foreign_run" else None,
    )
    assert result["component_verdict"] == "FAIL"
    assert "terminal_intent" not in result
    assert result["model_calls"] == result["provider_calls"] == 0
    assert result["inputs_unchanged"]


@pytest.mark.parametrize("mode", ["FACT_REFERENCES", "PROSE"])
def test_replay_case__unapproved_evidence_ref__does_not_rewrite_selection(mode: str) -> None:
    projection, selection, snapshots = _case(mode)
    if mode == "PROSE":
        selection["evidence_refs"] = ["foreign"]
    else:
        selection["items"][0]["evidence_ref"] = "foreign"
    result = gate.replay_case(projection, selection, snapshots)
    assert result["component_verdict"] == "FAIL" and "terminal_intent" not in result
    assert result["model_calls"] == result["provider_calls"] == 0


def test_replay_case__different_outline__reports_projection_divergence() -> None:
    projection, selection, snapshots = _case("PROSE")
    projection["answer_outline"]["sections"] = ["unrelated outline"]
    result = gate.replay_case(projection, selection, snapshots)
    assert result["component_verdict"] == "FAIL"
    assert "compiled compose input differs: answer_outline" in result["error"]
    assert "materialized_draft" not in result["semantic_adapter_calls"][0]
