"""Only fake HTTP: exact Product replay, inactive fact input and three FIRST bounds."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any, cast

import pytest
from scripts import evaluate_task_completion_fact as runner


def historical_fixture() -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    projection, snapshots = runner.synthetic_completed()
    wire = runner.handoff._wire_projection(projection)
    evidence = projection["evidence"][0]
    snapshot = snapshots[evidence["evidence_id"]]
    call = {
        "prompt_id": runner.PROMPT_ID,
        "prompt_ref": wire["prompt_ref"],
        "input": projection,
        "input_sha256": wire["input_sha256"],
        "output_schema": wire["schema"],
        "state": "RETURNED",
        "wire_request_count": 1,
        "wire_path": wire["wire_path"],
        "wire_sha256": wire["wire_sha256"],
        "wire_options": wire["wire_payload"]["options"],
        "wire_think": False,
        "model": runner.handoff.MODEL_ID,
        "temperature": None,
        "seed": runner.handoff.SEED,
        "runtime_policy": {
            "sampling_temperature": None,
            "sampling_seed": runner.handoff.SEED,
            "local_timeout_seconds": 180,
        },
        "content": json.dumps(
            {
                "schema_version": 2,
                "answer": "기존 원문 답변",
                "evidence_refs": [evidence["evidence_id"]],
            },
            ensure_ascii=False,
        ),
    }
    raw = {
        "run_id": "synthetic-run",
        "snapshot": {"run": {"run_id": "synthetic-run"}},
        "persisted_run": {"id": "synthetic-run"},
        "plan": {"head_sha": "historical-synthetic-not-product-run"},
        "read_results": [
            {
                "tool_id": "tasks_get_task",
                "arguments": {"task_id": "42", "task_list_id": snapshot["parent_id"]},
                "result": {
                    "output": {
                        "item": {
                            "resource_id": "42",
                            "resource_type": "task",
                            "parent_id": snapshot["parent_id"],
                            "version": snapshot["provider_version"],
                            "payload": {key: snapshot[key] for key in ("title", "status", "notes")},
                        }
                    }
                },
            }
        ],
    }
    legacy = deepcopy(call)
    legacy["input"]["evidence"][0].pop("locator")
    return call, raw, legacy


@pytest.fixture
def sealed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    model = {
        "model_id": runner.handoff.MODEL_ID,
        "model_digest": "test-digest",
        "ollama_version_response": {"version": "0.34.0"},
        "ollama_version_sha256": runner.object_hash({"version": "0.34.0"}),
    }
    history = historical_fixture()
    monkeypatch.setattr(runner, "RESULTS", tmp_path)
    monkeypatch.setattr(runner, "head", lambda: "test-head")
    monkeypatch.setattr(runner, "_bound_files", lambda: {"test-source": "sealed"})
    monkeypatch.setattr(runner, "load_history", lambda _: deepcopy(history))
    monkeypatch.setattr(runner.existing, "inspect_diagnostic_model", lambda _: deepcopy(model))
    return runner.make_plan(model)


def test_plan_has_three_fixed_firsts_and_no_semantic_pass(sealed: dict[str, Any]) -> None:
    assert [cell["cell_id"] for cell in sealed["cells"]] == list(runner.CELL_IDS)
    assert sealed["policy"]["max_new_calls"] == 3
    assert sealed["policy"]["repair"] == sealed["policy"]["retry"] == 0
    assert sealed["baseline"]["new_call"] is False
    assert sealed["legacy_negative"]["unchanged"] is True
    assert sealed["legacy_negative"]["new_calls"] == 0
    assert sealed["semantic_verdict"] == "UNREVIEWED"
    assert sealed["business_success"] == "NOT_EVALUATED"
    baseline, candidate = sealed["cells"][1:]
    assert "task_completion_facts" not in baseline["input"]
    facts = candidate["input"]["task_completion_facts"]
    assert facts[0]["task_status"] == "completed"
    assert {
        key: value for key, value in candidate["input"].items() if key != "task_completion_facts"
    } == baseline["input"]
    for key in ("format", "options", "think", "model"):
        assert baseline["wire_payload"][key] == candidate["wire_payload"][key]
    assert "source_snapshots" not in candidate["input"]
    assert "notes" not in facts[0] and "title" not in facts[0]
    assert candidate["schema"] == baseline["schema"]
    product = runner.PromptRegistry()
    registry = runner._EvaluationRegistry(baseline["input"], sealed["synthetic_snapshots"])
    assert registry.source_text(runner.EVALUATION_SLOT) == product.source_text(runner.PROMPT_ID)
    assert candidate["prompt_ref"]["content_hash"] == baseline["prompt_ref"]["content_hash"]


@pytest.mark.parametrize(
    "field", ["wire_sha256", "input_sha256", "prompt_ref", "output_schema", "temperature"]
)
def test_original_reconstruction_rejects_drift(field: str) -> None:
    call, _, _ = historical_fixture()
    original = deepcopy(call)
    assert runner.reconstruct_original(call)["wire_sha256"] == call["wire_sha256"]
    assert call == original
    call[field] = "tampered"
    with pytest.raises(ValueError, match="drift"):
        runner.reconstruct_original(call)


@pytest.mark.parametrize("field", ["run", "version", "status", "parent"])
def test_snapshot_record_requires_exact_run_identity_and_version(field: str) -> None:
    call, raw, _ = historical_fixture()
    item = raw["read_results"][0]["result"]["output"]["item"]
    if field == "run":
        raw["persisted_run"]["id"] = "foreign-run"
    elif field == "status":
        item["payload"]["status"] = "needsAction"
    elif field == "parent":
        item["parent_id"] = "other-list"
    else:
        item["version"] = "another-version"
    with pytest.raises(ValueError):
        runner.snapshots_from_record(raw, call["input"])


def test_isolated_contract_validates_product_base_and_rejects_fact_injection(
    sealed: dict[str, Any],
) -> None:
    base = sealed["cells"][1]["input"]
    registry = runner._EvaluationRegistry(base, sealed["synthetic_snapshots"])
    expected = deepcopy(registry.expected_input)
    registry.validate_projection(runner.EVALUATION_SLOT, expected)
    with pytest.raises(ValueError):
        registry.product_registry.input_contract.validate_projection(runner.PROMPT_ID, expected)
    cast(list[dict[str, str]], expected["task_completion_facts"])[0]["task_status"] = "incomplete"
    with pytest.raises(ValueError, match="exact snapshot"):
        registry.validate_projection(runner.EVALUATION_SLOT, expected)
    expected = deepcopy(registry.expected_input)
    expected["evaluation_gold"] = "completed"
    with pytest.raises(ValueError):
        registry.validate_projection(runner.EVALUATION_SLOT, expected)


@pytest.mark.parametrize("response_kind", ["valid", "invalid_schema", "prose_repair", "timeout"])
def test_three_attempts_persist_first_without_repair_or_repeat(
    sealed: dict[str, Any], monkeypatch: pytest.MonkeyPatch, response_kind: str
) -> None:
    output = runner.RESULTS / "trial"
    seen: list[dict[str, Any]] = []

    def post(**kwargs: Any) -> dict[str, Any]:
        row = runner.read_json(output / "raw.json")["calls"][-1]
        assert row["state"] == "DISPATCH_STARTED"
        assert row["wire_payload"] == kwargs["payload"]
        assert kwargs["timeout_seconds"] == 180
        seen.append(kwargs)
        if response_kind == "timeout":
            raise TimeoutError("fake timeout")
        projection = json.loads(kwargs["payload"]["prompt"])["input"]
        value = {
            "schema_version": 2,
            "answer": "확인한 자료입니다.",
            "evidence_refs": projection["answer_outline"]["evidence_refs"],
        }
        if response_kind == "invalid_schema":
            value = {}
        elif response_kind == "prose_repair":
            value["answer"] = '{"serialized": "not prose"}'
        return {
            "model": runner.handoff.MODEL_ID,
            "response": json.dumps(value),
            "done": True,
            "done_reason": "stop",
            "prompt_eval_count": 9,
            "eval_count": 3,
            "total_duration": 1_000_000,
            "thinking": "DO_NOT_PERSIST",
        }

    monkeypatch.setattr(runner.handoff.transport, "_post_json", post)
    digest = runner.object_hash(sealed)
    raw = runner.execute_plan(sealed, output, plan_sha256=digest)
    assert raw["actual_http_calls"] == len(seen) == 3
    assert raw["source_binding_unchanged"] is raw["model_binding_unchanged"] is True
    assert "DO_NOT_PERSIST" not in json.dumps(raw)
    for row in raw["calls"]:
        if response_kind == "timeout":
            assert row["state"] == "ERROR"
        else:
            assert (
                row["validation"]["structural_result"]
                == {
                    "valid": "VALID",
                    "invalid_schema": "INVALID_SCHEMA",
                    "prose_repair": "OWNER_VALIDATION_FAILED",
                }[response_kind]
            )
            assert row["validation"]["semantic_verdict"] == "UNREVIEWED"
    with pytest.raises(FileExistsError):
        runner.execute_plan(sealed, runner.RESULTS / "repeat", plan_sha256=digest)
    assert len(seen) == 3


def test_interruption_keeps_claim_and_the_failed_first(
    sealed: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    def interrupt(**_kwargs: Any) -> Any:
        raise KeyboardInterrupt

    monkeypatch.setattr(runner.handoff.transport, "_post_json", interrupt)
    output = runner.RESULTS / "interrupted"
    digest = runner.object_hash(sealed)
    with pytest.raises(KeyboardInterrupt):
        runner.execute_plan(sealed, output, plan_sha256=digest)
    raw = runner.read_json(output / "raw.json")
    assert raw["completed"] is False and len(raw["calls"]) == 1
    assert "wall_latency_ms" in raw["calls"][0]
    with pytest.raises(FileExistsError):
        runner.execute_plan(sealed, runner.RESULTS / "second", plan_sha256=digest)


@pytest.mark.parametrize("drift", ["plan", "model", "source"])
def test_drift_fails_before_generation(
    sealed: dict[str, Any], monkeypatch: pytest.MonkeyPatch, drift: str
) -> None:
    digest = runner.object_hash(sealed)
    if drift == "plan":
        sealed["cells"][0]["input"]["user_request"] = "changed"
    elif drift == "model":
        monkeypatch.setattr(
            runner.existing,
            "inspect_diagnostic_model",
            lambda _: {**sealed["model"], "model_digest": "changed"},
        )
    else:
        monkeypatch.setattr(runner, "_bound_files", lambda: {"test-source": "changed"})
    monkeypatch.setattr(
        runner.handoff.transport, "_post_json", lambda **_: pytest.fail("no HTTP allowed")
    )
    with pytest.raises(ValueError):
        runner.execute_plan(sealed, runner.RESULTS / "drift", plan_sha256=digest)
    assert not (runner.RESULTS / "drift" / "raw.json").exists()
