import pytest

from google_work_agent.application.agents.planning.project_empty_read_answer import (
    project_empty_read_answer,
)


@pytest.mark.parametrize("failure_kind", ["NOT_FOUND", "SCOPE"])
def test_github_access_failure__requires_access_action__never_claims_empty_issues(
    failure_kind,
) -> None:
    result = project_empty_read_answer(
        user_request="열린 이슈 보여줘",
        request_intent={
            "requested_effect_hints": ["READ"], "requested_resource_hints": ["GITHUB_ISSUE"],
        },
        retrieval_result={"source_statuses": [{
            "resource_type": "GITHUB_ISSUE", "status": "FAILED", "failure_kind": failure_kind,
        }]}, evidence=[],
    )
    assert result is not None
    assert "GitHub App 설치" in result.draft["answer"]
    assert "이슈가 없다는 뜻은 아닙니다" in result.draft["answer"]
    assert failure_kind not in result.draft["answer"]


def test_partial_source_failure__is_not_presented_as_no_result() -> None:
    result = project_empty_read_answer(
        user_request="최근 회의 메일을 찾아줘.",
        request_intent={
            "requested_effect_hints": ["READ"],
            "requested_resource_hints": ["GMAIL_THREAD"],
            "constraints": [{"kind": "DATE", "field": "period", "value": ["최근"]}],
        },
        retrieval_result={
            "coverage": "PARTIAL",
            "source_statuses": [{"status": "FAILED", "failure_kind": "CONNECTOR_UNAVAILABLE"}],
            "missing_information": [],
        },
        evidence=[],
    )

    assert result is not None
    assert "일부 읽기에 실패" in result.draft["answer"]
    assert "CONNECTOR_UNAVAILABLE" not in result.draft["answer"]


def test_no_result_criteria__uses_only_user_owned_search_constraints() -> None:
    result = project_empty_read_answer(
        user_request="지난주 프로젝트 일정 메일을 찾아줘.",
        request_intent={
            "requested_effect_hints": ["READ"],
            "requested_resource_hints": ["GMAIL_THREAD"],
            "constraints": [
                {"kind": "RESOURCE", "field": "search_terms", "value": "project_schedule"},
                {"kind": "DATE", "field": "period", "value": ["지난주"]},
                {
                    "kind": "USER_REQUIREMENT",
                    "field": "search_terms",
                    "value": ["프로젝트", "일정"],
                },
            ],
        },
        retrieval_result={
            "source_statuses": [{"status": "COMPLETE", "failure_kind": None}],
            "missing_information": [{"description": "REQUIRED_SOURCE_RETURNED_NO_RESOURCES"}],
        },
        evidence=[],
    )

    assert result is not None
    assert result.draft["answer"].startswith("'지난주 · 프로젝트 · 일정' 조건으로")
    assert "project_schedule" not in result.draft["answer"]
