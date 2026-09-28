"""A Review selector is reusable only for its immediate Planning-only REVISE.

These tests connect actual invalidation and Review entry without semantic/model execution.
"""

from collections.abc import Mapping
from copy import deepcopy
from typing import Any, cast

import pytest
from tests.unit.adapters.langgraph.test_request_revision_work_freshness import (
    _meta,
    _state,
)
from tests.unit.adapters.langgraph.test_review_answer_dispatch_budget import _DispatchRuntime

from google_work_agent.adapters.langgraph.main.state import GraphState, GraphStateUpdateV1
from google_work_agent.adapters.langgraph.main.supervisor_artifact_revisions import (
    invalidate_stale_downstream,
)
from google_work_agent.adapters.langgraph.main.supervisor_decision import SupervisorDecisionV1
from google_work_agent.adapters.langgraph.main.supervisor_state_projection import (
    project_supervisor_state,
)
from google_work_agent.adapters.langgraph.profiles.profile_registry import GraphProfile
from google_work_agent.adapters.langgraph.subgraphs.review.graph import ReviewSubgraph
from google_work_agent.adapters.langgraph.subgraphs.review.projections.proposal_transition_projection import (  # noqa: E501
    capture_reviewed_proposal,
)
from google_work_agent.adapters.langgraph.subgraphs.review.projections.recheck_affected_dimensions_projection import (  # noqa: E501
    project_recheck_affected_dimensions_input,
)
from google_work_agent.adapters.langgraph.subgraphs.review.state import ReviewState
from google_work_agent.adapters.system.memory.retrieval_evidence_store import RunScopedEvidenceStore
from google_work_agent.application.agents.planning.contracts.planning_result import (
    PlanningResultV2,
)
from google_work_agent.application.agents.review.aggregate_review_findings import (
    aggregate_review_findings,
)
from google_work_agent.application.agents.review.contracts.review_findings import (
    ReviewDimensionIdV1,
    ReviewInspectorFindingV1,
)
from google_work_agent.application.use_cases.run.get_supervisor_observation import (
    SupervisorObservationV1,
)
from google_work_agent.application.use_cases.run.guard_run_budget import build_default_run_budget
from google_work_agent.ports.system.contracts.confirmation import (
    validate_confirmation_response_projection_v1,
)

_DIMENSION: ReviewDimensionIdV1 = "review.inspect_action_scope_and_route"
_CONTEXT_KEYS = (
    "review_prior_findings",
    "review_affected_dimensions",
    "review_previous_proposal",
)


@pytest.mark.parametrize(
    "upstream",
    ["request_intent", "input_plan", "output_plan", "retrieval_result", "work_analysis_result"],
)
def test_upstream_revision_discards_old_review_selector_before_new_planning(
    upstream: str,
) -> None:
    previous = _reviewed_state("ISSUE")
    original = deepcopy(previous)
    current = deepcopy(previous)
    _bump_revision(current, upstream)

    invalidated = invalidate_stale_downstream(previous=previous, current=current)

    assert "plan_review" in invalidated
    assert current["plan_review"] is None
    _assert_review_context_cleared(current)
    current["planning_result"] = _planning(2)
    assert _review_entry(current) == "inspect_goal_and_evidence"
    assert previous == original


def test_planning_only_revise_preserves_bounded_review_selector() -> None:
    previous = _reviewed_state("ISSUE")
    current = deepcopy(previous)
    prior_context = deepcopy(previous["prompt_context"])
    current["planning_result"] = _planning(2)

    invalidated = invalidate_stale_downstream(previous=previous, current=current)

    assert "plan_review" in invalidated
    assert current["plan_review"] is None
    assert current["prompt_context"] == prior_context
    assert _review_entry(current) == "recheck"
    assert current["prompt_context"]["review_affected_dimensions"] == [_DIMENSION]


@pytest.mark.parametrize("kind", ["ROUTE_ISSUE", "EVIDENCE_GAP", "BLOCKER"])
def test_non_revise_review_does_not_authorize_planning_recheck(kind: str) -> None:
    previous = _reviewed_state(kind)
    current = deepcopy(previous)
    current["planning_result"] = _planning(2)

    invalidate_stale_downstream(previous=previous, current=current)

    assert current["plan_review"] is None
    _assert_review_context_cleared(current)
    assert _review_entry(current) == "inspect_goal_and_evidence"


def test_current_confirmation_keeps_its_review_resume_path() -> None:
    previous = _reviewed_state("CONFIRMATION")
    current = deepcopy(previous)
    response = validate_confirmation_response_projection_v1(
        {
            "schema_version": 1,
            "response_kind": "FREE_TEXT",
            "selected_option": None,
            "free_text": "확인된 사용자 응답",
        }
    )
    current["prompt_context"]["confirmation_response"] = response

    assert invalidate_stale_downstream(previous=previous, current=current) == []
    assert _review_entry(current) == "recheck"
    assert current["plan_review"] == previous["plan_review"]
    assert current["prompt_context"]["confirmation_response"] == response


def test_stale_revise_cannot_authorize_recheck_of_a_new_planning_revision() -> None:
    previous = _reviewed_state("ISSUE")
    review = previous["plan_review"]
    assert review is not None
    review["meta"]["based_on"] = [{"artifact_id": "other-plan", "revision": 1}]
    current = deepcopy(previous)
    current["planning_result"] = _planning(2)

    invalidate_stale_downstream(previous=previous, current=current)

    _assert_review_context_cleared(current)
    assert _review_entry(current) == "inspect_goal_and_evidence"


def test_fresh_review_context_from_same_stage_is_not_removed_with_old_artifacts() -> None:
    previous = _reviewed_state("ISSUE")
    current = deepcopy(previous)
    _bump_revision(current, "request_intent")
    current["planning_result"] = _planning(2)
    prior_findings = cast(
        list[dict[str, object]], current["prompt_context"]["review_prior_findings"]
    )
    finding = deepcopy(prior_findings[0])
    finding["code"] = "NEW_CURRENT_REVIEW_FINDING"
    review = aggregate_review_findings(
        [finding],
        artifact_id="review-1",
        revision=2,
        based_on=[{"artifact_id": "plan-1", "revision": 2}],
    )
    current["plan_review"] = review
    current["prompt_context"]["review_prior_findings"] = [finding]
    assert current["planning_result"] is not None
    current["prompt_context"]["review_previous_proposal"] = capture_reviewed_proposal(
        current["planning_result"], review
    )
    fresh_context = deepcopy(current["prompt_context"])

    invalidated = invalidate_stale_downstream(previous=previous, current=current)

    assert "plan_review" not in invalidated
    assert current["plan_review"] == review
    assert current["prompt_context"] == fresh_context


def test_saved_proposal_reaches_recheck_input_after_valid_planning_only_invalidation() -> None:
    previous = _reviewed_state("ISSUE")
    current = deepcopy(previous)
    current["planning_result"] = _planning(2)
    invalidate_stale_downstream(previous=previous, current=current)
    assert current["plan_review"] is None
    runtime = _DispatchRuntime()
    review_state = cast(ReviewState, current)
    review_state["evidence"] = []  # This test inspects proposal lineage, not evidence resolution.

    projected = _production_review(runtime)._project_runtime_inputs(review_state)  # noqa: SLF001

    assert projected["review_phase"] == "RECHECK"
    transition = projected["proposal_transition"]
    assert transition["stage"] == "PROPOSAL_REVIEW_BEFORE_EXECUTION"
    assert transition["previous_plan_ref"] == _planning(1)["meta"]
    assert transition["current_plan_ref"] == _planning(2)["meta"]
    assert transition["route_id"] == "draft-create"
    assert transition["changed_arguments"] == [
        {
            "path": "/body",
            "previous": {"present": True, "value": "작성안 revision 1"},
            "current": {"present": True, "value": "작성안 revision 2"},
        }
    ]
    saved = cast(Mapping[str, object], previous["prompt_context"]["review_previous_proposal"])
    assert transition["historical_review_issues"] == saved["historical_review_issues"]
    assert project_recheck_affected_dimensions_input(projected)["proposal_transition"] == transition
    assert runtime.calls == []


@pytest.mark.parametrize("status", ["PASS", "REVISE"])
def test_aggregate_cleared_proposal_is_not_resurrected_by_actual_supervisor_merge(
    status: str,
) -> None:
    state = cast(ReviewState, _reviewed_state("ISSUE"))
    original = deepcopy(state)
    findings: list[dict[str, object]] = []
    if status == "REVISE":
        old = cast(list[dict[str, object]], state["prompt_context"]["review_prior_findings"])[0]
        # A dimension-only REVISE is valid but cannot name an unambiguous prior Action.
        findings = [{**old, "affected_action_ids": [], "affected_route_ids": []}]
    state.update(
        {
            "review_phase": "INITIAL",
            "review_artifact_id": "review-1",
            "review_revision": 2,
            "review_based_on": [{"artifact_id": "plan-1", "revision": 1}],
            "goal_evidence_result": {
                "schema_version": 1,
                "dimension": "review.inspect_goal_and_evidence",
                "findings": [],
            },
            "action_scope_route_result": {
                "schema_version": 1,
                "dimension": _DIMENSION,
                "findings": cast(list[ReviewInspectorFindingV1], findings),
            },
            "constraints_policy_result": {
                "schema_version": 1,
                "dimension": "review.inspect_constraints_and_policy_summary",
                "findings": [],
            },
            "retry_budget": build_default_run_budget(),
            "trace_context": {},
        }
    )
    runtime = _DispatchRuntime()

    result = _production_review(runtime)._aggregate_review_findings_node(state)  # noqa: SLF001

    review = result["plan_review"]
    assert review is not None and review["status"] == status
    assert capture_reviewed_proposal(_planning(1), review) is None
    assert result["prompt_context"].get("review_previous_proposal") is None
    assert result["prompt_context"]["unrelated_context"] == {"preserve": True}
    assert original["prompt_context"]["review_previous_proposal"] is not None
    assert state["prompt_context"] == original["prompt_context"]
    decisions = cast(list[dict[str, object]], result["trace_context"]["supervisor_decisions"])
    assert decisions[-1]["target"] == (
        "DOMAIN_VALIDATION" if status == "PASS" else "PLANNING_REVISE_PLAN"
    )
    assert runtime.calls == []


def _reviewed_state(kind: str) -> GraphState:
    state = _state()
    state["planning_result"] = _planning(1)
    finding: dict[str, object] = {
        "dimension": _DIMENSION,
        "code": "FIXTURE_REVIEW_FINDING",
        "finding_kind": kind,
        "description": "현재 작성안에서 확인할 항목",
        "evidence_refs": [],
        "affected_action_ids": ["action-1"],
        "affected_route_ids": ["draft-create"],
        "required_information": ["대상 근거"] if kind == "EVIDENCE_GAP" else [],
    }
    review = aggregate_review_findings(
        [finding],
        artifact_id="review-1",
        revision=1,
        based_on=[{"artifact_id": "plan-1", "revision": 1}],
    )
    state["plan_review"] = review
    context: dict[str, object] = {
        "review_prior_findings": [finding],
        "review_affected_dimensions": [_DIMENSION],
        "unrelated_context": {"preserve": True},
    }
    assert state["planning_result"] is not None
    proposal = capture_reviewed_proposal(state["planning_result"], review)
    if kind == "ISSUE":
        assert proposal is not None
    if proposal is not None:
        context["review_previous_proposal"] = proposal
    state["prompt_context"] = context
    return state


def _planning(revision: int) -> PlanningResultV2:
    # Typed draft for capture/invalidation/entry; no semantic/model outcome is claimed.
    return cast(
        PlanningResultV2,
        {
            "schema_version": 2,
            "meta": _meta("plan-1", revision, ("output-1", 1), ("retrieval-1", 1)),
            "actions": [
                {
                    "action_id": "action-1",
                    "route_id": "draft-create",
                    "tool_id": "gmail_create_draft",
                    "effect": "CREATE",
                    "arguments": {"body": f"작성안 revision {revision}"},
                    "evidence_refs": ["evidence-1"],
                    "depends_on_action_ids": [],
                }
            ],
        },
    )


def _bump_revision(state: GraphState, upstream: str) -> None:
    values = cast(dict[str, object], state)
    if upstream in {"input_plan", "output_plan"}:
        plan = cast(dict[str, object], state["tool_route_plan"])
        artifact = cast(dict[str, object], plan[upstream])
    else:
        artifact = cast(dict[str, object], values[upstream])
    meta = cast(dict[str, object], artifact["meta"])
    meta["revision"] = 2


def _review_entry(state: GraphState) -> str:
    return ReviewSubgraph()._route_at_entry(cast(ReviewState, state))  # noqa: SLF001


def _production_review(runtime: _DispatchRuntime) -> ReviewSubgraph:
    return ReviewSubgraph(
        llm_runtime=runtime,
        id_factory=lambda: "fresh-review",
        graph_profile=GraphProfile.SIX_ROLE_BASELINE,
        merge_decision=_merge_review,
        evidence_store=RunScopedEvidenceStore(),
        load_persisted_evidence=lambda _state: [],
        confirm_inline=lambda _state: (None, None),
        resume_target_registry=cast(Any, object()),  # Not used by these non-interrupt paths.
    )


def _merge_review(
    state: GraphState, update: GraphStateUpdateV1, decision: SupervisorDecisionV1
) -> GraphState:
    return project_supervisor_state(
        state=state,
        stage_update=update,
        candidate=decision,
        durable_facts=SupervisorObservationV1(
            run_status="PLANNING",
            next_allowed_commands=(),
            action_statuses=(),
            cancel_intent_active=False,
        ),
    ).state


def _assert_review_context_cleared(state: GraphState) -> None:
    context = state["prompt_context"]
    assert isinstance(context, Mapping)
    assert all(not context.get(key) for key in _CONTEXT_KEYS)
    assert context["unrelated_context"] == {"preserve": True}
