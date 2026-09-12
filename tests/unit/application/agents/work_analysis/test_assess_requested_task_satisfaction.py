from __future__ import annotations

import pytest

from google_work_agent.application.agents.work_analysis.assess_requested_task_satisfaction import (
    assess_requested_task_satisfaction,
    not_applicable_task_satisfaction,
)
from tests.support.work_analysis import WorkAnalysisRuntimeFake, prompt_ref


def test_task_satisfaction__with_complete_empty_observation__returns_not_satisfied() -> None:
    output = {
        "requested_work_status": "NOT_SATISFIED",
        "requested_work_reason": "required Task scope was observed empty",
        "matched_fact_ids": [],
        "matched_candidate_refs": [],
        "evidence_refs": [],
    }
    runtime = WorkAnalysisRuntimeFake(output)

    result = assess_requested_task_satisfaction(
        work_facts=[],
        evidence=[],
        source_state={
            "source_statuses": [
                {
                    "route_id": "task-read",
                    "resource_type": "TASK",
                    "status": "COMPLETE",
                    "observed_resource_count": 0,
                }
            ]
        },
        request_intent={"requested_effect_hints": ["CREATE"]},
        llm_runtime=runtime,
        prompt_ref=prompt_ref(
            "work_analysis.assess_requested_task_satisfaction",
            "assess_requested_task_satisfaction",
        ),
        allowed_evidence_refs=set(),
        requested_mode="AUTO",
    )

    assert dict(result) == {"relation_candidates": [], **output}
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
def test_task_satisfaction__without_empty_or_item_evidence__rejects_determinate_result(
    source_statuses: list[dict[str, object]],
) -> None:
    runtime = WorkAnalysisRuntimeFake(
        {
            "requested_work_status": "NOT_SATISFIED",
            "requested_work_reason": "no duplicate",
            "matched_fact_ids": [],
            "matched_candidate_refs": [],
            "evidence_refs": [],
        }
    )

    with pytest.raises(ValueError, match="Task observation"):
        assess_requested_task_satisfaction(
            work_facts=[],
            evidence=[],
            source_state={"source_statuses": source_statuses},
            request_intent={"requested_effect_hints": ["CREATE"]},
            llm_runtime=runtime,
            prompt_ref=prompt_ref(
                "work_analysis.assess_requested_task_satisfaction",
                "assess_requested_task_satisfaction",
            ),
            allowed_evidence_refs=set(),
            requested_mode="AUTO",
        )


def test_not_applicable_task_satisfaction__without_duplicate_review__returns_empty_result() -> None:
    assert not_applicable_task_satisfaction() == {
        "relation_candidates": [],
        "requested_work_status": "NOT_APPLICABLE",
        "requested_work_reason": None,
        "matched_fact_ids": [],
        "matched_candidate_refs": [],
        "evidence_refs": [],
    }
