from __future__ import annotations

from typing import Any, cast

import pytest
from tests.support.fakes.llm import FakeStructuredInferencePort

from google_work_agent.application.agents.request_understanding.contracts.request_intent import (
    RequestGoalCandidateV1,
)
from google_work_agent.application.agents.request_understanding.detect_ambiguity import (
    _validate_ambiguity,
    detect_ambiguity,
)
from google_work_agent.application.use_cases.run.guard_run_budget import build_default_run_budget
from google_work_agent.ports.llm.structured_inference_contracts import PromptReference
from google_work_agent.ports.system.contracts.workflow_execution import (
    SelectedResourceRef,
    WorkflowCorrelationContext,
    WorkflowStartRequest,
)


def test_detect_ambiguity__canonical_call__owns_independent_ambiguity() -> None:
    runtime = FakeStructuredInferencePort(
        outputs=[
            {
                "requires_confirmation": True,
                "reason_codes": ["MISSING_RECIPIENT"],
                "missing_fields": ["recipient"],
            }
        ]
    )
    request = WorkflowStartRequest(
        run_id="run-1",
        conversation_id="conversation-1",
        workflow_key="thread-1",
        entry_mode="AGENT_SEARCH",
        requested_mode="AUTO",
        request_text="일정을 잡아줘",
        selected_resource_ids=(),
        run_budget=cast(dict[str, Any], build_default_run_budget()),
        correlation=WorkflowCorrelationContext(
            request_id="request-1", command_id="command-1", api_contract_version="v1"
        ),
    )
    candidate: RequestGoalCandidateV1 = {
        "goal": "일정 만들기",
        "completion_conditions": ["일정을 만든다"],
        "constraints": [],
        "requested_effect_hints": ["CREATE"],
        "requested_resource_hints": ["CALENDAR_EVENT"],
        "analysis_requirement": "REQUIRED",
    }
    prompt_ref = PromptReference(
        prompt_bundle_version="test",
        prompt_id="request_understanding.detect_ambiguity",
        prompt_version="1",
        content_hash="hash",
        agent_role="request_understanding",
        subgraph_name="request_understanding",
        node_name="detect_ambiguity",
        node_state="INITIAL",
        purpose="detect_ambiguity",
        input_schema_version="v1",
        output_schema_version="v1",
    )

    result = detect_ambiguity(
        llm_runtime=runtime,
        request=request,
        goal_candidate=candidate,
        prompt_ref=prompt_ref,
    )

    assert result["requires_confirmation"] is True
    assert runtime.calls[0]["prompt_input"] == {
        "user_request": "일정을 잡아줘",
        "goal_candidate": candidate,
    }


def test_detect_ambiguity__rejects_metadata__without_confirmation() -> None:
    with pytest.raises(ValueError, match="non-confirmation ambiguity metadata must be empty"):
        _validate_ambiguity(
            {
                "requires_confirmation": False,
                "reason_codes": ["MISSING_PROJECT_NAME"],
                "missing_fields": ["project_name"],
            }
        )


@pytest.mark.parametrize("repository", ["google-work-agent", "other-owner/repo"])
def test_detect_ambiguity__forces_existing_confirmation_for__unbound_repository(
    repository: str,
) -> None:
    runtime = FakeStructuredInferencePort(
        outputs=[{"requires_confirmation": False, "reason_codes": [], "missing_fields": []}]
    )
    request = _request("저 저장소의 열린 이슈를 찾아줘")
    candidate = _github_candidate(repository)

    result = detect_ambiguity(
        llm_runtime=runtime,
        request=request,
        goal_candidate=candidate,
        prompt_ref=_prompt_ref(),
    )

    assert result == {
        "requires_confirmation": True,
        "reason_codes": ["MISSING_TARGET"],
        "missing_fields": ["repository"],
    }


def test_detect_ambiguity__accepts_confirmation_source__without_owner_guessing() -> None:
    repository = "solar-ai-dev/google-work-agent"
    runtime = FakeStructuredInferencePort(
        outputs=[{"requires_confirmation": False, "reason_codes": [], "missing_fields": []}]
    )

    result = detect_ambiguity(
        llm_runtime=runtime,
        request=_request("저 저장소의 열린 이슈를 찾아줘"),
        goal_candidate=_github_candidate(repository),
        prompt_ref=_prompt_ref(),
        confirmation_response={
            "schema_version": 1,
            "response_kind": "FREE_TEXT",
            "selected_option": None,
            "free_text": repository,
        },
    )

    assert result["requires_confirmation"] is False


def test_detect_ambiguity__selected_and_explicit_conflict__has_no_precedence() -> None:
    runtime = FakeStructuredInferencePort(
        outputs=[{"requires_confirmation": False, "reason_codes": [], "missing_fields": []}]
    )
    request = _request(
        "owner-b/repo의 열린 이슈를 찾아줘",
        selected_resources=(
            SelectedResourceRef(
                resource_ref_id="ref-1",
                connector_id="github",
                resource_type="github_issue",
                resource_id="owner-a/repo#7",
                parent_resource_id="owner-a/repo",
            ),
        ),
    )

    result = detect_ambiguity(
        llm_runtime=runtime,
        request=request,
        goal_candidate=_github_candidate("owner-b/repo"),
        prompt_ref=_prompt_ref(),
    )

    assert result["requires_confirmation"] is True
    assert result["missing_fields"] == ["repository"]


def test_detect_ambiguity__matching_selected_and_explicit_repository__is_unambiguous() -> None:
    repository = "owner-a/repo"
    runtime = FakeStructuredInferencePort(
        outputs=[{"requires_confirmation": False, "reason_codes": [], "missing_fields": []}]
    )

    result = detect_ambiguity(
        llm_runtime=runtime,
        request=_request(
            f"List issues in {repository}",
            selected_resources=(
                SelectedResourceRef(
                    resource_ref_id="ref-1",
                    connector_id="github",
                    resource_type="github_issue",
                    resource_id=f"{repository}#7",
                    parent_resource_id=repository,
                ),
            ),
        ),
        goal_candidate=_github_candidate(repository),
        prompt_ref=_prompt_ref(),
    )

    assert result["requires_confirmation"] is False


def _github_candidate(repository: str) -> RequestGoalCandidateV1:
    return {
        "goal": "열린 이슈 조회",
        "completion_conditions": ["이슈를 나열한다"],
        "constraints": [{"kind": "RESOURCE", "field": "repository", "value": repository}],
        "requested_effect_hints": ["READ"],
        "requested_resource_hints": ["GITHUB_ISSUE"],
        "analysis_requirement": "NONE",
    }


def _request(
    request_text: str,
    *,
    selected_resources: tuple[SelectedResourceRef, ...] = (),
) -> WorkflowStartRequest:
    return WorkflowStartRequest(
        run_id="run-1",
        conversation_id="conversation-1",
        workflow_key="thread-1",
        entry_mode="RESOURCE_SELECTED" if selected_resources else "AGENT_SEARCH",
        requested_mode="AUTO",
        request_text=request_text,
        selected_resource_ids=tuple(item.resource_id for item in selected_resources),
        run_budget=cast(dict[str, Any], build_default_run_budget()),
        correlation=WorkflowCorrelationContext(
            request_id="request-1", command_id="command-1", api_contract_version="v1"
        ),
        selected_resources=selected_resources,
    )


def _prompt_ref() -> PromptReference:
    return PromptReference(
        prompt_bundle_version="test",
        prompt_id="request_understanding.detect_ambiguity",
        prompt_version="1",
        content_hash="hash",
        agent_role="request_understanding",
        subgraph_name="request_understanding",
        node_name="detect_ambiguity",
        node_state="INITIAL",
        purpose="detect_ambiguity",
        input_schema_version="v1",
        output_schema_version="v1",
    )
