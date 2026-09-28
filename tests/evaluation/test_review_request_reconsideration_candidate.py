"""Evaluation-only Review handoff; fake transport is not Main Graph migration.

The current RU projection accepts mappings after meta/observation checks. The
connected probe therefore proves carry to its first Goal input, not admission
of this new observation contract by the active Product runtime or Prompt.
"""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from typing import Any, cast

import pytest
from scripts import review_request_reconsideration_candidate as candidate
from tests.support import work_analysis as support
from tests.support.fakes.llm import FakeStructuredInferencePort

from google_work_agent.adapters.langgraph.main.state import WorkflowPhase
from google_work_agent.adapters.langgraph.main.supervisor_intake_rules import (
    route_request_reconsideration,
)
from google_work_agent.adapters.langgraph.subgraphs.request_understanding.projections.identify_goal_projection import (  # noqa: E501
    project_identify_goal_input,
)
from google_work_agent.application.agents.request_understanding.identify_goal import (
    identify_goal_with_budget,
)
from google_work_agent.application.prompt_runtime.prompt_registry import PromptRegistry
from google_work_agent.application.use_cases.run.guard_run_budget import build_default_run_budget
from google_work_agent.ports.llm.output_schema_validation import validate_output_schema
from google_work_agent.ports.llm.structured_inference_contracts import (
    OutputSchemaDefinition,
    PromptReference,
)
from google_work_agent.ports.llm.structured_inference_port import StructuredInferenceResultV1
from google_work_agent.ports.system.contracts.workflow_execution import (
    WorkflowCorrelationContext,
    WorkflowStartRequest,
)

_REQUEST = "선택한 자료의 상태만 알려줘."
_DIMENSION = "review.inspect_goal_and_evidence"
_NEW_KIND = "REQUEST_SEMANTICS_ISSUE"
_OUTPUT_PATH = "$.resource_responsibilities.outputs"
_PLAN_REF = {"artifact_id": "plan-1", "revision": 1}


@pytest.fixture
def intent() -> dict[str, Any]:
    value: dict[str, Any] = deepcopy(dict(support.intent()))
    value.update(
        goal="선택한 자료의 상태를 답한다.",
        completion_conditions=["조회한 상태를 답한다."],
        requested_effect_hints=["READ", "UPDATE"],
        requested_resource_hints=["TASK"],
        analysis_requirement="NONE",
        resource_responsibilities={
            "source_reads": [
                {
                    "resource_type": "TASK",
                    "target_scope": "SINGULAR",
                    "required_information": ["completion_status"],
                    "work_unit_ids": ["work-1"],
                }
            ],
            "outputs": [{"resource_type": "TASK", "effect": "UPDATE", "work_unit_ids": ["work-1"]}],
        },
    )
    value["requested_work"]["work_units"][0]["request_provenance"] = [
        {
            "source": "USER_REQUEST",
            "start_offset": 0,
            "end_offset": len(_REQUEST),
            "source_text": _REQUEST,
        }
    ]
    return value


def _finding(kind: str = _NEW_KIND) -> dict[str, Any]:
    result: dict[str, Any] = {
        "dimension": _DIMENSION,
        "code": "OBSERVED_MEANING_CONFLICT",
        "finding_kind": kind,
        "description": "조회 요청과 확정된 변경 의미가 일치하지 않습니다.",
        "evidence_refs": ["evidence-1"],
        "affected_action_ids": ["action-1"],
        "affected_route_ids": ["route-1"],
        "required_information": [],
    }
    if kind == _NEW_KIND:
        result.update(work_unit_ids=["work-1"], semantic_field_paths=[_OUTPUT_PATH])
    return result


def _root(*findings: dict[str, Any]) -> dict[str, Any]:
    return {"schema_version": 1, "dimension": _DIMENSION, "findings": list(findings)}


def _validate(value: dict[str, Any], intent: dict[str, Any], **overrides: Any) -> Any:
    options = {
        "current_intent": intent,
        "user_request": _REQUEST,
        "current_plan_ref": _PLAN_REF,
        "known_action_ids": ("action-1",),
        "known_route_ids": ("route-1",),
        "known_evidence_ids": ("evidence-1",),
        "pre_publication": True,
    }
    options.update(overrides)
    return candidate.validate_review_candidate(value, **options)


def _project(validated: Any, intent: dict[str, Any], **overrides: Any) -> Any:
    options = {
        "current_intent": intent,
        "original_request": _REQUEST,
        "current_plan_ref": _PLAN_REF,
        "pre_publication": True,
    }
    options.update(overrides)
    return candidate.build_request_reconsideration_projection(validated, **options)


def test_new_kind_carries_exact_owned_values_without_repair_or_write_authority(
    intent: dict[str, Any],
) -> None:
    raw = _root(_finding())
    before = deepcopy((raw, intent, _PLAN_REF))
    assert (
        validate_output_schema(raw, candidate.build_review_output_schema(["work-1"]).json_schema)
        == []
    )
    signal = _project(_validate(raw, intent)[0], intent)

    assert signal["schema_version"] == 2
    assert signal["kind"] == "REQUEST_RECONSIDERATION_REQUIRED"
    assert signal["based_on_request_intent"] == intent["meta"]
    assert signal["based_on_planning_result"] == _PLAN_REF
    observation = signal["observations"][0]
    assert observation == {
        "origin": "USER_REQUEST_PROVENANCE",
        "dimension": _DIMENSION,
        "code": "OBSERVED_MEANING_CONFLICT",
        "finding_kind": _NEW_KIND,
        "description": raw["findings"][0]["description"],
        "work_unit_ids": ["work-1"],
        "request_work_units": intent["requested_work"]["work_units"],
        "semantic_field_paths": [_OUTPUT_PATH],
        "semantic_values": {_OUTPUT_PATH: intent["resource_responsibilities"]["outputs"]},
        "evidence_refs": ["evidence-1"],
        "affected_action_ids": ["action-1"],
        "affected_route_ids": ["route-1"],
        "required_information": [],
    }
    # Existing Evidence references remain references, not forged observations.
    assert not {"evidence_ref", "resource_ref", "excerpt"} & observation.keys()
    assert not {"approval", "actions", "execution_permission", "selected_tool"} & signal.keys()
    assert (raw, intent, _PLAN_REF) == before
    observation["semantic_values"][_OUTPUT_PATH][0]["effect"] = "DELETE"
    assert intent["resource_responsibilities"]["outputs"][0]["effect"] == "UPDATE"


@pytest.mark.parametrize(
    "kind", ["ISSUE", "EVIDENCE_GAP", "ROUTE_ISSUE", "CONFIRMATION", "BLOCKER"]
)
def test_existing_kind_is_never_reclassified_from_free_text(
    intent: dict[str, Any], kind: str
) -> None:
    finding = _finding(kind)
    finding.update(
        code=_NEW_KIND,
        description="REQUEST_SEMANTICS_ISSUE: 원문 의미를 다시 판단해야 합니다.",
    )
    raw = _root(finding)
    before = deepcopy(raw)
    assert (
        validate_output_schema(raw, candidate.build_review_output_schema(["work-1"]).json_schema)
        == []
    )
    validated = _validate(raw, intent)
    assert _project(validated[0], intent) is None
    assert raw == before


def test_no_findings_produces_no_reconsideration(intent: dict[str, Any]) -> None:
    assert _validate(_root(), intent) == ()


def test_request_provenance_requires_no_invented_external_observation(
    intent: dict[str, Any],
) -> None:
    finding = _finding()
    finding["evidence_refs"] = []
    validated = _validate(_root(finding), intent, known_evidence_ids=())[0]
    observation = _project(validated, intent)["observations"][0]
    assert observation["origin"] == "USER_REQUEST_PROVENANCE"
    assert observation["evidence_refs"] == []
    assert observation["request_work_units"] == intent["requested_work"]["work_units"]


@pytest.mark.parametrize("path", candidate.SEMANTIC_FIELD_PATHS)
def test_each_closed_semantic_path_carries_its_current_value(
    intent: dict[str, Any], path: str
) -> None:
    finding = _finding()
    finding["semantic_field_paths"] = [path]
    before = deepcopy(intent)
    validated = _validate(_root(finding), intent)[0]
    observation = _project(validated, intent)["observations"][0]
    expected: Any = intent
    for part in path[2:].split("."):
        expected = expected[part]
    assert observation["semantic_values"] == {path: expected}
    assert intent == before


@pytest.mark.parametrize(
    "field, value",
    [
        ("work_unit_ids", ["foreign-work"]),
        ("work_unit_ids", []),
        ("work_unit_ids", ["work-1", "work-1"]),
        ("semantic_field_paths", ["$.requested_effect_hints"]),
        ("semantic_field_paths", ["$.resource_responsibilities.outputs[0].effect"]),
        ("semantic_field_paths", []),
        ("affected_action_ids", ["foreign-action"]),
        ("affected_route_ids", ["foreign-route"]),
        ("evidence_refs", ["foreign-evidence"]),
        ("dimension", "review.inspect_action_scope_and_route"),
    ],
)
def test_closed_binding_rejects_foreign_or_unsupported_values(
    intent: dict[str, Any], field: str, value: Any
) -> None:
    finding = _finding()
    finding[field] = value
    with pytest.raises(ValueError):
        _validate(_root(finding), intent)


@pytest.mark.parametrize("field", ["source_text", "start_offset", "end_offset", "source"])
def test_foreign_work_provenance_is_not_reinterpreted(intent: dict[str, Any], field: str) -> None:
    span = intent["requested_work"]["work_units"][0]["request_provenance"][0]
    span[field] = {
        "source_text": "다른 요청",
        "start_offset": 1,
        "end_offset": len(_REQUEST) + 1,
        "source": "EVIDENCE",
    }[field]
    with pytest.raises(ValueError):
        _validate(_root(_finding()), intent)


def test_closed_semantic_field_must_exist_in_frozen_intent(intent: dict[str, Any]) -> None:
    del intent["effect_prohibitions"]
    finding = _finding()
    finding["semantic_field_paths"] = ["$.effect_prohibitions"]
    with pytest.raises(ValueError):
        _validate(_root(finding), intent)


@pytest.mark.parametrize(
    "change", ["revision", "same_revision_value", "plan", "request", "published"]
)
def test_projection_rechecks_frozen_authorities(intent: dict[str, Any], change: str) -> None:
    validated = _validate(_root(_finding()), intent)[0]
    overrides: dict[str, Any] = {}
    if change == "revision":
        intent["meta"]["revision"] = 2
    elif change == "same_revision_value":
        intent["resource_responsibilities"]["outputs"][0]["effect"] = "DELETE"
    elif change == "plan":
        overrides["current_plan_ref"] = {"artifact_id": "plan-1", "revision": 2}
    elif change == "request":
        overrides["original_request"] = "다른 요청"
    else:
        overrides["pre_publication"] = False
    with pytest.raises(ValueError):
        _project(validated, intent, **overrides)


def test_already_published_plan_is_rejected_at_validation(intent: dict[str, Any]) -> None:
    with pytest.raises(ValueError):
        _validate(_root(_finding()), intent, pre_publication=False)


def test_only_chosen_work_provenance_is_carried_without_cross_work_value_rewrite(
    intent: dict[str, Any],
) -> None:
    other = "두 번째 자료도 알려줘."
    combined = _REQUEST + " " + other
    intent["requested_work"]["work_units"].append(
        {
            "unit_id": "work-2",
            "request_provenance": [
                {
                    "source": "USER_REQUEST",
                    "start_offset": len(_REQUEST) + 1,
                    "end_offset": len(combined),
                    "source_text": other,
                }
            ],
        }
    )
    finding = _finding()
    finding["work_unit_ids"] = ["work-2"]
    validated = _validate(_root(finding), intent, user_request=combined)[0]
    signal = _project(validated, intent, original_request=combined)
    observation = signal["observations"][0]
    assert observation["work_unit_ids"] == ["work-2"]
    assert observation["request_work_units"] == intent["requested_work"]["work_units"][1:]
    # Field evidence is copied, not silently rewritten to match the chosen Work.
    assert (
        observation["semantic_values"][_OUTPUT_PATH]
        == intent["resource_responsibilities"]["outputs"]
    )


class _GoalInputCaptured(Exception):
    pass


class _CaptureFirstGoal(FakeStructuredInferencePort):
    captured: dict[str, object] | None = None

    def infer(
        self,
        requested_mode: str,
        prompt_ref: PromptReference,
        input_projection: Mapping[str, object],
        output_schema_ref: OutputSchemaDefinition,
    ) -> StructuredInferenceResultV1:
        if prompt_ref.prompt_id == "request_understanding.identify_goal":
            self.captured = deepcopy(dict(input_projection))
            raise _GoalInputCaptured
        return super().infer(requested_mode, prompt_ref, input_projection, output_schema_ref)


def test_eval_observation_reaches_actual_ru_goal_input_but_is_not_product_migration(
    intent: dict[str, Any],
) -> None:
    signal = _project(_validate(_root(_finding()), intent)[0], intent)
    budget = build_default_run_budget()
    request = WorkflowStartRequest(
        run_id="run-review-carry",
        conversation_id="conversation-review-carry",
        workflow_key="review-carry",
        entry_mode="AGENT_SEARCH",
        requested_mode="LOCAL_GPU",
        request_text=_REQUEST,
        selected_resource_ids=(),
        correlation=WorkflowCorrelationContext("request-review-carry", None, "v1"),
        run_budget=budget,
    )
    state: dict[str, Any] = {
        "__request__": request,
        "run_input": {
            "entry_mode": "AGENT_SEARCH",
            "user_request": _REQUEST,
            "user_message_id": None,
            "requested_mode": "LOCAL_GPU",
            "selected_resource_refs": [],
        },
        "retry_budget": budget,
        "request_intent": intent,
        "request_reconsideration": signal,
    }
    before = deepcopy(state)
    projected = project_identify_goal_input(cast(Any, state))
    assert projected["request_reconsideration"] == signal
    runtime = _CaptureFirstGoal(outputs=[], validate_schema=True)
    registry = PromptRegistry()
    evaluation_refs = {
        parameter: registry.lookup_for_evaluation(f"request_understanding.{operation}")
        for parameter, operation in (
            ("prompt_ref", "identify_goal"),
            ("source_dependency_prompt_ref", "identify_source_dependencies"),
            ("output_responsibility_prompt_ref", "identify_output_responsibilities"),
            ("effect_prohibition_prompt_ref", "identify_effect_prohibitions"),
            ("source_status_prompt_ref", "identify_source_status"),
            ("requested_work_prompt_ref", "identify_requested_work"),
            ("work_relation_prompt_ref", "identify_work_relations"),
        )
    }
    with pytest.raises(_GoalInputCaptured):
        identify_goal_with_budget(
            llm_runtime=runtime,
            request=projected["request"],
            retry_budget=budget,
            source_dependency_candidates=(),
            output_responsibility_candidates=(),
            request_reconsideration=projected["request_reconsideration"],
            **evaluation_refs,
        )
    assert runtime.captured is not None
    assert runtime.captured["request_reconsideration"] == signal
    assert runtime.captured["user_request"] == _REQUEST
    assert runtime.captured["requested_work"] == intent["requested_work"]
    assert runtime.captured["selected_resource_refs"] == []
    assert state == before
    assert len(runtime.calls) == 1  # Fake Work owner only; Goal capture stops execution.

    # Active Main remains WorkAnalysis-only: transport carry did not enable a
    # Review back-edge or grant authorization to execute this evaluation signal.
    assert (
        route_request_reconsideration(
            phase=WorkflowPhase.PLAN_REVIEW,
            state=cast(Any, state),
            result={
                "disposition": "REQUEST_RECONSIDERATION_REQUIRED",
                "workflow_signal": signal,
            },
        )
        is None
    )
