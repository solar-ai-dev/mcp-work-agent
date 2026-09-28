"""No inference: exact think-only delta and schema-only dispatch gate."""

from __future__ import annotations

import json
from copy import deepcopy
from typing import Any

import pytest
from scripts import evaluate_source_focal_reasoning as candidate
from scripts import ru_source_focal_candidate as focal
from tests.support.source_dependency_wire import product_wire as product_wire


def test_build_payload__frozen_focal__changes_only_think(product_wire: dict[str, Any]) -> None:
    original = focal.build_payload(product_wire, "TASK")
    snapshot = deepcopy(original)
    result = candidate.build_payload(original)
    assert result == {**snapshot, "think": True}
    assert original == snapshot
    result["options"]["seed"] = 0
    assert original == snapshot


@pytest.mark.parametrize("field,value", [("think", None), ("think", True), ("stream", True)])
def test_build_payload__nonbaseline_runtime__rejects(field: str, value: Any) -> None:
    wire = {"think": False, "stream": False, field: value}
    with pytest.raises(ValueError):
        candidate.build_payload(wire)


@pytest.mark.parametrize("content", [None, "", "not json", "{}"])
def test_structural_stop__invalid_final__preserves_admission(
    product_wire: dict[str, Any], content: Any
) -> None:
    payload = focal.build_payload(product_wire, "TASK")
    row = {"content": content}
    reason = candidate.structural_stop(row, {"candidate_payload": payload})
    assert reason is not None and reason.startswith("FOCAL_FINAL_")
    assert row["source_admission"]["validated_focus"] is None
    assert row["content"] == content


def test_structural_stop__semantically_wrong_valid_output__does_not_stop_or_correct(
    product_wire: dict[str, Any],
) -> None:
    payload = focal.build_payload(product_wire, "TASK")
    # The request needs Tasks; this negative is deliberately semantically wrong.
    output = {
        "source_dependencies": [{"resource_type": "TASK", "dependency": "SOURCE_NOT_REQUIRED"}]
    }
    row = {"content": json.dumps(output)}
    assert candidate.structural_stop(row, {"candidate_payload": payload}) is None
    assert row["source_admission"]["validation"]["validated_output"] == output


def test_keys__fixed_compatibility_trial__failure_first_then_positive_and_negative_controls() -> (
    None
):
    assert candidate.KEYS == (
        ("CASE-CORE-049", "TASK"),
        ("CASE-CORE-005", "TASK"),
        ("CASE-CORE-017", "GMAIL_DRAFT"),
        ("SYNTHETIC-DRAFT-UPDATE", "GMAIL_DRAFT"),
    )


@pytest.mark.parametrize("format_mode", ["schema", "omitted"])
def test_build_payload__format_mode__preserves_body_and_changes_only_registered_wire_keys(
    product_wire: dict[str, Any],
    format_mode: str,
) -> None:
    original = focal.build_payload(product_wire, "TASK")
    snapshot = deepcopy(original)
    expected = {**deepcopy(original), "think": True}
    if format_mode == "omitted":
        del expected["format"]

    result = candidate.build_payload(original, format_mode=format_mode)

    assert result == expected
    assert result["prompt"] == original["prompt"]
    assert json.loads(result["prompt"])["output_schema"] == original["format"]
    if format_mode == "schema":
        assert result == candidate.build_payload(original)
    else:
        assert "format" not in result
    result["options"]["seed"] = 1
    assert original == snapshot


@pytest.mark.parametrize("format_mode", ["", "json", "OMITTED", "unknown"])
def test_build_payload__unknown_format_mode__rejects_before_dispatch(
    product_wire: dict[str, Any],
    format_mode: str,
) -> None:
    original = focal.build_payload(product_wire, "TASK")
    with pytest.raises(ValueError):
        candidate.build_payload(original, format_mode=format_mode)


@pytest.mark.parametrize("required", [False, True])
def test_structural_stop__omitted_format__validates_temporary_schema_without_mutating_wire(
    product_wire: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
    required: bool,
) -> None:
    original = focal.build_payload(product_wire, "TASK")
    payload = candidate.build_payload(original, format_mode="omitted")
    before = deepcopy(payload)
    output: dict[str, Any] = {"resource_type": "TASK", "dependency": "SOURCE_NOT_REQUIRED"}
    if required:
        output.update(
            dependency="SOURCE_REQUIRED",
            required_information=["completion_status"],
            target_scope="CRITERIA",
            work_unit_ids=["work-1"],
        )
    response = {"source_dependencies": [output]}
    row = {"content": json.dumps(response), "payload": payload}
    validator_inputs = []
    real_admit = candidate.reference.candidate.admit_focus

    def observe(content: object, validation_payload: dict[str, Any]) -> dict[str, Any]:
        validator_inputs.append(deepcopy(validation_payload))
        return real_admit(content, validation_payload)

    monkeypatch.setattr(candidate.reference.candidate, "admit_focus", observe)

    assert candidate.structural_stop(row, {"candidate_payload": payload}) is None
    assert row["source_admission"]["validated_focus"] == output
    assert row["source_admission"]["validation"]["validated_output"] == response
    assert row["source_admission"]["wire_format_policy"] == "OMITTED_SCHEMA_STILL_VALIDATED"
    assert validator_inputs == [{**before, "format": json.loads(before["prompt"])["output_schema"]}]
    assert payload == before == row["payload"]
    assert "format" not in payload


@pytest.mark.parametrize("invalid", ["unknown_work", "extra_resource", "fenced_json"])
def test_structural_stop__omitted_format_invalid_final__preserves_strict_rejection_and_raw_wire(
    product_wire: dict[str, Any],
    invalid: str,
) -> None:
    payload = candidate.build_payload(
        focal.build_payload(product_wire, "TASK"), format_mode="omitted"
    )
    before = deepcopy(payload)
    response = {
        "source_dependencies": [
            {
                "resource_type": "TASK",
                "dependency": "SOURCE_REQUIRED",
                "required_information": ["completion_status"],
                "target_scope": "CRITERIA",
                "work_unit_ids": ["not-current-work" if invalid == "unknown_work" else "work-1"],
            }
        ]
    }
    if invalid == "extra_resource":
        response["source_dependencies"].append(
            {"resource_type": "GMAIL_DRAFT", "dependency": "SOURCE_NOT_REQUIRED"}
        )
    content = json.dumps(response)
    if invalid == "fenced_json":
        content = "```json\n" + content + "\n```"
    row = {"content": content, "payload": payload}

    reason = candidate.structural_stop(row, {"candidate_payload": payload})

    assert reason is not None and reason.startswith("FOCAL_FINAL_")
    assert row["source_admission"]["validated_focus"] is None
    assert row["source_admission"]["wire_format_policy"] == "OMITTED_SCHEMA_STILL_VALIDATED"
    assert payload == before == row["payload"]
    assert row["content"] == content
    assert "format" not in payload


def test_structural_stop__omitted_format_body_schema_drift__rejects_without_repairing_wire(
    product_wire: dict[str, Any],
) -> None:
    payload = candidate.build_payload(
        focal.build_payload(product_wire, "TASK"), format_mode="omitted"
    )
    body = json.loads(payload["prompt"])
    body["output_schema"] = {"type": "object"}
    payload["prompt"] = json.dumps(body)
    before = deepcopy(payload)
    row = {"content": "{}", "payload": payload}

    with pytest.raises(ValueError, match="schema"):
        candidate.structural_stop(row, {"candidate_payload": payload})

    assert payload == before == row["payload"]
    assert "format" not in payload
