"""Revision freshness only: typed fixtures do not grade an LLM's work interpretation."""

from collections.abc import Mapping
from copy import deepcopy
from typing import cast

import pytest

from google_work_agent.adapters.langgraph.main import supervisor_artifact_revisions as revisions
from google_work_agent.adapters.langgraph.main.state import GraphState, WorkflowPhase
from google_work_agent.application.agents.planning.project_request_intent_for_work_units import (
    project_route_semantic_inputs,
)
from google_work_agent.application.agents.request_understanding.contracts.request_intent import (
    ConstraintProvenanceV1,
    RequestedWorkUnitV1,
    RequestIntentV3,
)
from google_work_agent.application.agents.request_understanding.validate_intent import (
    validate_intent,
)
from google_work_agent.application.agents.state_artifact import StateArtifactMetaV1

_READ_TEXT = "메일 A를 요약해줘."
_DRAFT_TEXT = "필요하면 그 요약을 초안으로 준비해줘."
_OTHER_TEXT = "처리 범위를 설명해줘."
_REQUEST = f"{_READ_TEXT} {_DRAFT_TEXT} 다시 말하면 {_READ_TEXT} {_OTHER_TEXT}"
_DEPENDENTS = ["work_analysis_result", "planning_result", "plan_review", "approved_plan_id"]
_ALL_DOWNSTREAM = ["tool_route_plan", "acquisition_result", "retrieval_result", *_DEPENDENTS]


@pytest.mark.parametrize(
    "change",
    ["span", "occurrence", "relation_added", "relation_removed", "work_added", "work_removed"],
)
def test_work_revision_with_unchanged_source_and_constraints_invalidates_observation(
    change: str,
) -> None:
    previous, current = _work_revision(change)
    before = deepcopy(previous)
    prior_intent = _intent(previous)
    next_intent = _intent(current)
    assert prior_intent["constraints"] == next_intent["constraints"]
    assert prior_intent["resource_responsibilities"] == next_intent["resource_responsibilities"]
    if change not in {"work_added", "work_removed"}:
        assert [unit["unit_id"] for unit in prior_intent["requested_work"]["work_units"]] == [
            unit["unit_id"] for unit in next_intent["requested_work"]["work_units"]
        ]

    invalidated = revisions.invalidate_stale_downstream(previous=previous, current=current)

    assert invalidated == _ALL_DOWNSTREAM
    assert all(cast(Mapping[str, object], current)[field] is None for field in invalidated)
    assert current.get("input_plan_reuse") is None
    assert not revisions.input_plan_reuse_is_current(current)
    assert (
        revisions.artifact_freshness_violation(WorkflowPhase.SOLUTION_PLANNING, current)
        == "TOOL_ROUTE_STALE"
    )
    assert previous == before


@pytest.mark.parametrize("change", ["goal", "completion", "output_only"])
def test_unchanged_work_preserves_input_reuse_for_non_input_revision(change: str) -> None:
    previous = _state()
    current = deepcopy(previous)
    intent = _intent(current)
    intent["meta"] = _meta("intent-1", 2)
    if change == "goal":
        intent["goal"] = "메일 요약을 답하고 필요한 경우에만 초안을 준비한다."
    elif change == "completion":
        intent["completion_conditions"] = ["조회한 내용으로 답하고 필요한 초안만 제안한다."]
    else:
        # An Output correction need not acquire the same source a second time.
        intent["resource_responsibilities"]["outputs"] = []
        intent["requested_effect_hints"] = ["READ"]
        intent["requested_resource_hints"] = ["GMAIL_THREAD"]
    _validate_current_intent(current)
    assert _intent(previous)["requested_work"] == _intent(current)["requested_work"]

    invalidated = revisions.invalidate_stale_downstream(previous=previous, current=current)

    assert invalidated == _DEPENDENTS
    for field in ("tool_route_plan", "acquisition_result", "retrieval_result"):
        assert (
            cast(Mapping[str, object], current)[field]
            == cast(Mapping[str, object], previous)[field]
        )
    assert revisions.input_plan_reuse_is_current(current)

    # Rebuilt Output lineage must still reference the revised Intent. Only READ is reused.
    before_routing = deepcopy(current)
    _rebuild_output(current)
    assert revisions.invalidate_stale_downstream(previous=before_routing, current=current) == []
    assert revisions.artifact_freshness_violation(WorkflowPhase.WORK_ANALYSIS, current) is None


def test_historical_two_field_reuse_pairs_revised_work_with_old_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    previous, revised = _work_revision("span")
    historical = deepcopy(revised)
    fixed = deepcopy(revised)

    # Freeze only the old comparison, not the current invalidator or Planning consumer.
    with monkeypatch.context() as patch:
        patch.setattr(revisions, "_request_input_semantics", _historical_input_semantics)
        assert (
            revisions.invalidate_stale_downstream(previous=previous, current=historical)
            == _DEPENDENTS
        )
        _rebuild_output(historical)
        assert revisions.input_plan_reuse_is_current(historical)
        assert (
            revisions.artifact_freshness_violation(WorkflowPhase.WORK_ANALYSIS, historical) is None
        )

    retrieval = historical["retrieval_result"]
    assert isinstance(retrieval, Mapping)
    old_evidence = [{"evidence_id": "evidence-1", "summary": "원래 Work 조회에서 얻은 내용"}]
    projected, evidence = project_route_semantic_inputs(
        _intent(historical),
        work_unit_ids=["work-1"],
        evidence=old_evidence,
        retrieval_result=retrieval,
    )
    assert projected is not None
    assert projected["requested_work"]["work_units"] == [
        _intent(revised)["requested_work"]["work_units"][0]
    ]
    assert projected["requested_work"]["work_units"] != [
        _intent(previous)["requested_work"]["work_units"][0]
    ]
    assert evidence == old_evidence
    assert retrieval == previous["retrieval_result"]

    # The projection consumes bindings; its parent freshness gate owns invalidation.
    assert (
        revisions.invalidate_stale_downstream(previous=previous, current=fixed) == _ALL_DOWNSTREAM
    )
    assert fixed["retrieval_result"] is None
    assert not revisions.input_plan_reuse_is_current(fixed)


def _work_revision(change: str) -> tuple[GraphState, GraphState]:
    previous = _state()
    work = _intent(previous)["requested_work"]
    if change == "relation_added":
        work["work_relations"] = []
    elif change == "work_removed":
        work["work_units"].append(_unit("work-3", _OTHER_TEXT))
    _validate_current_intent(previous)
    current = deepcopy(previous)
    intent = _intent(current)
    intent["meta"] = _meta("intent-1", 2)
    changed_work = intent["requested_work"]
    if change == "span":
        changed_work["work_units"][0] = _unit("work-1", "메일 A를")
    elif change == "occurrence":
        changed_work["work_units"][0] = _unit("work-1", _READ_TEXT, last=True)
        assert (
            work["work_units"][0]["request_provenance"][0]["source_text"]
            == changed_work["work_units"][0]["request_provenance"][0]["source_text"]
        )
    elif change == "relation_added":
        changed_work["work_relations"] = _intent(_state())["requested_work"]["work_relations"]
    elif change == "relation_removed":
        changed_work["work_relations"] = []
    elif change == "work_added":
        changed_work["work_units"].append(_unit("work-3", _OTHER_TEXT))
    elif change == "work_removed":
        changed_work["work_units"].pop()
    else:
        raise AssertionError(change)
    _validate_current_intent(current)
    return previous, current


def _state() -> GraphState:
    intent = validate_intent(
        {
            "schema_version": 3,
            "meta": _meta("intent-1", 1),
            "goal": "메일 내용을 요약하고 필요한 경우 초안을 준비한다.",
            "completion_conditions": ["요약과 필요한 초안을 제안한다."],
            "constraints": [
                {
                    "kind": "USER_REQUIREMENT",
                    "field": "required_information",
                    "value": ["message_history"],
                    "work_unit_ids": ["work-1"],
                }
            ],
            "requested_effect_hints": ["READ", "CREATE"],
            "requested_resource_hints": ["GMAIL_THREAD", "GMAIL_DRAFT"],
            "analysis_requirement": "NONE",
            "effect_prohibitions": [],
            "ambiguity": {
                "requires_confirmation": False,
                "reason_codes": [],
                "missing_fields": [],
            },
            "requested_work": {
                "work_units": [_unit("work-1", _READ_TEXT), _unit("work-2", _DRAFT_TEXT)],
                "work_relations": [
                    {
                        "source_work_unit_id": "work-1",
                        "target_work_unit_id": "work-2",
                        "kind": "CONSUMES_WORK_PRODUCT",
                    }
                ],
            },
            "resource_responsibilities": {
                "source_reads": [
                    {
                        "resource_type": "GMAIL_THREAD",
                        "required_information": ["message_history"],
                        "target_scope": "SINGULAR",
                        "work_unit_ids": ["work-1"],
                    }
                ],
                "outputs": [
                    {
                        "resource_type": "GMAIL_DRAFT",
                        "effect": "CREATE",
                        "work_unit_ids": ["work-2"],
                    }
                ],
            },
        },
        require_meta=True,
        provenance_sources={"USER_REQUEST": _REQUEST},
    )
    # These are the downstream fields consumed by freshness/projection, not fake model results.
    state = cast(
        GraphState,
        {
            "workflow_phase": WorkflowPhase.PLAN_REVIEW.value,
            "request_intent": intent,
            "tool_route_plan": {
                "schema_version": 2,
                "tool_registry_version": "fixture-registry",
                "input_plan": {
                    "schema_version": 1,
                    "meta": _meta("input-1", 1, ("intent-1", 1)),
                    "input_routes": [
                        {
                            "route_id": "mail-read",
                            "resource_type": "GMAIL_THREAD",
                            "connector_id": "google_workspace",
                            "allowed_read_tool_ids": ["gmail_get_thread"],
                            "required": True,
                            "reason_codes": ["USER_REQUEST"],
                            "work_unit_ids": ["work-1"],
                        }
                    ],
                },
            },
            "retrieval_result": {
                "meta": _meta("retrieval-1", 1, ("intent-1", 1), ("input-1", 1)),
                "evidence_by_work_unit": [
                    {"work_unit_id": "work-1", "evidence_refs": ["evidence-1"]}
                ],
            },
            "acquisition_result": {"status": "COMPLETE"},
            "work_analysis_result": {"meta": _meta("analysis-1", 1)},
            "planning_result": {"meta": _meta("plan-1", 1)},
            "plan_review": {"meta": _meta("review-1", 1)},
            "approved_plan_id": "approved-plan-1",
        },
    )
    _rebuild_output(state, revision=1)
    return state


def _rebuild_output(state: GraphState, *, revision: int = 2) -> None:
    intent = _intent(state)
    plan = cast(dict[str, object], state["tool_route_plan"])
    outputs = intent["resource_responsibilities"]["outputs"]
    output: dict[str, object] = {
        "schema_version": 1,
        "meta": _meta("output-1", revision, ("intent-1", intent["meta"]["revision"])),
        "output_mode": "ACTION" if outputs else "ANSWER",
    }
    if outputs:
        output["output_routes"] = [
            {
                "route_id": "draft-create",
                "resource_type": "GMAIL_DRAFT",
                "connector_id": "google_workspace",
                "effect": "CREATE",
                "selected_tool_id": "gmail_create_draft",
                "reason_codes": ["USER_REQUEST"],
                "work_unit_ids": ["work-2"],
            }
        ]
    plan["output_plan"] = output


def _unit(unit_id: str, text: str, *, last: bool = False) -> RequestedWorkUnitV1:
    start = _REQUEST.rindex(text) if last else _REQUEST.index(text)
    provenance: ConstraintProvenanceV1 = {
        "source": "USER_REQUEST",
        "start_offset": start,
        "end_offset": start + len(text),
        "source_text": text,
    }
    return {"unit_id": unit_id, "request_provenance": [provenance]}


def _intent(state: GraphState) -> RequestIntentV3:
    intent = state["request_intent"]
    assert intent is not None
    return intent


def _validate_current_intent(state: GraphState) -> None:
    state["request_intent"] = validate_intent(
        state["request_intent"],
        require_meta=True,
        provenance_sources={"USER_REQUEST": _REQUEST},
    )


def _meta(artifact_id: str, revision: int, *based_on: tuple[str, int]) -> StateArtifactMetaV1:
    return {
        "artifact_id": artifact_id,
        "revision": revision,
        "based_on": [{"artifact_id": name, "revision": version} for name, version in based_on],
    }


def _historical_input_semantics(intent: Mapping[str, object]) -> object:
    responsibilities = cast(Mapping[str, object], intent["resource_responsibilities"])
    return {"source_reads": responsibilities["source_reads"], "constraints": intent["constraints"]}
