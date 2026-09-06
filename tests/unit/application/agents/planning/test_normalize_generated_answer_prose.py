import pytest

from google_work_agent.application.agents.planning.normalize_generated_answer_prose import (
    normalize_generated_answer_prose,
)


def test_normalize_generated_answer_prose__nested_sections__retains_original_content() -> None:
    assert normalize_generated_answer_prose(
        '{"sections":[{"section_title":"일정","content":"연도 미확정: 9월 3일"}]}'
    ) == "## 일정\n\n연도 미확정: 9월 3일"


def test_normalize_generated_answer_prose__internal_json_only__rejects_non_prose() -> None:
    with pytest.raises(ValueError, match="user-visible prose"):
        normalize_generated_answer_prose('{"reason_codes":["DONE"]}')
