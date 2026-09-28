"""Pure v43 contract/projection controls, not model or decomposition quality."""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from typing import Any

import pytest
from scripts import ru_source_membership_candidate as candidate

from google_work_agent.application.agents.request_understanding.contracts.source_dependency_decision import (  # noqa: E501
    SourceDependencyCandidateV1,
)
from google_work_agent.application.agents.request_understanding.identify_source_dependencies import (  # noqa: E501
    build_source_dependency_output_schema,
    validate_source_dependency_candidate,
)
from google_work_agent.application.prompt_runtime.assemble_prompt import assemble_prompt
from google_work_agent.application.prompt_runtime.prompt_registry import EVALUATION, PromptRegistry
from google_work_agent.ports.llm.output_schema_validation import validate_output_schema


@pytest.fixture
def catalog() -> list[SourceDependencyCandidateV1]:
    return [
        {
            "resource_type": "TASK",
            "owned_fact_kinds": ["title", "notes", "completion_status"],
            "read_tool_ids": ["tasks_get_task"],
        },
        {
            "resource_type": "CALENDAR_EVENT",
            "owned_fact_kinds": ["title", "start", "end"],
            "read_tool_ids": ["calendar_get_event"],
        },
    ]


def _membership(
    task: str = "SOURCE_REQUIRED", event: str = "SOURCE_NOT_REQUIRED"
) -> dict[str, Any]:
    return {"resource_decisions": {"TASK": task, "CALENDAR_EVENT": event}}


def _details() -> dict[str, Any]:
    return {
        "source_details": {
            "TASK": {
                "required_information": ["completion_status"],
                "target_scope": "SINGULAR",
                "work_unit_ids": ["work-2"],
            }
        }
    }


@pytest.fixture
def product_payload(catalog: list[SourceDependencyCandidateV1]) -> dict[str, Any]:
    first = "선택한 자료를 읽어줘."
    second = "현재 상태를 알려줘."
    request = first + " " + second
    ref = PromptRegistry().lookup_for_evaluation(candidate.PROMPT_ID)
    projection = {
        "user_request": request,
        "selected_resource_refs": [],
        "run_reference_time": {"now_utc": "2026-09-28T00:00:00Z"},
        "goal_candidate": {"goal": request},
        "source_candidates": catalog,
        "requested_work": {
            "work_units": [
                {
                    "unit_id": unit,
                    "request_provenance": [
                        {
                            "source": "USER_REQUEST",
                            "source_text": text,
                            "start_offset": start,
                            "end_offset": start + len(text),
                        }
                    ],
                }
                for unit, text, start in (
                    ("work-1", first, 0),
                    ("work-2", second, len(first) + 1),
                )
            ],
            "work_relations": [],
        },
    }
    schema = build_source_dependency_output_schema(catalog, work_unit_ids=["work-1", "work-2"])
    return {
        "model": "fake-no-http",
        "system": assemble_prompt(ref, projection, execution_scope=EVALUATION),
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
            sort_keys=True,
            ensure_ascii=False,
        ),
        "format": deepcopy(schema.json_schema),
        "stream": False,
        "think": False,
        "options": {"num_ctx": 16_384, "temperature": 0.05, "seed": 20260923},
    }


def test_membership_exact_key_set_requires_explicit_negative_decisions(
    catalog: list[SourceDependencyCandidateV1],
) -> None:
    value = _membership()
    schema = candidate.build_membership_schema(catalog).json_schema
    assert validate_output_schema(value, schema) == []
    assert candidate.validate_membership(value, catalog) == value
    missing = deepcopy(value)
    del missing["resource_decisions"]["CALENDAR_EVENT"]
    with pytest.raises(ValueError, match="membership"):
        candidate.validate_membership(missing, catalog)
    unknown = deepcopy(value)
    unknown["resource_decisions"]["OTHER"] = "SOURCE_NOT_REQUIRED"
    with pytest.raises(ValueError, match="membership"):
        candidate.validate_membership(unknown, catalog)


@pytest.mark.parametrize("invalid", [None, True, "NOT_REQUIRED", {}, ["SOURCE_REQUIRED"]])
def test_membership_never_coerces_invalid_choice(
    catalog: list[SourceDependencyCandidateV1], invalid: Any
) -> None:
    value = _membership()
    value["resource_decisions"]["TASK"] = invalid
    with pytest.raises(ValueError):
        candidate.validate_membership(value, catalog)


def test_details_reuse_all_existing_positive_field_constraints(
    catalog: list[SourceDependencyCandidateV1],
) -> None:
    current = build_source_dependency_output_schema(catalog[:1], work_unit_ids=["work-2"])
    original: Any = current.json_schema
    positive = original["properties"]["source_dependencies"]["items"]["oneOf"][1]
    details: Any = candidate.build_details_schema(catalog[:1], ["work-2"]).json_schema
    task = details["properties"]["source_details"]["properties"]["TASK"]
    expected = set(positive["required"]) - {"resource_type", "dependency"}
    assert set(task["required"]) == expected
    assert task["properties"] == {name: positive["properties"][name] for name in expected}
    assert details["properties"]["source_details"]["required"] == ["TASK"]


def test_projection_preserves_explicit_membership_and_binding_without_guessing(
    catalog: list[SourceDependencyCandidateV1],
) -> None:
    membership, details = _membership(), _details()
    before = deepcopy((membership, details, catalog))
    result = candidate.materialize_decisions(membership, details, catalog, ["work-1", "work-2"])
    assert result == {
        "source_dependencies": [
            {
                "resource_type": "TASK",
                "dependency": "SOURCE_REQUIRED",
                **details["source_details"]["TASK"],
            },
            {"resource_type": "CALENDAR_EVENT", "dependency": "SOURCE_NOT_REQUIRED"},
        ]
    }
    assert (
        validate_source_dependency_candidate(
            result, source_candidates=catalog, work_unit_ids=["work-1", "work-2"]
        )
        == result
    )
    result["source_dependencies"][0]["required_information"].append("changed")
    assert (membership, details, catalog) == before


@pytest.mark.parametrize(
    "drift",
    [
        "missing_selected",
        "added_unselected",
        "reselect",
        "unknown_work",
        "no_work",
        "empty",
        "blank",
        "over_limit",
        "scope",
    ],
)
def test_details_cannot_drop_or_reselect_or_invent_closed_binding(
    catalog: list[SourceDependencyCandidateV1], drift: str
) -> None:
    details = _details()
    task = details["source_details"]["TASK"]
    if drift == "missing_selected":
        del details["source_details"]["TASK"]
    elif drift == "added_unselected":
        details["source_details"]["CALENDAR_EVENT"] = deepcopy(task)
    elif drift == "reselect":
        task["dependency"] = "SOURCE_NOT_REQUIRED"
    elif drift == "unknown_work":
        task["work_unit_ids"] = ["unknown"]
    elif drift == "no_work":
        task["work_unit_ids"] = []
    elif drift == "empty":
        task["required_information"] = []
    elif drift == "blank":
        task["required_information"] = [" {}[] "]
    elif drift == "over_limit":
        task["required_information"] = [str(index) for index in range(9)]
    else:
        task["target_scope"] = "ALL"
    with pytest.raises(ValueError):
        candidate.materialize_decisions(_membership(), details, catalog, ["work-1", "work-2"])


def test_all_negative_is_explicit_not_a_missing_key_default(
    catalog: list[SourceDependencyCandidateV1], product_payload: dict[str, Any]
) -> None:
    negative = _membership("SOURCE_NOT_REQUIRED")
    assert (
        candidate.build_stage_payload(product_payload, stage="details", membership=negative) is None
    )
    result = candidate.materialize_decisions(negative, None, catalog, ["work-1", "work-2"])
    assert all(
        set(item) == {"resource_type", "dependency"} for item in result["source_dependencies"]
    )
    with pytest.raises(ValueError, match="no details"):
        candidate.materialize_decisions(negative, {"source_details": {}}, catalog, ["work-1"])
    with pytest.raises(ValueError, match="details"):
        candidate.materialize_decisions(_membership(), None, catalog, ["work-1"])


@pytest.mark.parametrize("stage", ["membership", "details"])
def test_payload_changes_only_stage_contract_and_keeps_original_input_and_runtime(
    product_payload: dict[str, Any], stage: Any
) -> None:
    original = deepcopy(product_payload)
    body = json.loads(original["prompt"])
    membership = _membership() if stage == "details" else None
    result = candidate.build_stage_payload(product_payload, stage=stage, membership=membership)
    assert result is not None
    assert product_payload == original
    changed = {key for key in result if result[key] != original[key]}
    assert changed == {"system", "prompt", "format"}
    new_body = json.loads(result["prompt"])
    expected_input = deepcopy(body["input"])
    if membership is not None:
        expected_input["resource_decisions"] = membership["resource_decisions"]
    assert new_body["input"] == expected_input
    assert new_body["output_schema"] == result["format"]
    assert new_body["prompt_ref"] == {
        "prompt_id": candidate.PROMPT_ID,
        "prompt_version": f"evaluation-v43-{stage}",
        "content_hash": hashlib.sha256(candidate.PROMPT_PATHS[stage].read_bytes()).hexdigest(),
    }
    source = PromptRegistry().source_text(candidate.PROMPT_ID).rstrip()
    before_json = json.dumps(
        body["input"], ensure_ascii=False, separators=(",", ":"), sort_keys=True
    )
    suffix = original["system"][len(source) : -len(before_json + "\n")]
    assert result["system"] == (
        candidate.PROMPT_PATHS[stage].read_bytes().decode("utf-8").rstrip()
        + suffix
        + json.dumps(expected_input, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        + "\n"
    )


@pytest.mark.parametrize("drift", ["ref", "system", "schema", "format", "revision", "old_decision"])
def test_payload_rejects_noncurrent_or_unbound_original_authority(
    product_payload: dict[str, Any], drift: str
) -> None:
    body = json.loads(product_payload["prompt"])
    if drift == "ref":
        body["prompt_ref"]["content_hash"] = "not-current"
    elif drift == "system":
        product_payload["system"] += "changed"
    elif drift == "schema":
        body["output_schema"] = {}
    elif drift == "format":
        product_payload["format"] = {}
    elif drift == "revision":
        body["input"]["base_projection"] = {}
    else:
        body["input"]["resource_decisions"] = {}
    product_payload["prompt"] = json.dumps(body)
    with pytest.raises(ValueError):
        candidate.build_stage_payload(product_payload, stage="membership")


def test_schema_builders_reject_empty_or_duplicate_catalog(
    catalog: list[SourceDependencyCandidateV1],
) -> None:
    for invalid in ([], [catalog[0], catalog[0]]):
        with pytest.raises(ValueError):
            candidate.build_membership_schema(invalid)
        with pytest.raises(ValueError):
            candidate.build_details_schema(invalid, ["work-1"])


def test_wrong_membership_is_not_repaired_by_request_or_details(
    catalog: list[SourceDependencyCandidateV1], product_payload: dict[str, Any]
) -> None:
    wrong = _membership("SOURCE_NOT_REQUIRED", "SOURCE_REQUIRED")
    second = candidate.build_stage_payload(product_payload, stage="details", membership=wrong)
    assert second is not None
    assert second["format"]["properties"]["source_details"]["required"] == ["CALENDAR_EVENT"]
    details = {"source_details": {"CALENDAR_EVENT": _details()["source_details"]["TASK"]}}
    result = candidate.materialize_decisions(wrong, details, catalog, ["work-1", "work-2"])
    assert result["source_dependencies"][0]["dependency"] == "SOURCE_NOT_REQUIRED"
    # Structural admission is not evidence that this Resource choice is correct.
