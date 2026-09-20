from __future__ import annotations

import json
from pathlib import Path

import pytest
from scripts.regrade_ru_requested_work_decomposition import (
    DEFAULT_REVIEW,
    _status_for_issues,
    regrade,
)

SEMANTIC_STATE_REVIEW = Path(
    "evaluation/experiments/051-requested-work-semantic-state-review-v1.json"
)


def test_semantic_review_regrades_all_existing_outputs_without_exact_shape_gold() -> None:
    review = json.loads(DEFAULT_REVIEW.read_text(encoding="utf-8"))

    result = regrade(review, repository_root=Path.cwd())

    assert result["binding"]["llm_calls"] == 0
    assert result["binding"]["case_count"] == 24
    assert len(result["cases"]) == 24
    assert review["authority"]["exact_work_unit_count_is_authority"] is False
    assert review["authority"]["exact_relation_count_is_authority"] is False
    assert review["authority"]["alternative_decompositions_are_allowed"] is True
    assert set(result["summary"]) == {
        "minimal_v1",
        "counted_v1",
        "fewshot_v1",
        "two_stage_v1",
    }
    for summary in result["summary"].values():
        assert summary["PASS"] + summary["PARTIAL"] + summary["FAIL"] == 24


def test_semantic_review_distinguishes_relation_meanings() -> None:
    review = json.loads(DEFAULT_REVIEW.read_text(encoding="utf-8"))
    semantics = review["relation_semantics"]

    assert semantics["internal_derived_product"] == "CONSUMES_WORK_PRODUCT"
    assert semantics["preapproval_external_action"] == "CONSUMES_PLANNED_SPECIFICATION"
    assert semantics["legacy_provides_input_to_is_typed"] is False
    assert review["cases"]["CASE-CORE-019"]["relation_authority"] == (
        "CONSUMES_PLANNED_SPECIFICATION"
    )
    assert review["cases"]["CASE-CORE-046"]["relation_authority"] == (
        "CONSUMES_PLANNED_SPECIFICATION"
    )


def test_semantic_review_accepts_alternative_shapes_for_single_user_result() -> None:
    review = json.loads(DEFAULT_REVIEW.read_text(encoding="utf-8"))

    assert len(review["cases"]["CASE-CORE-054"]["allowed_shapes"]) == 2
    assert len(review["cases"]["CASE-CORE-056"]["allowed_shapes"]) == 2
    assert len(review["cases"]["CASE-CORE-059"]["allowed_shapes"]) == 2


def test_semantic_review_rejects_raw_result_drift() -> None:
    review = json.loads(DEFAULT_REVIEW.read_text(encoding="utf-8"))
    review["candidates"]["minimal_v1"]["sha256"] = "0" * 64

    with pytest.raises(ValueError, match="raw result SHA-256 mismatch"):
        regrade(review, repository_root=Path.cwd())


def test_issue_severity_controls_status_without_count_comparison() -> None:
    severity = {
        "boundary": "PARTIAL",
        "fatal": "FAIL",
        "alternative": "INFO",
    }

    assert _status_for_issues([], severity) == "PASS"
    assert _status_for_issues(["alternative"], severity) == "PASS"
    assert _status_for_issues(["boundary"], severity) == "PARTIAL"
    assert _status_for_issues(["boundary", "fatal"], severity) == "FAIL"


def test_semantic_state_review_compares_fixed_core24_without_new_model_calls() -> None:
    review = json.loads(SEMANTIC_STATE_REVIEW.read_text(encoding="utf-8"))

    result = regrade(review, repository_root=Path.cwd())

    assert result["binding"]["llm_calls"] == 0
    assert result["binding"]["case_count"] == 24
    assert set(result["summary"]) == {
        "minimal_v1",
        "two_stage_v1",
        "semantic_state_v1",
    }
    assert result["summary"]["semantic_state_v1"] == {
        "PASS": 7,
        "PARTIAL": 9,
        "FAIL": 8,
        "decision": "REJECT",
        "issue_counts": {
            "EFFECT_CHANGED": 6,
            "EXPLICIT_PROHIBITION_DROPPED": 3,
            "FACT_OVERCLAIMED": 2,
            "INTERNAL_STEP_PROMOTED": 1,
            "PLANNED_EFFECT_STATUS_AMBIGUOUS": 1,
            "RELATION_MISSING": 2,
            "RELATION_UNTYPED": 1,
            "REQUESTED_OUTCOME_MISSING": 2,
            "SOURCE_SCOPE_DROPPED": 3,
            "TEMPORAL_CONSTRAINT_DROPPED": 1,
            "TYPED_SEMANTIC_CARRY_DROPPED": 14,
        },
    }
