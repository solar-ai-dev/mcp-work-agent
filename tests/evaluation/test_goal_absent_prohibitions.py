"""V33 Goal-only removal, including actual wire and unchanged Product loader."""

from __future__ import annotations

import json
from copy import deepcopy
from typing import Any

import pytest
from scripts import evaluate_goal_absent_prohibitions as candidate
from scripts import evaluate_sparse_effect_prohibitions as sparse
from scripts.ru_observation import object_hash
from tests.support.ollama_transport import fake_ollama_transport

from google_work_agent.application.prompt_runtime.assemble_prompt import (
    PromptAssemblyError,
    assemble_prompt,
)
from google_work_agent.application.prompt_runtime.prompt_registry import EVALUATION, PromptRegistry


@pytest.mark.parametrize("index", range(6))
def test_only_generated_goal_is_removed_and_restoration_is_exact(index: int) -> None:
    original = sparse.baseline.fixed_cases()[index]
    projected = candidate.project_case(original)
    expected = deepcopy(original["input"])
    goal = expected.pop("goal_candidate")
    assert projected["input"] == expected
    assert projected["normalization_goal_candidate"] == goal
    assert projected["original_input_sha256"] == original["input_sha256"]
    assert projected["input_sha256"] == object_hash(expected)
    assert candidate.restore_normalization_case(projected)["input"] == original["input"]
    assert sparse.sparse_schema(projected) == sparse.sparse_schema(original)
    assert candidate.candidate_ref().content_hash == sparse.candidate_ref().content_hash
    assert candidate.candidate_ref().prompt_version == sparse.candidate_ref().prompt_version
    assert (
        candidate.candidate_ref().input_schema_version
        != sparse.candidate_ref().input_schema_version
    )


def test_system_changes_only_the_exact_json_projection_not_any_prompt_body() -> None:
    original = sparse.baseline.fixed_cases()[0]
    projected = candidate.project_case(original)
    old_system = sparse.instruction(sparse.candidate_ref(), original["input"])
    new_system = candidate.instruction(projected, candidate.candidate_ref(), projected["input"])
    marker = "Allowed current-Run input projection (JSON):\n"
    old_json = json.dumps(
        original["input"], ensure_ascii=False, separators=(",", ":"), sort_keys=True
    )
    new_json = json.dumps(
        projected["input"], ensure_ascii=False, separators=(",", ":"), sort_keys=True
    )
    assert new_system == old_system.replace(marker + old_json, marker + new_json, 1)
    assert "goal_candidate는 앞선 해석" in new_system


def test_product_loader_still_rejects_absent_goal_before_and_after_candidate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    projected = candidate.project_case(sparse.baseline.fixed_cases()[0])
    registry = PromptRegistry()
    ref = registry.lookup_for_evaluation(sparse.baseline.PROMPT_ID)
    with pytest.raises(PromptAssemblyError):
        assemble_prompt(ref, projected["input"], registry=registry, execution_scope=EVALUATION)
    fake_ollama_transport(
        monkeypatch, [{"effect_prohibitions": []}], model_id=sparse.baseline.MODEL_ID
    )
    row = candidate.run_candidate(projected, sparse.baseline.OllamaHTTPClient())
    assert row["final"]["structural_result"] == "PASS"
    assert row["final"]["owner_review"]["missing_prohibitions"] == ["CREATE"]
    assert row["normalized_prohibitions"] == []
    with pytest.raises(PromptAssemblyError):
        assemble_prompt(ref, projected["input"], registry=registry, execution_scope=EVALUATION)
    assert sparse.candidate_ref().input_schema_version == "2"


def test_first_and_repair_both_exclude_goal_but_normalizer_uses_original_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = sparse.baseline.fixed_cases()[0]
    projected = candidate.project_case(original)
    first = {"effect_prohibitions": [{"effect": "CREATE"}]}
    repaired = {"effect_prohibitions": [{"effect": "CREATE", "work_unit_ids": ["work-1"]}]}
    calls = fake_ollama_transport(monkeypatch, [first, repaired], model_id=sparse.baseline.MODEL_ID)
    seen_contexts: list[dict[str, Any]] = []
    normalize = candidate._SPARSE_NORMALIZE

    def inspect_context(value: object, case: dict[str, Any]) -> list[dict[str, Any]]:
        seen_contexts.append(deepcopy(case["input"]))
        return normalize(value, case)

    monkeypatch.setattr(candidate, "_SPARSE_NORMALIZE", inspect_context)
    row = candidate.run_candidate(projected, sparse.baseline.OllamaHTTPClient())
    assert row["candidate_id"] == candidate.CANDIDATE_ID
    assert row["metrics"]["calls"] == 2
    assert row["final"]["validated_output"] == repaired
    assert row["normalized_prohibitions"] == repaired["effect_prohibitions"]
    assert seen_contexts == [original["input"]]
    assert row["original_input_sha256"] == original["input_sha256"]
    assert row["input_sha256"] == projected["input_sha256"]
    for call in calls:
        payload = call["payload"]
        prompt = json.loads(payload["prompt"])
        actual = prompt["input"].get("base_projection", prompt["input"])
        assert actual == projected["input"]
        system_projection = json.loads(
            payload["system"]
            .split("Allowed current-Run input projection (JSON):\n")[1]
            .splitlines()[0]
        )
        assert system_projection == projected["input"]
        assert "goal_candidate" not in actual
        assert "normalization_goal_candidate" not in prompt["input"]
        assert payload["options"] == {"num_ctx": 16384, "seed": 20260923}
        assert payload["think"] is False
        assert payload["format"] == sparse.sparse_schema(original).json_schema
        assert "canonical_gold" not in payload["system"]


def test_tampered_external_goal_cannot_be_used_for_normalization() -> None:
    case = candidate.project_case(sparse.baseline.fixed_cases()[0])
    case["normalization_goal_candidate"]["goal"] = "invented Goal"
    with pytest.raises(ValueError, match="original frozen Goal"):
        candidate.restore_normalization_case(case)


@pytest.mark.parametrize("field", ["goal_candidate", "canonical_gold", "new_field"])
def test_injected_fields_are_rejected_even_with_recomputed_hash(field: str) -> None:
    case = candidate.project_case(sparse.baseline.fixed_cases()[0])
    case["input"][field] = {}
    case["input_sha256"] = object_hash(case["input"])
    with pytest.raises(ValueError, match="input contract"):
        candidate.restore_normalization_case(case)


def test_two_invalid_outputs_stop_without_model_input_changes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = candidate.project_case(sparse.baseline.fixed_cases()[0])
    fake_ollama_transport(monkeypatch, [{}, {}], model_id=sparse.baseline.MODEL_ID)
    row = candidate.run_candidate(case, sparse.baseline.OllamaHTTPClient())
    assert row["metrics"]["calls"] == 2
    assert row["final"]["structural_result"] == "FAIL"
    assert "normalized_prohibitions" not in row


def test_current_wire_cannot_reintroduce_goal_via_repair_base() -> None:
    original = sparse.baseline.fixed_cases()[0]
    case = candidate.project_case(original)
    invalid_repair = {
        "base_projection": original["input"],
        "candidate_output": {},
        "failure_record": {},
    }
    with pytest.raises(ValueError, match="actual inference input"):
        candidate.instruction(case, candidate.candidate_ref(), invalid_repair)
