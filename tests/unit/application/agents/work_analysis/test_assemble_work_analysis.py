from google_work_agent.application.agents.work_analysis.assemble_work_analysis import (
    assemble_work_analysis,
    required_override_confirmation_kind,
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


def test_duplicate_required__without_receipt__requires_duplicate_override_confirmation() -> None:
    based_on = [{"artifact_id": "intent-1", "revision": 1}]

    kind = required_override_confirmation_kind(
        validated_relations=[],
        action_execution_required=True,
        route_action_necessities=[
            {
                "route_id": "task-create",
                "status": "REQUIRED",
                "reason": "USER_REQUESTED_DUPLICATE_OVERRIDE",
                "evidence_refs": ["ev-1"],
                "candidate_refs": ["task:1"],
            }
        ],
        policy_confirmation_receipts=[],
        based_on=based_on,  # type: ignore[arg-type]
        duplicate_conflict_assessment=_satisfied_duplicate_assessment(),  # type: ignore[arg-type]
    )

    assert kind == "DUPLICATE_OVERRIDE"


def test_satisfied_task_route__with_unrelated_required_route__does_not_require_override() -> None:
    based_on = [{"artifact_id": "intent-1", "revision": 1}]
    route_necessities = [
        {
            "route_id": "task-create",
            "status": "NOT_REQUIRED",
            "reason": "THE_REQUESTED_TASK_ALREADY_EXISTS",
            "evidence_refs": ["ev-1"],
            "candidate_refs": ["task:1"],
        },
        {
            "route_id": "calendar-create",
            "status": "REQUIRED",
            "reason": "THE_REQUESTED_EVENT_DOES_NOT_EXIST",
            "evidence_refs": [],
            "candidate_refs": [],
        },
    ]

    kind = required_override_confirmation_kind(
        validated_relations=[],
        action_execution_required=True,
        route_action_necessities=route_necessities,  # type: ignore[arg-type]
        policy_confirmation_receipts=[],
        based_on=based_on,  # type: ignore[arg-type]
        duplicate_conflict_assessment=_satisfied_duplicate_assessment(),  # type: ignore[arg-type]
    )
    result = assemble_work_analysis(
        artifact_id="analysis-1",
        revision=1,
        based_on=based_on,  # type: ignore[arg-type]
        work_facts=[fact("f1")],
        validated_relations=[],
        ambiguities=[],
        risks=[],
        evidence_refs=["ev-1"],
        route_action_necessities=route_necessities,  # type: ignore[arg-type]
        policy_confirmation_receipts=[],
        duplicate_conflict_assessment=_satisfied_duplicate_assessment(),  # type: ignore[arg-type]
    )

    assert kind is None
    assert result["action_necessity"] == "REQUIRED"
    assert [item["status"] for item in result["route_action_necessities"]] == [
        "NOT_REQUIRED",
        "REQUIRED",
    ]


def test_duplicate_override__when_approved__keeps_route_and_summary_required() -> None:
    based_on = [{"artifact_id": "intent-1", "revision": 1}]
    receipt = _override_receipt(
        kind="DUPLICATE_OVERRIDE",
        decision="APPROVED",
        based_on=based_on,
    )

    result = assemble_work_analysis(
        artifact_id="analysis-1",
        revision=1,
        based_on=based_on,  # type: ignore[arg-type]
        work_facts=[fact("f1"), fact("f2")],
        validated_relations=[],
        ambiguities=[],
        risks=[],
        evidence_refs=["ev-1"],
        route_action_necessities=[
            {
                "route_id": "task-create",
                "status": "REQUIRED",
                "reason": "USER_CONFIRMED_DUPLICATE_OVERRIDE",
                "evidence_refs": ["ev-1"],
                "candidate_refs": ["task:1"],
            }
        ],
        policy_confirmation_receipts=[receipt],  # type: ignore[list-item]
        duplicate_conflict_assessment=_satisfied_duplicate_assessment(),  # type: ignore[arg-type]
    )

    assert result["action_necessity"] == "REQUIRED"
    assert result["action_necessity_reason"] == "DUPLICATE_OVERRIDE_APPROVED"
    assert result["route_action_necessities"][0]["status"] == "REQUIRED"


def test_duplicate_override__when_declined__makes_route_and_summary_not_required() -> None:
    based_on = [{"artifact_id": "intent-1", "revision": 1}]
    receipt = _override_receipt(
        kind="DUPLICATE_OVERRIDE",
        decision="DECLINED",
        based_on=based_on,
    )

    result = assemble_work_analysis(
        artifact_id="analysis-1",
        revision=1,
        based_on=based_on,  # type: ignore[arg-type]
        work_facts=[fact("f1"), fact("f2")],
        validated_relations=[],
        ambiguities=[],
        risks=[],
        evidence_refs=["ev-1"],
        route_action_necessities=[
            {
                "route_id": "task-create",
                "status": "REQUIRED",
                "reason": "USER_CONFIRMED_DUPLICATE_OVERRIDE",
                "evidence_refs": ["ev-1"],
                "candidate_refs": ["task:1"],
            }
        ],
        policy_confirmation_receipts=[receipt],  # type: ignore[list-item]
        duplicate_conflict_assessment=_satisfied_duplicate_assessment(),  # type: ignore[arg-type]
    )

    assert result["action_necessity"] == "NOT_REQUIRED"
    assert result["action_necessity_reason"] == "DUPLICATE_OVERRIDE_DECLINED"
    assert result["route_action_necessities"][0]["status"] == "NOT_REQUIRED"
    assert result["route_action_necessities"][0]["reason"] == "DUPLICATE_OVERRIDE_DECLINED"


def _override_receipt(
    *,
    kind: str,
    decision: str,
    based_on: list[dict[str, object]],
) -> dict[str, object]:
    interrupt_id = f"interrupt-{kind.lower()}"
    return {
        "schema_version": 1,
        "meta": {"artifact_id": f"receipt-{kind.lower()}", "revision": 1, "based_on": based_on},
        "interrupt_id": interrupt_id,
        "confirmation_kind": kind,
        "decision": decision,
        "semantic_owner_id": "WORK_ANALYSIS",
        "decision_context_hash": work_analysis_confirmation_context_hash(
            confirmation_kind=kind,
            interrupt_id=interrupt_id,
            based_on=based_on,  # type: ignore[arg-type]
        ),
        "affected_route_ids": ["task-create"],
        "affected_resource_refs": ["task:1"],
    }


def _satisfied_duplicate_assessment() -> dict[str, object]:
    return {
        "relation_candidates": [],
        "requested_work_status": "SATISFIED",
        "requested_work_reason": "The observed task already satisfies the request.",
        "matched_fact_ids": ["f1"],
        "matched_candidate_refs": ["task:1"],
        "evidence_refs": ["ev-1"],
    }
