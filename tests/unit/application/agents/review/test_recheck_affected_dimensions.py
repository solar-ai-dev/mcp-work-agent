from __future__ import annotations

from collections.abc import Mapping

import pytest

from google_work_agent.adapters.llm.runtime.schema_repair_scope import (
    find_out_of_scope_schema_repair_changes,
)
from google_work_agent.application.agents.review.contracts.review_findings import (
    review_recheck_output_schema,
)
from google_work_agent.application.agents.review.recheck_affected_dimensions import (
    recheck_affected_dimensions,
)
from google_work_agent.ports.llm.output_schema_validation import validate_output_schema


def test_recheck_affected_dimensions__uses_one_prompt__and_bounded_selector() -> None:
    calls: list[tuple[str, Mapping[str, object]]] = []

    def invoke(prompt_id: str, prompt_input: Mapping[str, object]) -> Mapping[str, object]:
        calls.append((prompt_id, prompt_input))
        return {
            "schema_version": 2,
            "affected_dimensions": ["review.inspect_action_scope_and_route"],
            "issue_assessments": [],
            "findings": [],
        }

    result = recheck_affected_dimensions(
        affected_dimensions=["review.inspect_action_scope_and_route"],
        affected_action_ids=["a1"],
        affected_route_ids=["r1"],
        request_intent={"goal": "update task"},
        tool_route_plan={"route_id": "r1"},
        planning_result={"actions": [{"action_id": "a1"}]},
        evidence=[],
        invoke=invoke,
    )

    assert result["affected_dimensions"] == ("review.inspect_action_scope_and_route",)
    assert [prompt_id for prompt_id, _ in calls] == ["review.recheck_affected_dimensions"]
    prompt_input = calls[0][1]
    assert "prior_review_findings" not in prompt_input
    assert "full_plan" not in prompt_input


def test_recheck_requires_one_assessment_per_historical_issue_without_masking_finding() -> None:
    transition = {"historical_review_issues": [{"description": "old"}]}

    def invoke(_prompt_id: str, _input: Mapping[str, object]) -> Mapping[str, object]:
        return {
            "schema_version": 2,
            "affected_dimensions": ["review.inspect_goal_and_evidence"],
            "issue_assessments": [
                {"issue_index": 0, "state": "RESOLVED", "current_reason": "current value"}
            ],
            "findings": [
                {
                    "dimension": "review.inspect_goal_and_evidence",
                    "code": "new",
                    "finding_kind": "ISSUE",
                    "description": "다른 현재 문제",
                    "evidence_refs": [],
                    "affected_action_ids": [],
                    "affected_route_ids": [],
                    "required_information": [],
                }
            ],
        }

    result = recheck_affected_dimensions(
        affected_dimensions=["review.inspect_goal_and_evidence"],
        request_intent={},
        planning_result={},
        proposal_transition=transition,
        invoke=invoke,
    )
    assert len(result["findings"]) == 1

    with pytest.raises(ValueError, match="assess each historical issue"):
        recheck_affected_dimensions(
            affected_dimensions=["review.inspect_goal_and_evidence"],
            request_intent={},
            planning_result={},
            proposal_transition=transition,
            invoke=lambda *_: {**invoke("", {}), "issue_assessments": []},
        )


@pytest.mark.parametrize("state", ["UNRESOLVED", "UNCERTAIN"])
def test_recheck_cannot_pass_with_unresolved_assessment_and_no_findings(state: str) -> None:
    transition = {"historical_review_issues": [{"description": "old"}]}
    output = {
        "schema_version": 2,
        "affected_dimensions": ["review.inspect_goal_and_evidence"],
        "issue_assessments": [
            {"issue_index": 0, "state": state, "current_reason": "아직 판단할 수 없음"}
        ],
        "findings": [],
    }
    schema = review_recheck_output_schema(("review.inspect_goal_and_evidence",), 1)
    errors = validate_output_schema(output, schema.json_schema)
    assert any("$.findings" in error for error in errors)
    with pytest.raises(ValueError, match="finding"):
        recheck_affected_dimensions(
            affected_dimensions=["review.inspect_goal_and_evidence"],
            request_intent={},
            planning_result={},
            proposal_transition=transition,
            invoke=lambda *_: output,
        )


def test_recheck_multiple_prior_issues_can_share_one_finding() -> None:
    dimension = "review.inspect_constraints_and_policy_summary"
    schema = review_recheck_output_schema((dimension,), 2)
    output = {
        "schema_version": 2,
        "affected_dimensions": [dimension],
        "issue_assessments": [
            {"issue_index": index, "state": "UNRESOLVED", "current_reason": "현재 위반"}
            for index in (0, 1)
        ],
        "findings": [
            {
                "dimension": dimension,
                "code": "constraint",
                "finding_kind": "ISSUE",
                "description": "현재 계획의 금지 조건 위반",
                "evidence_refs": [],
                "affected_action_ids": ["a1", "a2"],
                "affected_route_ids": [],
                "required_information": [],
            }
        ],
    }
    assert validate_output_schema(output, schema.json_schema) == []
    assert not find_out_of_scope_schema_repair_changes(
        failed_output={**output, "findings": []},
        repaired_output=output,
        affected_field_paths=("$.findings",),
        output_schema=schema.json_schema,
    )
    result = recheck_affected_dimensions(
        affected_dimensions=[dimension],
        request_intent={},
        planning_result={},
        proposal_transition={"historical_review_issues": [{}, {}]},
        invoke=lambda *_: output,
    )
    assert len(result["findings"]) == 1


def test_recheck_confirmation_without_transition_keeps_dimension_only_scope() -> None:
    dimension = "review.inspect_goal_and_evidence"
    confirmation = {"selected_value": "current choice"}
    calls: list[Mapping[str, object]] = []

    def invoke(_prompt_id: str, prompt_input: Mapping[str, object]) -> Mapping[str, object]:
        calls.append(prompt_input)
        return {
            "schema_version": 2,
            "affected_dimensions": [dimension],
            "issue_assessments": [],
            "findings": [
                {
                    "dimension": dimension,
                    "code": "new",
                    "finding_kind": "ISSUE",
                    "description": "현재 제안에 별도 오류가 있음",
                    "evidence_refs": [],
                    "affected_action_ids": [],
                    "affected_route_ids": [],
                    "required_information": [],
                }
            ],
        }

    result = recheck_affected_dimensions(
        affected_dimensions=[dimension],
        affected_action_ids=[],
        affected_route_ids=[],
        request_intent={},
        planning_result={"actions": [{"action_id": "a1"}, {"action_id": "a2"}]},
        confirmation_response=confirmation,
        invoke=invoke,
    )
    schema = review_recheck_output_schema((dimension,))
    assert validate_output_schema(invoke("", calls[0]), schema.json_schema) == []
    assert calls[0]["confirmation_response"] == confirmation
    assert calls[0]["affected_action_ids"] == []
    assert len(result["findings"]) == 1
