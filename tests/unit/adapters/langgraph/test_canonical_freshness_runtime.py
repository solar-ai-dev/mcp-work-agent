from copy import deepcopy
from typing import cast

import pytest

from google_work_agent.adapters.langgraph.main.state import (
    GraphState,
    GraphStateUpdateV1,
    WorkflowPhase,
)
from google_work_agent.adapters.langgraph.main.supervisor_artifact_revisions import (
    artifact_freshness_violation,
    input_plan_reuse_is_current,
    invalidate_stale_downstream,
)
from google_work_agent.adapters.langgraph.main.supervisor_decision import (
    SupervisorDecisionV1,
    SupervisorTarget,
    make_supervisor_decision,
)
from google_work_agent.adapters.langgraph.main.supervisor_progress import (
    guard_supervisor_no_progress,
    supervisor_progress_signature,
)
from google_work_agent.adapters.langgraph.main.supervisor_state_projection import (
    project_supervisor_state,
)
from google_work_agent.application.use_cases.run.get_supervisor_observation import (
    SupervisorObservationV1,
)


def test_intent_revision__with_existing_downstream__invalidates_all_artifacts() -> None:
    previous = _state()
    current = deepcopy(previous)
    cast(dict[str, object], current["request_intent"])["meta"] = _meta("intent-1", 2)

    invalidated = invalidate_stale_downstream(previous=previous, current=current)

    assert invalidated == [
        "tool_route_plan",
        "acquisition_result",
        "retrieval_result",
        "work_analysis_result",
        "planning_result",
        "plan_review",
        "approved_plan_id",
    ]
    current_values = cast(dict[str, object], current)
    assert all(current_values[field] is None for field in invalidated)


def test_output_only_intent_revision__preserves_input_observation__and_invalidates_dependents() -> (
    None
):
    previous = _state_with_reusable_input_observation()
    current = deepcopy(previous)
    intent = cast(dict[str, object], current["request_intent"])
    intent["meta"] = _meta("intent-1", 2)
    intent["goal"] = "Create the task only when the observed work remains outstanding."
    intent["completion_conditions"] = ["Preview only when action remains necessary."]

    invalidated = invalidate_stale_downstream(previous=previous, current=current)

    assert invalidated == [
        "work_analysis_result",
        "planning_result",
        "plan_review",
        "approved_plan_id",
    ]
    assert current["tool_route_plan"] == previous["tool_route_plan"]
    assert current["acquisition_result"] == previous["acquisition_result"]
    assert current["retrieval_result"] == previous["retrieval_result"]
    assert input_plan_reuse_is_current(current)


def test_input_semantics_revision__invalidates_input_observation__and_clears_reuse() -> None:
    previous = _state_with_reusable_input_observation()
    current = deepcopy(previous)
    intent = cast(dict[str, object], current["request_intent"])
    intent["meta"] = _meta("intent-1", 2)
    responsibilities = cast(dict[str, object], intent["resource_responsibilities"])
    responsibilities["source_reads"] = [
        {"resource_type": "CALENDAR_EVENT", "required_information": ["conflicts"]}
    ]

    invalidated = invalidate_stale_downstream(previous=previous, current=current)

    assert invalidated == [
        "tool_route_plan",
        "acquisition_result",
        "retrieval_result",
        "work_analysis_result",
        "planning_result",
        "plan_review",
        "approved_plan_id",
    ]
    assert current.get("input_plan_reuse") is None


def test_rebuilt_output_plan__with_reused_input_plan__keeps_retrieval_fresh() -> None:
    previous = _state_with_reusable_input_observation()
    current = deepcopy(previous)
    intent = cast(dict[str, object], current["request_intent"])
    intent["meta"] = _meta("intent-1", 2)
    intent["goal"] = "Create the task only when the observed work remains outstanding."
    intent["completion_conditions"] = ["Preview only when action remains necessary."]
    invalidate_stale_downstream(previous=previous, current=current)

    routed = deepcopy(current)
    plan = cast(dict[str, object], routed["tool_route_plan"])
    plan["output_plan"] = {
        "schema_version": 1,
        "meta": {
            "artifact_id": "output-1",
            "revision": 2,
            "based_on": [{"artifact_id": "intent-1", "revision": 2}],
        },
        "output_mode": "ANSWER",
    }
    invalidated = invalidate_stale_downstream(previous=current, current=routed)

    assert invalidated == []
    assert routed["retrieval_result"] is not None
    assert input_plan_reuse_is_current(routed)
    assert artifact_freshness_violation(WorkflowPhase.WORK_ANALYSIS, routed) is None


def test_retrieval_revision__with_existing_downstream__invalidates_dependent_artifacts() -> None:
    previous = _state()
    current = deepcopy(previous)
    cast(dict[str, object], current["retrieval_result"])["meta"] = _meta("retrieval-1", 2)

    invalidated = invalidate_stale_downstream(previous=previous, current=current)

    assert invalidated == [
        "work_analysis_result",
        "planning_result",
        "plan_review",
        "approved_plan_id",
    ]
    assert current["tool_route_plan"] is not None


@pytest.mark.parametrize(
    ("upstream", "expected"),
    [
        (
            "tool_route_plan",
            [
                "acquisition_result",
                "retrieval_result",
                "work_analysis_result",
                "planning_result",
                "plan_review",
                "approved_plan_id",
            ],
        ),
        ("work_analysis_result", ["planning_result", "plan_review", "approved_plan_id"]),
        ("planning_result", ["plan_review", "approved_plan_id"]),
    ],
)
def test_upstream_revision__with_existing_artifacts__invalidates_declared_descendants(
    upstream: str,
    expected: list[str],
) -> None:
    previous = _state()
    current = deepcopy(previous)
    current_values = cast(dict[str, object], current)
    artifact = current_values[upstream]
    if upstream == "tool_route_plan":
        artifact = cast(dict[str, object], artifact)["input_plan"]
    cast(dict[str, object], artifact)["meta"] = _meta(f"{upstream}-2", 2)

    invalidated = invalidate_stale_downstream(previous=previous, current=current)

    assert invalidated == expected
    assert all(current_values[field] is None for field in invalidated)


def test_upstream_revision__with_new_fresh_downstream__retains_new_artifacts() -> None:
    previous = _state()
    current = deepcopy(previous)
    cast(dict[str, object], current["planning_result"])["meta"] = _meta("plan-2", 1)
    cast(dict[str, object], current["plan_review"])["meta"] = {
        **_meta("review-2", 1),
        "based_on": [{"artifact_id": "plan-2", "revision": 1}],
    }

    invalidated = invalidate_stale_downstream(previous=previous, current=current)

    assert invalidated == ["approved_plan_id"]
    assert current["plan_review"] is not None
    assert current["approved_plan_id"] is None


def test_identical_back_edge__without_new_revision__fails_closed() -> None:
    state = _state()
    decision = _decision(SupervisorTarget.CONTEXT_RETRIEVAL, "EVIDENCE_GAP")
    signature = supervisor_progress_signature(state=state, decision=decision)
    state["trace_context"] = {
        "supervisor_decisions": [
            {
                "transition_kind": "BACK_EDGE",
                "progress_signature": signature,
            }
        ]
    }

    guarded = guard_supervisor_no_progress(state=state, decision=decision)

    assert guarded["target"] == SupervisorTarget.RECOVERY.value
    assert guarded["reason_code"] == "SUPERVISOR_NO_PROGRESS"


def test_supervisor_trace__after_invalidation__records_stage_produced_revision() -> None:
    state = _state()
    revised_intent = {"meta": _meta("intent-1", 2)}
    decision = make_supervisor_decision(
        target=SupervisorTarget.TOOL_ROUTE,
        next_phase=WorkflowPhase.TOOL_ROUTING,
        state_update={"workflow_phase": WorkflowPhase.TOOL_ROUTING.value},
        reason_code="INTENT_REVISED",
    )

    projection = project_supervisor_state(
        state=state,
        stage_update=cast(GraphStateUpdateV1, {"request_intent": revised_intent}),
        candidate=decision,
        durable_facts=SupervisorObservationV1(
            run_status="PLANNING",
            next_allowed_commands=(),
            action_statuses=(),
            cancel_intent_active=False,
        ),
    )

    trace_context = cast(dict[str, object], projection.state["trace_context"])
    decisions = cast(list[dict[str, object]], trace_context["supervisor_decisions"])
    trace = decisions[-1]
    progress_signature = trace["progress_signature"]
    assert isinstance(progress_signature, str)
    assert "request_intent=intent-1:2" in progress_signature
    assert trace["invalidated_fields"] == [
        "tool_route_plan",
        "acquisition_result",
        "retrieval_result",
        "work_analysis_result",
        "planning_result",
        "plan_review",
        "approved_plan_id",
    ]


def _state() -> GraphState:
    return cast(
        GraphState,
        {
            "workflow_phase": WorkflowPhase.PLAN_REVIEW.value,
            "request_intent": {"meta": _meta("intent-1", 1)},
            "tool_route_plan": {
                "input_plan": {"meta": _meta("input-1", 1)},
                "output_plan": {"meta": _meta("output-1", 1)},
            },
            "retrieval_result": {"meta": _meta("retrieval-1", 1)},
            "acquisition_result": {"status": "COMPLETE"},
            "work_analysis_result": {"meta": _meta("analysis-1", 1)},
            "planning_result": {"meta": _meta("plan-1", 1)},
            "plan_review": {"meta": _meta("review-1", 1)},
            "approved_plan_id": "approved-plan-1",
            "trace_context": {},
        },
    )


def _state_with_reusable_input_observation() -> GraphState:
    state = _state()
    state["request_intent"] = cast(
        object,
        {
            "schema_version": 2,
            "meta": _meta("intent-1", 1),
            "goal": "Create a task when needed.",
            "completion_conditions": ["Produce a safe result."],
            "constraints": [],
            "resource_responsibilities": {
                "source_reads": [{"resource_type": "TASK", "required_information": ["duplicates"]}],
                "outputs": [{"resource_type": "TASK", "effect": "CREATE"}],
            },
        },
    )
    state["tool_route_plan"] = cast(
        object,
        {
            "schema_version": 2,
            "input_plan": {
                "schema_version": 1,
                "meta": {
                    "artifact_id": "input-1",
                    "revision": 1,
                    "based_on": [{"artifact_id": "intent-1", "revision": 1}],
                },
                "input_routes": [{"route_id": "task-read"}],
            },
            "output_plan": {
                "schema_version": 1,
                "meta": {
                    "artifact_id": "output-1",
                    "revision": 1,
                    "based_on": [{"artifact_id": "intent-1", "revision": 1}],
                },
                "output_mode": "ACTION",
                "output_routes": [],
            },
        },
    )
    state["retrieval_result"] = cast(
        object,
        {
            "meta": {
                "artifact_id": "retrieval-1",
                "revision": 1,
                "based_on": [
                    {"artifact_id": "intent-1", "revision": 1},
                    {"artifact_id": "input-1", "revision": 1},
                ],
            }
        },
    )
    return state


def _meta(artifact_id: str, revision: int) -> dict[str, object]:
    return {"artifact_id": artifact_id, "revision": revision, "based_on": []}


def _decision(target: SupervisorTarget, reason: str) -> SupervisorDecisionV1:
    return {
        "target": target.value,
        "next_phase": WorkflowPhase.CONTEXT_RETRIEVAL.value,
        "state_update": {"workflow_phase": WorkflowPhase.CONTEXT_RETRIEVAL.value},
        "reason_code": reason,
        "budget_decision": None,
    }
