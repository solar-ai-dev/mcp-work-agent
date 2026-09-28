"""071 recording/authority controls only; fake responses are not meaning scores."""

from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from scripts import evaluate_ru_semantic_capability as runner


@pytest.fixture
def history(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    version = {"version": "0.34.0"}
    model = {
        "model_id": "qwen3.5:9b",
        "model_digest": "frozen-test-digest",
        "ollama_version_response": version,
        "ollama_version_sha256": runner.object_hash(version),
    }
    cases, rows, canonical, payloads = [], [], {}, {}
    for index, case_id in enumerate(runner.CASE_IDS):
        request = f"원문 {case_id}: 선택한 정보를 알려줘. 생성하지 마."
        refs = (
            [{"resource_type": "task", "resource_id": "selected", "parent_resource_id": "parent"}]
            if index == 0
            else []
        )
        original_input = {
            "user_request": request,
            "selected_resource_refs": refs,
            "run_reference_time": {
                "reference_time": "2026-08-07T09:00:00+09:00",
                "timezone": "Asia/Seoul",
            },
            "requested_work": {"marker": "WORK_MUST_NOT_REACH_CONTROL"},
            "goal_candidate": {"goal": "GOAL_MUST_NOT_REACH_CONTROL"},
            "source_candidates": ["CATALOG_MUST_NOT_REACH_CONTROL"],
            "evaluation_gold": "GOLD_MUST_NOT_REACH_CONTROL",
        }
        call = {
            "input": original_input,
            "prompt_ref": {"prompt_id": "source-owner"},
            "output_schema": {"type": "object"},
        }
        payload = {
            "model": model["model_id"],
            "think": False,
            "stream": False,
            "options": {"temperature": 0.05, "seed": 20260923, "num_ctx": 16384},
            "system": "ORIGINAL_ROLE_WITH_SCHEMA",
            "prompt": "ORIGINAL_PRODUCT_BODY",
            "format": {"type": "object"},
        }
        payloads[request] = payload
        canonical_raw = {
            "split": "CORE",
            "canonical_user_prompt": request,
            "evaluation_gold": "GOLD_MUST_NOT_REACH_CONTROL",
        }
        canonical[case_id] = SimpleNamespace(raw=canonical_raw)
        case = {
            "case_id": case_id,
            "source_call": call,
            "owner": "source",
            "case_binding": {"case_sha256": runner.object_hash(canonical_raw)},
        }
        cases.append(case)
        rows.append(
            {
                "case_id": case_id,
                "arm": "schema_constrained",
                "state": "RETURNED",
                "wire_request_count": 1,
                "wire_sha256": runner.object_hash(payload),
                "input_sha256": runner.object_hash(original_input),
                "wire_options": payload["options"],
                "wire_think": False,
                "prompt_ref": call["prompt_ref"],
                "model": model["model_id"],
                "content": "{}",
                "validation": {"structural_result": "VALIDATED"},
                "input_tokens": 10,
                "output_tokens": 2,
                "latency_ms": 3,
            }
        )
    binding = {
        "head_sha": "historical-head",
        "model": model,
        "cases": cases,
        "dataset_sha256": "dataset",
        "fixture_sha256": "fixture",
        "source_hashes": {},
    }
    raw = {"binding": binding, "completed": True, "results": rows}

    def digest(path: Path) -> str:
        if path == runner.BASELINE:
            return runner.BASELINE_HASH
        if path == runner.BASELINE_PLAN:
            return runner.BASELINE_PLAN_HASH
        if path == runner.existing.DEFAULT_DATASET_PATH:
            return "dataset"
        if path == runner.existing.DEFAULT_PROVIDER_FIXTURE_PATH:
            return "fixture"
        return "current-file-hash"

    def validate(content: Any, source: Any) -> dict[str, str]:
        assert content == "{}", (
            "Product validator must see only historical Source, never NL control"
        )
        return {"structural_result": "VALIDATED"}

    monkeypatch.setattr(runner, "ROOT", tmp_path)
    monkeypatch.setattr(runner, "RESULTS", tmp_path / "results")
    monkeypatch.setattr(runner, "head", lambda: "current-head")
    monkeypatch.setattr(
        runner.shared,
        "read_json",
        lambda path: deepcopy(raw if path == runner.BASELINE else binding),
    )
    monkeypatch.setattr(runner.existing, "file_hash", digest)
    monkeypatch.setattr(runner.existing, "load_cases", lambda: canonical)
    monkeypatch.setattr(
        runner.existing,
        "reconstruct_payload",
        lambda call: deepcopy(payloads[call["input"]["user_request"]]),
    )
    monkeypatch.setattr(runner.existing, "validate_response", validate)
    monkeypatch.setattr(runner.existing, "inspect_diagnostic_model", lambda mode: deepcopy(model))
    return {"raw": raw, "binding": binding, "model": model, "payloads": payloads}


def test_projection__frozen_source_input__preserves_runtime_without_product_or_gold(
    history: dict[str, Any],
) -> None:
    before = deepcopy(history)
    plan = runner.make_plan(history["model"])
    assert tuple(c["case_id"] for c in plan["cases"]) == runner.CASE_IDS
    assert plan["policy"]["new_calls"] == plan["policy"]["historical_reference_calls"] == 5
    for case in plan["cases"]:
        payload, source = case["candidate_payload"], case["source_call"]["input"]
        content = runner.json.loads(payload["prompt"])
        assert list(content) == list(runner.INPUT_FIELDS)
        assert content == {key: source[key] for key in runner.INPUT_FIELDS}
        assert payload["system"] == runner.SYSTEM and "format" not in payload
        assert {
            key: value for key, value in payload.items() if key not in {"system", "prompt"}
        } == {
            key: value
            for key, value in history["payloads"][source["user_request"]].items()
            if key not in {"system", "prompt", "format"}
        }
        assert all(
            marker not in runner.json.dumps(payload)
            for marker in ("MUST_NOT_REACH_CONTROL", "prompt_ref", "output_schema")
        )
        assert case["historical_source_result"]["new_call"] is False
    assert history == before


@pytest.mark.parametrize("change", ["raw_hash", "input", "runtime", "duplicate", "dataset"])
def test_prepare__authority_drift__rejects_without_generation(
    history: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
    change: str,
) -> None:
    monkeypatch.setattr(
        runner.existing.transport, "_post_json", lambda **_: pytest.fail("generation forbidden")
    )
    if change == "raw_hash":
        monkeypatch.setattr(runner.existing, "file_hash", lambda _: "changed")
    elif change == "input":
        history["binding"]["cases"][0]["source_call"]["input"]["selected_resource_refs"] = []
    elif change == "runtime":
        history["payloads"][next(iter(history["payloads"]))]["options"]["seed"] += 1
    elif change == "duplicate":
        history["raw"]["results"].append(deepcopy(history["raw"]["results"][0]))
    else:
        history["binding"]["dataset_sha256"] = "changed"
    with pytest.raises(ValueError):
        runner.make_plan(history["model"])


def _response() -> dict[str, Any]:
    return {
        "model": "qwen3.5:9b",
        "response": "필요한 자료를 확인하여 요청한 내용을 알려주는 업무입니다.",
        "done": True,
        "done_reason": "stop",
        "prompt_eval_count": 7,
        "eval_count": 3,
        "total_duration": 9_000_000,
        "load_duration": 2_000_000,
        "thinking": "SECRET_THINKING_MUST_NOT_PERSIST",
    }


def test_execute__five_fixed_firsts__records_sequentially_without_retry_or_hidden_thinking(
    history: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan, calls = runner.make_plan(history["model"]), []
    output = runner.RESULTS / "trial"

    def post(**kwargs: Any) -> dict[str, Any]:
        row = runner.json.loads((output / "raw.json").read_text(encoding="utf-8"))["calls"][-1]
        assert row["state"] == "DISPATCH_STARTED" and row["payload"] == kwargs["payload"]
        assert kwargs["endpoint"] == runner.existing.OLLAMA_FIXED_LOOPBACK_ENDPOINT
        assert kwargs["path"] == "/api/generate" and kwargs["timeout_seconds"] == 180
        calls.append(kwargs)
        return _response()

    monkeypatch.setattr(runner.existing.transport, "_post_json", post)
    raw = runner.execute_plan(plan, output, plan_sha256=runner.object_hash(plan))
    assert raw["completed"] and raw["binding_unchanged"] and raw["diagnostic_status"] == "RECORDED"
    assert raw["actual_http_calls"] == len(calls) == 5
    assert raw["metrics"]["control_new"]["input_tokens"] == 35
    assert raw["metrics"]["source_historical_reference"]["input_tokens"] == 50
    assert raw["provider_calls"] == raw["graph_calls"] == 0
    assert all(
        c["validation"] == "NONEMPTY_TEXT" and c["semantic_verdict"] == "NOT_REVIEWED"
        for c in raw["calls"]
    )
    assert "SECRET_THINKING" not in runner.json.dumps(raw)
    before = (output / "raw.json").read_bytes()
    with pytest.raises(FileExistsError):
        runner.execute_plan(
            plan, runner.RESULTS / "duplicate", plan_sha256=runner.object_hash(plan)
        )
    assert len(calls) == 5 and (output / "raw.json").read_bytes() == before


@pytest.mark.parametrize(
    "failure", ["timeout", "transport", "interrupted", "empty", "wrong_model", "incomplete"]
)
def test_execute__original_failures__retains_without_replacement(
    history: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
    failure: str,
) -> None:
    plan, calls = runner.make_plan(history["model"]), []
    output = runner.RESULTS / failure

    def post(**kwargs: Any) -> dict[str, Any]:
        calls.append(kwargs)
        if failure == "timeout":
            raise TimeoutError("synthetic timeout")
        if failure == "transport":
            raise ConnectionError("synthetic transport failure")
        if failure == "interrupted":
            raise KeyboardInterrupt("synthetic interruption")
        replacement = (
            {"response": " "}
            if failure == "empty"
            else ({"done": False} if failure == "incomplete" else {"model": "other-model"})
        )
        return {**_response(), **replacement}

    monkeypatch.setattr(runner.existing.transport, "_post_json", post)
    if failure == "interrupted":
        with pytest.raises(KeyboardInterrupt):
            runner.execute_plan(plan, output, plan_sha256=runner.object_hash(plan))
    else:
        runner.execute_plan(plan, output, plan_sha256=runner.object_hash(plan))
    raw = runner.json.loads((output / "raw.json").read_text(encoding="utf-8"))
    assert len(calls) == raw["actual_http_calls"] == (5 if failure == "empty" else 1)
    assert raw["completed"] is (failure == "empty")
    assert [row["case_id"] for row in raw["not_dispatched"]] == (
        [] if failure == "empty" else list(runner.CASE_IDS[1:])
    )
    assert all(
        row["state"] == "NOT_DISPATCHED" and row["wire_request_count"] == 0
        for row in raw["not_dispatched"]
    )
    assert raw["diagnostic_status"] == "FAILED"
    assert all("wall_latency_ms" in row for row in raw["calls"])
    with pytest.raises(FileExistsError):
        runner.execute_plan(plan, runner.RESULTS / "rerun", plan_sha256=runner.object_hash(plan))


def test_execute__seal_or_end_drift__rejects_dispatch_or_success(
    history: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan = runner.make_plan(history["model"])
    monkeypatch.setattr(
        runner.existing.transport, "_post_json", lambda **_: pytest.fail("bad seal dispatched")
    )
    with pytest.raises(ValueError, match="hash mismatch"):
        runner.execute_plan(plan, runner.RESULTS / "invalid", plan_sha256="wrong")

    def post(**kwargs: Any) -> dict[str, Any]:
        monkeypatch.setattr(runner, "head", lambda: "changed-during-trial")
        return _response()

    monkeypatch.setattr(runner.existing.transport, "_post_json", post)
    raw = runner.execute_plan(plan, runner.RESULTS / "drift", plan_sha256=runner.object_hash(plan))
    assert raw["completed"] and raw["binding_unchanged"] is False
    assert raw["diagnostic_status"] == "FAILED"


@pytest.mark.parametrize("stop_index", [None, 0, 4])
def test_execute__post_response_structural_hook__preserves_usage_and_stops_only_when_requested(
    history: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
    stop_index: int | None,
) -> None:
    plan = runner.make_plan(history["model"])
    calls, observations = [], []

    def post(**kwargs: Any) -> dict[str, Any]:
        calls.append(kwargs)
        return _response()

    def inspect(row: dict[str, Any], case: dict[str, Any]) -> str | None:
        assert row["state"] == "RETURNED"
        assert row["content"] == _response()["response"]
        assert row["model"] == plan["model"]["model_id"]
        assert row["done"] is True and row["done_reason"] == "stop"
        assert row["input_tokens"] == 7 and row["output_tokens"] == 3
        assert row["latency_ms"] == 9 and row["load_duration_ms"] == 2
        assert row["thinking_present"] is True and "thinking" not in row
        assert row["case_id"] == case["case_id"]
        observations.append(row["case_id"])
        return "FIXED_STRUCTURE_REJECTED" if len(observations) - 1 == stop_index else None

    monkeypatch.setattr(runner.existing.transport, "_post_json", post)
    raw = runner.execute_registered_plan(
        plan,
        runner.RESULTS / "hook-trial",
        plan_sha256=runner.object_hash(plan),
        reconstruct_plan=lambda: runner.make_plan(history["model"]),
        claim_directory=".hook-test-trials",
        reference_results=[],
        reference_metric="unused_reference",
        stop_after_response=inspect,
    )

    count = 5 if stop_index is None else stop_index + 1
    assert len(calls) == len(observations) == raw["actual_http_calls"] == count
    assert raw["metrics"]["control_new"]["input_tokens"] == 7 * count
    assert raw["metrics"]["control_new"]["output_tokens"] == 3 * count
    assert raw["completed"] is (stop_index is None)
    assert raw["diagnostic_status"] == ("RECORDED" if stop_index is None else "FAILED")
    assert [item["case_id"] for item in raw["not_dispatched"]] == list(runner.CASE_IDS[count:])
    assert "SECRET_THINKING" not in runner.json.dumps(raw)
    if stop_index is None:
        assert "circuit_break" not in raw
        assert all(row["state"] == "RETURNED" for row in raw["calls"])
    else:
        row = raw["calls"][-1]
        assert row["state"] == "ERROR" and row["content"] == _response()["response"]
        assert (
            row["structural_stop_reason"]
            == raw["circuit_break"]["reason"]
            == "FIXED_STRUCTURE_REJECTED"
        )
        assert row["semantic_verdict"] == "NOT_REVIEWED"
        assert all(
            item["reason"] == "PREVIOUS_RESPONSE_STRUCTURAL_STOP" for item in raw["not_dispatched"]
        )


def test_execute__post_response_hook_raises__retains_first_and_prevents_next_dispatch(
    history: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan, calls = runner.make_plan(history["model"]), []

    def post(**kwargs: Any) -> dict[str, Any]:
        calls.append(kwargs)
        return _response()

    def inspect(_row: dict[str, Any], _case: dict[str, Any]) -> str | None:
        raise RuntimeError("structural inspector failed")

    monkeypatch.setattr(runner.existing.transport, "_post_json", post)
    raw = runner.execute_registered_plan(
        plan,
        runner.RESULTS / "hook-error",
        plan_sha256=runner.object_hash(plan),
        reconstruct_plan=lambda: runner.make_plan(history["model"]),
        claim_directory=".hook-error-trials",
        reference_results=[],
        reference_metric="unused_reference",
        stop_after_response=inspect,
    )

    assert len(calls) == raw["actual_http_calls"] == 1
    assert raw["completed"] is False and raw["diagnostic_status"] == "FAILED"
    assert raw["calls"][0]["content"] == _response()["response"]
    assert raw["calls"][0]["error_type"] == "RuntimeError"
    assert raw["metrics"]["control_new"]["input_tokens"] == 7
    assert len(raw["not_dispatched"]) == 4
