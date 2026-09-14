from __future__ import annotations

import json
from pathlib import Path

import pytest

from google_work_agent.adapters.system.json_settings import (
    FileSettingsStore,
    JsonSettingsAdapter,
)
from google_work_agent.ports.system.settings_port import (
    GitHubRepositoryDefaultV1,
    SettingsPatchV1,
    SettingsViewV1,
)


def _adapter(tmp_path: Path) -> JsonSettingsAdapter:
    return JsonSettingsAdapter(store=FileSettingsStore(tmp_path / "app-settings.json"))


def test_settings_update__replays_same__operation_and_reconciles(tmp_path: Path) -> None:
    adapter = _adapter(tmp_path)
    patch = SettingsPatchV1(schema_version=1, theme="DARK", retention_days=7)

    first = adapter.update_settings(patch, "settings-op-1")
    replay = adapter.update_settings(patch, "settings-op-1")

    assert replay == first
    assert replay.theme == "DARK"
    assert replay.retention_days == 7
    assert adapter.reconcile_settings("settings-op-1", patch).status == "COMPLETED"


def test_settings_operation__ref_conflict__fails_closed(tmp_path: Path) -> None:
    adapter = _adapter(tmp_path)
    adapter.update_settings(SettingsPatchV1(schema_version=1, theme="DARK"), "settings-op-1")

    with pytest.raises(ValueError, match="different settings patch"):
        adapter.update_settings(SettingsPatchV1(schema_version=1, theme="LIGHT"), "settings-op-1")


def test_google_defaults__explicit_clear__persists_without_affecting_other_settings(
    tmp_path: Path,
) -> None:
    adapter = _adapter(tmp_path)
    original = adapter.update_settings(
        SettingsPatchV1(
            schema_version=1,
            default_calendar_id="calendar",
            default_tasklist_id="tasks",
        ),
        "set-google-defaults",
    )
    unchanged = adapter.update_settings(SettingsPatchV1(schema_version=1), "omit-google-defaults")
    assert unchanged == original
    patch = SettingsPatchV1(
        schema_version=1,
        clear_default_calendar=True,
        clear_default_tasklist=True,
    )
    cleared = adapter.update_settings(patch, "clear-google-defaults")
    assert cleared.default_calendar_id is None
    assert cleared.default_tasklist_id is None
    assert cleared.default_github_repository == original.default_github_repository
    assert _adapter(tmp_path).get_settings() == cleared
    assert adapter.update_settings(patch, "clear-google-defaults") == cleared
    assert adapter.reconcile_settings("clear-google-defaults", patch).status == "COMPLETED"


def test_settings_patch__persists_selected__local_model(tmp_path: Path) -> None:
    adapter = _adapter(tmp_path)

    updated = adapter.update_settings(
        SettingsPatchV1(
            schema_version=1,
            preferred_llm_mode="LOCAL_GPU",
            preferred_local_model_id="qwen3.5:4b",
        ),
        "settings-local-model-1",
    )

    assert updated.preferred_llm_mode == "LOCAL_GPU"
    assert updated.preferred_local_model_id == "qwen3.5:4b"
    assert _adapter(tmp_path).get_settings().preferred_local_model_id == "qwen3.5:4b"


def test_settings_previous_field_set__when_loaded__adds_local_model_and_preserves_marker(
    tmp_path: Path,
) -> None:
    adapter = _adapter(tmp_path)
    adapter.update_settings(SettingsPatchV1(schema_version=1, theme="DARK"), "settings-op-1")
    path = tmp_path / "app-settings.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    del payload["settings"]["preferred_local_model_id"]
    path.write_text(json.dumps(payload), encoding="utf-8")

    settings, marker = FileSettingsStore(path).load()

    assert settings.preferred_local_model_id is None
    assert marker is not None
    assert marker["operation_ref"] == "settings-op-1"


def test_settings_unknown__persisted_field__fails_closed(tmp_path: Path) -> None:
    adapter = _adapter(tmp_path)
    adapter.get_settings()
    path = tmp_path / "app-settings.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["unknown"] = True
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="unknown fields"):
        adapter.get_settings()


def test_settings_exact__legacy_flat_envelope__migrates_atomically(tmp_path: Path) -> None:
    path = tmp_path / "app-settings.json"
    path.write_text(
        json.dumps(
            {
                "approval_ttl_minutes": 30,
                "approved_model_id": "legacy-model",
                "config_schema_version": 1,
                "default_calendar_id": "calendar-1",
                "default_tasklist_id": "tasks-1",
                "deployment_profile": "API_ONLY",
                "external_llm_consent": True,
                "log_level": "INFO",
                "ollama_endpoint": "http://127.0.0.1:11434",
                "requested_runtime_mode": "API_LLM",
                "run_retention_days": 14,
                "timezone": "Asia/Seoul",
                "work_hours": {
                    "days": [0, 1, 2, 3, 4],
                    "end": "18:00",
                    "start": "09:00",
                },
            }
        ),
        encoding="utf-8",
    )

    settings, marker = FileSettingsStore(path).load()

    assert marker is None
    assert settings.default_calendar_id == "calendar-1"
    assert settings.default_tasklist_id == "tasks-1"
    assert settings.preferred_llm_mode == "API_LLM"
    assert settings.external_llm_consent is True
    assert settings.retention_days == 14
    assert settings.working_day_start_local == "09:00"
    assert settings.working_day_end_local == "18:00"
    assert settings.include_weekends is False
    persisted = json.loads(path.read_text(encoding="utf-8"))
    assert set(persisted) == {"last_operation", "schema_version", "settings"}
    assert set(persisted["settings"]) == set(SettingsViewV1.__dataclass_fields__)
    assert "approved_model_id" not in persisted["settings"]


def test_repository_default__save_change_remove__survives_restart(tmp_path: Path) -> None:
    first = GitHubRepositoryDefaultV1("example/one", 1, "github:2")
    second = GitHubRepositoryDefaultV1("example/two", 3, "github:2")
    adapter = _adapter(tmp_path)
    adapter.update_settings(
        SettingsPatchV1(1, default_calendar_id="calendar", default_tasklist_id="tasks"),
        "google-defaults",
    )
    for index, selection in enumerate((first, second, None)):
        patch = SettingsPatchV1(
            1, default_github_repository=selection, github_repository_supplied=True
        )
        result = adapter.update_settings(patch, f"repository-{index}")
        assert result.default_github_repository == selection
        assert result.default_calendar_id == "calendar" and result.default_tasklist_id == "tasks"
        assert _adapter(tmp_path).get_settings() == result
        reconciled = adapter.reconcile_settings(f"repository-{index}", patch)
        assert reconciled.status == "COMPLETED"
        assert isinstance(reconciled.bounded_result, dict)
        assert "panel_preferences" in reconciled.bounded_result
        adapter.update_settings(SettingsPatchV1(1, theme="DARK"), f"theme-{index}")
        assert adapter.get_settings().default_github_repository == selection


@pytest.mark.parametrize("omit_model", [False, True])
def test_old_settings__repository_addition__preserves_other_values_and_marker(
    tmp_path: Path, omit_model: bool
) -> None:
    adapter = _adapter(tmp_path)
    adapter.update_settings(
        SettingsPatchV1(1, theme="DARK", default_tasklist_id="tasks"), "previous"
    )
    path = tmp_path / "app-settings.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    marker = payload["last_operation"]
    del payload["settings"]["default_github_repository"]
    if omit_model:
        del payload["settings"]["preferred_local_model_id"]
    path.write_text(json.dumps(payload), encoding="utf-8")
    result, migrated_marker = FileSettingsStore(path).load()
    assert result.default_github_repository is None
    assert result.default_tasklist_id == "tasks" and result.theme == "DARK"
    assert migrated_marker == marker


@pytest.mark.parametrize(
    "repository",
    ["owner", "owner/../bad", "owner/..", "https://github.com/owner/repo", "owner/repo?x=1"],
)
def test_repository_default__noncanonical_name__is_rejected(repository: str) -> None:
    with pytest.raises(ValueError):
        GitHubRepositoryDefaultV1(repository, 1, "github:2")
