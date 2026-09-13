from google_work_agent.application.agents.task_calendar_draft_source import (
    project_task_calendar_source_terms,
)


def test_project_task_calendar_source_terms__with_ordered_sources__strips_calendar_suffix() -> None:
    constraints = [
        {
            "kind": "USER_REQUIREMENT",
            "field": "search_terms",
            "value": "recipient@example.com",
            "provenance": {"source": "USER_REQUEST", "start_offset": 30},
        },
        {
            "kind": "USER_REQUIREMENT",
            "field": "search_terms",
            "value": "Orion",
            "provenance": {"source": "USER_REQUEST", "start_offset": 0},
        },
        {
            "kind": "USER_REQUIREMENT",
            "field": "search_terms",
            "value": "제작소 일정 일정 보고",
            "provenance": {"source": "USER_REQUEST", "start_offset": 7},
        },
    ]

    assert project_task_calendar_source_terms(constraints) == {
        "task_terms": ["Orion"],
        "calendar_provider_terms": ["제작소"],
        "calendar_evidence_terms": ["Orion", "제작소"],
    }
