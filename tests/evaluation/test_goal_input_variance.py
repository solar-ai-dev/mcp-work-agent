"""No model calls: sealed two-factor Goal recording, not semantic correctness."""

from __future__ import annotations

import json
from copy import deepcopy
from dataclasses import asdict
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest
from scripts import evaluate_goal_input_variance as runner


def goal_value() -> dict[str, Any]:
    schema = cast(dict[str, Any], runner.identify_goal_output_schema(["work-1"]).json_schema)
    slots = schema["properties"]["constraints"]["properties"]
    return {
        "goal": "현재 입력을 설명한다.",
        "completion_conditions": [],
        "constraints": {
            key: {"value": "NOT_COLLECTION", "work_unit_ids": ["work-1"]}
            if key == "coverage_requirement"
            else []
            for key in slots
        },
        "analysis_requirement": "NONE",
    }


@pytest.fixture
def sealed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    results = tmp_path / "results"
    monkeypatch.setattr(runner, "RESULTS", results)
    monkeypatch.setattr(runner, "head", lambda: "test-head")
    dataset, snapshot = tmp_path / "dataset.json", tmp_path / "snapshot.json"
    runner.write_json(dataset, {"fixture": "test"})
    runner.write_json(snapshot, {"fixture": "test"})
    monkeypatch.setattr(runner.existing, "DEFAULT_DATASET_PATH", dataset)
    monkeypatch.setattr(runner.existing, "DEFAULT_PROVIDER_FIXTURE_PATH", snapshot)
    request = "선택한 작업의 상태를 알려줘."
    case = {"canonical_user_prompt": request, "split": "CORE"}
    monkeypatch.setattr(
        runner.existing, "load_cases", lambda: {runner.CASE_ID: SimpleNamespace(raw=case)}
    )
    version = {"version": "0.34.0"}
    model = {
        "model_id": "qwen3.5:9b",
        "model_digest": "test-digest",
        "ollama_version_response": version,
        "ollama_version_sha256": runner.object_hash(version),
    }
    monkeypatch.setattr(runner.existing, "inspect_diagnostic_model", lambda mode: model)
    origins = []
    for index, label in enumerate(("old", "new"), start=1):
        projection = {
            "user_request": request,
            "selected_resource_refs": [
                {
                    "resource_ref_id": f"00000000-0000-4000-8000-{index:012d}",
                    "connector_id": "google_workspace",
                    "resource_type": "task",
                    "resource_id": "test-task",
                    "parent_resource_id": "test-list",
                }
            ],
            "requested_work": {
                "work_units": [
                    {
                        "unit_id": "work-1",
                        "request_provenance": [
                            {
                                "source": "USER_REQUEST",
                                "start_offset": 0,
                                "end_offset": len(request),
                                "source_text": request,
                            }
                        ],
                    }
                ],
                "work_relations": [],
            },
            "run_reference_time": {
                "reference_time": f"2026-09-29T0{index}:00:00+09:00",
                "timezone": "Asia/Seoul",
            },
        }
        call = {
            "call_index": 2,
            "prompt_id": runner.PROMPT_ID,
            "prompt_ref": asdict(runner.PromptRegistry().lookup_for_evaluation(runner.PROMPT_ID)),
            "input": projection,
            "input_sha256": runner.object_hash(projection),
            "output_schema": runner.identify_goal_output_schema(["work-1"]).json_schema,
            "runtime_policy": {
                "local_timeout_seconds": 180,
                "sampling_temperature": 0.1,
                "sampling_seed": 20260923,
            },
            "temperature": 0.1,
            "seed": 20260923,
            "model": model["model_id"],
            "state": "RETURNED",
            "wire_request_count": 1,
            "wire_path": "/api/generate",
            "wire_options": {"num_ctx": 16384, "temperature": 0.1, "seed": 20260923},
            "wire_think": False,
            "content": json.dumps(goal_value(), ensure_ascii=False),
            "input_tokens": 10,
            "output_tokens": 2,
            "latency_ms": 3,
        }
        payload = runner.reconstruct_payload(call, projection=projection)
        call["wire_sha256"] = runner.object_hash(payload)
        calls_path = results / label / "calls.json"
        runner.write_json(calls_path, {"calls": [call]})
        runner.write_json(
            results / label / "raw.json",
            {
                "plan": {
                    "case_id": runner.CASE_ID,
                    "case_sha256": runner.object_hash(case),
                    "dataset_sha256": runner.existing.file_hash(dataset),
                    "snapshot_sha256": runner.existing.file_hash(snapshot),
                    "model": {"id": model["model_id"], "digest": model["model_digest"]},
                    "head_sha": f"historical-{label}",
                }
            },
        )
        origins.append((label, label, runner.existing.file_hash(calls_path)))
    monkeypatch.setattr(runner, "ORIGINS", tuple(origins))
    return runner.make_plan(model)


def test_plan_reconstructs_real_product_wire_and_changes_only_two_factors(
    sealed: dict[str, Any],
) -> None:
    old, new = [row["source_call"] for row in sealed["reused_results"]]
    first, second = sealed["cells"]
    assert first["input"]["selected_resource_refs"] == old["input"]["selected_resource_refs"]
    assert first["input"]["run_reference_time"] == new["input"]["run_reference_time"]
    assert second["input"]["selected_resource_refs"] == new["input"]["selected_resource_refs"]
    assert second["input"]["run_reference_time"] == old["input"]["run_reference_time"]
    assert sealed["policy"]["max_new_calls"] == 2
    for cell in sealed["cells"]:
        wire = json.loads(cell["payload"]["prompt"])
        assert wire["input"] == cell["input"]
        assert wire["output_schema"] == cell["payload"]["format"] == old["output_schema"]
        assert cell["payload"]["options"] == old["wire_options"]
        assert set(wire) == {"input", "output_schema", "prompt_ref"}
    assert all(
        row["validation"]["semantic_verdict"] == "UNREVIEWED" for row in sealed["reused_results"]
    )


@pytest.mark.parametrize("changed", ["user_request", "parent", "timezone", "work"])
def test_other_input_differences_are_not_absorbed(sealed: dict[str, Any], changed: str) -> None:
    old, new = [deepcopy(row["source_call"]["input"]) for row in sealed["reused_results"]]
    if changed == "parent":
        new["selected_resource_refs"][0]["parent_resource_id"] = "other-list"
    elif changed == "timezone":
        new["run_reference_time"]["timezone"] = "UTC"
    elif changed == "work":
        new["requested_work"]["work_units"][0]["unit_id"] = "other-work"
    else:
        new["user_request"] += " changed"
    with pytest.raises(ValueError, match="beyond UUID"):
        runner.crossed_inputs(old, new)


def test_strict_admission_is_not_semantic_success(sealed: dict[str, Any]) -> None:
    projection = sealed["cells"][0]["input"]
    valid = runner.validate_response(json.dumps(goal_value()), projection)
    assert valid["structural_result"] == "VALID"
    assert valid["semantic_verdict"] == "UNREVIEWED"
    assert valid["non_owner_semantics"] == "NOT_EVALUATED"
    fenced = runner.validate_response("```json\n{}\n```", projection)
    assert fenced["structural_result"] == "INVALID_JSON"
    wrong = goal_value()
    wrong["constraints"]["coverage_requirement"]["work_unit_ids"] = ["unknown"]
    assert (
        runner.validate_response(json.dumps(wrong), projection)["structural_result"]
        == "INVALID_SCHEMA"
    )


def test_two_calls_persist_before_wire_and_cannot_rerun(
    sealed: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    output = runner.RESULTS / "trial"
    seen = []

    def post(**kwargs: Any) -> dict[str, Any]:
        before = runner.read_json(output / "raw.json")["calls"][-1]
        assert before["state"] == "DISPATCH_STARTED" and before["payload"] == kwargs["payload"]
        assert kwargs["timeout_seconds"] == 180 and kwargs["path"] == "/api/generate"
        seen.append(kwargs)
        return {
            "model": "qwen3.5:9b",
            "response": json.dumps(goal_value()),
            "prompt_eval_count": 5,
            "eval_count": 1,
            "total_duration": 2_000_000,
            "thinking": "NEVER_SAVE_THINKING",
        }

    monkeypatch.setattr(runner.existing.transport, "_post_json", post)
    digest = runner.object_hash(sealed)
    raw = runner.execute_plan(sealed, output, plan_sha256=digest)
    assert len(seen) == raw["actual_http_calls"] == 2
    assert raw["metrics"]["new_crossed"]["input_tokens"] == 10
    assert raw["metrics"]["reused_diagonal"]["input_tokens"] == 20
    assert "NEVER_SAVE_THINKING" not in json.dumps(raw)
    with pytest.raises(FileExistsError):
        runner.execute_plan(sealed, runner.RESULTS / "second", plan_sha256=digest)
    with pytest.raises(ValueError, match="overwritten"):
        runner.execute_plan(sealed, output, plan_sha256=digest)
    assert len(seen) == 2


@pytest.mark.parametrize("failure", [TimeoutError, KeyboardInterrupt])
def test_failed_or_interrupted_dispatch_is_preserved_not_retried(
    sealed: dict[str, Any], monkeypatch: pytest.MonkeyPatch, failure: type[BaseException]
) -> None:
    output = runner.RESULTS / failure.__name__
    seen = []

    def post(**kwargs: Any) -> Any:
        seen.append(kwargs)
        raise failure("test failure")

    monkeypatch.setattr(runner.existing.transport, "_post_json", post)
    digest = runner.object_hash(sealed)
    if failure is KeyboardInterrupt:
        with pytest.raises(KeyboardInterrupt):
            runner.execute_plan(sealed, output, plan_sha256=digest)
    else:
        runner.execute_plan(sealed, output, plan_sha256=digest)
    raw = runner.read_json(output / "raw.json")
    assert len(seen) == (1 if failure is KeyboardInterrupt else 2)
    assert all("wall_latency_ms" in row for row in raw["calls"])
    assert raw["completed"] == (failure is TimeoutError)
    with pytest.raises(FileExistsError):
        runner.execute_plan(sealed, runner.RESULTS / "repeat", plan_sha256=digest)


@pytest.mark.parametrize("drift", ["plan", "source", "runtime"])
def test_drift_stops_before_generation(
    sealed: dict[str, Any], monkeypatch: pytest.MonkeyPatch, drift: str
) -> None:
    digest = runner.object_hash(sealed)
    if drift == "plan":
        sealed["cells"][0]["input"]["user_request"] = "tampered"
    elif drift == "source":
        path = Path(sealed["reused_results"][0]["source_calls_path"])
        runner.write_json(path, {"calls": []})
    else:
        monkeypatch.setattr(
            runner.existing,
            "inspect_diagnostic_model",
            lambda mode: {**sealed["model"], "model_digest": "changed"},
        )
    monkeypatch.setattr(
        runner.existing.transport, "_post_json", lambda **kwargs: pytest.fail("must not dispatch")
    )
    with pytest.raises(ValueError):
        runner.execute_plan(sealed, runner.RESULTS / "trial", plan_sha256=digest)
