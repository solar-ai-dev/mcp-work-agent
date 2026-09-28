"""Fake connected owner gate, not a Task matching or business-quality evaluation."""

from __future__ import annotations

from copy import deepcopy
from typing import Any, cast

import pytest
from scripts.route_task_satisfaction_candidate import (
    assess_task_routes,
    consume_task_route_assessments,
)
from tests.support.fakes.llm import FakeStructuredInferencePort
from tests.support.work_analysis import intent, prompt_ref

from google_work_agent.application.agents.planning.select_required_output_routes import (
    select_required_output_routes,
)
from google_work_agent.application.agents.request_understanding.validate_intent import (
    validate_intent,
)
from google_work_agent.application.agents.work_analysis.assess_action_necessity import (
    assess_action_necessity,
)
from google_work_agent.application.agents.work_analysis.assess_requested_task_satisfaction import (
    not_applicable_task_satisfaction,
)


def _inputs() -> dict[str, Any]:
    parts = (
        "Create a Task named Alpha review, without sending any email.",
        "Create a separate Task named Beta review if the readiness condition holds.",
    )
    text = " ".join(parts)
    request = cast(dict[str, Any], deepcopy(intent()))
    request.update(
        goal=text,
        completion_conditions=list(parts),
        requested_effect_hints=["READ", "CREATE"],
        requested_resource_hints=["TASK"],
        effect_prohibitions=[{"effect": "SEND", "work_unit_ids": ["work-1"]}],
        requested_work={
            "work_units": [
                {
                    "unit_id": unit,
                    "request_provenance": [
                        {
                            "source": "USER_REQUEST",
                            "start_offset": text.index(part),
                            "end_offset": text.index(part) + len(part),
                            "source_text": part,
                        }
                    ],
                }
                for unit, part in zip(("work-1", "work-2"), parts, strict=True)
            ],
            "work_relations": [],
        },
        constraints=[
            {"kind": "RESOURCE", "field": "title", "value": title, "work_unit_ids": [unit]}
            for title, unit in (("Alpha review", "work-1"), ("Beta review", "work-2"))
        ]
        + [
            {
                "kind": "USER_REQUIREMENT",
                "field": "required_information",
                "value": ["title", "status", "notes"],
                "work_unit_ids": ["work-1", "work-2"],
            },
            {
                "kind": "USER_REQUIREMENT",
                "field": "condition",
                "value": "the readiness condition holds",
                "work_unit_ids": ["work-2"],
            },
        ],
        resource_responsibilities={
            "source_reads": [
                {
                    "resource_type": "TASK",
                    "required_information": ["title", "status", "notes"],
                    "target_scope": "CRITERIA",
                    "work_unit_ids": ["work-1", "work-2"],
                }
            ],
            "outputs": [
                {"resource_type": "TASK", "effect": "CREATE", "work_unit_ids": [unit]}
                for unit in ("work-1", "work-2")
            ],
        },
    )
    validated = validate_intent(
        request, require_meta=True, provenance_sources={"USER_REQUEST": text}
    )
    return {
        "request_intent": validated,
        "output_routes": [
            {
                "route_id": identity,
                "resource_type": "TASK",
                "effect": "CREATE",
                "work_unit_ids": [unit],
                "selected_tool_id": "tasks_create_task",
            }
            for identity, unit in (("task-alpha", "work-1"), ("task-beta", "work-2"))
        ],
        "work_facts": [],
        "evidence": [
            {
                "schema_version": 1,
                "evidence_id": "ev-task",
                "resource_handle": "task:alpha",
                "segment_id": "segment-alpha",
                "kind": "TASK",
                "excerpt": "Observed Alpha review Task; readiness condition holds.",
                "locator": None,
                "reason_codes": [],
            }
        ],
        "allowed_evidence_refs": {"ev-task"},
        "source_state": {
            "source_statuses": [
                {
                    "route_id": "task-read",
                    "resource_type": "TASK",
                    "status": "COMPLETE",
                    "observed_resource_count": 1,
                    "work_unit_ids": ["work-1", "work-2"],
                    "evidence_refs": ["ev-task"],
                    "failure_kind": None,
                }
            ],
            "task_review_candidates": [
                {
                    "candidate_ref": "task:alpha",
                    "route_id": "task-read",
                    "resource_id": "alpha",
                    "task_list_id": "test-list",
                    "title": "Alpha review",
                    "status": "needsAction",
                    "due": None,
                    "source_version_ref": "observed-alpha-v1",
                }
            ],
        },
        "requested_mode": "AUTO",
    }


def _assessment(status: str) -> dict[str, Any]:
    return {
        "requested_work_status": status,
        "requested_work_reason": "Fixed fake owner decision; semantic quality is not tested",
        "matched_fact_ids": [],
        "matched_candidate_refs": ["task:alpha"] if status == "SATISFIED" else [],
        "evidence_refs": ["ev-task"] if status == "SATISFIED" else [],
    }


def _collection(alpha: str = "SATISFIED", beta: str = "NOT_SATISFIED") -> dict[str, Any]:
    return {"route_assessments": {"task-alpha": _assessment(alpha), "task-beta": _assessment(beta)}}


def _necessity(identity: str, status: str = "REQUIRED") -> dict[str, Any]:
    return {
        "route_assessments": [
            {
                "route_id": identity,
                "status": status,
                "reason": "The fake necessity owner assessed the request condition",
                "evidence_refs": ["ev-task"],
                "candidate_refs": [],
            }
        ]
    }


def _assess(inputs: dict[str, Any], runtime: FakeStructuredInferencePort) -> Any:
    return assess_task_routes(
        **inputs,
        llm_runtime=runtime,
        prompt_ref=prompt_ref("evaluation.route_task_satisfaction", "route_task_satisfaction"),
    )


def _consume(inputs: dict[str, Any], assessments: Any, runtime: FakeStructuredInferencePort) -> Any:
    return consume_task_route_assessments(
        **inputs,
        assessments=assessments,
        llm_runtime=runtime,
        prompt_ref=prompt_ref("work_analysis.assess_action_necessity", "assess_action_necessity"),
    )


def _plan(inputs: dict[str, Any], assessment: Any) -> Any:
    return select_required_output_routes(
        {"output_mode": "ACTION", "output_routes": inputs["output_routes"]},
        work_analysis={"route_action_necessities": assessment["route_assessments"]},
    )


def test_shared_observation_one_satisfaction_call_keeps_route_local_meaning() -> None:
    inputs = _inputs()
    before = deepcopy(inputs)
    runtime = FakeStructuredInferencePort(outputs=[_collection(), _necessity("task-beta")])

    assessments = _assess(inputs, runtime)
    result = _consume(inputs, assessments, runtime)
    plan = _plan(inputs, result)

    assert inputs == before
    assert len(runtime.calls) == 2  # satisfaction 1 + necessity for only the non-satisfied route 1
    payload = cast(Any, runtime.calls[0]["prompt_input"])
    assert payload["source_state"] == before["source_state"]
    assert len(payload["source_state"]["task_review_candidates"]) == 1
    local = payload["route_requests"]
    assert [item["source_route_ids"] for item in local] == [["task-read"], ["task-read"]]
    for item, unit, title in zip(
        local, ("work-1", "work-2"), ("Alpha review", "Beta review"), strict=True
    ):
        projected = item["request_intent"]
        assert projected["requested_work"]["work_units"][0]["unit_id"] == unit
        assert projected["resource_responsibilities"]["outputs"] == [
            {"resource_type": "TASK", "effect": "CREATE", "work_unit_ids": [unit]}
        ]
        assert [c["value"] for c in projected["constraints"] if c["field"] == "title"] == [title]
    assert local[0]["request_intent"]["effect_prohibitions"] == [
        {"effect": "SEND", "work_unit_ids": ["work-1"]}
    ]
    assert local[1]["request_intent"]["effect_prohibitions"] == []
    assert [item["status"] for item in result["route_assessments"]] == ["NOT_REQUIRED", "REQUIRED"]
    assert plan["output_routes"] == [before["output_routes"][1]]
    assert plan["output_routes"][0]["work_unit_ids"] == ["work-2"]
    necessity = cast(Any, runtime.calls[1]["prompt_input"])
    assert necessity["output_routes"] == [before["output_routes"][1]]
    assert necessity["request_intent"] == local[1]["request_intent"]
    assert any(c["field"] == "condition" for c in necessity["request_intent"]["constraints"])
    # No Provider port or Run factory exists in this direct gate; a plan is not execution approval.


def test_non_satisfied_route_is_not_forced_required_when_request_condition_is_false() -> None:
    inputs = _inputs()
    inputs["evidence"][0]["excerpt"] = "Observed Alpha review Task; readiness condition is false."
    runtime = FakeStructuredInferencePort(
        outputs=[_collection(), _necessity("task-beta", "NOT_REQUIRED")]
    )
    result = _consume(inputs, _assess(inputs, runtime), runtime)
    assert [item["status"] for item in result["route_assessments"]] == [
        "NOT_REQUIRED",
        "NOT_REQUIRED",
    ]
    assert _plan(inputs, result)["output_routes"] == []
    assert len(runtime.calls) == 2


def test_undetermined_route_stays_undetermined_and_planning_still_rejects_it() -> None:
    inputs = _inputs()
    runtime = FakeStructuredInferencePort(
        outputs=[_collection(alpha="UNDETERMINED"), _necessity("task-beta")]
    )
    result = _consume(inputs, _assess(inputs, runtime), runtime)
    assert [item["status"] for item in result["route_assessments"]] == ["UNDETERMINED", "REQUIRED"]
    with pytest.raises(ValueError, match="undetermined"):
        _plan(inputs, result)
    assert len(runtime.calls) == 2


def test_two_non_satisfied_routes_keep_two_existing_necessity_calls_in_this_prototype() -> None:
    inputs = _inputs()
    runtime = FakeStructuredInferencePort(
        outputs=[
            _collection(alpha="NOT_SATISFIED"),
            _necessity("task-alpha"),
            _necessity("task-beta"),
        ]
    )
    result = _consume(inputs, _assess(inputs, runtime), runtime)
    assert _plan(inputs, result)["output_routes"] == inputs["output_routes"]
    assert len(runtime.calls) == 3  # Explicit cost: 1 collection + 2 unmodified necessity calls.
    assert len(runtime.calls[1]["prompt_input"]["output_routes"]) == 1  # type: ignore[arg-type]
    assert len(runtime.calls[2]["prompt_input"]["output_routes"]) == 1  # type: ignore[arg-type]


def test_all_satisfied_routes_need_no_necessity_call() -> None:
    inputs = _inputs()
    inputs["source_state"]["task_review_candidates"].append(
        {
            "candidate_ref": "task:beta",
            "route_id": "task-read",
            "resource_id": "beta",
            "task_list_id": "test-list",
            "title": "Beta review",
            "status": "needsAction",
            "due": None,
            "source_version_ref": "observed-beta-v1",
        }
    )
    inputs["source_state"]["source_statuses"][0]["observed_resource_count"] = 2
    inputs["evidence"][0]["excerpt"] = "Observed Alpha review and Beta review Tasks."
    raw = _collection(beta="SATISFIED")
    raw["route_assessments"]["task-beta"]["matched_candidate_refs"] = ["task:beta"]
    runtime = FakeStructuredInferencePort(outputs=[raw])
    result = _consume(inputs, _assess(inputs, runtime), runtime)
    assert _plan(inputs, result)["output_routes"] == []
    assert len(runtime.calls) == 1


@pytest.mark.parametrize("field", ["missing_route", "unknown_route", "missing_status", "status"])
def test_collection_requires_exact_routes_and_valid_required_status(field: str) -> None:
    raw = _collection()
    if field == "missing_route":
        del raw["route_assessments"]["task-beta"]
    elif field == "unknown_route":
        raw["route_assessments"]["task-extra"] = _assessment("UNDETERMINED")
    elif field == "missing_status":
        del raw["route_assessments"]["task-beta"]["requested_work_status"]
    else:
        raw["route_assessments"]["task-beta"]["requested_work_status"] = "NOT_APPLICABLE"
    runtime = FakeStructuredInferencePort(outputs=[raw])
    with pytest.raises(ValueError, match="invalid route Task assessment"):
        _assess(_inputs(), runtime)
    assert len(runtime.calls) == 1


@pytest.mark.parametrize("field", ["evidence_refs", "matched_candidate_refs", "matched_fact_ids"])
def test_reference_fields_are_closed_to_route_accessible_observed_pool(field: str) -> None:
    raw = _collection()
    raw["route_assessments"]["task-alpha"][field] = ["unobserved"]
    with pytest.raises(ValueError, match="invalid route Task assessment"):
        _assess(_inputs(), FakeStructuredInferencePort(outputs=[raw]))


def test_work_local_source_binding_does_not_allow_another_work_candidate() -> None:
    inputs = _inputs()
    source = inputs["source_state"]
    source["source_statuses"][0]["work_unit_ids"] = ["work-1"]
    source["source_statuses"].append(
        {
            "route_id": "task-read-beta",
            "resource_type": "TASK",
            "status": "COMPLETE",
            "observed_resource_count": 0,
            "work_unit_ids": ["work-2"],
            "evidence_refs": [],
            "failure_kind": None,
        }
    )
    raw = _collection(beta="SATISFIED")  # Attempts to reuse work-1-only candidate for work-2.
    runtime = FakeStructuredInferencePort(outputs=[raw])
    with pytest.raises(ValueError, match="invalid route Task assessment"):
        _assess(inputs, runtime)
    assert len(runtime.calls) == 1


@pytest.mark.parametrize("kind", ["no_match", "partial_source", "incomplete_pool", "not_task_fact"])
def test_existing_scalar_semantic_validator_is_not_bypassed(kind: str) -> None:
    inputs = _inputs()
    raw = _collection()
    if kind == "no_match":
        raw["route_assessments"]["task-alpha"]["matched_candidate_refs"] = []
    elif kind == "partial_source":
        inputs["source_state"]["source_statuses"][0]["status"] = "PARTIAL"
    elif kind == "incomplete_pool":
        inputs["source_state"]["source_statuses"][0]["observed_resource_count"] = 2
    else:
        inputs["work_facts"] = [
            {
                "fact_id": "fact-other",
                "kind": "EVENT",
                "subject": "observed event",
                "value": "not a Task observation",
                "derivation": "EXPLICIT",
                "evidence_refs": ["ev-task"],
            }
        ]
        raw["route_assessments"]["task-alpha"]["matched_candidate_refs"] = []
        raw["route_assessments"]["task-alpha"]["matched_fact_ids"] = ["fact-other"]
    with pytest.raises(ValueError, match="observation|Task facts"):
        _assess(inputs, FakeStructuredInferencePort(outputs=[raw]))


def test_consumer_does_not_accept_global_or_partial_assessment() -> None:
    inputs = _inputs()
    runtime = FakeStructuredInferencePort(outputs=[_collection()])
    assessments = _assess(inputs, runtime)
    del assessments["task-beta"]
    with pytest.raises(ValueError, match="exactly the frozen"):
        _consume(inputs, assessments, runtime)
    assert len(runtime.calls) == 1


def test_consumer_does_not_duplicate_an_assessment_for_repeated_route_identity() -> None:
    inputs = _inputs()
    runtime = FakeStructuredInferencePort(outputs=[_collection()])
    assessments = _assess(inputs, runtime)
    inputs["output_routes"].append(deepcopy(inputs["output_routes"][0]))
    with pytest.raises(ValueError, match="exactly the frozen"):
        _consume(inputs, assessments, runtime)
    assert len(runtime.calls) == 1


def test_single_task_route_keeps_existing_satisfied_lowering_without_second_call() -> None:
    inputs = _inputs()
    inputs["output_routes"] = inputs["output_routes"][:1]
    raw = _collection()
    del raw["route_assessments"]["task-beta"]
    runtime = FakeStructuredInferencePort(outputs=[raw])
    result = _consume(inputs, _assess(inputs, runtime), runtime)
    assert _plan(inputs, result)["output_routes"] == []
    assert len(runtime.calls) == 1


@pytest.mark.parametrize("identity", [None, "", "task-alpha"])
def test_invalid_frozen_route_identity_fails_before_inference(identity: str | None) -> None:
    inputs = _inputs()
    inputs["output_routes"][1]["route_id"] = identity
    runtime = FakeStructuredInferencePort(outputs=[])
    with pytest.raises(ValueError, match="frozen route ID"):
        _assess(inputs, runtime)
    assert runtime.calls == []


def test_unknown_work_unit_fails_before_inference() -> None:
    inputs = _inputs()
    inputs["output_routes"][1]["work_unit_ids"] = ["unknown-work"]
    runtime = FakeStructuredInferencePort(outputs=[])
    with pytest.raises(ValueError, match="unknown WorkUnit"):
        _assess(inputs, runtime)
    assert runtime.calls == []


def test_no_task_route_produces_no_satisfaction_call() -> None:
    inputs = _inputs()
    inputs["output_routes"] = []
    runtime = FakeStructuredInferencePort(outputs=[])
    assert _assess(inputs, runtime) == {}
    assert _consume(inputs, {}, runtime) == {"route_assessments": []}
    assert runtime.calls == []


def test_product_multi_task_guard_is_unchanged_and_not_removed_by_candidate() -> None:
    inputs = _inputs()
    runtime = FakeStructuredInferencePort(outputs=[])
    source_state = inputs.pop("source_state")
    with pytest.raises(ValueError, match="cannot bind multiple CREATE routes"):
        assess_action_necessity(
            **inputs,
            source_statuses=source_state["source_statuses"],
            task_review_candidates=source_state["task_review_candidates"],
            duplicate_conflict_assessment=not_applicable_task_satisfaction(),
            llm_runtime=runtime,
            prompt_ref=prompt_ref(
                "work_analysis.assess_action_necessity", "assess_action_necessity"
            ),
        )
    assert runtime.calls == []
