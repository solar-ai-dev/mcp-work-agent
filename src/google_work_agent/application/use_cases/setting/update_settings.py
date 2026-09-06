"""Update non-secret settings through crash-safe operational replay."""

from dataclasses import asdict, dataclass, replace
from typing import Any, cast

from google_work_agent.application.use_cases.operational_replay import execute_operational_command
from google_work_agent.application.use_cases.resource.get_repository_access import (
    GetRepositoryAccessHandler,
    GetRepositoryAccessQuery,
)
from google_work_agent.ports.system.operational_command_replay_port import (
    OperationalCommandReplayPort,
)
from google_work_agent.ports.system.settings_port import (
    GitHubRepositoryDefaultV1,
    PanelPreferencesV1,
    SettingsPatchV1,
    SettingsPort,
    SettingsViewV1,
)


@dataclass(frozen=True, slots=True)
class UpdateSettingsCommand:
    command_id: str
    settings_patch: SettingsPatchV1
    github_repository: str | None = None
    github_repository_supplied: bool = False


@dataclass(frozen=True, slots=True)
class UpdateSettingsResult:
    settings: SettingsViewV1
    operation_ref: str
    replayed: bool


class UpdateSettingsHandler:
    def __init__(
        self,
        *,
        settings: SettingsPort,
        replay: OperationalCommandReplayPort,
        repository_access: GetRepositoryAccessHandler | None = None,
    ) -> None:
        self._settings = settings
        self._replay = replay
        self._repository_access = repository_access

    def __call__(self, command: UpdateSettingsCommand) -> UpdateSettingsResult:
        request_payload = asdict(command.settings_patch)
        for field in ("clear_default_calendar", "clear_default_tasklist"):
            if not request_payload[field]:
                request_payload.pop(field)
        request_payload.pop("default_github_repository")
        request_payload.pop("github_repository_supplied")
        if command.github_repository_supplied:
            request_payload.update(
                github_repository=command.github_repository, github_repository_supplied=True
            )

        def resolved_patch(*, reconcile: bool = False) -> SettingsPatchV1:
            if not command.github_repository_supplied:
                return command.settings_patch
            binding = None
            if command.github_repository is not None:
                if reconcile:
                    binding = self._settings.get_settings().default_github_repository
                    if (
                        binding is None
                        or binding.repository.casefold() != command.github_repository.casefold()
                    ):
                        return replace(command.settings_patch, github_repository_supplied=True)
                else:
                    if self._repository_access is None:
                        raise ValueError("GitHub Repository 연결 준비가 필요합니다.")
                    binding = self._repository_access(
                        GetRepositoryAccessQuery(command.github_repository)
                    )
            return replace(
                command.settings_patch,
                default_github_repository=binding,
                github_repository_supplied=True,
            )

        def execute(ref: str) -> tuple[str, dict[str, object]]:
            value = self._settings.update_settings(resolved_patch(), ref)
            return ref, asdict(value)

        outcome = execute_operational_command(
            replay_port=self._replay,
            command_id=command.command_id,
            operation_kind="UPDATE_SETTINGS",
            request_payload=request_payload,
            reconcile=lambda ref: self._settings.reconcile_settings(
                ref, resolved_patch(reconcile=True)
            ),
            execute=execute,
        )
        payload = dict(cast(dict[str, object], outcome.bounded_result))
        payload["panel_preferences"] = PanelPreferencesV1(**cast(Any, payload["panel_preferences"]))
        if payload.get("default_github_repository") is not None:
            payload["default_github_repository"] = GitHubRepositoryDefaultV1(
                **cast(Any, payload["default_github_repository"]),
            )
        return UpdateSettingsResult(
            settings=SettingsViewV1(**cast(Any, payload)),
            operation_ref=outcome.operation_ref,
            replayed=outcome.replayed,
        )


__all__ = ["UpdateSettingsCommand", "UpdateSettingsHandler", "UpdateSettingsResult"]
