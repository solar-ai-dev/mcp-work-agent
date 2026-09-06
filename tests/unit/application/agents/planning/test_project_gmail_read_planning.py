from google_work_agent.application.agents.planning.project_gmail_read_planning import (
    project_gmail_read_planning,
)


def test_project_gmail_read_planning__simple_read__does_not_add_unrequested_analysis() -> None:
    result = project_gmail_read_planning(
        user_request="메일 찾아줘", request_intent={
            "requested_effect_hints": ["READ"], "requested_resource_hints": ["GMAIL_THREAD"],
            "analysis_requirement": "NONE", "constraints": [],
        }, evidence=[{"evidence_id": "e1", "excerpt": "9월 3일 행사"}],
    )
    assert result is not None
    assert result.outline == {"sections": ["찾은 메일"], "evidence_refs": ["e1"]}


def test_project_gmail_read_planning__non_gmail_read__does_not_claim_authority() -> None:
    assert project_gmail_read_planning(
        user_request="이슈 찾아줘", request_intent={
            "requested_effect_hints": ["READ"], "requested_resource_hints": ["GITHUB_ISSUE"],
        }, evidence=[{"evidence_id": "e1"}],
    ) is None
