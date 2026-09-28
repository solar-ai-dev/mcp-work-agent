"""Owner runner registration/transport probes, never real model or Provider calls."""

from __future__ import annotations

import json
from copy import deepcopy
from typing import Any

import pytest
from evaluation.dataset_v8 import load_cases
from scripts.evaluate_work_bound_source_status import (
    MODEL_ID,
    POLICY,
    PROMPT_ID,
    _grade,
    fixed_cases,
    make_plan,
    owner_instruction,
    run_arm,
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
