from copy import deepcopy

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


@pytest.mark.parametrize("roles", [
    ("CONTEXT", "SUPPORTS"), ("CONTRADICTS", "CONTEXT"),
    ("EXCLUDED", "SUPPORTS"), ("EXCLUDED", "EXCLUDED"),
])
def test_each_visible_source_requires_one_explicit_assessment(roles):
    schema = bind_evidence_selection_schema(
        candidate_resource_refs={"mail": "gmail_thread:1", "task": "task:2"}, max_evidence=12,
    )
    output = {"schema_version": 3, "segment_assessments": {
        key: {"role": role, "relevance_reason": "후속 업무 확인 대상 또는 무관한 후보"}
        for key, role in zip(("mail", "task"), roles, strict=True)
    }}
    assert validate_output_schema(output, schema.json_schema) == []
    missing = deepcopy(output)
    del missing["segment_assessments"]["task"]
    assert validate_output_schema(missing, schema.json_schema)
    invented = deepcopy(output)
    invented["segment_assessments"]["invented"] = output["segment_assessments"]["mail"]
    assert validate_output_schema(invented, schema.json_schema)


@pytest.mark.parametrize("assessment", [
    {"role": "EXCLUDED"}, {"role": "EXCLUDED", "relevance_reason": ""},
    {"role": "SUCCESS", "relevance_reason": "임의 성공"},
    {"role": "CONTEXT", "relevance_reason": "관련 자료", "segment_id": "other"},
])
def test_unsupported_role_missing_reason_or_parallel_identity_is_rejected(assessment):
    schema = bind_evidence_selection_schema(
        candidate_resource_refs={"mail": "gmail_thread:1"}, max_evidence=12,
    )
    assert validate_output_schema(
        {"schema_version": 3, "segment_assessments": {"mail": assessment}}, schema.json_schema,
    )


def test_empty_candidates_do_not_require_invented_evidence():
    schema = bind_evidence_selection_schema(candidate_resource_refs={}, max_evidence=12)
    assert validate_output_schema(
        {"schema_version": 3, "segment_assessments": {}}, schema.json_schema,
    ) == []


def test_old_inference_shape_is_not_silently_accepted():
    schema = bind_evidence_selection_schema(candidate_resource_refs={}, max_evidence=12)
    assert validate_output_schema(
        {"schema_version": 2, "selected_segment_ids": [], "excluded_segment_ids": [],
         "evidence_drafts": []}, schema.json_schema,
    )


def test_visible_candidates_cannot_exceed_evidence_budget():
    with pytest.raises(ValueError, match="budget"):
        bind_evidence_selection_schema(
            candidate_resource_refs={"mail": "gmail_thread:1", "task": "task:2"}, max_evidence=1,
        )


def test_inference_schema_version_matches_prompt_contract_and_manifest():
    import json

    contract = next(entry for entry in load_prompt_input_contract().entries
                    if entry.prompt_slot_id == "retrieval.select_evidence")
    manifest = json.loads(default_prompt_manifest_path().read_text(encoding="utf-8"))
    slot = next(item for item in manifest["slots"]
                if item["prompt_slot_id"] == "retrieval.select_evidence")
    schema = bind_evidence_selection_schema(candidate_resource_refs={}, max_evidence=12)
    version = schema.json_schema["properties"]["schema_version"]["enum"][0]
    assert version == contract.output_schema_version == slot["output_schema_version"] == 3
    assert contract.input_schema_version == slot["input_schema_version"] == 3
