from google_work_agent.application.agents.planning.materialize_task_create_payload import (
    materialize_task_create_payload,
)


def test_exact_task_values__when_unambiguous__materialize_without_inference() -> None:
    result = materialize_task_create_payload(
        {
            "requested_effect_hints": ["CREATE"],
            "requested_resource_hints": ["TASK"],
            "ambiguity": {"requires_confirmation": False},
            "constraints": [
                {
                    "kind": "USER_REQUIREMENT",
                    "field": "search_terms",
                    "value": ["GWA E2E Validation"],
                },
                {"kind": "RESOURCE", "field": "title", "value": "Submit report"},
                {"kind": "RESOURCE", "field": "notes", "value": "Attach evidence"},
                {"kind": "DATE", "field": "scheduled_date", "value": "2026-09-11"},
            ],
        }
    )

    assert result == {
        "title": "Submit report",
        "notes": "Attach evidence",
        "scheduled_date": "2026-09-11",
    }


def test_ambiguous_task_values__when_confirmation_required__do_not_materialize() -> None:
    result = materialize_task_create_payload(
        {
            "requested_effect_hints": ["CREATE"],
            "requested_resource_hints": ["TASK"],
            "ambiguity": {"requires_confirmation": True},
            "constraints": [
                {"kind": "RESOURCE", "field": "title", "value": "Submit report"},
            ],
        }
    )

    assert result is None


def test_semantic_field_alias__when_not_typed__does_not_materialize() -> None:
    result = materialize_task_create_payload(
        {
            "requested_effect_hints": ["CREATE"],
            "requested_resource_hints": ["TASK"],
            "ambiguity": {"requires_confirmation": False},
            "constraints": [
                {"kind": "RESOURCE", "field": "subject", "value": "Submit report"},
            ],
        }
    )

    assert result is None


def test_task_business_field__when_kind_or_name_is_invalid__does_not_materialize() -> None:
    for constraint in (
        {"kind": "TIME", "field": "scheduled_date", "value": "2026-09-11"},
        {"kind": "RESOURCE", "field": "description", "value": "Attach evidence"},
    ):
        result = materialize_task_create_payload(
            {
                "requested_effect_hints": ["CREATE"],
                "requested_resource_hints": ["TASK"],
                "ambiguity": {"requires_confirmation": False},
                "constraints": [
                    {"kind": "RESOURCE", "field": "title", "value": "Submit report"},
                    constraint,
                ],
            }
        )

        assert result is None


def test_source_derived_task__with_required_information__requires_composition() -> None:
    result = materialize_task_create_payload(
        {
            "requested_effect_hints": ["READ", "CREATE"],
            "requested_resource_hints": ["GMAIL_THREAD", "TASK"],
            "ambiguity": {"requires_confirmation": False},
            "constraints": [
                {"kind": "RESOURCE", "field": "title", "value": "Submit report"},
                {
                    "kind": "USER_REQUIREMENT",
                    "field": "required_information",
                    "value": ["메일의 최신 변경 내용을 메모에 반영"],
                },
            ],
        }
    )

    assert result is None


def test_direct_task__with_unresolved_business_meaning__requires_composition() -> None:
    result = materialize_task_create_payload(
        {
            "requested_effect_hints": ["CREATE"],
            "requested_resource_hints": ["TASK"],
            "ambiguity": {"requires_confirmation": False},
            "constraints": [
                {"kind": "RESOURCE", "field": "title", "value": "Submit report"},
                {
                    "kind": "USER_REQUIREMENT",
                    "field": "business_concepts",
                    "value": ["최신 변경 내용"],
                },
            ],
        }
    )

    assert result is None
