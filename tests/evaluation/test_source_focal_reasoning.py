"""No inference: exact think-only delta and schema-only dispatch gate."""

from __future__ import annotations

import json
from copy import deepcopy
from typing import Any

import pytest
from scripts import evaluate_source_focal_reasoning as candidate
from scripts import ru_source_focal_candidate as focal
from tests.evaluation.test_source_interpretation_handoff import product_wire as product_wire


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
    # The request needs the selected Task; this negative is deliberately semantically wrong.
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
