from contextlib import nullcontext
from types import SimpleNamespace
from typing import Any, cast

from google_work_agent.adapters.langgraph.main.state import GraphState
from google_work_agent.adapters.langgraph.main.supervisor_decision import SupervisorTarget
from google_work_agent.adapters.langgraph.main.workflow import LangGraphWorkflowRuntime
from google_work_agent.application.use_cases.run.guard_run_budget import build_default_run_budget
from google_work_agent.domain.plan.model import PlanReviewStatus


def test_modify_review_revise__after_durable_replan__restores_route() -> None:
    runtime = cast(Any, object.__new__(LangGraphWorkflowRuntime))
    runtime._store_modify_review_result = lambda *_args: True
    runtime._begin_modify_replan = lambda _state: True
    captured: dict[str, object] = {}

    def merge_decision(state: GraphState, update: object, decision: object) -> GraphState:
        captured["decision"] = decision
        return cast(GraphState, {**state, "__target__": "planning_entry"})

    runtime._merge_decision = merge_decision
    state = cast(
        GraphState,
        {
            "run_id": "run-1",
            "workflow_phase": "WAITING_APPROVAL",
            "retry_budget": build_default_run_budget(),
            "request_intent": {
                "schema_version": 2,
                "meta": {"artifact_id": "intent-1", "revision": 1, "based_on": []},
                "goal": "Update the selected event.",
                "completion_conditions": ["Update the selected event."],
                "constraints": [],
                "ambiguity": {
                    "requires_confirmation": False,
                    "reason_codes": [],
                    "missing_fields": [],
                },
                "requested_effect_hints": ["UPDATE"],
                "requested_resource_hints": ["CALENDAR_EVENT"],
                "analysis_requirement": "NONE",
            },
            "tool_route_plan": {
                "schema_version": 2,
                "input_plan": {
                    "schema_version": 1,
                    "meta": {
                        "artifact_id": "route-plan-1",
                        "revision": 1,
                        "based_on": [{"artifact_id": "intent-1", "revision": 1}],
                    },
                    "input_routes": [],
                },
                "output_plan": {
                    "schema_version": 1,
                    "meta": {
                        "artifact_id": "route-plan-1",
                        "revision": 1,
                        "based_on": [{"artifact_id": "intent-1", "revision": 1}],
                    },
                    "output_mode": "PLAN",
                },
                "tool_registry_version": "test",
            },
            "planning_result": {
                "schema_version": 2,
                "kind": "ACTION",
                "meta": {
                    "artifact_id": "plan-draft-1",
                    "revision": 1,
                    "based_on": [{"artifact_id": "route-plan-1", "revision": 1}],
                },
                "summary": "Update the selected event",
                "actions": [],
            },
            "plan_review": {
                "schema_version": 2,
                "meta": {
                    "artifact_id": "review-1",
                    "revision": 1,
                    "based_on": [{"artifact_id": "plan-draft-1", "revision": 1}],
                },
                "status": "REVISE",
                "issues": [
                    {
                        "code": "REQUEST_VALUE_MISMATCH",
                        "description": "The edited value needs a fresh plan.",
                        "affected_dimensions": ["review.inspect_goal_and_evidence"],
                        "affected_action_ids": ["action-1"],
                        "affected_route_ids": [],
                        "evidence_refs": [],
                    }
                ],
            },
            "__modify_review_plan_id__": "plan-1",
            "__modify_review_version__": 2,
            "__modify_review_risks__": {},
        },
    )

    settled = runtime._settle_persisted_review(state)

    assert settled["__target__"] == "planning_entry"
    assert settled["__replan_from_plan_id__"] == "plan-1"
    assert settled["__modify_review_plan_id__"] is None
    decision = cast(dict[str, object], captured["decision"])
    assert decision["target"] == SupervisorTarget.PLANNING_REVISE_PLAN.value


def test_modify_review_recheck__with_review_artifact__uses_idempotency_identity() -> None:
    runtime = cast(Any, object.__new__(LangGraphWorkflowRuntime))
    plan = SimpleNamespace(
        id="plan-1",
        run_id="run-1",
        revision_no=1,
        review_disposition="CONFIRM",
    )
    unit_of_work = SimpleNamespace(
        plans=SimpleNamespace(
            load_bundle=lambda _plan_id: SimpleNamespace(plan=plan),
        ),
        actions=SimpleNamespace(list_for_plan=lambda _plan_id: ()),
    )
    runtime._unit_of_work_factory = lambda: nullcontext(unit_of_work)
    recorded: list[object] = []

    def record_review_result(command: object) -> SimpleNamespace:
        recorded.append(command)
        return SimpleNamespace(applied=True)

    runtime._record_review_result = record_review_result
    state = cast(
        GraphState,
        {
            "__modify_review_plan_id__": "plan-1",
            "__modify_review_version__": 2,
            "plan_review": {
                "schema_version": 2,
                "meta": {"artifact_id": "review-artifact-1", "revision": 2, "based_on": []},
                "status": "PASS",
                "summary": "Confirmed value is valid.",
            },
        },
    )

    assert runtime._store_modify_review_result(state, PlanReviewStatus.PASSED, "PASS")

    command = cast(Any, recorded[0])
    assert command.review_artifact_id == "review-artifact-1"
    assert command.command_id == runtime._phase_command_id(
        "run-1", "record_review:plan-1:review-artifact-1", 2
    )
