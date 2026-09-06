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
