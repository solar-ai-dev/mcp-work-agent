"""Update non-secret settings through crash-safe operational replay."""

from collections.abc import Callable
from dataclasses import asdict, dataclass, replace
from typing import Any, cast

from google_work_agent.application.use_cases.operational_replay import execute_operational_command
from google_work_agent.application.use_cases.resource.connector_read_projection import (
    ConnectorReadProjection,
)
from google_work_agent.application.use_cases.resource.get_repository_access import (
    GetRepositoryAccessHandler,
    GetRepositoryAccessQuery,
)
from google_work_agent.ports.llm.llm_runtime_status_port import LlmRuntimeStatusPort
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
    github_repositories: tuple[str, ...] | None = None


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
        resource_inventory: ConnectorReadProjection | None = None,
        google_account_id: Callable[[], str | None] = lambda: None,
        local_models: LlmRuntimeStatusPort | None = None,
        has_active_run: Callable[[], bool] = lambda: False,
    ) -> None:
        self._settings = settings
        self._replay = replay
        self._repository_access = repository_access
        self._resource_inventory = resource_inventory
        self._google_account_id = google_account_id
        self._local_models = local_models
        self._has_active_run = has_active_run

    def __call__(self, command: UpdateSettingsCommand) -> UpdateSettingsResult:
        request_payload = asdict(command.settings_patch)
        for field in (
            "selected_calendar_ids",
            "selected_tasklist_ids",
            "selected_github_repositories",
            "google_resource_account_id",
            "preferred_local_model_id",
        ):
            if request_payload[field] is None:
                request_payload.pop(field)
        if command.github_repositories is not None:
            request_payload["github_repositories"] = command.github_repositories
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
            patch = self._resolve_selection(command, reconcile=reconcile)
            if not command.github_repository_supplied:
                return patch
            binding = None
            if command.github_repository is not None:
                if reconcile:
                    binding = self._settings.get_settings().default_github_repository
                    if (
                        binding is None
                        or binding.repository.casefold() != command.github_repository.casefold()
                    ):
                        return replace(patch, github_repository_supplied=True)
                else:
                    if self._repository_access is None:
                        raise ValueError("GitHub Repository 연결 준비가 필요합니다.")
                    binding = self._repository_access(
                        GetRepositoryAccessQuery(command.github_repository)
                    )
            return replace(
                patch,
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
        if payload.get("selected_github_repositories") is not None:
            payload["selected_github_repositories"] = tuple(
                GitHubRepositoryDefaultV1.from_payload(item)
                for item in cast(list[object], payload["selected_github_repositories"])
            )
        for field in ("selected_calendar_ids", "selected_tasklist_ids"):
            if payload.get(field) is not None:
                payload[field] = tuple(cast(list[str], payload[field]))
        return UpdateSettingsResult(
            settings=SettingsViewV1(**cast(Any, payload)),
            operation_ref=outcome.operation_ref,
            replayed=outcome.replayed,
        )

    def _resolve_selection(
        self, command: UpdateSettingsCommand, *, reconcile: bool
    ) -> SettingsPatchV1:
        patch = command.settings_patch
        current = self._settings.get_settings()
        if patch.timezone is not None and patch.timezone != "Asia/Seoul":
            raise ValueError("시간대는 한국(Asia/Seoul)입니다.")
        if patch.preferred_local_model_id is not None and not reconcile:
            if (
                patch.preferred_local_model_id != current.preferred_local_model_id
                and self._has_active_run()
            ):
                raise ValueError("진행 중인 작업을 끝낸 뒤 로컬 모델을 변경해 주세요.")
            if self._local_models is None or not any(
                item.model_id == patch.preferred_local_model_id and item.installed and item.approved
                for item in self._local_models.list_local_models()
            ):
                raise ValueError("검사에서 준비가 확인된 로컬 모델만 선택할 수 있습니다.")
        for selected, default, clearing in (
            (patch.selected_calendar_ids, patch.default_calendar_id, patch.clear_default_calendar),
            (patch.selected_tasklist_ids, patch.default_tasklist_id, patch.clear_default_tasklist),
        ):
            if selected is not None and (default is not None or clearing):
                raise ValueError("자료 선택과 이전 기본값을 함께 변경할 수 없습니다.")
        if command.github_repositories is not None:
            if command.github_repository_supplied:
                raise ValueError("저장소 선택과 이전 기본값을 함께 변경할 수 없습니다.")
            names = command.github_repositories
            if len(names) > 100 or len({name.casefold() for name in names}) != len(names):
                raise ValueError("저장소는 중복 없이 100개까지 선택할 수 있습니다.")
            if reconcile:
                bindings = current.selected_github_repositories or ()
            else:
                if names and self._repository_access is None:
                    raise ValueError("GitHub 연결 준비가 필요합니다.")
                bindings = tuple(
                    self._repository_access(GetRepositoryAccessQuery(name))
                    for name in names
                    if self._repository_access is not None
                )
            patch = replace(patch, selected_github_repositories=bindings)
        if patch.selected_calendar_ids is not None or patch.selected_tasklist_ids is not None:
            account = current.google_resource_account_id if reconcile else self._google_account_id()
            if not account:
                raise ValueError("Google Workspace를 연결한 뒤 사용할 자료를 선택해 주세요.")
            if not reconcile:
                self._validate_google_selection("calendar", patch.selected_calendar_ids)
                self._validate_google_selection("tasks", patch.selected_tasklist_ids)
            patch = replace(patch, google_resource_account_id=account)
            if current.google_resource_account_id not in (None, account):
                patch = replace(
                    patch,
                    selected_calendar_ids=patch.selected_calendar_ids or (),
                    selected_tasklist_ids=patch.selected_tasklist_ids or (),
                )
            # Materialize both account-bound selections for stable post-save reconciliation.
            patch = replace(
                patch,
                selected_calendar_ids=(
                    patch.selected_calendar_ids
                    if patch.selected_calendar_ids is not None
                    else current.selected_calendar_ids or ()
                ),
                selected_tasklist_ids=(
                    patch.selected_tasklist_ids
                    if patch.selected_tasklist_ids is not None
                    else current.selected_tasklist_ids or ()
                ),
            )
        # Retired default updates must not bypass an explicitly saved resource scope.
        if (
            (current.selected_calendar_ids is not None and patch.default_calendar_id is not None)
            or (current.selected_tasklist_ids is not None and patch.default_tasklist_id is not None)
            or (
                current.selected_github_repositories is not None
                and command.github_repository_supplied
            )
        ):
            raise ValueError("기본값 대신 사용할 자료 목록을 변경해 주세요.")
        return patch

    def _validate_google_selection(self, source: str, selected: tuple[str, ...] | None) -> None:
        if selected is None or not selected:
            return
        if len(selected) > 100 or len(set(selected)) != len(selected):
            raise ValueError("자료는 중복 없이 100개까지 선택할 수 있습니다.")
        if self._resource_inventory is None:
            raise ValueError("Google 자료 목록을 확인할 수 없습니다.")
        operation = (
            self._resource_inventory.list_calendars
            if source == "calendar"
            else self._resource_inventory.list_task_lists
        )
        remaining = set(selected)
        token = None
        seen: set[str] = set()
        for _ in range(100):
            page = operation(page_token=token, page_size=100)
            remaining.difference_update(item.resource_id for item in page.items)
            if not remaining:
                return
            token = page.next_page_token
            if token is None or token in seen:
                break
            seen.add(token)
        raise ValueError("접근 가능한 자료만 선택할 수 있습니다. 목록을 새로고침해 주세요.")


__all__ = ["UpdateSettingsCommand", "UpdateSettingsHandler", "UpdateSettingsResult"]
