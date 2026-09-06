from pathlib import Path
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
