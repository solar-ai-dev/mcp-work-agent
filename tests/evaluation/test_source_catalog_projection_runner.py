"""Bounded diagnostic recording/claim tests; no actual model or Provider."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from scripts import evaluate_source_catalog_projection as runner


@pytest.fixture
def sealed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    plan = {
        "head_sha": "test-head",
        "model": {"model_id": "test-model"},
        "cases": [
            {
                "case_id": case_id,
                "candidate_payload": {"model": "test-model", "prompt": case_id},
                "baseline": {"input_tokens": 10, "output_tokens": 2, "latency_ms": 3},
            }
            for case_id in runner.CASE_IDS
        ],
    }
    monkeypatch.setattr(runner, "RESULTS", tmp_path / "results")
    monkeypatch.setattr(runner, "make_plan", lambda model: plan)
    monkeypatch.setattr(runner.existing, "inspect_diagnostic_model", lambda mode: plan["model"])
    monkeypatch.setattr(
        runner.existing,
        "validate_response",
        lambda content, case: {"structural_result": "FAKE_VALIDATION"},
    )
    return plan


def test_three_firsts_recorded_before_dispatch_and_cannot_rerun(
    sealed: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output = runner.RESULTS / "trial"
    calls = []

    def post(**kwargs: Any) -> dict[str, Any]:
        raw = runner.read_json(output / "raw.json")
        assert raw["calls"][-1]["state"] == "DISPATCH_STARTED"
        assert raw["calls"][-1]["payload"] == kwargs["payload"]
        assert kwargs["timeout_seconds"] == 180
        calls.append(kwargs)
        return {
            "response": "{}",
            "prompt_eval_count": 7,
            "eval_count": 1,
            "total_duration": 2_000_000,
            "thinking": "MUST_NOT_PERSIST",
        }

    monkeypatch.setattr(runner.existing.transport, "_post_json", post)
    digest = runner.object_hash(sealed)
    raw = runner.execute_plan(sealed, output, plan_sha256=digest)
    assert raw["completed"] and raw["actual_http_calls"] == len(calls) == 3
    assert raw["metrics"]["candidate_new"]["input_tokens"] == 21
    assert raw["metrics"]["baseline_reused"]["input_tokens"] == 30
    assert raw["semantic_verdict"] == "UNREVIEWED"
    assert "MUST_NOT_PERSIST" not in json.dumps(raw)
    original = (output / "raw.json").read_bytes()
    with pytest.raises(FileExistsError):
        runner.execute_plan(sealed, runner.RESULTS / "duplicate", plan_sha256=digest)
    assert len(calls) == 3 and (output / "raw.json").read_bytes() == original


@pytest.mark.parametrize("failure", [TimeoutError, KeyboardInterrupt])
def test_error_or_interruption_remains_original_trial(
    sealed: dict[str, Any],
    failure: type[BaseException],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output = runner.RESULTS / failure.__name__
    calls = []

    def fail(**kwargs: Any) -> Any:
        calls.append(kwargs)
        raise failure("synthetic test")

    monkeypatch.setattr(runner.existing.transport, "_post_json", fail)
    digest = runner.object_hash(sealed)
    if failure is KeyboardInterrupt:
        with pytest.raises(KeyboardInterrupt):
            runner.execute_plan(sealed, output, plan_sha256=digest)
    else:
        runner.execute_plan(sealed, output, plan_sha256=digest)
    raw = runner.read_json(output / "raw.json")
    assert len(calls) == (1 if failure is KeyboardInterrupt else 3)
    assert raw["completed"] == (failure is TimeoutError)
    assert all("wall_latency_ms" in c for c in raw["calls"])
    with pytest.raises(FileExistsError):
        runner.execute_plan(sealed, runner.RESULTS / "second", plan_sha256=digest)


@pytest.mark.parametrize("drift", ["sealed", "reconstructed"])
def test_drift_rejects_before_generation(
    sealed: dict[str, Any],
    drift: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    digest = runner.object_hash(sealed)
    if drift == "sealed":
        digest = "incorrect"
    else:
        monkeypatch.setattr(runner, "make_plan", lambda model: {**sealed, "head_sha": "changed"})

    def forbidden(**kwargs: Any) -> Any:
        raise AssertionError("drift must not dispatch")

    monkeypatch.setattr(runner.existing.transport, "_post_json", forbidden)
    with pytest.raises(ValueError):
        runner.execute_plan(sealed, runner.RESULTS / "trial", plan_sha256=digest)
