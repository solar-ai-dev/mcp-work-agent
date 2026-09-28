"""Recorded-output replay checks; no runtime or model is started."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest
from scripts import regrade_work_span_codec as replay
from scripts.ru_observation import object_hash


def _call(request: str, *spans: str) -> dict[str, Any]:
    projection = {"user_request": request}
    return {
        "call_index": 1,
        "prompt_id": replay.WORK_SLOT,
        "prompt_ref": {"prompt_id": replay.WORK_SLOT, "content_hash": "same-product-prompt"},
        "input": projection,
        "input_sha256": object_hash(projection),
        "output_schema": deepcopy(replay.REQUESTED_WORK_OUTPUT_SCHEMA.json_schema),
        "state": "RETURNED",
        "wire_request_count": 1,
        "content": json.dumps(
            {
                "schema_version": 1,
                "work_units": [{"request_spans": list(spans)}],
            },
            ensure_ascii=False,
        ),
        "runtime_policy": {"sampling_temperature": None, "sampling_seed": 7},
        "wire_options": {"seed": 7},
    }


def _artifact(root: Path, call: dict[str, Any], *, arm: str = "production") -> Path:
    path = root / "CASE-CORE-001" / arm / "calls.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"calls": [call]}, ensure_ascii=False), encoding="utf-8")
    return path


def test_whitespace_structural_recovery_has_no_semantic_pass() -> None:
    call = _call("8월 12일 작업 확인.", "8 월 12 일 작업 확인.")
    before = deepcopy(call)
    result = replay.compare_first(call)
    assert result["baseline"]["structural_status"] == "REJECTED"
    assert result["candidate"]["structural_status"] == "ACCEPTED"
    assert result["spans"][0]["comparison"] == "WHITESPACE_ONLY_UNIQUE"
    assert result["candidate"]["uncovered_nonwhitespace_characters"] == 0
    assert result["candidate"]["provenance"][0]["exact_current_request_slice"] is True
    assert result["semantic_verdict"] == "UNREVIEWED"
    assert result["downstream_success"] == "NOT_EVALUATED"
    assert call == before


def test_exact_span_with_omitted_sentence_is_preserved_not_completed() -> None:
    result = replay.compare_first(_call("상태 확인. 생성 금지.", "상태 확인."))
    assert result["accepted_baseline_preserved"] is True
    assert result["candidate"]["uncovered_nonwhitespace_characters"] == 5
    assert result["semantic_verdict"] == "UNREVIEWED"


@pytest.mark.parametrize(
    ("user_text", "span", "comparison"),
    [
        ("검토해. 검토해.", "검토해.", "EXACT_AMBIGUOUS"),
        ("검토 해. 검토 해.", "검 토해.", "NORMALIZED_AMBIGUOUS"),
        ("확인해.", "확인해!", "NONWHITESPACE_DIFFERENCE_OR_EMPTY"),
        ("승인 12", "승인 13", "NONWHITESPACE_DIFFERENCE_OR_EMPTY"),
        ("ab", "a\x1cb", "NONWHITESPACE_DIFFERENCE_OR_EMPTY"),
    ],
)
def test_non_unique_or_changed_characters_are_not_repaired(
    user_text: str, span: str, comparison: str
) -> None:
    row = replay.compare_first(_call(user_text, span))
    assert row["baseline"]["structural_status"] == "REJECTED"
    assert row["candidate"]["structural_status"] == "REJECTED"
    assert row["spans"][0]["comparison"] == comparison


def test_exact_match_keeps_precedence_over_normalized_collision() -> None:
    result = replay.compare_first(_call("ab a b", "ab"))
    assert result["spans"][0]["comparison_view_matches"] == 2
    assert result["accepted_baseline_preserved"] is True


def test_replay_binds_files_and_counts_observations_without_mutating_raw(tmp_path: Path) -> None:
    call = _call("상태를 확인.", "상태를 확인.")
    a = _artifact(tmp_path, call)
    b = _artifact(tmp_path, call, arm="connected")
    before = {path: path.read_bytes() for path in (a, b)}
    result = replay.build_report([tmp_path, tmp_path], expected_prompt_ref=call["prompt_ref"])
    assert result["summary"]["first_outputs"] == 2
    assert result["summary"]["distinct_requests"] == 1
    assert result["summary"]["baseline_acceptance_regressions"] == 0
    assert result["new_model_calls"] == 0
    assert len(result["rows"][0]["calls_sha256"]) == 64
    assert result["rows"][0]["runtime_policy"] == call["runtime_policy"]
    assert result["rows"][0]["call_index"] == 1
    assert {path: path.read_bytes() for path in (a, b)} == before


@pytest.mark.parametrize("mismatch", ["prompt", "schema", "revision", "hash", "wire"])
def test_incompatible_or_non_first_raw_is_excluded(tmp_path: Path, mismatch: str) -> None:
    call = _call("상태를 확인.", "상태를 확인.")
    expected = deepcopy(call["prompt_ref"])
    if mismatch == "prompt":
        call["prompt_ref"]["content_hash"] = "different"
    elif mismatch == "schema":
        call["output_schema"] = {}
    elif mismatch == "revision":
        call["input"] = {"base_projection": call["input"], "failure_record": {}}
    elif mismatch == "hash":
        call["input_sha256"] = "invalid"
    else:
        call["wire_request_count"] = 0
    _artifact(tmp_path, call)
    report = replay.build_report([tmp_path], expected_prompt_ref=expected)
    assert report["rows"] == []
    assert len(report["excluded"]) == 1


def test_distinct_spans_do_not_claim_missing_punctuation_is_preserved() -> None:
    row = replay.compare_first(_call("A 1, B 2", "A1", "B2"))
    assert row["candidate"]["structural_status"] == "ACCEPTED"
    assert row["candidate"]["work_unit_count"] == 1
    assert row["candidate"]["uncovered_nonwhitespace_characters"] == 1
