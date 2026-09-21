from __future__ import annotations

from copy import deepcopy

import pytest
from evaluation.dataset_v8 import load_cases
from evaluation.requested_work_relation_candidate import (
    bind_full_request_controls,
    bind_relation_case,
    relation_decision_output_schema,
    relation_decision_pairs,
    relation_diagnostic_cases,
    relation_inference_required,
    relation_output_schema,
    relation_scores,
    semantic_input_sha256,
    validate_relation_candidate,
    validate_relation_decisions,
)

from google_work_agent.ports.llm.output_schema_validation import validate_output_schema


def _bound_cases() -> list[dict[str, object]]:
    canonical = load_cases()
    result = []
    for definition in relation_diagnostic_cases():
        request = str(canonical[definition["case_id"]].raw["canonical_user_prompt"])
        result.append(
            bind_relation_case(
                bind_full_request_controls(definition, user_request=request),
                user_request=request,
            )
        )
    return result


def test_diagnostic_set_uses_only_exact_core_request_spans() -> None:
    cases = _bound_cases()

    assert len(cases) == 8
    assert all(case["case_id"].startswith("CASE-CORE-") for case in cases)
    for case in cases:
        request = case["user_request"]
        for unit in case["work_units"]:
            assert request[unit["request_start"] : unit["request_end"]] == unit["request_excerpt"]


def test_single_work_unit_controls_skip_relation_inference() -> None:
    cases = _bound_cases()
    controls = [case for case in cases if len(case["work_units"]) == 1]

    assert [case["case_id"] for case in controls] == [
        "CASE-CORE-001",
        "CASE-CORE-041",
        "CASE-CORE-056",
    ]
    assert not any(relation_inference_required(case["work_units"]) for case in controls)


def test_relation_schema_closes_endpoints_and_kind() -> None:
    case = next(case for case in _bound_cases() if case["case_id"] == "CASE-CORE-046")
    schema = relation_output_schema(case["work_units"]).json_schema

    assert validate_output_schema(
        {
            "schema_version": 1,
            "work_relations": [
                {
                    "source_unit_id": "missing",
                    "target_unit_id": "draft",
                    "kind": "CONSUMES_PLANNED_SPECIFICATION",
                }
            ],
        },
        schema,
    )
    assert validate_output_schema(
        {
            "schema_version": 1,
            "work_relations": [
                {
                    "source_unit_id": "event",
                    "target_unit_id": "draft",
                    "kind": "PROVIDES_INPUT_TO",
                }
            ],
        },
        schema,
    )


def test_validator_rejects_self_relation_and_kind_conflicting_with_fixed_output() -> None:
    case = next(case for case in _bound_cases() if case["case_id"] == "CASE-CORE-046")
    self_relation = {
        "schema_version": 1,
        "work_relations": [
            {
                "source_unit_id": "event",
                "target_unit_id": "event",
                "kind": "CONSUMES_PLANNED_SPECIFICATION",
            }
        ],
    }
    wrong_kind = deepcopy(self_relation)
    wrong_kind["work_relations"][0] = {
        "source_unit_id": "event",
        "target_unit_id": "draft",
        "kind": "CONSUMES_WORK_PRODUCT",
    }

    with pytest.raises(ValueError, match="self relation"):
        validate_relation_candidate(
            self_relation,
            work_units=case["work_units"],
            semantic_items=case["semantic_items"],
        )
    with pytest.raises(ValueError, match="fixed output responsibility"):
        validate_relation_candidate(
            wrong_kind,
            work_units=case["work_units"],
            semantic_items=case["semantic_items"],
        )


def test_validator_does_not_mutate_fixed_semantic_input() -> None:
    case = next(case for case in _bound_cases() if case["case_id"] == "CASE-CORE-054")
    before = semantic_input_sha256(case)

    validated = validate_relation_candidate(
        {"schema_version": 1, "work_relations": case["expected_relations"]},
        work_units=case["work_units"],
        semantic_items=case["semantic_items"],
    )

    assert validated == case["expected_relations"]
    assert semantic_input_sha256(case) == before


def test_exhaustive_pair_decisions_close_none_and_fixed_relation_kind() -> None:
    case = next(case for case in _bound_cases() if case["case_id"] == "CASE-CORE-046")
    pairs = relation_decision_pairs(case["work_units"], semantic_items=case["semantic_items"])
    schema = relation_decision_output_schema(pairs).json_schema
    candidate = {
        "schema_version": 2,
        "relation_decisions": [
            {
                "source_unit_id": "event",
                "target_unit_id": "draft",
                "disposition": "CONSUMES_PLANNED_SPECIFICATION",
            },
            {
                "source_unit_id": "draft",
                "target_unit_id": "event",
                "disposition": "NONE",
            },
        ],
    }

    assert validate_output_schema(candidate, schema) == []
    assert validate_relation_decisions(candidate, pairs=pairs) == case["expected_relations"]


def test_exhaustive_pair_decisions_require_every_pair_and_reject_kind_rejudgment() -> None:
    case = next(case for case in _bound_cases() if case["case_id"] == "CASE-CORE-046")
    pairs = relation_decision_pairs(case["work_units"], semantic_items=case["semantic_items"])
    missing_pair = {
        "schema_version": 2,
        "relation_decisions": [
            {
                "source_unit_id": "event",
                "target_unit_id": "draft",
                "disposition": "NONE",
            }
        ],
    }
    wrong_kind = {
        "schema_version": 2,
        "relation_decisions": [
            {
                "source_unit_id": "event",
                "target_unit_id": "draft",
                "disposition": "CONSUMES_WORK_PRODUCT",
            },
            {
                "source_unit_id": "draft",
                "target_unit_id": "event",
                "disposition": "NONE",
            },
        ],
    }

    with pytest.raises(ValueError, match="cover every candidate pair"):
        validate_relation_decisions(missing_pair, pairs=pairs)
    with pytest.raises(ValueError, match="rejudges the fixed result kind"):
        validate_relation_decisions(wrong_kind, pairs=pairs)


def test_relation_scoring_counts_wrong_kind_as_false_positive_and_negative() -> None:
    expected = [
        {
            "source_unit_id": "event",
            "target_unit_id": "draft",
            "kind": "CONSUMES_PLANNED_SPECIFICATION",
        }
    ]
    actual = [
        {
            "source_unit_id": "event",
            "target_unit_id": "draft",
            "kind": "CONSUMES_WORK_PRODUCT",
        }
    ]

    score = relation_scores(expected, actual)

    assert score["true_positive"] == 0
    assert score["false_positive"] == 1
    assert score["false_negative"] == 1
    assert score["precision"] == 0.0
    assert score["recall"] == 0.0
