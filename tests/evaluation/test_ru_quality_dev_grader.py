from __future__ import annotations

from copy import deepcopy
from typing import Any, cast

from evaluation.ru_quality_dev_grader import aggregate_ru_scores, grade_ru_case


def _case() -> dict[str, Any]:
    return {
        "case_id": "RU-X-001",
        "semantic_family": "TEST_FAMILY",
        "expected_typed_semantic_outcome": {
            "goal_semantics": ["Marigold mail summary"],
            "requested_effect_hints": ["READ"],
            "requested_resource_hints": ["GMAIL_THREAD"],
            "resource_responsibilities": {
                "source_reads": [
                    {
                        "resource_type": "GMAIL_THREAD",
                        "required_information_semantics": ["thread identity"],
                    }
                ],
                "outputs": [],
            },
            "analysis_requirement": "NONE",
            "ambiguity": {
                "requires_confirmation": False,
                "reason_codes": [],
                "missing_fields": [],
            },
            "constraints": [
                {
                    "kind": "USER_REQUIREMENT",
                    "field": "search_terms",
                    "value_semantics": ["Marigold"],
                }
            ],
        },
        "forbidden_semantic_outcome": {
            "requested_effect_hints": ["CREATE", "UPDATE", "SEND", "DELETE"],
            "requested_resource_hints": ["GMAIL_DRAFT"],
            "resource_responsibilities": {
                "source_reads": [],
                "outputs": [{"resource_type": "GMAIL_DRAFT", "effect": "CREATE"}],
            },
            "ambiguity_requires_confirmation": True,
            "semantic_failures": ["invented draft"],
        },
    }


def _observation() -> dict[str, Any]:
    return {
        "typed_ru_output": {
            "request_intent": {
                "goal": "Marigold mail summary",
                "completion_conditions": ["thread identity summarized"],
                "constraints": [
                    {
                        "kind": "USER_REQUIREMENT",
                        "field": "search_terms",
                        "value": ["Marigold"],
                    }
                ],
                "requested_effect_hints": ["READ"],
                "requested_resource_hints": ["GMAIL_THREAD"],
                "resource_responsibilities": {
                    "source_reads": [
                        {
                            "resource_type": "GMAIL_THREAD",
                            "required_information": ["thread identity"],
                        }
                    ],
                    "outputs": [],
                },
                "analysis_requirement": "NONE",
                "ambiguity": {
                    "requires_confirmation": False,
                    "reason_codes": [],
                    "missing_fields": [],
                },
            },
            "goal_candidate": None,
            "ambiguity_candidate": None,
        },
        "provider_calls": [],
        "execution_failure": None,
    }


def test_grader_passes_matching_typed_intent() -> None:
    grade = grade_ru_case(_case(), _observation())

    assert grade["verdict"] == "PASS"
    assert grade["semantic_judgable"] is True
    assert grade["first_semantic_mismatch"] is None
    assert grade["failure_cluster"] is None


def test_goal_semantics_is_diagnostic_when_typed_contract_matches() -> None:
    case = _case()
    case["expected_typed_semantic_outcome"]["goal_semantics"] = [
        "Vega 일정과 Marigold 메일을 근거로 후속 Task 생성"
    ]
    observation = _observation()
    observation["typed_ru_output"]["request_intent"]["goal"] = "unrelated wording"

    grade = grade_ru_case(case, observation)

    assert grade["verdict"] == "PASS"
    assert grade["goal_semantics_scoring"] == "DIAGNOSTIC_ONLY_TYPED_FIELDS_PRIMARY"
    assert grade["goal_semantics_diagnostic"] == {
        "applicable": True,
        "required_count": 1,
        "matched_count": 0,
        "unmatched": ["Vega 일정과 Marigold 메일을 근거로 후속 Task 생성"],
    }


def test_forbidden_typed_outcome_is_explicitly_judged() -> None:
    observation = _observation()
    intent = observation["typed_ru_output"]["request_intent"]
    intent["requested_effect_hints"] = ["READ", "CREATE"]
    intent["requested_resource_hints"] = ["GMAIL_THREAD", "GMAIL_DRAFT"]
    intent["resource_responsibilities"]["outputs"] = [
        {"resource_type": "GMAIL_DRAFT", "effect": "CREATE"}
    ]

    grade = grade_ru_case(_case(), observation)
    forbidden = cast(dict[str, Any], grade["forbidden_semantic_outcome"])

    assert grade["verdict"] == "FAIL"
    assert forbidden["violated"] is True
    assert {
        mismatch["path"]
        for mismatch in cast(list[dict[str, Any]], forbidden["violations"])
    } == {
        "forbidden.requested_effect_hints",
        "forbidden.requested_resource_hints",
        "forbidden.resource_responsibilities.outputs",
    }
    assert grade["forbidden_narrative_scoring"] == "TYPED_OUTCOME_RULES"


def test_grader_clusters_over_confirmation_without_case_hardcoding() -> None:
    observation = _observation()
    intent = observation["typed_ru_output"]["request_intent"]
    intent["ambiguity"] = {
        "requires_confirmation": True,
        "reason_codes": ["RESOURCE_IDENTITY_MISSING"],
        "missing_fields": ["thread_identity"],
    }

    grade = grade_ru_case(_case(), observation)

    assert grade["verdict"] == "FAIL"
    assert grade["failure_cluster"] == "INTENT_OVER_CONFIRMATION"
    assert any(
        mismatch["path"] == "ambiguity.requires_confirmation"
        for mismatch in cast(list[dict[str, Any]], grade["mismatches"])
    )


def test_semantic_validator_exception_is_judged_not_counted_as_runtime() -> None:
    observation = {
        "typed_ru_output": {
            "request_intent": None,
            "goal_candidate": None,
            "ambiguity_candidate": None,
        },
        "provider_calls": [
            {
                "sequence": 0,
                "prompt_ref": {"prompt_id": "request_understanding.identify_goal"},
                "typed_output": {
                    "analysis_requirement": "REQUIRED",
                    "requested_effect_hints": ["READ"],
                    "requested_resource_hints": ["GMAIL_THREAD"],
                },
            }
        ],
        "execution_failure": {
            "category": "RU_SEMANTIC_CONTRACT",
            "type": "RequestGoalSemanticValidationError",
            "reason_code": "REQUEST_STATUS_PROVENANCE_MISMATCH",
        },
    }
    case = _case()
    case["expected_typed_semantic_outcome"]["analysis_requirement"] = "REQUIRED"

    grade = grade_ru_case(case, observation)
    result = {
        "semantic_family": case["semantic_family"],
        "observation": observation,
        "grade": grade,
    }
    aggregate = aggregate_ru_scores([result])

    assert grade["verdict"] == "FAIL"
    assert grade["semantic_judgable"] is True
    assert grade["failure_cluster"] == "REQUEST_STATUS_PROVENANCE_MISMATCH"
    assert aggregate["semantic_pass"] == {
        "passed": 0,
        "total": 1,
        "rate": 0.0,
        "excluded_count": 0,
    }
    assert aggregate["execution_failures"] == {
        "semantic_contract": 1,
        "schema_contract": 0,
        "timeout": 0,
        "provider": 0,
        "runtime": 0,
    }


def test_partial_goal_output_only_scores_fields_that_are_present() -> None:
    observation = {
        "typed_ru_output": {
            "request_intent": None,
            "goal_candidate": None,
            "ambiguity_candidate": None,
        },
        "provider_calls": [
            {
                "sequence": 0,
                "prompt_ref": {"prompt_id": "request_understanding.identify_goal"},
                "typed_output": {
                    "goal": "Marigold mail summary",
                    "completion_conditions": [],
                    "constraints": {},
                    "analysis_requirement": "NONE",
                },
            }
        ],
        "execution_failure": {
            "category": "RU_SEMANTIC_CONTRACT",
            "type": "RequestGoalSemanticValidationError",
            "reason_code": "REQUEST_STATUS_PROVENANCE_MISMATCH",
        },
    }

    grade = grade_ru_case(_case(), observation)

    assert grade["mismatches"] == [
        {
            "path": "validator.semantic_contract",
            "kind": "SEMANTIC_CONTRACT_FAILURE",
            "expected": "VALID",
            "actual": "REQUEST_STATUS_PROVENANCE_MISMATCH",
        }
    ]
    first_mismatch = cast(dict[str, Any], grade["first_semantic_mismatch"])
    assert first_mismatch["path"] == "validator.semantic_contract"


def test_aggregate_keeps_runtime_failures_out_of_semantic_denominator() -> None:
    semantic_observation = _observation()
    semantic_observation["typed_ru_output"]["request_intent"]["analysis_requirement"] = "REQUIRED"
    semantic_grade = grade_ru_case(_case(), semantic_observation)
    runtime_observation = deepcopy(_observation())
    runtime_observation["typed_ru_output"] = {
        "request_intent": None,
        "goal_candidate": None,
        "ambiguity_candidate": None,
    }
    runtime_observation["execution_failure"] = {
        "category": "TIMEOUT",
        "reason_code": "PROVIDER_TIMEOUT",
    }
    runtime_grade = grade_ru_case(_case(), runtime_observation)

    aggregate = aggregate_ru_scores(
        [
            {
                "semantic_family": "TEST_FAMILY",
                "observation": semantic_observation,
                "grade": semantic_grade,
            },
            {
                "semantic_family": "TEST_FAMILY",
                "observation": runtime_observation,
                "grade": runtime_grade,
            },
        ]
    )

    assert aggregate["strict_pass"] == {"passed": 0, "total": 2, "rate": 0.0}
    assert aggregate["semantic_pass"] == {
        "passed": 0,
        "total": 1,
        "rate": 0.0,
        "excluded_count": 1,
    }
    execution_failures = cast(dict[str, Any], aggregate["execution_failures"])
    assert execution_failures["timeout"] == 1
