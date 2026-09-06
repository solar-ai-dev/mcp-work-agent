from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest

from google_work_agent.adapters.system.filesystem_operational_command_replay import (
    FilesystemOperationalCommandReplayAdapter,
)
from google_work_agent.adapters.system.json_settings import FileSettingsStore, JsonSettingsAdapter
from google_work_agent.application.use_cases.setting.update_settings import (
    UpdateSettingsCommand,
    UpdateSettingsHandler,
)
from google_work_agent.ports.connector.connector_failure import (
    ConnectorFailureCode,
    ConnectorOperationFailure,
)
from google_work_agent.ports.system.settings_port import GitHubRepositoryDefaultV1, SettingsPatchV1


def test_resource_selection__save_reload_clear_and_replay__preserves_identity(
    tmp_path: Path,
) -> None:
    settings = JsonSettingsAdapter(store=FileSettingsStore(tmp_path / "settings.json"))
    calls = []

    class Inventory:
        def list_task_lists(self, **_kwargs):
            calls.append("tasks")
            return SimpleNamespace(
                items=[SimpleNamespace(resource_id=item) for item in ("one", "two", "three")],
                next_page_token=None,
            )

        def list_calendars(self, **_kwargs):
            calls.append("calendars")
            return SimpleNamespace(
                items=[SimpleNamespace(resource_id=item) for item in ("one", "two", "three")],
                next_page_token=None,
            )

    def access(query):
        calls.append(query.repository)
        return GitHubRepositoryDefaultV1(
            query.repository, 2 if query.repository.endswith("two") else 3, "github:1"
        )

    handler = UpdateSettingsHandler(
        settings=settings,
        replay=FilesystemOperationalCommandReplayAdapter(tmp_path / "replay"),
        resource_inventory=cast(Any, Inventory()),
        google_account_id=lambda: "google:1",
        repository_access=cast(Any, access),
    )
    command = UpdateSettingsCommand(
        "multi-select",
        SettingsPatchV1(
            1, selected_tasklist_ids=("one", "two"), selected_calendar_ids=("two", "three")
        ),
        github_repositories=("person/two", "person/three"),
    )
    first = handler(command)
    assert first.settings.selected_tasklist_ids == ("one", "two")
    assert first.settings.selected_calendar_ids == ("two", "three")
    assert first.settings.google_resource_account_id == "google:1"
    assert first.settings.default_tasklist_id is None and first.settings.default_calendar_id is None
    assert first.settings.default_github_repository is None
    assert len(first.settings.selected_github_repositories) == 2
    assert (
        JsonSettingsAdapter(store=FileSettingsStore(tmp_path / "settings.json")).get_settings()
        == first.settings
    )
    assert handler(command).settings == first.settings
    assert len(calls) == 4
    cleared = handler(
        UpdateSettingsCommand(
            "clear", SettingsPatchV1(1, selected_tasklist_ids=()), github_repositories=()
        )
    )
    assert cleared.settings.selected_tasklist_ids == ()
    assert cleared.settings.selected_github_repositories == ()
    assert cleared.settings.selected_calendar_ids == ("two", "three")


def test_resource_selection__invalid_or_stale_target__does_not_persist(tmp_path: Path) -> None:
    settings = JsonSettingsAdapter(store=FileSettingsStore(tmp_path / "settings.json"))
    original = settings.get_settings()
    inventory = SimpleNamespace(
        list_task_lists=lambda **_: SimpleNamespace(items=[], next_page_token=None)
    )
    handler = UpdateSettingsHandler(
        settings=settings,
        replay=FilesystemOperationalCommandReplayAdapter(tmp_path / "replay"),
        resource_inventory=inventory,
        google_account_id=lambda: "google:1",
    )
    with pytest.raises(ValueError, match="접근 가능한"):
        handler(
            UpdateSettingsCommand("invalid", SettingsPatchV1(1, selected_tasklist_ids=("missing",)))
        )
    assert settings.get_settings() == original


@pytest.mark.parametrize(
    "ready,active,allowed", [(True, False, True), (False, False, False), (True, True, False)]
)
def test_local_model_selection__validates_ready_and_active_run__before_save(
    tmp_path, ready, active, allowed
):
    settings = JsonSettingsAdapter(store=FileSettingsStore(tmp_path / "settings.json"))
    models = SimpleNamespace(
        list_local_models=lambda: [
            SimpleNamespace(model_id="qwen3.5:4b", installed=ready, approved=ready)
        ]
    )
    handler = UpdateSettingsHandler(
        settings=settings,
        replay=FilesystemOperationalCommandReplayAdapter(tmp_path / "replay"),
        local_models=models,
        has_active_run=lambda: active,
    )
    command = UpdateSettingsCommand(
        "model", SettingsPatchV1(1, preferred_local_model_id="qwen3.5:4b")
    )
    if allowed:
        assert handler(command).settings.preferred_local_model_id == "qwen3.5:4b"
        assert handler(command).replayed
    else:
        with pytest.raises(ValueError):
            handler(command)
        assert settings.get_settings().preferred_local_model_id is None


def test_update_settings__has_exact__application_owner() -> None:
    assert (
        UpdateSettingsHandler.__module__
        == "google_work_agent.application.use_cases.setting.update_settings"
    )
    assert UpdateSettingsHandler.__name__ == "UpdateSettingsHandler"


def test_repository_selection__server_bound_identity__replays_without_provider_access(
    tmp_path: Path,
) -> None:
    settings = JsonSettingsAdapter(store=FileSettingsStore(tmp_path / "settings.json"))
    calls = []

    def access(query):
        calls.append(query)
        return GitHubRepositoryDefaultV1(query.repository, 12, "github:42")

    handler = UpdateSettingsHandler(
        settings=settings,
        replay=FilesystemOperationalCommandReplayAdapter(tmp_path / "replay"),
        repository_access=cast(Any, access),
    )
    command = UpdateSettingsCommand("select", SettingsPatchV1(1), "sample/project", True)
    first = handler(command)
    second = handler(command)
    assert first.settings.default_github_repository == GitHubRepositoryDefaultV1(
        "sample/project", 12, "github:42"
    )
    assert second.replayed and second.settings == first.settings
    assert len(calls) == 1
    cleared = handler(UpdateSettingsCommand("clear", SettingsPatchV1(1), None, True))
    assert cleared.settings.default_github_repository is None
    assert len(calls) == 1


def test_repository_selection__permission_failure__does_not_persist_default(tmp_path: Path) -> None:
    settings = JsonSettingsAdapter(store=FileSettingsStore(tmp_path / "settings.json"))
    original = settings.get_settings()

    def denied(_query):
        raise ConnectorOperationFailure(ConnectorFailureCode.PERMISSION_DENIED, "DENIED")

    handler = UpdateSettingsHandler(
        settings=settings,
        replay=FilesystemOperationalCommandReplayAdapter(tmp_path / "replay"),
        repository_access=cast(Any, denied),
    )
    with pytest.raises(ConnectorOperationFailure):
        handler(UpdateSettingsCommand("select", SettingsPatchV1(1), "sample/project", True))
    assert settings.get_settings() == original


def test_repository_selection__post_commit_crash__reconciles_full_settings_without_rewrite(
    tmp_path: Path,
) -> None:
    class InterruptedSettings(JsonSettingsAdapter):
        def update_settings(self, patch, operation_ref):
            super().update_settings(patch, operation_ref)
            raise RuntimeError("simulated crash after atomic settings save")

    calls = []

    def access(query):
        calls.append(query)
        return GitHubRepositoryDefaultV1(query.repository, 12, "github:42")

    settings = InterruptedSettings(store=FileSettingsStore(tmp_path / "settings.json"))
    handler = UpdateSettingsHandler(
        settings=settings,
        replay=FilesystemOperationalCommandReplayAdapter(tmp_path / "replay"),
        repository_access=cast(Any, access),
    )
    command = UpdateSettingsCommand("select", SettingsPatchV1(1), "sample/project", True)
    with pytest.raises(RuntimeError, match="simulated crash"):
        handler(command)
    recovered = handler(command)
    assert recovered.replayed
    assert recovered.settings.default_github_repository.repository == "sample/project"
    assert len(calls) == 1
