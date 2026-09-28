"""084 serialization/admission gates using the existing 083 synthetic fixture only."""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest
from scripts import evaluate_answer_mode_first as runner
from scripts import evaluate_answer_rendering_choice as previous
from scripts.evaluate_effect_prohibition_sampler import write_json
from scripts.ru_observation import object_hash
from tests.evaluation.test_answer_rendering_choice_diagnostic import lookup as lookup
from tests.evaluation.test_answer_rendering_choice_diagnostic import sealed as sealed

from google_work_agent.ports.llm.output_schema_validation import validate_output_schema


@pytest.fixture
def wire(lookup: tuple[dict[str, Any], dict[str, Any]]) -> dict[str, Any]:
    projection, snapshots = lookup
    original = previous.history.handoff._wire_projection(projection)["wire_payload"]
    return previous.choice_wire(original, projection, snapshots)


@pytest.fixture
def plan(sealed: dict[str, Any]) -> dict[str, Any]:
    result = deepcopy(sealed)
    result["cases"] = [case for case in result["cases"] if case["arm"] == "CHOICE"]
    for case in result["cases"]:
        case["candidate_payload"] = runner.mode_first_wire(case["candidate_payload"])
        case["candidate_transport_sha256"] = runner.transport_hash(case["candidate_payload"])
        case["candidate_property_orders"] = runner.property_orders(case["candidate_payload"])
        case["arm"] = "MODE_FIRST"
    return result


def test_mode_first_wire__existing_union__changes_order_without_changing_values(
    wire: dict[str, Any],
) -> None:
    before = deepcopy(wire)
    result = runner.mode_first_wire(wire)
    assert wire == before == result
    assert result is not wire and result["format"] is not wire["format"]
    assert runner.transport_hash(result) != runner.transport_hash(wire)
    assert object_hash(result) == object_hash(wire)
    for old, new in zip(wire["format"]["oneOf"], result["format"]["oneOf"], strict=True):
        assert list(new["properties"])[0] == "mode"
        assert list(new["properties"])[1:] == [key for key in old["properties"] if key != "mode"]
        assert new["required"] == old["required"]
        assert new["properties"]["mode"] == old["properties"]["mode"]
    for key in wire:
        if key != "format":
            assert result[key] == wire[key]
    # The prompt's sorted schema remains byte-identical; only top-level format order changes.
    assert result["prompt"] == wire["prompt"]


@pytest.mark.parametrize("mode", ["FACT_REFERENCES", "PROSE"])
def test_mode_first_wire__both_original_branches__retains_admission(
    wire: dict[str, Any],
    mode: str,
) -> None:
    ref = json.loads(wire["prompt"])["input"]["answer_outline"]["evidence_refs"][0]
    value = (
        {"mode": mode, "items": [{"evidence_ref": ref, "field": "status"}]}
        if mode == "FACT_REFERENCES"
        else {"mode": mode, "schema_version": 2, "answer": "확인한 내용", "evidence_refs": [ref]}
    )
    assert not validate_output_schema(value, wire["format"])
    assert not validate_output_schema(value, runner.mode_first_wire(wire)["format"])


@pytest.mark.parametrize("kind", ["missing_format", "missing_mode", "missing_const"])
def test_mode_first_wire__invalid_contract__rejects(kind: str, wire: dict[str, Any]) -> None:
    if kind == "missing_format":
        wire.pop("format")
    elif kind == "missing_mode":
        wire["format"]["oneOf"][0]["properties"].pop("mode")
    else:
        wire["format"]["oneOf"][0]["properties"]["mode"].pop("const")
    before = deepcopy(wire)
    with pytest.raises(ValueError):
        runner.mode_first_wire(wire)
    assert wire == before


def test_transport_hash__json_roundtrip_and_write_json__matches_actual_transport_bytes(
    wire: dict[str, Any],
    tmp_path: Path,
) -> None:
    payload = runner.mode_first_wire(wire)
    expected = hashlib.sha256(json.dumps(payload).encode("utf-8")).hexdigest()
    assert runner.transport_hash(payload) == expected
    path = tmp_path / "wire.json"
    write_json(path, payload, exclusive=True)
    restored = json.loads(path.read_text(encoding="utf-8"))
    assert runner.transport_hash(restored) == expected
    assert all(list(branch["properties"])[0] == "mode" for branch in restored["format"]["oneOf"])


def test_verify_wire_seals__property_reordering__rejects_despite_object_equality(
    plan: dict[str, Any],
) -> None:
    runner.verify_wire_seals(plan)
    before = deepcopy(plan)
    properties = plan["cases"][0]["candidate_payload"]["format"]["oneOf"][0]["properties"]
    mode = properties.pop("mode")
    properties["mode"] = mode
    assert plan == before and object_hash(plan) == object_hash(before)
    with pytest.raises(ValueError):
        runner.verify_wire_seals(plan)


@pytest.mark.parametrize("mode", ["FACT_REFERENCES", "PROSE"])
def test_record_admission__valid_response__records_order_without_semantic_pass(
    plan: dict[str, Any],
    mode: str,
) -> None:
    case = plan["cases"][0]
    ref = case["prompt_input"]["answer_outline"]["evidence_refs"][0]
    value = (
        {"mode": mode, "items": [{"evidence_ref": ref, "field": "status"}]}
        if mode == "FACT_REFERENCES"
        else {"mode": mode, "schema_version": 2, "answer": "확인한 내용", "evidence_refs": [ref]}
    )
    row: dict[str, Any] = {"payload": case["candidate_payload"], "content": json.dumps(value)}
    content = row["content"]
    runner.record_admission(row, case)
    assert row["content"] == content
    assert row["wire_bytes_sha256"] == case["candidate_transport_sha256"]
    assert row["output_property_order"] == list(value)
    assert row["answer_admission"]["validation"]["structural_result"] == "VALID"
    assert row["answer_admission"]["semantic_verdict"] == "NOT_REVIEWED"


def test_record_admission__wire_order_drift__rejects_before_answer_admission(
    plan: dict[str, Any],
) -> None:
    case = plan["cases"][0]
    payload = deepcopy(case["candidate_payload"])
    properties = payload["format"]["oneOf"][0]["properties"]
    properties["mode"] = properties.pop("mode")
    row: dict[str, Any] = {"payload": payload, "content": '{"mode":"FACT_REFERENCES","items":[]}'}
    with pytest.raises(ValueError):
        runner.record_admission(row, case)
    assert "answer_admission" not in row


@pytest.mark.parametrize("invalid_ref", [False, True])
def test_record_admission__empty_or_invalid_selection__does_not_switch_to_prose(
    plan: dict[str, Any],
    invalid_ref: bool,
) -> None:
    case = plan["cases"][0]
    items = [{"evidence_ref": "foreign", "field": "status"}] if invalid_ref else []
    row: dict[str, Any] = {
        "payload": case["candidate_payload"],
        "content": json.dumps({"mode": "FACT_REFERENCES", "items": items}),
    }
    runner.record_admission(row, case)
    assert row["answer_admission"]["structural_result"] == (
        "INVALID" if invalid_ref else "NO_DRAFT"
    )
    assert "draft" not in row["answer_admission"]


@pytest.mark.parametrize("wrong_model", [False, True])
def test_recorder__fake_runtime_response__preserves_seals_and_stops_on_model_drift(
    plan: dict[str, Any],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    wrong_model: bool,
) -> None:
    observed: list[str] = []
    monkeypatch.setattr(previous.recorder, "RESULTS", tmp_path)

    def post(**kwargs: Any) -> dict[str, Any]:
        payload = kwargs["payload"]
        observed.append(runner.transport_hash(payload))
        assert kwargs["path"] == "/api/generate" and kwargs["timeout_seconds"] == 180
        assert payload["options"] == plan["cases"][0]["candidate_payload"]["options"]
        assert payload["think"] is False
        return {
            "model": "foreign-model" if wrong_model else plan["model"]["model_id"],
            "response": '{"mode":"FACT_REFERENCES","items":[]}',
            "done": True,
            "done_reason": "stop",
            "prompt_eval_count": 5,
            "eval_count": 3,
            "total_duration": 1_000_000,
            "thinking": "MUST_NOT_BE_PERSISTED",
        }

    monkeypatch.setattr(previous.recorder.existing.transport, "_post_json", post)

    def reconstruct() -> dict[str, Any]:
        runner.verify_wire_seals(plan)
        return deepcopy(plan)

    kwargs: dict[str, Any] = {
        "plan_sha256": object_hash(plan),
        "reconstruct_plan": reconstruct,
        "claim_directory": ".mode-first-test-trials",
        "reference_results": [],
        "reference_metric": "historical",
        "stop_after_response": runner.record_admission,
    }
    raw = previous.recorder.execute_registered_plan(plan, tmp_path / "first", **kwargs)
    expected = 1 if wrong_model else len(plan["cases"])
    assert raw["actual_http_calls"] == len(observed) == expected
    assert observed == [case["candidate_transport_sha256"] for case in plan["cases"][:expected]]
    assert raw["completed"] is not wrong_model
    assert raw["binding_unchanged"] is True
    assert raw["provider_calls"] == raw["graph_calls"] == 0
    assert raw["semantic_verdict"] == "NOT_REVIEWED"
    assert "MUST_NOT_BE_PERSISTED" not in json.dumps(raw)
    if wrong_model:
        assert raw["calls"][0]["state"] == "ERROR"
        assert len(raw["not_dispatched"]) == len(plan["cases"]) - 1
    else:
        assert all(
            row["answer_admission"]["structural_result"] == "NO_DRAFT" for row in raw["calls"]
        )
    persisted = json.loads((tmp_path / "first" / "raw.json").read_text(encoding="utf-8"))
    runner.verify_wire_seals(persisted["binding"])
    with pytest.raises(FileExistsError):
        previous.recorder.execute_registered_plan(plan, tmp_path / "repeat", **kwargs)
    assert len(observed) == expected
