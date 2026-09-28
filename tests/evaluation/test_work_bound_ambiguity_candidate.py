"""v30 work-local output/fold/wire/reuse contract, with synthetic transport only."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest
from scripts import evaluate_ambiguity_owner as runner
from scripts.ru_ambiguity_owner_candidate import INPUT_MARKER
from scripts.ru_work_bound_ambiguity_candidate import (
    fold_work_ambiguities,
    project_work_ambiguity_input,
    work_ambiguity_schema,
)
from tests.evaluation.test_evaluate_ambiguity_owner import _fake_transport

from google_work_agent.adapters.llm.ollama import transport
from google_work_agent.application.prompt_runtime.prompt_registry import PromptRegistry
from google_work_agent.ports.llm.output_schema_validation import validate_output_schema


def _decisions(*owners: str) -> dict[str, Any]:
    return {
        "work_ambiguities": [
            {
                "work_unit_id": f"work-{index + 1}",
                "missing_information_owner": owner,
                "missing_fields": []
                if owner == "NONE"
                else ["target_resource" if owner == "USER" else "start"],
            }
            for index, owner in enumerate(owners)
        ]
    }


@pytest.fixture
def registered(monkeypatch: pytest.MonkeyPatch) -> tuple[dict[str, Any], dict[str, Any], Path]:
    original = runner.make_plan(model_digest="TEST_MODEL_DIGEST_NO_EXECUTION")
    outputs = [
        {
            "missing_information_owner": case["expected_owners"][0],
            "missing_fields": []
            if case["expected_owners"][0] == "NONE"
            else ["target_resource" if case["expected_owners"][0] == "USER" else "start"],
        }
        for case in original["cases"]
    ]
    _fake_transport(monkeypatch, outputs)
    rows = [
        runner.run_arm(case, "baseline", transport.OllamaHTTPClient(), PromptRegistry())
        for case in original["cases"]
    ]
    document = {"binding": original, "results": rows, "completed": True}
    # In-memory raw at the real allowed artifact boundary; no ignored local file needed in CI.
    path = runner.ROOT / "evaluation/results/v30-test-baseline-not-written/raw.json"
    original_read = Path.read_text

    def read(candidate: Path, *args: Any, **kwargs: Any) -> str:
        if candidate.resolve() == path.resolve():
            return json.dumps(document, ensure_ascii=False)
        return original_read(candidate, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", read)
    plan = runner.make_plan(
        model_digest=original["model_digest"], comparison=runner.V30, baseline_raw_path=path
    )
    return plan, document, path


def test_registration_reuses_only_original_baseline_and_bounds_six_new_calls(
    registered: tuple[dict[str, Any], dict[str, Any], Path],
) -> None:
    plan, old, _ = registered
    assert plan["max_first_calls"] == 6
    assert plan["max_total_calls_with_schema_repair"] == 12
    assert len(plan["baseline_reuse"]["record_sha256"]) == 6
    for case, before in zip(plan["cases"], old["binding"]["cases"], strict=True):
        assert case["arms"]["baseline"]["input"] == before["arms"]["baseline"]["input"]
        assert case["arms"]["candidate"]["input"] == project_work_ambiguity_input(
            before["arms"]["baseline"]["input"]
        )
        assert (
            case["arms"]["candidate"]["input"]["goal_candidate"]
            == before["arms"]["baseline"]["input"]["goal_candidate"]
        )
        assert (
            case["arms"]["candidate"]["input"]["selected_resource_refs"]
            == before["arms"]["baseline"]["input"]["selected_resource_refs"]
        )


def test_exact_closed_work_set_accepts_reordering_but_not_unknown_duplicate_or_missing(
    registered: tuple[dict[str, Any], dict[str, Any], Path],
) -> None:
    projection = registered[0]["cases"][0]["arms"]["candidate"]["input"]
    schema = work_ambiguity_schema(projection).json_schema
    valid = _decisions("CONNECTOR", "USER")
    assert not validate_output_schema(valid, schema)
    assert not validate_output_schema(
        {"work_ambiguities": list(reversed(valid["work_ambiguities"]))}, schema
    )
    for values in (["work-1"], ["work-1", "work-1"], ["work-1", "unknown"]):
        bad = deepcopy(valid)
        bad["work_ambiguities"] = [
            dict(valid["work_ambiguities"][0], work_unit_id=value) for value in values
        ]
        assert validate_output_schema(bad, schema)


def test_fold_preserves_chosen_fields_without_semantic_correction(
    registered: tuple[dict[str, Any], dict[str, Any], Path],
) -> None:
    projection = registered[0]["cases"][0]["arms"]["candidate"]["input"]
    raw = _decisions("CONNECTOR", "USER")
    raw["work_ambiguities"][1]["missing_fields"] = ["a concrete second-target choice"]
    original = deepcopy(raw)
    assert fold_work_ambiguities(raw, projection) == {
        "missing_information_owner": "USER",
        "missing_fields": ["a concrete second-target choice"],
    }
    assert raw == original
    both = _decisions("USER", "USER")
    assert fold_work_ambiguities(both, projection)["missing_fields"] == [
        "target_resource",
        "target_resource",
    ]
    assert (
        fold_work_ambiguities(_decisions("CONNECTOR", "NONE"), projection)[
            "missing_information_owner"
        ]
        == "CONNECTOR"
    )
    assert fold_work_ambiguities(_decisions("NONE", "NONE"), projection)["missing_fields"] == []
    invalid = _decisions("NONE", "USER")
    invalid["work_ambiguities"][0]["missing_fields"] = ["invalid but lower priority"]
    with pytest.raises(ValueError, match="NONE needs empty"):
        fold_work_ambiguities(invalid, projection)


@pytest.mark.parametrize("case_index", [0, 1])
def test_candidate_wire_counts_absent_and_work1_connector_work2_user_remains_confirmation(
    registered: tuple[dict[str, Any], dict[str, Any], Path],
    monkeypatch: pytest.MonkeyPatch,
    case_index: int,
) -> None:
    case = registered[0]["cases"][case_index]
    raw = _decisions("CONNECTOR", "USER")
    calls = _fake_transport(monkeypatch, [raw])
    record = runner.run_arm(case, "candidate", transport.OllamaHTTPClient(), PromptRegistry())
    assert len(calls) == 1
    wire = calls[0]["payload"]
    assert "searchable_target_anchor_count" not in wire["system"] + wire["prompt"]
    assert "connector_owned_source_count" not in wire["system"] + wire["prompt"]
    assert wire["options"] == {"num_ctx": 16384, "temperature": 0.0, "seed": runner.SEED}
    assert wire["think"] is False
    assert record["attempts"][0]["raw_output"] == raw
    assert record["attempts"][0]["folded_output"] == {
        "missing_information_owner": "USER",
        "missing_fields": ["target_resource"],
    }
    assert record["final"]["postvalidator_output"]["requires_confirmation"] is True
    assert record["final"]["per_work_owner_evaluation"][0]["actual_owner"] == "CONNECTOR"
    assert record["final"]["per_work_owner_evaluation"][1]["actual_owner"] == "USER"
    assert "PENDING" in record["final"]["semantic_review"]
    projected_text = wire["system"].partition(INPUT_MARKER)[2]
    assert json.loads(projected_text) == case["arms"]["candidate"]["input"]


def test_one_repair_only_uses_same_work_contract_and_does_not_reinsert_counts(
    registered: tuple[dict[str, Any], dict[str, Any], Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = registered[0]["cases"][0]
    invalid = _decisions("CONNECTOR", "USER")
    invalid["work_ambiguities"][1].pop("missing_fields")
    calls = _fake_transport(monkeypatch, [invalid, _decisions("CONNECTOR", "USER")])
    record = runner.run_arm(case, "candidate", transport.OllamaHTTPClient(), PromptRegistry())
    assert len(calls) == 2
    assert record["attempts"][0]["schema_errors"]
    assert record["final"]["structural_result"] == "PASS"
    assert record["attempts"][1]["out_of_scope_repair_changes"] == []
    assert "searchable_target_anchor_count" not in calls[1]["payload"]["system"]
    assert "connector_owned_source_count" not in calls[1]["payload"]["prompt"]


def test_repair_cannot_change_other_work_owner(
    registered: tuple[dict[str, Any], dict[str, Any], Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = registered[0]["cases"][0]
    invalid = _decisions("CONNECTOR", "USER")
    invalid["work_ambiguities"][1].pop("missing_fields")
    repaired = _decisions("NONE", "USER")
    _fake_transport(monkeypatch, [invalid, repaired])
    record = runner.run_arm(case, "candidate", transport.OllamaHTTPClient(), PromptRegistry())
    assert record["final"]["structural_result"] == "FAIL"
    assert record["attempts"][1]["out_of_scope_repair_changes"]


@pytest.mark.parametrize(
    "damage", ["input", "schema", "prompt", "runtime", "model", "code", "duplicate"]
)
def test_baseline_reuse_rejects_changed_actual_conditions(
    registered: tuple[dict[str, Any], dict[str, Any], Path],
    damage: str,
) -> None:
    plan, document, path = registered
    call = document["results"][0]["transport_calls"][0]
    if damage in ("input", "schema", "prompt"):
        call[
            {"input": "input_sha256", "schema": "schema_sha256", "prompt": "instruction_sha256"}[
                damage
            ]
        ] = "changed"
    elif damage == "runtime":
        call["temperature"] = 1
    elif damage == "model":
        document["binding"]["model_digest"] = "other-model"
    elif damage == "code":
        key = "src/google_work_agent/application/agents/request_understanding/detect_ambiguity.py"
        document["binding"]["source_hashes"][key] = "changed"
    else:
        document["results"].append(deepcopy(document["results"][0]))
    with pytest.raises(ValueError):
        runner.reusable_baseline(path, plan)


def test_candidate_cannot_modify_semantics_while_removing_counts(
    registered: tuple[dict[str, Any], dict[str, Any], Path],
) -> None:
    case = registered[0]["cases"][0]
    changed = deepcopy(case["arms"]["candidate"]["input"])
    changed["goal_candidate"]["constraints"] = []
    registry = PromptRegistry()
    with pytest.raises(ValueError, match="remove only"):
        runner.owner_instruction(
            changed,
            registry.lookup_for_evaluation(runner.PROMPT_ID),
            registry,
            "candidate",
            representation=runner.V30,
            product_projection=case["arms"]["baseline"]["input"],
        )


def test_same_folded_owner_does_not_certify_correct_work_binding(
    registered: tuple[dict[str, Any], dict[str, Any], Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = registered[0]["cases"][0]
    _fake_transport(monkeypatch, [_decisions("USER", "CONNECTOR")])
    record = runner.run_arm(case, "candidate", transport.OllamaHTTPClient(), PromptRegistry())
    # Wrong target attribution still folds to USER; retain the evidence for manual grading.
    assert record["final"]["raw_owner_evaluation"]["owner_choice"] == "OWNER_CHOICE_PASS"
    assert record["final"]["per_work_owner_evaluation"][0]["actual_owner"] == "USER"
    assert record["final"]["per_work_owner_evaluation"][1]["actual_owner"] == "CONNECTOR"
    assert record["final"]["semantic_review"] == "PENDING_MANUAL_REVIEW"


def test_shared_contract_comparison_preserves_global_fields_and_current_slot() -> None:
    before = {
        "schema_version": 1,
        "forbidden_input_fields": ["gold"],
        "entries": [
            {"prompt_slot_id": runner.PROMPT_ID, "input_schema_version": 3},
            {"prompt_slot_id": "retrieval.assess_sufficiency", "input_schema_version": 2},
        ],
    }
    other_slot = deepcopy(before)
    other_slot["entries"][1]["input_schema_version"] = 3
    assert runner._relevant_contract(before, "entries") == runner._relevant_contract(
        other_slot, "entries"
    )
    current_slot = deepcopy(before)
    current_slot["entries"][0]["input_schema_version"] = 4
    assert runner._relevant_contract(before, "entries") != runner._relevant_contract(
        current_slot, "entries"
    )
    global_fields = deepcopy(before)
    global_fields["forbidden_input_fields"] = []
    assert runner._relevant_contract(before, "entries") != runner._relevant_contract(
        global_fields, "entries"
    )
