from google_work_agent.application.agents.planning.sanitize_user_visible_answer import (
    sanitize_user_visible_answer,
)


def test_sanitize_user_visible_answer__internal_identifiers__removes_diagnostic_values() -> None:
    result = sanitize_user_visible_answer(
        "근거 custom-private-ref evidence-abc (THREAD ID: private-thread)",
        internal_refs=["custom-private-ref"], user_request="요약해줘",
    )
    assert "확인한 자료" in result
    assert "private" not in result
    assert "evidence-abc" not in result


def test_sanitize_user_visible_answer__foreign_source_quote__retains_observed_text() -> None:
    result = sanitize_user_visible_answer(
        "원문 東京, 추가 未確認", internal_refs=[], user_request="내용 알려줘",
        source_texts=["東京 행사 안내"],
    )
    assert "東京" in result
    assert "未確認" not in result
