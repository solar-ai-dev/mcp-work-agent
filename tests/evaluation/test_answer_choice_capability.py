"""087 wire preservation on valid synthetic observations; no model or Provider.

Snapshot authorization remains a caller prerequisite. The verifier controls
below reject invalid bindings before the capability helper is called.
"""

import json
from collections.abc import Mapping
from copy import deepcopy
from typing import Any

import pytest
from scripts import answer_choice_capability_candidate as candidate
from scripts import evaluate_read_answer_handoff as handoff
from scripts import verify_answer_choice_capability as verifier
from tests.support.task_calendar_evidence import bind_task_calendar_snapshots

from google_work_agent.application.agents.retrieval.resolve_task_calendar_snapshot import (
    resolve_unique_task_calendar_snapshots,
)
from google_work_agent.ports.llm.output_schema_validation import validate_output_schema


@pytest.fixture
def compose_inputs() -> dict[str, dict[str, Any]]:
    values = {}
    for case in handoff.fixtures():
        if case["dispatch_limit"] != 1:
            continue
        first: dict[str, Any] = {}

        def capture(
            prompt_id: str,
            prompt_input: Mapping[str, object],
            *,
            _first: dict[str, Any] = first,
        ) -> Mapping[str, object]:
            assert prompt_id == "planning.compose_answer" and not _first
            _first.update(handoff._wire_projection(dict(prompt_input)))
            raise handoff._CapturedFirst

        with pytest.raises(handoff._CapturedFirst):
            handoff._pipeline(case, capture, {})
        values[case["case_id"]] = {
            "case_id": case["case_id"],
            "prompt_input": first["input"],
            "snapshots": case["pipeline_input"]["source_snapshots"],
            "original": first["wire_payload"],
        }
    return values


def test_build_capability_wire__valid_calendar__preserves_product_bytes_and_validator(
    compose_inputs: dict[str, dict[str, Any]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = compose_inputs["SYNTHETIC_CALENDAR_LOCATION"]
    before = deepcopy(case)

    def forbidden(*_: Any) -> None:
        pytest.fail("unsupported normal input must not gain a choice envelope")

    monkeypatch.setattr(candidate.choice, "choice_wire", forbidden)
    payload = candidate.build_capability_wire(
        case["original"],
        case["prompt_input"],
        case["snapshots"],
    )
    assert payload == case["original"] and case == before
    assert candidate.ordered.transport_hash(payload) == candidate.ordered.transport_hash(
        case["original"],
    )
    refs = case["prompt_input"]["answer_outline"]["evidence_refs"]
    response = {"schema_version": 2, "answer": "일정 정보입니다.", "evidence_refs": refs}
    assert validate_output_schema(response, payload["format"]) == []
    assert validate_output_schema({**response, "evidence_refs": ["foreign"]}, payload["format"])
    assert validate_output_schema({**response, "mode": "PROSE"}, payload["format"])
    payload["options"]["seed"] += 1
    assert case == before


def test_build_capability_wire__valid_task__retains_two_mode_first_choices_and_input(
    compose_inputs: dict[str, dict[str, Any]],
) -> None:
    case = compose_inputs["SYNTHETIC_TASK_NOTES"]
    before = deepcopy(case)
    original, projection, snapshots = case["original"], case["prompt_input"], case["snapshots"]
    payload = candidate.build_capability_wire(original, projection, snapshots)
    expected = candidate.ordered.mode_first_wire(
        candidate.choice.choice_wire(original, projection, snapshots),
    )
    assert case == before and payload == expected
    assert candidate.ordered.transport_hash(payload) == candidate.ordered.transport_hash(expected)
    assert json.loads(payload["prompt"])["input"] == projection
    assert "source_snapshots" not in json.loads(payload["prompt"])["input"]
    for key in ("options", "model", "think", "stream"):
        assert payload[key] == original[key]
    branches = payload["format"]["oneOf"]
    assert [branch["properties"]["mode"]["const"] for branch in branches] == [
        "FACT_REFERENCES",
        "PROSE",
    ]
    assert all(next(iter(branch["properties"])) == "mode" for branch in branches)
    pairs = branches[0]["properties"]["items"]["items"]["enum"]
    assert {pair["field"] for pair in pairs} == {"title", "notes"}
    for response in (
        {"mode": "FACT_REFERENCES", "items": [{"evidence_ref": "e-task", "field": "notes"}]},
        {
            "mode": "PROSE",
            "schema_version": 2,
            "answer": "메모입니다.",
            "evidence_refs": ["e-task"],
        },
    ):
        assert validate_output_schema(response, payload["format"]) == []


def test_build_capability_wire__valid_snapshot_without_supported_values__retains_product_wire(
    compose_inputs: dict[str, dict[str, Any]],
) -> None:
    projection = deepcopy(compose_inputs["SYNTHETIC_TASK_NOTES"]["prompt_input"])
    projection["evidence"][0]["excerpt"] = "status: unknown-provider-enum"
    snapshots = bind_task_calendar_snapshots(
        projection["evidence"],
        {"e-task": {"status": "unknown-provider-enum"}},
    )
    assert resolve_unique_task_calendar_snapshots(projection["evidence"], snapshots) is not None
    assert candidate.bind_fact_selection_schema(projection, source_snapshots=snapshots) is None
    original = handoff._wire_projection(projection)["wire_payload"]
    payload = candidate.build_capability_wire(original, projection, snapshots)
    assert candidate.ordered.transport_hash(payload) == candidate.ordered.transport_hash(original)


@pytest.mark.parametrize("change", ["mismatch", "missing", "not_object", "malformed"])
def test_build_capability_wire__invalid_projection_binding__rejects_before_capability(
    compose_inputs: dict[str, dict[str, Any]],
    change: str,
) -> None:
    case = deepcopy(compose_inputs["SYNTHETIC_TASK_NOTES"])
    body = json.loads(case["original"]["prompt"])
    if change == "mismatch":
        body["input"]["user_request"] += " changed"
    elif change == "missing":
        del body["input"]
    elif change == "not_object":
        body = []
    case["original"]["prompt"] = "{" if change == "malformed" else json.dumps(body)
    with pytest.raises(ValueError):
        candidate.build_capability_wire(case["original"], case["prompt_input"], case["snapshots"])


def test_build_capability_wire__catalog_exception__propagates_without_prose_fallback(
    compose_inputs: dict[str, dict[str, Any]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = compose_inputs["SYNTHETIC_TASK_NOTES"]

    def reject(*_: Any, **__: Any) -> None:
        raise ValueError("caller validation failure")

    monkeypatch.setattr(candidate, "bind_fact_selection_schema", reject)
    with pytest.raises(ValueError, match="caller validation failure"):
        candidate.build_capability_wire(case["original"], case["prompt_input"], case["snapshots"])


def test_verify_reused_response__exact_calendar_wire__preserves_product_draft(
    compose_inputs: dict[str, dict[str, Any]],
) -> None:
    case = compose_inputs["SYNTHETIC_CALENDAR_LOCATION"]
    value = {
        "schema_version": 2,
        "answer": "일정의 시간과 장소입니다.",
        "evidence_refs": case["prompt_input"]["answer_outline"]["evidence_refs"],
    }
    row = {"payload": deepcopy(case["original"]), "content": json.dumps(value)}
    before = deepcopy((case, row))
    result = verifier.verify_reused_response(case, row, historical_product=True)
    assert result["structural_verdict"] == "PASS"
    assert result["semantic_verdict"] == "NOT_REVIEWED"
    assert result["response"]["answer_admission"]["draft"] == value
    assert (case, row) == before


@pytest.mark.parametrize("change", ["wire", "snapshot"])
def test_verify_reused_response__invalid_binding__rejects_before_response_reuse(
    compose_inputs: dict[str, dict[str, Any]],
    change: str,
) -> None:
    case = deepcopy(compose_inputs["SYNTHETIC_CALENDAR_LOCATION"])
    row = {"payload": deepcopy(case["original"]), "content": "{}"}
    if change == "wire":
        row["payload"]["options"]["seed"] += 1
    else:
        next(iter(case["snapshots"].values()))["title"] = "changed without rebinding"
    with pytest.raises(ValueError, match="no exact historical response|missing or stale"):
        verifier.verify_reused_response(case, row, historical_product=True)
