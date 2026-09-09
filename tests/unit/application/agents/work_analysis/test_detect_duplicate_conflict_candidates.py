import pytest

from google_work_agent.application.agents.work_analysis import (
    detect_duplicate_conflict_candidates,
)
from tests.support.work_analysis import (
    WorkAnalysisRuntimeFake,
    fact,
    output_json_schema,
    prompt_ref,
)


def test_duplicate_is__never_promoted__by_candidate_operation() -> None:
    output = {
        "relation_candidates": [
            {
                "relation_id": "r1",
                "kind": "DUPLICATES",
                "source_fact_id": "f1",
                "target_fact_id": "f2",
                "evidence_refs": ["ev-1"],
            }
        ],
        "requested_work_status": "SATISFIED",
        "requested_work_reason": "existing task fulfils the request",
        "matched_fact_ids": ["f1"],
        "evidence_refs": ["ev-1"],
    }
    runtime = WorkAnalysisRuntimeFake(output)
    result = detect_duplicate_conflict_candidates.detect_duplicate_conflict_candidates(
        work_facts=[fact("f1"), fact("f2")],
        entity_relations=[],
        evidence=[],
        source_state={
            "source_statuses": [
                {
                    "route_id": "task-read",
                    "resource_type": "TASK",
                    "status": "COMPLETE",
                    "observed_resource_count": 2,
                }
            ]
        },
        request_intent={"requested_effect_hints": ["CREATE"]},
        task_duplicate_review_required=True,
        llm_runtime=runtime,
        prompt_ref=prompt_ref(
            "work_analysis.detect_duplicate_conflict_candidates",
            "detect_duplicate_conflict_candidates",
        ),
        allowed_evidence_refs={"ev-1"},
        requested_mode="AUTO",
    )
    assert result == output
    assert len(runtime.calls) == 1
    assert "validated_relations" not in output
    candidate_schema = output_json_schema(runtime)["properties"]["relation_candidates"]["items"]
    properties = candidate_schema["properties"]
    assert properties["source_fact_id"]["enum"] == ["f1", "f2"]
    assert properties["target_fact_id"]["enum"] == ["f1", "f2"]
    assert properties["evidence_refs"]["items"]["enum"] == ["ev-1"]


def test_duplicate_candidates__without_policy_or_two_facts__materialize_empty_without_llm() -> None:
    runtime = WorkAnalysisRuntimeFake({})

    result = detect_duplicate_conflict_candidates.detect_duplicate_conflict_candidates(
        work_facts=[fact("f1")],
        entity_relations=[],
        evidence=[],
        source_state={},
        request_intent={"requested_effect_hints": ["CREATE"]},
        task_duplicate_review_required=False,
        llm_runtime=runtime,
        prompt_ref=prompt_ref(
            "work_analysis.detect_duplicate_conflict_candidates",
            "detect_duplicate_conflict_candidates",
        ),
        allowed_evidence_refs=set(),
        requested_mode="AUTO",
    )

    assert result == {
        "relation_candidates": [],
        "requested_work_status": "NOT_APPLICABLE",
        "requested_work_reason": None,
        "matched_fact_ids": [],
        "evidence_refs": [],
    }
    assert runtime.calls == []


def test_complete_empty_task_observation__supports_nonduplicate__without_item_evidence() -> None:
    output = {
        "relation_candidates": [],
        "requested_work_status": "NOT_SATISFIED",
        "requested_work_reason": "required Task scope was observed empty",
        "matched_fact_ids": [],
        "evidence_refs": [],
    }
    runtime = WorkAnalysisRuntimeFake(output)

    result = detect_duplicate_conflict_candidates.detect_duplicate_conflict_candidates(
        work_facts=[],
        entity_relations=[],
        evidence=[],
        source_state={
            "source_statuses": [
                {
                    "route_id": "task-read",
                    "resource_type": "task",
                    "status": "COMPLETE",
                    "observed_resource_count": 0,
                }
            ]
        },
        request_intent={"requested_effect_hints": ["CREATE"]},
        task_duplicate_review_required=True,
        llm_runtime=runtime,
        prompt_ref=prompt_ref(
            "work_analysis.detect_duplicate_conflict_candidates",
            "detect_duplicate_conflict_candidates",
        ),
        allowed_evidence_refs=set(),
        requested_mode="AUTO",
    )

    assert result == output
    assert len(runtime.calls) == 1


@pytest.mark.parametrize(
    "source_statuses",
    [
        [
            {
                "route_id": "task-read",
                "resource_type": "TASK",
                "status": "PARTIAL",
                "observed_resource_count": 1,
            }
        ],
        [
            {
                "route_id": "task-read",
                "resource_type": "TASK",
                "status": "COMPLETE",
                "observed_resource_count": 1,
            }
        ],
    ],
)
def test_nonduplicate_review__requires_complete__represented_task_observation(
    source_statuses: list[dict[str, object]],
) -> None:
    runtime = WorkAnalysisRuntimeFake(
        {
            "relation_candidates": [],
            "requested_work_status": "NOT_SATISFIED",
            "requested_work_reason": "no duplicate",
            "matched_fact_ids": [],
            "evidence_refs": [],
        }
    )

    with pytest.raises(ValueError, match="Task observation"):
        detect_duplicate_conflict_candidates.detect_duplicate_conflict_candidates(
            work_facts=[],
            entity_relations=[],
            evidence=[],
            source_state={"source_statuses": source_statuses},
            request_intent={"requested_effect_hints": ["CREATE"]},
            task_duplicate_review_required=True,
            llm_runtime=runtime,
            prompt_ref=prompt_ref(
                "work_analysis.detect_duplicate_conflict_candidates",
                "detect_duplicate_conflict_candidates",
            ),
            allowed_evidence_refs=set(),
            requested_mode="AUTO",
        )
