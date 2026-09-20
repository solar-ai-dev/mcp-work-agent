"""Compare RequestedWork semantic binding shapes without changing model prompts."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import cast

from evaluation.requested_work_binding_contract import (
    inline_round_trip_semantics,
    local_id_round_trip_semantics,
    normalized_decomposition,
    project_inline_work_unit_ids,
    project_local_id_bindings,
    representation_metrics,
    validate_inline_work_unit_ids,
    validate_local_id_bindings,
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-result", type=Path, required=True)
    parser.add_argument("--semantic-review", type=Path, required=True)
    parser.add_argument("--result-path", type=Path, required=True)
    arguments = parser.parse_args()
    if arguments.result_path.exists():
        raise ValueError("result path already exists; preserve every prior trial")

    source = _object(json.loads(arguments.source_result.read_text(encoding="utf-8")))
    review = _object(json.loads(arguments.semantic_review.read_text(encoding="utf-8")))
    reviewed_candidates = _object(review.get("candidates"), "review.candidates")
    reviewed_v3 = _object(reviewed_candidates.get("span_bound_v3"), "review.span_bound_v3")
    reviewed_source_path = Path(
        _string(reviewed_v3.get("path"), "review.candidates.span_bound_v3.path")
    )
    reviewed_source = _object(json.loads(reviewed_source_path.read_text(encoding="utf-8")))
    if _candidate_projection(source) != _candidate_projection(reviewed_source):
        raise ValueError("source candidate outputs differ from the reviewed v3 authority")
    cases = _object_list(source.get("cases"), "cases")
    review_cases = _object(review.get("cases"), "review.cases")
    severity = _object(review.get("issue_severity"), "review.issue_severity")

    aggregate = {
        "case_count": len(cases),
        "inline_valid": 0,
        "inline_binding_valid": 0,
        "local_id_valid": 0,
        "local_id_binding_valid": 0,
        "inline_round_trip_equal": 0,
        "local_id_round_trip_equal": 0,
        "raw_semantic_occurrences": 0,
        "inline_semantic_item_count": 0,
        "inline_work_unit_reference_count": 0,
        "local_id_semantic_item_count": 0,
        "local_id_binding_record_count": 0,
        "local_id_work_unit_reference_count": 0,
    }
    outcome_counts: Counter[str] = Counter()
    result_cases: list[dict[str, object]] = []
    for raw_case in cases:
        case_id = _string(raw_case.get("case_id"), "case_id")
        user_request = _string(raw_case.get("user_request"), f"{case_id}.user_request")
        materialize = _object(raw_case.get("materialize"), f"{case_id}.materialize")
        decomposition = _object(materialize.get("candidate"), f"{case_id}.materialize.candidate")
        inline = project_inline_work_unit_ids(decomposition)
        local_id = project_local_id_bindings(decomposition)
        inline_errors = validate_inline_work_unit_ids(inline, user_request=user_request)
        local_id_errors = validate_local_id_bindings(local_id, user_request=user_request)
        inline_binding_errors = _without_inherited_span_errors(inline_errors)
        local_id_binding_errors = _without_inherited_span_errors(local_id_errors)
        normalized = normalized_decomposition(decomposition)
        inline_equal = inline_round_trip_semantics(inline) == normalized
        local_id_equal = local_id_round_trip_semantics(local_id) == normalized
        inline_metrics = representation_metrics(inline)
        local_id_metrics = representation_metrics(local_id)
        raw_occurrences = sum(
            len(value)
            for unit in cast(list[dict[str, object]], decomposition.get("work_units", []))
            for key, value in unit.items()
            if key
            in {
                "source_scopes",
                "targets",
                "temporal_constraints",
                "quantity_constraints",
                "prohibitions",
            }
            and isinstance(value, list)
        )

        case_review = _object(review_cases.get(case_id), f"review.cases.{case_id}")
        reviews = _object(case_review.get("reviews"), f"review.cases.{case_id}.reviews")
        v3_review = _object(reviews.get("span_bound_v3"), f"{case_id}.span_bound_v3")
        issues = [_string(item, f"{case_id}.issues") for item in _list(v3_review.get("issues"))]
        outcome = _outcome(issues, severity)
        outcome_counts[outcome] += 1

        aggregate["inline_valid"] += int(not inline_errors)
        aggregate["inline_binding_valid"] += int(not inline_binding_errors)
        aggregate["local_id_valid"] += int(not local_id_errors)
        aggregate["local_id_binding_valid"] += int(not local_id_binding_errors)
        aggregate["inline_round_trip_equal"] += int(inline_equal)
        aggregate["local_id_round_trip_equal"] += int(local_id_equal)
        aggregate["raw_semantic_occurrences"] += raw_occurrences
        aggregate["inline_semantic_item_count"] += inline_metrics["semantic_item_count"]
        aggregate["inline_work_unit_reference_count"] += inline_metrics["work_unit_reference_count"]
        aggregate["local_id_semantic_item_count"] += local_id_metrics["semantic_item_count"]
        aggregate["local_id_binding_record_count"] += local_id_metrics["binding_record_count"]
        aggregate["local_id_work_unit_reference_count"] += local_id_metrics[
            "work_unit_reference_count"
        ]
        result_cases.append(
            {
                "case_id": case_id,
                "semantic_outcome": outcome,
                "inline": {
                    "valid": not inline_errors,
                    "errors": inline_errors,
                    "binding_valid": not inline_binding_errors,
                    "binding_errors": inline_binding_errors,
                    "round_trip_equal": inline_equal,
                    "metrics": inline_metrics,
                },
                "local_id_binding": {
                    "valid": not local_id_errors,
                    "errors": local_id_errors,
                    "binding_valid": not local_id_binding_errors,
                    "binding_errors": local_id_binding_errors,
                    "round_trip_equal": local_id_equal,
                    "metrics": local_id_metrics,
                },
            }
        )

    result = {
        "version": "ru288-requested-work-binding-contract-v1",
        "scope": "EVALUATION_ONLY_CONTRACT_PROJECTION",
        "source": {
            "result_path": arguments.source_result.as_posix(),
            "result_sha256": _sha256(arguments.source_result),
            "semantic_review_path": arguments.semantic_review.as_posix(),
            "semantic_review_sha256": _sha256(arguments.semantic_review),
            "reviewed_source_path": reviewed_source_path.as_posix(),
            "reviewed_source_sha256": _sha256(reviewed_source_path),
            "candidate_outputs_match_reviewed_source": True,
            "prompt_change": False,
            "model_call_count": 0,
        },
        "semantic_outcomes_unchanged": dict(sorted(outcome_counts.items())),
        "summary": aggregate,
        "decision": {
            "selected": "SEMANTIC_ITEM_OWNS_WORK_UNIT_IDS",
            "rejected": "STABLE_LOCAL_ID_WITH_SEPARATE_BINDING_TABLE",
            "reason_codes": [
                "FEWER_REFERENCE_LAYERS",
                "NO_NEW_BINDING_OWNER",
                "NO_STALE_SEMANTIC_LOCAL_ID",
                "OWNER_LOCAL_APPLICABILITY",
            ],
            "known_migration_risk": (
                "Current SourceResponsibility and OutputResponsibility validation aggregates "
                "by resource_type; same-resource/effect work multiplicity needs a V3 owner "
                "contract decision before production implementation."
            ),
        },
        "cases": result_cases,
    }
    arguments.result_path.parent.mkdir(parents=True, exist_ok=True)
    arguments.result_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _outcome(issues: list[str], severity: dict[str, object]) -> str:
    levels = [str(severity.get(issue, "PARTIAL")) for issue in issues]
    if "FAIL" in levels:
        return "FAIL"
    if "PARTIAL" in levels:
        return "PARTIAL"
    return "PASS"


def _candidate_projection(result: dict[str, object]) -> list[dict[str, object]]:
    projected = []
    for case in _object_list(result.get("cases"), "cases"):
        identify = _object(case.get("identify"), "case.identify")
        materialize = _object(case.get("materialize"), "case.materialize")
        projected.append(
            {
                "case_id": case.get("case_id"),
                "identify": identify.get("candidate"),
                "materialize": materialize.get("candidate"),
            }
        )
    return projected


def _without_inherited_span_errors(errors: list[str]) -> list[str]:
    return [error for error in errors if "non-verbatim request span" not in error]


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _object(value: object, path: str = "root") -> dict[str, object]:
    if not isinstance(value, dict):
        raise TypeError(f"{path} must be an object")
    return value


def _object_list(value: object, path: str) -> list[dict[str, object]]:
    if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
        raise TypeError(f"{path} must be an object list")
    return value


def _list(value: object) -> list[object]:
    if not isinstance(value, list):
        raise TypeError("value must be a list")
    return value


def _string(value: object, path: str) -> str:
    if not isinstance(value, str) or not value:
        raise TypeError(f"{path} must be a non-empty string")
    return value


if __name__ == "__main__":
    main()
