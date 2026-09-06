from dataclasses import replace

import pytest

from google_work_agent.adapters.system.json_settings import FileSettingsStore, JsonSettingsAdapter
from google_work_agent.application.use_cases.resource.require_resource_selection import (
    RequireResourceSelectionHandler,
    SelectedResourceReadPort,
)
from google_work_agent.ports.connector.connector_failure import ConnectorOperationFailure
from google_work_agent.ports.connector.connector_read_port import ConnectorReadResultV1
from google_work_agent.ports.connector.contracts.validated_connector_tool_binding import (
    ValidatedConnectorToolBindingV1,
)
from google_work_agent.ports.system.settings_port import GitHubRepositoryDefaultV1


@pytest.mark.parametrize(
    "connector,tool,arguments,allowed",
    [
        ("google_workspace", "tasks_list_tasks", {"task_list_id": "two"}, True),
        ("google_workspace", "tasks_get_task", {"task_list_id": "one", "task_id": "task"}, False),
        ("google_workspace", "tasks_create_task", {"task_list_id": "three"}, True),
        ("google_workspace", "tasks_create_task", {"task_list_id": "@default"}, False),
        ("google_workspace", "calendar_create_event", {"calendar_id": "two"}, True),
        ("google_workspace", "calendar_query_freebusy", {"calendar_ids": ["two", "one"]}, False),
        ("google_workspace", "calendar_query_freebusy", {"calendar_ids": ["two", "three"]}, True),
        ("google_workspace", "gmail_search_threads", {"query": "subject:meeting"}, True),
        ("github", "github_list_issues", {"repository": "person/two"}, True),
        ("github", "github_create_issue", {"repository": "person/one"}, False),
    ],
)
def test_selection_gate__checks_exact_scope__before_io(
    tmp_path, connector, tool, arguments, allowed
):
    settings = replace(
        JsonSettingsAdapter(store=FileSettingsStore(tmp_path / "settings.json")).get_settings(),
        selected_tasklist_ids=("two", "three"),
        selected_calendar_ids=("two", "three"),
        google_resource_account_id="google:1",
        selected_github_repositories=(GitHubRepositoryDefaultV1("person/two", 2, "github:1"),),
    )
    gate = RequireResourceSelectionHandler(
        lambda: settings, lambda source: "github:1" if source == "github" else "google:1"
    )
    if allowed:
        gate(connector, tool, arguments)
    else:
        with pytest.raises(ConnectorOperationFailure, match="RESOURCE_NOT_SELECTED"):
            gate(connector, tool, arguments)
    assert gate.default_target("tasks", "@default") is None
    assert gate.default_target("calendar", "primary") is None
    assert gate.browse_target("tasks", "@default") == "two"


def test_selection_gate__account_change_and_empty_selection__never_fall_back(tmp_path):
    settings = replace(
        JsonSettingsAdapter(store=FileSettingsStore(tmp_path / "settings.json")).get_settings(),
        selected_tasklist_ids=("two",),
        google_resource_account_id="google:1",
    )
    gate = RequireResourceSelectionHandler(lambda: settings, lambda _: "google:2")
    assert gate.default_target("tasks", "@default") is None
    with pytest.raises(ConnectorOperationFailure):
        gate("google_workspace", "tasks_list_tasks", {"task_list_id": "two"})
    settings = replace(settings, google_resource_account_id="google:2", selected_tasklist_ids=())
    with pytest.raises(ConnectorOperationFailure):
        gate("google_workspace", "tasks_create_task", {"task_list_id": "two"})


def test_selected_reader__filters_inventory_and_blocks_details__without_provider_call(tmp_path):
    settings = replace(
        JsonSettingsAdapter(store=FileSettingsStore(tmp_path / "settings.json")).get_settings(),
        selected_tasklist_ids=("two",),
        google_resource_account_id="google:1",
    )
    calls = []

    class Reader:
        def execute_read(self, binding, arguments):
            calls.append((binding.tool_id, arguments))
            return ConnectorReadResultV1(
                1,
                binding.tool_id,
                "request",
                {
                    "items": [{"resource_id": "one"}, {"resource_id": "two"}],
                    "next_page_token": "next",
                },
                "next",
                2,
            )

    raw = Reader()
    scoped = SelectedResourceReadPort(
        raw, RequireResourceSelectionHandler(lambda: settings, lambda _: "google:1")
    )
    binding = ValidatedConnectorToolBindingV1(
        1,
        "google_workspace",
        "task_list",
        "tasks_list_tasklists",
        "READ",
        "input",
        "output",
        "a" * 64,
    )
    result = scoped.execute_read(binding, {})
    assert result.output["items"] == [{"resource_id": "two"}]
    assert result.next_page_token == "next" and result.total_count is None
    with pytest.raises(ConnectorOperationFailure):
        scoped.execute_read(replace(binding, tool_id="tasks_get_task"), {"task_list_id": "one"})
    assert len(calls) == 1
    # Only Settings inventory uses the dedicated unscoped read boundary.
    assert len(raw.execute_read(binding, {}).output["items"]) == 2


@pytest.mark.parametrize(
    "connector,tool,arguments",
    [
        ("google_workspace", "tasks_get_task", {"task_list_id": "two"}),
        ("google_workspace", "calendar_get_event", {"calendar_id": "two"}),
        ("github", "github_get_issue", {"repository": "person/two"}),
        ("github", "search_by_recovery_fingerprint", {"repository": "person/two"}),
        (
            "google_workspace",
            "search_by_recovery_fingerprint",
            {"resource_type": "task", "task_list_id": "two"},
        ),
    ],
)
def test_selection_gate__unconfigured_or_revoked__blocks_followup_io(
    tmp_path, connector, tool, arguments
):
    settings = JsonSettingsAdapter(
        store=FileSettingsStore(tmp_path / "settings.json")
    ).get_settings()
    for selected_settings in (
        settings,
        replace(
            settings,
            selected_tasklist_ids=(),
            selected_calendar_ids=(),
            selected_github_repositories=(),
        ),
    ):
        gate = RequireResourceSelectionHandler(
            lambda selected_settings=selected_settings: selected_settings, lambda _: "account"
        )
        with pytest.raises(ConnectorOperationFailure, match="RESOURCE_NOT_SELECTED"):
            gate(connector, tool, arguments)
    assert gate.default_target("tasks", "@default") is None
