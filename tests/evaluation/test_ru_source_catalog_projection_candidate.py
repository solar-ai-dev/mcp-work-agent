"""V45 admission and exact metadata-only projection; no inference is performed."""

from __future__ import annotations

import json
from copy import deepcopy
from typing import Any

import pytest
from scripts import ru_source_catalog_projection_candidate as candidate

from google_work_agent.application.agents.request_understanding.identify_source_dependencies import (  # noqa: E501
    build_source_dependency_candidates,
    build_source_dependency_output_schema,
)
from google_work_agent.application.prompt_runtime.assemble_prompt import assemble_prompt
from google_work_agent.application.prompt_runtime.prompt_registry import EVALUATION, PromptRegistry
from google_work_agent.application.tool_registry.load_signed_tool_registry import (
    load_development_tool_registry,
)


@pytest.fixture
def product_payload() -> dict[str, Any]:
    request = "선택한 자료의 read_tool_ids라는 문구를 확인해줘."
    registry = PromptRegistry()
    ref = registry.lookup_for_evaluation(candidate.PROMPT_ID)
    catalog = list(build_source_dependency_candidates(load_development_tool_registry()))
    projection = {
        "user_request": request,
        "selected_resource_refs": [],
        "run_reference_time": {"now_utc": "2026-09-29T00:00:00Z"},
        "goal_candidate": {"goal": request},
        "source_candidates": catalog,
        "requested_work": {
            "work_units": [
                {
                    "unit_id": "live-work",
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
    schema = build_source_dependency_output_schema(catalog, work_unit_ids=["live-work"])
    return {
        "model": "fake-no-http",
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


def test_only_catalog_tool_metadata_changes_in_both_input_copies(
    product_payload: dict[str, Any],
) -> None:
    before = deepcopy(product_payload)
    original_body = json.loads(before["prompt"])
    expected_body = deepcopy(original_body)
    for item in expected_body["input"]["source_candidates"]:
        del item["read_tool_ids"]

    result = candidate.build_payload(product_payload)

    assert product_payload == before
    assert {key for key in result if result[key] != before[key]} == {"system", "prompt"}
    assert json.loads(result["prompt"]) == expected_body
    original_json = json.dumps(
        original_body["input"], ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    candidate_json = json.dumps(
        expected_body["input"], ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    unchanged_prefix = before["system"][: -len(original_json + "\n")]
    assert result["system"] == unchanged_prefix + candidate_json + "\n"
    assert result["system"].startswith(PromptRegistry().source_text(candidate.PROMPT_ID).rstrip())
    assert result["format"] == expected_body["output_schema"] == before["format"]
    assert "read_tool_ids" in expected_body["input"]["user_request"]
    assert all(
        set(item) == {"resource_type", "owned_fact_kinds"}
        for item in expected_body["input"]["source_candidates"]
    )
    assert len(expected_body["input"]["source_candidates"]) == len(
        original_body["input"]["source_candidates"]
    )
    assert candidate.CANDIDATE_ID not in result["prompt"]
    assert candidate.INPUT_CONTRACT not in result["system"]
    result["options"]["temperature"] = 1
    result["format"].clear()
    assert product_payload == before


@pytest.mark.parametrize(
    "drift", ["ref", "system", "schema", "format", "revision", "repair", "candidate", "envelope"]
)
def test_current_product_and_first_envelope_drift_is_rejected(
    product_payload: dict[str, Any], drift: str
) -> None:
    body = json.loads(product_payload["prompt"])
    if drift == "ref":
        body["prompt_ref"]["content_hash"] = "other"
    elif drift == "system":
        product_payload["system"] += "changed"
    elif drift == "schema":
        body["output_schema"] = {}
    elif drift == "format":
        product_payload["format"] = {}
    elif drift == "revision":
        body["input"]["base_projection"] = {}
    elif drift == "repair":
        body["input"]["failure_record"] = {}
    elif drift == "candidate":
        body["input"]["candidate_output"] = {}
    else:
        body["case_id"] = "not-model-input"
    product_payload["prompt"] = json.dumps(body)
    before = deepcopy(product_payload)
    with pytest.raises(ValueError):
        candidate.build_payload(product_payload)
    assert product_payload == before


@pytest.mark.parametrize(
    "drift", ["missing", "unknown", "write", "empty", "duplicate", "resource", "facts"]
)
def test_original_catalog_must_retain_current_registry_read_eligibility(
    product_payload: dict[str, Any], drift: str
) -> None:
    body = json.loads(product_payload["prompt"])
    old_json = json.dumps(body["input"], ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    catalog = body["input"]["source_candidates"]
    if drift == "missing":
        del catalog[0]["read_tool_ids"]
    elif drift == "unknown":
        catalog[0]["read_tool_ids"] = ["unknown_read"]
    elif drift == "write":
        catalog[0]["read_tool_ids"] = ["tasks_create_task"]
    elif drift == "empty":
        catalog[0]["read_tool_ids"] = []
    elif drift == "duplicate":
        catalog.append(deepcopy(catalog[0]))
    elif drift == "resource":
        catalog[0]["resource_type"] = "UNKNOWN_RESOURCE"
    else:
        catalog[0]["owned_fact_kinds"] = ["invented_fact"]
    new_json = json.dumps(body["input"], ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    product_payload["system"] = product_payload["system"][: -len(old_json + "\n")] + new_json + "\n"
    product_payload["prompt"] = json.dumps(body)
    before = deepcopy(product_payload)
    with pytest.raises(ValueError, match="catalog"):
        candidate.build_payload(product_payload)
    assert product_payload == before
