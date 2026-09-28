"""Pure 077 wire-delta checks; no historical raw, model, or Source semantic judge."""

from __future__ import annotations

import json
from copy import deepcopy
from typing import Any

import pytest
from scripts import evaluate_source_goal_constraint_ablation as candidate

PREFIX = (
    "Existing focal Source role.\n\nExisting common Product instruction.\n\n"
    "Allowed current-Run input projection (JSON):\n"
)


def _compact(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def _write_body(wire: dict[str, Any], body: dict[str, Any], *, bind_system: bool = True) -> None:
    wire["prompt"] = json.dumps(body, ensure_ascii=False, sort_keys=True)
    if bind_system:
        wire["system"] = PREFIX + _compact(body["input"]) + "\n"


@pytest.fixture
def focal_wire() -> dict[str, Any]:
    request = "선택한 작업의 상태와 기한만 알려줘.  새 작업은 만들지 마."
    projection = {
        "user_request": request,
        "selected_resource_refs": [{"resource_type": "TASK", "resource_id": "task-1"}],
        "run_reference_time": {"now_utc": "2026-09-29T00:00:00Z", "timezone": "Asia/Seoul"},
        "requested_work": {
            "work_units": [
                {
                    "unit_id": "work-1",
                    "request_provenance": [
                        {
                            "source": "USER_REQUEST",
                            "start_offset": 0,
                            "end_offset": len(request),
                            "source_text": request,
                        }
                    ],
                }
            ],
            "work_relations": [],
        },
        "goal_candidate": {
            "goal": "선택한 작업 정보 확인",
            "completion_conditions": ["요청한 정보를 근거로 답한다."],
            "analysis_requirement": "NONE",
            "constraints": {
                "search_terms": ["선택한 작업"],
                "coverage": "NOT_COLLECTION",
                "period": {"start": None, "end": None},
                "additional_constraints": [{"field": "due", "value": "내일"}],
            },
        },
        "source_candidates": [
            {
                "resource_type": "TASK",
                "owned_fact_kinds": ["completion_status", "due"],
                "read_tool_ids": ["tasks_get_task"],
            },
            {
                "resource_type": "GMAIL_DRAFT",
                "owned_fact_kinds": ["body"],
                "read_tool_ids": ["gmail_get_draft"],
            },
        ],
        "assessment_resource_type": "TASK",
    }
    schema = {"type": "object", "properties": {"source_dependencies": {"type": "array"}}}
    wire = {
        "model": "fake-no-http",
        "format": deepcopy(schema),
        "options": {"num_ctx": 16_384, "temperature": 0.05, "seed": 20260923},
        "think": False,
        "stream": False,
    }
    _write_body(
        wire,
        {
            "prompt_ref": {
                "prompt_id": "evaluation.source_focal_assessment",
                "prompt_version": "v1",
                "content_hash": "frozen-role-hash",
            },
            "input": projection,
            "output_schema": schema,
        },
    )
    return wire


def test_build_payload__focal_goal_constraints__changes_only_constraints_in_both_input_copies(
    focal_wire: dict[str, Any],
) -> None:
    original = deepcopy(focal_wire)
    old_body = json.loads(original["prompt"])
    expected_body = deepcopy(old_body)
    expected_body["input"]["goal_candidate"]["constraints"] = {}
    expected = deepcopy(original)
    _write_body(expected, expected_body)

    result = candidate.build_payload(focal_wire)

    assert result == expected
    assert result["system"].startswith(PREFIX)
    assert json.loads(result["prompt"])["prompt_ref"] == old_body["prompt_ref"]
    assert result["format"] == old_body["output_schema"]
    assert focal_wire == original
    result["options"]["seed"] = 1
    assert focal_wire == original


def test_build_payload__already_empty_constraints__returns_exact_noop_wire(
    focal_wire: dict[str, Any],
) -> None:
    body = json.loads(focal_wire["prompt"])
    body["input"]["goal_candidate"]["constraints"] = {}
    _write_body(focal_wire, body)
    # The no-op must not canonicalize otherwise-valid USER JSON whitespace.
    focal_wire["prompt"] = json.dumps(body, ensure_ascii=False, indent=3)
    original = deepcopy(focal_wire)

    result = candidate.build_payload(focal_wire)

    assert result == original
    result["format"]["type"] = "array"
    assert focal_wire == original


@pytest.mark.parametrize("invalid", [None, [], "empty", 0, False])
def test_build_payload__nondict_goal_constraints__rejects_without_coercion(
    focal_wire: dict[str, Any],
    invalid: Any,
) -> None:
    body = json.loads(focal_wire["prompt"])
    body["input"]["goal_candidate"]["constraints"] = invalid
    _write_body(focal_wire, body)

    with pytest.raises(ValueError):
        candidate.build_payload(focal_wire)


def test_build_payload__missing_goal_constraints__rejects_without_defaulting(
    focal_wire: dict[str, Any],
) -> None:
    body = json.loads(focal_wire["prompt"])
    del body["input"]["goal_candidate"]["constraints"]
    _write_body(focal_wire, body)

    with pytest.raises(ValueError):
        candidate.build_payload(focal_wire)


@pytest.mark.parametrize("drift", ["input_mismatch", "trailing_text", "missing_newline"])
def test_build_payload__system_input_not_exact__rejects_instead_of_recovering(
    focal_wire: dict[str, Any],
    drift: str,
) -> None:
    if drift == "input_mismatch":
        body = json.loads(focal_wire["prompt"])
        body["input"]["user_request"] = "다른 요청"
        _write_body(focal_wire, body, bind_system=False)
    elif drift == "trailing_text":
        focal_wire["system"] += "another instruction"
    else:
        focal_wire["system"] = focal_wire["system"].removesuffix("\n")

    with pytest.raises(ValueError):
        candidate.build_payload(focal_wire)


@pytest.mark.parametrize(
    "drift", ["repair", "extra_input", "missing_focus", "extra_envelope", "missing_input"]
)
def test_build_payload__nonfocal_first_envelope__rejects_before_dispatch(
    focal_wire: dict[str, Any],
    drift: str,
) -> None:
    body = json.loads(focal_wire["prompt"])
    if drift == "repair":
        body["input"] = {"base_projection": body["input"], "candidate_output": {}}
    elif drift == "extra_input":
        body["input"]["interpretation_candidate"] = "not this comparison"
    elif drift == "missing_focus":
        del body["input"]["assessment_resource_type"]
    elif drift == "extra_envelope":
        body["failure_record"] = {}
    else:
        del body["input"]
    _write_body(focal_wire, body, bind_system=drift != "missing_input")

    with pytest.raises(ValueError):
        candidate.build_payload(focal_wire)
