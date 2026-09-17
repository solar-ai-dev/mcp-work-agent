"""Deterministic grader for the frozen RU development dataset.

This module is intentionally separate from canonical grader_v8 and does not
import Product Runtime code. It only compares an evaluation observation with
the development Gold attached to the same dataset row.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Mapping, Sequence
from typing import Any

GRADER_VERSION = "ru-quality-dev-grader-v2"

_NON_SEMANTIC_FAILURE_CATEGORIES = frozenset(
    {"TIMEOUT", "PROVIDER_FAILURE", "RUNTIME_FAILURE", "RU_SCHEMA_CONTRACT"}
)
_KOREAN_SUFFIXES = (
    "으로부터",
    "로부터",
    "에서의",
    "에게서",
    "에서는",
    "하도록",
    "으로",
    "로서",
    "로써",
    "에서",
    "에게",
    "까지",
    "부터",
    "한다",
    "하다",
    "하여",
    "해서",
    "하고",
    "하며",
    "이며",
    "로",
    "와",
    "과",
    "을",
    "를",
    "은",
    "는",
    "이",
    "가",
    "의",
    "에",
    "함",
)


def grade_ru_case(
    case: Mapping[str, object], observation: Mapping[str, object]
) -> dict[str, object]:
    """Compare one RU observation with expected and forbidden Gold."""

    expected = _mapping(case.get("expected_typed_semantic_outcome"))
    forbidden = _mapping(case.get("forbidden_semantic_outcome"))
    typed_output = _mapping(observation.get("typed_ru_output"))
    raw_failure = observation.get("execution_failure")
    failure = _mapping(raw_failure) if isinstance(raw_failure, Mapping) else None
    failure_category = _string(failure.get("category")) if failure else None

    request_intent = _mapping(typed_output.get("request_intent"))
    goal_candidate = _mapping(typed_output.get("goal_candidate"))
    candidate = request_intent or goal_candidate or _partial_goal_candidate(observation)
    partial = bool(candidate) and not request_intent and not goal_candidate
    ambiguity = (
        _mapping(request_intent.get("ambiguity"))
        if request_intent
        else _mapping(typed_output.get("ambiguity_candidate"))
    )

    mismatches: list[dict[str, object]] = []
    if candidate:
        _compare_candidate(
            candidate=candidate,
            ambiguity=ambiguity,
            expected=expected,
            forbidden=forbidden,
            mismatches=mismatches,
            partial=partial,
        )

    goal_semantics_diagnostic = _goal_semantics_diagnostic(
        expected.get("goal_semantics"),
        candidate,
        partial=partial,
    )

    if failure_category == "RU_SEMANTIC_CONTRACT":
        mismatches.append(
            _mismatch(
                "validator.semantic_contract",
                "VALID",
                _string((failure or {}).get("reason_code"))
                or _string((failure or {}).get("type")),
                "SEMANTIC_CONTRACT_FAILURE",
            )
        )
    elif failure_category in _NON_SEMANTIC_FAILURE_CATEGORIES:
        mismatches.append(
            _mismatch(
                "execution",
                "COMPLETED_OR_SEMANTICALLY_JUDGABLE",
                failure_category,
                failure_category,
            )
        )
    elif candidate is None:
        mismatches.append(
            _mismatch(
                "typed_ru_output",
                "REQUEST_INTENT_OR_GOAL_CANDIDATE",
                None,
                "RU_TYPED_OUTPUT_MISSING",
            )
        )

    semantic_judgable = candidate is not None or failure_category == "RU_SEMANTIC_CONTRACT"
    if failure_category in _NON_SEMANTIC_FAILURE_CATEGORIES:
        semantic_judgable = False
    passed = not mismatches and failure is None
    cluster = None if passed else _failure_cluster(mismatches, failure or {})
    first_mismatch = mismatches[0] if mismatches else None
    forbidden_mismatches = [
        dict(item)
        for item in mismatches
        if (_string(item.get("path")) or "").startswith("forbidden.")
    ]
    return {
        "grader_version": GRADER_VERSION,
        "verdict": "PASS" if passed else "FAIL",
        "semantic_judgable": semantic_judgable,
        "first_semantic_mismatch": first_mismatch,
        "failure_cluster": cluster,
        "mismatch_count": len(mismatches),
        "mismatches": mismatches,
        "goal_semantics_scoring": "DIAGNOSTIC_ONLY_TYPED_FIELDS_PRIMARY",
        "goal_semantics_diagnostic": goal_semantics_diagnostic,
        "forbidden_semantic_outcome": {
            "violated": bool(forbidden_mismatches),
            "violation_count": len(forbidden_mismatches),
            "violations": forbidden_mismatches,
        },
        "forbidden_narrative_labels": list(_sequence(forbidden.get("semantic_failures"))),
        "forbidden_narrative_scoring": "TYPED_OUTCOME_RULES",
    }


def aggregate_ru_scores(results: Sequence[Mapping[str, object]]) -> dict[str, object]:
    """Aggregate strict, semantic, family, cluster, and runtime denominators."""

    total = len(results)
    strict_passed = sum(_verdict(item) == "PASS" for item in results)
    semantic = [item for item in results if _mapping(item.get("grade")).get("semantic_judgable")]
    semantic_passed = sum(_verdict(item) == "PASS" for item in semantic)

    families: dict[str, dict[str, object]] = {}
    for family in sorted({_string(item.get("semantic_family")) or "UNKNOWN" for item in results}):
        family_results = [
            item
            for item in results
            if (_string(item.get("semantic_family")) or "UNKNOWN") == family
        ]
        family_semantic = [
            item for item in family_results if _mapping(item.get("grade")).get("semantic_judgable")
        ]
        family_passed = sum(_verdict(item) == "PASS" for item in family_results)
        family_semantic_passed = sum(_verdict(item) == "PASS" for item in family_semantic)
        families[family] = {
            "strict": _score(family_passed, len(family_results)),
            "semantic": _score(family_semantic_passed, len(family_semantic)),
        }

    categories = Counter(
        _string(
            _mapping(_mapping(item.get("observation")).get("execution_failure")).get("category")
        )
        for item in results
    )
    clusters = Counter(
        _string(_mapping(item.get("grade")).get("failure_cluster"))
        for item in results
        if _verdict(item) == "FAIL"
    )
    return {
        "case_count": total,
        "strict_pass": _score(strict_passed, total),
        "semantic_pass": {
            **_score(semantic_passed, len(semantic)),
            "excluded_count": total - len(semantic),
        },
        "families": families,
        "failure_clusters": {
            key: value for key, value in sorted(clusters.items()) if key is not None
        },
        "execution_failures": {
            "semantic_contract": categories.get("RU_SEMANTIC_CONTRACT", 0),
            "schema_contract": categories.get("RU_SCHEMA_CONTRACT", 0),
            "timeout": categories.get("TIMEOUT", 0),
            "provider": categories.get("PROVIDER_FAILURE", 0),
            "runtime": categories.get("RUNTIME_FAILURE", 0),
        },
    }


def _compare_candidate(
    *,
    candidate: Mapping[str, object],
    ambiguity: Mapping[str, object],
    expected: Mapping[str, object],
    forbidden: Mapping[str, object],
    mismatches: list[dict[str, object]],
    partial: bool,
) -> None:
    _compare_scalar(
        "analysis_requirement",
        expected.get("analysis_requirement"),
        candidate.get("analysis_requirement"),
        mismatches,
    )
    if not partial or "requested_effect_hints" in candidate:
        _compare_set(
            "requested_effect_hints",
            expected.get("requested_effect_hints"),
            candidate.get("requested_effect_hints"),
            mismatches,
        )
    if not partial or "requested_resource_hints" in candidate:
        _compare_set(
            "requested_resource_hints",
            expected.get("requested_resource_hints"),
            candidate.get("requested_resource_hints"),
            mismatches,
        )
    _forbidden_intersection(
        "requested_effect_hints",
        forbidden.get("requested_effect_hints"),
        candidate.get("requested_effect_hints"),
        mismatches,
    )
    _forbidden_intersection(
        "requested_resource_hints",
        forbidden.get("requested_resource_hints"),
        candidate.get("requested_resource_hints"),
        mismatches,
    )

    if not partial:
        expected_roles = _mapping(expected.get("resource_responsibilities"))
        forbidden_roles = _mapping(forbidden.get("resource_responsibilities"))
        actual_roles = _mapping(candidate.get("resource_responsibilities"))
        expected_sources = {
            _string(_mapping(item).get("resource_type"))
            for item in _sequence(expected_roles.get("source_reads"))
        }
        actual_sources = {
            _string(_mapping(item).get("resource_type"))
            for item in _sequence(actual_roles.get("source_reads"))
        }
        if expected_sources != actual_sources:
            mismatches.append(
                _mismatch(
                    "resource_responsibilities.source_reads",
                    sorted(_without_none(expected_sources)),
                    sorted(_without_none(actual_sources)),
                    "EXPECTED_SET_MISMATCH",
                )
            )
        forbidden_sources = {
            _string(item) for item in _sequence(forbidden_roles.get("source_reads"))
        }
        forbidden_source_hits = _without_none(actual_sources & forbidden_sources)
        if forbidden_source_hits:
            mismatches.append(
                _mismatch(
                    "forbidden.resource_responsibilities.source_reads",
                    [],
                    sorted(forbidden_source_hits),
                    "FORBIDDEN_VALUE_PRESENT",
                )
            )
        _compare_required_information(
            expected_roles.get("source_reads"), actual_roles.get("source_reads"), mismatches
        )

        expected_outputs = _output_pairs(expected_roles.get("outputs"))
        actual_outputs = _output_pairs(actual_roles.get("outputs"))
        if expected_outputs != actual_outputs:
            mismatches.append(
                _mismatch(
                    "resource_responsibilities.outputs",
                    _sorted_pairs(expected_outputs),
                    _sorted_pairs(actual_outputs),
                    "EXPECTED_SET_MISMATCH",
                )
            )
        forbidden_output_hits = actual_outputs & _output_pairs(forbidden_roles.get("outputs"))
        if forbidden_output_hits:
            mismatches.append(
                _mismatch(
                    "forbidden.resource_responsibilities.outputs",
                    [],
                    _sorted_pairs(forbidden_output_hits),
                    "FORBIDDEN_VALUE_PRESENT",
                )
            )

        _compare_constraints(expected.get("constraints"), candidate.get("constraints"), mismatches)

    if ambiguity:
        expected_ambiguity = _mapping(expected.get("ambiguity"))
        _compare_scalar(
            "ambiguity.requires_confirmation",
            expected_ambiguity.get("requires_confirmation"),
            ambiguity.get("requires_confirmation"),
            mismatches,
        )
        _compare_set(
            "ambiguity.reason_codes",
            expected_ambiguity.get("reason_codes"),
            ambiguity.get("reason_codes"),
            mismatches,
        )
        _compare_set(
            "ambiguity.missing_fields",
            expected_ambiguity.get("missing_fields"),
            ambiguity.get("missing_fields"),
            mismatches,
        )
        if ambiguity.get("requires_confirmation") is forbidden.get(
            "ambiguity_requires_confirmation"
        ):
            mismatches.append(
                _mismatch(
                    "forbidden.ambiguity_requires_confirmation",
                    "NOT_PRESENT",
                    ambiguity.get("requires_confirmation"),
                    "FORBIDDEN_VALUE_PRESENT",
                )
            )
    elif not partial:
        mismatches.append(
            _mismatch("ambiguity", expected.get("ambiguity"), None, "EXPECTED_VALUE_MISSING")
        )


def _compare_required_information(
    expected_sources: object,
    actual_sources: object,
    mismatches: list[dict[str, object]],
) -> None:
    actual_by_type = {
        _string(_mapping(item).get("resource_type")): _sequence(
            _mapping(item).get("required_information")
        )
        for item in _sequence(actual_sources)
    }
    for raw_expected in _sequence(expected_sources):
        expected = _mapping(raw_expected)
        resource_type = _string(expected.get("resource_type"))
        if resource_type not in actual_by_type:
            continue
        actual = actual_by_type[resource_type]
        for requirement in _sequence(expected.get("required_information_semantics")):
            if not _semantic_match(requirement, actual):
                mismatches.append(
                    _mismatch(
                        f"resource_responsibilities.source_reads[{resource_type}].required_information",
                        requirement,
                        actual,
                        "SEMANTIC_REQUIREMENT_MISSING",
                    )
                )


def _compare_constraints(
    expected_constraints: object,
    actual_constraints: object,
    mismatches: list[dict[str, object]],
) -> None:
    actual = [_mapping(item) for item in _sequence(actual_constraints)]
    for raw_expected in _sequence(expected_constraints):
        expected = _mapping(raw_expected)
        matching = [
            item
            for item in actual
            if item.get("kind") == expected.get("kind")
            and item.get("field") == expected.get("field")
            and item.get("source_resource_type") == expected.get("source_resource_type")
        ]
        actual_values = [
            value for item in matching for value in _scalar_sequence(item.get("value"))
        ]
        missing = [
            value
            for value in _sequence(expected.get("value_semantics"))
            if not _semantic_match(value, actual_values)
        ]
        if missing:
            mismatches.append(
                _mismatch(
                    f"constraints[{expected.get('kind')}:{expected.get('field')}]",
                    list(_sequence(expected.get("value_semantics"))),
                    actual_values,
                    "SEMANTIC_SUBSET_MISMATCH",
                )
            )


def _goal_semantics_diagnostic(
    expected_goal_semantics: object,
    candidate: Mapping[str, object],
    *,
    partial: bool,
) -> dict[str, object]:
    required = list(_sequence(expected_goal_semantics))
    if not candidate or partial:
        return {
            "applicable": False,
            "required_count": len(required),
            "matched_count": 0,
            "unmatched": required,
        }
    actual_goal_text = [
        candidate.get("goal"),
        *_sequence(candidate.get("completion_conditions")),
    ]
    unmatched = [
        requirement
        for requirement in required
        if not _semantic_match(requirement, actual_goal_text)
    ]
    return {
        "applicable": True,
        "required_count": len(required),
        "matched_count": len(required) - len(unmatched),
        "unmatched": unmatched,
    }


def _partial_goal_candidate(observation: Mapping[str, object]) -> Mapping[str, object]:
    calls = _sequence(observation.get("provider_calls"))
    for raw_call in sorted(calls, key=lambda item: int(_mapping(item).get("sequence", 0))):
        call = _mapping(raw_call)
        prompt_ref = _mapping(call.get("prompt_ref"))
        if prompt_ref.get("prompt_id") == "request_understanding.identify_goal":
            return _mapping(call.get("typed_output"))
    return {}


def _failure_cluster(
    mismatches: Sequence[Mapping[str, object]], failure: Mapping[str, object]
) -> str:
    category = _string(failure.get("category"))
    if category == "RU_SEMANTIC_CONTRACT":
        return _string(failure.get("reason_code")) or "RU_SEMANTIC_CONTRACT"
    if category:
        return _string(failure.get("reason_code")) or category

    by_path = {_string(item.get("path")): item for item in mismatches}
    ambiguity = by_path.get("ambiguity.requires_confirmation")
    if ambiguity:
        return (
            "INTENT_OVER_CONFIRMATION"
            if ambiguity.get("actual") is True
            else "INTENT_AMBIGUITY_MISSED"
        )
    first_path = _string(mismatches[0].get("path")) if mismatches else None
    if first_path == "analysis_requirement":
        return "RU_ANALYSIS_REQUIREMENT_MISMATCH"
    if first_path and "requested_effect_hints" in first_path:
        return "RU_EFFECT_SET_MISMATCH"
    if first_path and "requested_resource_hints" in first_path:
        return "RU_RESOURCE_SET_MISMATCH"
    if first_path and "source_reads" in first_path:
        return "RU_SOURCE_RESPONSIBILITY_MISMATCH"
    if first_path and "outputs" in first_path:
        return "RU_OUTPUT_RESPONSIBILITY_MISMATCH"
    if first_path and first_path.startswith("constraints"):
        return "RU_CONSTRAINT_MISMATCH"
    if first_path == "goal_semantics":
        return "RU_GOAL_SEMANTICS_MISMATCH"
    return (
        _string(mismatches[0].get("kind")) or "RU_UNKNOWN_FAILURE"
        if mismatches
        else "RU_UNKNOWN_FAILURE"
    )


def _compare_scalar(
    path: str, expected: object, actual: object, mismatches: list[dict[str, object]]
) -> None:
    if expected != actual:
        mismatches.append(_mismatch(path, expected, actual, "EXPECTED_VALUE_MISMATCH"))


def _compare_set(
    path: str, expected: object, actual: object, mismatches: list[dict[str, object]]
) -> None:
    expected_set = {_string(item) for item in _sequence(expected)}
    actual_set = {_string(item) for item in _sequence(actual)}
    if expected_set != actual_set:
        mismatches.append(
            _mismatch(
                path,
                sorted(_without_none(expected_set)),
                sorted(_without_none(actual_set)),
                "EXPECTED_SET_MISMATCH",
            )
        )


def _forbidden_intersection(
    path: str, forbidden: object, actual: object, mismatches: list[dict[str, object]]
) -> None:
    hits = {_string(item) for item in _sequence(forbidden)} & {
        _string(item) for item in _sequence(actual)
    }
    if hits:
        mismatches.append(
            _mismatch(
                f"forbidden.{path}",
                [],
                sorted(_without_none(hits)),
                "FORBIDDEN_VALUE_PRESENT",
            )
        )


def _semantic_match(expected: object, actual_values: Sequence[object]) -> bool:
    if not isinstance(expected, str) or not expected.strip():
        return False
    actual_texts = [item for item in actual_values if isinstance(item, str) and item.strip()]
    expected_normalized = _normalized_text(expected)
    combined = " ".join(_normalized_text(item) for item in actual_texts)
    if expected_normalized in combined:
        return True
    expected_tokens = _semantic_tokens(expected)
    actual_tokens = set().union(*(_semantic_tokens(item) for item in actual_texts))
    if not expected_tokens:
        return False
    return len(expected_tokens & actual_tokens) / len(expected_tokens) >= 0.7


def _semantic_tokens(value: str) -> set[str]:
    tokens: set[str] = set()
    for raw in re.findall(r"[0-9a-z가-힣]+", value.casefold()):
        token = raw
        for suffix in _KOREAN_SUFFIXES:
            if token.endswith(suffix) and len(token) > len(suffix) + 1:
                token = token[: -len(suffix)]
                break
        if len(token) > 1:
            tokens.add(token)
    return tokens


def _normalized_text(value: str) -> str:
    return " ".join(re.findall(r"[0-9a-z가-힣]+", value.casefold()))


def _output_pairs(value: object) -> set[tuple[str, str]]:
    return {
        (resource_type, effect)
        for item in _sequence(value)
        if (mapping := _mapping(item))
        if (resource_type := _string(mapping.get("resource_type"))) is not None
        if (effect := _string(mapping.get("effect"))) is not None
    }


def _sorted_pairs(value: set[tuple[str, str]]) -> list[dict[str, str]]:
    return [
        {"resource_type": resource_type, "effect": effect}
        for resource_type, effect in sorted(value)
    ]


def _mismatch(path: str, expected: object, actual: object, kind: str) -> dict[str, object]:
    return {"path": path, "kind": kind, "expected": expected, "actual": actual}


def _score(passed: int, total: int) -> dict[str, object]:
    return {
        "passed": passed,
        "total": total,
        "rate": None if total == 0 else passed / total,
    }


def _verdict(result: Mapping[str, object]) -> str | None:
    return _string(_mapping(result.get("grade")).get("verdict"))


def _mapping(value: object) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _sequence(value: object) -> list[Any]:
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return list(value)
    return []


def _scalar_sequence(value: object) -> list[object]:
    return _sequence(value) if not isinstance(value, str) else [value]


def _string(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def _without_none(values: set[str | None]) -> set[str]:
    return {value for value in values if value is not None}


__all__ = ["GRADER_VERSION", "aggregate_ru_scores", "grade_ru_case"]
