"""Synthetic current Product wire controls, not Source semantic-quality grading."""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from typing import Any

import pytest
from scripts import ru_source_focal_candidate as candidate
from tests.evaluation.test_source_interpretation_handoff import product_wire as product_wire

from google_work_agent.application.agents.request_understanding.identify_source_dependencies import (  # noqa: E501
    build_source_dependency_output_schema,
)
from google_work_agent.application.prompt_runtime.prompt_registry import PromptRegistry


def _decision(required: bool = True) -> dict[str, Any]:
    value: dict[str, Any] = {"resource_type": "TASK", "dependency": "SOURCE_NOT_REQUIRED"}
    if required:
        value.update(
            dependency="SOURCE_REQUIRED",
            required_information=["completion_status"],
            target_scope="CRITERIA",
            work_unit_ids=["work-1"],
        )
    return {"source_dependencies": [value]}


def test_build_payload__one_focus__preserves_full_input_and_runtime_with_narrow_schema(
    product_wire: dict[str, Any],
) -> None:
    original = deepcopy(product_wire)
    old_body = json.loads(original["prompt"])
    result = candidate.build_payload(product_wire, "TASK")
    body = json.loads(result["prompt"])
    selected = [
        item for item in old_body["input"]["source_candidates"] if item["resource_type"] == "TASK"
    ]
    expected_schema = build_source_dependency_output_schema(
        selected, work_unit_ids=["work-1"]
    ).json_schema
    role = PromptRegistry().source_text(candidate.PROMPT_ID).rstrip()
    for old, new in candidate.ROLE_REPLACEMENTS:
        assert role.count(old) == 1
        role = role.replace(old, new, 1)

    assert body["input"] == {**old_body["input"], "assessment_resource_type": "TASK"}
    assert len(body["input"]["source_candidates"]) > 1
    assert body["output_schema"] == result["format"] == expected_schema
    assert body["prompt_ref"] == {
        "prompt_id": candidate.CANDIDATE_ID,
        "prompt_version": "v1",
        "content_hash": hashlib.sha256(role.encode("utf-8")).hexdigest(),
    }
    assert result["system"].startswith(role + "\n\n")
    assert result["system"].endswith(
        json.dumps(body["input"], ensure_ascii=False, separators=(",", ":"), sort_keys=True) + "\n"
    )
    assert {
        key: value for key, value in result.items() if key not in {"system", "prompt", "format"}
    } == {
        key: value for key, value in original.items() if key not in {"system", "prompt", "format"}
    }
    assert product_wire == original
    result["options"]["seed"] = 1
    result["format"]["type"] = "array"
    assert product_wire == original


@pytest.mark.parametrize("focus", ["", "task", "UNREGISTERED", "TASK_LIST "])
def test_build_payload__unknown_focus__rejects_without_guessing(
    product_wire: dict[str, Any],
    focus: str,
) -> None:
    with pytest.raises(ValueError, match="focus"):
        candidate.build_payload(product_wire, focus)


@pytest.mark.parametrize("drift", ["ref", "catalog", "schema", "system", "revision"])
def test_build_payload__changed_product_authority__rejects(
    product_wire: dict[str, Any],
    drift: str,
) -> None:
    body = json.loads(product_wire["prompt"])
    if drift == "ref":
        body["prompt_ref"]["content_hash"] = "changed"
    elif drift == "catalog":
        body["input"]["source_candidates"] = []
    elif drift == "schema":
        product_wire["format"] = {"type": "object"}
    elif drift == "system":
        product_wire["system"] += "Extra instruction"
    else:
        body["input"] = {"base_projection": body["input"], "candidate_output": {}}
    product_wire["prompt"] = json.dumps(body)
    with pytest.raises(ValueError):
        candidate.build_payload(product_wire, "TASK")


def test_build_payload__replacement_drift__rejects_instead_of_partial_role_edit(
    product_wire: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(candidate, "ROLE_REPLACEMENTS", (("not in Product source", "new"),))
    with pytest.raises(ValueError, match="exactly one"):
        candidate.build_payload(product_wire, "TASK")


@pytest.mark.parametrize("required", [False, True])
def test_admit_focus__valid_decision__returns_only_assessed_resource(
    product_wire: dict[str, Any],
    required: bool,
) -> None:
    payload = candidate.build_payload(product_wire, "TASK")
    before = deepcopy(payload)
    response = _decision(required)
    result = candidate.admit_focus(json.dumps(response), payload)

    assert result["validation"]["structural_result"] == "VALIDATED"
    assert result["validation"]["validated_output"] == response
    assert result["validated_focus"] == response["source_dependencies"][0]
    assert set(result) == {"validation", "validated_focus"}
    assert len(result["validation"]["validated_output"]["source_dependencies"]) == 1
    assert payload == before


@pytest.mark.parametrize(
    "drift", ["foreign_resource", "foreign_work", "extra_resource", "blank_fact", "json"]
)
def test_admit_focus__invalid_decision__does_not_repair_or_fill_other_resources(
    product_wire: dict[str, Any],
    drift: str,
) -> None:
    payload = candidate.build_payload(product_wire, "TASK")
    response = _decision()
    decision = response["source_dependencies"][0]
    if drift == "foreign_resource":
        decision["resource_type"] = "GMAIL_DRAFT"
    elif drift == "foreign_work":
        decision["work_unit_ids"] = ["foreign-work"]
    elif drift == "extra_resource":
        response["source_dependencies"].append(
            {"resource_type": "GMAIL_DRAFT", "dependency": "SOURCE_NOT_REQUIRED"}
        )
    elif drift == "blank_fact":
        decision["required_information"] = [" [] "]
    content = "not JSON" if drift == "json" else json.dumps(response)

    result = candidate.admit_focus(content, payload)

    assert result["validation"]["structural_result"] != "VALIDATED"
    assert result["validated_focus"] is None


def test_admit_focus__changed_frozen_schema__rejects_before_admission(
    product_wire: dict[str, Any],
) -> None:
    payload = candidate.build_payload(product_wire, "TASK")
    payload["format"] = {"type": "object"}
    with pytest.raises(ValueError, match="schema"):
        candidate.admit_focus(json.dumps(_decision()), payload)
