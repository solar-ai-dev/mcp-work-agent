from __future__ import annotations

import json
from collections import Counter
from typing import cast

from evaluation.dataset_v8 import load_cases
from scripts.evaluate_ru_requested_work_decomposition import (
    CORE24_EXPECTATIONS,
    DECOMPOSITION_SCHEMA,
    _validate_decomposition,
)


def test_core_projection_has_24_unique_core_cases() -> None:
    assert len(CORE24_EXPECTATIONS) == 24
    assert all(case_id.startswith("CASE-CORE-") for case_id in CORE24_EXPECTATIONS)


def test_core_projection_is_balanced_across_canonical_categories() -> None:
    cases = load_cases()
    categories = Counter(cases[case_id].raw["category"] for case_id in CORE24_EXPECTATIONS)
    assert len(categories) == 6
    assert set(categories.values()) == {4}
    assert sum(len(item.expected_units) == 1 for item in CORE24_EXPECTATIONS.values()) == 17
    assert sum(bool(item.expected_relations) for item in CORE24_EXPECTATIONS.values()) == 4


def test_candidate_schema_contains_only_requested_work_structure() -> None:
    encoded = json.dumps(DECOMPOSITION_SCHEMA.json_schema, sort_keys=True)
    properties = cast(dict[str, object], DECOMPOSITION_SCHEMA.json_schema["properties"])
    assert set(properties) == {
        "work_units",
        "work_relations",
    }
    for forbidden in (
        "resource_type",
        "effect",
        "tool",
        "query",
        "evidence",
        "product_ref",
        "approval",
        "execution",
    ):
        assert forbidden not in encoded.lower()


def test_decomposition_validator_accepts_minimal_acyclic_graph() -> None:
    assert not _validate_decomposition(
        {
            "work_units": [
                {"unit_id": "summary", "objective": "자료를 요약한다"},
                {"unit_id": "draft", "objective": "요약으로 문서 초안을 만든다"},
            ],
            "work_relations": [
                {
                    "source_unit_id": "summary",
                    "target_unit_id": "draft",
                    "kind": "PROVIDES_INPUT_TO",
                }
            ],
        }
    )


def test_decomposition_validator_rejects_invalid_semantic_graph_shape() -> None:
    errors = _validate_decomposition(
        {
            "work_units": [
                {"unit_id": "same", "objective": "첫 업무"},
                {"unit_id": "same", "objective": "둘째 업무"},
            ],
            "work_relations": [
                {
                    "source_unit_id": "missing",
                    "target_unit_id": "same",
                    "kind": "PROVIDES_INPUT_TO",
                }
            ],
        }
    )
    assert "work unit ids must be unique" in errors
    assert any("invalid endpoints" in error for error in errors)


def test_decomposition_validator_rejects_relation_cycle() -> None:
    errors = _validate_decomposition(
        {
            "work_units": [
                {"unit_id": "a", "objective": "첫 업무"},
                {"unit_id": "b", "objective": "둘째 업무"},
            ],
            "work_relations": [
                {"source_unit_id": "a", "target_unit_id": "b"},
                {"source_unit_id": "b", "target_unit_id": "a"},
            ],
        }
    )
    assert "work relations must be acyclic" in errors
