"""Artifact-partitioned Review representation; fake findings are not semantic PASS."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

import pytest
from scripts import review_request_owner_partition as candidate
from tests.evaluation import test_review_request_reconsideration_candidate as shared
from tests.evaluation.test_review_request_reconsideration_candidate import (
    _PLAN_REF,
    _REQUEST,
    _finding,
)

from google_work_agent.application.agents.review.contracts.review_findings import (
    review_inspector_output_schema,
)
from google_work_agent.ports.llm.output_schema_validation import validate_output_schema


@pytest.fixture(name="intent")
def _current_intent() -> dict[str, Any]:
    return shared.intent.__wrapped__()


def _request_finding() -> dict[str, Any]:
    return {
        "work_unit_ids": ["work-1"],
        "semantic_field_paths": ["$.resource_responsibilities.outputs"],
        "description": "조회 요청과 현재 변경 책임이 일치하지 않습니다.",
    }


def _root(*request_findings: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": 2,
        "dimension": candidate.DIMENSION,
        "request_intent_findings": list(request_findings),
        "planning_findings": [],
    }


def _validate(value: object, intent: dict[str, Any], **overrides: Any) -> dict[str, Any]:
    context = {
        "current_intent": intent,
        "user_request": _REQUEST,
        "current_plan_ref": _PLAN_REF,
        "known_action_ids": ["action-1"],
        "known_route_ids": ["route-1"],
        "known_evidence_ids": ["evidence-1"],
        "pre_publication": True,
    }
    context.update(overrides)
    return candidate.validate_and_project(value, **context)


def test_empty_sections_are_valid_and_not_a_semantic_pass(intent: dict[str, Any]) -> None:
    assert _validate(_root(), intent) == {
        "semantic_verdict": "UNREVIEWED",
        "validated_findings": [],
        "candidate_projections": [],
    }


def test_partition_preserves_existing_planning_schema() -> None:
    schema = candidate.build_output_schema(["work-1"]).json_schema
    ordinary = review_inspector_output_schema(candidate.DIMENSION).json_schema
    assert schema["properties"]["planning_findings"] == ordinary["properties"]["findings"]
    request = schema["properties"]["request_intent_findings"]["items"]
    assert set(request["properties"]) == {"work_unit_ids", "semantic_field_paths", "description"}
    assert request["additionalProperties"] is False


def test_request_section_projects_exact_current_authority_without_plan_refs(
    intent: dict[str, Any],
) -> None:
    value = _root(_request_finding())
    before = deepcopy((value, intent, _PLAN_REF))
    result = _validate(value, intent)
    finding = result["validated_findings"][0]
    assert finding["finding_kind"] == candidate.previous.REQUEST_SEMANTICS_ISSUE
    assert finding["code"] == candidate.REQUEST_FINDING_CODE
    assert finding["description"] == value["request_intent_findings"][0]["description"]
    assert (
        finding["evidence_refs"]
        == finding["affected_action_ids"]
        == finding["affected_route_ids"]
        == []
    )
    projection = result["candidate_projections"][0]
    assert projection["based_on_request_intent"] == intent["meta"]
    assert projection["based_on_planning_result"] == _PLAN_REF
    observation = projection["observations"][0]
    assert observation["request_work_units"] == intent["requested_work"]["work_units"]
    assert (
        observation["semantic_values"]["$.resource_responsibilities.outputs"]
        == intent["resource_responsibilities"]["outputs"]
    )
    assert (value, intent, _PLAN_REF) == before
    assert not {"approval", "execution_permission", "actions"} & projection.keys()
    observation["semantic_values"]["$.resource_responsibilities.outputs"][0]["effect"] = "DELETE"
    assert intent["resource_responsibilities"]["outputs"][0]["effect"] == "UPDATE"


@pytest.mark.parametrize(
    "kind", ["ISSUE", "EVIDENCE_GAP", "ROUTE_ISSUE", "CONFIRMATION", "BLOCKER"]
)
def test_planning_free_text_never_reclassifies_ownership(intent: dict[str, Any], kind: str) -> None:
    finding = _finding(kind)
    finding.update(code="REQUEST_SEMANTICS_ISSUE", description="원문 해석에 오류가 있습니다.")
    value = _root()
    value["planning_findings"] = [finding]
    result = _validate(value, intent)
    assert result["validated_findings"] == [finding]
    assert result["candidate_projections"] == []


@pytest.mark.parametrize(
    "field,value",
    [
        ("work_unit_ids", ["unknown-work"]),
        ("work_unit_ids", []),
        ("work_unit_ids", ["work-1", "work-1"]),
        ("semantic_field_paths", ["$.planning_result"]),
        ("semantic_field_paths", []),
        ("description", "English only"),
        ("code", "EXTRA_FIELD"),
    ],
)
def test_request_fields_are_closed(intent: dict[str, Any], field: str, value: Any) -> None:
    finding = _request_finding()
    finding[field] = value
    with pytest.raises(ValueError, match="partition schema"):
        _validate(_root(finding), intent)


def test_no_v1_shape_or_new_kind_in_planning_section(intent: dict[str, Any]) -> None:
    with pytest.raises(ValueError, match="partition schema"):
        _validate({"schema_version": 1, "dimension": candidate.DIMENSION, "findings": []}, intent)
    value = _root()
    value["planning_findings"] = [_finding()]
    assert validate_output_schema(value, candidate.build_output_schema(["work-1"]).json_schema)
    with pytest.raises(ValueError, match="partition schema"):
        _validate(value, intent)


@pytest.mark.parametrize("field", ["affected_action_ids", "affected_route_ids", "evidence_refs"])
def test_ordinary_closed_refs_remain_enforced(intent: dict[str, Any], field: str) -> None:
    finding = _finding("ISSUE")
    finding[field] = ["unknown-reference"]
    value = _root()
    value["planning_findings"] = [finding]
    with pytest.raises(ValueError, match="unknown current IDs"):
        _validate(value, intent)


@pytest.mark.parametrize(
    "override",
    [
        {"user_request": "다른 원문"},
        {"pre_publication": False},
        {"current_plan_ref": {"artifact_id": "plan-1", "revision": 0}},
    ],
)
def test_existing_provenance_and_prepublication_guards_remain(
    intent: dict[str, Any],
    override: dict[str, Any],
) -> None:
    with pytest.raises(ValueError):
        _validate(_root(_request_finding()), intent, **override)


def _request_only(*findings: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": 3,
        "dimension": candidate.DIMENSION,
        "request_intent_findings": list(findings),
    }


def _validate_request_only(
    value: object,
    intent: dict[str, Any],
    **overrides: Any,
) -> dict[str, Any]:
    context = {
        "current_intent": intent,
        "user_request": _REQUEST,
        "current_plan_ref": _PLAN_REF,
        "pre_publication": True,
    }
    context.update(overrides)
    return candidate.validate_request_only_and_project(value, **context)


def test_request_only_schema_reuses_exact_v2_request_item() -> None:
    properties = candidate.build_request_only_output_schema(["work-1"]).json_schema["properties"]
    previous = candidate.build_output_schema(["work-1"]).json_schema["properties"]
    assert properties["request_intent_findings"] == previous["request_intent_findings"]
    assert set(properties) == {"schema_version", "dimension", "request_intent_findings"}
    assert properties["schema_version"] == {"const": 3}


@pytest.mark.parametrize("findings", [[], [_request_finding()]])
def test_request_only_preserves_projection_but_never_claims_plan_was_reviewed(
    intent: dict[str, Any],
    findings: list[dict[str, Any]],
) -> None:
    raw = _request_only(*findings)
    before = deepcopy((raw, intent))
    result = _validate_request_only(raw, intent)
    expected = _validate(_root(*findings), intent)
    assert result == {**expected, "planning_semantics": "NOT_EVALUATED"}
    assert result["semantic_verdict"] == "UNREVIEWED"
    assert (raw, intent) == before


@pytest.mark.parametrize(
    "mutation",
    [
        {"schema_version": 2},
        {"planning_findings": []},
        {"findings": []},
        {"request_intent_findings": [{**_request_finding(), "work_unit_ids": ["unknown"]}]},
        {
            "request_intent_findings": [
                {**_request_finding(), "semantic_field_paths": ["$.actions"]}
            ]
        },
    ],
)
def test_request_only_rejects_wrong_shapes_and_closed_references(
    intent: dict[str, Any],
    mutation: dict[str, Any],
) -> None:
    with pytest.raises(ValueError, match="Request-only Review schema"):
        _validate_request_only({**_request_only(), **mutation}, intent)


@pytest.mark.parametrize(
    "override",
    [
        {"user_request": "다른 원문"},
        {"pre_publication": False},
        {"current_plan_ref": {"artifact_id": "plan-1", "revision": 0}},
    ],
)
def test_request_only_preserves_context_authority(
    intent: dict[str, Any],
    override: dict[str, Any],
) -> None:
    with pytest.raises(ValueError):
        _validate_request_only(_request_only(_request_finding()), intent, **override)
