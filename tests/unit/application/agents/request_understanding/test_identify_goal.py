from __future__ import annotations

from dataclasses import replace
from typing import Any, cast

import pytest
from tests.support.fakes.llm import FakeStructuredInferencePort

from google_work_agent.application.agents.request_understanding.contracts import (
    request_goal_candidate_schema as goal_schema,
)
from google_work_agent.application.agents.request_understanding.contracts.request_intent import (
    AmbiguityV1,
    validated_repository_authority,
)
from google_work_agent.application.agents.request_understanding.detect_ambiguity import (
    detect_ambiguity as _detect_ambiguity_with_budget,
)
from google_work_agent.application.agents.request_understanding.finalize_intent import (
    finalize_intent,
)
from google_work_agent.application.agents.request_understanding.identify_goal import (
    identify_goal,
    identify_goal_with_budget,
)
from google_work_agent.application.use_cases.run.guard_run_budget import build_default_run_budget
from google_work_agent.ports.llm.structured_inference_contracts import (
    OutputSchemaDefinition,
    PromptReference,
)
from google_work_agent.ports.system.contracts.workflow_execution import (
    SelectedResourceRef,
    WorkflowCorrelationContext,
    WorkflowStartRequest,
)
from google_work_agent.ports.system.settings_port import GitHubRepositoryDefaultV1

_GMAIL_CONSTRAINT_KINDS = {
    "search_terms": "USER_REQUIREMENT",
    "business_concepts": "USER_REQUIREMENT",
    "required_information": "USER_REQUIREMENT",
    "person": "PERSON",
    "sender": "PERSON",
    "recipient": "PERSON",
    "subject": "RESOURCE",
    "period": "DATE",
    "status": "SCOPE",
}


def detect_ambiguity(**kwargs: object) -> AmbiguityV1:
    ambiguity, _ = _detect_ambiguity_with_budget(
        **kwargs,
        retry_budget=build_default_run_budget(),
    )
    return ambiguity


def _goal_constraints(
    *additional: dict[str, object], **values: list[object]
) -> dict[str, object]:
    return {
        **dict.fromkeys(_GMAIL_CONSTRAINT_KINDS, []),
        **values,
        "additional_constraints": list(additional),
    }


def _source_status(
    value: str,
    resource_type: str,
    source_text: str,
) -> dict[str, str]:
    return {
        "value": value,
        "source_resource_type": resource_type,
        "source": "USER_REQUEST",
        "source_text": source_text,
    }


def _resource_responsibilities(
    *,
    source_type: str,
    required_information: list[str],
    output_type: str,
    output_effect: str,
) -> dict[str, list[dict[str, object]]]:
    return {
        "source_reads": [
            {
                "resource_type": source_type,
                "required_information": required_information,
            }
        ],
        "outputs": [{"resource_type": output_type, "effect": output_effect}],
    }


@pytest.mark.parametrize(
    "kind,valid",
    [("RESOURCE", False), ("SCOPE", False), ("USER_REQUIREMENT", True)],
)
def test_normalized_search_semantic_fields__wrong_kind__fails_output_contract(
    kind: str, valid: bool
) -> None:
    candidate = {
        "goal": "자료 확인", "completion_conditions": ["최종 기준 확인"],
        "constraints": [
            {"kind": kind, "field": "business_concepts", "value": ["출하"]}
        ],
        "requested_effect_hints": ["READ"],
        "requested_resource_hints": ["GMAIL_THREAD", "TASK"],
        "analysis_requirement": "NONE",
    }
    if valid:
        goal_schema.validate_normalized_request_goal_candidate(candidate)
    else:
        with pytest.raises(ValueError, match="normalized request goal candidate is invalid"):
            goal_schema.validate_normalized_request_goal_candidate(candidate)


def test_gmail_goal__unknown_named_slot__rejects_before_routing() -> None:
    runtime = FakeStructuredInferencePort(outputs=[{
        "goal": "프로젝트 자료 확인", "completion_conditions": ["확인"],
        "constraints": {"target_project": ["ORB-17"]},
        "requested_effect_hints": ["READ"], "requested_resource_hints": ["GMAIL_THREAD"],
        "analysis_requirement": "NONE",
    }])
    with pytest.raises(ValueError, match="request goal candidate is invalid"):
        identify_goal(
            llm_runtime=runtime, request=_request("ORB-17 메일 찾아줘"),
            prompt_ref=_prompt_ref("request_understanding.identify_goal", "identify_goal"),
        )


def test_gmail_goal__keyed_slots__preserves_distinct_semantic_roles() -> None:
    runtime = FakeStructuredInferencePort(outputs=[{
        "goal": "근거 조회", "completion_conditions": ["사실 확인"],
        "constraints": _goal_constraints(
            search_terms=["ORB-17"], person=["박과장"],
            sender=["sender@example.test"], recipient=["recipient@example.test"],
            business_concepts=["검수"], period=["이번 주"],
            required_information=["최종 정정된 시각"],
        ),
        "requested_effect_hints": ["READ"], "requested_resource_hints": ["GMAIL_THREAD"],
        "analysis_requirement": "NONE",
    }])
    candidate = identify_goal(
        llm_runtime=runtime,
        request=_request(
            "ORB-17 박과장 이번 주 검수 메일 찾아줘. "
            "sender@example.test가 recipient@example.test에 보낸 최종 정정 시각 알려줘."
        ),
        prompt_ref=_prompt_ref("request_understanding.identify_goal", "identify_goal"),
    )
    fields = {item["field"]: item for item in candidate["constraints"]}
    assert fields["search_terms"]["value"] == ["ORB-17"]
    assert fields["business_concepts"]["value"] == ["검수"]
    assert fields["sender"]["value"] == ["sender@example.test"]
    assert fields["recipient"]["value"] == ["recipient@example.test"]
    assert fields["period"]["value"] == ["이번 주"]
    assert "temporal_axis" not in fields
    assert "subject" not in fields


def test_source_status__explicit_sent_scope__retains_resource_and_source_provenance() -> None:
    request = _request("보낸 편지함에서 Quartz 찾아줘")
    runtime = FakeStructuredInferencePort(outputs=[{
        "goal": "보낸 메일에서 Quartz 자료 조회",
        "completion_conditions": ["일치하는 보낸 메일을 보여준다"],
        "constraints": _goal_constraints(
            search_terms=["Quartz"],
            status=[_source_status("SENT", "GMAIL_MESSAGE", "보낸 편지함")],
        ),
        "requested_effect_hints": ["READ"],
        "requested_resource_hints": ["GMAIL_MESSAGE"],
        "analysis_requirement": "NONE",
    }])

    candidate = identify_goal(
        llm_runtime=runtime,
        request=request,
        prompt_ref=_prompt_ref("request_understanding.identify_goal", "identify_goal"),
    )
    intent = finalize_intent(
        candidate,
        {"requires_confirmation": False, "reason_codes": [], "missing_fields": []},
        artifact_id="intent-sent",
        user_request=request.request_text,
    )

    status = next(item for item in intent["constraints"] if item["field"] == "status")
    assert status["value"] == "SENT"
    assert status["source_resource_type"] == "GMAIL_MESSAGE"
    assert status["provenance"]["source_text"] == "보낸 편지함"


def test_source_status__without_current_run_source_binding__rejects_before_intent() -> None:
    runtime = FakeStructuredInferencePort(outputs=[{
        "goal": "기존 메일 대화에 답장",
        "completion_conditions": ["같은 대화에 답장을 보낸다"],
        "constraints": _goal_constraints(
            search_terms=["Quartz"],
            required_information=["납품 일정", "답장 대상 대화 identity"],
            status=[_source_status("SENT", "GMAIL_THREAD", "보낸 편지함")],
        ),
        "requested_effect_hints": ["READ", "SEND"],
        "requested_resource_hints": ["GMAIL_THREAD", "GMAIL_MESSAGE"],
        "resource_responsibilities": _resource_responsibilities(
            source_type="GMAIL_THREAD",
            required_information=["납품 일정", "답장 대상 대화 identity"],
            output_type="GMAIL_MESSAGE",
            output_effect="SEND",
        ),
        "analysis_requirement": "NONE",
    }])

    with pytest.raises(ValueError, match="source binding"):
        identify_goal(
            llm_runtime=runtime,
            request=_request("Quartz 납품 일정 확인했다고 답장 보내줘."),
            prompt_ref=_prompt_ref("request_understanding.identify_goal", "identify_goal"),
        )


def test_thread_reply__without_explicit_source_status__does_not_create_status() -> None:
    runtime = FakeStructuredInferencePort(outputs=[{
        "goal": "기존 Quartz 메일 대화에 답장",
        "completion_conditions": ["같은 대화에 답장을 보낸다"],
        "constraints": _goal_constraints(
            search_terms=["Quartz"],
            required_information=["납품 일정", "답장 대상 대화 identity"],
        ),
        "requested_effect_hints": ["READ", "SEND"],
        "requested_resource_hints": ["GMAIL_THREAD", "GMAIL_MESSAGE"],
        "resource_responsibilities": _resource_responsibilities(
            source_type="GMAIL_THREAD",
            required_information=["납품 일정", "답장 대상 대화 identity"],
            output_type="GMAIL_MESSAGE",
            output_effect="SEND",
        ),
        "analysis_requirement": "NONE",
    }])

    candidate = identify_goal(
        llm_runtime=runtime,
        request=_request("Quartz 납품 일정 확인했다고 답장 보내줘."),
        prompt_ref=_prompt_ref("request_understanding.identify_goal", "identify_goal"),
    )

    assert not any(item["field"] == "status" for item in candidate["constraints"])


def test_cross_resource_read_write__without_typed_responsibility__rejects_before_routing() -> None:
    runtime = FakeStructuredInferencePort(outputs=[{
        "goal": "기존 자료를 근거로 메시지 전송",
        "completion_conditions": ["메시지를 보낸다"],
        "constraints": _goal_constraints(required_information=["기존 자료의 일정"]),
        "requested_effect_hints": ["READ", "SEND"],
        "requested_resource_hints": ["GMAIL_THREAD", "GMAIL_MESSAGE"],
        "analysis_requirement": "NONE",
    }])

    with pytest.raises(ValueError, match="resource_responsibilities"):
        identify_goal(
            llm_runtime=runtime,
            request=_request("기존 자료에서 일정을 확인해 관련 메시지를 보내줘."),
            prompt_ref=_prompt_ref("request_understanding.identify_goal", "identify_goal"),
        )


def test_cross_resource_read_write__responsibility_must_match_flat_hints() -> None:
    runtime = FakeStructuredInferencePort(outputs=[{
        "goal": "기존 자료를 근거로 메시지 전송",
        "completion_conditions": ["메시지를 보낸다"],
        "constraints": _goal_constraints(required_information=["기존 자료의 일정"]),
        "requested_effect_hints": ["READ", "CREATE", "SEND"],
        "requested_resource_hints": ["GMAIL_DRAFT", "GMAIL_MESSAGE"],
        "resource_responsibilities": _resource_responsibilities(
            source_type="GMAIL_THREAD",
            required_information=["기존 자료의 일정"],
            output_type="GMAIL_MESSAGE",
            output_effect="SEND",
        ),
        "analysis_requirement": "NONE",
    }])

    with pytest.raises(ValueError, match="requested hints"):
        identify_goal(
            llm_runtime=runtime,
            request=_request("기존 자료에서 일정을 확인해 관련 메시지를 보내줘."),
            prompt_ref=_prompt_ref("request_understanding.identify_goal", "identify_goal"),
        )


def test_cross_resource_read_write__bounded_revision_repairs_responsibility_mismatch() -> None:
    request = _request("기존 자료에서 일정을 확인해 관련 메시지를 보내줘.")
    corrected = {
        "goal": "기존 자료를 근거로 메시지 전송",
        "completion_conditions": ["메시지를 보낸다"],
        "constraints": _goal_constraints(required_information=["기존 자료의 일정"]),
        "requested_effect_hints": ["READ", "SEND"],
        "requested_resource_hints": ["GMAIL_THREAD", "GMAIL_MESSAGE"],
        "resource_responsibilities": _resource_responsibilities(
            source_type="GMAIL_THREAD",
            required_information=["기존 자료의 일정"],
            output_type="GMAIL_MESSAGE",
            output_effect="SEND",
        ),
        "analysis_requirement": "NONE",
    }
    runtime = FakeStructuredInferencePort(outputs=[
        {
            **corrected,
            "requested_effect_hints": ["READ", "CREATE", "SEND"],
            "requested_resource_hints": ["GMAIL_DRAFT", "GMAIL_MESSAGE"],
        },
        corrected,
    ])

    candidate, budget = identify_goal_with_budget(
        llm_runtime=runtime,
        request=request,
        retry_budget=build_default_run_budget(),
        prompt_ref=_prompt_ref("request_understanding.identify_goal", "identify_goal"),
    )

    assert candidate["requested_effect_hints"] == ["READ", "SEND"]
    assert candidate["requested_resource_hints"] == ["GMAIL_THREAD", "GMAIL_MESSAGE"]
    assert len(runtime.calls) == 2
    assert list(budget["semantic_revisions_used_by_failure"].values()) == [1]


def test_standalone_send__source_scope__does_not_create_status_or_read() -> None:
    runtime = FakeStructuredInferencePort(outputs=[{
        "goal": "새 메일 전송",
        "completion_conditions": ["새 메시지를 한 번 보낸다"],
        "constraints": _goal_constraints(
            recipient=["person@example.test"],
            subject=["안내"],
        ),
        "requested_effect_hints": ["SEND"],
        "requested_resource_hints": ["GMAIL_MESSAGE"],
        "analysis_requirement": "NONE",
    }])

    candidate = identify_goal(
        llm_runtime=runtime,
        request=_request(
            'person@example.test에게 제목은 “안내”, 본문은 “확인했습니다.”로 새 메일 보내줘.'
        ),
        prompt_ref=_prompt_ref("request_understanding.identify_goal", "identify_goal"),
    )

    assert candidate["requested_effect_hints"] == ["SEND"]
    assert not any(item["field"] == "status" for item in candidate["constraints"])


def test_gmail_goal__invented_exact_subject__is_not_promoted_to_anchor() -> None:
    runtime = FakeStructuredInferencePort(outputs=[{
        "goal": "근거 조회", "completion_conditions": ["확인"],
        "constraints": _goal_constraints(subject=["ORB-17 검수 일정"]),
        "requested_effect_hints": ["READ"], "requested_resource_hints": ["GMAIL_THREAD"],
        "analysis_requirement": "NONE",
    }])
    result = identify_goal(
        llm_runtime=runtime, request=_request("ORB-17 검수 관련 메일 찾아줘"),
        prompt_ref=_prompt_ref("request_understanding.identify_goal", "identify_goal"),
    )
    assert not any(item["field"] == "subject" for item in result["constraints"])


@pytest.mark.parametrize("value,valid", [("]", False), ("[]", False),
                                         ("東京", True), ("[검증]", True)])
def test_gmail_goal__empty_array_text__cannot_become_a_person(
    value: str, valid: bool
) -> None:
    runtime = FakeStructuredInferencePort(outputs=[{
        "goal": "근거 조회", "completion_conditions": ["확인"],
        "constraints": _goal_constraints(person=[value]),
        "requested_effect_hints": ["READ"], "requested_resource_hints": ["GMAIL_THREAD"],
        "analysis_requirement": "NONE",
    }])
    request = _request(f"{value}의 메일 찾아줘")
    prompt_ref = _prompt_ref("request_understanding.identify_goal", "identify_goal")
    if valid:
        result = identify_goal(llm_runtime=runtime, request=request, prompt_ref=prompt_ref)
        assert any(item["field"] == "person" and item["value"] == [value]
                   for item in result["constraints"])
    else:
        with pytest.raises(ValueError, match="request goal candidate is invalid"):
            identify_goal(llm_runtime=runtime, request=request, prompt_ref=prompt_ref)


def test_default_repository__stays_system_owned__without_user_constraint_or_confirmation() -> None:
    request = replace(
        _request("열린 이슈 보여줘"),
        default_github_repository=GitHubRepositoryDefaultV1("sample/project", 42, "github:1"),
    )
    runtime = FakeStructuredInferencePort(outputs=[{
        "goal": "열린 이슈 조회", "completion_conditions": ["조회 결과를 보여준다"],
        "constraints": _goal_constraints(
            status=[_source_status("OPEN", "GITHUB_ISSUE", "열린")]
        ),
        "requested_effect_hints": ["READ"], "requested_resource_hints": ["GITHUB_ISSUE"],
        "analysis_requirement": "NONE",
    }])
    candidate = identify_goal(
        llm_runtime=runtime, request=request,
        prompt_ref=_prompt_ref("request_understanding.identify_goal", "identify_goal"),
    )
    assert runtime.calls[0]["prompt_input"] == {
        "user_request": request.request_text, "selected_resource_refs": [],
    }
    ambiguity = detect_ambiguity(llm_runtime=runtime, request=request, goal_candidate=candidate)
    assert ambiguity["requires_confirmation"] is False
    assert all(item["field"] != "repository" for item in candidate["constraints"])
    intent = finalize_intent(
        candidate, ambiguity, artifact_id="intent-1", user_request=request.request_text,
        repository_default=request.default_github_repository,
    )
    assert intent["repository_default"]["repository"] == "sample/project"
    assert all(item["field"] != "repository" for item in intent["constraints"])


def test_explicit_repository__omitted_by_inference__retains_current_run_authority() -> None:
    repository = "acme/search-save"
    request = _request(f"{repository} 저장소의 열린 이슈를 조회해줘")
    runtime = FakeStructuredInferencePort(outputs=[{
        "goal": "열린 이슈 조회", "completion_conditions": ["조회 결과를 보여준다"],
        "constraints": _goal_constraints(
            status=[_source_status("OPEN", "GITHUB_ISSUE", "열린")]
        ),
        "requested_effect_hints": ["READ"], "requested_resource_hints": ["GITHUB_ISSUE"],
        "analysis_requirement": "NONE",
    }])

    candidate = identify_goal(
        llm_runtime=runtime, request=request,
        prompt_ref=_prompt_ref("request_understanding.identify_goal", "identify_goal"),
    )
    ambiguity = detect_ambiguity(
        llm_runtime=runtime, request=request, goal_candidate=candidate,
    )
    intent = finalize_intent(
        candidate, ambiguity, artifact_id="intent-1", user_request=request.request_text,
    )

    repository_constraint = next(
        item for item in intent["constraints"] if item["field"] == "repository"
    )
    assert ambiguity["requires_confirmation"] is False
    assert repository_constraint["value"] == repository
    assert repository_constraint["provenance"]["source"] == "USER_REQUEST"


@pytest.mark.parametrize("request_text, expected_resources", [
    (
        "Google Calendar에 'Gmail Google Tasks 검증' 일정을 만들어줘. "
        "설명은 '메일을 읽어줘'이고 참석자는 reviewer@gmail.com이야.",
        ["CALENDAR_EVENT"],
    ),
    (
        "reviewer@gmail.com의 메일을 찾아서 Google Calendar에 일정을 만들어줘.",
        ["CALENDAR_EVENT", "GMAIL_THREAD"],
    ),
])
def test_identify_goal__payload_literals_do_not__add_unrequested_resources(
    request_text: str, expected_resources: list[str],
) -> None:
    runtime = FakeStructuredInferencePort(outputs=[{
        "goal": "일정 생성", "completion_conditions": ["일정을 생성한다"],
        "constraints": _goal_constraints(
            {"kind": "RESOURCE", "field": "title", "value": "검증"}
        ),
        "requested_effect_hints": ["CREATE"],
        "requested_resource_hints": expected_resources,
        "analysis_requirement": "NONE",
    }])
    candidate = identify_goal(
        llm_runtime=runtime, request=_request(request_text),
        prompt_ref=_prompt_ref("request_understanding.identify_goal", "identify_goal"),
    )
    assert candidate["requested_resource_hints"] == expected_resources
    assert candidate["requested_effect_hints"] == ["CREATE"]


def test_identify_goal__preserves_exact_quoted__description_spacing() -> None:
    runtime = FakeStructuredInferencePort(outputs=[{
        "goal": "일정 생성", "completion_conditions": ["일정을 생성한다"],
        "constraints": _goal_constraints({
            "kind": "RESOURCE", "field": "description",
            "value": "Task 와 Calendar 검증 결과를 확인합니다.",
        }),
        "requested_effect_hints": ["CREATE"],
        "requested_resource_hints": ["CALENDAR_EVENT"], "analysis_requirement": "NONE",
    }])
    result = identify_goal(
        llm_runtime=runtime,
        request=_request("일정을 만들어줘. 설명은 'Task와 Calendar 검증 결과를 확인합니다.'야."),
        prompt_ref=_prompt_ref("request_understanding.identify_goal", "identify_goal"),
    )
    assert result["constraints"][0]["value"] == "Task와 Calendar 검증 결과를 확인합니다."


def test_identify_goal__with_spaced_literal__restores_exact_semantic_fields() -> None:
    exact_sentence = "8월 21일 입고 준비를 확인 중입니다."
    spaced_sentence = "8 월 21 일 입고 준비를 확인 중입니다."
    runtime = FakeStructuredInferencePort(outputs=[{
        "goal": f"초안 끝에 '{spaced_sentence}'만 추가",
        "completion_conditions": [f"'{spaced_sentence}'가 한 번만 추가된다"],
        "constraints": _goal_constraints(
            search_terms=["Quartz 납품 회신 검토"],
            required_information=[f"초안 끝에 '{spaced_sentence}'를 추가"],
            status=[_source_status("DRAFT", "GMAIL_DRAFT", "임시보관함")],
        ),
        "requested_effect_hints": ["READ", "UPDATE"],
        "requested_resource_hints": ["GMAIL_DRAFT"],
        "analysis_requirement": "NONE",
    }])

    result = identify_goal(
        llm_runtime=runtime,
        request=_request(
            '임시보관함의 “Quartz 납품 회신 검토” 초안 끝에 '
            f'“{exact_sentence}”만 추가해줘. 보내지는 마.'
        ),
        prompt_ref=_prompt_ref("request_understanding.identify_goal", "identify_goal"),
    )

    assert exact_sentence in result["goal"]
    assert exact_sentence in result["completion_conditions"][0]
    required_information = next(
        item["value"] for item in result["constraints"]
        if item["field"] == "required_information"
    )
    assert exact_sentence in required_information[0]
    assert spaced_sentence not in str(result)
    status = next(item for item in result["constraints"] if item["field"] == "status")
    assert status["value"] == "DRAFT"
    assert status["source_resource_type"] == "GMAIL_DRAFT"
    assert status["provenance"]["source_text"] == "임시보관함"


def test_identify_goal__canonical_call__uses_bounded_current_run_prompt() -> None:
    runtime = FakeStructuredInferencePort(
        outputs=[
            {
                "goal": "업무 메일 찾기",
                "completion_conditions": ["관련 메일을 찾는다"],
                "constraints": _goal_constraints(required_information=["관련 자료"]),
                "requested_effect_hints": ["READ"],
                "requested_resource_hints": ["GMAIL_THREAD"],
                "analysis_requirement": "REQUIRED",
            }
        ]
    )
    request = _request("관련 메일을 찾아줘")
    prompt_ref = _prompt_ref("request_understanding.identify_goal", "identify_goal")

    candidate = identify_goal(llm_runtime=runtime, request=request, prompt_ref=prompt_ref)

    assert candidate["goal"] == "업무 메일 찾기"
    assert "ambiguity" not in candidate
    assert runtime.calls[0]["prompt_input"] == {
        "user_request": "관련 메일을 찾아줘",
        "selected_resource_refs": [],
    }
    prompt = cast(PromptReference, runtime.calls[0]["prompt_ref"])
    assert prompt.prompt_id == "request_understanding.identify_goal"
    output_schema = cast(OutputSchemaDefinition, runtime.calls[0]["output_schema"])
    constraint_schema = cast(
        dict[str, Any],
        cast(dict[str, Any], output_schema.json_schema["properties"])["constraints"],
    )
    assert constraint_schema["type"] == "object"
    assert "additional_constraints" in constraint_schema["required"]


def test_identify_goal__selected_resource__preserves_trusted_read_identity() -> None:
    runtime = FakeStructuredInferencePort(
        outputs=[
            {
                "goal": "선택한 메일 요약",
                "completion_conditions": ["요약을 답한다"],
                "constraints": _goal_constraints(),
                "requested_effect_hints": [],
                "requested_resource_hints": [],
                "analysis_requirement": "NONE",
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
        selected_resources=(SelectedResourceRef(
            "ref-thread-42", "google_workspace", "gmail_thread", "thread-42"
        ),),
        run_budget=cast(dict[str, Any], build_default_run_budget()),
        correlation=WorkflowCorrelationContext("request-1", "command-1", "v1"),
    )

    candidate = identify_goal(
        llm_runtime=runtime,
        request=request,
        prompt_ref=_prompt_ref("request_understanding.identify_goal", "identify_goal"),
    )

    assert candidate["requested_effect_hints"] == ["READ"]
    assert candidate["requested_resource_hints"] == ["GMAIL_THREAD"]
    assert candidate["constraints"] == [
        {
            "kind": "RESOURCE",
            "field": "selected_resource_id",
            "value": ["thread-42"],
        }
    ]


def test_selected_github_issue__uses_typed_repository__without_unbound_duplicate() -> None:
    repository = "bonggyulim/search-save"
    runtime = FakeStructuredInferencePort(
        outputs=[
            {
                "goal": "선택한 GitHub Issue 조회",
                "completion_conditions": ["현재 제목, 상태, 본문을 보여준다"],
                "constraints": _goal_constraints(
                    {"kind": "RESOURCE", "field": "repository", "value": repository}
                ),
                "requested_effect_hints": ["READ"],
                "requested_resource_hints": ["GITHUB_ISSUE"],
                "analysis_requirement": "NONE",
            }
        ]
    )
    selected = SelectedResourceRef(
        "ref-issue-2",
        "github",
        "github_issue",
        f"{repository}#2",
        repository,
    )
    request = WorkflowStartRequest(
        run_id="run-selected-github",
        conversation_id="conversation-1",
        workflow_key="thread-1",
        entry_mode="RESOURCE_SELECTED",
        requested_mode="LOCAL_GPU",
        request_text="선택한 GitHub Issue의 현재 제목, 상태, 본문을 알려줘",
        selected_resource_ids=(selected.resource_id,),
        selected_resources=(selected,),
        run_budget=cast(dict[str, Any], build_default_run_budget()),
        correlation=WorkflowCorrelationContext("request-1", "command-1", "v1"),
    )

    candidate = identify_goal(
        llm_runtime=runtime,
        request=request,
        prompt_ref=_prompt_ref("request_understanding.identify_goal", "identify_goal"),
    )
    ambiguity = detect_ambiguity(
        llm_runtime=runtime,
        request=request,
        goal_candidate=candidate,
    )
    intent = finalize_intent(
        candidate,
        ambiguity,
        artifact_id="intent-1",
        user_request=request.request_text,
    )

    assert ambiguity["requires_confirmation"] is False
    assert all(item["field"] != "repository" for item in intent["constraints"])
    assert validated_repository_authority(
        intent,
        selected_resources=request.selected_resources,
    ) == repository


def test_identify_goal__workspace_effect_without_resource_hint__fails_contract() -> None:
    runtime = FakeStructuredInferencePort(
        outputs=[
            {
                "goal": "캘린더 일정 생성",
                "completion_conditions": ["일정이 생성된다"],
                "constraints": _goal_constraints(),
                "requested_effect_hints": ["CREATE"],
                "requested_resource_hints": [],
                "analysis_requirement": "NONE",
            }
        ]
    )

    with pytest.raises(ValueError, match="request goal candidate is invalid"):
        identify_goal(
            llm_runtime=runtime,
            request=_request("내 캘린더에 일정을 만들어줘"),
            prompt_ref=_prompt_ref("request_understanding.identify_goal", "identify_goal"),
        )


def test_identify_goal__answer_only__allows_empty_workspace_hints() -> None:
    runtime = FakeStructuredInferencePort(
        outputs=[
            {
                "goal": "간단한 답변",
                "completion_conditions": ["답을 표시한다"],
                "constraints": _goal_constraints(),
                "requested_effect_hints": [],
                "requested_resource_hints": [],
                "analysis_requirement": "NONE",
            }
        ]
    )

    candidate = identify_goal(
        llm_runtime=runtime,
        request=_request("2 더하기 2는?"),
        prompt_ref=_prompt_ref("request_understanding.identify_goal", "identify_goal"),
    )

    assert candidate["requested_effect_hints"] == []
    assert candidate["requested_resource_hints"] == []


def test_identify_goal__with_advice_keywords__preserves_model_semantics() -> None:
    runtime = FakeStructuredInferencePort(
        outputs=[
            {
                "goal": "프로젝트 회의 준비 원칙 제공",
                "completion_conditions": ["한 문장으로 원칙을 답한다"],
                "constraints": _goal_constraints(),
                "requested_effect_hints": ["READ"],
                "requested_resource_hints": ["GMAIL_THREAD", "TASK", "CALENDAR_EVENT"],
                "analysis_requirement": "REQUIRED",
            }
        ]
    )

    candidate = identify_goal(
        llm_runtime=runtime,
        request=_request("프로젝트 회의 준비 원칙을 한 문장으로 알려줘."),
        prompt_ref=_prompt_ref("request_understanding.identify_goal", "identify_goal"),
    )

    assert candidate["requested_effect_hints"] == ["READ"]
    assert candidate["requested_resource_hints"] == ["GMAIL_THREAD", "TASK", "CALENDAR_EVENT"]
    assert candidate["analysis_requirement"] == "REQUIRED"


def test_identify_goal__current_workspace_read__is_not_rewritten_as_advice() -> None:
    runtime = FakeStructuredInferencePort(
        outputs=[
            {
                "goal": "현재 Google Tasks 원칙 확인",
                "completion_conditions": ["현재 태스크를 읽어 답한다"],
                "constraints": _goal_constraints(),
                "requested_effect_hints": ["READ"],
                "requested_resource_hints": ["TASK"],
                "analysis_requirement": "NONE",
            }
        ]
    )

    candidate = identify_goal(
        llm_runtime=runtime,
        request=_request("내 Google Tasks의 현재 우선순위 원칙을 알려줘."),
        prompt_ref=_prompt_ref("request_understanding.identify_goal", "identify_goal"),
    )

    assert candidate["requested_effect_hints"] == ["READ"]
    assert candidate["requested_resource_hints"] == ["TASK"]


def test_identify_goal__validated_google_tasks_read__preserves_model_semantics() -> None:
    runtime = FakeStructuredInferencePort(
        outputs=[
            {
                "goal": "현재 할 일 목록 제공",
                "completion_conditions": ["할 일을 간단히 답한다"],
                "constraints": _goal_constraints(),
                "requested_effect_hints": ["READ"],
                "requested_resource_hints": ["TASK"],
                "analysis_requirement": "NONE",
            }
        ]
    )

    candidate = identify_goal(
        llm_runtime=runtime,
        request=_request("Google Tasks에 있는 현재 할 일을 목록으로 간단히 알려줘."),
        prompt_ref=_prompt_ref("request_understanding.identify_goal", "identify_goal"),
    )

    assert candidate["requested_effect_hints"] == ["READ"]
    assert candidate["requested_resource_hints"] == ["TASK"]
    output_schema = cast(OutputSchemaDefinition, runtime.calls[0]["output_schema"])
    assert "allOf" in output_schema.json_schema


def test_identify_goal__vague_mail_read__requires_original_search_semantics() -> None:
    runtime = FakeStructuredInferencePort(
        outputs=[
            {
                "goal": "회의 관련 메일을 분석해 일정 정리",
                "completion_conditions": ["회의 일정 근거를 정리한다"],
                "constraints": _goal_constraints(
                    business_concepts=["회의"], required_information=["일정", "후속 작업"],
                ),
                "requested_effect_hints": ["READ"],
                "requested_resource_hints": ["GMAIL_THREAD"],
                "analysis_requirement": "REQUIRED",
            }
        ]
    )

    candidate = identify_goal(
        llm_runtime=runtime,
        request=_request("회의 관련 메일이 있는데 그거 분석해서 일정 정리해줘."),
        prompt_ref=_prompt_ref("request_understanding.identify_goal", "identify_goal"),
    )

    assert candidate["constraints"][0] == {
        "kind": "USER_REQUIREMENT",
        "field": "business_concepts",
        "value": ["회의"],
    }
    output_schema = cast(OutputSchemaDefinition, runtime.calls[0]["output_schema"])
    constraint_schema = cast(
        dict[str, Any],
        cast(dict[str, Any], output_schema.json_schema["properties"])["constraints"],
    )
    assert constraint_schema["type"] == "object"
    assert "additional_constraints" in constraint_schema["required"]


def test_identify_goal__inference_omits_topic__preserves_only_verbatim_request() -> None:
    runtime = FakeStructuredInferencePort(
        outputs=[
            {
                "goal": "Find and analyze meeting-related emails",
                "completion_conditions": ["Summarize schedule information"],
                "constraints": _goal_constraints(),
                "requested_effect_hints": ["READ"],
                "requested_resource_hints": ["GMAIL_THREAD"],
                "analysis_requirement": "NONE",
            }
        ]
    )
    request_text = "회의 관련 메일이 있는데 그거 분석해서 일정 정리해줘."

    candidate = identify_goal(
        llm_runtime=runtime,
        request=_request(request_text),
        prompt_ref=_prompt_ref("request_understanding.identify_goal", "identify_goal"),
    )

    by_field = {item["field"]: item["value"] for item in candidate["constraints"]}
    assert "start" not in by_field
    assert "end" not in by_field
    assert by_field["original_search_request"] == [request_text]
    assert "search_terms" not in by_field
    assert "required_information" not in by_field
    assert candidate["analysis_requirement"] == "NONE"


def test_identify_goal__decision_word__does_not_override_analysis_semantics() -> None:
    runtime = FakeStructuredInferencePort(
        outputs=[
            {
                "goal": "KAN-93 관련 메일 찾기",
                "completion_conditions": ["관련 메일을 찾는다"],
                "constraints": _goal_constraints(search_terms=["KAN-93"]),
                "requested_effect_hints": ["READ"],
                "requested_resource_hints": ["GMAIL_THREAD"],
                "analysis_requirement": "NONE",
            }
        ]
    )

    candidate = identify_goal(
        llm_runtime=runtime,
        request=_request("KAN-93 관련 메일이 여러 개일 때 최신 결정이 무엇인지 알려줘."),
        prompt_ref=_prompt_ref("request_understanding.identify_goal", "identify_goal"),
    )

    assert candidate["analysis_requirement"] == "NONE"


def test_identify_goal__schedule_words__do_not_rewrite_model_resource_or_effect() -> None:
    runtime = FakeStructuredInferencePort(
        outputs=[
            {
                "goal": "회의 메일을 분석하고 캘린더 일정을 만든다",
                "completion_conditions": ["회의 일정을 생성한다"],
        "constraints": _goal_constraints(
            business_concepts=["회의"], required_information=["회의 일정"]
        ),
                "requested_effect_hints": ["READ", "CREATE"],
                "requested_resource_hints": ["GMAIL_THREAD", "CALENDAR_EVENT"],
                "resource_responsibilities": _resource_responsibilities(
                    source_type="GMAIL_THREAD",
                    required_information=["회의 일정"],
                    output_type="CALENDAR_EVENT",
                    output_effect="CREATE",
                ),
                "analysis_requirement": "NONE",
            }
        ]
    )

    candidate = identify_goal(
        llm_runtime=runtime,
        request=_request("회의 관련 메일이 있는데 그거 분석해서 일정 정리해줘."),
        prompt_ref=_prompt_ref("request_understanding.identify_goal", "identify_goal"),
    )

    assert candidate["requested_effect_hints"] == ["READ", "CREATE"]
    assert candidate["requested_resource_hints"] == ["GMAIL_THREAD", "CALENDAR_EVENT"]
    assert candidate["analysis_requirement"] == "NONE"


def test_identify_goal__validated_google_tasks_write__preserves_create() -> None:
    runtime = FakeStructuredInferencePort(
        outputs=[
            {
                "goal": "새 할 일 생성",
                "completion_conditions": ["할 일을 생성한다"],
                "constraints": _goal_constraints(),
                "requested_effect_hints": ["CREATE"],
                "requested_resource_hints": ["TASK"],
                "analysis_requirement": "NONE",
            }
        ]
    )

    result = identify_goal(
        llm_runtime=runtime,
        request=_request("Google Tasks 목록에 새 할 일을 만들어줘."),
        prompt_ref=_prompt_ref("request_understanding.identify_goal", "identify_goal"),
    )

    assert result["requested_effect_hints"] == ["CREATE"]
    assert result["requested_resource_hints"] == ["TASK"]


def test_identify_goal__mail_derived_task_registration__preserves_inferred_effects() -> None:
    effects = ["READ", "CREATE"]
    runtime = FakeStructuredInferencePort(outputs=[{
        "goal": "메일 후속 업무 등록", "completion_conditions": ["태스크 등록"],
        "constraints": _goal_constraints(
            search_terms=["회의"], required_information=["후속 업무"]
        ),
        "requested_effect_hints": effects,
        "requested_resource_hints": ["GMAIL_THREAD", "TASK"],
        "resource_responsibilities": _resource_responsibilities(
            source_type="GMAIL_THREAD",
            required_information=["후속 업무"],
            output_type="TASK",
            output_effect="CREATE",
        ),
        "analysis_requirement": "NONE",
    }])
    request = _request("회의 관련 메일을 찾아서 후속 업무를 내 기본 Google Tasks 목록에 등록해줘.")
    prompt_ref = _prompt_ref("request_understanding.identify_goal", "identify_goal")
    result = identify_goal(llm_runtime=runtime, request=request, prompt_ref=prompt_ref)
    assert result["requested_effect_hints"] == effects


@pytest.mark.parametrize("request_text,constraints", [
    ("Google Tasks에 등록하지 말고 회의 메일만 찾아줘.",
     _goal_constraints(search_terms=["회의"])),
    ("'Google Tasks에 등록해줘'라는 제목의 메일을 읽어줘.",
     _goal_constraints(subject=["Google Tasks에 등록해줘"])),
])
def test_identify_goal__forbidden_or_quoted_registration__does_not_require_create(
    request_text: str, constraints: object,
) -> None:
    runtime = FakeStructuredInferencePort(outputs=[{
        "goal": "메일 읽기", "completion_conditions": ["메일 확인"],
        "constraints": constraints,
        "requested_effect_hints": ["READ"], "requested_resource_hints": ["GMAIL_THREAD"],
        "analysis_requirement": "NONE",
    }])
    result = identify_goal(
        llm_runtime=runtime, request=_request(request_text),
        prompt_ref=_prompt_ref("request_understanding.identify_goal", "identify_goal"),
    )
    assert result["requested_effect_hints"] == ["READ"]


@pytest.mark.parametrize(
    ("request_text", "expected_dates"),
    [
        ("Google Tasks에 '2/8 Supervisor 승인 테스트' 태스크를 만들어줘.", []),
        ("Google Tasks에 '2/8 Supervisor 승인 테스트' 태스크를 2026-09-05까지 만들어줘.",
         ["2026-09-05"]),
    ],
)
def test_identify_goal__quoted_task_title__does_not_become_an_unstated_date(
    request_text: str,
    expected_dates: list[str],
) -> None:
    additional_constraints: list[dict[str, object]] = [
        {"kind": "DATE", "field": "date", "value": "2026-02-08"},
        {
            "kind": "RESOURCE",
            "field": "title",
            "value": "2/8 Supervisor 승인 테스트",
        },
    ]
    if expected_dates:
        additional_constraints.append(
            {"kind": "DATE", "field": "due", "value": "2026-09-05"}
        )
    runtime = FakeStructuredInferencePort(
        outputs=[
            {
                "goal": "새 할 일 생성",
                "completion_conditions": ["할 일을 생성한다"],
                "constraints": _goal_constraints(*additional_constraints),
                "requested_effect_hints": ["CREATE"],
                "requested_resource_hints": ["TASK"],
                "analysis_requirement": "NONE",
            }
        ]
    )

    candidate = identify_goal(
        llm_runtime=runtime,
        request=_request(request_text),
        prompt_ref=_prompt_ref("request_understanding.identify_goal", "identify_goal"),
    )

    assert [
        constraint["value"]
        for constraint in candidate["constraints"]
        if constraint["kind"] == "DATE"
    ] == expected_dates


def test_new_gmail_send__ambiguous_model_scope__is_not_silently_rewritten() -> None:
    runtime = FakeStructuredInferencePort(
        outputs=[
            {
                "goal": "새 메시지를 보내고 결과를 확인한다",
                "completion_conditions": ["전송된 메시지를 재조회한다"],
                "constraints": _goal_constraints(
                    recipient=["qhdrbdhkdwks2@gmail.com"],
                    subject=["[GWA E2E #197] SEND"],
                ),
                "requested_effect_hints": ["READ", "SEND"],
                "requested_resource_hints": ["GMAIL_MESSAGE"],
                "analysis_requirement": "NONE",
            }
        ]
    )

    candidate = identify_goal(
        llm_runtime=runtime,
        request=_request(
            'qhdrbdhkdwks2@gmail.com에게 제목 "[GWA E2E #197] SEND"로 보내고 '
            "전송 결과를 다시 조회해 확인해."
        ),
        prompt_ref=_prompt_ref("request_understanding.identify_goal", "identify_goal"),
    )

    assert candidate["requested_effect_hints"] == ["READ", "SEND"]
    assert candidate["requested_resource_hints"] == ["GMAIL_MESSAGE"]


def test_existing_gmail_thread_reply__thread_input_hint__is_not_collapsed() -> None:
    runtime = FakeStructuredInferencePort(
        outputs=[
            {
                "goal": "기존 메일 대화에 답장한다",
                "completion_conditions": ["같은 대화의 보낸 답장을 재조회한다"],
                "constraints": _goal_constraints(
                    recipient=["qhdrbdhkdwks2@gmail.com"],
                    subject=["[GWA E2E #197] SEND"],
                    required_information=["기존 대화 identity"],
                ),
                "requested_effect_hints": ["READ", "SEND"],
                "requested_resource_hints": ["GMAIL_THREAD", "GMAIL_MESSAGE"],
                "resource_responsibilities": _resource_responsibilities(
                    source_type="GMAIL_THREAD",
                    required_information=["기존 대화 identity"],
                    output_type="GMAIL_MESSAGE",
                    output_effect="SEND",
                ),
                "analysis_requirement": "NONE",
            }
        ]
    )

    candidate = identify_goal(
        llm_runtime=runtime,
        request=_request(
            '제목이 "[GWA E2E #197] SEND"인 기존 메일 대화를 찾아서 '
            "qhdrbdhkdwks2@gmail.com에게 답장하고 같은 대화에서 확인해."
        ),
        prompt_ref=_prompt_ref("request_understanding.identify_goal", "identify_goal"),
    )

    assert candidate["requested_effect_hints"] == ["READ", "SEND"]
    assert candidate["requested_resource_hints"] == ["GMAIL_THREAD", "GMAIL_MESSAGE"]


def test_source_search_write__without_read_effect__rejects_candidate() -> None:
    runtime = FakeStructuredInferencePort(
        outputs=[
            {
                "goal": "기존 자료를 찾아 메시지를 보낸다",
                "completion_conditions": ["관련 메시지를 보낸다"],
                "constraints": _goal_constraints(
                    search_terms=["Project Anchor"],
                    required_information=["일정"],
                ),
                "requested_effect_hints": ["SEND"],
                "requested_resource_hints": ["GMAIL_MESSAGE"],
                "analysis_requirement": "NONE",
            }
        ]
    )

    with pytest.raises(ValueError, match="request goal candidate is invalid"):
        identify_goal(
            llm_runtime=runtime,
            request=_request("기존 Project Anchor 자료를 찾아 관련 답장을 보내줘."),
            prompt_ref=_prompt_ref("request_understanding.identify_goal", "identify_goal"),
        )


def test_lexical_anchor_alone__standalone_write__does_not_force_source_read() -> None:
    runtime = FakeStructuredInferencePort(
        outputs=[
            {
                "goal": "새 메시지를 보낸다",
                "completion_conditions": ["메시지를 보낸다"],
                "constraints": _goal_constraints(search_terms=["Project Anchor"]),
                "requested_effect_hints": ["SEND"],
                "requested_resource_hints": ["GMAIL_MESSAGE"],
                "analysis_requirement": "NONE",
            }
        ]
    )

    candidate = identify_goal(
        llm_runtime=runtime,
        request=_request("Project Anchor 팀에게 새 메시지를 보내줘."),
        prompt_ref=_prompt_ref("request_understanding.identify_goal", "identify_goal"),
    )

    assert candidate["requested_effect_hints"] == ["SEND"]
    assert candidate["requested_resource_hints"] == ["GMAIL_MESSAGE"]


def test_existing_gmail_thread_reply__missing_output_hint__rejects_output() -> None:
    runtime = FakeStructuredInferencePort(
        outputs=[
            {
                "goal": "기존 메일 대화에 답장한다",
                "completion_conditions": ["같은 대화의 보낸 답장을 재조회한다"],
                "constraints": _goal_constraints(
                    recipient=["qhdrbdhkdwks2@gmail.com"],
                    subject=["[GWA E2E #197] SEND"],
                ),
                "requested_effect_hints": ["READ", "SEND"],
                "requested_resource_hints": ["GMAIL_THREAD"],
                "analysis_requirement": "NONE",
            }
        ]
    )

    with pytest.raises(ValueError, match="request goal candidate is invalid"):
        identify_goal(
            llm_runtime=runtime,
            request=_request(
                '제목이 "[GWA E2E #197] SEND"인 기존 메일 대화를 찾아서 '
                "qhdrbdhkdwks2@gmail.com에게 답장해."
            ),
            prompt_ref=_prompt_ref("request_understanding.identify_goal", "identify_goal"),
        )


def test_identify_goal__duplicate_effect_hints__rejects_output() -> None:
    runtime = FakeStructuredInferencePort(
        outputs=[
            {
                "goal": "기존 메일 대화에 답장한다",
                "completion_conditions": ["답장을 보낸다"],
                "constraints": _goal_constraints(
                    recipient=["qhdrbdhkdwks2@gmail.com"],
                    subject=["[GWA E2E #197] SEND"],
                ),
                "requested_effect_hints": ["READ", "SEND", "READ"],
                "requested_resource_hints": ["GMAIL_THREAD", "GMAIL_MESSAGE"],
                "analysis_requirement": "NONE",
            }
        ]
    )

    with pytest.raises(ValueError, match="request goal candidate is invalid"):
        identify_goal(
            llm_runtime=runtime,
            request=_request("기존 메일 대화를 찾아 답장해."),
            prompt_ref=_prompt_ref("request_understanding.identify_goal", "identify_goal"),
        )


@pytest.mark.parametrize(
    "effect,resources",
    [
        ("CREATE", ["GMAIL_THREAD"]),
        ("UPDATE", ["GMAIL_THREAD"]),
        ("SEND", ["GMAIL_THREAD"]),
        ("DELETE", ["GMAIL_THREAD"]),
    ],
)
def test_identify_goal__write_effect_without_compatible_resource__rejects_output(
    effect: str, resources: list[str]
) -> None:
    runtime = FakeStructuredInferencePort(
        outputs=[
            {
                "goal": "외부 업무를 수행한다",
                "completion_conditions": ["요청한 변경을 수행한다"],
                "constraints": _goal_constraints(),
                "requested_effect_hints": [effect],
                "requested_resource_hints": resources,
                "analysis_requirement": "NONE",
            }
        ]
    )

    with pytest.raises(ValueError, match="request goal candidate is invalid"):
        identify_goal(
            llm_runtime=runtime,
            request=_request("외부 업무를 수행해."),
            prompt_ref=_prompt_ref("request_understanding.identify_goal", "identify_goal"),
        )


def test_identify_goal__named_recipient_in_additional_constraints__rejects_output() -> None:
    runtime = FakeStructuredInferencePort(
        outputs=[
            {
                "goal": "기존 메일 대화에 답장한다",
                "completion_conditions": ["답장을 보낸다"],
                "constraints": _goal_constraints(
                    {
                        "kind": "USER_REQUIREMENT",
                        "field": "recipient",
                        "value": ["qhdrbdhkdwks2@gmail.com"],
                    },
                    sender=["qhdrbdhkdwks2@gmail.com"],
                ),
                "requested_effect_hints": ["READ", "SEND"],
                "requested_resource_hints": ["GMAIL_THREAD"],
                "analysis_requirement": "NONE",
            }
        ]
    )

    with pytest.raises(ValueError, match="request goal candidate is invalid"):
        identify_goal(
            llm_runtime=runtime,
            request=_request("qhdrbdhkdwks2@gmail.com에게 답장해."),
            prompt_ref=_prompt_ref("request_understanding.identify_goal", "identify_goal"),
        )


def test_identify_goal__repository_constraint_without_github_target__rejects_output() -> None:
    runtime = FakeStructuredInferencePort(
        outputs=[
            {
                "goal": "선택한 할 일을 수정한다",
                "completion_conditions": ["할 일 제목과 메모를 수정한다"],
                "constraints": _goal_constraints(
                    {"kind": "RESOURCE", "field": "repository", "value": "GWA E2E"}
                ),
                "requested_effect_hints": ["READ", "UPDATE"],
                "requested_resource_hints": ["TASK"],
                "analysis_requirement": "NONE",
            }
        ]
    )

    with pytest.raises(ValueError, match="request goal candidate is invalid"):
        identify_goal(
            llm_runtime=runtime,
            request=_request("선택한 실제 테스트 할 일을 수정해줘."),
            prompt_ref=_prompt_ref("request_understanding.identify_goal", "identify_goal"),
        )


def test_identify_goal__llm_supplied_constraint_provenance__rejects_output() -> None:
    runtime = FakeStructuredInferencePort(
        outputs=[
            {
                "goal": "List issues",
                "completion_conditions": ["Issues are listed"],
                "constraints": _goal_constraints({
                    "kind": "RESOURCE",
                    "field": "repository",
                    "value": "openai/codex",
                    "provenance": {
                        "source": "USER_REQUEST",
                        "start_offset": 0,
                        "end_offset": 12,
                    },
                }),
                "requested_effect_hints": ["READ"],
                "requested_resource_hints": ["GITHUB_ISSUE"],
                "analysis_requirement": "REQUIRED",
            }
        ]
    )

    with pytest.raises(ValueError, match="request goal candidate is invalid"):
        identify_goal(
            llm_runtime=runtime,
            request=_request("List issues in openai/codex"),
            prompt_ref=_prompt_ref("request_understanding.identify_goal", "identify_goal"),
        )


def _request(text: str) -> WorkflowStartRequest:
    return WorkflowStartRequest(
        run_id="run-1",
        conversation_id="conversation-1",
        workflow_key="thread-1",
        entry_mode="AGENT_SEARCH",
        requested_mode="AUTO",
        request_text=text,
        selected_resource_ids=(),
        run_budget=cast(dict[str, Any], build_default_run_budget()),
        correlation=WorkflowCorrelationContext(
            request_id="request-1", command_id="command-1", api_contract_version="v1"
        ),
    )


def _prompt_ref(prompt_id: str, node_name: str) -> PromptReference:
    return PromptReference(
        prompt_bundle_version="test",
        prompt_id=prompt_id,
        prompt_version="1",
        content_hash="hash",
        agent_role="request_understanding",
        subgraph_name="request_understanding",
        node_name=node_name,
        node_state="INITIAL",
        purpose=node_name,
        input_schema_version="v1",
        output_schema_version="v1",
    )
