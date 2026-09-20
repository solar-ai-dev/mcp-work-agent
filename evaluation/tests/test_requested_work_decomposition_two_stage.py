from __future__ import annotations

import json
from pathlib import Path
from typing import cast

from scripts.evaluate_ru_requested_work_decomposition_two_stage import (
    IDENTIFIED_RESULTS_SCHEMA,
    IDENTIFY_PROMPT,
    MATERIALIZE_PROMPT,
    REQUESTED_EFFECTS,
    SEMANTIC_CARRY_DECOMPOSITION_SCHEMA,
    SEMANTIC_CARRY_IDENTIFIED_RESULTS_SCHEMA,
    SEMANTIC_CARRY_IDENTIFY_PROMPT,
    SEMANTIC_CARRY_RELATION_PROMPT,
    SEMANTIC_CARRY_RELATIONS_SCHEMA,
    SEMANTIC_STATE_DECOMPOSITION_SCHEMA,
    SEMANTIC_STATE_IDENTIFIED_RESULTS_SCHEMA,
    SEMANTIC_STATE_IDENTIFY_PROMPT,
    SEMANTIC_STATE_MATERIALIZE_PROMPT,
    _has_exact_carry,
    _project_identified_results,
    _validate_identified_results,
)


def test_stage_one_schema_contains_only_independent_results() -> None:
    properties = cast(dict[str, object], IDENTIFIED_RESULTS_SCHEMA.json_schema["properties"])
    encoded = json.dumps(IDENTIFIED_RESULTS_SCHEMA.json_schema, sort_keys=True)
    assert set(properties) == {"identified_results"}
    for forbidden in ("relation", "tool", "query", "evidence", "approval", "execution"):
        assert forbidden not in encoded.lower()


def test_two_stage_prompts_do_not_add_few_shots() -> None:
    for prompt in (
        IDENTIFY_PROMPT,
        MATERIALIZE_PROMPT,
        SEMANTIC_CARRY_IDENTIFY_PROMPT,
        SEMANTIC_CARRY_RELATION_PROMPT,
        SEMANTIC_STATE_IDENTIFY_PROMPT,
        SEMANTIC_STATE_MATERIALIZE_PROMPT,
    ):
        assert "few-shot" not in prompt.read_text(encoding="utf-8").lower()


def test_semantic_state_fields_are_optional_and_owner_local() -> None:
    result_item = SEMANTIC_STATE_IDENTIFIED_RESULTS_SCHEMA.json_schema["properties"][
        "identified_results"
    ]["items"]
    unit_item = SEMANTIC_STATE_DECOMPOSITION_SCHEMA.json_schema["properties"]["work_units"]["items"]
    expected_fields = {
        "source_scopes",
        "targets",
        "temporal_constraints",
        "quantity_constraints",
        "prohibitions",
        "requested_effects",
    }

    assert set(result_item["required"]) == {"result_id", "objective"}
    assert set(unit_item["required"]) == {"unit_id", "objective"}
    assert expected_fields == set(result_item["properties"]) - {"result_id", "objective"}
    assert expected_fields == set(unit_item["properties"]) - {"unit_id", "objective"}
    assert result_item["properties"]["requested_effects"]["items"]["enum"] == (REQUESTED_EFFECTS)
    encoded = json.dumps(result_item, sort_keys=True)
    for forbidden_bucket in ("metadata", "hints", "extra_context", "semantic_flags"):
        assert forbidden_bucket not in encoded


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


def test_semantic_carry_state_is_optional_and_effect_free() -> None:
    result_item = SEMANTIC_CARRY_IDENTIFIED_RESULTS_SCHEMA.json_schema["properties"][
        "identified_results"
    ]["items"]
    unit_item = SEMANTIC_CARRY_DECOMPOSITION_SCHEMA.json_schema["properties"]["work_units"]["items"]
    expected_fields = {
        "source_scopes",
        "targets",
        "temporal_constraints",
        "quantity_constraints",
        "prohibitions",
    }

    assert set(result_item["required"]) == {"result_id", "objective"}
    assert set(unit_item["required"]) == {"unit_id", "objective"}
    assert expected_fields == set(result_item["properties"]) - {"result_id", "objective"}
    assert expected_fields == set(unit_item["properties"]) - {"unit_id", "objective"}
    assert "requested_effects" not in json.dumps(
        SEMANTIC_CARRY_IDENTIFIED_RESULTS_SCHEMA.json_schema
    )
    assert "requested_effects" not in json.dumps(SEMANTIC_CARRY_DECOMPOSITION_SCHEMA.json_schema)


def test_semantic_carry_stage_two_only_generates_relations() -> None:
    properties = SEMANTIC_CARRY_RELATIONS_SCHEMA.json_schema["properties"]

    assert set(properties) == {"work_relations"}
    assert SEMANTIC_CARRY_RELATIONS_SCHEMA.json_schema["required"] == ["work_relations"]


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


def test_exact_carry_includes_optional_semantic_fields() -> None:
    identified = [
        {
            "result_id": "result-1",
            "objective": "초안을 준비한다",
            "source_scopes": ["Atlas 메일", "Atlas 작업"],
            "targets": ["qhdrbdhkdwks@naver.com"],
            "prohibitions": ["보내지 않는다"],
            "requested_effects": ["DRAFT"],
        }
    ]
    carried = [
        {
            "unit_id": "result-1",
            "objective": "초안을 준비한다",
            "source_scopes": ["Atlas 메일", "Atlas 작업"],
            "targets": ["qhdrbdhkdwks@naver.com"],
            "prohibitions": ["보내지 않는다"],
            "requested_effects": ["DRAFT"],
        }
    ]

    assert _has_exact_carry(identified, carried)
    carried[0]["prohibitions"] = []
    assert not _has_exact_carry(identified, carried)


def test_semantic_carry_projects_stage_one_without_llm_rewriting() -> None:
    identified = [
        {
            "result_id": "result-1",
            "objective": "선택한 자료를 요약한다",
            "source_scopes": ["선택한 메일"],
            "targets": ["사용자"],
            "temporal_constraints": ["오늘"],
            "quantity_constraints": ["하나"],
            "prohibitions": ["다른 메일을 검색하지 않는다"],
        }
    ]

    projected = _project_identified_results(identified)

    assert projected == [
        {
            "unit_id": "result-1",
            "objective": "선택한 자료를 요약한다",
            "source_scopes": ["선택한 메일"],
            "targets": ["사용자"],
            "temporal_constraints": ["오늘"],
            "quantity_constraints": ["하나"],
            "prohibitions": ["다른 메일을 검색하지 않는다"],
        }
    ]
    assert _has_exact_carry(identified, projected)
    assert "requested_effects" not in projected[0]


def test_prompt_paths_are_evaluation_candidates() -> None:
    expected_parent = Path(
        "evaluation/prompt_candidates/ru-requested-work-decomposition-two-stage-v1/sources"
    )
    assert IDENTIFY_PROMPT.parent == expected_parent
    assert MATERIALIZE_PROMPT.parent == expected_parent
    semantic_parent = Path(
        "evaluation/prompt_candidates/"
        "ru-requested-work-decomposition-two-stage-semantic-state-v1/sources"
    )
    assert SEMANTIC_STATE_IDENTIFY_PROMPT.parent == semantic_parent
    assert SEMANTIC_STATE_MATERIALIZE_PROMPT.parent == semantic_parent
    carry_parent = Path(
        "evaluation/prompt_candidates/"
        "ru-requested-work-decomposition-two-stage-semantic-carry-v2/sources"
    )
    assert SEMANTIC_CARRY_IDENTIFY_PROMPT.parent == carry_parent
    assert SEMANTIC_CARRY_RELATION_PROMPT.parent == carry_parent
