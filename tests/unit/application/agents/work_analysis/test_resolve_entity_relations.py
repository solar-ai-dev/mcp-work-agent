import pytest

from google_work_agent.application.agents.work_analysis.resolve_entity_relations import (
    entity_relation_candidate_llm_required,
    resolve_entity_relations,
)
from tests.support.work_analysis import WorkAnalysisRuntimeFake, fact, prompt_ref


def test_entity_relation__is_candidate__only() -> None:
    output = {
        "relation_candidates": [
            {
                "relation_id": "r1",
                "kind": "ASSIGNED_TO",
                "source_fact_id": "f1",
                "target_fact_id": "f2",
                "evidence_refs": ["ev-1"],
            }
        ]
    }
    result = resolve_entity_relations(
        work_facts=[fact("f1"), fact("f2", "PERSON")],
        evidence=[],
        llm_runtime=WorkAnalysisRuntimeFake(output),
        prompt_ref=prompt_ref("work_analysis.resolve_entity_relations", "resolve_entity_relations"),
        allowed_evidence_refs={"ev-1"},
        requested_mode="AUTO",
    )
    assert result == output["relation_candidates"]


def test_entity_relation__binds_output_references__to_validated_inputs() -> None:
    runtime = WorkAnalysisRuntimeFake({"relation_candidates": []})

    resolve_entity_relations(
        work_facts=[fact("f1"), fact("f2", "PERSON")],
        evidence=[],
        llm_runtime=runtime,
        prompt_ref=prompt_ref("work_analysis.resolve_entity_relations", "resolve_entity_relations"),
        allowed_evidence_refs={"ev-2", "ev-1"},
        requested_mode="AUTO",
    )

    output_schema = runtime.calls[0]["output_schema"]
    properties = output_schema.json_schema["properties"]  # type: ignore[union-attr]
    candidates = properties["relation_candidates"]
    item = candidates["items"]
    item_properties = item["properties"]
    assert candidates["uniqueItems"] is True
    assert item_properties["source_fact_id"]["enum"] == ["f1", "f2"]
    assert item_properties["target_fact_id"]["enum"] == ["f1", "f2"]
    assert item_properties["evidence_refs"]["items"]["enum"] == ["ev-1", "ev-2"]
    assert item["allOf"] == [
        {
            "if": {"properties": {"source_fact_id": {"const": "f1"}}},
            "then": {
                "properties": {
                    "target_fact_id": {"type": "string", "enum": ["f2"]},
                }
            },
        },
        {
            "if": {"properties": {"source_fact_id": {"const": "f2"}}},
            "then": {
                "properties": {
                    "target_fact_id": {"type": "string", "enum": ["f1"]},
                }
            },
        },
    ]


def test_entity_relation__rejects_same_fact__through_bound_schema() -> None:
    output = {
        "relation_candidates": [
            {
                "relation_id": "r1",
                "kind": "RELATED_TO",
                "source_fact_id": "f1",
                "target_fact_id": "f1",
                "evidence_refs": ["ev-1"],
            }
        ]
    }

    with pytest.raises(ValueError, match="entity relation candidate schema"):
        resolve_entity_relations(
            work_facts=[fact("f1"), fact("f2", "PERSON")],
            evidence=[],
            llm_runtime=WorkAnalysisRuntimeFake(output),
            prompt_ref=prompt_ref(
                "work_analysis.resolve_entity_relations", "resolve_entity_relations"
            ),
            allowed_evidence_refs={"ev-1"},
            requested_mode="LOCAL_GPU",
        )


def test_entity_relation__rejects_guarded__kind() -> None:
    output = {
        "relation_candidates": [
            {
                "relation_id": "r1",
                "kind": "DUPLICATES",
                "source_fact_id": "f1",
                "target_fact_id": "f2",
                "evidence_refs": ["ev-1"],
            }
        ]
    }
    with pytest.raises(ValueError, match="entity relation"):
        resolve_entity_relations(
            work_facts=[fact("f1"), fact("f2")],
            evidence=[],
            llm_runtime=WorkAnalysisRuntimeFake(output),
            prompt_ref=prompt_ref(
                "work_analysis.resolve_entity_relations", "resolve_entity_relations"
            ),
            allowed_evidence_refs={"ev-1"},
            requested_mode="AUTO",
        )


def test_entity_relation__without_entity_fact__does_not_require_llm() -> None:
    assert entity_relation_candidate_llm_required(
        [fact("f1", "TASK"), fact("f2", "STATUS")]
    ) is False
    assert entity_relation_candidate_llm_required(
        [fact("f1", "TASK"), fact("f2", "PERSON")]
    ) is True
