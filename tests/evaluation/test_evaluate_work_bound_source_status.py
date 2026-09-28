"""Owner runner registration/transport probes, never real model or Provider calls."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest
from evaluation.dataset_v8 import load_cases
from scripts import evaluate_work_bound_source_status as owner_runner
from scripts.evaluate_work_bound_source_status import (
    MODEL_ID,
    POLICY,
    PROMPT_ID,
    V26_V27,
    _grade,
    fixed_cases,
    make_plan,
    owner_instruction,
    run_arm,
    summarize_results,
)

from google_work_agent.adapters.llm.ollama import transport
from google_work_agent.application.prompt_runtime.prompt_registry import PromptRegistry


def test_registration_fixes_six_cases_and_keeps_gold_out_of_owner_input() -> None:
    plan = make_plan(model_digest="DRY_MODEL_NOT_EXECUTED")
    assert len(plan["cases"]) == len(set(plan["case_ids"])) == 6
    assert plan["trials_per_arm_case"] == 1
    assert plan["max_first_calls"] == 12
    assert plan["max_total_calls_with_schema_repair"] == 24
    assert plan["runtime_policy"] == POLICY
    assert plan["candidate_binding"]["activation_status"] == "DRAFT"
    canonical = load_cases()
    for case in plan["cases"]:
        if case["case_id"].startswith("CASE-"):
            assert (
                case["prompt_input"]["user_request"]
                == canonical[case["case_id"]].raw["canonical_user_prompt"]
            )
        for arm in case["arms"].values():
            serialized = json.dumps(arm["input"])
            for field in ("expected_bindings", "evaluation_gold", "expectation_basis"):
                assert field not in serialized


def test_candidate_changes_current_input_only_not_product_instruction_text() -> None:
    registry = PromptRegistry()
    ref = registry.lookup_for_evaluation(PROMPT_ID)
    case = make_plan(model_digest=None)["cases"][0]
    baseline = owner_instruction(case["arms"]["baseline"]["input"], ref, registry)
    candidate = owner_instruction(case["arms"]["candidate"]["input"], ref, registry)
    marker = "Allowed current-Run input projection (JSON):\n"
    assert baseline.split(marker)[0] == candidate.split(marker)[0]
    before = json.loads(baseline.split(marker)[1])
    after = json.loads(candidate.split(marker)[1])
    assert after.pop("requested_work") == case["prompt_input"]["requested_work"]
    assert after == before


def test_semantic_grader_accepts_shared_grouping_and_detects_cross_work_leakage() -> None:
    shared = fixed_cases()[2]
    status = {
        "value": "INCOMPLETE",
        "source_resource_type": "TASK",
        "source": "USER_REQUEST",
        "source_text": "미완료 Task",
        "work_unit_ids": ["work-1", "work-2"],
    }
    assert _grade({"statuses": [status]}, shared, "candidate")["owner_result"] == "PASS"
    split = [{**status, "work_unit_ids": [unit]} for unit in ("work-1", "work-2")]
    assert _grade({"statuses": split}, shared, "candidate")["owner_result"] == "PASS"
    opposite = fixed_cases()[0]
    leaked = _grade({"statuses": [status]}, opposite, "candidate")
    assert leaked["owner_result"] == "FAIL"
    assert leaked["missing_bindings"] == [("TASK", "COMPLETED", "work-2")]
    assert leaked["extra_bindings"] == [("TASK", "INCOMPLETE", "work-2")]


def _fake_transport(monkeypatch: pytest.MonkeyPatch, outputs: list[object]) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []

    def post(**kwargs: Any) -> dict[str, Any]:
        calls.append(deepcopy(kwargs))
        value = outputs.pop(0)
        return {
            "response": json.dumps(value, ensure_ascii=False),
            "model": MODEL_ID,
            "prompt_eval_count": 30,
            "eval_count": 20,
            "total_duration": 1000000,
        }

    monkeypatch.setattr(transport, "_post_json", post)
    return calls


def test_actual_transport_options_and_first_response_are_observed_without_execution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _fake_transport(monkeypatch, [{"statuses": []}])
    case = make_plan(model_digest=None)["cases"][3]
    record = run_arm(case, "candidate", transport.OllamaHTTPClient(), PromptRegistry())
    assert len(calls) == 1
    wire = calls[0]["payload"]
    assert wire["options"] == {"num_ctx": 16384, "temperature": 0.0, "seed": 20260923}
    assert wire["think"] is False
    assert calls[0]["timeout_seconds"] == 180
    assert record["attempts"][0]["raw_output"] == {"statuses": []}
    assert record["metrics"]["calls"] == 1
    assert record["metrics"]["output_tokens"] == 20
    assert record["final"]["owner_result"] == "PASS"


def test_one_schema_repair_preserves_failed_trial_and_rejects_unaffected_changes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first = {
        "statuses": [
            {
                "value": "INCOMPLETE",
                "source_resource_type": "TASK",
                "source": "USER_REQUEST",
                "source_text": "미완료 Task",
            }
        ]
    }
    repaired = deepcopy(first)
    repaired["statuses"][0].update(value="COMPLETED", work_unit_ids=["work-1"])
    calls = _fake_transport(monkeypatch, [first, repaired])
    case = make_plan(model_digest=None)["cases"][0]
    record = run_arm(case, "candidate", transport.OllamaHTTPClient(), PromptRegistry())
    assert len(calls) == 2
    assert [attempt["attempt"] for attempt in record["attempts"]] == ["FIRST", "SCHEMA_REPAIR"]
    assert record["attempts"][0]["raw_output"] == first
    assert record["attempts"][1]["out_of_scope_repair_changes"]
    assert record["final"]["owner_result"] == "FAIL"
    assert "unaffected" in record["final"]["error"]


def test_provenance_error_does_not_trigger_schema_repair_or_semantic_rerun(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _fake_transport(
        monkeypatch,
        [
            {
                "statuses": [
                    {
                        "value": "INCOMPLETE",
                        "source_resource_type": "TASK",
                        "source": "USER_REQUEST",
                        "source_text": "not in request",
                        "work_unit_ids": ["work-1"],
                    }
                ]
            }
        ],
    )
    case = make_plan(model_digest=None)["cases"][0]
    record = run_arm(case, "candidate", transport.OllamaHTTPClient(), PromptRegistry())
    assert len(calls) == 1
    assert record["final"]["owner_result"] == "FAIL"
    assert record["final"]["error_type"] == "RequestGoalSemanticValidationError"


def test_slot_registration_reuses_exact_v26_input_and_fixed_cases() -> None:
    previous = make_plan(model_digest=None)
    plan = make_plan(model_digest=None, comparison=V26_V27)
    assert plan["candidate_binding"]["candidate_output_version"] == 4
    assert plan["candidate_binding"]["prompt_change"] == "OUTPUT_SHAPE_ONLY"
    assert plan["runtime_policy"] == previous["runtime_policy"]
    assert plan["case_ids"] == previous["case_ids"]
    assert plan["max_first_calls"] == 12
    for before, case in zip(previous["cases"], plan["cases"], strict=True):
        baseline, candidate = case["arms"]["baseline"], case["arms"]["candidate"]
        assert baseline["input"] == candidate["input"] == before["arms"]["candidate"]["input"]
        assert baseline["input_sha256"] == candidate["input_sha256"]
        assert baseline["schema_sha256"] == before["arms"]["candidate"]["schema_sha256"]
        assert baseline["prompt_source_sha256"] != candidate["prompt_source_sha256"]
        assert case["goal_candidate"] == before["goal_candidate"]
        assert case["responsibilities"] == before["responsibilities"]
        assert case["expected_bindings"] == before["expected_bindings"]
        assert "expected_bindings" not in json.dumps(candidate["input"])


def test_slot_transport_records_raw_separately_from_deterministic_projection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output = {
        "source_status_slots": {
            "slot_1": {"decision": "NO_FILTER"},
            "slot_2": {"decision": "NO_FILTER"},
        }
    }
    calls = _fake_transport(monkeypatch, [output])
    case = make_plan(model_digest=None, comparison=V26_V27)["cases"][3]
    record = run_arm(case, "candidate", transport.OllamaHTTPClient(), PromptRegistry())
    assert len(calls) == 1
    event = record["attempts"][0]
    assert event["raw_output"] == output
    assert event["deterministic_status_projection"] == {"statuses": []}
    assert record["final"]["owner_result"] == "PASS"
    wire = calls[0]["payload"]
    assert wire["options"] == {"num_ctx": 16384, "temperature": 0.0, "seed": 20260923}
    assert wire["format"] == case["arms"]["candidate"]["schema"]["json_schema"]
    assert "STATUS_FILTER" in wire["system"]


def test_slot_trial_does_not_turn_schema_valid_semantic_failure_into_repair(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output = {
        "source_status_slots": {
            "slot_1": {
                "decision": "STATUS_FILTER",
                "predicates": [
                    {"value": "INCOMPLETE", "source": "USER_REQUEST", "source_text": "현재 상태"}
                ],
            },
            "slot_2": {"decision": "NO_FILTER"},
        }
    }
    calls = _fake_transport(monkeypatch, [output])
    case = make_plan(model_digest=None, comparison=V26_V27)["cases"][3]
    record = run_arm(case, "candidate", transport.OllamaHTTPClient(), PromptRegistry())
    assert len(calls) == 1
    assert record["final"]["owner_result"] == "FAIL"
    assert record["final"]["extra_bindings"] == [("TASK", "INCOMPLETE", "work-1")]


def test_slot_schema_repair_preserves_unaffected_decisions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first = {
        "source_status_slots": {
            "slot_1": {
                "decision": "STATUS_FILTER",
                "predicates": [{"value": "INCOMPLETE", "source_text": "미완료 Task"}],
            },
            "slot_2": {"decision": "NO_FILTER"},
        }
    }
    repaired = deepcopy(first)
    repaired["source_status_slots"]["slot_1"]["predicates"][0]["source"] = "USER_REQUEST"
    repaired["source_status_slots"]["slot_2"] = deepcopy(repaired["source_status_slots"]["slot_1"])
    calls = _fake_transport(monkeypatch, [first, repaired])
    case = make_plan(model_digest=None, comparison=V26_V27)["cases"][0]
    record = run_arm(case, "candidate", transport.OllamaHTTPClient(), PromptRegistry())
    assert len(calls) == 2
    assert record["attempts"][1]["out_of_scope_repair_changes"]
    assert record["final"]["owner_result"] == "FAIL"


def test_v26_arm_keeps_explicit_work_binding_when_named_baseline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = make_plan(model_digest=None, comparison=V26_V27)["cases"][0]
    output = {
        "statuses": [
            {
                "value": value,
                "source_resource_type": "TASK",
                "source": "USER_REQUEST",
                "source_text": text,
                "work_unit_ids": [unit],
            }
            for value, text, unit in (
                ("INCOMPLETE", "미완료 Task", "work-1"),
                ("COMPLETED", "완료 Task", "work-2"),
            )
        ]
    }
    calls = _fake_transport(monkeypatch, [output])
    record = run_arm(case, "baseline", transport.OllamaHTTPClient(), PromptRegistry())
    assert len(calls) == 1
    assert record["final"]["owner_result"] == "PASS"


def _fake_historical_trial(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    plan = make_plan(model_digest="FIXED_TEST_DIGEST")
    _fake_transport(monkeypatch, [{"statuses": []} for _ in plan["cases"]])
    return {
        "completed": True,
        "binding": plan,
        "results": [
            run_arm(case, "candidate", transport.OllamaHTTPClient(), PromptRegistry())
            for case in plan["cases"]
        ],
    }


def test_baseline_reuse_validates_exact_request_contract_runtime_and_record(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    historical = _fake_historical_trial(monkeypatch)
    current = make_plan(model_digest="FIXED_TEST_DIGEST", comparison=V26_V27)
    path = tmp_path / "evaluation/results/raw.json"
    path.parent.mkdir(parents=True)
    original_text = json.dumps(historical, ensure_ascii=False)
    path.write_text(original_text, encoding="utf-8")
    monkeypatch.setattr(owner_runner, "ROOT", tmp_path)
    reused = owner_runner.load_reusable_baseline(path, current)
    assert len(reused) == 6
    assert path.read_text(encoding="utf-8") == original_text
    assert reused["CASE-CORE-005"]["final"]["owner_result"] == "PASS"
    for field, altered in (
        ("model_digest", "OTHER"),
        ("runtime_policy", {**current["runtime_policy"], "seed": 2}),
        ("dataset_sha256", "OTHER"),
    ):
        changed = deepcopy(current)
        changed[field] = altered
        with pytest.raises(ValueError, match="does not match"):
            owner_runner.load_reusable_baseline(path, changed)
    for field in ("prompt_input", "responsibilities", "expected_bindings"):
        changed = deepcopy(current)
        changed["cases"][0][field] = []
        with pytest.raises(ValueError, match="changed"):
            owner_runner.load_reusable_baseline(path, changed)
    changed = deepcopy(current)
    changed["cases"][0]["arms"]["baseline"]["schema_sha256"] = "OTHER"
    with pytest.raises(ValueError, match="schema_sha256 changed"):
        owner_runner.load_reusable_baseline(path, changed)


def test_reuse_plan_limits_new_calls_and_accounts_historical_calls_separately(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    historical = _fake_historical_trial(monkeypatch)
    rows = {row["case_id"]: row for row in historical["results"]}
    path = owner_runner.ROOT / "evaluation/results/fake-baseline/raw.json"
    real_hash = owner_runner.normalized_sha256
    monkeypatch.setattr(owner_runner, "load_reusable_baseline", lambda *_: deepcopy(rows))
    monkeypatch.setattr(
        owner_runner,
        "normalized_sha256",
        lambda given: "RAW_HASH" if given == path else real_hash(given),
    )
    plan = make_plan(model_digest="FIXED_TEST_DIGEST", comparison=V26_V27, baseline_raw_path=path)
    assert plan["max_first_calls"] == 6
    assert plan["max_total_calls_with_schema_repair"] == 12
    assert plan["baseline_reuse"]["new_call"] is False
    assert plan["baseline_reuse"]["reused_calls"] == 6
    assert plan["baseline_reuse"]["original_arm"] == "candidate"
    assert plan["baseline_reuse"]["raw_sha256"] == "RAW_HASH"
    reused = [{**row, "arm": "baseline", "new_call": False} for row in rows.values()]
    fresh = [{**row, "arm": "candidate", "new_call": True} for row in rows.values()]
    summary = summarize_results(reused + fresh)
    assert summary["baseline"]["new_call_metrics"]["calls"] == 0
    assert summary["baseline"]["reused_call_metrics"]["calls"] == 6
    assert summary["candidate"]["new_call_metrics"]["calls"] == 6
    assert summary["candidate"]["reused_call_metrics"]["calls"] == 0
