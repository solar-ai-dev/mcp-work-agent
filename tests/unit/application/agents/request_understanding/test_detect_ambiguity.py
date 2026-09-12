from __future__ import annotations

from typing import Any, cast

import pytest
from tests.support.fakes.llm import FakeStructuredInferencePort

from google_work_agent.application.agents.request_understanding.contracts.request_intent import (
    AmbiguityV1,
    RequestGoalCandidateV1,
)
from google_work_agent.application.agents.request_understanding.detect_ambiguity import (
    DETECT_AMBIGUITY_OUTPUT_SCHEMA,
)
from google_work_agent.application.agents.request_understanding.detect_ambiguity import (
    detect_ambiguity as _detect_ambiguity_with_budget,
)
from google_work_agent.application.use_cases.run.guard_run_budget import build_default_run_budget
from google_work_agent.ports.llm.output_schema_validation import validate_output_schema
from google_work_agent.ports.llm.structured_inference_contracts import PromptReference
from google_work_agent.ports.system.contracts.workflow_execution import (
    SelectedResourceRef,
    WorkflowCorrelationContext,
    WorkflowStartRequest,
)


def detect_ambiguity(**kwargs: object) -> AmbiguityV1:
    ambiguity, _ = _detect_ambiguity_with_budget(
        **kwargs,
        retry_budget=build_default_run_budget(),
    )
    return ambiguity


def test_detect_ambiguity__canonical_call__owns_independent_ambiguity() -> None:
    runtime = FakeStructuredInferencePort(
        outputs=[
            {
                "missing_information_owner": "USER",
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
        "resolution_responsibilities": {
            "connector_owned_information": [],
            "resolved_resource_refs": [],
            "searchable_target_anchor_count": 0,
            "connector_owned_source_count": 0,
        },
        "selected_resource_refs": [],
    }


def test_connector_owned_information__before_retrieval__proceeds_without_confirmation() -> None:
    runtime = FakeStructuredInferencePort(
        outputs=[
            {
                "missing_information_owner": "CONNECTOR",
                "missing_fields": ["납품 일정"],
            }
        ]
    )
    candidate: RequestGoalCandidateV1 = {
        "goal": "기존 대화의 납품 일정을 확인하고 답장한다",
        "completion_conditions": ["기존 대화에 답장을 보낸다"],
        "constraints": [
            {
                "kind": "USER_REQUIREMENT",
                "field": "required_information",
                "value": ["납품 일정", "답장 대상 identity"],
            }
        ],
        "requested_effect_hints": ["READ", "SEND"],
        "requested_resource_hints": ["GMAIL_THREAD", "GMAIL_MESSAGE"],
        "analysis_requirement": "NONE",
    }

    result = detect_ambiguity(
        llm_runtime=runtime,
        request=_request("기존 메일의 납품 일정을 확인하고 답장해줘"),
        goal_candidate=candidate,
        prompt_ref=_prompt_ref(),
    )

    assert result == {"requires_confirmation": False, "reason_codes": [], "missing_fields": []}
    assert runtime.calls[0]["prompt_input"]["resolution_responsibilities"] == {
        "connector_owned_information": [
            {
                "constraint_path": "$.goal_candidate.constraints[0]",
                "information": "납품 일정",
                "owner": "CONNECTOR",
            },
            {
                "constraint_path": "$.goal_candidate.constraints[0]",
                "information": "답장 대상 identity",
                "owner": "CONNECTOR",
            },
        ],
        "resolved_resource_refs": [],
        "searchable_target_anchor_count": 0,
        "connector_owned_source_count": 0,
    }


def test_connector_need_reclassified_as_user__contract_conflict__uses_bounded_revision() -> None:
    runtime = FakeStructuredInferencePort(
        outputs=[
            {
                "missing_information_owner": "USER",
                "missing_fields": ["납품 일정"],
            },
            {
                "missing_information_owner": "CONNECTOR",
                "missing_fields": ["납품 일정"],
            },
        ]
    )
    candidate: RequestGoalCandidateV1 = {
        "goal": "기존 대화의 납품 일정을 확인하고 답장한다",
        "completion_conditions": ["기존 대화에 답장을 보낸다"],
        "constraints": [
            {
                "kind": "USER_REQUIREMENT",
                "field": "required_information",
                "value": ["납품 일정"],
            }
        ],
        "requested_effect_hints": ["READ", "SEND"],
        "requested_resource_hints": ["GMAIL_THREAD", "GMAIL_MESSAGE"],
        "analysis_requirement": "NONE",
    }

    ambiguity, budget = _detect_ambiguity_with_budget(
        llm_runtime=runtime,
        request=_request("기존 메일의 납품 일정을 확인하고 답장해줘"),
        goal_candidate=candidate,
        prompt_ref=_prompt_ref(),
        retry_budget=build_default_run_budget(),
    )

    assert ambiguity == {
        "requires_confirmation": False,
        "reason_codes": [],
        "missing_fields": [],
    }
    assert len(runtime.calls) == 2
    assert runtime.calls[1]["prompt_input"]["failure_record"]["failure_reason_code"] == (
        "REQUEST_AMBIGUITY_RESOLUTION_OWNER_CONFLICT"
    )
    assert len(budget["semantic_revisions_used_by_failure"]) == 1


def test_searchable_target_reclassified_as_user__contract_conflict__uses_bounded_revision() -> None:
    runtime = FakeStructuredInferencePort(
        outputs=[
            {
                "missing_information_owner": "USER",
                "missing_fields": ["target_resource"],
            },
            {
                "missing_information_owner": "CONNECTOR",
                "missing_fields": ["final shipment criteria and owner"],
            },
        ]
    )
    candidate: RequestGoalCandidateV1 = {
        "goal": "Confirm the final shipment criteria and owner from related mail",
        "completion_conditions": ["Answer from the retrieved mail evidence"],
        "constraints": [
            {
                "kind": "USER_REQUIREMENT",
                "field": "search_terms",
                "value": ["Project Anchor"],
            },
            {
                "kind": "USER_REQUIREMENT",
                "field": "required_information",
                "value": ["final shipment criteria", "owner"],
            },
        ],
        "requested_effect_hints": ["READ"],
        "requested_resource_hints": ["GMAIL_THREAD"],
        "resource_responsibilities": {
            "source_reads": [
                {
                    "resource_type": "GMAIL_THREAD",
                    "required_information": ["final shipment criteria", "owner"],
                }
            ],
            "outputs": [],
        },
        "analysis_requirement": "NONE",
    }

    ambiguity, budget = _detect_ambiguity_with_budget(
        llm_runtime=runtime,
        request=_request("Project Anchor mail shipment criteria and owner"),
        goal_candidate=candidate,
        prompt_ref=_prompt_ref(),
        retry_budget=build_default_run_budget(),
    )

    assert ambiguity == {
        "requires_confirmation": False,
        "reason_codes": [],
        "missing_fields": [],
    }
    assert len(runtime.calls) == 2
    resolution = runtime.calls[0]["prompt_input"]["resolution_responsibilities"]
    assert resolution["searchable_target_anchor_count"] == 1
    assert resolution["connector_owned_source_count"] == 1
    assert runtime.calls[1]["prompt_input"]["failure_record"]["failure_reason_code"] == (
        "REQUEST_AMBIGUITY_TARGET_ANCHOR_CONFLICT"
    )
    assert len(budget["semantic_revisions_used_by_failure"]) == 1


def test_detect_ambiguity__rejects_fields__without_owner() -> None:
    runtime = FakeStructuredInferencePort(
        outputs=[
            {"missing_information_owner": "NONE", "missing_fields": ["project_name"]},
            {"missing_information_owner": "NONE", "missing_fields": ["project_name"]},
        ]
    )
    candidate: RequestGoalCandidateV1 = {
        "goal": "새 할 일 생성",
        "completion_conditions": ["할 일을 생성한다"],
        "constraints": [],
        "requested_effect_hints": ["CREATE"],
        "requested_resource_hints": ["TASK"],
        "analysis_requirement": "NONE",
    }

    with pytest.raises(ValueError, match="NONE ambiguity fields must be empty"):
        detect_ambiguity(
            llm_runtime=runtime,
            request=_request("Google Tasks에 새 할 일을 만들어줘"),
            goal_candidate=candidate,
            prompt_ref=_prompt_ref(),
        )


def test_detect_ambiguity_schema__connector_owned_gap__passes_output_contract() -> None:
    errors = validate_output_schema(
        {
            "missing_information_owner": "CONNECTOR",
            "missing_fields": ["source_fact"],
        },
        DETECT_AMBIGUITY_OUTPUT_SCHEMA.json_schema,
    )

    assert errors == []


def test_detect_ambiguity_schema__accepts_user_owned_fields__without_derived_metadata() -> None:
    errors = validate_output_schema(
        {
            "missing_information_owner": "USER",
            "missing_fields": ["analysis_scope"],
        },
        DETECT_AMBIGUITY_OUTPUT_SCHEMA.json_schema,
    )

    assert errors == []


def test_selected_gmail_read__retrievable_content_gap__still_assesses_ambiguity() -> None:
    runtime = FakeStructuredInferencePort(
        outputs=[
            {
                "missing_information_owner": "CONNECTOR",
                "missing_fields": ["메일 본문"],
            }
        ]
    )
    request = WorkflowStartRequest(
        run_id="run-selected",
        conversation_id="conversation-1",
        workflow_key="thread-1",
        entry_mode="RESOURCE_SELECTED",
        requested_mode="LOCAL_GPU",
        request_text="선택한 메일을 읽고 요약해줘",
        selected_resource_ids=("thread-42",),
        selected_resources=(
            SelectedResourceRef("ref-thread-42", "google_workspace", "gmail_thread", "thread-42"),
        ),
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
    assert len(runtime.calls) == 1


def test_general_advice__model_invented_choice__does_not_ask_user() -> None:
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


def test_selected_gmail_analysis__user_owned_choice__may_require_confirmation() -> None:
    runtime = FakeStructuredInferencePort(
        outputs=[
            {
                "missing_information_owner": "USER",
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
        selected_resources=(
            SelectedResourceRef("ref-thread-42", "google_workspace", "gmail_thread", "thread-42"),
        ),
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

    assert result == {
        "requires_confirmation": True,
        "reason_codes": ["REQUEST_UNDERSTANDING_NEEDS_CONFIRMATION"],
        "missing_fields": ["analysis_focus"],
    }
    assert len(runtime.calls) == 1


def test_connector_owner_overlap__similar_wording__does_not_reclassify_user_choice() -> None:
    runtime = FakeStructuredInferencePort(
        outputs=[
            {
                "missing_information_owner": "USER",
                "missing_fields": ["Quartz 납품 일정 중 어느 변경안을 적용할지"],
            }
        ]
    )
    candidate: RequestGoalCandidateV1 = {
        "goal": "기존 대화의 납품 일정을 확인하고 변경안을 선택한다",
        "completion_conditions": ["선택된 변경안을 적용한다"],
        "constraints": [
            {
                "kind": "USER_REQUIREMENT",
                "field": "required_information",
                "value": ["납품 일정"],
            }
        ],
        "requested_effect_hints": ["READ", "UPDATE"],
        "requested_resource_hints": ["GMAIL_DRAFT"],
        "analysis_requirement": "REQUIRED",
    }

    result = detect_ambiguity(
        llm_runtime=runtime,
        request=_request("기존 초안을 읽고 변경할 일정을 정해줘"),
        goal_candidate=candidate,
        prompt_ref=_prompt_ref(),
    )

    assert result == {
        "requires_confirmation": True,
        "reason_codes": ["REQUEST_UNDERSTANDING_NEEDS_CONFIRMATION"],
        "missing_fields": ["Quartz 납품 일정 중 어느 변경안을 적용할지"],
    }
    assert len(runtime.calls) == 1


def test_general_tasks_analysis__retrieves_requested_result_fields__before_confirmation() -> None:
    runtime = FakeStructuredInferencePort(
        outputs=[
            {
                "missing_information_owner": "CONNECTOR",
                "missing_fields": ["담당자와 승인 예산"],
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
            "Google Tasks에 있는 현재 할 일을 읽고 담당자와 승인 예산 정보가 있는지 분석해줘."
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
    assert len(runtime.calls) == 1


def test_unselected_read__with_user_owned_target_gap__asks_before_retrieval() -> None:
    runtime = FakeStructuredInferencePort(
        outputs=[
            {
                "missing_information_owner": "USER",
                "missing_fields": ["target_resource"],
            }
        ]
    )
    candidate: RequestGoalCandidateV1 = {
        "goal": "일정 시각 확인",
        "completion_conditions": ["선택한 일정의 시각을 답한다"],
        "constraints": [],
        "requested_effect_hints": ["READ"],
        "requested_resource_hints": ["CALENDAR_EVENT"],
        "analysis_requirement": "NONE",
    }

    result = detect_ambiguity(
        llm_runtime=runtime,
        request=_request("그 일정 언제야?"),
        goal_candidate=candidate,
        prompt_ref=_prompt_ref(),
    )

    assert result == {
        "requires_confirmation": True,
        "reason_codes": ["REQUEST_UNDERSTANDING_NEEDS_CONFIRMATION"],
        "missing_fields": ["target_resource"],
    }
    assert len(runtime.calls) == 1


def test_unselected_read__target_identity_named_as_connector_need__still_asks_user() -> None:
    runtime = FakeStructuredInferencePort(
        outputs=[
            {
                "missing_information_owner": "USER",
                "missing_fields": ["target_resource"],
            }
        ]
    )
    candidate: RequestGoalCandidateV1 = {
        "goal": "일정 시각 확인",
        "completion_conditions": ["선택한 일정의 시각을 답한다"],
        "constraints": [],
        "requested_effect_hints": ["READ"],
        "requested_resource_hints": ["CALENDAR_EVENT"],
        "resource_responsibilities": {
            "source_reads": [
                {
                    "resource_type": "CALENDAR_EVENT",
                    "required_information": ["target_resource", "event_time"],
                }
            ],
            "outputs": [],
        },
        "analysis_requirement": "NONE",
    }

    result = detect_ambiguity(
        llm_runtime=runtime,
        request=_request("그 일정 언제야?"),
        goal_candidate=candidate,
        prompt_ref=_prompt_ref(),
    )

    assert result == {
        "requires_confirmation": True,
        "reason_codes": ["REQUEST_UNDERSTANDING_NEEDS_CONFIRMATION"],
        "missing_fields": ["target_resource"],
    }
    assert len(runtime.calls) == 1


def test_unselected_calendar_event_identity__without_target_anchor__is_user_owned() -> None:
    runtime = FakeStructuredInferencePort(
        outputs=[
            {
                "missing_information_owner": "USER",
                "missing_fields": ["event_identity"],
            }
        ]
    )

    result = detect_ambiguity(
        llm_runtime=runtime,
        request=_request("그 일정 언제야?"),
        goal_candidate=_calendar_event_identity_candidate(),
        prompt_ref=_prompt_ref(),
    )

    assert result == {
        "requires_confirmation": True,
        "reason_codes": ["REQUEST_UNDERSTANDING_NEEDS_CONFIRMATION"],
        "missing_fields": ["event_identity"],
    }
    assert len(runtime.calls) == 1


def test_searchable_calendar_event_identity__with_target_anchor__keeps_conflict() -> None:
    runtime = FakeStructuredInferencePort(
        outputs=[
            {
                "missing_information_owner": "USER",
                "missing_fields": ["event_identity"],
            },
            {
                "missing_information_owner": "CONNECTOR",
                "missing_fields": ["start"],
            },
        ]
    )

    result = detect_ambiguity(
        llm_runtime=runtime,
        request=_request("Nimbus 일정을 찾아서 언제인지 알려줘."),
        goal_candidate=_calendar_event_identity_candidate(searchable=True),
        prompt_ref=_prompt_ref(),
    )

    assert result == {"requires_confirmation": False, "reason_codes": [], "missing_fields": []}
    assert len(runtime.calls) == 2
    assert runtime.calls[1]["prompt_input"]["failure_record"]["failure_reason_code"] == (
        "REQUEST_AMBIGUITY_TARGET_ANCHOR_CONFLICT"
    )


def test_selected_event_identity__with_resource__keeps_resolved_conflict() -> None:
    runtime = FakeStructuredInferencePort(
        outputs=[
            {
                "missing_information_owner": "USER",
                "missing_fields": ["event_identity"],
            },
            {
                "missing_information_owner": "CONNECTOR",
                "missing_fields": ["start"],
            },
        ]
    )
    selected_event = SelectedResourceRef(
        "ref-event-42",
        "google_workspace",
        "calendar_event",
        "event-42",
    )

    result = detect_ambiguity(
        llm_runtime=runtime,
        request=_request("그 일정 언제야?", selected_resources=(selected_event,)),
        goal_candidate=_calendar_event_identity_candidate(),
        prompt_ref=_prompt_ref(),
    )

    assert result == {"requires_confirmation": False, "reason_codes": [], "missing_fields": []}
    assert len(runtime.calls) == 2
    assert runtime.calls[1]["prompt_input"]["failure_record"]["failure_reason_code"] == (
        "REQUEST_AMBIGUITY_TARGET_ANCHOR_CONFLICT"
    )


def test_connector_owned_event_attribute__with_resolved_target__keeps_owner_conflict() -> None:
    runtime = FakeStructuredInferencePort(
        outputs=[
            {
                "missing_information_owner": "USER",
                "missing_fields": ["start"],
            },
            {
                "missing_information_owner": "CONNECTOR",
                "missing_fields": ["start"],
            },
        ]
    )

    result = detect_ambiguity(
        llm_runtime=runtime,
        request=_request("Nimbus 일정이 언제인지 알려줘."),
        goal_candidate=_calendar_event_identity_candidate(),
        prompt_ref=_prompt_ref(),
    )

    assert result == {"requires_confirmation": False, "reason_codes": [], "missing_fields": []}
    assert len(runtime.calls) == 2
    assert runtime.calls[1]["prompt_input"]["failure_record"]["failure_reason_code"] == (
        "REQUEST_AMBIGUITY_RESOLUTION_OWNER_CONFLICT"
    )


def test_event_container_identity__without_selected_event__stays_container_scope() -> None:
    runtime = FakeStructuredInferencePort(
        outputs=[
            {
                "missing_information_owner": "USER",
                "missing_fields": ["calendar_identity"],
            },
            {
                "missing_information_owner": "CONNECTOR",
                "missing_fields": ["calendar_identity"],
            },
        ]
    )
    candidate = _calendar_event_identity_candidate()
    responsibilities = cast(dict[str, Any], candidate["resource_responsibilities"])
    source_reads = cast(list[dict[str, Any]], responsibilities["source_reads"])
    source_reads[0]["required_information"] = ["calendar_identity"]

    result = detect_ambiguity(
        llm_runtime=runtime,
        request=_request("어느 캘린더에서 일정을 확인해야 하는지 찾아줘."),
        goal_candidate=candidate,
        prompt_ref=_prompt_ref(),
    )

    assert result == {"requires_confirmation": False, "reason_codes": [], "missing_fields": []}
    assert len(runtime.calls) == 2
    assert runtime.calls[1]["prompt_input"]["failure_record"]["failure_reason_code"] == (
        "REQUEST_AMBIGUITY_RESOLUTION_OWNER_CONFLICT"
    )


def test_unselected_task_identity__without_target_anchor__uses_user_owner() -> None:
    runtime = FakeStructuredInferencePort(
        outputs=[
            {
                "missing_information_owner": "USER",
                "missing_fields": ["task_identity"],
            }
        ]
    )
    candidate: RequestGoalCandidateV1 = {
        "goal": "대상 할 일 확인",
        "completion_conditions": ["선택한 할 일을 답한다"],
        "constraints": [],
        "requested_effect_hints": ["READ"],
        "requested_resource_hints": ["TASK"],
        "resource_responsibilities": {
            "source_reads": [
                {
                    "resource_type": "TASK",
                    "required_information": ["task_identity", "title"],
                }
            ],
            "outputs": [],
        },
        "analysis_requirement": "NONE",
    }

    result = detect_ambiguity(
        llm_runtime=runtime,
        request=_request("그 할 일 보여줘."),
        goal_candidate=candidate,
        prompt_ref=_prompt_ref(),
    )

    assert result == {
        "requires_confirmation": True,
        "reason_codes": ["REQUEST_UNDERSTANDING_NEEDS_CONFIRMATION"],
        "missing_fields": ["task_identity"],
    }
    assert len(runtime.calls) == 1


def test_selected_calendar_read__with_selected_resource__does_not_ask_identity() -> None:
    runtime = FakeStructuredInferencePort(
        outputs=[
            {
                "missing_information_owner": "USER",
                "missing_fields": ["target_resource"],
            },
            {
                "missing_information_owner": "CONNECTOR",
                "missing_fields": ["event_time"],
            },
        ]
    )
    selected_event = SelectedResourceRef(
        "ref-event-42",
        "google_workspace",
        "calendar_event",
        "event-42",
    )
    candidate: RequestGoalCandidateV1 = {
        "goal": "선택한 일정의 시각 확인",
        "completion_conditions": ["선택한 일정의 시각을 답한다"],
        "constraints": [],
        "requested_effect_hints": ["READ"],
        "requested_resource_hints": ["CALENDAR_EVENT"],
        "analysis_requirement": "NONE",
    }

    result = detect_ambiguity(
        llm_runtime=runtime,
        request=_request("그 일정 언제야?", selected_resources=(selected_event,)),
        goal_candidate=candidate,
        prompt_ref=_prompt_ref(),
    )

    assert result == {"requires_confirmation": False, "reason_codes": [], "missing_fields": []}
    assert len(runtime.calls) == 2
    assert runtime.calls[1]["prompt_input"]["failure_record"]["failure_reason_code"] == (
        "REQUEST_AMBIGUITY_TARGET_ANCHOR_CONFLICT"
    )


def test_selected_source__with_separate_target_gap__asks_without_revision() -> None:
    runtime = FakeStructuredInferencePort(
        outputs=[
            {
                "missing_information_owner": "USER",
                "missing_fields": ["target_resource"],
            },
        ]
    )
    selected_mail = SelectedResourceRef(
        "ref-mail-42",
        "google_workspace",
        "gmail_thread",
        "thread-42",
    )
    candidate: RequestGoalCandidateV1 = {
        "goal": "선택한 메일을 참고해 별도 일정 대상을 확인",
        "completion_conditions": ["사용자가 정한 일정 대상을 확인한다"],
        "constraints": [],
        "requested_effect_hints": ["READ"],
        "requested_resource_hints": ["GMAIL_THREAD", "CALENDAR_EVENT"],
        "analysis_requirement": "NONE",
    }

    result = detect_ambiguity(
        llm_runtime=runtime,
        request=_request(
            "이 메일을 참고해서 그 일정을 확인해줘.",
            selected_resources=(selected_mail,),
        ),
        goal_candidate=candidate,
        prompt_ref=_prompt_ref(),
    )

    assert result == {
        "requires_confirmation": True,
        "reason_codes": ["REQUEST_UNDERSTANDING_NEEDS_CONFIRMATION"],
        "missing_fields": ["target_resource"],
    }
    assert len(runtime.calls) == 1
    assert runtime.calls[0]["prompt_input"]["selected_resource_refs"] == [
        {
            "resource_ref_id": "ref-mail-42",
            "connector_id": "google_workspace",
            "resource_type": "gmail_thread",
            "resource_id": "thread-42",
            "parent_resource_id": None,
        }
    ]


def test_selected_calendar_read__event_time_gap__passes_without_revision() -> None:
    runtime = FakeStructuredInferencePort(
        outputs=[
            {
                "missing_information_owner": "CONNECTOR",
                "missing_fields": ["event_time"],
            }
        ]
    )
    selected_event = SelectedResourceRef(
        "ref-event-42",
        "google_workspace",
        "calendar_event",
        "event-42",
    )
    candidate: RequestGoalCandidateV1 = {
        "goal": "선택한 일정의 시각 확인",
        "completion_conditions": ["선택한 일정의 시각을 답한다"],
        "constraints": [],
        "requested_effect_hints": ["READ"],
        "requested_resource_hints": ["CALENDAR_EVENT"],
        "analysis_requirement": "NONE",
    }

    result = detect_ambiguity(
        llm_runtime=runtime,
        request=_request("그 일정 언제야?", selected_resources=(selected_event,)),
        goal_candidate=candidate,
        prompt_ref=_prompt_ref(),
    )

    assert result == {"requires_confirmation": False, "reason_codes": [], "missing_fields": []}
    assert len(runtime.calls) == 1
    assert runtime.calls[0]["prompt_input"]["selected_resource_refs"] == [
        {
            "resource_ref_id": "ref-event-42",
            "connector_id": "google_workspace",
            "resource_type": "calendar_event",
            "resource_id": "event-42",
            "parent_resource_id": None,
        }
    ]


def test_named_gmail_target__retrievable_date__does_not_ask_user() -> None:
    runtime = FakeStructuredInferencePort(
        outputs=[
            {
                "missing_information_owner": "CONNECTOR",
                "missing_fields": ["launch_date"],
            }
        ]
    )
    candidate: RequestGoalCandidateV1 = {
        "goal": "Nimbus 출시 날짜 확인",
        "completion_conditions": ["메일 근거로 Nimbus 출시 날짜를 답한다"],
        "constraints": [],
        "requested_effect_hints": ["READ"],
        "requested_resource_hints": ["GMAIL_THREAD"],
        "analysis_requirement": "NONE",
    }

    result = detect_ambiguity(
        llm_runtime=runtime,
        request=_request("Nimbus 출시 날짜만 메일에서 확인해줘."),
        goal_candidate=candidate,
        prompt_ref=_prompt_ref(),
    )

    assert result == {"requires_confirmation": False, "reason_codes": [], "missing_fields": []}
    assert len(runtime.calls) == 1


def test_general_handoff_advice__without_external_resources__skips_ambiguity_inference() -> None:
    runtime = FakeStructuredInferencePort(outputs=[])
    candidate: RequestGoalCandidateV1 = {
        "goal": "업무 인수인계 메모의 일반적인 작성 항목 설명",
        "completion_conditions": ["일반적인 작성 항목을 답한다"],
        "constraints": [],
        "requested_effect_hints": [],
        "requested_resource_hints": [],
        "analysis_requirement": "NONE",
    }

    result = detect_ambiguity(
        llm_runtime=runtime,
        request=_answer_only_request("업무 인수인계 메모에는 보통 뭘 적으면 돼?"),
        goal_candidate=candidate,
        prompt_ref=_prompt_ref(),
    )

    assert result == {"requires_confirmation": False, "reason_codes": [], "missing_fields": []}
    assert runtime.calls == []


def test_selected_gmail_send__with_missing_recipient__preserves_confirmation() -> None:
    runtime = FakeStructuredInferencePort(
        outputs=[
            {
                "missing_information_owner": "USER",
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
        selected_resources=(
            SelectedResourceRef("ref-thread-42", "google_workspace", "gmail_thread", "thread-42"),
        ),
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
        outputs=[{"missing_information_owner": "NONE", "missing_fields": []}]
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
        outputs=[{"missing_information_owner": "NONE", "missing_fields": []}]
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
        outputs=[{"missing_information_owner": "NONE", "missing_fields": []}]
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
        outputs=[{"missing_information_owner": "NONE", "missing_fields": []}]
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


def _calendar_event_identity_candidate(
    *,
    searchable: bool = False,
) -> RequestGoalCandidateV1:
    return {
        "goal": "일정 시각 확인",
        "completion_conditions": ["대상 일정의 시각을 답한다"],
        "constraints": (
            [
                {
                    "kind": "USER_REQUIREMENT",
                    "field": "search_terms",
                    "value": ["Nimbus"],
                }
            ]
            if searchable
            else []
        ),
        "requested_effect_hints": ["READ"],
        "requested_resource_hints": ["CALENDAR_EVENT"],
        "resource_responsibilities": {
            "source_reads": [
                {
                    "resource_type": "CALENDAR_EVENT",
                    "required_information": ["event_identity", "start"],
                }
            ],
            "outputs": [],
        },
        "analysis_requirement": "NONE",
    }


def test_github_read__without_repository_constraint__requires_confirmation_before_llm() -> None:
    runtime = FakeStructuredInferencePort(outputs=[])
    candidate = _github_candidate("unused")
    candidate["constraints"] = []
    result = detect_ambiguity(
        llm_runtime=runtime,
        request=_request("GitHub 열린 이슈를 보여줘"),
        goal_candidate=candidate,
        prompt_ref=_prompt_ref(),
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
