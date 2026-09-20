from __future__ import annotations

import json
from pathlib import Path
from typing import cast

from scripts.evaluate_ru_requested_work_decomposition_two_stage import (
    IDENTIFIED_RESULTS_SCHEMA,
    IDENTIFY_PROMPT,
    MATERIALIZE_PROMPT,
    _first_divergence,
    _has_exact_carry,
    _validate_identified_results,
)


def test_stage_one_schema_contains_only_independent_results() -> None:
    properties = cast(
        dict[str, object], IDENTIFIED_RESULTS_SCHEMA.json_schema["properties"]
    )
    encoded = json.dumps(IDENTIFIED_RESULTS_SCHEMA.json_schema, sort_keys=True)
    assert set(properties) == {"identified_results"}
    for forbidden in ("relation", "tool", "query", "evidence", "approval", "execution"):
        assert forbidden not in encoded.lower()


def test_two_stage_prompts_do_not_add_few_shots() -> None:
    assert "few-shot" not in IDENTIFY_PROMPT.read_text(encoding="utf-8").lower()
    assert "few-shot" not in MATERIALIZE_PROMPT.read_text(encoding="utf-8").lower()


def test_stage_one_validator_rejects_duplicate_result_ids() -> None:
    errors = _validate_identified_results(
        {
            "identified_results": [
                {"result_id": "same", "objective": "첫 결과"},
                {"result_id": "same", "objective": "둘째 결과"},
            ]
        }
    )
    assert errors == ["identified result ids must be unique"]


def test_exact_carry_requires_ids_and_objectives_to_be_unchanged() -> None:
    identified = [
        {"result_id": "result-1", "objective": "첫 결과"},
        {"result_id": "result-2", "objective": "둘째 결과"},
    ]
    assert _has_exact_carry(
        identified,
        [
            {"unit_id": "result-1", "objective": "첫 결과"},
            {"unit_id": "result-2", "objective": "둘째 결과"},
        ],
    )
    assert not _has_exact_carry(
        identified,
        [{"unit_id": "result-1", "objective": "다르게 쓴 결과"}],
    )


def test_first_divergence_prefers_stage_one_boundary_before_relation() -> None:
    assert (
        _first_divergence(
            identify_errors=[],
            identify_boundary_matches=False,
            materialize_errors=[],
            carry_matches=True,
            actual_relation_count=0,
            expected_relation_count=1,
        )
        == "STAGE1_RESULT_BOUNDARY"
    )


def test_prompt_paths_are_evaluation_candidates() -> None:
    expected_parent = Path(
        "evaluation/prompt_candidates/ru-requested-work-decomposition-two-stage-v1/sources"
    )
    assert IDENTIFY_PROMPT.parent == expected_parent
    assert MATERIALIZE_PROMPT.parent == expected_parent
