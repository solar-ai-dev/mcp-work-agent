from google_work_agent.application.tool_registry.load_signed_tool_registry import (
    load_signed_tool_registry,
)


def test_signed_manifest__matches_current_canonical__connector_rows() -> None:
    registry = load_signed_tool_registry()
    expected = {
        "gmail_search_threads",
        "gmail_get_thread",
        "gmail_get_message",
        "gmail_get_attachment",
        "gmail_create_draft",
        "gmail_update_draft",
        "gmail_get_draft",
        "gmail_send",
        "tasks_list_tasklists",
        "tasks_list_tasks",
        "tasks_get_task",
        "tasks_create_task",
        "tasks_update_task",
        "tasks_delete_task",
        "calendar_list_calendars",
        "calendar_list_events",
        "calendar_query_freebusy",
        "calendar_get_event",
        "calendar_create_event",
        "calendar_update_event",
        "calendar_delete_event",
    }

    assert {
        entry.tool_id
        for entry in registry.entries
        if entry.connector_id == "google_workspace"
    } == expected
    assert {
        entry.tool_id for entry in registry.entries if entry.connector_id == "github"
    } == {
        "github_list_issues",
        "github_get_issue",
        "github_create_issue",
        "github_update_issue",
        "github_close_issue",
        "github_reopen_issue",
    }
