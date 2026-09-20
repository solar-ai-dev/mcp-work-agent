"""Corrected saved-response evaluator for the issue 294 requested-fact experiments."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, cast

from evaluation import ru294_producer_observation as historical
from google_work_agent.ports.llm.output_schema_validation import validate_output_schema

ROOT = Path(__file__).resolve().parents[1]
REFERENCE_PATH = ROOT / "evaluation/ru294_direct_fact_reference_13_v2.json"
DATASET_PATH = ROOT / "evaluation/development_datasets/agent/ru_quality_dev_v2.jsonl"
SCORER_VERSION = "ru294-requested-fact-evaluator-v2"
PROVENANCE_VERSION = "ru294-exact-span-with-overlap-diagnostic-v2"
APPLICABILITY_STATES = {"SCORABLE", "NOT_APPLICABLE", "UNSCORABLE"}

SAVED_RUNS = {
    "minimal-fewshot": ROOT / "evaluation/results/ru294-producer-ab-20260919",
    "concise-zeroshot": ROOT / "evaluation/results/ru294-concise-zeroshot-ab-20260920",
}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_reference(path: Path = REFERENCE_PATH) -> dict[str, Any]:
    reference = cast(dict[str, Any], json.loads(path.read_text(encoding="utf-8")))
    if reference.get("schema_version") != 2:
        raise ValueError("unsupported requested-fact reference version")
    cases = cast(dict[str, Any], reference.get("cases"))
    if len(cases) != 13:
        raise ValueError("corrected reference must cover the focused 13-case set")
    for case_id, rules in cases.items():
        applicability = rules.get("applicability")
        pair_sets = rules.get("accepted_pair_sets")
        if applicability not in APPLICABILITY_STATES or not isinstance(pair_sets, list):
            raise ValueError(f"invalid reference rules for {case_id}")
        if applicability == "SCORABLE" and not pair_sets:
            raise ValueError(f"scorable case has no accepted pair set: {case_id}")
        if applicability != "SCORABLE" and not rules.get("exclusion_reason"):
            raise ValueError(f"excluded case has no reason: {case_id}")
        if rules.get("subset_role") not in {"TARGET", "CONTROL"}:
            raise ValueError(f"invalid subset role for {case_id}")
        if not rules.get("inclusion_reason") or not rules.get("intended_failure_signature"):
            raise ValueError(f"subset metadata missing for {case_id}")
    return reference


def load_cases(path: Path = DATASET_PATH) -> dict[str, dict[str, Any]]:
    return {
        case["case_id"]: case
        for line in path.read_text(encoding="utf-8").splitlines()
        if (case := json.loads(line))
    }


def score_response(
    raw_content: str,
    *,
    case: Mapping[str, Any],
    rules: Mapping[str, Any],
) -> dict[str, Any]:
    applicability = str(rules["applicability"])
    scorable = applicability == "SCORABLE"
    try:
        parsed = json.loads(raw_content)
    except (TypeError, ValueError):
        return {
            "applicability": applicability,
            "scorable": scorable,
            "not_applicable": applicability == "NOT_APPLICABLE",
            "unscorable": applicability == "UNSCORABLE",
            "exclusion_reason": rules.get("exclusion_reason"),
            "shape_errors": ["provider response is not JSON"],
            "candidates": [],
            "semantic_valid_candidates": 0,
            "missing_required_facts": [],
            "requested_fact_omission": False,
            "extra_fact_count": 0,
            "identity_diagnostic_count": 0,
            "provenance_only_false_reject_count": 0,
            "strict_semantic_valid": False if scorable else None,
            "semantic_valid": False if scorable else None,
            "authority_eligible": False if scorable else None,
        }

    schema = historical.observation_schema()
    shape_errors = validate_output_schema(parsed, schema.json_schema)
    output = parsed if isinstance(parsed, dict) else {}
    raw_candidates = output.get("requested_fact_candidates")
    candidates = raw_candidates if isinstance(raw_candidates, list) else []
    accepted_sets = [set(items) for items in rules["accepted_pair_sets"]]
    accepted_pairs = set().union(*accepted_sets) if accepted_sets else set()
    identity_pairs = set(rules.get("identity_pairs", []))

    pairs: list[str] = []
    results: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, candidate in enumerate(candidates):
        item = candidate if isinstance(candidate, dict) else {}
        kind = item.get("fact_kind") if isinstance(item.get("fact_kind"), str) else None
        role = item.get("role") if isinstance(item.get("role"), str) else None
        pair = f"{kind}|{role}"
        duplicate = pair in seen
        seen.add(pair)
        pairs.append(pair)

        provenance = item.get("provenance")
        provenance = provenance if isinstance(provenance, dict) else {}
        source = provenance.get("source")
        source_text = provenance.get("source_text")
        authority = _source_authority(case, source)
        exact_span = (
            isinstance(authority, str)
            and isinstance(source_text, str)
            and bool(source_text)
            and source_text in authority
        )
        overlaps = _constraint_overlaps(output.get("constraints"), source_text)
        semantic_candidate_valid = pair in accepted_pairs and not duplicate
        semantic_category = (
            "USER_RESULT_FACT"
            if semantic_candidate_valid and role == "RESULT_FACT"
            else "CURRENT_STATE_PREREQUISITE"
            if semantic_candidate_valid and role == "CURRENT_STATE"
            else "SEARCH_OR_RESOURCE_IDENTITY"
            if pair in identity_pairs
            else "OUT_OF_CONTRACT"
        )
        results.append(
            {
                "diagnostic_id": f"{case['case_id']}:{index:03d}",
                "fact_kind": kind,
                "role": role,
                "semantic_candidate_valid": semantic_candidate_valid,
                "semantic_category": semantic_category,
                "fact_kind_correct": kind in {p.split("|", 1)[0] for p in accepted_pairs},
                "role_correct": role in {p.split("|", 1)[1] for p in accepted_pairs},
                "duplicate": duplicate,
                "extra_fact": not semantic_candidate_valid,
                "exact_source_span": exact_span,
                "constraint_overlap_diagnostic": overlaps,
                "legacy_overlap_would_reject": bool(overlaps),
                "textual_provenance_valid": exact_span,
                "provenance_only_false_reject": False,
                "authority_eligible": not shape_errors and semantic_candidate_valid and exact_span,
            }
        )

    actual = set(pairs)
    chosen = _closest_expected(actual, accepted_sets)
    missing = sorted(chosen - actual)
    extras = actual - chosen
    duplicates = len(pairs) - len(actual)
    strict_semantic_valid = (
        not shape_errors and actual in accepted_sets and duplicates == 0 if scorable else None
    )
    authority_eligible = (
        bool(strict_semantic_valid) and all(result["authority_eligible"] for result in results)
        if scorable
        else None
    )
    return {
        "applicability": applicability,
        "scorable": scorable,
        "not_applicable": applicability == "NOT_APPLICABLE",
        "unscorable": applicability == "UNSCORABLE",
        "exclusion_reason": rules.get("exclusion_reason"),
        "shape_errors": shape_errors,
        "candidates": results,
        "semantic_valid_candidates": sum(
            bool(result["semantic_candidate_valid"]) for result in results
        ),
        "missing_required_facts": missing,
        "requested_fact_omission": scorable and bool(missing),
        "extra_fact_count": len(extras) + duplicates,
        "identity_diagnostic_count": sum(
            result["semantic_category"] == "SEARCH_OR_RESOURCE_IDENTITY" for result in results
        ),
        "provenance_only_false_reject_count": 0,
        "strict_semantic_valid": strict_semantic_valid,
        "semantic_valid": strict_semantic_valid,
        "authority_eligible": authority_eligible,
    }


def load_raw_observation(path: Path) -> tuple[str, str, str]:
    envelope = json.loads(path.read_text(encoding="utf-8"))
    case_id, arm, raw_content = (
        envelope.get("case_id"),
        envelope.get("arm"),
        envelope.get("raw_first_response"),
    )
    if not isinstance(case_id, str) or arm not in {"A", "B"}:
        raise ValueError("saved raw observation identity is invalid")
    if not isinstance(raw_content, str):
        raise ValueError("saved raw observation has no first response")
    return case_id, arm, raw_content


def rescore_saved_runs(output_path: Path) -> dict[str, Any]:
    reference = load_reference()
    cases = load_cases()
    result: dict[str, Any] = {
        "schema_version": 1,
        "artifact_kind": "RU294_SAVED_RESPONSE_RESCORE",
        "dataset": {"path": str(DATASET_PATH.relative_to(ROOT)), "sha256": sha256(DATASET_PATH)},
        "reference": {
            "path": str(REFERENCE_PATH.relative_to(ROOT)),
            "sha256": sha256(REFERENCE_PATH),
            "version": SCORER_VERSION,
            "provenance_validator_version": PROVENANCE_VERSION,
        },
        "qwen_rerun": False,
        "runs": {},
    }
    for run_name, run_dir in SAVED_RUNS.items():
        result["runs"][run_name] = _rescore_run(run_dir, cases, reference)
    _write_json(output_path, result)
    return result


def _rescore_run(
    run_dir: Path,
    cases: Mapping[str, Mapping[str, Any]],
    reference: Mapping[str, Any],
) -> dict[str, Any]:
    historical_observations = json.loads(
        (run_dir / "observations.json").read_text(encoding="utf-8")
    )
    old_by_key = {(row["case_id"], row["arm"]): row for row in historical_observations}
    rescored: list[dict[str, Any]] = []
    for raw_path in sorted((run_dir / "raw").glob("*.json")):
        case_id, arm, raw_content = load_raw_observation(raw_path)
        score = score_response(
            raw_content,
            case=cases[case_id],
            rules=reference["cases"][case_id],
        )
        historical_row = old_by_key[(case_id, arm)]
        rescored.append(
            {
                "case_id": case_id,
                "arm": arm,
                "raw_path": str(raw_path.relative_to(ROOT)),
                "raw_response_sha256": hashlib.sha256(raw_content.encode("utf-8")).hexdigest(),
                "input_tokens": historical_row.get("input_tokens"),
                "output_tokens": historical_row.get("output_tokens"),
                "latency_ms": historical_row.get("latency_ms"),
                "score": score,
            }
        )
    return {
        "source": {
            "directory": str(run_dir.relative_to(ROOT)),
            "observations_sha256": sha256(run_dir / "observations.json"),
            "raw_response_count": len(rescored),
        },
        "summary": summarize(rescored),
        "observations": rescored,
    }


def summarize(observations: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    by_arm = {
        arm: {str(row["case_id"]): row for row in observations if row["arm"] == arm}
        for arm in ("A", "B")
    }
    arm_summaries: dict[str, Any] = {}
    for arm, rows_by_case in by_arm.items():
        rows = list(rows_by_case.values())
        judged = [row for row in rows if row["score"]["scorable"]]
        candidates = [item for row in judged for item in row["score"]["candidates"]]
        arm_summaries[arm] = {
            "response_count": len(rows),
            "judged_case_count": len(judged),
            "semantic_pass_count": sum(
                row["score"]["strict_semantic_valid"] is True for row in judged
            ),
            "semantic_pass_case_ids": sorted(
                str(row["case_id"])
                for row in judged
                if row["score"]["strict_semantic_valid"] is True
            ),
            "omission_case_count": sum(
                bool(row["score"]["requested_fact_omission"]) for row in judged
            ),
            "missing_item_count": sum(
                len(row["score"]["missing_required_facts"]) for row in judged
            ),
            "extra_item_count": sum(row["score"]["extra_fact_count"] for row in judged),
            "candidate_count": len(candidates),
            "semantic_valid_candidate_count": sum(
                bool(item["semantic_candidate_valid"]) for item in candidates
            ),
            "exact_source_span_count": sum(bool(item["exact_source_span"]) for item in candidates),
            "constraint_overlap_diagnostic_count": sum(
                bool(item["constraint_overlap_diagnostic"]) for item in candidates
            ),
            "authority_eligible_case_count": sum(
                row["score"]["authority_eligible"] is True for row in judged
            ),
            "input_tokens": sum(int(row.get("input_tokens") or 0) for row in rows),
            "output_tokens": sum(int(row.get("output_tokens") or 0) for row in rows),
            "latency_ms": sum(int(row.get("latency_ms") or 0) for row in rows),
        }

    complete_pairs = sorted(set(by_arm["A"]) & set(by_arm["B"]))
    judged_pairs = [
        case_id
        for case_id in complete_pairs
        if by_arm["A"][case_id]["score"]["scorable"] and by_arm["B"][case_id]["score"]["scorable"]
    ]
    transitions: dict[str, list[str]] = {
        "FAIL_TO_PASS": [],
        "PASS_TO_FAIL": [],
        "PASS_TO_PASS": [],
        "FAIL_TO_FAIL": [],
    }
    for case_id in judged_pairs:
        a_pass = by_arm["A"][case_id]["score"]["strict_semantic_valid"] is True
        b_pass = by_arm["B"][case_id]["score"]["strict_semantic_valid"] is True
        key = (
            "PASS_TO_PASS"
            if a_pass and b_pass
            else "PASS_TO_FAIL"
            if a_pass
            else "FAIL_TO_PASS"
            if b_pass
            else "FAIL_TO_FAIL"
        )
        transitions[key].append(case_id)
    not_applicable_case_ids: list[str] = []
    unscorable_case_ids: list[str] = []
    for case_id in sorted(set(by_arm["A"]) | set(by_arm["B"])):
        row = by_arm["A"].get(case_id) or by_arm["B"].get(case_id)
        if row is not None and row["score"]["applicability"] == "NOT_APPLICABLE":
            not_applicable_case_ids.append(case_id)
        if row is not None and row["score"]["applicability"] == "UNSCORABLE":
            unscorable_case_ids.append(case_id)

    return {
        "complete_pair_count": len(complete_pairs),
        "judged_pair_count": len(judged_pairs),
        "not_applicable_case_ids": not_applicable_case_ids,
        "unscorable_case_ids": unscorable_case_ids,
        "arms": arm_summaries,
        "transitions": transitions,
    }


def _source_authority(case: Mapping[str, Any], source: object) -> object:
    if source == "USER_REQUEST":
        return case.get("user_request")
    if source == "CONFIRMATION_RESPONSE":
        return case.get("confirmation_response")
    return None


def _closest_expected(actual: set[str], accepted_sets: Sequence[set[str]]) -> set[str]:
    if not accepted_sets:
        return set()
    return min(accepted_sets, key=lambda expected: (len(expected - actual), len(actual - expected)))


def _constraint_overlaps(constraints: object, source_text: object) -> list[dict[str, str]]:
    if not isinstance(constraints, dict) or not isinstance(source_text, str):
        return []
    matches: list[dict[str, str]] = []
    for field, raw in constraints.items():
        values: list[object] = raw if isinstance(raw, list) else [raw]
        for value in values:
            if isinstance(value, dict):
                value = value.get("value")
            for text in value if isinstance(value, list) else [value]:
                if isinstance(text, str) and text and text in source_text:
                    matches.append({"field": str(field), "value": text})
    return matches


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    rescore_saved_runs(args.output.resolve())


if __name__ == "__main__":
    main()
