from __future__ import annotations

from collections.abc import Mapping
from typing import Any, cast

import pytest

from google_work_agent.adapters.langgraph.subgraphs.planning.graph import (
    PlanningRuntimeDependencies,
    PlanningSubgraph,
)
from google_work_agent.adapters.langgraph.subgraphs.review.graph import (
    ReviewRuntimeDependencies,
    ReviewSubgraph,
)
from google_work_agent.adapters.system.memory.retrieval_evidence_store import (
    RunScopedEvidenceStore,
)
from google_work_agent.application.agents.planning.contracts.planning_semantics import (
    PlanningSemanticInvoker,
)
from google_work_agent.application.agents.review.contracts.review_findings import (
    ReviewSemanticInvoker,
)


def _inspection(prompt_id: str, findings: list[dict[str, object]]) -> dict[str, object]:
    return {"schema_version": 1, "dimension": prompt_id, "findings": findings}


def _finding(
    dimension: str,
    *,
    code: str,
    description: str,
    action_ids: list[str] | None = None,
    route_ids: list[str] | None = None,
) -> dict[str, object]:
    return {
        "dimension": dimension,
        "code": code,
        "finding_kind": "ISSUE",
        "description": description,
        "evidence_refs": [],
        "affected_action_ids": action_ids or [],
        "affected_route_ids": route_ids or [],
        "required_information": [],
    }


def _action_intent(*, user_request: str, resource_type: str, effect: str) -> dict[str, object]:
    return {
        "schema_version": 3,
        "goal": user_request,
        "completion_conditions": ["Requested preview is prepared."],
        "constraints": [],
        "requested_effect_hints": [effect],
        "requested_resource_hints": [resource_type],
        "resource_responsibilities": {
            "source_reads": [],
            "outputs": [
                {
                    "resource_type": resource_type,
                    "effect": effect,
                    "work_unit_ids": ["work-1"],
                }
            ],
        },
        "analysis_requirement": "NONE",
        "effect_prohibitions": [],
        "requested_work": {
            "work_units": [
                {
                    "unit_id": "work-1",
                    "request_provenance": [
                        {
                            "source": "USER_REQUEST",
                            "start_offset": 0,
                            "end_offset": len(user_request),
                            "source_text": user_request,
                        }
                    ],
                }
            ],
            "work_relations": [],
        },
        "ambiguity": {"requires_confirmation": False, "reason_codes": [], "missing_fields": []},
    }


def test_compiled_planning__answer_executes__canonical_operations() -> None:
    calls: list[str] = []

    def invoke(prompt_id: str, prompt_input: Mapping[str, object]) -> Mapping[str, object]:
        calls.append(prompt_id)
        if prompt_id == "planning.outline_answer":
            assert set(prompt_input) == {
                "user_request",
                "request_intent",
                "work_analysis",
                "evidence",
            }
            return {"sections": ["summary"], "evidence_refs": ["e1"]}
        assert set(prompt_input) == {
            "user_request",
            "request_intent",
            "answer_outline",
            "temporal_constraints",
            "work_analysis",
            "evidence",
        }
        return {"schema_version": 2, "answer": "done", "evidence_refs": ["e1"]}

    graph = PlanningSubgraph(
        dependencies=PlanningRuntimeDependencies(invoke=cast(PlanningSemanticInvoker, invoke))
    ).build()
    result = graph.invoke(
        {
            "user_request": "Summarize it",
            "request_intent": {"goal": "summary"},
            "tool_route_plan": {"output_plan": {"output_mode": "ANSWER", "output_routes": []}},
            "work_analysis": {},
            "evidence": [{"evidence_ref": "e1"}],
        }
    )
    assert result["planning_disposition"] == "ANSWER"
    assert result["answer_outline"] == {"sections": ["summary"], "evidence_refs": ["e1"]}
    assert result["final_result"] == {
        "schema_version": 2,
        "answer": "done",
        "evidence_refs": ["e1"],
    }
    assert calls == ["planning.outline_answer", "planning.compose_answer"]


def test_compiled_planning__answer_without_analysis__skips_outline_llm() -> None:
    calls: list[str] = []

    def invoke(prompt_id: str, prompt_input: Mapping[str, object]) -> Mapping[str, object]:
        calls.append(prompt_id)
        assert prompt_id == "planning.compose_answer"
        assert prompt_input["answer_outline"] == {
            "sections": ["Summarize the selected message"],
            "evidence_refs": ["e1"],
        }
        return {"schema_version": 2, "answer": "done", "evidence_refs": ["e1"]}

    graph = PlanningSubgraph(
        dependencies=PlanningRuntimeDependencies(invoke=cast(PlanningSemanticInvoker, invoke))
    ).build()
    result = graph.invoke(
        {
            "user_request": "Summarize the selected message",
            "request_intent": {
                "goal": "summary",
                "ambiguity": {"requires_confirmation": False},
            },
            "tool_route_plan": {
                "output_plan": {"output_mode": "ANSWER", "output_routes": []}
            },
            "evidence": [{"evidence_ref": "e1"}],
        }
    )

    assert result["answer_outline"] == {
        "sections": ["Summarize the selected message"],
        "evidence_refs": ["e1"],
    }
    assert result["final_result"] == {
        "schema_version": 2,
        "answer": "done",
        "evidence_refs": ["e1"],
    }
    assert calls == ["planning.compose_answer"]


def test_compiled_planning__graph_has_exact__six_runtime_nodes() -> None:
    graph = PlanningSubgraph(
        dependencies=PlanningRuntimeDependencies(invoke=lambda _prompt_id, _input: {})
    ).build()
    assert set(graph.get_graph().nodes) - {"__start__", "__end__"} == {
        "outline_answer",
        "compose_answer",
        "draft_action_objective_per_output_route",
        "compose_arguments_per_output_route",
        "derive_dependencies",
        "assemble",
    }


def test_compiled_planning__action_executes_exact__four_node_path() -> None:
    route = {
        "route_id": "r1",
        "resource_type": "GMAIL_DRAFT",
        "connector_id": "google_workspace",
        "effect": "CREATE",
        "selected_tool_id": "gmail_create_draft",
        "reason_codes": ["USER_REQUEST"],
        "work_unit_ids": ["work-1"],
    }
    calls: list[str] = []

    def invoke(prompt_id: str, _prompt_input: Mapping[str, object]) -> Mapping[str, object]:
        calls.append(prompt_id)
        if prompt_id.endswith("draft_action_objective_per_output_route"):
            return {
                "schema_version": 1,
                "objective": "Create draft",
                "scope_constraints": ["draft only"],
                "evidence_refs": ["e1"],
            }
        return {
            "schema_version": 1,
            "route_id": "r1",
            "arguments": {"payload": {"to": ["a@example.com"], "subject": "s", "body": "b"}},
            "evidence_refs": ["e1"],
        }

    ids = iter(["action-1", "plan-1"])
    graph = PlanningSubgraph(
        dependencies=PlanningRuntimeDependencies(invoke=cast(PlanningSemanticInvoker, invoke)),
        id_factory=ids.__next__,
    ).build()
    result = graph.invoke(
        {
            "user_request": "Create a draft",
            "request_intent": _action_intent(
                user_request="Create a draft",
                resource_type="GMAIL_DRAFT",
                effect="CREATE",
            ),
            "tool_route_plan": {"output_plan": {"output_mode": "ACTION", "output_routes": [route]}},
            "evidence": [{"evidence_ref": "e1"}],
        }
    )
    assert result["final_result"]["actions"][0]["tool_id"] == "gmail_create_draft"
    assert calls == [
        "planning.draft_action_objective_per_output_route",
        "planning.compose_arguments_per_output_route",
    ]


def test_compiled_planning__unchanged_draft_update__returns_answer_without_action() -> None:
    route = {
        "route_id": "r1",
        "resource_type": "GMAIL_DRAFT",
        "connector_id": "google_workspace",
        "effect": "UPDATE",
        "selected_tool_id": "gmail_update_draft",
        "reason_codes": ["USER_REQUEST"],
        "work_unit_ids": ["work-1"],
    }
    snapshot = {
        "to": ["recipient@example.com"],
        "cc": [],
        "bcc": [],
        "subject": "Existing subject",
        "body": "Already updated",
        "thread_id": None,
        "in_reply_to": None,
        "references": None,
        "attachments": [],
    }
    calls: list[str] = []
    evidence_store = RunScopedEvidenceStore()
    evidence_store.put_resource_snapshot(
        run_id="run-1",
        resource_handle="gmail_draft:draft-actual",
        source_version_ref="version-1",
        snapshot=snapshot,
    )

    def invoke(prompt_id: str, _prompt_input: Mapping[str, object]) -> Mapping[str, object]:
        calls.append(prompt_id)
        if prompt_id.endswith("draft_action_objective_per_output_route"):
            return {
                "schema_version": 1,
                "objective": "Apply the requested Draft update",
                "scope_constraints": [],
                "evidence_refs": ["draft-evidence"],
            }
        return {
            "schema_version": 1,
            "route_id": "r1",
            "arguments": {"payload": {"body": "Already updated"}},
            "evidence_refs": ["draft-evidence"],
        }

    graph = PlanningSubgraph(
        dependencies=PlanningRuntimeDependencies(invoke=cast(PlanningSemanticInvoker, invoke)),
        evidence_store=evidence_store,
    ).build()
    result = graph.invoke(
        {
            "run_id": "run-1",
            "user_request": "기존 초안을 요청한 내용으로 수정해줘",
            "request_intent": _action_intent(
                user_request="기존 초안을 요청한 내용으로 수정해줘",
                resource_type="GMAIL_DRAFT",
                effect="UPDATE",
            ),
            "tool_route_plan": {
                "output_plan": {"output_mode": "ACTION", "output_routes": [route]}
            },
            "evidence": [
                {
                    "evidence_ref": "draft-evidence",
                    "resource_handle": "gmail_draft:draft-actual",
                    "locator": {"source_version_ref": "version-1"},
                }
            ],
        }
    )

    assert result["planning_disposition"] == "ANSWER"
    assert result["final_result"] == {
        "schema_version": 2,
        "answer": (
            "요청한 Gmail 임시보관함 초안 변경이 이미 반영되어 있어 "
            "추가 변경이 필요하지 않습니다."
        ),
        "evidence_refs": ["draft-evidence"],
    }
    assert "argument_candidates" not in result
    assert calls == [
        "planning.draft_action_objective_per_output_route",
        "planning.compose_arguments_per_output_route",
    ]


def test_planning_runtime_projection__repeated_call__uses_frozen_output_route_coverage() -> None:
    routes = [
        {
            "route_id": "required-route",
            "resource_type": "TASK",
            "connector_id": "google_workspace",
            "effect": "CREATE",
            "selected_tool_id": "tasks_create_task",
            "reason_codes": [],
        },
        {
            "route_id": "satisfied-route",
            "resource_type": "TASK",
            "connector_id": "google_workspace",
            "effect": "CREATE",
            "selected_tool_id": "tasks_create_task",
            "reason_codes": [],
        },
    ]
    state = {
        "tool_route_plan": {"output_plan": {"output_mode": "ACTION", "output_routes": routes}},
        "work_analysis": {
            "route_action_necessities": [
                {
                    "route_id": "required-route",
                    "status": "REQUIRED",
                    "reason": "REQUEST_REMAINS_OUTSTANDING",
                    "evidence_refs": [],
                    "candidate_refs": [],
                },
                {
                    "route_id": "satisfied-route",
                    "status": "NOT_REQUIRED",
                    "reason": "REQUEST_ALREADY_SATISFIED",
                    "evidence_refs": ["ev-1"],
                    "candidate_refs": ["task:existing"],
                },
            ]
        },
        "evidence": [],
    }
    subgraph = PlanningSubgraph(
        dependencies=PlanningRuntimeDependencies(invoke=lambda _prompt_id, _input: {})
    )

    first = subgraph._project_runtime_inputs(cast(Any, state))  # noqa: SLF001
    second = subgraph._project_runtime_inputs(first)  # noqa: SLF001

    first_output_plan = cast(dict[str, Any], first["output_plan"])
    first_output_routes = cast(list[dict[str, object]], first_output_plan["output_routes"])
    assert [route["route_id"] for route in first_output_routes] == [
        "required-route"
    ]
    assert second["output_plan"] == first["output_plan"]


def test_compiled_review_revise__emits_bounded_planning__revision_signal_without_recheck() -> None:
    calls: list[str] = []

    def invoke(prompt_id: str, _prompt_input: Mapping[str, object]) -> Mapping[str, object]:
        calls.append(prompt_id)
        if prompt_id == "review.inspect_action_scope_and_route":
            return _inspection(
                prompt_id,
                [
                    _finding(
                        prompt_id,
                        code="ACTION_NEEDS_REVISION",
                        description="revise action",
                        action_ids=["a1"],
                        route_ids=["r1"],
                    )
                ],
            )
        return _inspection(prompt_id, [])

    graph = ReviewSubgraph(
        dependencies=ReviewRuntimeDependencies(invoke=cast(ReviewSemanticInvoker, invoke))
    ).build()
    result = graph.invoke(
        {
            "review_phase": "INITIAL",
            "request_intent": {"goal": "update task"},
            "tool_route_plan": {},
            "planning_result": {"actions": [{"action_id": "a1"}]},
            "work_analysis": {},
            "evidence": [],
            "policy_summary": {},
            "review_artifact_id": "rv1",
            "review_revision": 1,
            "review_based_on": [],
        }
    )
    assert result["review_result"]["status"] == "REVISE"
    assert result["review_result"]["issues"] == [
        {
            "code": "ACTION_NEEDS_REVISION",
            "description": "revise action",
            "affected_dimensions": ["review.inspect_action_scope_and_route"],
            "affected_action_ids": ["a1"],
            "affected_route_ids": ["r1"],
            "evidence_refs": [],
        }
    ]
    assert result["workflow_signal"] is None
    assert "affected_dimension_recheck" not in result
    assert calls == [
        "review.inspect_goal_and_evidence",
        "review.inspect_action_scope_and_route",
        "review.inspect_constraints_and_policy_summary",
    ]
    assert "review.recheck_affected_dimensions" not in calls


def test_compiled_review_pass__does_not_emit__planning_revision_signal() -> None:
    calls: list[str] = []

    def invoke(prompt_id: str, _prompt_input: Mapping[str, object]) -> Mapping[str, object]:
        calls.append(prompt_id)
        return _inspection(prompt_id, [])

    graph = ReviewSubgraph(
        dependencies=ReviewRuntimeDependencies(invoke=cast(ReviewSemanticInvoker, invoke))
    ).build()
    result = graph.invoke(
        {
            "review_phase": "INITIAL",
            "request_intent": {"goal": "summarize"},
            "tool_route_plan": {},
            "planning_result": {"answer": "done"},
            "work_analysis": {},
            "evidence": [],
            "policy_summary": {},
            "review_artifact_id": "rv-pass",
            "review_revision": 1,
            "review_based_on": [],
            "workflow_signal": None,
        }
    )
    assert result["review_result"]["status"] == "PASS"
    assert result["workflow_signal"] is None
    assert calls == [
        "review.inspect_goal_and_evidence",
        "review.inspect_constraints_and_policy_summary",
    ]


@pytest.mark.parametrize("assessment_state", ["UNRESOLVED", "UNCERTAIN"])
def test_compiled_recheck__open_issue_without_finding_never_aggregates_pass(
    assessment_state: str,
) -> None:
    def invoke(_prompt_id: str, _prompt_input: Mapping[str, object]) -> Mapping[str, object]:
        return {
            "schema_version": 2,
            "affected_dimensions": ["review.inspect_goal_and_evidence"],
            "issue_assessments": [
                {
                    "issue_index": 0,
                    "state": assessment_state,
                    "current_reason": "current proposal remains uncertain",
                }
            ],
            "findings": [],
        }

    graph = ReviewSubgraph(
        dependencies=ReviewRuntimeDependencies(invoke=cast(ReviewSemanticInvoker, invoke))
    ).build()
    with pytest.raises(ValueError, match="current finding"):
        graph.invoke(
            {
                "review_phase": "RECHECK",
                "request_intent": {},
                "planning_result": {"actions": []},
                "evidence": [],
                "proposal_transition": {"historical_review_issues": [{}]},
                "affected_dimensions": ["review.inspect_goal_and_evidence"],
                "affected_action_ids": [],
                "affected_route_ids": [],
                "review_artifact_id": "rv2",
                "review_revision": 2,
                "review_based_on": [],
            }
        )


def test_compiled_review__recheck_refreshes__only_affected_dimensions() -> None:
    calls: list[str] = []

    def invoke(prompt_id: str, _prompt_input: Mapping[str, object]) -> Mapping[str, object]:
        calls.append(prompt_id)
        if prompt_id == "review.recheck_affected_dimensions":
            transition = _prompt_input.get("proposal_transition")
            historical = (
                transition.get("historical_review_issues")
                if isinstance(transition, Mapping)
                else None
            )
            return {
                "schema_version": 2,
                "affected_dimensions": ["review.inspect_action_scope_and_route"],
                "issue_assessments": [
                    {"issue_index": index, "state": "UNRESOLVED", "current_reason": "fixture"}
                    for index in range(len(historical) if isinstance(historical, list) else 0)
                ],
                "findings": [
                    _finding(
                        "review.inspect_action_scope_and_route",
                        code="FRESH_ACTION_REVIEW",
                        description="fresh revised result",
                        action_ids=["a1"],
                        route_ids=["r1"],
                    )
                ],
            }
        raise AssertionError(f"unaffected dimension was rechecked: {prompt_id}")

    # This is exactly the bounded public issue shape carried by the REVISE signal;
    # RECHECK does not require private Review findings or required_information state.
    public_revision_issues = [
        {
            "dimension": "review.inspect_action_scope_and_route",
            "code": "STALE_ACTION_REVIEW",
            "finding_kind": "ISSUE",
            "description": "stale",
            "evidence_refs": [],
            "affected_action_ids": ["a1"],
            "affected_route_ids": ["r1"],
            "required_information": [],
        },
        {
            "dimension": "review.inspect_constraints_and_policy_summary",
            "code": "UNCHANGED_POLICY_REVIEW",
            "finding_kind": "ISSUE",
            "description": "unchanged",
            "evidence_refs": [],
            "affected_action_ids": [],
            "affected_route_ids": [],
            "required_information": [],
        },
    ]
    affected_action_ids = [
        action_id for issue in public_revision_issues for action_id in issue["affected_action_ids"]
    ]
    affected_route_ids = [
        route_id for issue in public_revision_issues for route_id in issue["affected_route_ids"]
    ]

    graph = ReviewSubgraph(
        dependencies=ReviewRuntimeDependencies(invoke=cast(ReviewSemanticInvoker, invoke))
    ).build()
    result = graph.invoke(
        {
            "review_phase": "RECHECK",
            "request_intent": {"goal": "update task"},
            "tool_route_plan": {},
            "planning_result": {"revision": 2, "actions": [{"action_id": "a1"}]},
            "work_analysis": {},
            "evidence": [],
            "policy_summary": {},
            "prior_review_findings": public_revision_issues,
            "affected_dimensions": ["review.inspect_action_scope_and_route"],
            "affected_action_ids": affected_action_ids,
            "affected_route_ids": affected_route_ids,
            "review_artifact_id": "rv2",
            "review_revision": 2,
            "review_based_on": [],
        }
    )
    assert calls == [
        "review.recheck_affected_dimensions",
    ]
    assert result["review_result"]["status"] == "REVISE"
    issues = result["review_result"]["issues"]
    codes = {issue["code"] for issue in issues}
    assert "FRESH_ACTION_REVIEW" in codes
    assert "UNCHANGED_POLICY_REVIEW" in codes
    assert "STALE_ACTION_REVIEW" not in codes
    assert next(issue for issue in issues if issue["code"] == "FRESH_ACTION_REVIEW") == {
        "code": "FRESH_ACTION_REVIEW",
        "description": "fresh revised result",
        "affected_dimensions": ["review.inspect_action_scope_and_route"],
        "affected_action_ids": ["a1"],
        "affected_route_ids": ["r1"],
        "evidence_refs": [],
    }
    assert next(issue for issue in issues if issue["code"] == "UNCHANGED_POLICY_REVIEW") == {
        "code": "UNCHANGED_POLICY_REVIEW",
        "description": "unchanged",
        "affected_dimensions": ["review.inspect_constraints_and_policy_summary"],
        "affected_action_ids": [],
        "affected_route_ids": [],
        "evidence_refs": [],
    }
