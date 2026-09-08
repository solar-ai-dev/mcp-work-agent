from threading import Lock
from types import SimpleNamespace
from typing import cast

import pytest

from google_work_agent.adapters.langgraph.invocation import WorkflowInvocationCoordinator
from google_work_agent.adapters.langgraph.main.state import GraphState, initial_graph_state
from google_work_agent.adapters.langgraph.profiles.profile_registry import GraphProfile
from google_work_agent.application.use_cases.run.guard_run_budget import build_default_run_budget
from google_work_agent.ports.system.contracts.workflow_execution import (
    WorkflowCorrelationContext,
    WorkflowResumeRequest,
    WorkflowStartRequest,
)
from google_work_agent.ports.system.contracts.workflow_handoff import (
    RetrievalCacheRestartControlV1,
)


class _Graph:
    def __init__(self) -> None:
        self.calls: list[object] = []
        self.updates: list[tuple[object, str]] = []
        self.snapshot = SimpleNamespace(
            values=initial_graph_state(
                WorkflowStartRequest(
                    run_id="run-1",
                    conversation_id="conversation-1",
                    workflow_key="thread-1",
                    entry_mode="AGENT_SEARCH",
                    requested_mode="LOCAL_GPU",
                    request_text="요청",
                    selected_resource_ids=(),
                    correlation=WorkflowCorrelationContext("request-1", "command-1", "v2"),
                    run_budget=build_default_run_budget(),
                ),
                graph_profile=GraphProfile.SIX_ROLE_BASELINE,
                graph_version="v1",
                initial_target="initialize",
            ),
            next=(),
            config={"configurable": {"checkpoint_id": "before"}},
            tasks=(),
        )

    def get_state(self, _config: object) -> object:
        return self.snapshot

    def invoke(self, value: object, *, config: object) -> dict[str, object]:
        del config
        self.calls.append(value)
        self.snapshot = SimpleNamespace(
            values={
                **self.snapshot.values,
                "graph_profile": "SIX_ROLE_BASELINE",
                "graph_version": "v1",
                "workflow_phase": "PLAN_REVIEW",
            },
            next=(),
            config={"configurable": {"checkpoint_id": "after"}},
            tasks=(),
        )
        return dict(self.snapshot.values)

    def update_state(self, _config: object, value: object, *, as_node: str) -> None:
        self.updates.append((value, as_node))


def test_normal_handoff__consumes_its_durably__materialized_target_once() -> None:
    graph = _Graph()
    coordinator = _coordinator(graph)

    result = coordinator.resume(
        WorkflowResumeRequest(
            run_id="run-1",
            workflow_key="thread-1",
            resume_kind="NORMAL_HANDOFF",
            resume_payload={},
            correlation=WorkflowCorrelationContext("request-1", "command-1", "v2"),
            normal_handoff_target_node="review_entry",
        )
    )

    assert result.outcome == "ACCEPTED"
    assert len(graph.calls) == 1
    assert graph.calls[0] is None


@pytest.mark.parametrize("settled", [True, False])
def test_verification_handoff__replaces_crashed_execution__only_with_durable_effect(
    settled: bool,
) -> None:
    graph = _Graph()
    graph.snapshot.next = ("action_execution", "verification")
    coordinator = _coordinator(graph)
    coordinator._has_executed_action = lambda _: settled
    coordinator.resume(
        WorkflowResumeRequest(
            run_id="run-1",
            workflow_key="thread-1",
            resume_kind="NORMAL_HANDOFF",
            resume_payload={},
            correlation=WorkflowCorrelationContext("r", "c", "1"),
            normal_handoff_target_node="verification",
        )
    )
    assert graph.calls == [None]
    assert len(graph.updates) == int(settled)
    if settled:
        assert graph.updates[0][1] == "action_execution"
        update = graph.updates[0][0]
        assert isinstance(update, dict)
        assert update["__target__"] == "verification"


def test_cache_restart__replaces_stale__pending_retrieval_task() -> None:
    graph = _Graph()
    graph.snapshot.values.update(
        {
            "acquisition_result": {"stale": True},
            "retrieval_result": {"stale": True},
            "__context_canonical_plans__": {"route-1": {"stale": True}},
            "__context_query_attempts__": [{"stale": True}],
            "__context_read_result_handles__": ["lost-handle"],
            "__context_read_bindings__": {"lost-handle": {"stale": True}},
            "__context_segment_handles__": ["lost-segment"],
            "exclusion_obligation_segment_ids": ["lost-segment"],
        }
    )
    coordinator = _coordinator(graph)

    coordinator.resume(
        WorkflowResumeRequest(
            run_id="run-1",
            workflow_key="thread-1",
            resume_kind="NORMAL_HANDOFF",
            resume_payload={},
            correlation=WorkflowCorrelationContext("request-1", "command-1", "v2"),
            normal_handoff_target_node="retrieval_entry",
            normal_handoff_control=RetrievalCacheRestartControlV1(
                kind="RETRIEVAL_CACHE_RESTART",
                lost_checkpoint_id="checkpoint-1",
                lost_handle_fingerprint="a" * 64,
            ),
        )
    )

    assert graph.updates == [
        (
            {
                "workflow_phase": "CONTEXT_RETRIEVAL",
                "__logical_target__": "context_retriever",
                "__target__": "context_retriever",
                "__workflow_control__": None,
                "acquisition_result": None,
                "retrieval_result": None,
                "__context_canonical_plans__": {},
                "__context_query_attempts__": [],
                "__context_read_result_handles__": [],
                "__context_read_bindings__": {},
                "__context_segment_handles__": [],
                "exclusion_obligation_segment_ids": [],
                "user_interrupt": None,
            },
            "retrieval_entry",
        )
    ]
    assert graph.calls == [None]


def test_cancel_replaces__a_preempted__user_interrupt() -> None:
    graph = _Graph()
    coordinator = _coordinator(graph)

    coordinator.resume(
        WorkflowResumeRequest(
            run_id="run-1",
            workflow_key="thread-1",
            resume_kind="NORMAL_HANDOFF",
            resume_payload={},
            correlation=WorkflowCorrelationContext("request-1", "command-1", "v2"),
            normal_handoff_target_node="cancel_resolution",
        )
    )

    assert graph.updates == [
        (
            {
                "workflow_phase": "CANCEL_RESOLUTION",
                "__logical_target__": "cancel_resolution",
                "__target__": "cancel_resolution",
                "user_interrupt": None,
            },
            "cancel_resolution",
        )
    ]
    assert graph.calls == [None]


def _coordinator(graph: _Graph) -> WorkflowInvocationCoordinator:
    return WorkflowInvocationCoordinator(
        graph=graph,
        graph_profile=GraphProfile.SIX_ROLE_BASELINE,
        start_node="initialize",
        initial_state=lambda _request: cast(GraphState, {}),
        current_run_status=lambda _run_id: "WAITING_APPROVAL",
        latest_unknown_action=lambda _run_id: None,
        recovery_node=lambda state: state,
        has_executed_action=lambda _run_id: False,
        recover_executed_actions=lambda state, _run_id: state,
        mark_stalled_claims_as_unknown=lambda _run_id: False,
        cancel_signal_lock=Lock(),
        cancel_signals=set(),
    )


@pytest.mark.parametrize(
    "connector,resource_type,resource_id,parent",
    [
        ("google_workspace", "gmail_thread", "thread-1", None),
        ("github", "github_issue", "acme/repo#7", "acme/repo"),
    ],
)
def test_resume__immutable_input__preserves_identity_and_message(
    connector: str,
    resource_type: str,
    resource_id: str,
    parent: str | None,
) -> None:
    from google_work_agent.adapters.langgraph.main.state import request_from_run_input_state

    graph = _Graph()
    values = graph.snapshot.values
    values["run_input"].update(
        {
            "user_message_id": "message-original",
            "user_request": "원래 요청",
            "entry_mode": "RESOURCE_SELECTED",
            "selected_resource_refs": [
                {
                    "resource_ref_id": "persisted-ref-1",
                    "connector_id": connector,
                    "resource_type": resource_type,
                    "resource_id": resource_id,
                    "parent_resource_id": parent,
                }
            ],
        }
    )
    restored = request_from_run_input_state(values)
    assert restored.request_text == "원래 요청"
    assert restored.user_message_id == "message-original"
    assert restored.selected_resources[0].resource_ref_id == "persisted-ref-1"
    assert restored.selected_resources[0].connector_id == connector
    assert restored.selected_resources[0].parent_resource_id == parent
    assert _coordinator(graph).is_profile_compatible(values)


def test_legacy_selected_checkpoint__resume__fails_before_io() -> None:
    graph = _Graph()
    graph.snapshot.values["run_input"]["selected_resource_refs"] = [
        {
            "source": "GMAIL",
            "resource_type": "THREAD",
            "resource_id": "thread-1",
        }
    ]
    result = _coordinator(graph).resume(
        WorkflowResumeRequest(
            run_id="run-1",
            workflow_key="thread-1",
            resume_kind="REAUTH_COMPLETED",
            resume_payload={},
            correlation=WorkflowCorrelationContext("r", "c", "v2"),
        )
    )
    assert result.outcome == "DOMAIN_CHECKPOINT_CONFLICT"
    assert graph.calls == graph.updates == []
