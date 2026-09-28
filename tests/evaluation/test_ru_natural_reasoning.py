"""072 fake-transport conformance, not model/business-quality evaluation."""

from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest
from scripts import evaluate_ru_natural_reasoning as runner


@pytest.fixture
def history(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    model = {"model_id": "qwen3.5:9b", "model_digest": "fixed", "version": "test-only"}
    cases, calls = [], []
    for case_id in runner.control.CASE_IDS:
        projection = {
            "user_request": f"{case_id} 원문 의미를 그대로 보존해줘.",
            "selected_resource_refs": [{"resource_id": "selected", "resource_type": "task"}]
            if case_id.endswith("005")
            else [],
            "run_reference_time": {
                "reference_time": "2026-08-07T09:00:00+09:00",
                "timezone": "Asia/Seoul",
            },
        }
        payload = {
            "model": model["model_id"],
            "system": runner.control.SYSTEM,
            "prompt": runner.json.dumps(projection, ensure_ascii=False),
            "think": False,
            "stream": False,
            "options": {"temperature": 0.05, "seed": 20260923, "num_ctx": 16384},
        }
        cases.append(
            {
                "case_id": case_id,
                "candidate_payload": payload,
                "candidate_input_sha256": runner.object_hash(projection),
                "candidate_wire_sha256": runner.object_hash(payload),
                "source_call_sha256": "source-" + case_id,
                "case_binding": {"case_sha256": "case-" + case_id},
            }
        )
        calls.append(
            {
                "case_id": case_id,
                "payload": payload,
                "wire_sha256": runner.object_hash(payload),
                "input_sha256": runner.object_hash(projection),
                "state": "RETURNED",
                "wire_request_count": 1,
                "validation": "NONEMPTY_TEXT",
                "done": True,
                "model": model["model_id"],
                "content": "과거 자연어 응답",
                "input_tokens": 12,
                "output_tokens": 4,
                "latency_ms": 6,
            }
        )
    original: dict[str, Any] = {
        "head_sha": "071-head",
        "cases": cases,
        "model": model,
        "source_hashes": {
            "src/owner.py": "same-product",
            "scripts/evaluate_ru_semantic_capability.py": "071-helper",
        },
        "dataset_sha256": "dataset",
        "fixture_sha256": "fixture",
    }
    current = deepcopy(original)
    current["head_sha"] = "072-head"
    current["source_hashes"]["scripts/evaluate_ru_semantic_capability.py"] = "extracted-helper"
    raw = {
        "binding": original,
        "plan_sha256": runner.object_hash(original),
        "completed": True,
        "binding_unchanged": True,
        "diagnostic_status": "RECORDED",
        "actual_http_calls": 5,
        "calls": calls,
    }

    def digest(path: Path) -> str:
        if path == runner.BASELINE:
            return runner.BASELINE_HASH
        if path == runner.BASELINE_PLAN:
            return runner.BASELINE_PLAN_HASH
        return "new-bound-file"

    monkeypatch.setattr(runner, "ROOT", tmp_path)
    monkeypatch.setattr(runner, "RESULTS", tmp_path / "results")
    monkeypatch.setattr(runner.control, "RESULTS", tmp_path / "results")
    monkeypatch.setattr(runner.existing, "file_hash", digest)
    monkeypatch.setattr(
        runner.control.shared,
        "read_json",
        lambda path: deepcopy(raw if path == runner.BASELINE else original),
    )
    monkeypatch.setattr(runner.control, "make_plan", lambda actual: deepcopy(current))
    monkeypatch.setattr(runner.existing, "inspect_diagnostic_model", lambda mode: deepcopy(model))
    return {"original": original, "current": current, "raw": raw, "model": model}


def test_plan__thinking_enabled__changes_only_think_and_preserves_hashes(
    history: dict[str, Any],
) -> None:
    before = deepcopy(history)
    plan = runner.make_plan(history["model"])
    assert tuple(c["case_id"] for c in plan["cases"]) == runner.CASE_IDS
    assert plan["policy"]["new_calls"] == plan["policy"]["historical_reference_calls"] == 3
    assert plan["historical_file_differences"] == {
        "scripts/evaluate_ru_semantic_capability.py": {
            "historical": "071-helper",
            "current": "extracted-helper",
        }
    }
    for case in plan["cases"]:
        payload = case["candidate_payload"]
        original = case["historical_nl_result"]["payload"]
        assert payload == {**original, "think": True}
        assert payload["options"] == original["options"]
        assert "format" not in payload
        assert case["historical_nl_result"]["new_call"] is False
        assert set(runner.json.loads(payload["prompt"])) == set(runner.control.INPUT_FIELDS)
    assert history == before


@pytest.mark.parametrize(
    "field", ["hash", "model", "product", "wire", "input", "duplicate", "incomplete"]
)
def test_prepare__authority_drift__fails_before_generation(
    history: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
    field: str,
) -> None:
    monkeypatch.setattr(
        runner.existing.transport, "_post_json", lambda **_: pytest.fail("generation forbidden")
    )
    if field == "hash":
        monkeypatch.setattr(runner.existing, "file_hash", lambda _: "wrong")
    elif field == "model":
        history["model"] = {"model_id": "wrong"}
    elif field == "product":
        history["current"]["source_hashes"]["src/owner.py"] = "changed"
    elif field == "wire":
        history["raw"]["calls"][2]["wire_sha256"] = "wrong"
    elif field == "input":
        history["current"]["cases"][2]["candidate_payload"]["prompt"] = "different"
    elif field == "duplicate":
        history["raw"]["calls"].append(deepcopy(history["raw"]["calls"][2]))
    else:
        history["raw"]["completed"] = False
    with pytest.raises(ValueError):
        runner.make_plan(history["model"])


def _response() -> dict[str, Any]:
    return {
        "model": "qwen3.5:9b",
        "response": "요청한 자료를 확인하고 최종 결과를 준비하는 업무입니다.",
        "done": True,
        "done_reason": "stop",
        "prompt_eval_count": 8,
        "eval_count": 20,
        "total_duration": 30_000_000,
        "load_duration": 1_000_000,
        "thinking": "HIDDEN_THOUGHT_NEVER_STORE",
    }


def test_execute__three_fixed_firsts__reuses_recorder_without_hidden_reasoning(
    history: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan, dispatched = runner.make_plan(history["model"]), []
    output = runner.RESULTS / "trial"

    def post(**kwargs: Any) -> dict[str, Any]:
        row = runner.json.loads((output / "raw.json").read_text(encoding="utf-8"))["calls"][-1]
        assert row["state"] == "DISPATCH_STARTED" and row["payload"] == kwargs["payload"]
        assert kwargs["timeout_seconds"] == 180 and kwargs["payload"]["think"] is True
        dispatched.append(kwargs)
        return _response()

    monkeypatch.setattr(runner.existing.transport, "_post_json", post)
    raw = runner.execute_plan(plan, output, plan_sha256=runner.object_hash(plan))
    assert raw["diagnostic_status"] == "RECORDED" and raw["completed"]
    assert raw["actual_http_calls"] == len(dispatched) == 3
    assert [r["case_id"] for r in raw["calls"]] == list(runner.CASE_IDS)
    assert raw["metrics"]["control_new"]["output_tokens"] == 60
    assert raw["metrics"]["natural_language_historical_reference"]["input_tokens"] == 36
    assert all(
        r["thinking_present"] and r["semantic_verdict"] == "NOT_REVIEWED" for r in raw["calls"]
    )
    assert "HIDDEN_THOUGHT_NEVER_STORE" not in runner.json.dumps(raw)
    before = (output / "raw.json").read_bytes()
    with pytest.raises(FileExistsError):
        runner.execute_plan(plan, runner.RESULTS / "rerun", plan_sha256=runner.object_hash(plan))
    assert (output / "raw.json").read_bytes() == before and len(dispatched) == 3


@pytest.mark.parametrize("failure", ["timeout", "wrong_model", "incomplete", "empty"])
def test_circuit__uncertain_completion__stops_remaining_cases(
    history: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
    failure: str,
) -> None:
    plan = runner.make_plan(history["model"])

    def post(**kwargs: Any) -> dict[str, Any]:
        if failure == "timeout":
            raise TimeoutError("synthetic timeout")
        changes = (
            {"response": ""}
            if failure == "empty"
            else ({"done": False} if failure == "incomplete" else {"model": "other"})
        )
        return {**_response(), **changes}

    monkeypatch.setattr(runner.existing.transport, "_post_json", post)
    raw = runner.execute_plan(plan, runner.RESULTS / failure, plan_sha256=runner.object_hash(plan))
    assert raw["diagnostic_status"] == "FAILED"
    assert raw["actual_http_calls"] == (3 if failure == "empty" else 1)
    assert raw["completed"] is (failure == "empty")
    assert [r["case_id"] for r in raw["not_dispatched"]] == (
        [] if failure == "empty" else list(runner.CASE_IDS[1:])
    )


def test_execute__end_binding_drift__retains_responses_but_fails_gate(
    history: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan = runner.make_plan(history["model"])

    def post(**kwargs: Any) -> dict[str, Any]:
        history["current"]["head_sha"] = "changed"
        return _response()

    monkeypatch.setattr(runner.existing.transport, "_post_json", post)
    raw = runner.execute_plan(plan, runner.RESULTS / "drift", plan_sha256=runner.object_hash(plan))
    assert raw["completed"] and raw["actual_http_calls"] == 3
    assert raw["binding_unchanged"] is False and raw["diagnostic_status"] == "FAILED"
