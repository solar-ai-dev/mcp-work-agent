from google_work_agent.adapters.langgraph.main.action_evidence_projection import (
    project_current_action_evidence,
    project_persisted_plan_evidence_for_review,
)
from google_work_agent.domain.action.model import ActionEvidence
from google_work_agent.domain.evidence.model import Evidence, EvidenceOriginType
from google_work_agent.domain.resource_ref.model import ResourceRef
from google_work_agent.ports.system.contracts.workflow_execution import (
    WorkflowCorrelationContext,
    WorkflowStartRequest,
)


def test_current_action_evidence__projects_persisted__user_message_identity() -> None:
    request = WorkflowStartRequest(
        run_id="run-1",
        conversation_id="conversation-1",
        workflow_key="thread-1",
        entry_mode="AGENT_SEARCH",
        requested_mode="LOCAL_GPU",
        request_text="Create the exact event.",
        selected_resource_ids=(),
        correlation=WorkflowCorrelationContext("request-1", "command-1", "v1"),
        user_message_id="message-1",
    )

    result = project_current_action_evidence(
        state={"run_id": "run-1", "retrieval_result": None, "__request__": request},
        evidence_store=object(),
    )

    assert result == [
        {
            "schema_version": 1,
            "evidence_id": "message-1",
            "origin_type": "USER_MESSAGE",
            "message_id": "message-1",
            "kind": "USER_REQUEST",
            "excerpt": "Create the exact event.",
        }
    ]


def test_persisted_plan_evidence__with_logical_ids__restores_resource_identity() -> None:
    resource_ref = ResourceRef(
        id="resource-ref-1",
        run_id="run-1",
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
    connector_evidence = Evidence(
        id="persisted-evidence-1",
        run_id="run-1",
        origin_type=EvidenceOriginType.GOOGLE_RESOURCE,
        resource_ref_id=resource_ref.id,
        message_id=None,
        kind="excerpt",
        excerpt="Existing event at 15:00",
        locator_json=(
            '{"resource_handle":"calendar_event:event-1",'
            '"retrieval_artifact_id":"retrieval-1","role":"SUPPORTS",'
            '"segment_id":"segment-1","source_locator":{"chunk_index":0}}'
        ),
        created_at_ms=10,
    )
    user_evidence = Evidence(
        id="persisted-evidence-2",
        run_id="run-1",
        origin_type=EvidenceOriginType.USER_MESSAGE,
        resource_ref_id=None,
        message_id="message-1",
        kind="USER_REQUEST",
        excerpt="Update the existing event.",
        locator_json=None,
        created_at_ms=10,
    )

    result = project_persisted_plan_evidence_for_review(
        run_id="run-1",
        evidence_by_id={item.id: item for item in (connector_evidence, user_evidence)},
        action_evidence=(
            ActionEvidence("action-1", connector_evidence.id),
            ActionEvidence("action-1", user_evidence.id),
        ),
        logical_evidence_refs_by_action={
            "action-1": ("retrieval-evidence-1", "message-1")
        },
        resource_refs_by_id={resource_ref.id: resource_ref},
    )

    assert result == [
        {
            "schema_version": 1,
            "evidence_id": "retrieval-evidence-1",
            "resource_handle": "calendar_event:event-1",
            "segment_id": "segment-1",
            "kind": "excerpt",
            "excerpt": "Existing event at 15:00",
            "locator": {"chunk_index": 0},
            "reason_codes": ["SUPPORTS"],
        },
        {
            "schema_version": 1,
            "evidence_id": "message-1",
            "origin_type": "USER_MESSAGE",
            "message_id": "message-1",
            "kind": "USER_REQUEST",
            "excerpt": "Update the existing event.",
        },
    ]
