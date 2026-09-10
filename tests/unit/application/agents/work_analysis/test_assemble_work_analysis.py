from google_work_agent.application.agents.work_analysis.assemble_work_analysis import (
    assemble_work_analysis,
    work_analysis_confirmation_context_hash,
)
from tests.support.work_analysis import fact


def test_requested_task_satisfied__becomes_not_required__from_duplicate_owner() -> None:
    result = assemble_work_analysis(
        artifact_id="analysis-1",
        revision=1,
        based_on=[{"artifact_id": "intent-1", "revision": 1}],
        work_facts=[fact("f1"), fact("f2")],
        validated_relations=[],
        ambiguities=[],
        risks=[],
        evidence_refs=["ev-1"],
        route_action_necessities=[
            {
                "route_id": "task-create",
                "status": "NOT_REQUIRED",
                "reason": "EXACT_DUPLICATE_ALREADY_SATISFIES_REQUEST",
                "evidence_refs": ["ev-1"],
                "candidate_refs": ["task:1"],
            }
        ],
        policy_confirmation_receipts=[],
    )

    assert result["action_necessity"] == "NOT_REQUIRED"
    assert result["action_necessity_reason"] == "EXACT_DUPLICATE_ALREADY_SATISFIES_REQUEST"
    assert result["policy_confirmation_receipt_refs"] == []


def test_incomplete_duplicate_review__keeps_action__undetermined() -> None:
    result = assemble_work_analysis(
        artifact_id="analysis-1",
        revision=1,
        based_on=[{"artifact_id": "intent-1", "revision": 1}],
        work_facts=[fact("f1"), fact("f2")],
        validated_relations=[],
        ambiguities=[],
        risks=[],
        evidence_refs=["ev-1"],
        route_action_necessities=[
            {
                "route_id": "task-create",
                "status": "UNDETERMINED",
                "reason": "TASK_DUPLICATE_REVIEW_UNDETERMINED",
                "evidence_refs": [],
                "candidate_refs": [],
            }
        ],
        policy_confirmation_receipts=[],
    )

    assert result["action_necessity"] == "UNDETERMINED"
    assert result["action_necessity_reason"] == "TASK_DUPLICATE_REVIEW_UNDETERMINED"


def test_complete_nonduplicate_review__keeps_frozen_action__required() -> None:
    result = assemble_work_analysis(
        artifact_id="analysis-1",
        revision=1,
        based_on=[{"artifact_id": "intent-1", "revision": 1}],
        work_facts=[],
        validated_relations=[],
        ambiguities=[],
        risks=[],
        evidence_refs=[],
        route_action_necessities=[
            {
                "route_id": "task-create",
                "status": "REQUIRED",
                "reason": "CURRENT_TASK_OBSERVATION_DOES_NOT_SATISFY_REQUEST",
                "evidence_refs": [],
                "candidate_refs": [],
            }
        ],
        policy_confirmation_receipts=[],
    )

    assert result["action_necessity"] == "REQUIRED"
    assert result["action_necessity_reason"] == (
        "CURRENT_TASK_OBSERVATION_DOES_NOT_SATISFY_REQUEST"
    )


def test_current_approved_conflict__override_receipt_is__bound_into_result() -> None:
    based_on = [{"artifact_id": "intent-1", "revision": 1}]
    receipt = {
        "schema_version": 1,
        "meta": {"artifact_id": "receipt-1", "revision": 1, "based_on": based_on},
        "interrupt_id": "interrupt-1",
        "confirmation_kind": "CONFLICT_OVERRIDE",
        "decision": "APPROVED",
        "semantic_owner_id": "WORK_ANALYSIS",
        "decision_context_hash": work_analysis_confirmation_context_hash(
            confirmation_kind="CONFLICT_OVERRIDE",
            interrupt_id="interrupt-1",
            based_on=based_on,  # type: ignore[arg-type]
        ),
        "affected_route_ids": [],
        "affected_resource_refs": [],
    }
    result = assemble_work_analysis(
        artifact_id="analysis-1",
        revision=1,
        based_on=based_on,  # type: ignore[arg-type]
        work_facts=[fact("f1"), fact("f2")],
        validated_relations=[
            {
                "relation_id": "r1",
                "kind": "CONFLICTS_WITH",
                "source_fact_id": "f1",
                "target_fact_id": "f2",
                "evidence_refs": ["ev-1"],
            }
        ],
        ambiguities=[],
        risks=[],
        evidence_refs=["ev-1"],
        route_action_necessities=[
            {
                "route_id": "calendar-create",
                "status": "REQUIRED",
                "reason": "CURRENT_OBSERVATION_REQUIRES_ACTION",
                "evidence_refs": ["ev-1"],
                "candidate_refs": [],
            }
        ],
        policy_confirmation_receipts=[receipt],  # type: ignore[list-item]
    )

    assert result["action_necessity"] == "REQUIRED"
    assert result["policy_confirmation_receipt_refs"] == [
        {"artifact_id": "receipt-1", "revision": 1}
    ]
    assert {"artifact_id": "receipt-1", "revision": 1} in result["meta"]["based_on"]
