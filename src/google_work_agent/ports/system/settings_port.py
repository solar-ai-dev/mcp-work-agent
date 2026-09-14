"""Versioned non-secret settings storage boundary."""

import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal, Protocol

from google_work_agent.ports.system.contracts.operational_command_replay import (
    OperationalReconcileResultV1,
)

MAX_SOURCE_PAGE_CALLS_PER_RUN = 50


@dataclass(frozen=True, slots=True)
class PanelPreferencesV1:
    schema_version: Literal[1]
    right_panel_default_open: bool
    right_panel_default_tab: Literal["CONVERSATIONS", "RESOURCES"]


@dataclass(frozen=True, slots=True)
class GitHubRepositoryDefaultV1:
    repository: str
    repository_id: int
    account_id: str

    @classmethod
    def from_payload(cls, value: object) -> "GitHubRepositoryDefaultV1":
        if not isinstance(value, Mapping) or set(value) != {
            "repository",
            "repository_id",
            "account_id",
        }:
            raise ValueError("invalid GitHub repository default payload")
        repository, repository_id, account_id = (
            value["repository"],
            value["repository_id"],
            value["account_id"],
        )
        if (
            not isinstance(repository, str)
            or type(repository_id) is not int
            or not isinstance(account_id, str)
        ):
            raise ValueError("invalid GitHub repository default fields")
        return cls(repository, repository_id, account_id)

    def __post_init__(self) -> None:
        if (
            not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9-]*/[A-Za-z0-9_.-]+", self.repository)
            or self.repository.split("/")[-1] in {".", ".."}
            or len(self.repository) > 200
            or type(self.repository_id) is not int
            or self.repository_id <= 0
            or not re.fullmatch(r"github:[1-9][0-9]*", self.account_id)
        ):
            raise ValueError("invalid GitHub repository default")


@dataclass(frozen=True, slots=True)
class SettingsPatchV1:
    schema_version: Literal[1]
    selected_calendar_ids: tuple[str, ...] | None = None
    selected_tasklist_ids: tuple[str, ...] | None = None
    selected_github_repositories: tuple[GitHubRepositoryDefaultV1, ...] | None = None
    google_resource_account_id: str | None = None
    preferred_local_model_id: Literal["qwen3.5:9b", "qwen3.5:4b"] | None = None
    timezone: str | None = None
    default_tasklist_id: str | None = None
    default_calendar_id: str | None = None
    clear_default_calendar: bool = False
    clear_default_tasklist: bool = False
    default_github_repository: GitHubRepositoryDefaultV1 | None = None
    github_repository_supplied: bool = False
    preferred_llm_mode: Literal["LOCAL_GPU", "API_LLM"] | None = None
    external_llm_consent: bool | None = None
    retention_days: int | None = None
    theme: Literal["LIGHT", "DARK"] | None = None
    panel_preferences: PanelPreferencesV1 | None = None
    working_day_start_local: str | None = None
    working_day_end_local: str | None = None
    include_weekends: bool | None = None
    calendar_buffer_minutes: int | None = None
    max_run_execution_ms: int | None = None
    max_connector_calls_per_run: int | None = None
    max_source_page_calls_per_run: int | None = None
    max_detail_fetches_per_run: int | None = None
    max_context_tokens_per_run: int | None = None
    max_retry_attempts_per_run: int | None = None
    circuit_failure_threshold: int | None = None
    circuit_open_duration_ms: int | None = None


@dataclass(frozen=True, slots=True)
class SettingsViewV1:
    schema_version: Literal[1]
    timezone: str
    default_tasklist_id: str | None
    default_calendar_id: str | None
    preferred_llm_mode: Literal["AUTO", "LOCAL_GPU", "API_LLM"]
    external_llm_consent: bool
    retention_days: int
    theme: Literal["LIGHT", "DARK"]
    panel_preferences: PanelPreferencesV1
    working_day_start_local: str
    working_day_end_local: str
    include_weekends: bool
    calendar_buffer_minutes: int
    max_run_execution_ms: int
    max_connector_calls_per_run: int
    max_source_page_calls_per_run: int
    max_detail_fetches_per_run: int
    max_context_tokens_per_run: int
    max_retry_attempts_per_run: int
    circuit_failure_threshold: int
    circuit_open_duration_ms: int
    preferred_local_model_id: str | None = None
    default_github_repository: GitHubRepositoryDefaultV1 | None = None
    selected_calendar_ids: tuple[str, ...] | None = None
    selected_tasklist_ids: tuple[str, ...] | None = None
    selected_github_repositories: tuple[GitHubRepositoryDefaultV1, ...] | None = None
    google_resource_account_id: str | None = None


class SettingsPort(Protocol):
    def get_settings(self) -> SettingsViewV1: ...

    def update_settings(
        self, settings_patch: SettingsPatchV1, operation_ref: str
    ) -> SettingsViewV1: ...

    def reconcile_settings(
        self, operation_ref: str, settings_patch: SettingsPatchV1
    ) -> OperationalReconcileResultV1: ...


__all__ = [
    "GitHubRepositoryDefaultV1",
    "PanelPreferencesV1",
    "SettingsPatchV1",
    "SettingsPort",
    "SettingsViewV1",
    "MAX_SOURCE_PAGE_CALLS_PER_RUN",
]
