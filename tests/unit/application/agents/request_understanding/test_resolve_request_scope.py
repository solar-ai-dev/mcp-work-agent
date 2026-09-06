from google_work_agent.application.agents.request_understanding.resolve_request_scope import (
    resolve_request_scope,
)


def test_quoted_write_literal__does_not_create__explicit_write_scope() -> None:
    result = resolve_request_scope("'send'라는 단어의 개념을 설명해줘")

    assert result.quoted_literals == ("'send'",)
    assert result.has_explicit_write_marker is False
    assert result.is_general_answer_only is True


def test_external_write_request__is_classified__before_goal_inference() -> None:
    result = resolve_request_scope("이 내용을 팀에게 send 해줘")

    assert result.has_explicit_write_marker is True
    assert result.is_general_answer_only is False


def test_workspace_fact_request__is_not_classified__as_general_answer() -> None:
    result = resolve_request_scope("최근 메일 요약 방법을 알려줘")

    assert result.has_explicit_write_marker is False
    assert result.is_general_answer_only is False
