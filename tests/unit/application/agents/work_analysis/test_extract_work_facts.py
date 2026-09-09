from typing import cast

import pytest

from google_work_agent.application.agents.work_analysis.extract_work_facts import extract_work_facts
from google_work_agent.ports.llm.output_schema_validation import validate_output_schema
from google_work_agent.ports.llm.structured_inference_contracts import PromptReference
from tests.support.work_analysis import WorkAnalysisRuntimeFake, output_json_schema, prompt_ref


def test_extract_work_facts__uses_exact_contract__and_bounded_evidence() -> None:
    output = {
        "fact_candidates": [
            {
                "kind": "TASK",
                "subject": "report",
                "value": "submit",
                "derivation": "EXPLICIT",
                "evidence_refs": ["ev-1"],
            }
        ]
    }
    runtime = WorkAnalysisRuntimeFake(output)
    result = extract_work_facts(
        semantic_input={"user_request": "submit", "request_intent": {}, "evidence": []},
        llm_runtime=runtime,
        prompt_ref=prompt_ref("work_analysis.extract_work_facts", "extract_work_facts"),
        allowed_evidence_refs={"ev-1"},
        requested_mode="AUTO",
    )
    assert len(result) == 1
    assert result[0]["fact_id"].startswith("fact-")
    assert {key: value for key, value in result[0].items() if key != "fact_id"} == output[
        "fact_candidates"
    ][0]
    assert (
        cast(PromptReference, runtime.calls[0]["prompt_ref"]).prompt_id
        == "work_analysis.extract_work_facts"
    )
    schema = output_json_schema(runtime)
    refs_schema = schema["properties"]["fact_candidates"]["items"]["properties"]["evidence_refs"]
    assert refs_schema["uniqueItems"] is True
    assert refs_schema["items"] == {"type": "string", "enum": ["ev-1"]}
    candidate_schema = schema["properties"]["fact_candidates"]["items"]
    assert "fact_id" not in candidate_schema["required"]
    assert "fact_id" not in candidate_schema["properties"]


def test_extract_work_facts__repeated_candidates__assigns_unique_ids() -> None:
    candidate = {
        "kind": "TEXT_CLAIM",
        "subject": "latest decision",
        "value": "use the revised schedule",
        "derivation": "EXPLICIT",
        "evidence_refs": ["ev-1"],
    }
    runtime = WorkAnalysisRuntimeFake({"fact_candidates": [candidate, candidate]})

    result = extract_work_facts(
        semantic_input={"user_request": "latest decision", "request_intent": {}, "evidence": []},
        llm_runtime=runtime,
        prompt_ref=prompt_ref("work_analysis.extract_work_facts", "extract_work_facts"),
        allowed_evidence_refs={"ev-1"},
        requested_mode="AUTO",
    )

    assert len({fact["fact_id"] for fact in result}) == 2


def test_extract_work__facts_rejects_old__or_stale_schema() -> None:
    runtime = WorkAnalysisRuntimeFake(
        {"fact_candidates": [{"fact_type": "TASK", "value": "x", "evidence_refs": ["stale"]}]}
    )
    with pytest.raises(ValueError, match="WorkFactV1"):
        extract_work_facts(
            semantic_input={"user_request": "x", "request_intent": {}, "evidence": []},
            llm_runtime=runtime,
            prompt_ref=prompt_ref("work_analysis.extract_work_facts", "extract_work_facts"),
            allowed_evidence_refs={"ev-1"},
            requested_mode="AUTO",
        )


def test_extract_work_facts__empty_evidence__does_not_prove_creation() -> None:
    runtime = WorkAnalysisRuntimeFake({"fact_candidates": []})
    result = extract_work_facts(
        semantic_input={
            "user_request": "보고서 태스크를 만들어줘",
            "request_intent": {"completion_conditions": ["보고서 태스크가 존재함"]},
            "evidence": [],
        },
        llm_runtime=runtime,
        prompt_ref=prompt_ref("work_analysis.extract_work_facts", "extract_work_facts"),
        allowed_evidence_refs=set(),
        requested_mode="LOCAL_GPU",
    )
    assert result == []
    schema = output_json_schema(runtime)
    assert not validate_output_schema({"fact_candidates": []}, schema)
    assert validate_output_schema(
        {
            "fact_candidates": [
                {
                    "kind": "TASK",
                    "subject": "보고서",
                    "value": "태스크가 존재함",
                    "derivation": "EXPLICIT",
                    "evidence_refs": [],
                }
            ]
        },
        schema,
    )


def test_task_duplicate_review__requires_selected_task_observation__to_be_represented() -> None:
    runtime = WorkAnalysisRuntimeFake({"fact_candidates": []})

    with pytest.raises(ValueError, match="selected Task observation"):
        extract_work_facts(
            semantic_input={
                "user_request": "태스크를 만들어줘",
                "request_intent": {"requested_effect_hints": ["CREATE"]},
                "evidence": [
                    {
                        "evidence_id": "ev-task",
                        "resource_handle": "task:existing",
                    }
                ],
                "task_duplicate_review_required": True,
            },
            llm_runtime=runtime,
            prompt_ref=prompt_ref("work_analysis.extract_work_facts", "extract_work_facts"),
            allowed_evidence_refs={"ev-task"},
            requested_mode="LOCAL_GPU",
        )
