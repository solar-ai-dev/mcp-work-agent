"""Synthetic transport tests only: no model, Graph, or live Provider execution."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest
from scripts import evaluate_effect_prohibition_sampler as sampler
from scripts.ru_observation import object_hash
from tests.support.ollama_transport import fake_ollama_transport

from google_work_agent.adapters.llm.ollama import transport
from google_work_agent.ports.llm.output_schema_validation import validate_output_schema


def decision(case: dict[str, Any], forbidden: tuple[str, ...] = ()) -> dict[str, Any]:
    return {
        "effect_prohibitions": [
            {
                "effect": item["effect"],
                "prohibition": "FORBIDDEN" if item["effect"] in forbidden else "NOT_FORBIDDEN",
                "work_unit_ids": case["work_unit_ids"],
            }
            for item in case["input"]["effect_candidates"]
        ]
    }


def test_registered_actual_inputs_are_preserved_without_old_score_reuse() -> None:
    rows = sampler.fixed_cases()
    assert tuple(row["case_id"] for row in rows) == sampler.CASE_IDS
    assert all(object_hash(row["input"]) == row["input_sha256"] for row in rows)
    assert all(row["origin"]["reuse"] == "INPUT_ONLY_NO_BASELINE_SCORE" for row in rows)
    assert rows[3]["work_unit_ids"] == ["work-1", "work-2"]
    assert "새 작업은 만들지 마." in rows[0]["input"]["user_request"]
    assert "새 작업은 만들지 마." not in rows[0]["input"]["goal_candidate"]["goal"]
    assert all("review" not in row["input"] for row in rows)


def test_plan_binds_prompt_schema_inputs_and_exact_two_arm_budget() -> None:
    plan = sampler.make_plan({"model_id": sampler.MODEL_ID, "model_digest": "synthetic-only"})
    assert plan["max_first_calls"] == 12
    assert plan["max_total_calls"] == 24
    assert plan["old_baseline_scores_reused"] == 0
    assert plan["policy"]["temperature_by_arm"] == {"model_default": None, "explicit_zero": 0}
    assert all(len(entry["arms"]) == 2 for entry in plan["order"])
    assert all(row["canonical_case_sha256"] and row["schema_sha256"] for row in plan["cases"])


@pytest.mark.parametrize("index", range(6))
def test_semantic_expectations_follow_request_not_model_shape(index: int) -> None:
    case = sampler.fixed_cases()[index]
    value = decision(case, tuple(case["review"]["expected_forbidden_effects"]))
    assert sampler.review_output(value, case)["result"] == "OWNER_EXPECTATION_MET"
    assert sampler.review_output(value, case)["business_success"] == "NOT_EVALUATED"


def test_only_temperature_wire_option_changes_between_arms(monkeypatch: pytest.MonkeyPatch) -> None:
    case = sampler.fixed_cases()[0]
    outputs = [decision(case), decision(case)]
    calls = fake_ollama_transport(monkeypatch, outputs, model_id=sampler.MODEL_ID)
    rows = [
        sampler.run_arm(case, arm, transport.OllamaHTTPClient()) for arm in sampler.TEMPERATURES
    ]
    left, right = [deepcopy(call["payload"]) for call in calls]
    assert "temperature" not in left["options"]
    assert right["options"].pop("temperature") == 0
    assert left == right
    assert left["options"]["seed"] == 20260923
    assert left["think"] is False
    assert json.loads(left["prompt"])["input"] == case["input"]
    assert "canonical_gold" not in left["prompt"]
    assert all(row["metrics"]["calls"] == 1 for row in rows)
    assert all(row["metrics"]["missing_usage_calls"] == 0 for row in rows)
    assert all(row["final"]["owner_review"]["missing_prohibitions"] == ["CREATE"] for row in rows)
    assert rows[0]["wire_calls"][0]["temperature_option_present"] is False
    assert rows[1]["wire_calls"][0]["temperature_option_present"] is True


def test_schema_repair_is_bounded_and_first_semantics_are_retained(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = sampler.fixed_cases()[0]
    repaired = decision(case, ("CREATE",))
    first = deepcopy(repaired)
    del first["effect_prohibitions"][0]["work_unit_ids"]
    calls = fake_ollama_transport(monkeypatch, [first, repaired], model_id=sampler.MODEL_ID)
    row = sampler.run_arm(case, "explicit_zero", transport.OllamaHTTPClient())
    assert row["metrics"]["calls"] == 2
    assert row["attempts"][0]["raw_output"] == first
    assert row["attempts"][0]["schema_errors"]
    assert row["final"]["owner_review"]["result"] == "OWNER_EXPECTATION_MET"
    assert all(call["payload"]["options"]["temperature"] == 0 for call in calls)
    repair_input = json.loads(calls[1]["payload"]["prompt"])["input"]
    assert repair_input["base_projection"] == case["input"]
    assert repair_input["candidate_output"] == first


def test_repair_cannot_change_unaffected_effect_semantics(monkeypatch: pytest.MonkeyPatch) -> None:
    case = sampler.fixed_cases()[0]
    first = decision(case)
    del first["effect_prohibitions"][1]["work_unit_ids"]
    repaired = decision(case, ("CREATE",))
    fake_ollama_transport(monkeypatch, [first, repaired], model_id=sampler.MODEL_ID)
    row = sampler.run_arm(case, "explicit_zero", transport.OllamaHTTPClient())
    assert row["metrics"]["calls"] == 2
    assert row["final"]["structural_result"] == "FAIL"
    assert row["attempts"][1]["out_of_scope_changes"]


def test_two_invalid_outputs_stop_without_success_replacement(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = sampler.fixed_cases()[0]
    fake_ollama_transport(monkeypatch, [{}, {}], model_id=sampler.MODEL_ID)
    row = sampler.run_arm(case, "model_default", transport.OllamaHTTPClient())
    assert row["metrics"]["calls"] == 2
    assert row["final"]["structural_result"] == "FAIL"


def test_timeout_is_preserved_without_retry_or_complete_usage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail(**kwargs: Any) -> dict[str, Any]:
        raise TimeoutError("synthetic boundary timeout")

    monkeypatch.setattr(transport, "_post_json", fail)
    row = sampler.run_arm(sampler.fixed_cases()[0], "model_default", transport.OllamaHTTPClient())
    assert row["metrics"]["calls"] == 1
    assert row["metrics"]["missing_usage_calls"] == 1
    assert row["final"]["error_type"] == "TimeoutError"
    assert len(row["wire_calls"]) == 1


def test_closed_current_work_ids_remain_product_schema_authority() -> None:
    case = sampler.fixed_cases()[0]
    wrong = decision(case)
    wrong["effect_prohibitions"][0]["work_unit_ids"] = ["invented-work"]
    assert validate_output_schema(wrong, sampler.schema_for(case).json_schema)
    assert sampler.review_output(wrong, case)["result"] == "STRUCTURALLY_INVALID"


def test_frozen_input_tampering_is_rejected(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    rows = json.loads(sampler.FROZEN_INPUTS.read_text(encoding="utf-8"))
    rows[0]["input"]["goal_candidate"]["goal"] = "tampered Goal"
    path = tmp_path / "tampered.json"
    path.write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(sampler, "FROZEN_INPUTS", path)
    with pytest.raises(ValueError, match="input hash mismatch"):
        sampler.fixed_cases()


def test_trial_claim_never_overwrites_existing_record(tmp_path: Path) -> None:
    path = tmp_path / "claim.json"
    sampler.write_json(path, {"first": True}, exclusive=True)
    with pytest.raises(FileExistsError):
        sampler.write_json(path, {"first": False}, exclusive=True)
    assert json.loads(path.read_text(encoding="utf-8")) == {"first": True}
