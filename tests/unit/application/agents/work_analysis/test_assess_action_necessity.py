from typing import cast

from google_work_agent.application.agents.work_analysis.assess_action_necessity import (
    assess_action_necessity,
)
from google_work_agent.application.agents.work_analysis.contracts.work_analysis_candidates import (
    DuplicateConflictAssessmentV1,
)
from tests.support.work_analysis import WorkAnalysisRuntimeFake, prompt_ref


def _duplicate(status: str) -> DuplicateConflictAssessmentV1:
    return cast(
        DuplicateConflictAssessmentV1,
        {
            "relation_candidates": [],
            "requested_work_status": status,
            "requested_work_reason": "current Task review",
            "matched_fact_ids": [],
            "matched_candidate_refs": ["task:1"] if status == "SATISFIED" else [],
            "evidence_refs": [],
        },
    )


def test_task_create__duplicate_owner_satisfied__becomes_route_no_action() -> None:
    runtime = WorkAnalysisRuntimeFake({})

    result = assess_action_necessity(
        request_intent={},
        output_routes=[
            {
                "route_id": "task-create",
                "resource_type": "TASK",
                "effect": "CREATE",
            }
        ],
        work_facts=[],
        evidence=[],
        source_statuses=[],
        task_review_candidates=[],
        duplicate_conflict_assessment=_duplicate("SATISFIED"),
        llm_runtime=runtime,
        prompt_ref=prompt_ref("work_analysis.assess_action_necessity", "assess_action_necessity"),
        allowed_evidence_refs=set(),
        requested_mode="AUTO",
    )

    assert result["route_assessments"][0]["status"] == "NOT_REQUIRED"
    assert result["route_assessments"][0]["candidate_refs"] == ["task:1"]
    assert runtime.calls == []


def test_non_task_routes__are_assessed_independently__without_task_substitution() -> None:
    runtime = WorkAnalysisRuntimeFake(
        {
            "route_assessments": [
                {
                    "route_id": "issue-close",
                    "status": "NOT_REQUIRED",
                    "reason": "issue is already closed",
                    "evidence_refs": ["ev-1"],
                    "candidate_refs": [],
                },
                {
                    "route_id": "issue-update",
                    "status": "REQUIRED",
                    "reason": "requested body differs",
                    "evidence_refs": ["ev-2"],
                    "candidate_refs": [],
                },
            ]
        }
    )
    routes = [
        {"route_id": "issue-close", "resource_type": "GITHUB_ISSUE", "effect": "UPDATE"},
        {"route_id": "issue-update", "resource_type": "GITHUB_ISSUE", "effect": "UPDATE"},
    ]

    result = assess_action_necessity(
        request_intent={},
        output_routes=routes,
        work_facts=[],
        evidence=[],
        source_statuses=[],
        task_review_candidates=[],
        duplicate_conflict_assessment=_duplicate("NOT_APPLICABLE"),
        llm_runtime=runtime,
        prompt_ref=prompt_ref("work_analysis.assess_action_necessity", "assess_action_necessity"),
        allowed_evidence_refs={"ev-1", "ev-2"},
        requested_mode="AUTO",
    )

    assert [item["status"] for item in result["route_assessments"]] == [
        "NOT_REQUIRED",
        "REQUIRED",
    ]
