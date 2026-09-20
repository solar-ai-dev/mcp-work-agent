"""Regrade existing #287 decomposition outputs against Canonical meaning.

The review accepts alternative decompositions.  It never treats an exact
WorkUnit or WorkRelation count as semantic authority and performs no LLM or
Provider call.
"""

from __future__ import annotations

import hashlib
import json
from argparse import ArgumentParser
from collections import Counter
from pathlib import Path
from typing import cast

from evaluation.dataset_v8 import load_cases, normalized_sha256
from scripts.evaluate_ru_requested_work_decomposition import (
    CORE24_CASE_IDS,
    DATASET,
    _git_head,
    _write,
)

DEFAULT_REVIEW = Path("evaluation/experiments/050-requested-work-semantic-review-v1.json")
STATUS_RANK = {"INFO": 0, "PARTIAL": 1, "FAIL": 2}


def main() -> None:
    parser = ArgumentParser()
    parser.add_argument("--review-path", type=Path, default=DEFAULT_REVIEW)
    parser.add_argument("--result-path", type=Path, required=True)
    arguments = parser.parse_args()
    if arguments.result_path.exists():
        raise ValueError("result path already exists; preserve every prior review")

    review = json.loads(arguments.review_path.read_text(encoding="utf-8"))
    result = regrade(review, repository_root=Path.cwd())
    _write(arguments.result_path, result)
    print(json.dumps(result["summary"], ensure_ascii=False, indent=2))


def regrade(review: object, *, repository_root: Path) -> dict[str, object]:
    if not isinstance(review, dict):
        raise ValueError("review must be an object")
    authority = _mapping(review, "authority")
    if authority.get("exact_work_unit_count_is_authority") is not False:
        raise ValueError("exact WorkUnit count must not be evaluation authority")
    if authority.get("exact_relation_count_is_authority") is not False:
        raise ValueError("exact relation count must not be evaluation authority")
    if authority.get("alternative_decompositions_are_allowed") is not True:
        raise ValueError("alternative meaning-preserving decompositions must be allowed")

    issue_severity = {
        str(key): str(value) for key, value in _mapping(review, "issue_severity").items()
    }
    if any(severity not in STATUS_RANK for severity in issue_severity.values()):
        raise ValueError("issue severity must be INFO, PARTIAL, or FAIL")

    candidates = _mapping(review, "candidates")
    decisions = _mapping(review, "decisions")
    review_cases = _mapping(review, "cases")
    expected_case_ids = set(CORE24_CASE_IDS)
    if set(review_cases) != expected_case_ids:
        raise ValueError("review must cover the fixed Core 24 exactly once")
    if set(decisions) != set(candidates):
        raise ValueError("every candidate needs one decision")
    if any(value not in {"ADOPT", "REJECT", "HOLD"} for value in decisions.values()):
        raise ValueError("candidate decision must be ADOPT, REJECT, or HOLD")

    canonical_cases = load_cases()
    raw_candidates: dict[str, dict[str, dict[str, object]]] = {}
    raw_hashes: dict[str, str] = {}
    raw_bindings: dict[str, object] = {}
    for candidate_id, binding_value in candidates.items():
        if not isinstance(binding_value, dict):
            raise ValueError(f"{candidate_id}: candidate binding must be an object")
        relative_path = Path(str(binding_value["path"]))
        raw_path = repository_root / relative_path
        raw_bytes = raw_path.read_bytes()
        actual_hash = hashlib.sha256(raw_bytes).hexdigest()
        expected_hash = str(binding_value["sha256"])
        if actual_hash != expected_hash:
            raise ValueError(f"{candidate_id}: raw result SHA-256 mismatch")
        raw_hashes[candidate_id] = actual_hash
        raw_result = json.loads(raw_bytes.decode("utf-8"))
        raw_binding = raw_result.get("binding")
        if not isinstance(raw_binding, dict):
            raise ValueError(f"{candidate_id}: raw result binding is missing")
        if raw_binding.get("dataset_sha256") != normalized_sha256(DATASET):
            raise ValueError(f"{candidate_id}: raw result dataset binding drifted")
        raw_bindings[candidate_id] = raw_binding
        records = cast(list[dict[str, object]], raw_result["cases"])
        by_case = {str(record["case_id"]): record for record in records}
        if set(by_case) != expected_case_ids or len(records) != len(expected_case_ids):
            raise ValueError(f"{candidate_id}: raw result must contain Core 24 exactly once")
        raw_candidates[candidate_id] = by_case

    summaries: dict[str, dict[str, object]] = {
        candidate_id: {
            "PASS": 0,
            "PARTIAL": 0,
            "FAIL": 0,
            "decision": decisions[candidate_id],
            "issue_counts": {},
        }
        for candidate_id in candidates
    }
    output_cases: list[dict[str, object]] = []

    for case_id in CORE24_CASE_IDS:
        canonical = canonical_cases[case_id].raw
        if canonical.get("split") != "CORE":
            raise ValueError(f"{case_id}: comparison set contains a non-Core Case")
        canonical_prompt = str(canonical["canonical_user_prompt"])
        case_review = review_cases[case_id]
        if not isinstance(case_review, dict):
            raise ValueError(f"{case_id}: review must be an object")
        candidate_reviews = _mapping(case_review, "reviews")
        if set(candidate_reviews) != set(candidates):
            raise ValueError(f"{case_id}: candidate review coverage mismatch")

        output_candidate_reviews: dict[str, object] = {}
        for candidate_id in candidates:
            raw_record = raw_candidates[candidate_id][case_id]
            if raw_record.get("user_request") != canonical_prompt:
                raise ValueError(f"{candidate_id}/{case_id}: user request drifted")
            candidate = _candidate_output(raw_record)
            review_value = candidate_reviews[candidate_id]
            if not isinstance(review_value, dict):
                raise ValueError(f"{candidate_id}/{case_id}: review must be an object")
            issues = review_value.get("issues")
            reason = review_value.get("reason")
            if not isinstance(issues, list) or len(issues) != len(set(issues)):
                raise ValueError(f"{candidate_id}/{case_id}: issues must be a unique list")
            if not isinstance(reason, str) or not reason.strip():
                raise ValueError(f"{candidate_id}/{case_id}: reason is required")
            unknown_issues = set(issues) - set(issue_severity)
            if unknown_issues:
                raise ValueError(
                    f"{candidate_id}/{case_id}: unknown issues {sorted(unknown_issues)}"
                )
            status = _status_for_issues(cast(list[str], issues), issue_severity)
            summary = summaries[candidate_id]
            summary[status] = cast(int, summary[status]) + 1
            counts = Counter(cast(dict[str, int], summary["issue_counts"]))
            counts.update(cast(list[str], issues))
            summary["issue_counts"] = dict(sorted(counts.items()))
            output_candidate_reviews[candidate_id] = {
                "status": status,
                "issues": issues,
                "reason": reason,
                "candidate": candidate,
            }

        gold = canonical["evaluation_gold"]
        output_cases.append(
            {
                "case_id": case_id,
                "canonical_user_prompt": canonical_prompt,
                "canonical_authority": {
                    "required_semantics": gold["required_semantics"],
                    "forbidden_semantics": gold["forbidden_semantics"],
                },
                "relation_authority": case_review.get("relation_authority"),
                "allowed_shapes": case_review.get("allowed_shapes", []),
                "candidates": output_candidate_reviews,
            }
        )

    return {
        "binding": {
            "regrader_sha": _git_head(),
            "dataset_sha256": normalized_sha256(DATASET),
            "review_sha256": hashlib.sha256(
                json.dumps(review, ensure_ascii=False, sort_keys=True).encode("utf-8")
            ).hexdigest(),
            "raw_result_sha256": raw_hashes,
            "raw_bindings": raw_bindings,
            "case_count": len(CORE24_CASE_IDS),
            "llm_calls": 0,
            "provider_read_count": 0,
            "provider_write_count": 0,
        },
        "summary": summaries,
        "superseded_metrics": [
            "baseline_structure_matches",
            "candidate_structure_matches",
            "identify_boundary_matches",
            "relation_required_matches",
        ],
        "cases": output_cases,
    }


def _status_for_issues(issues: list[str], issue_severity: dict[str, str]) -> str:
    highest = max((STATUS_RANK[issue_severity[issue]] for issue in issues), default=0)
    if highest == STATUS_RANK["FAIL"]:
        return "FAIL"
    if highest == STATUS_RANK["PARTIAL"]:
        return "PARTIAL"
    return "PASS"


def _candidate_output(record: dict[str, object]) -> object:
    materialize = record.get("materialize")
    if isinstance(materialize, dict):
        return materialize.get("candidate")
    return record.get("candidate")


def _mapping(value: dict[str, object], key: str) -> dict[str, object]:
    selected = value.get(key)
    if not isinstance(selected, dict):
        raise ValueError(f"{key} must be an object")
    return selected


if __name__ == "__main__":
    main()
