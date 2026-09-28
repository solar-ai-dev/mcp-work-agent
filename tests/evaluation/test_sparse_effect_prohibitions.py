"""Sparse owner representation and real Product consumers, without model calls."""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from dataclasses import asdict
from pathlib import Path
from typing import Any

import pytest
from scripts import evaluate_effect_prohibition_sampler as baseline
from scripts import evaluate_sparse_effect_prohibitions as candidate
from scripts.ru_observation import object_hash
from tests.support.ollama_transport import fake_ollama_transport

from google_work_agent.application.agents.request_understanding import (
    identify_output_responsibilities as outputs,
)
from google_work_agent.application.prompt_runtime.prompt_registry import PromptRegistry
from google_work_agent.application.tool_registry.load_signed_tool_registry import (
    load_signed_tool_registry,
)
from google_work_agent.ports.llm.output_schema_validation import validate_output_schema

_OUTPUT_CANDIDATES = outputs.build_output_responsibility_candidates(load_signed_tool_registry())


def sparse(*effects: str, work_ids: tuple[str, ...] = ("work-1",)) -> dict[str, Any]:
    return {
        "effect_prohibitions": [
            {"effect": effect, "work_unit_ids": list(work_ids)} for effect in effects
        ]
    }


@pytest.mark.parametrize("index", range(6))
def test_current_normalizer_preserves_generated_sparse_items(index: int) -> None:
    case = baseline.fixed_cases()[index]
    value = sparse(*case["review"]["expected_forbidden_effects"])
    assert candidate.validate_sparse(value, case) == value
    assert candidate.normalize_with_product(value, case) == value["effect_prohibitions"]
    assert candidate.review_sparse(value, case)["result"] == "OWNER_EXPECTATION_MET"


def test_empty_wrong_answer_is_not_filled_from_gold_or_original_request() -> None:
    case = baseline.fixed_cases()[0]
    empty = sparse()
    assert candidate.validate_sparse(empty, case) == empty
    assert candidate.normalize_with_product(empty, case) == []
    assert candidate.review_sparse(empty, case)["missing_prohibitions"] == ["CREATE"]
    assert candidate.review_sparse(empty, case)["result"] == "OWNER_EXPECTATION_MISMATCH"


def test_multi_effect_and_multiple_work_refs_are_preserved_without_union() -> None:
    case = baseline.fixed_cases()[3]
    value = {
        "effect_prohibitions": [
            {"effect": "CREATE", "work_unit_ids": ["work-2"]},
            {"effect": "SEND", "work_unit_ids": ["work-1", "work-2"]},
        ]
    }
    assert candidate.normalize_with_product(value, case) == value["effect_prohibitions"]
    assert candidate.to_owner_decisions(value, case)["effect_prohibitions"][0] == {
        "effect": "CREATE",
        "work_unit_ids": ["work-2"],
        "prohibition": "FORBIDDEN",
    }


@pytest.mark.parametrize(
    "value",
    [
        {"effect_prohibitions": [{"effect": "READ", "work_unit_ids": ["work-1"]}]},
        {"effect_prohibitions": [{"effect": "CREATE", "work_unit_ids": ["other-work"]}]},
        {"effect_prohibitions": [{"effect": "CREATE", "work_unit_ids": []}]},
        {"effect_prohibitions": [{"effect": "CREATE", "work_unit_ids": ["work-1", "work-1"]}]},
        {
            "effect_prohibitions": [
                {"effect": "CREATE", "work_unit_ids": ["work-1"]},
                {"effect": "CREATE", "work_unit_ids": ["work-2"]},
            ]
        },
        {
            "effect_prohibitions": [
                {"effect": "CREATE", "work_unit_ids": ["work-1"], "resource_type": "TASK"}
            ]
        },
    ],
)
def test_closed_shape_rejects_invalid_ids_and_unregistered_scope(value: object) -> None:
    case = baseline.fixed_cases()[3]
    with pytest.raises(ValueError, match="shape invalid"):
        candidate.validate_sparse(value, case)


def test_product_output_validator_blocks_only_intersecting_work() -> None:
    case = baseline.fixed_cases()[3]
    prohibitions = candidate.to_owner_decisions(sparse("CREATE", work_ids=("work-2",)), case)
    allowed = {
        "output_responsibilities": [
            {"resource_type": "TASK", "effect": "CREATE", "work_unit_ids": ["work-1"]},
        ]
    }
    assert (
        outputs.validate_output_responsibility_candidate(
            allowed,
            output_candidates=_OUTPUT_CANDIDATES,
            effect_prohibitions=prohibitions,
            work_unit_ids=case["work_unit_ids"],
        )
        == allowed
    )
    blocked = deepcopy(allowed)
    blocked["output_responsibilities"][0]["work_unit_ids"] = ["work-2"]
    with pytest.raises(outputs.ProhibitedOutputResponsibilityDecisionError):
        outputs.validate_output_responsibility_candidate(
            blocked,
            output_candidates=_OUTPUT_CANDIDATES,
            effect_prohibitions=prohibitions,
            work_unit_ids=case["work_unit_ids"],
        )


def test_source_only_read_exclusion_does_not_make_effect_bans() -> None:
    case = baseline.fixed_cases()[-1]
    value = sparse()
    assert "작업이나 캘린더는 보지 마." in case["input"]["user_request"]
    assert candidate.review_sparse(value, case)["result"] == "OWNER_EXPECTATION_MET"
    assert outputs.validate_output_responsibility_candidate(
        {"output_responsibilities": []},
        output_candidates=_OUTPUT_CANDIDATES,
        effect_prohibitions=candidate.to_owner_decisions(value, case),
        work_unit_ids=case["work_unit_ids"],
    ) == {"output_responsibilities": []}


def test_actual_wire_uses_same_input_default_sampler_and_new_prompt_schema(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = baseline.fixed_cases()[0]
    original_schema = baseline.schema_for(case)
    original_ref = PromptRegistry().lookup_for_evaluation(baseline.PROMPT_ID)
    calls = fake_ollama_transport(monkeypatch, [sparse("CREATE")], model_id=baseline.MODEL_ID)
    row = candidate.run_candidate(case, baseline.OllamaHTTPClient())
    assert row["metrics"]["calls"] == 1
    assert row["normalized_prohibitions"] == sparse("CREATE")["effect_prohibitions"]
    assert row["final"]["owner_review"]["result"] == "OWNER_EXPECTATION_MET"
    payload = calls[0]["payload"]
    wire = json.loads(payload["prompt"])
    assert wire["input"] == case["input"]
    assert wire["prompt_ref"]["content_hash"] == candidate.candidate_ref().content_hash
    assert payload["format"] == candidate.sparse_schema(case).json_schema
    assert payload["options"] == {"num_ctx": 16384, "seed": 20260923}
    assert payload["think"] is False
    assert payload["system"].startswith(candidate.SOURCE.rstrip())
    assert "canonical_gold" not in payload["system"]
    assert baseline.schema_for(case) == original_schema
    assert PromptRegistry().lookup_for_evaluation(baseline.PROMPT_ID) == original_ref
    assert baseline.validate_effect_prohibition_candidate.__module__.startswith(
        "google_work_agent."
    )


def test_one_bounded_product_repair_retains_sparse_prompt_and_unaffected_items(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = baseline.fixed_cases()[0]
    first = {"effect_prohibitions": [{"effect": "CREATE"}]}
    repaired = sparse("CREATE")
    calls = fake_ollama_transport(monkeypatch, [first, repaired], model_id=baseline.MODEL_ID)
    row = candidate.run_candidate(case, baseline.OllamaHTTPClient())
    assert row["metrics"]["calls"] == 2
    assert row["attempts"][0]["raw_output"] == first
    assert row["attempts"][1]["raw_output"] == repaired
    assert row["final"]["structural_result"] == "PASS"
    for call in calls:
        assert call["payload"]["system"].startswith(candidate.SOURCE.rstrip())
        assert "temperature" not in call["payload"]["options"]
    assert json.loads(calls[1]["payload"]["prompt"])["input"]["base_projection"] == case["input"]


def test_product_repair_guard_rejects_change_to_unaffected_forbidden_effect(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = baseline.fixed_cases()[0]
    first = sparse("CREATE", "SEND")
    del first["effect_prohibitions"][1]["work_unit_ids"]
    repaired = sparse("DELETE", "SEND")
    fake_ollama_transport(monkeypatch, [first, repaired], model_id=baseline.MODEL_ID)
    row = candidate.run_candidate(case, baseline.OllamaHTTPClient())
    assert row["final"]["structural_result"] == "FAIL"
    assert row["attempts"][1]["out_of_scope_changes"]


def test_invalid_first_and_repair_stop_at_two_calls(monkeypatch: pytest.MonkeyPatch) -> None:
    case = baseline.fixed_cases()[0]
    fake_ollama_transport(monkeypatch, [{}, {}], model_id=baseline.MODEL_ID)
    row = candidate.run_candidate(case, baseline.OllamaHTTPClient())
    assert row["metrics"]["calls"] == 2
    assert row["final"]["structural_result"] == "FAIL"


def test_unrecognized_effects_are_not_selected_to_fill_sparse_schema() -> None:
    case = baseline.fixed_cases()[0]
    assert not validate_output_schema(sparse(), candidate.sparse_schema(case).json_schema)
    assert not validate_output_schema(
        sparse("CREATE", "UPDATE", "SEND", "DELETE"), candidate.sparse_schema(case).json_schema
    )
    assert object_hash(candidate.sparse_schema(case).json_schema) != object_hash(
        baseline.schema_for(case).json_schema
    )
    assert asdict(candidate.candidate_ref()) != asdict(
        PromptRegistry().lookup_for_evaluation(baseline.PROMPT_ID)
    )


def reuse_fixture(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> tuple[dict[str, Any], Path]:
    current = baseline.make_plan({"model_id": baseline.MODEL_ID, "model_digest": "test-only"})
    rows = [
        {
            "case_id": case["case_id"],
            "arm": "model_default",
            "input_sha256": case["input_sha256"],
            "wire_calls": [
                {
                    "format_sha256": case["schema_sha256"],
                    "system_sha256": case["instruction_sha256"],
                    "options": {"num_ctx": 16384, "seed": baseline.SEED},
                    "think": False,
                }
            ],
        }
        for case in current["cases"]
    ]
    path = tmp_path / "synthetic-baseline.json"
    path.write_text(json.dumps({"binding": current, "results": rows}), encoding="utf-8")
    monkeypatch.setattr(
        candidate, "BASELINE_RAW_SHA256", hashlib.sha256(path.read_bytes()).hexdigest()
    )
    return current, path


def test_baseline_reuse_checks_actual_input_schema_and_related_implementation(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    current, path = reuse_fixture(monkeypatch, tmp_path)
    assert len(candidate.baseline_reuse(current, path)["rows"]) == 6
    for field in ("input_sha256", "schema_sha256", "instruction_sha256"):
        changed = deepcopy(current)
        changed["cases"][0][field] = "changed"
        with pytest.raises(ValueError, match="wire"):
            candidate.baseline_reuse(changed, path)
    changed = deepcopy(current)
    changed["source_hashes"]["scripts/evaluate_effect_prohibition_sampler.py"] = "changed"
    with pytest.raises(ValueError, match="implementation changed"):
        candidate.baseline_reuse(changed, path)


def test_baseline_reuse_rejects_different_sampler_or_model(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    current, path = reuse_fixture(monkeypatch, tmp_path)
    for field in ("model", "policy"):
        changed = deepcopy(current)
        changed[field] = {"different": True}
        with pytest.raises(ValueError, match="mismatch"):
            candidate.baseline_reuse(changed, path)
