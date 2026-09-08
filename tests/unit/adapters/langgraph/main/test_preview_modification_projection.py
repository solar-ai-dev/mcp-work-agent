from google_work_agent.adapters.langgraph.main.preview_modification_projection import (
    project_user_action_modification,
)


def test_preview_modification__projects_only__explicitly_changed_argument_paths() -> None:
    result = project_user_action_modification(
        action_id="action-1",
        previous_arguments={
            "to": ["bonggyulim0728@gmail.com"],
            "subject": "Before",
            "body": "Before body",
            "attachments": [],
        },
        current_arguments={
            "to": ["bonggyulim0728@gmail.com"],
            "subject": "After",
            "body": "After body",
            "attachments": [],
        },
    )

    assert result == {
        "action_id": "action-1",
        "argument_overrides": {"body": "After body", "subject": "After"},
    }


def test_preview_modification__preserves_nested_and_removed__field_identity() -> None:
    result = project_user_action_modification(
        action_id="action-1",
        previous_arguments={"payload": {"title": "Same", "notes": "Remove"}},
        current_arguments={"payload": {"title": "Same", "due": None}},
    )

    assert result == {
        "action_id": "action-1",
        "argument_overrides": {"payload.due": None, "payload.notes": None},
    }


def test_preview_modification__omits_unchanged__action() -> None:
    assert (
        project_user_action_modification(
            action_id="action-1",
            previous_arguments={"subject": "Same"},
            current_arguments={"subject": "Same"},
        )
        is None
    )
