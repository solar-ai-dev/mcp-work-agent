"""Sealed model-artifact diagnostic tests; no real model, Graph or Provider."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest
from scripts import evaluate_source_fixed_model as runner


def _models() -> tuple[dict[str, Any], dict[str, Any]]:
    version = {"version": "0.34.0"}
    common = {
        "show_parameters": "presence_penalty 1.5\ntemperature 1\ntop_k 20\ntop_p 0.95",
        "ollama_version_response": version,
        "ollama_version_sha256": runner.object_hash(version),
    }
    return (
        {
            **common,
            "model_id": runner.BASELINE_MODEL_ID,
            "model_digest": runner.BASELINE_MODEL_DIGEST,
        },
        {**common, "model_id": runner.MODEL_ID, "model_digest": runner.MODEL_DIGEST},
    )


@pytest.fixture
def frozen(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> dict[str, Any]:
    baseline, model = _models()
    historical = {
        "head_sha": "current-head",
        "baseline_sha": "historical-head",
        "model": baseline,
        "source_hashes": {"historical-file": "current-hash"},
        "policy": {"max_calls": 3, "repair": 0, "retry": 0, "concurrency": 1},
        "cases": [
            {
                "case_id": case_id,
                "payload": {
                    "model": runner.BASELINE_MODEL_ID,
                    "system": "original system",
                    "prompt": json.dumps({"source_candidates": [{"read_tool_ids": ["read"]}]}),
                    "format": {"type": "object"},
                    "options": {"temperature": 0.05, "seed": 20260923, "num_ctx": 16384},
                    "think": False,
                    "stream": False,
                },
                # A reused v45 preparation must not leak its catalog change.
                "candidate_payload": {"prompt": "wrong catalog ablation"},
                "baseline": {"new_call": False, "input_tokens": 11, "output_tokens": 2},
            }
            for case_id in runner.shared.CASE_IDS
        ],
    }
    monkeypatch.setattr(runner.shared, "make_plan", lambda value: deepcopy(historical))
    monkeypatch.setattr(runner.existing, "file_hash", lambda path: f"hash:{path}")
    monkeypatch.setattr(runner, "render_binding", lambda value: {"sha256": "fixed-render"})
    monkeypatch.setattr(runner, "RESULTS", tmp_path / "results")
    monkeypatch.setattr(runner.shared, "RESULTS", runner.RESULTS)
    return {"historical": historical, "baseline_model": baseline, "model": model}


def test_plan_changes_only_model_and_preserves_original_read_catalog(
    frozen: dict[str, Any],
) -> None:
    before = deepcopy(frozen)
    plan = runner.make_plan(frozen["baseline_model"], frozen["model"])
    assert frozen == before
    assert plan["model"] == frozen["model"]
    assert plan["baseline_model"] == frozen["baseline_model"]
    assert plan["baseline_sha"] == "historical-head"
    assert plan["head_sha"] == "current-head"
    assert plan["policy"]["max_calls"] == 3
    assert len(plan["cases"]) == 3
    for case, old in zip(plan["cases"], frozen["historical"]["cases"], strict=True):
        expected = deepcopy(old["payload"])
        expected["model"] = runner.MODEL_ID
        assert case["candidate_payload"] == expected
        assert case["candidate_wire_sha256"] == runner.object_hash(expected)
        assert case["baseline"] == old["baseline"]
        assert "read_tool_ids" in case["candidate_payload"]["prompt"]
    assert runner.CRITERIA in plan["source_hashes"]


@pytest.mark.parametrize("mutation", ["digest", "defaults", "baseline", "version"])
def test_unregistered_model_or_runtime_rejects_without_dispatch(
    frozen: dict[str, Any], mutation: str
) -> None:
    if mutation == "digest":
        frozen["model"]["model_digest"] = "different"
    elif mutation == "defaults":
        frozen["model"]["show_parameters"] = "different defaults"
    elif mutation == "baseline":
        frozen["baseline_model"]["model_id"] = runner.MODEL_ID
    else:
        frozen["model"]["ollama_version_response"] = {"version": "other"}
    with pytest.raises(ValueError):
        runner.make_plan(frozen["baseline_model"], frozen["model"])


def test_inspection_reads_actual_metadata_without_generation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, model = _models()
    tags = {"models": [{"name": runner.MODEL_ID, "digest": runner.MODEL_DIGEST}]}
    show = {"parameters": model["show_parameters"], "template": "actual template"}
    paths = []

    def get(**kwargs: Any) -> dict[str, Any]:
        paths.append(kwargs["path"])
        return tags if kwargs["path"] == "/api/tags" else {"version": "0.34.0"}

    def post(**kwargs: Any) -> dict[str, Any]:
        paths.append(kwargs["path"])
        assert kwargs["path"] == "/api/show"
        assert kwargs["payload"] == {"model": runner.MODEL_ID}
        return show

    monkeypatch.setattr(runner.existing.transport, "_get_json", get)
    monkeypatch.setattr(runner.existing.transport, "_post_json", post)
    observed = runner.inspect_candidate_model()
    assert paths == ["/api/tags", "/api/show", "/api/version"]
    assert observed["model_digest"] == runner.MODEL_DIGEST
    assert observed["show_response"] == show
    assert observed["tags_response_sha256"] == runner.object_hash(tags)
    assert observed["show_sha256"] == runner.object_hash(show)


def test_historical_render_binding_rejects_generated_or_wrong_role_response(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, model = _models()
    observation = {
        "model_digest": runner.MODEL_DIGEST,
        "ollama_version": "0.34.0",
        "new_generation_calls": 0,
        "request": {
            "model": runner.MODEL_ID,
            "system": "EVAL_ROLE_SYSTEM_066",
            "prompt": "EVAL_ROLE_USER_066",
            "think": False,
            "stream": False,
            "options": {"num_ctx": 16384},
            "_debug_render_only": True,
        },
        "response": {
            "model": runner.MODEL_ID,
            "created_at": "fixed historical timestamp",
            "response": "",
            "done": False,
            "_debug_info": {"rendered_template": runner.RENDER_TEMPLATE},
        },
    }
    path = tmp_path / "render.json"
    monkeypatch.setattr(runner, "RENDER_OBSERVATION", path)
    runner.write_json(path, observation)
    binding = runner.render_binding(model)
    assert binding["sha256"] == runner.existing.file_hash(path)
    for wrong_response in (
        {**observation["response"], "eval_count": 0},
        {**observation["response"], "response": "generated text"},
        {**observation["response"], "_debug_info": {"rendered_template": "wrong roles"}},
    ):
        runner.write_json(path, {**observation, "response": wrong_response})
        with pytest.raises(ValueError):
            runner.render_binding(model)


def _seal_execution(frozen: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    plan = runner.make_plan(frozen["baseline_model"], frozen["model"])
    monkeypatch.setattr(
        runner.existing, "inspect_diagnostic_model", lambda mode: frozen["baseline_model"]
    )
    monkeypatch.setattr(runner, "inspect_candidate_model", lambda: frozen["model"])
    return plan


def test_three_registered_firsts_record_usage_and_model_mismatch_without_retry(
    frozen: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    plan = _seal_execution(frozen, monkeypatch)
    output = runner.RESULTS / "trial"
    calls = []
    validations = []

    def post(**kwargs: Any) -> dict[str, Any]:
        raw = runner.shared.read_json(output / "raw.json")
        assert raw["calls"][-1]["state"] == "DISPATCH_STARTED"
        assert kwargs["payload"]["model"] == runner.MODEL_ID
        assert kwargs["timeout_seconds"] == 180
        calls.append(kwargs)
        return {
            "model": runner.BASELINE_MODEL_ID if len(calls) == 2 else runner.MODEL_ID,
            "response": "{}",
            "done": True,
            "done_reason": "stop",
            "prompt_eval_count": 7,
            "eval_count": 2,
            "total_duration": 3_000_000,
            "thinking": "NOT_STORED",
        }

    def validate(content: str, case: dict[str, Any]) -> dict[str, Any]:
        validations.append(case["case_id"])
        return {"structural_result": "TEST_VALIDATION_ONLY"}

    monkeypatch.setattr(runner.existing.transport, "_post_json", post)
    monkeypatch.setattr(runner.existing, "validate_response", validate)
    digest = runner.object_hash(plan)
    raw = runner.execute_plan(plan, output, plan_sha256=digest)
    assert raw["actual_http_calls"] == len(calls) == 3
    assert len(validations) == 2
    assert raw["calls"][1]["state"] == "ERROR"
    assert raw["calls"][1]["response_model_matches"] is False
    assert "validation" not in raw["calls"][1]
    assert all(c["done_reason"] == "stop" and c["output_tokens"] == 2 for c in raw["calls"])
    assert raw["metrics"]["candidate_new"]["input_tokens"] == 21
    assert len(raw["reused_results"]) == 3
    assert "NOT_STORED" not in json.dumps(raw)
    with pytest.raises(FileExistsError):
        runner.execute_plan(plan, runner.RESULTS / "duplicate", plan_sha256=digest)
    assert len(calls) == 3


@pytest.mark.parametrize("drift", ["hash", "payload", "model"])
def test_tampered_plan_or_current_model_stops_before_generation(
    frozen: dict[str, Any], monkeypatch: pytest.MonkeyPatch, drift: str
) -> None:
    plan = _seal_execution(frozen, monkeypatch)
    digest = runner.object_hash(plan)
    if drift == "hash":
        digest = "incorrect"
    elif drift == "payload":
        plan["cases"][0]["candidate_payload"]["options"]["temperature"] = 0
        digest = runner.object_hash(plan)
    else:
        monkeypatch.setattr(
            runner, "inspect_candidate_model", lambda: {**frozen["model"], "model_digest": "other"}
        )

    def forbidden(**kwargs: Any) -> Any:
        raise AssertionError("drift must not dispatch")

    monkeypatch.setattr(runner.existing.transport, "_post_json", forbidden)
    with pytest.raises(ValueError):
        runner.execute_plan(plan, runner.RESULTS / "trial", plan_sha256=digest)
    assert not (runner.RESULTS / "trial" / "raw.json").exists()
