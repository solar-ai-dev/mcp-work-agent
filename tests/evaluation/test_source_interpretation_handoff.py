"""Synthetic wire/owner controls only; no saved trials, HTTP, or semantic judge."""

from __future__ import annotations

import json
from copy import deepcopy
from typing import Any

import pytest
from scripts import evaluate_source_interpretation_handoff as runner

from google_work_agent.application.agents.request_understanding.identify_source_dependencies import (  # noqa: E501
    build_source_dependency_candidates,
    build_source_dependency_output_schema,
)
from google_work_agent.application.prompt_runtime.assemble_prompt import assemble_prompt
from google_work_agent.application.prompt_runtime.prompt_registry import EVALUATION, PromptRegistry
from google_work_agent.application.tool_registry.load_signed_tool_registry import (
    load_development_tool_registry,
)

PROMPT_ID = "request_understanding.identify_source_dependencies"
INTERPRETATION = (
    "최종 결과는 작업 목록의 제목과 상태다.\n  기존 작업이 필요하며 새 작업은 만들지 않는다."
)


@pytest.fixture
def product_wire() -> dict[str, Any]:
    request = "작업 목록의 제목과 상태를 알려줘. 새 작업은 만들지 마."
    registry = PromptRegistry()
    ref = registry.lookup_for_evaluation(PROMPT_ID)
    candidates = list(build_source_dependency_candidates(load_development_tool_registry()))
    projection = {
        "user_request": request,
        "selected_resource_refs": [],
        "run_reference_time": {"now_utc": "2026-09-29T00:00:00Z"},
        "goal_candidate": {"goal": request},
        "source_candidates": candidates,
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
    }
    schema = build_source_dependency_output_schema(candidates, work_unit_ids=["work-1"])
    return {
        "model": "qwen3.5:9b",
        "system": assemble_prompt(ref, projection, registry=registry, execution_scope=EVALUATION),
        "prompt": json.dumps(
            {
                "prompt_ref": {
                    "prompt_id": ref.prompt_id,
                    "prompt_version": ref.prompt_version,
                    "content_hash": ref.content_hash,
                },
                "input": projection,
                "output_schema": schema.json_schema,
            },
            ensure_ascii=False,
            sort_keys=True,
        ),
        "format": deepcopy(schema.json_schema),
        "stream": False,
        "think": False,
        "options": {"num_ctx": 16_384, "temperature": 0.05, "seed": 20260923},
    }


def _source_case(payload: dict[str, Any]) -> dict[str, Any]:
    body = json.loads(payload["prompt"])
    return {
        "owner": "source",
        "source_call": {
            "prompt_id": PROMPT_ID,
            "prompt_ref": body["prompt_ref"],
            "input": body["input"],
            "output_schema": body["output_schema"],
        },
    }


def _source_result(case: dict[str, Any], *, required: bool = True) -> dict[str, Any]:
    return {
        "source_dependencies": [
            {
                "resource_type": source["resource_type"],
                "dependency": "SOURCE_REQUIRED",
                "required_information": ["title", "completion_status"],
                "target_scope": "CRITERIA",
                "work_unit_ids": ["work-1"],
            }
            if required and source["resource_type"] == "TASK"
            else {"resource_type": source["resource_type"], "dependency": "SOURCE_NOT_REQUIRED"}
            for source in case["source_call"]["input"]["source_candidates"]
        ]
    }


def test_build_payload__current_product_first__preserves_wire_and_adds_exact_interpretation(
    product_wire: dict[str, Any],
) -> None:
    original = deepcopy(product_wire)
    baseline_body = json.loads(original["prompt"])
    candidate = runner.build_payload(product_wire, INTERPRETATION)
    body = json.loads(candidate["prompt"])

    assert product_wire == original
    assert set(candidate) == set(original)
    assert {key: value for key, value in candidate.items() if key not in {"system", "prompt"}} == {
        key: value for key, value in original.items() if key not in {"system", "prompt"}
    }
    assert set(body) == set(baseline_body)
    assert body["input"] == {
        **baseline_body["input"],
        "interpretation_candidate": INTERPRETATION,
    }
    assert body["output_schema"] == baseline_body["output_schema"] == candidate["format"]
    assert body["prompt_ref"] != baseline_body["prompt_ref"]
    assert body["prompt_ref"]["content_hash"] != baseline_body["prompt_ref"]["content_hash"]
    projection_json = json.dumps(
        body["input"], ensure_ascii=False, separators=(",", ":"), sort_keys=True
    )
    assert projection_json in candidate["system"]
    assert body["input"]["interpretation_candidate"] == INTERPRETATION
    assert not {"gold", "evaluation_gold", "expected_semantics", "thinking"} & set(body["input"])
    candidate["options"]["num_ctx"] = 1
    assert product_wire == original


@pytest.mark.parametrize("interpretation", ["", " ", "\n\t"])
def test_build_payload__empty_interpretation__rejects_before_dispatch(
    product_wire: dict[str, Any],
    interpretation: str,
) -> None:
    with pytest.raises(ValueError):
        runner.build_payload(product_wire, interpretation)


@pytest.mark.parametrize("drift", ["ref", "schema", "format", "catalog", "system", "revision"])
def test_build_payload__untrusted_first_authority__rejects_before_dispatch(
    product_wire: dict[str, Any],
    drift: str,
) -> None:
    body = json.loads(product_wire["prompt"])
    if drift == "ref":
        body["prompt_ref"]["content_hash"] = "not-the-registered-hash"
    elif drift == "schema":
        body["output_schema"] = {"type": "object"}
    elif drift == "format":
        product_wire["format"] = {"type": "object"}
    elif drift == "catalog":
        body["input"]["source_candidates"] = []
        ref = PromptRegistry().lookup_for_evaluation(PROMPT_ID)
        product_wire["system"] = assemble_prompt(ref, body["input"], execution_scope=EVALUATION)
    elif drift == "system":
        product_wire["system"] += "\nUnregistered instruction"
    else:
        body["input"] = {"base_projection": body["input"], "candidate_output": {}}
    product_wire["prompt"] = json.dumps(body, ensure_ascii=False, sort_keys=True)

    with pytest.raises(ValueError):
        runner.build_payload(product_wire, INTERPRETATION)


def test_admit_source__valid_exact_set__preserves_facts_scope_and_work_binding(
    product_wire: dict[str, Any],
) -> None:
    case = _source_case(product_wire)
    source = _source_result(case)
    original = deepcopy((case, source))
    result = runner.admit_source(json.dumps(source), case)

    assert result["validation"]["structural_result"] == "VALIDATED"
    assert result["validation"]["validated_output"] == source
    assert result["merged_source_reads"] == [
        {
            "resource_type": "TASK",
            "required_information": ["title", "completion_status"],
            "target_scope": "CRITERIA",
            "work_unit_ids": ["work-1"],
        }
    ]
    assert (case, source) == original


@pytest.mark.parametrize(
    "invalid", ["unknown_work", "missing_resource", "duplicate_resource", "invalid_json"]
)
def test_admit_source__invalid_owner_result__does_not_merge_or_repair(
    product_wire: dict[str, Any],
    invalid: str,
) -> None:
    case = _source_case(product_wire)
    source = _source_result(case)
    if invalid == "unknown_work":
        task = next(
            item for item in source["source_dependencies"] if item["resource_type"] == "TASK"
        )
        task["work_unit_ids"] = ["not-a-current-work"]
    elif invalid == "missing_resource":
        source["source_dependencies"].pop()
    elif invalid == "duplicate_resource":
        source["source_dependencies"][-1] = deepcopy(source["source_dependencies"][0])
    content = "not JSON" if invalid == "invalid_json" else json.dumps(source)
    result = runner.admit_source(content, case)

    assert result["validation"]["structural_result"] != "VALIDATED"
    assert not result.get("merged_source_reads")


def test_admit_source__explicit_no_source__preserves_empty_without_inventing_read(
    product_wire: dict[str, Any],
) -> None:
    case = _source_case(product_wire)
    result = runner.admit_source(json.dumps(_source_result(case, required=False)), case)

    assert result["validation"]["structural_result"] == "VALIDATED"
    assert result["merged_source_reads"] == []
