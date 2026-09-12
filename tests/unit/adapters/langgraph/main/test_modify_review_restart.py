from contextlib import nullcontext
from json import dumps
from types import SimpleNamespace
from typing import Any, cast

from google_work_agent.adapters.langgraph.main.workflow import LangGraphWorkflowRuntime
from google_work_agent.adapters.langgraph.subgraphs.planning.graph import PlanningSubgraph
from google_work_agent.adapters.langgraph.subgraphs.review.graph import ReviewSubgraph
from google_work_agent.application.use_cases.run.guard_run_budget import build_default_run_budget
from google_work_agent.domain.action.model import Action, ActionEvidence
from google_work_agent.domain.evidence.model import Evidence, EvidenceOriginType
from google_work_agent.domain.plan.model import Plan, PlanReviewStatus, PlanStatusV1
from google_work_agent.domain.resource_ref.model import ResourceRef
from google_work_agent.ports.persistence.plan_repository import PlanBundle


def test_modify_review_restart__with_persisted_plan__restores_evidence() -> None:
    plan = Plan(
        id="plan-1",
        run_id="run-1",
        revision_no=1,
        status=PlanStatusV1.WAITING_APPROVAL,
        summary_text="Update the event",
        created_at_ms=10,
        review_status=PlanReviewStatus.REQUIRED,
        review_version=2,
    )
    action = Action(
        id="action-1",
        plan_id=plan.id,
        connector_id="google_workspace",
        position=1,
        tool_name="calendar_update_event",
        effect_type="UPDATE",
        approval_requirement="REQUIRED",
        verification_policy="GET_COMPARE",
        recovery_policy="GET_TARGET",
        target_resource_ref_id="resource-ref-1",
        status="MODIFIED",
        arguments_json=dumps(
            {
                "calendar_id": "calendar-1",
                "event_id": "event-1",
                "payload": {"location": "Room 212"},
            },
            sort_keys=True,
        ),
        arguments_hash="modified-hash",
        expected_json="{}",
        risk={},
        version=1,
        created_at_ms=10,
        updated_at_ms=11,
    )
    resource_ref = ResourceRef(
        id="resource-ref-1",
        run_id=plan.run_id,
        connector_id="google_workspace",
        resource_type="calendar_event",
        resource_id="event-1",
        parent_resource_id="calendar-1",
        canonical_url=None,
        title="Existing event",
        event_time_ms=None,
        version_token=None,
        metadata_json="{}",
        captured_at_ms=10,
    )
    evidence = Evidence(
        id="persisted-evidence-1",
        run_id=plan.run_id,
        origin_type=EvidenceOriginType.CONNECTOR_RESOURCE,
        resource_ref_id=resource_ref.id,
        message_id=None,
        kind="excerpt",
        excerpt="Existing event",
        locator_json=(
            '{"resource_handle":"calendar_event:event-1",'
            '"retrieval_artifact_id":"retrieval-1","role":"SUPPORTS",'
            '"segment_id":"segment-1","source_locator":null}'
        ),
        created_at_ms=10,
    )
    bundle = PlanBundle(
        plan=plan,
        actions=(action,),
        dependencies=(),
        evidence=(evidence,),
        action_evidence=(ActionEvidence(action.id, evidence.id),),
    )
    unit_of_work = SimpleNamespace(
        plans=SimpleNamespace(load_bundle=lambda plan_id: bundle if plan_id == plan.id else None),
        resource_refs=SimpleNamespace(
            list_for_run_bounded=lambda run_id, limit: (resource_ref,)
        ),
    )
    runtime = cast(Any, object.__new__(LangGraphWorkflowRuntime))
    runtime._unit_of_work_factory = lambda: nullcontext(unit_of_work)
    state = {
        "run_id": plan.run_id,
        "planning_result": {
            "schema_version": 2,
            "meta": {"artifact_id": plan.id, "revision": 1, "based_on": []},
            "actions": [
                {
                    "action_id": action.id,
                    "route_id": "route-1",
                    "tool_id": action.tool_name,
                    "effect": "UPDATE",
                    "arguments": {
                        "calendar_id": "calendar-1",
                        "event_id": "event-1",
                        "payload": {},
                    },
                    "evidence_refs": ["logical-evidence-1"],
                    "depends_on_action_ids": [],
                }
            ],
        },
        "retry_budget": build_default_run_budget(),
    }

    prepared = runtime._prepare_modify_review_state(  # noqa: SLF001
        cast(Any, state),
        plan_id=plan.id,
        review_version=plan.review_version,
    )

    assert prepared["__modify_review_evidence__"] == [
        {
            "schema_version": 1,
            "evidence_id": "logical-evidence-1",
            "resource_handle": "calendar_event:event-1",
            "segment_id": "segment-1",
            "kind": "excerpt",
            "excerpt": "Existing event",
            "locator": None,
            "reason_codes": ["SUPPORTS"],
        }
    ]
    assert cast(Any, prepared["planning_result"])["actions"][0]["arguments"]["payload"] == {
        "location": "Room 212"
    }
    assert ReviewSubgraph(
        evidence_store=cast(Any, object()),
        load_persisted_evidence=runtime._load_persisted_modify_review_evidence,  # noqa: SLF001
    )._evidence(  # noqa: SLF001
        cast(Any, prepared)
    ) == prepared["__modify_review_evidence__"]

    checkpoint_without_new_projection = dict(prepared)
    checkpoint_without_new_projection.pop("__modify_review_evidence__")
    assert ReviewSubgraph(
        evidence_store=cast(Any, object()),
        load_persisted_evidence=runtime._load_persisted_modify_review_evidence,  # noqa: SLF001
    )._evidence(  # noqa: SLF001
        cast(Any, checkpoint_without_new_projection)
    ) == prepared["__modify_review_evidence__"]

    replan_state = {
        **prepared,
        "__replan_from_plan_id__": plan.id,
        "retrieval_result": {
            "schema_version": 1,
            "evidence_refs": ["stale-in-memory-reference"],
        },
    }
    assert PlanningSubgraph(evidence_store=cast(Any, object()))._evidence(  # noqa: SLF001
        cast(Any, replan_state)
    ) == prepared["__modify_review_evidence__"]
