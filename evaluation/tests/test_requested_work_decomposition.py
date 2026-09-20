from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import cast

from evaluation.dataset_v8 import load_cases
from scripts.evaluate_ru_requested_work_decomposition import (
    CORE24_CASE_IDS,
    COUNTED_DECOMPOSITION_SCHEMA,
    DECOMPOSITION_SCHEMA,
    _validate_decomposition,
)


def test_core_comparison_set_has_24_unique_core_cases() -> None:
    assert len(CORE24_CASE_IDS) == 24
    assert len(set(CORE24_CASE_IDS)) == 24
    assert all(case_id.startswith("CASE-CORE-") for case_id in CORE24_CASE_IDS)


def test_core_comparison_set_is_balanced_across_canonical_categories() -> None:
    cases = load_cases()
    categories = Counter(cases[case_id].raw["category"] for case_id in CORE24_CASE_IDS)
    assert len(categories) == 6
    assert set(categories.values()) == {4}
    for case_id in CORE24_CASE_IDS:
        gold = cases[case_id].raw["evaluation_gold"]
        assert gold["required_semantics"]
        assert gold["forbidden_semantics"]


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


def test_counted_candidate_adds_only_work_count() -> None:
    properties = cast(dict[str, object], COUNTED_DECOMPOSITION_SCHEMA.json_schema["properties"])
    assert set(properties) == {"work_count", "work_units", "work_relations"}
    assert COUNTED_DECOMPOSITION_SCHEMA.json_schema["required"] == [
        "work_count",
        "work_units",
        "work_relations",
    ]


def test_fewshot_candidate_keeps_minimal_v1_rules_unchanged() -> None:
    prompt_root = Path("evaluation/prompt_candidates")
    baseline = (
        prompt_root
        / "ru-requested-work-decomposition-v1"
        / "sources"
        / "request_understanding.decompose_requested_work.md"
    ).read_text(encoding="utf-8")
    candidate = (
        prompt_root
        / "ru-requested-work-decomposition-fewshot-v1"
        / "sources"
        / "request_understanding.decompose_requested_work.md"
    ).read_text(encoding="utf-8")

    assert candidate.startswith(baseline.rstrip() + "\n\n# Contrastive few-shot\n")


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


def test_counted_decomposition_requires_matching_unit_count() -> None:
    errors = _validate_decomposition(
        {
            "work_count": 1,
            "work_units": [
                {"unit_id": "a", "objective": "첫 업무"},
                {"unit_id": "b", "objective": "둘째 업무"},
            ],
            "work_relations": [],
        },
        require_work_count=True,
    )
    assert "work_count must match the number of work_units" in errors
