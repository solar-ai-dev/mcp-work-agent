from __future__ import annotations

from typing import Any, cast

import pytest
from tests.support.fakes.llm import FakeStructuredInferencePort

from google_work_agent.application.agents.request_understanding.contracts.request_intent import (
    RequestGoalCandidateV1,
)
from google_work_agent.application.agents.request_understanding.detect_ambiguity import (
    DETECT_AMBIGUITY_OUTPUT_SCHEMA,
    _validate_ambiguity,
    detect_ambiguity,
)
from google_work_agent.application.use_cases.run.guard_run_budget import build_default_run_budget
from google_work_agent.ports.llm.output_schema_validation import validate_output_schema
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
                "missing_information_owner": "USER",
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
        "selected_resource_refs": [],
    }


def test_detect_ambiguity__rejects_metadata__without_confirmation() -> None:
    with pytest.raises(ValueError, match="non-confirmation ambiguity metadata must be empty"):
        _validate_ambiguity(
            {
                "requires_confirmation": False,
                "missing_information_owner": "NONE",
                "reason_codes": ["MISSING_PROJECT_NAME"],
                "missing_fields": ["project_name"],
            }
        )


def test_detect_ambiguity_schema__rejects_empty_confirmation_details__before_application() -> None:
    errors = validate_output_schema(
        {
            "requires_confirmation": True,
            "missing_information_owner": "USER",
            "reason_codes": [],
            "missing_fields": ["analysis_scope"],
        },
        DETECT_AMBIGUITY_OUTPUT_SCHEMA.json_schema,
    )

    assert errors == ["$.reason_codes must contain at least 1 items"]


def test_selected_gmail_read__with_retrievable_content_gap__does_not_confirm() -> None:
    runtime = FakeStructuredInferencePort(outputs=[])
    request = WorkflowStartRequest(
        run_id="run-selected",
        conversation_id="conversation-1",
        workflow_key="thread-1",
        entry_mode="RESOURCE_SELECTED",
        requested_mode="LOCAL_GPU",
        request_text="선택한 메일을 읽고 요약해줘",
        selected_resource_ids=("thread-42",),
        selected_resources=(SelectedResourceRef(
            "ref-thread-42", "google_workspace", "gmail_thread", "thread-42"
        ),),
        run_budget=cast(dict[str, Any], build_default_run_budget()),
        correlation=WorkflowCorrelationContext("request-1", "command-1", "v1"),
    )
    candidate: RequestGoalCandidateV1 = {
        "goal": "선택한 메일 읽기",
        "completion_conditions": ["메일 내용을 요약한다"],
        "constraints": [],
        "requested_effect_hints": ["READ"],
        "requested_resource_hints": ["GMAIL_THREAD"],
        "analysis_requirement": "NONE",
    }

    result = detect_ambiguity(
        llm_runtime=runtime,
        request=request,
        goal_candidate=candidate,
        prompt_ref=PromptReference(
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
        ),
    )

    assert result == {"requires_confirmation": False, "reason_codes": [], "missing_fields": []}
    assert runtime.calls == []


def test_general_advice__does_not_ask_for_model_invented_user_choice() -> None:
    runtime = FakeStructuredInferencePort(outputs=[])
    request = _answer_only_request("프로젝트 회의 준비 원칙을 한 문장으로 알려줘.")
    candidate: RequestGoalCandidateV1 = {
        "goal": "프로젝트 회의 준비 원칙 제공",
        "completion_conditions": ["한 문장으로 원칙을 답한다"],
        "constraints": [],
        "requested_effect_hints": [],
        "requested_resource_hints": [],
        "analysis_requirement": "NONE",
    }

    result = detect_ambiguity(
        llm_runtime=runtime,
        request=request,
        goal_candidate=candidate,
        prompt_ref=PromptReference(
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
        ),
    )

    assert result == {"requires_confirmation": False, "reason_codes": [], "missing_fields": []}
    assert runtime.calls == []


def test_selected_gmail_analysis__does_not_invent_user_owned__ambiguity() -> None:
    runtime = FakeStructuredInferencePort(
        outputs=[
            {
                "requires_confirmation": True,
                "missing_information_owner": "USER",
                "reason_codes": ["MISSING_ANALYSIS_FOCUS"],
                "missing_fields": ["analysis_focus"],
            }
        ]
    )
    request = WorkflowStartRequest(
        run_id="run-selected",
        conversation_id="conversation-1",
        workflow_key="thread-1",
        entry_mode="RESOURCE_SELECTED",
        requested_mode="LOCAL_GPU",
        request_text="선택한 메일을 분석해줘",
        selected_resource_ids=("thread-42",),
        selected_resources=(SelectedResourceRef(
            "ref-thread-42", "google_workspace", "gmail_thread", "thread-42"
        ),),
        run_budget=cast(dict[str, Any], build_default_run_budget()),
        correlation=WorkflowCorrelationContext("request-1", "command-1", "v1"),
    )

    result = detect_ambiguity(
        llm_runtime=runtime,
        request=request,
        goal_candidate={
            "goal": "선택한 메일 분석",
            "completion_conditions": ["사용자가 선택한 관점으로 메일을 분석한다"],
            "constraints": [],
            "requested_effect_hints": ["READ"],
            "requested_resource_hints": ["GMAIL_THREAD"],
            "analysis_requirement": "REQUIRED",
        },
        prompt_ref=PromptReference(
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
        ),
    )

    assert result == {"requires_confirmation": False, "reason_codes": [], "missing_fields": []}
    assert runtime.calls == []


def test_general_tasks_analysis__retrieves_requested_result_fields__before_confirmation() -> None:
    runtime = FakeStructuredInferencePort(
        outputs=[
            {
                "requires_confirmation": True,
                "missing_information_owner": "USER",
                "reason_codes": ["BUDGET_FIELD_MISSING"],
                "missing_fields": ["승인 예산"],
            }
        ]
    )
    request = WorkflowStartRequest(
        run_id="run-tasks",
        conversation_id="conversation-1",
        workflow_key="thread-1",
        entry_mode="AGENT_SEARCH",
        requested_mode="LOCAL_GPU",
        request_text=(
            "Google Tasks에 있는 현재 할 일을 읽고 담당자와 승인 예산 정보가 있는지 "
            "분석해줘."
        ),
        selected_resource_ids=(),
        run_budget=cast(dict[str, Any], build_default_run_budget()),
        correlation=WorkflowCorrelationContext("request-1", "command-1", "v1"),
    )

    result = detect_ambiguity(
        llm_runtime=runtime,
        request=request,
        goal_candidate={
            "goal": "현재 Tasks의 담당자와 승인 예산 정보를 분석한다",
            "completion_conditions": ["현재 Tasks를 읽는다", "담당자와 예산을 확인한다"],
            "constraints": [],
            "requested_effect_hints": ["READ"],
            "requested_resource_hints": ["TASK"],
            "analysis_requirement": "REQUIRED",
        },
        prompt_ref=PromptReference(
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
        ),
    )

    assert result == {"requires_confirmation": False, "reason_codes": [], "missing_fields": []}
    assert runtime.calls == []


def test_selected_gmail_send__with_missing_recipient__preserves_confirmation() -> None:
    runtime = FakeStructuredInferencePort(
        outputs=[
            {
                "requires_confirmation": True,
                "missing_information_owner": "USER",
                "reason_codes": ["MISSING_RECIPIENT"],
                "missing_fields": ["recipient"],
            }
        ]
    )
    request = WorkflowStartRequest(
        run_id="run-selected",
        conversation_id="conversation-1",
        workflow_key="thread-1",
        entry_mode="RESOURCE_SELECTED",
        requested_mode="LOCAL_GPU",
        request_text="이 메일에 답장해줘",
        selected_resource_ids=("thread-42",),
        selected_resources=(SelectedResourceRef(
            "ref-thread-42", "google_workspace", "gmail_thread", "thread-42"
        ),),
        run_budget=cast(dict[str, Any], build_default_run_budget()),
        correlation=WorkflowCorrelationContext("request-1", "command-1", "v1"),
    )
    candidate: RequestGoalCandidateV1 = {
        "goal": "선택한 메일에 답장",
        "completion_conditions": ["답장을 보낸다"],
        "constraints": [],
        "requested_effect_hints": ["READ", "SEND"],
        "requested_resource_hints": ["GMAIL_THREAD"],
        "analysis_requirement": "REQUIRED",
    }

    result = detect_ambiguity(
        llm_runtime=runtime,
        request=request,
        goal_candidate=candidate,
        prompt_ref=PromptReference(
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
        ),
    )

    assert result["requires_confirmation"] is True
    assert result["missing_fields"] == ["recipient"]


def _answer_only_request(text: str) -> WorkflowStartRequest:
    return WorkflowStartRequest(
        run_id="run-answer",
        conversation_id="conversation-1",
        workflow_key="thread-1",
        entry_mode="AGENT_SEARCH",
        requested_mode="LOCAL_GPU",
        request_text=text,
        selected_resource_ids=(),
        run_budget=cast(dict[str, Any], build_default_run_budget()),
        correlation=WorkflowCorrelationContext("request-1", "command-1", "v1"),
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


def test_github_read__without_repository_constraint__requires_confirmation_before_llm() -> None:
    runtime = FakeStructuredInferencePort(outputs=[])
    candidate = _github_candidate("unused")
    candidate["constraints"] = []
    result = detect_ambiguity(
        llm_runtime=runtime, request=_request("GitHub 열린 이슈를 보여줘"),
        goal_candidate=candidate, prompt_ref=_prompt_ref(),
    )
    assert result["requires_confirmation"] is True
    assert result["missing_fields"] == ["repository"]
    assert runtime.calls == []


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
