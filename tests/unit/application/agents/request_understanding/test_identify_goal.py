from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from typing import Any, cast

import pytest
from tests.support.fakes.llm import FakeStructuredInferencePort

from google_work_agent.application.agents.request_understanding import (
    identify_effect_prohibitions as effect_prohibitions,
)
from google_work_agent.application.agents.request_understanding import (
    identify_output_responsibilities as output_responsibilities,
)
from google_work_agent.application.agents.request_understanding import (
    identify_source_dependencies as source_dependencies,
)
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
    identify_goal as _identify_goal,
)
from google_work_agent.application.agents.request_understanding.identify_goal import (
    identify_goal_with_budget as _identify_goal_with_budget,
)
from google_work_agent.application.tool_registry.load_signed_tool_registry import (
    load_signed_tool_registry,
)
from google_work_agent.application.use_cases.run.guard_run_budget import build_default_run_budget
from google_work_agent.ports.llm.output_schema_validation import validate_output_schema
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
    "person": "PERSON",
    "sender": "PERSON",
    "recipient": "PERSON",
    "subject": "RESOURCE",
    "period": "DATE",
    "coverage_requirement": "SCOPE",
}
_SOURCE_DEPENDENCY_CANDIDATES = source_dependencies.build_source_dependency_candidates(
    load_signed_tool_registry()
)
_OUTPUT_RESPONSIBILITY_CANDIDATES = output_responsibilities.build_output_responsibility_candidates(
    load_signed_tool_registry()
)
_EFFECT_PROHIBITION_CANDIDATES = effect_prohibitions.build_effect_prohibition_candidates(
    _OUTPUT_RESPONSIBILITY_CANDIDATES
)


def identify_goal(**kwargs: Any) -> Any:
    kwargs.setdefault("source_dependency_candidates", _SOURCE_DEPENDENCY_CANDIDATES)
    kwargs.setdefault("output_responsibility_candidates", _OUTPUT_RESPONSIBILITY_CANDIDATES)
    kwargs.setdefault(
        "effect_prohibition_prompt_ref",
        _prompt_ref(
            "request_understanding.identify_effect_prohibitions",
            "identify_effect_prohibitions",
        ),
    )
    kwargs.setdefault(
        "source_dependency_prompt_ref",
        _prompt_ref(
            "request_understanding.identify_source_dependencies",
            "identify_source_dependencies",
        ),
    )
    kwargs.setdefault(
        "output_responsibility_prompt_ref",
        _prompt_ref(
            "request_understanding.identify_output_responsibilities",
            "identify_output_responsibilities",
        ),
    )
    kwargs.setdefault(
        "source_status_prompt_ref",
        _prompt_ref(
            "request_understanding.identify_source_status",
            "identify_source_status",
        ),
    )
    return _identify_goal(**kwargs)


def identify_goal_with_budget(**kwargs: Any) -> Any:
    kwargs.setdefault("source_dependency_candidates", _SOURCE_DEPENDENCY_CANDIDATES)
    kwargs.setdefault("output_responsibility_candidates", _OUTPUT_RESPONSIBILITY_CANDIDATES)
    kwargs.setdefault(
        "effect_prohibition_prompt_ref",
        _prompt_ref(
            "request_understanding.identify_effect_prohibitions",
            "identify_effect_prohibitions",
        ),
    )
    kwargs.setdefault(
        "source_dependency_prompt_ref",
        _prompt_ref(
            "request_understanding.identify_source_dependencies",
            "identify_source_dependencies",
        ),
    )
    kwargs.setdefault(
        "output_responsibility_prompt_ref",
        _prompt_ref(
            "request_understanding.identify_output_responsibilities",
            "identify_output_responsibilities",
        ),
    )
    kwargs.setdefault(
        "source_status_prompt_ref",
        _prompt_ref(
            "request_understanding.identify_source_status",
            "identify_source_status",
        ),
    )
    return _identify_goal_with_budget(**kwargs)


def detect_ambiguity(**kwargs: Any) -> AmbiguityV1:
    ambiguity, _ = _detect_ambiguity_with_budget(
        **kwargs,
        retry_budget=build_default_run_budget(),
    )
    return ambiguity


def _goal_constraints(*additional: dict[str, object], **values: object) -> dict[str, object]:
    return {
        **dict.fromkeys(_GMAIL_CONSTRAINT_KINDS, []),
        "coverage_requirement": "NOT_COLLECTION",
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
    source_type: str | None = None,
    required_information: list[str] | None = None,
    output_type: str | None = None,
    output_effect: str | None = None,
) -> dict[str, list[dict[str, object]]]:
    if (source_type is None) != (required_information is None):
        raise ValueError("source_type and required_information must be supplied together")
    if (output_type is None) != (output_effect is None):
        raise ValueError("output_type and output_effect must be supplied together")
    return {
        "source_reads": (
            [{"resource_type": source_type, "required_information": required_information}]
            if source_type is not None and required_information is not None
            else []
        ),
        "outputs": (
            [{"resource_type": output_type, "effect": output_effect}]
            if output_type is not None and output_effect is not None
            else []
        ),
    }


@pytest.mark.parametrize(
    "kind,valid",
    [("RESOURCE", False), ("SCOPE", False), ("USER_REQUIREMENT", True)],
)
def test_normalized_search_semantic_fields__wrong_kind__fails_output_contract(
    kind: str, valid: bool
) -> None:
    candidate = {
        "goal": "자료 확인",
        "completion_conditions": ["최종 기준 확인"],
        "constraints": [{"kind": kind, "field": "business_concepts", "value": ["출하"]}],
        "requested_effect_hints": ["READ"],
        "requested_resource_hints": ["GMAIL_THREAD", "TASK"],
        "resource_responsibilities": {
            "source_reads": [
                {"resource_type": "GMAIL_THREAD", "required_information": []},
                {"resource_type": "TASK", "required_information": []},
            ],
            "outputs": [],
        },
        "analysis_requirement": "NONE",
    }
    if valid:
        goal_schema.validate_normalized_request_goal_candidate(candidate)
    else:
        with pytest.raises(ValueError, match="normalized request goal candidate is invalid"):
            goal_schema.validate_normalized_request_goal_candidate(candidate)


def test_gmail_goal__unknown_named_slot__rejects_before_routing() -> None:
    runtime = FakeStructuredInferencePort(
        outputs=[
            {
                "goal": "프로젝트 자료 확인",
                "completion_conditions": ["확인"],
                "constraints": {"target_project": ["ORB-17"]},
                "resource_responsibilities": _resource_responsibilities(
                    source_type="GMAIL_THREAD", required_information=[]
                ),
                "analysis_requirement": "NONE",
            }
        ]
    )
    with pytest.raises(ValueError, match="request goal candidate is invalid"):
        identify_goal(
            llm_runtime=runtime,
            request=_request("ORB-17 메일 찾아줘"),
            prompt_ref=_prompt_ref("request_understanding.identify_goal", "identify_goal"),
        )


def test_gmail_goal__keyed_slots__preserves_distinct_semantic_roles() -> None:
    runtime = FakeStructuredInferencePort(
        outputs=[
            {
                "goal": "근거 조회",
                "completion_conditions": ["사실 확인"],
                "constraints": _goal_constraints(
                    search_terms=["ORB-17"],
                    person=["박과장"],
                    sender=["sender@example.test"],
                    recipient=["recipient@example.test"],
                    business_concepts=["검수"],
                    period=["이번 주"],
                ),
                "resource_responsibilities": _resource_responsibilities(
                    source_type="GMAIL_THREAD", required_information=["최종 정정된 시각"]
                ),
                "analysis_requirement": "NONE",
            }
        ]
    )
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


def test_gmail_goal__finalized_literal__binds_normalized_ru_output_to_request() -> None:
    request = _request("Nimbus 출시 날짜를 메일에서 확인해줘")
    runtime = FakeStructuredInferencePort(
        outputs=[
            {
                "goal": "Nimbus 출시 날짜 확인",
                "completion_conditions": ["출시 날짜를 답한다"],
                "constraints": _goal_constraints(
                    search_terms=["Nimbus"],
                    business_concepts=["출시"],
                ),
                "resource_responsibilities": _resource_responsibilities(
                    source_type="GMAIL_THREAD", required_information=["출시 날짜"]
                ),
                "analysis_requirement": "NONE",
            }
        ]
    )

    candidate = identify_goal(
        llm_runtime=runtime,
        request=request,
        prompt_ref=_prompt_ref("request_understanding.identify_goal", "identify_goal"),
    )
    intent = finalize_intent(
        candidate,
        {"requires_confirmation": False, "reason_codes": [], "missing_fields": []},
        artifact_id="intent-source-literal",
        user_request=request.request_text,
    )

    nimbus = next(item for item in intent["constraints"] if item["value"] == "Nimbus")
    assert nimbus["provenance"] == {
        "source": "USER_REQUEST",
        "start_offset": request.request_text.index("Nimbus"),
        "end_offset": request.request_text.index("Nimbus") + len("Nimbus"),
    }
    business_concept = next(
        item for item in intent["constraints"] if item["field"] == "business_concepts"
    )
    assert "provenance" not in business_concept


def test_source_status__explicit_sent_scope__retains_resource_and_source_provenance() -> None:
    request = _request("보낸 편지함에서 Quartz 찾아줘")
    runtime = FakeStructuredInferencePort(
        outputs=[
            {
                "goal": "보낸 메일에서 Quartz 자료 조회",
                "completion_conditions": ["일치하는 보낸 메일을 보여준다"],
                "constraints": _goal_constraints(search_terms=["Quartz"]),
                "analysis_requirement": "NONE",
            },
            _resource_responsibilities(source_type="GMAIL_MESSAGE", required_information=[]),
            {"statuses": [_source_status("SENT", "GMAIL_MESSAGE", "보낸 편지함")]},
        ]
    )

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


@pytest.mark.parametrize(
    ("request_text", "resource_type", "status_value", "source_text"),
    [
        ("완료된 할 일을 찾아줘", "TASK", "COMPLETED", "완료된"),
        ("닫힌 GitHub 이슈를 찾아줘", "GITHUB_ISSUE", "CLOSED", "닫힌"),
    ],
)
def test_source_status__fixed_source_role__accepts_only_its_explicit_scope(
    request_text: str,
    resource_type: str,
    status_value: str,
    source_text: str,
) -> None:
    runtime = FakeStructuredInferencePort(
        outputs=[
            {
                "goal": "상태가 명시된 기존 자료 조회",
                "completion_conditions": ["일치하는 자료를 보여준다"],
                "constraints": _goal_constraints(),
                "analysis_requirement": "NONE",
            },
            _resource_responsibilities(source_type=resource_type, required_information=[]),
            {
                "statuses": [
                    _source_status(status_value, resource_type, source_text),
                ]
            },
        ],
        validate_schema=True,
    )

    candidate = identify_goal(
        llm_runtime=runtime,
        request=_request(request_text),
        prompt_ref=_prompt_ref("request_understanding.identify_goal", "identify_goal"),
    )

    assert next(item for item in candidate["constraints"] if item["field"] == "status") == {
        "kind": "SCOPE",
        "field": "status",
        "value": status_value,
        "source_resource_type": resource_type,
        "provenance": {
            "source": "USER_REQUEST",
            "start_offset": request_text.index(source_text),
            "end_offset": request_text.index(source_text) + len(source_text),
            "source_text": source_text,
        },
    }


def _source_dependency_decisions(
    *,
    source_types: dict[str, list[str]] | None = None,
) -> dict[str, list[dict[str, object]]]:
    source_types = source_types or {}
    decisions: list[dict[str, object]] = []
    for candidate in _SOURCE_DEPENDENCY_CANDIDATES:
        resource_type = candidate["resource_type"]
        information = source_types.get(resource_type)
        if information is not None:
            decisions.append(
                {
                    "resource_type": resource_type,
                    "dependency": "SOURCE_REQUIRED",
                    "required_information": information,
                }
            )
        else:
            decisions.append({"resource_type": resource_type, "dependency": "SOURCE_NOT_REQUIRED"})
    return {"source_dependencies": decisions}


def _output_responsibility_decisions(
    *,
    output_types: dict[str, str] | None = None,
) -> dict[str, list[dict[str, object]]]:
    output_types = output_types or {}
    return {
        "output_responsibilities": [
            {
                "resource_type": candidate["resource_type"],
                "effect": output_types[candidate["resource_type"]],
            }
            for candidate in _OUTPUT_RESPONSIBILITY_CANDIDATES
            if candidate["resource_type"] in output_types
        ]
    }


def _effect_prohibition_decisions(*forbidden: str) -> dict[str, object]:
    return {
        "effect_prohibitions": [
            {
                "effect": candidate["effect"],
                "prohibition": (
                    "FORBIDDEN" if candidate["effect"] in forbidden else "NOT_FORBIDDEN"
                ),
            }
            for candidate in _EFFECT_PROHIBITION_CANDIDATES
        ]
    }


def test_source_status__task_update_output__does_not_become_completed_source_scope() -> None:
    runtime = FakeStructuredInferencePort(
        outputs=[
            {
                "goal": "선택한 할 일 완료 처리",
                "completion_conditions": ["할 일을 완료 상태로 변경한다"],
                "constraints": _goal_constraints(),
                "analysis_requirement": "NONE",
            },
            _resource_responsibilities(
                source_type="TASK",
                required_information=["기존 할 일 identity"],
                output_type="TASK",
                output_effect="UPDATE",
            ),
            {"statuses": []},
        ],
        validate_schema=True,
    )

    candidate = identify_goal(
        llm_runtime=runtime,
        request=_request("이 Task를 완료해줘"),
        prompt_ref=_prompt_ref("request_understanding.identify_goal", "identify_goal"),
    )

    assert candidate["resource_responsibilities"] == {
        "source_reads": [
            {"resource_type": "TASK", "required_information": ["기존 할 일 identity"]}
        ],
        "outputs": [{"resource_type": "TASK", "effect": "UPDATE"}],
    }
    assert not any(item["field"] == "status" for item in candidate["constraints"])


def test_source_status__without_current_run_source_binding__uses_bounded_revision() -> None:
    runtime = FakeStructuredInferencePort(
        outputs=[
            {
                "goal": "기존 메일 대화에 답장",
                "completion_conditions": ["같은 대화에 답장을 보낸다"],
                "constraints": _goal_constraints(search_terms=["Quartz"]),
                "analysis_requirement": "NONE",
            },
            _resource_responsibilities(
                source_type="GMAIL_THREAD",
                required_information=["납품 일정", "답장 대상 대화 identity"],
                output_type="GMAIL_MESSAGE",
                output_effect="SEND",
            ),
            {"statuses": [_source_status("SENT", "GMAIL_THREAD", "보낸 편지함")]},
            {
                "goal": "기존 메일 대화에 답장",
                "completion_conditions": ["같은 대화에 답장을 보낸다"],
                "constraints": _goal_constraints(search_terms=["Quartz"]),
                "analysis_requirement": "NONE",
            },
            _resource_responsibilities(
                source_type="GMAIL_THREAD",
                required_information=["납품 일정", "답장 대상 대화 identity"],
                output_type="GMAIL_MESSAGE",
                output_effect="SEND",
            ),
            {"statuses": []},
        ]
    )

    candidate, budget = identify_goal_with_budget(
        llm_runtime=runtime,
        request=_request("Quartz 납품 일정 확인했다고 답장 보내줘."),
        prompt_ref=_prompt_ref("request_understanding.identify_goal", "identify_goal"),
        retry_budget=build_default_run_budget(),
    )

    assert not any(item["field"] == "status" for item in candidate["constraints"])
    revision_input = cast(dict[str, object], runtime.calls[5]["prompt_input"])
    failure_record = cast(dict[str, object], revision_input["failure_record"])
    assert failure_record["failure_reason_code"] == ("REQUEST_STATUS_PROVENANCE_MISMATCH")
    assert len(budget["semantic_revisions_used_by_failure"]) == 1


def test_source_status_revision__with_unaffected_owner_outputs__preserves_them() -> None:
    runtime = FakeStructuredInferencePort(
        outputs=[
            {
                "goal": "기존 메일 대화에 답장",
                "completion_conditions": ["같은 대화에 답장을 보낸다"],
                "constraints": _goal_constraints(search_terms=["Quartz"]),
                "analysis_requirement": "NONE",
            },
            _resource_responsibilities(
                source_type="GMAIL_THREAD",
                required_information=["납품 일정", "답장 대상 대화 identity"],
                output_type="GMAIL_MESSAGE",
                output_effect="SEND",
            ),
            {"statuses": [_source_status("SENT", "GMAIL_THREAD", "보낸 편지함")]},
            {"statuses": []},
        ]
    )

    candidate, budget = identify_goal_with_budget(
        llm_runtime=runtime,
        request=_request("Quartz 납품 일정 확인했다고 답장 보내줘."),
        prompt_ref=_prompt_ref("request_understanding.identify_goal", "identify_goal"),
        retry_budget=build_default_run_budget(),
    )

    prompt_ids = [call["prompt_ref"].prompt_id for call in runtime.calls]
    assert prompt_ids == [
        "request_understanding.identify_goal",
        "request_understanding.identify_effect_prohibitions",
        "request_understanding.identify_source_dependencies",
        "request_understanding.identify_output_responsibilities",
        "request_understanding.identify_source_status",
        "request_understanding.identify_source_status",
    ]
    assert candidate["resource_responsibilities"] == {
        "source_reads": [
            {
                "resource_type": "GMAIL_THREAD",
                "required_information": ["납품 일정", "답장 대상 대화 identity"],
            }
        ],
        "outputs": [{"resource_type": "GMAIL_MESSAGE", "effect": "SEND"}],
    }
    assert len(budget["semantic_revisions_used_by_failure"]) == 1


def test_target_confirmation_resume__preserves_nonempty_source_without_reassessment() -> None:
    request_text = "확정된 일정의 시작과 끝을 알려줘"
    prior_candidate = {
        "goal": "대상 일정의 시작과 끝 확인",
        "completion_conditions": ["대상 일정의 시작과 끝을 답한다"],
        "constraints": [
            {
                "kind": "USER_REQUIREMENT",
                "field": "business_concepts",
                "value": ["일정 시간 확인"],
            },
            {
                "kind": "SCOPE",
                "field": "status",
                "value": "CONFIRMED",
                "source_resource_type": "CALENDAR_EVENT",
                "provenance": {
                    "source": "USER_REQUEST",
                    "start_offset": 0,
                    "end_offset": 2,
                    "source_text": "확정",
                },
            },
        ],
        "requested_effect_hints": ["READ"],
        "requested_resource_hints": ["CALENDAR_EVENT"],
        "resource_responsibilities": {
            "source_reads": [
                {
                    "resource_type": "CALENDAR_EVENT",
                    "required_information": ["event_identity", "start", "end"],
                }
            ],
            "outputs": [],
        },
        "analysis_requirement": "NONE",
    }
    runtime = FakeStructuredInferencePort(outputs=[])

    candidate, _ = identify_goal_with_budget(
        llm_runtime=runtime,
        request=_request(request_text),
        prompt_ref=_prompt_ref("request_understanding.identify_goal", "identify_goal"),
        retry_budget=build_default_run_budget(),
        confirmation_response={
            "schema_version": 1,
            "response_kind": "FREE_TEXT",
            "selected_option": None,
            "free_text": "프로젝트 검토 회의",
        },
        prior_goal_candidate=cast(Any, prior_candidate),
        prior_ambiguity_candidate={
            "requires_confirmation": True,
            "reason_codes": ["MISSING_TARGET_RESOURCE"],
            "missing_fields": ["target_resource"],
        },
    )

    assert candidate["goal"] == prior_candidate["goal"]
    assert candidate["completion_conditions"] == prior_candidate["completion_conditions"]
    assert candidate["resource_responsibilities"] == prior_candidate["resource_responsibilities"]
    assert candidate["constraints"] == [
        *prior_candidate["constraints"],
        {
            "kind": "USER_REQUIREMENT",
            "field": "search_terms",
            "value": "프로젝트 검토 회의",
            "provenance": {
                "source": "CONFIRMATION_RESPONSE",
                "start_offset": 0,
                "end_offset": 10,
                "source_text": "프로젝트 검토 회의",
            },
        },
    ]
    assert runtime.calls == []


def test_target_confirmation_resume__reassesses_only_empty_source_responsibility() -> None:
    request_text = "확정된 그 일정의 시작과 끝으로 초안을 만들어줘"
    status = {
        "kind": "SCOPE",
        "field": "status",
        "value": "CONFIRMED",
        "source_resource_type": "CALENDAR_EVENT",
        "provenance": {
            "source": "USER_REQUEST",
            "start_offset": 0,
            "end_offset": 2,
            "source_text": "확정",
        },
    }
    prior_candidate = {
        "goal": "대상 일정의 시작과 끝으로 초안 생성",
        "completion_conditions": ["대상 일정의 시간을 포함한 초안을 만든다"],
        "constraints": [
            {
                "kind": "USER_REQUIREMENT",
                "field": "business_concepts",
                "value": ["일정 시간 확인"],
            },
            status,
        ],
        "requested_effect_hints": ["CREATE"],
        "requested_resource_hints": ["GMAIL_DRAFT"],
        "resource_responsibilities": {
            "source_reads": [],
            "outputs": [{"resource_type": "GMAIL_DRAFT", "effect": "CREATE"}],
        },
        "analysis_requirement": "NONE",
    }
    runtime = FakeStructuredInferencePort(
        outputs=[
            _source_dependency_decisions(
                source_types={
                    "CALENDAR_EVENT": ["event_identity", "start", "end"],
                }
            )
        ]
    )

    candidate, _ = identify_goal_with_budget(
        llm_runtime=runtime,
        request=_request(request_text),
        prompt_ref=_prompt_ref("request_understanding.identify_goal", "identify_goal"),
        retry_budget=build_default_run_budget(),
        confirmation_response={
            "schema_version": 1,
            "response_kind": "FREE_TEXT",
            "selected_option": None,
            "free_text": "프로젝트 검토 회의",
        },
        prior_goal_candidate=cast(Any, prior_candidate),
        prior_ambiguity_candidate={
            "requires_confirmation": True,
            "reason_codes": ["MISSING_TARGET_RESOURCE"],
            "missing_fields": ["target_resource"],
        },
    )

    assert candidate["goal"] == prior_candidate["goal"]
    assert candidate["completion_conditions"] == prior_candidate["completion_conditions"]
    assert candidate["resource_responsibilities"] == {
        "source_reads": [
            {
                "resource_type": "CALENDAR_EVENT",
                "required_information": ["event_identity", "start", "end"],
            }
        ],
        "outputs": prior_candidate["resource_responsibilities"]["outputs"],
    }
    assert candidate["requested_effect_hints"] == ["READ", "CREATE"]
    assert candidate["requested_resource_hints"] == ["CALENDAR_EVENT", "GMAIL_DRAFT"]
    assert status in candidate["constraints"]
    assert [call["prompt_ref"].prompt_id for call in runtime.calls] == [
        "request_understanding.identify_source_dependencies"
    ]
    source_goal = cast(dict[str, object], runtime.calls[0]["prompt_input"])["goal_candidate"]
    assert isinstance(source_goal, dict)
    assert any(
        item["field"] == "search_terms"
        and item["value"] == "프로젝트 검토 회의"
        and item["provenance"]["source"] == "CONFIRMATION_RESPONSE"
        for item in source_goal["constraints"]
    )


def test_confirmation_resume__keeps_selected_resource_identity_authority() -> None:
    selected = SelectedResourceRef(
        "ref-event-42",
        "google_workspace",
        "calendar_event",
        "event-42",
    )
    request = replace(
        _request("선택한 일정의 시작과 끝을 알려줘"),
        entry_mode="RESOURCE_SELECTED",
        selected_resource_ids=(selected.resource_id,),
        selected_resources=(selected,),
    )
    prior_candidate = {
        "goal": "선택한 일정의 시작과 끝 확인",
        "completion_conditions": ["선택한 일정의 시작과 끝을 답한다"],
        "constraints": [
            {
                "kind": "RESOURCE",
                "field": "selected_resource_id",
                "value": [selected.resource_id],
            }
        ],
        "requested_effect_hints": ["READ"],
        "requested_resource_hints": ["CALENDAR_EVENT"],
        "resource_responsibilities": {
            "source_reads": [
                {
                    "resource_type": "CALENDAR_EVENT",
                    "required_information": ["event_identity", "start", "end"],
                }
            ],
            "outputs": [],
        },
        "analysis_requirement": "NONE",
    }
    runtime = FakeStructuredInferencePort(outputs=[])

    candidate, _ = identify_goal_with_budget(
        llm_runtime=runtime,
        request=request,
        prompt_ref=_prompt_ref("request_understanding.identify_goal", "identify_goal"),
        retry_budget=build_default_run_budget(),
        confirmation_response={
            "schema_version": 1,
            "response_kind": "FREE_TEXT",
            "selected_option": None,
            "free_text": "프로젝트 검토 회의",
        },
        prior_goal_candidate=cast(Any, prior_candidate),
        prior_ambiguity_candidate={
            "requires_confirmation": True,
            "reason_codes": ["MISSING_TARGET_RESOURCE"],
            "missing_fields": ["target_resource"],
        },
    )

    assert candidate["constraints"][0] == prior_candidate["constraints"][0]
    assert all(item["field"] != "search_terms" for item in candidate["constraints"])
    assert runtime.calls == []


def test_thread_reply__without_explicit_source_status__does_not_create_status() -> None:
    runtime = FakeStructuredInferencePort(
        outputs=[
            {
                "goal": "기존 Quartz 메일 대화에 답장",
                "completion_conditions": ["같은 대화에 답장을 보낸다"],
                "constraints": _goal_constraints(
                    search_terms=["Quartz"],
                ),
                "resource_responsibilities": _resource_responsibilities(
                    source_type="GMAIL_THREAD",
                    required_information=["납품 일정", "답장 대상 대화 identity"],
                    output_type="GMAIL_MESSAGE",
                    output_effect="SEND",
                ),
                "analysis_requirement": "NONE",
            }
        ]
    )

    candidate = identify_goal(
        llm_runtime=runtime,
        request=_request("Quartz 납품 일정 확인했다고 답장 보내줘."),
        prompt_ref=_prompt_ref("request_understanding.identify_goal", "identify_goal"),
    )

    assert not any(item["field"] == "status" for item in candidate["constraints"])


def test_cross_resource_read_write__without_typed_responsibility__rejects_before_routing() -> None:
    runtime = FakeStructuredInferencePort(
        outputs=[
            {
                "goal": "기존 자료를 근거로 메시지 전송",
                "completion_conditions": ["메시지를 보낸다"],
                "constraints": _goal_constraints(),
                "analysis_requirement": "NONE",
            },
            {},
        ]
    )

    with pytest.raises(ValueError, match="source dependency candidate"):
        identify_goal(
            llm_runtime=runtime,
            request=_request("기존 자료에서 일정을 확인해 관련 메시지를 보내줘."),
            prompt_ref=_prompt_ref("request_understanding.identify_goal", "identify_goal"),
        )


def test_cross_resource_read_write__single_responsibility__derives_flat_fields() -> None:
    runtime = FakeStructuredInferencePort(
        outputs=[
            {
                "goal": "기존 자료를 근거로 메시지 전송",
                "completion_conditions": ["메시지를 보낸다"],
                "constraints": _goal_constraints(),
                "resource_responsibilities": _resource_responsibilities(
                    source_type="GMAIL_THREAD",
                    required_information=["기존 자료의 일정"],
                    output_type="GMAIL_MESSAGE",
                    output_effect="SEND",
                ),
                "analysis_requirement": "NONE",
            }
        ]
    )

    candidate = identify_goal(
        llm_runtime=runtime,
        request=_request("기존 자료에서 일정을 확인해 관련 메시지를 보내줘."),
        prompt_ref=_prompt_ref("request_understanding.identify_goal", "identify_goal"),
    )

    assert candidate["requested_effect_hints"] == ["READ", "SEND"]
    assert candidate["requested_resource_hints"] == ["GMAIL_THREAD", "GMAIL_MESSAGE"]
    assert next(
        item["value"]
        for item in candidate["constraints"]
        if item["field"] == "required_information"
    ) == ["기존 자료의 일정"]


def test_same_resource_read_update__single_responsibility__preserves_both_roles() -> None:
    runtime = FakeStructuredInferencePort(
        outputs=[
            {
                "goal": "기존 태스크 수정",
                "completion_conditions": ["기존 태스크를 수정한다"],
                "constraints": _goal_constraints(),
                "resource_responsibilities": _resource_responsibilities(
                    source_type="TASK",
                    required_information=["기존 태스크 identity"],
                    output_type="TASK",
                    output_effect="UPDATE",
                ),
                "analysis_requirement": "NONE",
            }
        ]
    )

    candidate = identify_goal(
        llm_runtime=runtime,
        request=_request("기존 태스크를 찾아 제목을 수정해줘."),
        prompt_ref=_prompt_ref("request_understanding.identify_goal", "identify_goal"),
    )

    assert candidate["requested_effect_hints"] == ["READ", "UPDATE"]
    assert candidate["requested_resource_hints"] == ["TASK"]
    assert len(runtime.calls) == 5


def test_split_source_information__normalizes_once__before_finalize() -> None:
    exact_sentence = "8월 21일 입고 준비를 확인 중입니다."
    raw_candidate = {
        "goal": f"기존 초안 끝에 '{exact_sentence}'만 추가",
        "completion_conditions": [
            "기존 수신자와 제목과 본문을 보존한다",
            f"'{exact_sentence}'를 한 번 추가한다",
            "메일을 보내지 않는다",
        ],
        "constraints": _goal_constraints(
            search_terms=["Quartz 납품 회신 검토"],
        ),
        "resource_responsibilities": {
            "source_reads": [
                {
                    "resource_type": "GMAIL_DRAFT",
                    "required_information": ["기존 본문 확인"],
                },
                {
                    "resource_type": "GMAIL_DRAFT",
                    "required_information": ["기존 수신자 확인"],
                },
            ],
            "outputs": [{"resource_type": "GMAIL_DRAFT", "effect": "UPDATE"}],
        },
        "analysis_requirement": "NONE",
    }
    original_candidate = deepcopy(raw_candidate)
    runtime = FakeStructuredInferencePort(outputs=[raw_candidate])
    request = _request(
        "임시보관함의 'Quartz 납품 회신 검토' 초안 끝에 "
        f"'{exact_sentence}'만 추가해줘. 보내지는 마."
    )

    candidate = identify_goal(
        llm_runtime=runtime,
        request=request,
        prompt_ref=_prompt_ref("request_understanding.identify_goal", "identify_goal"),
    )
    intent = finalize_intent(
        candidate,
        {"requires_confirmation": False, "reason_codes": [], "missing_fields": []},
        artifact_id="intent-draft-update",
        user_request=request.request_text,
    )

    assert raw_candidate == original_candidate
    assert len(runtime.calls) == 5
    assert candidate["resource_responsibilities"] == {
        "source_reads": [
            {
                "resource_type": "GMAIL_DRAFT",
                "required_information": ["기존 본문 확인", "기존 수신자 확인"],
            }
        ],
        "outputs": [{"resource_type": "GMAIL_DRAFT", "effect": "UPDATE"}],
    }
    assert intent["resource_responsibilities"] == candidate["resource_responsibilities"]
    assert intent["requested_effect_hints"] == ["READ", "UPDATE"]
    assert intent["requested_resource_hints"] == ["GMAIL_DRAFT"]
    assert exact_sentence in intent["goal"]
    assert "메일을 보내지 않는다" in intent["completion_conditions"]


def test_source_information_normalization__when_repeated__is_lossless_and_idempotent() -> None:
    raw_candidate = {
        "goal": "메일 자료 확인",
        "completion_conditions": ["필요한 자료를 확인한다"],
        "constraints": _goal_constraints(),
        "resource_responsibilities": {
            "source_reads": [
                {
                    "resource_type": "GMAIL_DRAFT",
                    "required_information": ["기존 본문", "기존 수신자"],
                },
                {
                    "resource_type": "GMAIL_THREAD",
                    "required_information": [],
                },
                {
                    "resource_type": "GMAIL_DRAFT",
                    "required_information": ["기존 수신자", "기존 제목"],
                },
            ],
            "outputs": [{"resource_type": "GMAIL_DRAFT", "effect": "UPDATE"}],
        },
        "analysis_requirement": "NONE",
    }
    original_candidate = deepcopy(raw_candidate)

    goal_candidate = {
        key: value for key, value in raw_candidate.items() if key != "resource_responsibilities"
    }
    normalized = goal_schema.validate_request_goal_candidate(
        goal_candidate,
        resource_responsibilities=raw_candidate["resource_responsibilities"],
    )
    normalized_again = goal_schema.validate_request_goal_candidate(
        goal_candidate,
        resource_responsibilities=deepcopy(normalized["resource_responsibilities"]),
    )

    assert raw_candidate == original_candidate
    assert normalized["resource_responsibilities"] == {
        "source_reads": [
            {
                "resource_type": "GMAIL_DRAFT",
                "required_information": ["기존 본문", "기존 수신자", "기존 제목"],
            },
            {"resource_type": "GMAIL_THREAD", "required_information": []},
        ],
        "outputs": [{"resource_type": "GMAIL_DRAFT", "effect": "UPDATE"}],
    }
    assert normalized_again["resource_responsibilities"] == normalized["resource_responsibilities"]
    required_information = next(
        constraint["value"]
        for constraint in normalized["constraints"]
        if constraint["field"] == "required_information"
    )
    assert required_information == ["기존 본문", "기존 수신자", "기존 제목"]


def test_cross_source_draft__with_atomic_inference__keeps_separate_responsibility() -> None:
    runtime = FakeStructuredInferencePort(
        outputs=[
            {
                "goal": "기존 업무 자료를 바탕으로 메일 초안을 저장한다",
                "completion_conditions": ["메일 초안 Preview를 준비한다", "메일을 보내지 않는다"],
                "constraints": _goal_constraints(
                    search_terms=["Atlas"],
                    recipient=["person@example.test"],
                ),
                "analysis_requirement": "NONE",
            },
            {
                "source_reads": [
                    {"resource_type": "TASK", "required_information": ["준비 상황"]},
                    {
                        "resource_type": "CALENDAR_EVENT",
                        "required_information": ["인쇄소 일정"],
                    },
                ],
                "outputs": [{"resource_type": "GMAIL_DRAFT", "effect": "CREATE"}],
            },
        ],
        validate_schema=True,
    )

    candidate = identify_goal(
        llm_runtime=runtime,
        request=_request(
            "Atlas 할 일과 인쇄소 일정 보고 person@example.test에 준비 상황 메일 초안을 저장해줘."
        ),
        prompt_ref=_prompt_ref("request_understanding.identify_goal", "identify_goal"),
    )

    assert [call["prompt_ref"].prompt_id for call in runtime.calls] == [
        "request_understanding.identify_goal",
        "request_understanding.identify_effect_prohibitions",
        "request_understanding.identify_source_dependencies",
        "request_understanding.identify_output_responsibilities",
        "request_understanding.identify_source_status",
    ]
    assert [call["output_schema"].schema_version for call in runtime.calls] == [
        "request-goal-candidate-v16",
        "request-effect-prohibition-decision-v1",
        "request-source-dependency-decision-v2",
        "request-output-responsibility-decision-v2",
        "request-source-status-v2",
    ]
    assert runtime.calls[2]["prompt_input"]["goal_candidate"] == {
        "goal": (
            "Atlas 할 일과 인쇄소 일정 보고 person@example.test에 준비 상황 메일 초안을 저장해줘."
        ),
        "completion_conditions": [],
        "constraints": _goal_constraints(
            search_terms=["Atlas"],
            recipient=["person@example.test"],
        ),
        "analysis_requirement": "NONE",
    }
    assert runtime.calls[2]["prompt_input"]["source_candidates"] == list(
        _SOURCE_DEPENDENCY_CANDIDATES
    )
    assert runtime.calls[3]["prompt_input"]["output_candidates"] == list(
        _OUTPUT_RESPONSIBILITY_CANDIDATES
    )
    assert candidate["resource_responsibilities"] == {
        "source_reads": [
            {"resource_type": "TASK", "required_information": ["준비 상황"]},
            {
                "resource_type": "CALENDAR_EVENT",
                "required_information": ["인쇄소 일정"],
            },
        ],
        "outputs": [{"resource_type": "GMAIL_DRAFT", "effect": "CREATE"}],
    }
    assert candidate["requested_effect_hints"] == ["READ", "CREATE"]
    assert candidate["requested_resource_hints"] == [
        "TASK",
        "CALENDAR_EVENT",
        "GMAIL_DRAFT",
    ]
    assert runtime.calls[4]["prompt_input"]["source_reads"] == [
        {"resource_type": "TASK", "required_information": ["준비 상황"]},
        {
            "resource_type": "CALENDAR_EVENT",
            "required_information": ["인쇄소 일정"],
        },
    ]
    assert runtime.calls[4]["prompt_input"]["outputs"] == [
        {"resource_type": "GMAIL_DRAFT", "effect": "CREATE"}
    ]
    assert runtime.calls[4]["prompt_input"]["allowed_status_values"] == [
        {
            "resource_type": "TASK",
            "values": ["COMPLETED", "INCOMPLETE"],
        },
        {
            "resource_type": "CALENDAR_EVENT",
            "values": ["CANCELLED", "CONFIRMED", "TENTATIVE"],
        },
    ]
    assert not any(item["field"] == "status" for item in candidate["constraints"])


def test_explicit_send_prohibition__rejects_role_conflict__then_revises_once() -> None:
    goal = {
        "goal": "기존 업무 자료를 바탕으로 메일 초안을 저장한다",
        "completion_conditions": ["메일 초안 Preview를 준비한다", "메일을 보내지 않는다"],
        "constraints": _goal_constraints(
            search_terms=["Atlas"],
            recipient=["person@example.test"],
        ),
        "analysis_requirement": "NONE",
    }
    source_decisions = _source_dependency_decisions(
        source_types={
            "TASK": ["준비 상황"],
            "CALENDAR_EVENT": ["인쇄소 일정"],
        },
    )
    invalid_outputs = _output_responsibility_decisions(
        output_types={"GMAIL_DRAFT": "CREATE", "GMAIL_MESSAGE": "SEND"},
    )
    corrected_outputs = _output_responsibility_decisions(
        output_types={"GMAIL_DRAFT": "CREATE"},
    )
    runtime = FakeStructuredInferencePort(
        outputs=[
            goal,
            _effect_prohibition_decisions("SEND"),
            source_decisions,
            invalid_outputs,
            corrected_outputs,
        ]
    )

    candidate, budget = identify_goal_with_budget(
        llm_runtime=runtime,
        request=_request(
            "Atlas 할 일과 인쇄소 일정 보고 person@example.test에 "
            "준비 상황 메일을 Draft로 저장해줘. 보내지는 마."
        ),
        prompt_ref=_prompt_ref("request_understanding.identify_goal", "identify_goal"),
        retry_budget=build_default_run_budget(),
    )

    assert [call["prompt_ref"].prompt_id for call in runtime.calls] == [
        "request_understanding.identify_goal",
        "request_understanding.identify_effect_prohibitions",
        "request_understanding.identify_source_dependencies",
        "request_understanding.identify_output_responsibilities",
        "request_understanding.identify_output_responsibilities",
        "request_understanding.identify_source_status",
    ]
    revision_input = runtime.calls[4]["prompt_input"]
    assert revision_input["candidate_output"] == invalid_outputs
    failure_record = cast(dict[str, object], revision_input["failure_record"])
    assert failure_record["failure_reason_code"] == ("REQUEST_PROHIBITED_OUTPUT_EFFECT_SELECTED")
    assert candidate["resource_responsibilities"] == {
        "source_reads": [
            {"resource_type": "TASK", "required_information": ["준비 상황"]},
            {
                "resource_type": "CALENDAR_EVENT",
                "required_information": ["인쇄소 일정"],
            },
        ],
        "outputs": [{"resource_type": "GMAIL_DRAFT", "effect": "CREATE"}],
    }
    assert len(budget["semantic_revisions_used_by_failure"]) == 1


def test_source_status_revision__with_source_information__preserves_responsibilities() -> None:
    invalid_candidate = {
        "goal": "기존 Quartz 초안 수정",
        "completion_conditions": ["초안을 수정한다"],
        "constraints": _goal_constraints(
            search_terms=["Quartz"],
            status=[_source_status("DRAFT", "GMAIL_DRAFT", "원문에 없는 임시보관함")],
        ),
        "resource_responsibilities": _resource_responsibilities(
            source_type="GMAIL_DRAFT",
            required_information=["기존 초안"],
            output_type="GMAIL_DRAFT",
            output_effect="UPDATE",
        ),
        "analysis_requirement": "NONE",
    }
    runtime = FakeStructuredInferencePort(outputs=[invalid_candidate, {"statuses": []}])

    candidate, _budget = identify_goal_with_budget(
        llm_runtime=runtime,
        request=_request("Quartz 초안의 기존 값을 보존해서 수정해줘."),
        prompt_ref=_prompt_ref("request_understanding.identify_goal", "identify_goal"),
        retry_budget=build_default_run_budget(),
    )

    assert len(runtime.calls) == 6
    assert candidate["resource_responsibilities"]["source_reads"] == [
        {
            "resource_type": "GMAIL_DRAFT",
            "required_information": ["기존 초안"],
        }
    ]


def test_standalone_send__source_scope__does_not_create_status_or_read() -> None:
    runtime = FakeStructuredInferencePort(
        outputs=[
            {
                "goal": "새 메일 전송",
                "completion_conditions": ["새 메시지를 한 번 보낸다"],
                "constraints": _goal_constraints(
                    recipient=["person@example.test"],
                    subject=["안내"],
                ),
                "resource_responsibilities": _resource_responsibilities(
                    output_type="GMAIL_MESSAGE", output_effect="SEND"
                ),
                "analysis_requirement": "NONE",
            }
        ]
    )

    candidate = identify_goal(
        llm_runtime=runtime,
        request=_request(
            "person@example.test에게 제목은 “안내”, 본문은 “확인했습니다.”로 새 메일 보내줘."
        ),
        prompt_ref=_prompt_ref("request_understanding.identify_goal", "identify_goal"),
    )

    assert candidate["requested_effect_hints"] == ["SEND"]
    assert not any(item["field"] == "status" for item in candidate["constraints"])


def test_gmail_goal__invented_exact_subject__is_not_promoted_to_anchor() -> None:
    runtime = FakeStructuredInferencePort(
        outputs=[
            {
                "goal": "근거 조회",
                "completion_conditions": ["확인"],
                "constraints": _goal_constraints(subject=["ORB-17 검수 일정"]),
                "resource_responsibilities": _resource_responsibilities(
                    source_type="GMAIL_THREAD", required_information=[]
                ),
                "analysis_requirement": "NONE",
            }
        ]
    )
    result = identify_goal(
        llm_runtime=runtime,
        request=_request("ORB-17 검수 관련 메일 찾아줘"),
        prompt_ref=_prompt_ref("request_understanding.identify_goal", "identify_goal"),
    )
    assert not any(item["field"] == "subject" for item in result["constraints"])


@pytest.mark.parametrize(
    "value,valid", [("]", False), ("[]", False), ("東京", True), ("[검증]", True)]
)
def test_gmail_goal__empty_array_text__cannot_become_a_person(value: str, valid: bool) -> None:
    runtime = FakeStructuredInferencePort(
        outputs=[
            {
                "goal": "근거 조회",
                "completion_conditions": ["확인"],
                "constraints": _goal_constraints(person=[value]),
                "resource_responsibilities": _resource_responsibilities(
                    source_type="GMAIL_THREAD", required_information=[]
                ),
                "analysis_requirement": "NONE",
            }
        ]
    )
    request = _request(f"{value}의 메일 찾아줘")
    prompt_ref = _prompt_ref("request_understanding.identify_goal", "identify_goal")
    if valid:
        result = identify_goal(llm_runtime=runtime, request=request, prompt_ref=prompt_ref)
        assert any(
            item["field"] == "person" and item["value"] == [value] for item in result["constraints"]
        )
    else:
        with pytest.raises(ValueError, match="request goal candidate is invalid"):
            identify_goal(llm_runtime=runtime, request=request, prompt_ref=prompt_ref)


def test_request_goal_schema__additional_field__is_closed_and_has_no_kind_choice() -> None:
    constraints = cast(
        dict[str, Any],
        cast(dict[str, Any], goal_schema.IDENTIFY_GOAL_OUTPUT_SCHEMA.json_schema["properties"])[
            "constraints"
        ],
    )
    additional = cast(dict[str, Any], constraints["properties"])["additional_constraints"]
    item = cast(dict[str, Any], additional)["items"]
    properties = cast(dict[str, Any], item)["properties"]

    assert set(properties) == {"field", "value"}
    assert cast(dict[str, Any], properties["field"])["enum"] == [
        "date",
        "description",
        "due",
        "notes",
        "repository",
        "scheduled_date",
        "title",
    ]


@pytest.mark.parametrize("field", sorted(goal_schema.REQUEST_GOAL_SLOT_KINDS))
def test_request_goal_schema__reserved_additional_field__rejects_output(field: str) -> None:
    value = "ALL_ITEMS" if field == "coverage_requirement" else "explicit value"
    candidate = {
        "goal": "요청한 결과를 준비한다",
        "completion_conditions": ["요청한 결과가 준비된다"],
        "constraints": _goal_constraints(
            {"field": field, "value": value}
        ),
        "analysis_requirement": "NONE",
    }

    errors = validate_output_schema(
        candidate, goal_schema.IDENTIFY_GOAL_OUTPUT_SCHEMA.json_schema
    )

    assert any("must be one of" in error for error in errors)


def test_request_goal_schema__atlas_reserved_status__rejects_at_output_schema() -> None:
    candidate = {
        "goal": "기존 자료를 바탕으로 초안을 준비한다",
        "completion_conditions": ["초안을 준비하고 보내지 않는다"],
        "constraints": _goal_constraints(
            {"field": "title", "value": "draft"},
            {"field": "status", "value": "not sent"},
        ),
        "analysis_requirement": "NONE",
    }

    errors = validate_output_schema(
        candidate, goal_schema.IDENTIFY_GOAL_OUTPUT_SCHEMA.json_schema
    )

    assert any(
        "$.constraints.additional_constraints[1].field must be one of" in error
        for error in errors
    )
    assert not any(
        "$.constraints.additional_constraints[0].field" in error for error in errors
    )


def test_request_goal_schema__non_reserved_additional_field__remains_valid() -> None:
    candidate = {
        "goal": "요청한 결과를 준비한다",
        "completion_conditions": ["요청한 결과가 준비된다"],
        "constraints": _goal_constraints(
            {"field": "title", "value": "draft"},
            search_terms=["Atlas"],
            recipient=["person@example.test"],
        ),
        "analysis_requirement": "NONE",
    }

    assert not validate_output_schema(
        candidate, goal_schema.IDENTIFY_GOAL_OUTPUT_SCHEMA.json_schema
    )

    normalized = goal_schema.validate_request_goal_candidate(
        candidate,
        resource_responsibilities=_resource_responsibilities(
            output_type="TASK", output_effect="CREATE"
        ),
    )
    assert {"kind": "RESOURCE", "field": "title", "value": "draft"} in normalized[
        "constraints"
    ]


def test_request_goal_validator__unknown_additional_field__remains_defense_in_depth() -> None:
    candidate = {
        "goal": "요청한 결과를 준비한다",
        "completion_conditions": ["요청한 결과가 준비된다"],
        "constraints": _goal_constraints(
            {"field": "status", "value": "not sent"}
        ),
        "analysis_requirement": "NONE",
    }
    permissive_json_schema = deepcopy(goal_schema.IDENTIFY_GOAL_OUTPUT_SCHEMA.json_schema)
    constraint_schema = cast(
        dict[str, Any], cast(dict[str, Any], permissive_json_schema["properties"])["constraints"]
    )
    additional_schema = cast(
        dict[str, Any],
        cast(dict[str, Any], constraint_schema["properties"])["additional_constraints"],
    )
    item_schema = cast(dict[str, Any], additional_schema["items"])
    field_schema = cast(
        dict[str, Any], cast(dict[str, Any], item_schema["properties"])["field"]
    )
    field_schema.pop("enum")
    permissive_schema = OutputSchemaDefinition(
        schema_version="request-goal-candidate-permissive-test",
        json_schema=permissive_json_schema,
    )

    with pytest.raises(ValueError, match="unsupported additional constraint field"):
        goal_schema.validate_request_goal_candidate(
            candidate,
            resource_responsibilities=_resource_responsibilities(),
            schema=permissive_schema,
        )


def test_request_goal_schema__with_exhaustive_collection__preserves_model_scope() -> None:
    candidate = {
        "goal": "관련 제목 목록을 요청 범위 끝까지 반환한다",
        "completion_conditions": ["요청 범위의 제목을 빠짐없이 반환한다"],
        "constraints": _goal_constraints(
            search_terms=["Project Anchor"],
            coverage_requirement="ALL_ITEMS",
        ),
        "analysis_requirement": "NONE",
    }

    normalized = goal_schema.validate_request_goal_candidate(
        candidate,
        resource_responsibilities=_resource_responsibilities(
            source_type="GMAIL_THREAD",
            required_information=["관련 제목 목록"],
        ),
    )

    assert {
        "kind": "SCOPE",
        "field": "coverage_requirement",
        "value": "EXHAUSTIVE",
    } in normalized["constraints"]


def test_request_goal_schema__with_non_typed_collection_scope__rejects_candidate() -> None:
    candidate = {
        "goal": "관련 제목 목록을 반환한다",
        "completion_conditions": ["관련 제목을 반환한다"],
        "constraints": _goal_constraints(coverage_requirement="ALL_RESULTS"),
        "analysis_requirement": "NONE",
    }

    with pytest.raises(ValueError, match="request goal candidate is invalid"):
        goal_schema.validate_request_goal_candidate(
            candidate,
            resource_responsibilities=_resource_responsibilities(
                source_type="GMAIL_THREAD",
                required_information=["관련 제목 목록"],
            ),
        )


def test_request_goal_schema__limited_collection__does_not_enable_exhaustive() -> None:
    candidate = {
        "goal": "관련 제목 일부를 반환한다",
        "completion_conditions": ["제한된 제목을 반환한다"],
        "constraints": _goal_constraints(
            search_terms=["Project Anchor"],
            coverage_requirement="LIMITED_ITEMS",
        ),
        "analysis_requirement": "NONE",
    }

    normalized = goal_schema.validate_request_goal_candidate(
        candidate,
        resource_responsibilities=_resource_responsibilities(
            source_type="GMAIL_THREAD",
            required_information=["제한된 관련 제목 목록"],
        ),
    )

    assert all(
        constraint["field"] != "coverage_requirement"
        for constraint in normalized["constraints"]
    )


@pytest.mark.parametrize(
    "effect,resource_type",
    [
        ("CREATE", "TASK"),
        ("UPDATE", "GMAIL_DRAFT"),
        ("SEND", "GMAIL_MESSAGE"),
        ("DELETE", "CALENDAR_EVENT"),
    ],
)
def test_request_goal_schema__accepts_supported_output_pairs__before_application(
    effect: str, resource_type: str
) -> None:
    candidate = _output_responsibility_decisions(
        output_types={resource_type: effect},
    )

    assert (
        validate_output_schema(
            candidate,
            output_responsibilities.build_output_responsibility_output_schema(
                _OUTPUT_RESPONSIBILITY_CANDIDATES
            ).json_schema,
        )
        == []
    )


def test_request_goal_schema__rejects_unsupported_output_pair__before_application() -> None:
    candidate = _output_responsibility_decisions(
        output_types={"GMAIL_MESSAGE": "CREATE"},
    )

    errors = validate_output_schema(
        candidate,
        output_responsibilities.build_output_responsibility_output_schema(
            _OUTPUT_RESPONSIBILITY_CANDIDATES
        ).json_schema,
    )

    assert errors


def test_request_goal_validator__with_empty_responsibility_text__rejects_candidate() -> None:
    candidate = {
        "goal": "메일을 확인해 태스크 생성",
        "completion_conditions": ["태스크 Preview 준비"],
        "constraints": _goal_constraints(),
        "resource_responsibilities": _resource_responsibilities(
            source_type="GMAIL_THREAD",
            required_information=["[]"],
            output_type="TASK",
            output_effect="CREATE",
        ),
        "analysis_requirement": "NONE",
    }

    with pytest.raises(ValueError, match="has no semantic text"):
        goal_schema.validate_request_goal_candidate(
            {key: value for key, value in candidate.items() if key != "resource_responsibilities"},
            resource_responsibilities=candidate["resource_responsibilities"],
        )


def test_default_repository__stays_system_owned__without_user_constraint_or_confirmation() -> None:
    request = replace(
        _request("열린 이슈 보여줘"),
        default_github_repository=GitHubRepositoryDefaultV1("sample/project", 42, "github:1"),
    )
    runtime = FakeStructuredInferencePort(
        outputs=[
            {
                "goal": "열린 이슈 조회",
                "completion_conditions": ["조회 결과를 보여준다"],
                "constraints": _goal_constraints(
                    status=[_source_status("OPEN", "GITHUB_ISSUE", "열린")]
                ),
                "resource_responsibilities": _resource_responsibilities(
                    source_type="GITHUB_ISSUE", required_information=[]
                ),
                "analysis_requirement": "NONE",
            },
            {
                "missing_information_owner": "NONE",
                "missing_fields": [],
            },
        ]
    )
    candidate = identify_goal(
        llm_runtime=runtime,
        request=request,
        prompt_ref=_prompt_ref("request_understanding.identify_goal", "identify_goal"),
    )
    assert runtime.calls[0]["prompt_input"] == {
        "user_request": request.request_text,
        "selected_resource_refs": [],
        "run_reference_time": {
            "reference_time": "1970-01-01T09:00:00+09:00",
            "timezone": "Asia/Seoul",
        },
    }
    ambiguity = detect_ambiguity(
        llm_runtime=runtime,
        request=request,
        goal_candidate=candidate,
        prompt_ref=_prompt_ref("request_understanding.detect_ambiguity", "detect_ambiguity"),
    )
    assert ambiguity["requires_confirmation"] is False
    assert all(item["field"] != "repository" for item in candidate["constraints"])
    intent = finalize_intent(
        candidate,
        ambiguity,
        artifact_id="intent-1",
        user_request=request.request_text,
        repository_default=request.default_github_repository,
    )
    assert intent["repository_default"]["repository"] == "sample/project"
    assert all(item["field"] != "repository" for item in intent["constraints"])


def test_explicit_repository__omitted_by_inference__retains_current_run_authority() -> None:
    repository = "acme/search-save"
    request = _request(f"{repository} 저장소의 열린 이슈를 조회해줘")
    runtime = FakeStructuredInferencePort(
        outputs=[
            {
                "goal": "열린 이슈 조회",
                "completion_conditions": ["조회 결과를 보여준다"],
                "constraints": _goal_constraints(
                    status=[_source_status("OPEN", "GITHUB_ISSUE", "열린")]
                ),
                "resource_responsibilities": _resource_responsibilities(
                    source_type="GITHUB_ISSUE", required_information=[]
                ),
                "analysis_requirement": "NONE",
            },
            {
                "missing_information_owner": "NONE",
                "missing_fields": [],
            },
        ]
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
        prompt_ref=_prompt_ref("request_understanding.detect_ambiguity", "detect_ambiguity"),
    )
    intent = finalize_intent(
        candidate,
        ambiguity,
        artifact_id="intent-1",
        user_request=request.request_text,
    )

    repository_constraint = next(
        item for item in intent["constraints"] if item["field"] == "repository"
    )
    assert ambiguity["requires_confirmation"] is False
    assert repository_constraint["value"] == repository
    assert repository_constraint["provenance"]["source"] == "USER_REQUEST"


@pytest.mark.parametrize(
    "request_text, expected_resources",
    [
        (
            "Google Calendar에 'Gmail Google Tasks 검증' 일정을 만들어줘. "
            "설명은 '메일을 읽어줘'이고 참석자는 reviewer@gmail.com이야.",
            ["CALENDAR_EVENT"],
        ),
        (
            "reviewer@gmail.com의 메일을 찾아서 Google Calendar에 일정을 만들어줘.",
            ["GMAIL_THREAD", "CALENDAR_EVENT"],
        ),
    ],
)
def test_identify_goal__payload_literals_do_not__add_unrequested_resources(
    request_text: str,
    expected_resources: list[str],
) -> None:
    runtime = FakeStructuredInferencePort(
        outputs=[
            {
                "goal": "일정 생성",
                "completion_conditions": ["일정을 생성한다"],
                "constraints": _goal_constraints(
                    {"field": "title", "value": "검증"}
                ),
                "resource_responsibilities": {
                    "source_reads": [
                        {"resource_type": resource, "required_information": []}
                        for resource in expected_resources
                        if resource != "CALENDAR_EVENT"
                    ],
                    "outputs": [{"resource_type": "CALENDAR_EVENT", "effect": "CREATE"}],
                },
                "analysis_requirement": "NONE",
            }
        ]
    )
    candidate = identify_goal(
        llm_runtime=runtime,
        request=_request(request_text),
        prompt_ref=_prompt_ref("request_understanding.identify_goal", "identify_goal"),
    )
    assert candidate["requested_resource_hints"] == expected_resources
    assert candidate["requested_effect_hints"] == (
        ["READ", "CREATE"] if "GMAIL_THREAD" in expected_resources else ["CREATE"]
    )


def test_identify_goal__preserves_exact_quoted__description_spacing() -> None:
    runtime = FakeStructuredInferencePort(
        outputs=[
            {
                "goal": "일정 생성",
                "completion_conditions": ["일정을 생성한다"],
                "constraints": _goal_constraints(
                    {
                        "field": "description",
                        "value": "Task 와 Calendar 검증 결과를 확인합니다.",
                    }
                ),
                "resource_responsibilities": _resource_responsibilities(
                    output_type="CALENDAR_EVENT", output_effect="CREATE"
                ),
                "analysis_requirement": "NONE",
            }
        ]
    )
    result = identify_goal(
        llm_runtime=runtime,
        request=_request("일정을 만들어줘. 설명은 'Task와 Calendar 검증 결과를 확인합니다.'야."),
        prompt_ref=_prompt_ref("request_understanding.identify_goal", "identify_goal"),
    )
    assert result["constraints"][0]["value"] == "Task와 Calendar 검증 결과를 확인합니다."


def test_identify_goal__with_spaced_literal__restores_exact_semantic_fields() -> None:
    exact_sentence = "8월 21일 입고 준비를 확인 중입니다."
    spaced_sentence = "8 월 21 일 입고 준비를 확인 중입니다."
    runtime = FakeStructuredInferencePort(
        outputs=[
            {
                "goal": f"초안 끝에 '{spaced_sentence}'만 추가",
                "completion_conditions": [f"'{spaced_sentence}'가 한 번만 추가된다"],
                "constraints": _goal_constraints(
                    search_terms=["Quartz 납품 회신 검토"],
                ),
                "resource_responsibilities": _resource_responsibilities(
                    source_type="GMAIL_DRAFT",
                    required_information=[f"초안 끝에 '{spaced_sentence}'를 추가"],
                    output_type="GMAIL_DRAFT",
                    output_effect="UPDATE",
                ),
                "analysis_requirement": "NONE",
            }
        ]
    )

    result = identify_goal(
        llm_runtime=runtime,
        request=_request(
            "임시보관함의 “Quartz 납품 회신 검토” 초안 끝에 "
            f"“{exact_sentence}”만 추가해줘. 보내지는 마."
        ),
        prompt_ref=_prompt_ref("request_understanding.identify_goal", "identify_goal"),
    )

    assert exact_sentence in result["goal"]
    assert exact_sentence in result["completion_conditions"][0]
    required_information = next(
        item["value"] for item in result["constraints"] if item["field"] == "required_information"
    )
    assert exact_sentence in required_information[0]
    assert spaced_sentence not in str(result)
    assert not any(item["field"] == "status" for item in result["constraints"])
    assert result["resource_responsibilities"] == {
        "source_reads": [
            {
                "resource_type": "GMAIL_DRAFT",
                "required_information": [f"초안 끝에 '{exact_sentence}'를 추가"],
            }
        ],
        "outputs": [{"resource_type": "GMAIL_DRAFT", "effect": "UPDATE"}],
    }


def test_identify_goal__canonical_call__uses_bounded_current_run_prompt() -> None:
    runtime = FakeStructuredInferencePort(
        outputs=[
            {
                "goal": "업무 메일 찾기",
                "completion_conditions": ["관련 메일을 찾는다"],
                "constraints": _goal_constraints(),
                "resource_responsibilities": _resource_responsibilities(
                    source_type="GMAIL_THREAD", required_information=["관련 자료"]
                ),
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
        "run_reference_time": {
            "reference_time": "1970-01-01T09:00:00+09:00",
            "timezone": "Asia/Seoul",
        },
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
                "resource_responsibilities": _resource_responsibilities(),
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
        selected_resources=(
            SelectedResourceRef("ref-thread-42", "google_workspace", "gmail_thread", "thread-42"),
        ),
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


def test_normalized_goal__existing_resource_update_without_source__rejects_contract() -> None:
    candidate = {
        "goal": "기존 GitHub 이슈 닫기",
        "completion_conditions": ["지정한 이슈를 닫는다"],
        "constraints": [],
        "requested_effect_hints": ["UPDATE"],
        "requested_resource_hints": ["GITHUB_ISSUE"],
        "resource_responsibilities": _resource_responsibilities(
            output_type="GITHUB_ISSUE",
            output_effect="UPDATE",
        ),
        "analysis_requirement": "NONE",
    }

    with pytest.raises(
        goal_schema.RequestGoalSemanticValidationError,
        match="existing Resource UPDATE/DELETE requires a same-resource source read",
    ) as raised:
        goal_schema.validate_normalized_request_goal_candidate(candidate)

    assert raised.value.reason_code == "REQUEST_EXISTING_RESOURCE_SOURCE_REQUIRED"
    assert raised.value.affected_field_paths == (
        "$.resource_responsibilities.source_reads",
        "$.resource_responsibilities.outputs[0]",
    )


def test_existing_resource_update__with_missing_source__revises_source_owner() -> None:
    runtime = FakeStructuredInferencePort(
        outputs=[
            {
                "goal": "기존 GitHub 이슈 닫기",
                "completion_conditions": ["지정한 이슈를 닫는다"],
                "constraints": _goal_constraints(),
                "resource_responsibilities": _resource_responsibilities(
                    output_type="GITHUB_ISSUE",
                    output_effect="UPDATE",
                ),
                "analysis_requirement": "NONE",
            },
            _source_dependency_decisions(
                source_types={"GITHUB_ISSUE": ["기존 issue identity와 현재 상태"]}
            ),
        ]
    )

    candidate, budget = identify_goal_with_budget(
        llm_runtime=runtime,
        request=_request("기존 GitHub 이슈를 찾아 닫아줘."),
        prompt_ref=_prompt_ref("request_understanding.identify_goal", "identify_goal"),
        retry_budget=build_default_run_budget(),
    )

    assert candidate["resource_responsibilities"] == {
        "source_reads": [
            {
                "resource_type": "GITHUB_ISSUE",
                "required_information": ["기존 issue identity와 현재 상태"],
            }
        ],
        "outputs": [{"resource_type": "GITHUB_ISSUE", "effect": "UPDATE"}],
    }
    prompt_ids = [call["prompt_ref"].prompt_id for call in runtime.calls]
    assert prompt_ids.count("request_understanding.identify_source_dependencies") == 2
    assert prompt_ids.count("request_understanding.identify_output_responsibilities") == 1
    assert len(budget["semantic_revisions_used_by_failure"]) == 1


def test_source_status_revision__with_independent_source_need__preserves_it() -> None:
    runtime = FakeStructuredInferencePort(
        outputs=[
            {
                "goal": "새 메일 전송",
                "completion_conditions": ["새 메시지를 보낸다"],
                "constraints": _goal_constraints(
                    recipient=["person@example.test"],
                    subject=["안내"],
                    status=[_source_status("SENT", "GMAIL_THREAD", "보낸 편지함")],
                ),
                "resource_responsibilities": _resource_responsibilities(
                    source_type="GMAIL_THREAD",
                    required_information=["발명된 기존 대화 identity"],
                    output_type="GMAIL_MESSAGE",
                    output_effect="SEND",
                ),
                "analysis_requirement": "NONE",
            },
            {"statuses": []},
        ]
    )

    candidate, budget = identify_goal_with_budget(
        llm_runtime=runtime,
        request=_request('person@example.test에게 제목은 "안내"로 새 메일을 보내줘.'),
        prompt_ref=_prompt_ref("request_understanding.identify_goal", "identify_goal"),
        retry_budget=build_default_run_budget(),
    )

    assert candidate["requested_effect_hints"] == ["READ", "SEND"]
    assert candidate["requested_resource_hints"] == ["GMAIL_THREAD", "GMAIL_MESSAGE"]
    assert candidate["resource_responsibilities"]["source_reads"] == [
        {
            "resource_type": "GMAIL_THREAD",
            "required_information": ["발명된 기존 대화 identity"],
        }
    ]
    assert len(runtime.calls) == 6
    assert len(budget["semantic_revisions_used_by_failure"]) == 1


def test_semantic_revision__user_required_source__remains_after_output_correction() -> None:
    request = _request(
        "기존 Project Anchor 메일에서 납품 주소를 확인하고 "
        "그 내용을 바탕으로 person@example.test에게 답장해줘."
    )
    runtime = FakeStructuredInferencePort(
        outputs=[
            {
                "goal": "기존 메일을 확인해 답장",
                "completion_conditions": ["확인한 납품 주소를 반영해 답장한다"],
                "constraints": _goal_constraints(
                    search_terms=["Project Anchor"],
                    status=[_source_status("SENT", "GMAIL_THREAD", "보낸 편지함")],
                ),
                "resource_responsibilities": _resource_responsibilities(
                    source_type="GMAIL_THREAD",
                    required_information=["기존 메일의 납품 주소"],
                    output_type="GMAIL_MESSAGE",
                    output_effect="SEND",
                ),
                "analysis_requirement": "NONE",
            },
            {"statuses": []},
        ]
    )

    candidate, _ = identify_goal_with_budget(
        llm_runtime=runtime,
        request=request,
        prompt_ref=_prompt_ref("request_understanding.identify_goal", "identify_goal"),
        retry_budget=build_default_run_budget(),
    )

    assert candidate["requested_effect_hints"] == ["READ", "SEND"]
    assert candidate["requested_resource_hints"] == ["GMAIL_THREAD", "GMAIL_MESSAGE"]
    assert candidate["resource_responsibilities"]["source_reads"] == [
        {
            "resource_type": "GMAIL_THREAD",
            "required_information": ["기존 메일의 납품 주소"],
        }
    ]
    assert len(runtime.calls) == 6
    revision_input = runtime.calls[5]["prompt_input"]
    base_projection = cast(dict[str, object], revision_input["base_projection"])
    assert base_projection["user_request"] == request.request_text
    assert base_projection["source_reads"] == [
        {
            "resource_type": "GMAIL_THREAD",
            "required_information": ["기존 메일의 납품 주소"],
        }
    ]
    assert base_projection["outputs"] == [
        {"resource_type": "GMAIL_MESSAGE", "effect": "SEND"}
    ]


def test_semantic_revision__validated_selected_resource__remains_bound() -> None:
    selected = SelectedResourceRef("ref-thread-42", "google_workspace", "gmail_thread", "thread-42")
    request = replace(
        _request("선택한 메일을 읽고 요약해줘"),
        entry_mode="RESOURCE_SELECTED",
        selected_resource_ids=(selected.resource_id,),
        selected_resources=(selected,),
    )
    runtime = FakeStructuredInferencePort(
        outputs=[
            {
                "goal": "선택한 메일 요약",
                "completion_conditions": ["요약을 답한다"],
                "constraints": _goal_constraints(
                    status=[_source_status("SENT", "GMAIL_THREAD", "보낸 편지함")]
                ),
                "resource_responsibilities": _resource_responsibilities(
                    source_type="GMAIL_THREAD",
                    required_information=["선택한 메일 내용"],
                ),
                "analysis_requirement": "NONE",
            },
            {"statuses": []},
        ]
    )

    candidate, _ = identify_goal_with_budget(
        llm_runtime=runtime,
        request=request,
        prompt_ref=_prompt_ref("request_understanding.identify_goal", "identify_goal"),
        retry_budget=build_default_run_budget(),
    )

    assert candidate["requested_effect_hints"] == ["READ"]
    assert candidate["requested_resource_hints"] == ["GMAIL_THREAD"]
    assert candidate["resource_responsibilities"]["source_reads"] == [
        {
            "resource_type": "GMAIL_THREAD",
            "required_information": ["선택한 메일 내용"],
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
                    {"field": "repository", "value": repository}
                ),
                "resource_responsibilities": _resource_responsibilities(
                    source_type="GITHUB_ISSUE", required_information=[]
                ),
                "analysis_requirement": "NONE",
            },
            {
                "missing_information_owner": "NONE",
                "missing_fields": [],
            },
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
        prompt_ref=_prompt_ref("request_understanding.detect_ambiguity", "detect_ambiguity"),
    )
    intent = finalize_intent(
        candidate,
        ambiguity,
        artifact_id="intent-1",
        user_request=request.request_text,
    )

    assert ambiguity["requires_confirmation"] is False
    assert all(item["field"] != "repository" for item in intent["constraints"])
    assert (
        validated_repository_authority(
            intent,
            selected_resources=request.selected_resources,
        )
        == repository
    )


def test_identify_goal__workspace_effect_without_resource_hint__fails_contract() -> None:
    runtime = FakeStructuredInferencePort(
        outputs=[
            {
                "goal": "캘린더 일정 생성",
                "completion_conditions": ["일정이 생성된다"],
                "constraints": _goal_constraints(),
                "resource_responsibilities": {
                    "source_reads": [],
                    "outputs": [{"resource_type": "GMAIL_THREAD", "effect": "CREATE"}],
                },
                "analysis_requirement": "NONE",
            }
        ]
    )

    with pytest.raises(ValueError, match="output responsibility candidate"):
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
                "resource_responsibilities": _resource_responsibilities(),
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
                "resource_responsibilities": {
                    "source_reads": [
                        {"resource_type": resource, "required_information": []}
                        for resource in ("GMAIL_THREAD", "TASK", "CALENDAR_EVENT")
                    ],
                    "outputs": [],
                },
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
                "resource_responsibilities": _resource_responsibilities(
                    source_type="TASK", required_information=[]
                ),
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
                "resource_responsibilities": _resource_responsibilities(
                    source_type="TASK", required_information=[]
                ),
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
    assert "allOf" not in output_schema.json_schema


def test_identify_goal__vague_mail_read__requires_original_search_semantics() -> None:
    runtime = FakeStructuredInferencePort(
        outputs=[
            {
                "goal": "회의 관련 메일을 분석해 일정 정리",
                "completion_conditions": ["회의 일정 근거를 정리한다"],
                "constraints": _goal_constraints(
                    business_concepts=["회의"],
                ),
                "resource_responsibilities": _resource_responsibilities(
                    source_type="GMAIL_THREAD",
                    required_information=["일정", "후속 작업"],
                ),
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
                "resource_responsibilities": _resource_responsibilities(
                    source_type="GMAIL_THREAD", required_information=["message_history"]
                ),
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
    assert by_field["required_information"] == ["message_history"]
    assert candidate["analysis_requirement"] == "NONE"


def test_identify_goal__decision_word__does_not_override_analysis_semantics() -> None:
    runtime = FakeStructuredInferencePort(
        outputs=[
            {
                "goal": "KAN-93 관련 메일 찾기",
                "completion_conditions": ["관련 메일을 찾는다"],
                "constraints": _goal_constraints(search_terms=["KAN-93"]),
                "resource_responsibilities": _resource_responsibilities(
                    source_type="GMAIL_THREAD", required_information=[]
                ),
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
                "constraints": _goal_constraints(business_concepts=["회의"]),
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
                "resource_responsibilities": _resource_responsibilities(
                    output_type="TASK", output_effect="CREATE"
                ),
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
    runtime = FakeStructuredInferencePort(
        outputs=[
            {
                "goal": "메일 후속 업무 등록",
                "completion_conditions": ["태스크 등록"],
                "constraints": _goal_constraints(search_terms=["회의"]),
                "resource_responsibilities": _resource_responsibilities(
                    source_type="GMAIL_THREAD",
                    required_information=["후속 업무"],
                    output_type="TASK",
                    output_effect="CREATE",
                ),
                "analysis_requirement": "NONE",
            }
        ]
    )
    request = _request("회의 관련 메일을 찾아서 후속 업무를 내 기본 Google Tasks 목록에 등록해줘.")
    prompt_ref = _prompt_ref("request_understanding.identify_goal", "identify_goal")
    result = identify_goal(llm_runtime=runtime, request=request, prompt_ref=prompt_ref)
    assert result["requested_effect_hints"] == effects


@pytest.mark.parametrize(
    "request_text,constraints",
    [
        (
            "Google Tasks에 등록하지 말고 회의 메일만 찾아줘.",
            _goal_constraints(search_terms=["회의"]),
        ),
        (
            "'Google Tasks에 등록해줘'라는 제목의 메일을 읽어줘.",
            _goal_constraints(subject=["Google Tasks에 등록해줘"]),
        ),
    ],
)
def test_identify_goal__forbidden_or_quoted_registration__does_not_require_create(
    request_text: str,
    constraints: object,
) -> None:
    runtime = FakeStructuredInferencePort(
        outputs=[
            {
                "goal": "메일 읽기",
                "completion_conditions": ["메일 확인"],
                "constraints": constraints,
                "resource_responsibilities": _resource_responsibilities(
                    source_type="GMAIL_THREAD", required_information=[]
                ),
                "analysis_requirement": "NONE",
            }
        ]
    )
    result = identify_goal(
        llm_runtime=runtime,
        request=_request(request_text),
        prompt_ref=_prompt_ref("request_understanding.identify_goal", "identify_goal"),
    )
    assert result["requested_effect_hints"] == ["READ"]


@pytest.mark.parametrize(
    ("request_text", "expected_dates"),
    [
        ("Google Tasks에 '2/8 Supervisor 승인 테스트' 태스크를 만들어줘.", []),
        (
            "Google Tasks에 '2/8 Supervisor 승인 테스트' 태스크를 2026-09-05까지 만들어줘.",
            ["2026-09-05"],
        ),
    ],
)
def test_identify_goal__quoted_task_title__does_not_become_an_unstated_date(
    request_text: str,
    expected_dates: list[str],
) -> None:
    additional_constraints: list[dict[str, object]] = [
        {"field": "date", "value": "2026-02-08"},
        {
            "field": "title",
            "value": "2/8 Supervisor 승인 테스트",
        },
    ]
    if expected_dates:
        additional_constraints.append({"field": "due", "value": "2026-09-05"})
    runtime = FakeStructuredInferencePort(
        outputs=[
            {
                "goal": "새 할 일 생성",
                "completion_conditions": ["할 일을 생성한다"],
                "constraints": _goal_constraints(*additional_constraints),
                "resource_responsibilities": _resource_responsibilities(
                    output_type="TASK", output_effect="CREATE"
                ),
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


def test_identify_goal__structured_task_date__preserves_explicit_field_role() -> None:
    runtime = FakeStructuredInferencePort(
        outputs=[
            {
                "goal": "새 할 일 생성",
                "completion_conditions": ["할 일을 생성한다"],
                "constraints": _goal_constraints(
                    {"field": "title", "value": "구조화 입력"},
                    {"field": "scheduled_date", "value": "2026-09-11"},
                ),
                "resource_responsibilities": _resource_responsibilities(
                    output_type="TASK", output_effect="CREATE"
                ),
                "analysis_requirement": "NONE",
            }
        ]
    )

    candidate = identify_goal(
        llm_runtime=runtime,
        request=_request(
            'Google Tasks에 {"title": "구조화 입력", '
            '"scheduled_date": "2026-09-11"}로 만들어줘.'
        ),
        prompt_ref=_prompt_ref("request_understanding.identify_goal", "identify_goal"),
    )

    assert [
        constraint["value"]
        for constraint in candidate["constraints"]
        if constraint["field"] == "scheduled_date"
    ] == ["2026-09-11"]


def test_identify_goal__with_unlisted_relative_date__preserves_date_outside_title() -> None:
    runtime = FakeStructuredInferencePort(
        outputs=[
            {
                "goal": "분기 정리 할 일 생성",
                "completion_conditions": ["사흘 뒤 수행할 할 일을 생성한다"],
                "constraints": _goal_constraints(
                    {"field": "title", "value": "분기 정리"},
                    period=["사흘 뒤"],
                ),
                "resource_responsibilities": _resource_responsibilities(
                    output_type="TASK", output_effect="CREATE"
                ),
                "analysis_requirement": "NONE",
            }
        ]
    )

    candidate = identify_goal(
        llm_runtime=runtime,
        request=_request('"분기 정리" 할 일을 사흘 뒤에 하도록 등록해 줘.'),
        prompt_ref=_prompt_ref("request_understanding.identify_goal", "identify_goal"),
    )

    assert [
        constraint["value"]
        for constraint in candidate["constraints"]
        if constraint["kind"] == "DATE"
    ] == [["사흘 뒤"]]


def test_new_gmail_send__verification_reread__is_not_a_source_read() -> None:
    runtime = FakeStructuredInferencePort(
        outputs=[
            {
                "goal": "새 메시지를 보내고 결과를 확인한다",
                "completion_conditions": ["전송된 메시지를 재조회한다"],
                "constraints": _goal_constraints(
                    recipient=["qhdrbdhkdwks2@gmail.com"],
                    subject=["[GWA E2E #197] SEND"],
                ),
                "resource_responsibilities": _resource_responsibilities(
                    output_type="GMAIL_MESSAGE", output_effect="SEND"
                ),
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

    assert candidate["requested_effect_hints"] == ["SEND"]
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
                ),
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


def test_source_search_write__source_responsibility__derives_read_effect() -> None:
    runtime = FakeStructuredInferencePort(
        outputs=[
            {
                "goal": "기존 자료를 찾아 메시지를 보낸다",
                "completion_conditions": ["관련 메시지를 보낸다"],
                "constraints": _goal_constraints(
                    search_terms=["Project Anchor"],
                ),
                "resource_responsibilities": _resource_responsibilities(
                    source_type="GMAIL_THREAD",
                    required_information=["일정"],
                    output_type="GMAIL_MESSAGE",
                    output_effect="SEND",
                ),
                "analysis_requirement": "NONE",
            }
        ]
    )

    candidate = identify_goal(
        llm_runtime=runtime,
        request=_request("기존 Project Anchor 자료를 찾아 관련 답장을 보내줘."),
        prompt_ref=_prompt_ref("request_understanding.identify_goal", "identify_goal"),
    )

    assert candidate["requested_effect_hints"] == ["READ", "SEND"]
    assert candidate["requested_resource_hints"] == ["GMAIL_THREAD", "GMAIL_MESSAGE"]


def test_lexical_anchor_alone__standalone_write__does_not_force_source_read() -> None:
    runtime = FakeStructuredInferencePort(
        outputs=[
            {
                "goal": "새 메시지를 보낸다",
                "completion_conditions": ["메시지를 보낸다"],
                "constraints": _goal_constraints(search_terms=["Project Anchor"]),
                "resource_responsibilities": _resource_responsibilities(
                    output_type="GMAIL_MESSAGE", output_effect="SEND"
                ),
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


def test_existing_gmail_thread_reply__incompatible_output_resource__rejects_output() -> None:
    runtime = FakeStructuredInferencePort(
        outputs=[
            {
                "goal": "기존 메일 대화에 답장한다",
                "completion_conditions": ["같은 대화의 보낸 답장을 재조회한다"],
                "constraints": _goal_constraints(
                    recipient=["qhdrbdhkdwks2@gmail.com"],
                    subject=["[GWA E2E #197] SEND"],
                ),
                "resource_responsibilities": _resource_responsibilities(
                    source_type="GMAIL_THREAD",
                    required_information=[],
                    output_type="GMAIL_THREAD",
                    output_effect="SEND",
                ),
                "analysis_requirement": "NONE",
            }
        ]
    )

    with pytest.raises(ValueError, match="output responsibility candidate"):
        identify_goal(
            llm_runtime=runtime,
            request=_request(
                '제목이 "[GWA E2E #197] SEND"인 기존 메일 대화를 찾아서 '
                "qhdrbdhkdwks2@gmail.com에게 답장해."
            ),
            prompt_ref=_prompt_ref("request_understanding.identify_goal", "identify_goal"),
        )


def test_identify_goal__duplicate_output_responsibilities__rejects_output() -> None:
    decisions = _output_responsibility_decisions(output_types={"GMAIL_MESSAGE": "SEND"})[
        "output_responsibilities"
    ]
    duplicated_decisions = [*decisions, dict(decisions[0])]
    runtime = FakeStructuredInferencePort(
        outputs=[
            {
                "goal": "기존 메일 대화에 답장한다",
                "completion_conditions": ["답장을 보낸다"],
                "constraints": _goal_constraints(
                    recipient=["qhdrbdhkdwks2@gmail.com"],
                    subject=["[GWA E2E #197] SEND"],
                ),
                "analysis_requirement": "NONE",
            },
            _source_dependency_decisions(),
            {"output_responsibilities": duplicated_decisions},
        ]
    )

    with pytest.raises(ValueError, match="output responsibility candidate"):
        identify_goal(
            llm_runtime=runtime,
            request=_request("기존 메일 대화를 찾아 답장해."),
            prompt_ref=_prompt_ref("request_understanding.identify_goal", "identify_goal"),
        )


@pytest.mark.parametrize(
    "effect,resource_type",
    [
        ("CREATE", "GMAIL_THREAD"),
        ("UPDATE", "GMAIL_THREAD"),
        ("SEND", "GMAIL_THREAD"),
        ("DELETE", "GMAIL_THREAD"),
    ],
)
def test_identify_goal__write_effect_without_compatible_resource__rejects_output(
    effect: str, resource_type: str
) -> None:
    runtime = FakeStructuredInferencePort(
        outputs=[
            {
                "goal": "외부 업무를 수행한다",
                "completion_conditions": ["요청한 변경을 수행한다"],
                "constraints": _goal_constraints(),
                "resource_responsibilities": _resource_responsibilities(
                    output_type=resource_type, output_effect=effect
                ),
                "analysis_requirement": "NONE",
            }
        ]
    )

    with pytest.raises(ValueError, match="output responsibility candidate"):
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
                        "field": "recipient",
                        "value": ["qhdrbdhkdwks2@gmail.com"],
                    },
                    sender=["qhdrbdhkdwks2@gmail.com"],
                ),
                "resource_responsibilities": _resource_responsibilities(
                    source_type="GMAIL_THREAD", required_information=[]
                ),
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
                    {"field": "repository", "value": "GWA E2E"}
                ),
                "resource_responsibilities": _resource_responsibilities(
                    source_type="TASK",
                    required_information=[],
                    output_type="TASK",
                    output_effect="UPDATE",
                ),
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
                "constraints": _goal_constraints(
                    {
                        "field": "repository",
                        "value": "openai/codex",
                        "provenance": {
                            "source": "USER_REQUEST",
                            "start_offset": 0,
                            "end_offset": 12,
                        },
                    }
                ),
                "resource_responsibilities": _resource_responsibilities(
                    source_type="GITHUB_ISSUE", required_information=[]
                ),
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
