from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from evaluation import ru294_requested_fact_evaluator_v2 as evaluator


def _output(candidates: list[dict[str, object]], **constraints: object) -> str:
    slots: dict[str, object] = {
        "search_terms": [],
        "business_concepts": [],
        "person": [],
        "sender": [],
        "recipient": [],
        "subject": [],
        "period": [],
        "coverage_requirement": "NOT_COLLECTION",
        "additional_constraints": [],
    }
    slots.update(constraints)
    return json.dumps(
        {
            "goal": "요청을 처리한다.",
            "completion_conditions": [],
            "constraints": slots,
            "analysis_requirement": "NONE",
            "requested_fact_candidates": candidates,
        },
        ensure_ascii=False,
    )


def _candidate(kind: str, role: str, text: str) -> dict[str, object]:
    return {
        "fact_kind": kind,
        "role": role,
        "provenance": {"source": "USER_REQUEST", "source_text": text},
    }


def _inputs(case_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
    return evaluator.load_cases()[case_id], evaluator.load_reference()["cases"][case_id]


def _score(
    case_id: str, candidates: list[dict[str, object]], **constraints: object
) -> dict[str, Any]:
    case, rules = _inputs(case_id)
    return evaluator.score_response(
        _output(candidates, **constraints),
        case=case,
        rules=rules,
    )


def test_reference_records_subset_roles_applicability_and_failure_signatures() -> None:
    rules = evaluator.load_reference()["cases"]
    assert sum(case["subset_role"] == "TARGET" for case in rules.values()) == 9
    assert sum(case["subset_role"] == "CONTROL" for case in rules.values()) == 4
    assert sum(case["applicability"] == "SCORABLE" for case in rules.values()) == 8
    assert sum(case["applicability"] == "NOT_APPLICABLE" for case in rules.values()) == 3
    assert sum(case["applicability"] == "UNSCORABLE" for case in rules.values()) == 2
    assert all(case["inclusion_reason"] for case in rules.values())
    assert all(case["intended_failure_signature"] for case in rules.values())


def test_b001_due_span_survives_search_anchor_overlap() -> None:
    case, _ = _inputs("RU-B-001")
    score = _score(
        "RU-B-001",
        [_candidate("due", "RESULT_FACT", case["user_request"])],
        search_terms=["Nimbus"],
        business_concepts=["작업", "마감일"],
    )

    item = score["candidates"][0]
    assert item["constraint_overlap_diagnostic"]
    assert item["textual_provenance_valid"] is True
    assert item["provenance_only_false_reject"] is False
    assert item["authority_eligible"] is True
    assert score["strict_semantic_valid"] is True
    assert score["authority_eligible"] is True


def test_h002_valid_facts_survive_constraint_overlap() -> None:
    case, _ = _inputs("RU-H-002")
    score = _score(
        "RU-H-002",
        [
            _candidate("completion_status", "RESULT_FACT", case["user_request"]),
            _candidate("notes", "RESULT_FACT", case["user_request"]),
        ],
        search_terms=["Atlas"],
        business_concepts=["체크리스트", "메모"],
    )

    assert score["strict_semantic_valid"] is True
    assert score["authority_eligible"] is True
    assert score["provenance_only_false_reject_count"] == 0
    assert all(item["constraint_overlap_diagnostic"] for item in score["candidates"])


def test_a003_is_unscorable_instead_of_forced_strict_fail() -> None:
    case, _ = _inputs("RU-A-003")
    score = _score(
        "RU-A-003",
        [_candidate("start", "CURRENT_STATE", case["user_request"])],
    )

    assert score["applicability"] == "UNSCORABLE"
    assert score["scorable"] is False
    assert score["strict_semantic_valid"] is None
    assert score["authority_eligible"] is None
    assert score["exclusion_reason"]


def test_b002_does_not_treat_message_history_as_exact_high_level_results() -> None:
    case, _ = _inputs("RU-B-002")
    score = _score(
        "RU-B-002",
        [_candidate("message_history", "RESULT_FACT", case["user_request"])],
    )

    assert score["applicability"] == "UNSCORABLE"
    assert score["candidates"][0]["semantic_candidate_valid"] is False
    assert score["strict_semantic_valid"] is None


def test_output_construction_and_work_analysis_cases_are_not_applicable() -> None:
    for case_id in ("RU-D-001", "RU-E-003", "RU-G-003"):
        score = _score(case_id, [])
        assert score["applicability"] == "NOT_APPLICABLE"
        assert score["not_applicable"] is True
        assert score["strict_semantic_valid"] is None
        assert score["exclusion_reason"]


def test_all_scorable_contracts_can_receive_a_strict_pass() -> None:
    cases = evaluator.load_cases()
    candidates = {
        "RU-A-002": [("start", "RESULT_FACT")],
        "RU-B-001": [("due", "RESULT_FACT")],
        "RU-E-002": [("subject", "CURRENT_STATE")],
        "RU-H-001": [("subject", "RESULT_FACT")],
        "RU-H-002": [("completion_status", "RESULT_FACT"), ("notes", "RESULT_FACT")],
        "RU-H-003": [("title", "RESULT_FACT")],
        "RU-F-001": [],
        "RU-E-001": [("start", "RESULT_FACT"), ("end", "RESULT_FACT")],
    }
    for case_id, pairs in candidates.items():
        requested = [_candidate(kind, role, cases[case_id]["user_request"]) for kind, role in pairs]
        score = _score(case_id, requested)
        assert score["applicability"] == "SCORABLE"
        assert score["strict_semantic_valid"] is True


def test_variations_do_not_cross_resource_fact_kind_ownership() -> None:
    case, _ = _inputs("RU-H-002")
    score = _score(
        "RU-H-002",
        [
            _candidate("status", "RESULT_FACT", case["user_request"]),
            _candidate("content", "RESULT_FACT", case["user_request"]),
        ],
    )
    assert score["strict_semantic_valid"] is False
    assert score["semantic_valid_candidates"] == 0

    case, _ = _inputs("RU-E-001")
    score = _score(
        "RU-E-001",
        [_candidate("timestamps", "RESULT_FACT", case["user_request"])],
    )
    assert score["strict_semantic_valid"] is False


def test_identity_is_reported_separately_from_user_result_scoring() -> None:
    case, _ = _inputs("RU-B-001")
    score = _score(
        "RU-B-001",
        [
            _candidate("task_identity", "RESULT_FACT", case["user_request"]),
            _candidate("due", "RESULT_FACT", case["user_request"]),
        ],
    )
    assert score["identity_diagnostic_count"] == 1
    assert score["candidates"][0]["semantic_category"] == "SEARCH_OR_RESOURCE_IDENTITY"
    assert score["strict_semantic_valid"] is False


def test_existing_raw_first_response_format_is_readable_without_model_call() -> None:
    path = evaluator.ROOT / "evaluation/results/ru294-producer-ab-20260919/raw/RU-B-001-A.json"
    case_id, arm, raw_content = evaluator.load_raw_observation(path)
    case, rules = _inputs(case_id)
    score = evaluator.score_response(raw_content, case=case, rules=rules)

    assert (case_id, arm) == ("RU-B-001", "A")
    assert score["applicability"] == "SCORABLE"
    assert isinstance(score["strict_semantic_valid"], bool)


def test_invalid_saved_raw_envelope_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "invalid.json"
    path.write_text(json.dumps({"case_id": "RU-B-001", "arm": "A"}), encoding="utf-8")
    try:
        evaluator.load_raw_observation(path)
    except ValueError as exc:
        assert "no first response" in str(exc)
    else:
        raise AssertionError("invalid saved raw envelope was accepted")
