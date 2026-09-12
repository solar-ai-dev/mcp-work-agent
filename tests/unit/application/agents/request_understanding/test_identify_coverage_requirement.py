from __future__ import annotations

import pytest
from tests.support.fakes.llm import FakeStructuredInferencePort

from google_work_agent.application.agents.request_understanding import (
    identify_coverage_requirement as coverage_requirement,
)
from google_work_agent.ports.llm.output_schema_validation import validate_output_schema
from google_work_agent.ports.llm.structured_inference_contracts import PromptReference


def _prompt_ref() -> PromptReference:
    return PromptReference(
        prompt_bundle_version="test",
        prompt_id="request_understanding.identify_coverage_requirement",
        prompt_version="1",
        content_hash="hash",
        agent_role="request_understanding",
        subgraph_name="request_understanding",
        node_name="identify_goal",
        node_state="INITIAL",
        purpose="identify_coverage_requirement",
        input_schema_version="v1",
        output_schema_version="v1",
    )


@pytest.mark.parametrize(
    ("user_request", "completion_conditions", "decision"),
    [
        (
            "Juniper 관련 제목 전부 알려줘",
            ["요청 범위의 제목 전체를 반환한다"],
            ["EXHAUSTIVE"],
        ),
        ("Juniper 관련 메일 찾아줘", ["관련 메일을 찾는다"], []),
        ("Juniper 관련 메일 몇 개 확인해줘", ["관련 메일 일부를 확인한다"], []),
        (
            "모든 열린 GitHub Issue를 보여줘",
            ["요청 범위의 열린 Issue 전체를 보여준다"],
            ["EXHAUSTIVE"],
        ),
        (
            "Task와 Calendar를 참고해서 Draft를 작성해줘",
            ["자료를 참고한 Draft를 작성한다"],
            [],
        ),
    ],
)
def test_coverage_requirement__uses_one_atomic_decision(
    user_request: str,
    completion_conditions: list[str],
    decision: list[str],
) -> None:
    runtime = FakeStructuredInferencePort(
        outputs=[{"coverage_requirement": decision}],
        validate_schema=True,
    )

    result = coverage_requirement.identify_coverage_requirement(
        llm_runtime=runtime,
        requested_mode="LOCAL_GPU",
        prompt_ref=_prompt_ref(),
        prompt_input={"user_request": user_request, "selected_resource_refs": []},
        goal_candidate={
            "goal": "요청한 결과를 제공한다",
            "completion_conditions": completion_conditions,
        },
    )

    assert result == {"coverage_requirement": decision}
    assert runtime.calls[0]["prompt_input"] == {
        "user_request": user_request,
        "goal": "요청한 결과를 제공한다",
        "completion_conditions": completion_conditions,
    }
    constraint = coverage_requirement.normalize_coverage_requirement_constraint(result)
    assert constraint == (
        {
            "kind": "SCOPE",
            "field": "coverage_requirement",
            "value": "EXHAUSTIVE",
        }
        if decision
        else None
    )


@pytest.mark.parametrize(
    "value",
    [
        {},
        {"coverage_requirement": ["ALL_RESULTS"]},
        {"coverage_requirement": ["EXHAUSTIVE", "EXHAUSTIVE"]},
        {"coverage_requirement": [], "resource_type": "GMAIL_THREAD"},
    ],
)
def test_coverage_requirement_schema__rejects_values_outside_closed_choice(
    value: object,
) -> None:
    assert validate_output_schema(
        value,
        coverage_requirement.IDENTIFY_COVERAGE_REQUIREMENT_OUTPUT_SCHEMA.json_schema,
    )
    with pytest.raises(ValueError, match="coverage requirement candidate is invalid"):
        coverage_requirement.validate_coverage_requirement_decision(value)
