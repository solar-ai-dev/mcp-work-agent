"""Canonical partial settings-update wire request."""

from typing import Literal

from pydantic import Field

from google_work_agent.api.schemas.model import ApiModel


class PanelPreferencesPayloadV1(ApiModel):
    schema_version: Literal[1]
    right_panel_default_open: bool
    right_panel_default_tab: Literal["CONVERSATIONS", "RESOURCES"]


class SettingsPatchPayloadV1(ApiModel):
    schema_version: Literal[1]
    timezone: Literal["Asia/Seoul"] | None = None
    selected_calendar_ids: tuple[str, ...] | None = Field(default=None, max_length=100)
    selected_tasklist_ids: tuple[str, ...] | None = Field(default=None, max_length=100)
    selected_github_repositories: tuple[str, ...] | None = Field(default=None, max_length=100)
    preferred_local_model_id: Literal["qwen3.5:9b", "qwen3.5:4b"] | None = None
    default_tasklist_id: str | None = None
    default_calendar_id: str | None = None
    default_github_repository: str | None = Field(
        default=None, max_length=200, pattern=r"^[A-Za-z0-9][A-Za-z0-9-]*/[A-Za-z0-9_.-]+$"
    )
    preferred_llm_mode: Literal["LOCAL_GPU", "API_LLM"] | None = None
    external_llm_consent: bool | None = None
    retention_days: int | None = None
    theme: Literal["LIGHT", "DARK"] | None = None
    panel_preferences: PanelPreferencesPayloadV1 | None = None
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


class PatchSettingsRequest(ApiModel):
    schema_version: Literal[1]
    command_id: str
    settings_patch: SettingsPatchPayloadV1


__all__ = ["PanelPreferencesPayloadV1", "PatchSettingsRequest", "SettingsPatchPayloadV1"]
