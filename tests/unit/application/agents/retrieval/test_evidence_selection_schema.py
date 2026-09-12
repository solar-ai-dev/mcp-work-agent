from copy import deepcopy
from typing import Any, cast

import pytest

from google_work_agent.application.agents.retrieval.contracts.evidence_selection_schema import (
    bind_evidence_selection_schema,
)
from google_work_agent.application.prompt_runtime.load_prompt_input_contract import (
    load_prompt_input_contract,
)
from google_work_agent.application.prompt_runtime.prompt_registry import (
    default_prompt_manifest_path,
)
from google_work_agent.ports.llm.output_schema_validation import validate_output_schema


@pytest.mark.parametrize(
    "roles",
    [
        ("CONTEXT", "SUPPORTS"),
        ("CONTRADICTS", "CONTEXT"),
        ("EXCLUDED", "SUPPORTS"),
        ("EXCLUDED", "EXCLUDED"),
    ],
)
def test_source_assessment__visible_candidates__requires_one_per_source(
    roles: tuple[str, str],
) -> None:
    schema = bind_evidence_selection_schema(
        candidate_resource_refs={"mail": "gmail_thread:1", "task": "task:2"},
        max_evidence=12,
    )
    output: dict[str, Any] = {
        "schema_version": 3,
        "segment_assessments": {
            key: {"role": role, "relevance_reason": "후속 업무 확인 대상 또는 무관한 후보"}
            for key, role in zip(("mail", "task"), roles, strict=True)
        },
    }
    assert validate_output_schema(output, schema.json_schema) == []
    missing = deepcopy(output)
    del missing["segment_assessments"]["task"]
    assert validate_output_schema(missing, schema.json_schema)
    invented = deepcopy(output)
    invented["segment_assessments"]["invented"] = output["segment_assessments"]["mail"]
    assert validate_output_schema(invented, schema.json_schema)


@pytest.mark.parametrize(
    "assessment",
    [
        {"role": "EXCLUDED"},
        {"role": "EXCLUDED", "relevance_reason": ""},
        {"role": "SUCCESS", "relevance_reason": "임의 성공"},
        {"role": "CONTEXT", "relevance_reason": "관련 자료", "segment_id": "other"},
    ],
)
def test_source_assessment__invalid_role_reason_or_identity__rejects(
    assessment: dict[str, object],
) -> None:
    schema = bind_evidence_selection_schema(
        candidate_resource_refs={"mail": "gmail_thread:1"},
        max_evidence=12,
    )
    assert validate_output_schema(
        {"schema_version": 3, "segment_assessments": {"mail": assessment}},
        schema.json_schema,
    )


def test_source_assessment__empty_candidates__does_not_invent_evidence() -> None:
    schema = bind_evidence_selection_schema(candidate_resource_refs={}, max_evidence=12)
    assert (
        validate_output_schema(
            {"schema_version": 3, "segment_assessments": {}},
            schema.json_schema,
        )
        == []
    )


def test_source_assessment__old_inference_shape__rejects() -> None:
    schema = bind_evidence_selection_schema(candidate_resource_refs={}, max_evidence=12)
    assert validate_output_schema(
        {
            "schema_version": 2,
            "selected_segment_ids": [],
            "excluded_segment_ids": [],
            "evidence_drafts": [],
        },
        schema.json_schema,
    )


def test_source_assessment__visible_candidates__honors_evidence_budget() -> None:
    with pytest.raises(ValueError, match="budget"):
        bind_evidence_selection_schema(
            candidate_resource_refs={"mail": "gmail_thread:1", "task": "task:2"},
            max_evidence=1,
        )


def test_source_assessment_schema__runtime_version__matches_prompt_and_manifest() -> None:
    import json

    contract = next(
        entry
        for entry in load_prompt_input_contract().entries
        if entry.prompt_slot_id == "retrieval.select_evidence"
    )
    manifest = json.loads(default_prompt_manifest_path().read_text(encoding="utf-8"))
    slot = next(
        item for item in manifest["slots"] if item["prompt_slot_id"] == "retrieval.select_evidence"
    )
    schema = bind_evidence_selection_schema(candidate_resource_refs={}, max_evidence=12)
    json_schema = cast(dict[str, Any], schema.json_schema)
    version = json_schema["properties"]["schema_version"]["enum"][0]
    assert version == contract.output_schema_version == slot["output_schema_version"] == 3
    assert contract.input_schema_version == slot["input_schema_version"] == 5
