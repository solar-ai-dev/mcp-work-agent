import pytest

from google_work_agent.application.agents.request_understanding.contracts.request_intent import (
    RequestGoalCandidateV1,
    RequestUnderstandingValidationError,
)
from google_work_agent.application.agents.request_understanding.finalize_intent import (
    finalize_intent,
)


def test_finalize_intent__valid_candidates__attaches_application_lineage() -> None:
    goal_candidate: RequestGoalCandidateV1 = {
        "goal": "goal",
        "completion_conditions": ["done"],
        "constraints": [],
        "requested_effect_hints": ["READ"],
        "requested_resource_hints": ["TASK"],
        "analysis_requirement": "REQUIRED",
    }
    intent = finalize_intent(
        goal_candidate,
        {"requires_confirmation": False, "reason_codes": [], "missing_fields": []},
        artifact_id="intent-1",
        user_request="goal",
    )

    assert intent["schema_version"] == 2
    assert intent["meta"] == {"artifact_id": "intent-1", "revision": 1, "based_on": []}


def test_finalize_intent__same_run_reconsideration__increments_existing_artifact() -> None:
    goal_candidate: RequestGoalCandidateV1 = {
        "goal": "reconsidered goal",
        "completion_conditions": ["done"],
        "constraints": [],
        "requested_effect_hints": ["READ"],
        "requested_resource_hints": ["GMAIL_MESSAGE"],
        "analysis_requirement": "REQUIRED",
    }
    prior = finalize_intent(
        {**goal_candidate, "goal": "initial goal"},
        {"requires_confirmation": False, "reason_codes": [], "missing_fields": []},
        artifact_id="intent-1",
        user_request="goal",
    )

    revised = finalize_intent(
        goal_candidate,
        {"requires_confirmation": False, "reason_codes": [], "missing_fields": []},
        artifact_id="ignored-new-id",
        user_request="goal",
        prior_intent=prior,
    )

    assert revised["meta"] == {
        "artifact_id": "intent-1",
        "revision": 2,
        "based_on": [{"artifact_id": "intent-1", "revision": 1}],
    }


def test_finalize_intent__materializes_exact_user_request__repository_provenance() -> None:
    repository = "solar-ai-dev/google-work-agent"
    request_text = f"{repository} 저장소의 열린 이슈를 찾아줘"
    candidate: RequestGoalCandidateV1 = {
        "goal": "열린 이슈 조회",
        "completion_conditions": ["이슈를 나열한다"],
        "constraints": [{"kind": "RESOURCE", "field": "repository", "value": repository}],
        "requested_effect_hints": ["READ"],
        "requested_resource_hints": ["GITHUB_ISSUE"],
        "analysis_requirement": "NONE",
    }

    intent = finalize_intent(
        candidate,
        {"requires_confirmation": False, "reason_codes": [], "missing_fields": []},
        artifact_id="intent-1",
        user_request=request_text,
    )

    provenance = intent["constraints"][0]["provenance"]
    assert provenance == {
        "source": "USER_REQUEST",
        "start_offset": 0,
        "end_offset": len(repository),
    }


def test_finalize_intent__materializes_confirmation_response__repository_provenance() -> None:
    repository = "solar-ai-dev/google-work-agent"
    candidate: RequestGoalCandidateV1 = {
        "goal": "열린 이슈 조회",
        "completion_conditions": ["이슈를 나열한다"],
        "constraints": [{"kind": "RESOURCE", "field": "repository", "value": repository}],
        "requested_effect_hints": ["READ"],
        "requested_resource_hints": ["GITHUB_ISSUE"],
        "analysis_requirement": "NONE",
    }

    intent = finalize_intent(
        candidate,
        {"requires_confirmation": False, "reason_codes": [], "missing_fields": []},
        artifact_id="intent-1",
        user_request="저 저장소의 열린 이슈를 찾아줘",
        confirmation_response_text=repository,
    )

    assert intent["constraints"][0]["provenance"] == {
        "source": "CONFIRMATION_RESPONSE",
        "start_offset": 0,
        "end_offset": len(repository),
    }


def test_finalize_intent__source_literals__split_and_bind_each_scalar_value() -> None:
    request_text = "Nimbus와 Quartz 관련 메일을 확인해줘"
    candidate: RequestGoalCandidateV1 = {
        "goal": "관련 메일 조회",
        "completion_conditions": ["관련 메일을 확인한다"],
        "constraints": [
            {
                "kind": "USER_REQUIREMENT",
                "field": "search_terms",
                "value": ["Nimbus", "Quartz", "모델 가설"],
                "provenance": {
                    "source": "USER_REQUEST",
                    "start_offset": 999,
                    "end_offset": 1000,
                },
            },
            {
                "kind": "USER_REQUIREMENT",
                "field": "business_concepts",
                "value": ["출시 일정"],
            },
        ],
        "requested_effect_hints": ["READ"],
        "requested_resource_hints": ["GMAIL_THREAD"],
        "analysis_requirement": "NONE",
    }

    intent = finalize_intent(
        candidate,
        {"requires_confirmation": False, "reason_codes": [], "missing_fields": []},
        artifact_id="intent-literals",
        user_request=request_text,
    )

    assert intent["constraints"][:3] == [
        {
            "kind": "USER_REQUIREMENT",
            "field": "search_terms",
            "value": "Nimbus",
            "provenance": {
                "source": "USER_REQUEST",
                "start_offset": request_text.index("Nimbus"),
                "end_offset": request_text.index("Nimbus") + len("Nimbus"),
            },
        },
        {
            "kind": "USER_REQUIREMENT",
            "field": "search_terms",
            "value": "Quartz",
            "provenance": {
                "source": "USER_REQUEST",
                "start_offset": request_text.index("Quartz"),
                "end_offset": request_text.index("Quartz") + len("Quartz"),
            },
        },
        {
            "kind": "USER_REQUIREMENT",
            "field": "search_terms",
            "value": "모델 가설",
        },
    ]
    assert intent["constraints"][3] == {
        "kind": "USER_REQUIREMENT",
        "field": "business_concepts",
        "value": ["출시 일정"],
    }


def test_finalize_intent__confirmation_literal__binds_only_to_current_response() -> None:
    subject = "Quartz 납품 회신 검토"
    candidate: RequestGoalCandidateV1 = {
        "goal": "확인된 제목의 메일 조회",
        "completion_conditions": ["메일을 확인한다"],
        "constraints": [{"kind": "RESOURCE", "field": "subject", "value": [subject]}],
        "requested_effect_hints": ["READ"],
        "requested_resource_hints": ["GMAIL_THREAD"],
        "analysis_requirement": "NONE",
    }

    intent = finalize_intent(
        candidate,
        {"requires_confirmation": False, "reason_codes": [], "missing_fields": []},
        artifact_id="intent-confirmed-subject",
        user_request="방금 선택한 제목의 메일을 확인해줘",
        confirmation_response_text=subject,
    )

    assert intent["constraints"] == [
        {
            "kind": "RESOURCE",
            "field": "subject",
            "value": subject,
            "provenance": {
                "source": "CONFIRMATION_RESPONSE",
                "start_offset": 0,
                "end_offset": len(subject),
            },
        }
    ]


def test_finalize_intent__materializes_exact_user_request__gmail_draft_provenance() -> None:
    draft_id = "r976635311795334843"
    request_text = f"Gmail 초안 ID {draft_id}를 수정해줘"
    candidate: RequestGoalCandidateV1 = {
        "goal": "Gmail 초안 수정",
        "completion_conditions": ["초안을 수정한다"],
        "constraints": [{"kind": "RESOURCE", "field": "draft_id", "value": draft_id}],
        "requested_effect_hints": ["UPDATE"],
        "requested_resource_hints": ["GMAIL_DRAFT"],
        "analysis_requirement": "NONE",
    }

    intent = finalize_intent(
        candidate,
        {"requires_confirmation": False, "reason_codes": [], "missing_fields": []},
        artifact_id="intent-1",
        user_request=request_text,
    )

    start_offset = request_text.index(draft_id)
    assert intent["constraints"][0]["provenance"] == {
        "source": "USER_REQUEST",
        "start_offset": start_offset,
        "end_offset": start_offset + len(draft_id),
    }


def test_finalize_intent__rejects_llm_only__gmail_draft_id() -> None:
    candidate: RequestGoalCandidateV1 = {
        "goal": "Gmail 초안 수정",
        "completion_conditions": ["초안을 수정한다"],
        "constraints": [
            {"kind": "RESOURCE", "field": "draft_id", "value": "invented-draft-id"}
        ],
        "requested_effect_hints": ["UPDATE"],
        "requested_resource_hints": ["GMAIL_DRAFT"],
        "analysis_requirement": "NONE",
    }

    with pytest.raises(RequestUnderstandingValidationError, match="source binding"):
        finalize_intent(
            candidate,
            {"requires_confirmation": False, "reason_codes": [], "missing_fields": []},
            artifact_id="intent-1",
            user_request="이 Gmail 초안을 수정해줘",
        )


@pytest.mark.parametrize("repository", ["google-work-agent", "owner/", "/repo", "a/b/c"])
def test_finalize_intent__rejects_repository_without__fully_qualified_source_authority(
    repository: str,
) -> None:
    candidate: RequestGoalCandidateV1 = {
        "goal": "열린 이슈 조회",
        "completion_conditions": ["이슈를 나열한다"],
        "constraints": [{"kind": "RESOURCE", "field": "repository", "value": repository}],
        "requested_effect_hints": ["READ"],
        "requested_resource_hints": ["GITHUB_ISSUE"],
        "analysis_requirement": "NONE",
    }

    with pytest.raises(RequestUnderstandingValidationError):
        finalize_intent(
            candidate,
            {"requires_confirmation": False, "reason_codes": [], "missing_fields": []},
            artifact_id="intent-1",
            user_request=repository,
        )


def test_finalize_intent__rejects_llm_only__repository() -> None:
    candidate: RequestGoalCandidateV1 = {
        "goal": "열린 이슈 조회",
        "completion_conditions": ["이슈를 나열한다"],
        "constraints": [
            {"kind": "RESOURCE", "field": "repository", "value": "other-owner/repo"}
        ],
        "requested_effect_hints": ["READ"],
        "requested_resource_hints": ["GITHUB_ISSUE"],
        "analysis_requirement": "NONE",
    }

    with pytest.raises(RequestUnderstandingValidationError, match="source binding"):
        finalize_intent(
            candidate,
            {"requires_confirmation": False, "reason_codes": [], "missing_fields": []},
            artifact_id="intent-1",
            user_request="저 저장소의 열린 이슈를 찾아줘",
        )
