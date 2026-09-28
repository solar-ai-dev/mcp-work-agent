"""092 full-input temperature-only fixed FIRST gates; all transports are fake."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest
from scripts import evaluate_answer_temperature as runner
from scripts.evaluate_task_completion_fact import synthetic_completed
from scripts.ru_observation import object_hash


@pytest.fixture(scope="module")
def source() -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    projection, snapshots = synthetic_completed()
    wire = runner.history.registered.expected_first(projection, snapshots)["payload"]
    return projection, snapshots, wire


@pytest.fixture
def plan(source: tuple[dict[str, Any], dict[str, Any], dict[str, Any]]) -> dict[str, Any]:
    projection, snapshots, wire = source
    payload = runner.build_payload(wire)
    cases = [
        {
            "case_id": f"{group}-TEMPERATURE_ZERO-T1",
            "group": group,
            "trial": 1,
            "arm": runner.ARM,
            "original_payload": deepcopy(wire),
            "historical_transport_sha256": runner.ordered.transport_hash(wire),
            "candidate_payload": deepcopy(payload),
            "prompt_input": deepcopy(projection),
            "snapshots": deepcopy(snapshots),
            "candidate_input_sha256": object_hash(projection),
            "candidate_transport_sha256": runner.ordered.transport_hash(payload),
            "candidate_property_orders": runner.ordered.property_orders(payload),
        }
        for group in runner.history.GROUPS
    ]
    return {
        "cases": cases,
        "model": {"model_id": "qwen3.5:9b"},
        "historical_references": [],
        "scope": "SYNTHETIC_TEST_ONLY",
    }


def test_build_payload__default_temperature__changes_only_option_and_preserves_original(
    source: tuple[dict[str, Any], dict[str, Any], dict[str, Any]],
) -> None:
    wire = deepcopy(source[2])
    before = deepcopy(wire)
    result = runner.build_payload(wire)
    assert wire == before
    assert result["options"]["temperature"] == 0.0
    result["options"].pop("temperature")
    assert runner.ordered.transport_hash(result) == runner.ordered.transport_hash(wire)
    assert json.loads(result["prompt"])["input"]["request_intent"]["constraints"]
    assert runner.history._PRODUCT_CONTEXT_INSTRUCTION in result["system"]


@pytest.mark.parametrize("value", [None, 0.0, 1.0])
def test_build_payload__already_explicit_temperature__rejects_new_baseline(value: object) -> None:
    with pytest.raises(ValueError, match="default-temperature"):
        runner.build_payload({"options": {"temperature": value}})


@pytest.mark.parametrize("change", ["projection", "presence", "order", "fourth_call"])
def test_verify_wire_seals__other_axis_or_extra_trial__rejects(
    plan: dict[str, Any],
    change: str,
) -> None:
    runner.verify_wire_seals(plan)
    case = plan["cases"][0]
    if change == "projection":
        case["prompt_input"]["request_intent"]["constraints"] = []
    elif change == "presence":
        case["candidate_payload"]["options"]["presence_penalty"] = 0
        case["candidate_transport_sha256"] = runner.ordered.transport_hash(
            case["candidate_payload"]
        )
    elif change == "order":
        props = case["candidate_payload"]["format"]["oneOf"][0]["properties"]
        props["mode"] = props.pop("mode")
    else:
        plan["cases"].append(deepcopy(case))
    with pytest.raises(ValueError):
        runner.verify_wire_seals(plan)


@pytest.mark.parametrize("failure", [None, "timeout", "wrong_model"])
def test_execute_plan__fake_transport__limits_firsts_and_preserves_failed_trials(
    plan: dict[str, Any],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure: str | None,
) -> None:
    sent = []
    monkeypatch.setattr(runner.recorder, "RESULTS", tmp_path)

    def post(**kwargs: Any) -> dict[str, Any]:
        assert kwargs["path"] == "/api/generate" and kwargs["timeout_seconds"] == 180
        sent.append(runner.ordered.transport_hash(kwargs["payload"]))
        if failure == "timeout":
            raise TimeoutError("synthetic timeout")
        return {
            "model": "wrong" if failure else "qwen3.5:9b",
            "done": True,
            "done_reason": "stop",
            "response": '{"mode":"FACT_REFERENCES","items":[]}',
            "prompt_eval_count": 5,
            "eval_count": 3,
            "total_duration": 1_000_000,
        }

    monkeypatch.setattr(runner.existing.transport, "_post_json", post)
    kwargs: dict[str, Any] = {
        "plan_sha256": object_hash(plan),
        "reconstruct_plan": lambda: deepcopy(plan),
    }
    raw = runner.execute_plan(plan, tmp_path / "trial", **kwargs)
    count = 1 if failure else 3
    assert raw["actual_http_calls"] == len(sent) == count
    assert sent == [c["candidate_transport_sha256"] for c in plan["cases"][:count]]
    assert raw["completed"] is (failure is None)
    assert raw["registered_router_calls"] == raw["graph_calls"] == raw["provider_calls"] == 0
    assert raw["semantic_verdict"] == "NOT_REVIEWED"
    if failure is None:
        assert all(r["answer_admission"]["structural_result"] == "NO_DRAFT" for r in raw["calls"])
    else:
        assert raw["calls"][0]["state"] == "ERROR" and len(raw["not_dispatched"]) == 2
    with pytest.raises(FileExistsError):
        runner.execute_plan(plan, tmp_path / "again", **kwargs)
    assert len(sent) == count
