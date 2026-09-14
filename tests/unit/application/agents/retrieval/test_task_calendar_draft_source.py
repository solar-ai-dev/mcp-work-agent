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


def test_project_task_calendar_source_terms__recovers_source_bound_typed_concepts() -> None:
    request = (
        "Orion 할 일과 제작소 일정 보고로 준비 상황을 알리는 메일 초안을 작성해줘."
    )
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
            "value": "Gmail 임시보관함",
            "provenance": {"source": "USER_REQUEST", "start_offset": 45},
        },
        {
            "kind": "USER_REQUIREMENT",
            "field": "business_concepts",
            "value": ["Orion 할 일", "제작소 일정 보고", "준비 상황"],
        },
        {
            "kind": "USER_REQUIREMENT",
            "field": "original_search_request",
            "value": [request],
        },
    ]

    assert project_task_calendar_source_terms(constraints) == {
        "task_terms": ["Orion"],
        "calendar_provider_terms": ["제작소"],
        "calendar_evidence_terms": ["Orion", "제작소"],
    }


def test_project_task_calendar_source_terms__does_not_invent_unbound_concept_anchor() -> None:
    constraints = [
        {
            "kind": "USER_REQUIREMENT",
            "field": "search_terms",
            "value": "Gmail 임시보관함",
            "provenance": {"source": "USER_REQUEST", "start_offset": 10},
        },
        {
            "kind": "USER_REQUIREMENT",
            "field": "business_concepts",
            "value": ["Invented 할 일", "Invented 일정"],
        },
        {
            "kind": "USER_REQUIREMENT",
            "field": "original_search_request",
            "value": ["요청 원문에는 그 고유명이 없다"],
        },
    ]

    assert project_task_calendar_source_terms(constraints) == {
        "task_terms": ["Gmail 임시보관함"],
        "calendar_provider_terms": ["Gmail 임시보관함"],
        "calendar_evidence_terms": ["Gmail 임시보관함"],
    }
