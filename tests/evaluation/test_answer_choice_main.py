"""089 construction/registration controls; no Main, model or Provider execution."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from scripts import evaluate_answer_choice_main as runner


@pytest.fixture
def registered(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    model = {
        "model_id": "qwen3.5:9b",
        "model_digest": "a" * 64,
        "ollama_version_response": {"version": "0.34.0"},
        "ollama_version_sha256": runner.object_hash({"version": "0.34.0"}),
    }

    def build(digest: str, *, trial_id: str | None = None) -> dict[str, Any]:
        return {
            "trial_id": trial_id or "trial-089",
            "candidate": None,
            "model": {"id": "qwen3.5:9b", "digest": digest},
        }

    monkeypatch.setattr(runner.main_trial, "build_plan", build)
    monkeypatch.setattr(runner.main_trial, "validate_plan", lambda value: None)
    return runner.make_plan(model)


def test_make_plan__fixed_main_trial__keeps_upstream_and_counts_separate(
    registered: dict[str, Any],
) -> None:
    assert registered["production_plan"]["candidate"] is None
    assert registered["candidate"] == runner.CANDIDATE
    assert registered["overlay"]["upstream"] == "UNCHANGED_CURRENT_PRODUCT"
    assert registered["overlay"]["checkpoint_input_reuse"] is False
    assert registered["policy"]["case_id"] == "CASE-CORE-005"
    assert registered["policy"]["trials"] == 1
    assert registered["policy"]["actual_wire_cap"] == 20
    assert registered["policy"]["wall_seconds"] == 600
    assert registered["policy"]["historical_score_reuse"] is False
    assert runner.CRITERIA in registered["dependency_sha256"]
    runner.validate_plan(registered)


@pytest.mark.parametrize("field", ["candidate", "policy", "dependency_sha256", "model"])
def test_validate_plan__binding_tampered__rejects_before_dispatch(
    registered: dict[str, Any],
    field: str,
) -> None:
    changed = deepcopy(registered)
    changed[field] = {} if field != "candidate" else "different-candidate"
    with pytest.raises(ValueError):
        runner.validate_plan(changed)


def test_validate_plan__actual_model_missing__does_not_use_registered_model(
    registered: dict[str, Any],
) -> None:
    with pytest.raises(ValueError, match="actual installed"):
        runner.validate_plan(registered, model={})


def test_planning_scope__development_constructor__changes_only_planning_scope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: list[dict[str, Any]] = []
    original = runner.workflow.PlanningSubgraph
    events: list[dict[str, object]] = []
    store, runtime = object(), object()
    monkeypatch.setattr(
        runner, "AnswerChoicePlanningSubgraph", lambda **kwargs: captured.append(kwargs)
    )
    monkeypatch.setattr(runner, "decorate_answer_choice_provider", lambda leaf: ("choice", leaf))
    observer = SimpleNamespace(decorate=lambda leaf: ("observed", leaf))
    arguments: dict[str, Any] = {
        "prompt_execution_scope": runner.DEVELOPMENT_SMOKE,
        "evidence_store": store,
        "llm_runtime": runtime,
    }
    with runner.planning_candidate_scope(None, observer, events) as decorate:
        runner.workflow.PlanningSubgraph(**arguments)
        assert decorate("leaf") == ("observed", ("choice", "leaf"))
    assert runner.workflow.PlanningSubgraph is original
    assert arguments["prompt_execution_scope"] == runner.DEVELOPMENT_SMOKE
    assert captured[0] == {
        **arguments,
        "prompt_execution_scope": runner.EVALUATION,
        "observations": events,
    }
    assert captured[0]["evidence_store"] is store
    assert captured[0]["llm_runtime"] is runtime
    assert events[0]["operation"] == "EVALUATION_PLANNING_CONSTRUCTION"


def test_planning_scope__stacked_ru_candidate__rejects_without_construction() -> None:
    with (
        pytest.raises(ValueError, match="must not stack"),
        runner.planning_candidate_scope("goal-output-v4-connected", None, []),
    ):
        pytest.fail("stacked candidate was admitted")


def test_planning_scope__nondevelopment_constructor__rejects_and_restores_symbol() -> None:
    original = runner.workflow.PlanningSubgraph
    with (
        pytest.raises(ValueError, match="development composition"),
        runner.planning_candidate_scope(None, None, []),
    ):
        runner.workflow.PlanningSubgraph(prompt_execution_scope="PRODUCT_RELEASE")
    assert runner.workflow.PlanningSubgraph is original


@pytest.mark.parametrize("reached", [False, True])
def test_run_trial__actual_overlay_observations__never_promotes_nonreach_to_pass(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    registered: dict[str, Any],
    reached: bool,
) -> None:
    historical = deepcopy(registered)

    def fake_main(production: dict[str, Any], output: Path) -> None:
        assert production == historical["production_plan"]
        assert runner.main_trial.candidate_scope is runner.planning_candidate_scope
        runner.main_trial.write_json(
            output / "raw.json",
            {
                "state": "COMPLETED_OBSERVATION" if reached else "PRODUCT_STOP",
                "semantic_verdict": "UNREVIEWED",
                "candidate_events": [{"events": [{"operation": "CHOICE_DISPATCH"}]}]
                if reached
                else [],
            },
        )

    original_scope = runner.main_trial.candidate_scope
    monkeypatch.setattr(runner.main_trial, "run_trial", fake_main)
    runner.run_trial(registered, tmp_path)
    raw = json.loads((tmp_path / "raw.json").read_text(encoding="utf-8"))
    assert raw["evaluation_candidate"] == runner.CANDIDATE
    assert raw["candidate_choice_attempts"] == int(reached)
    assert raw["candidate_wire_dispatches"] == 0
    assert raw["candidate_not_reached_is_not_pass"] is True
    assert raw["semantic_verdict"] == "UNREVIEWED"
    assert registered == historical
    assert runner.main_trial.candidate_scope is original_scope
    overlay = json.loads((tmp_path / "active_evaluation_overlay.json").read_text(encoding="utf-8"))
    assert overlay["registered_plan_sha256"] == runner.object_hash(registered)


def test_execute_plan__existing_attempt__rejects_without_metadata_or_dispatch(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    registered: dict[str, Any],
) -> None:
    monkeypatch.setattr(runner, "RESULTS", tmp_path)
    output = tmp_path / "trial"
    output.mkdir()
    runner.write_json(output / "plan.json", registered, exclusive=True)
    runner.write_json(output / "attempt.json", {}, exclusive=True)
    monkeypatch.setattr(
        runner, "inspect_diagnostic_model", lambda mode: pytest.fail("metadata must not run")
    )
    with pytest.raises(FileExistsError):
        runner.execute_plan(output / "plan.json", runner.main_trial.file_hash(output / "plan.json"))


def test_execute_plan__registered_hash_mismatch__rejects_before_metadata(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    registered: dict[str, Any],
) -> None:
    monkeypatch.setattr(runner, "RESULTS", tmp_path)
    output = tmp_path / "trial"
    output.mkdir()
    runner.write_json(output / "plan.json", registered, exclusive=True)
    monkeypatch.setattr(
        runner, "inspect_diagnostic_model", lambda mode: pytest.fail("metadata must not run")
    )
    with pytest.raises(ValueError, match="file hash"):
        runner.execute_plan(output / "plan.json", "0" * 64)
