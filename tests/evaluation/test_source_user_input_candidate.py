"""Pure role-placement controls; no historical raw, HTTP, or semantic grading."""

from __future__ import annotations

import json
from copy import deepcopy
from typing import Any

import pytest
from scripts import ru_source_user_input_candidate as candidate

PREFIX = "Source owner instruction.\n\nCurrent authority remains unchanged.\n\n"


@pytest.fixture
def wire() -> dict[str, Any]:
    request = "선택 자료의 상태만 알려줘.  만들지는 마."
    projection = {
        "user_request": request,
        "selected_resource_refs": [],
        "run_reference_time": {"now_utc": "2026-09-29T00:00:00Z"},
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
        "goal_candidate": {"goal": request},
        "source_candidates": [{"resource_type": "TASK"}],
    }
    schema = {"type": "object", "properties": {"source_dependencies": {"type": "array"}}}
    body = {
        "prompt_ref": {
            "prompt_id": "request_understanding.identify_source_dependencies",
            "prompt_version": "fixture-only",
            "content_hash": "fixture-hash",
        },
        "input": projection,
        "output_schema": schema,
    }
    return {
        "model": "fake-no-http",
        "system": PREFIX + candidate.INPUT_MARKER + _compact(projection) + "\n",
        "prompt": json.dumps(body, ensure_ascii=False, sort_keys=True),
        "format": deepcopy(schema),
        "options": {"num_ctx": 16_384, "temperature": 0.05, "seed": 20260923},
        "think": False,
        "stream": False,
    }


def _compact(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


@pytest.mark.parametrize("interpretation", [False, True])
def test_build_payload__valid_first__removes_only_system_input_without_mutation(
    wire: dict[str, Any],
    interpretation: bool,
) -> None:
    if interpretation:
        body = json.loads(wire["prompt"])
        body["input"]["interpretation_candidate"] = (
            "상태 확인이 목적이다.\n새 항목은 만들지 않는다."
        )
        body["prompt_ref"] = {
            "prompt_id": "evaluation.source_interpretation_handoff",
            "prompt_version": "v1",
            "content_hash": "separate-evaluation-hash",
        }
        wire["prompt"] = json.dumps(body, ensure_ascii=False, sort_keys=True)
        wire["system"] = PREFIX + candidate.INPUT_MARKER + _compact(body["input"]) + "\n"
    original = deepcopy(wire)

    result = candidate.build_payload(wire)

    assert result == {**original, "system": PREFIX}
    assert candidate.INPUT_MARKER not in result["system"]
    assert result["prompt"] == original["prompt"]
    assert (
        json.loads(result["prompt"])["prompt_ref"] == json.loads(original["prompt"])["prompt_ref"]
    )
    assert wire == original
    result["options"]["temperature"] = 1.0
    result["format"]["properties"]["source_dependencies"]["type"] = "string"
    assert wire == original


@pytest.mark.parametrize(
    "drift",
    ["missing_suffix", "trailing_text", "missing_newline", "input_mismatch", "duplicate_marker"],
)
def test_build_payload__nonexact_system_suffix__rejects_without_extraction(
    wire: dict[str, Any],
    drift: str,
) -> None:
    if drift == "missing_suffix":
        wire["system"] = PREFIX
    elif drift == "trailing_text":
        wire["system"] += "extra instruction"
    elif drift == "missing_newline":
        wire["system"] = wire["system"].removesuffix("\n")
    elif drift == "input_mismatch":
        body = json.loads(wire["prompt"])
        body["input"]["user_request"] = "다른 요청"
        wire["prompt"] = json.dumps(body)
    else:
        wire["system"] = candidate.INPUT_MARKER + wire["system"]

    with pytest.raises(ValueError):
        candidate.build_payload(wire)


@pytest.mark.parametrize(
    "drift", ["missing_input", "repair", "unknown_field", "format", "ref", "invalid_json"]
)
def test_build_payload__nonfirst_or_inconsistent_body__rejects_before_dispatch(
    wire: dict[str, Any],
    drift: str,
) -> None:
    body = json.loads(wire["prompt"])
    if drift == "missing_input":
        del body["input"]
    elif drift == "repair":
        body["input"] = {
            "base_projection": body["input"],
            "candidate_output": {},
            "failure_record": {},
        }
    elif drift == "unknown_field":
        body["input"]["unexpected_context"] = "not permitted"
    elif drift == "format":
        wire["format"] = {"type": "array"}
    elif drift == "ref":
        body["prompt_ref"] = None
    wire["prompt"] = "not JSON" if drift == "invalid_json" else json.dumps(body)

    with pytest.raises(ValueError):
        candidate.build_payload(wire)
