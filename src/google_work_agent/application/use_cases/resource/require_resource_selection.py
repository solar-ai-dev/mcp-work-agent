"""Enforce the user's account-bound resource selection before new provider work."""

from collections.abc import Callable
from dataclasses import dataclass, replace

from google_work_agent.application.use_cases.resource.get_repository_access import (
    GetRepositoryAccessHandler,
    GetRepositoryAccessQuery,
)
from google_work_agent.ports.connector.connector_failure import (
    ConnectorFailureCode,
    ConnectorOperationFailure,
)
from google_work_agent.ports.connector.connector_read_port import (
    ConnectorReadPort,
    ConnectorReadResultV1,
    JsonValue,
)
from google_work_agent.ports.connector.contracts.validated_connector_tool_binding import (
    ValidatedConnectorToolBindingV1,
)
from google_work_agent.ports.system.settings_port import SettingsViewV1


@dataclass(frozen=True, slots=True)
class RequireResourceSelectionHandler:
    settings: Callable[[], SettingsViewV1]
    current_account_id: Callable[[str], str | None]
    repository_access: GetRepositoryAccessHandler | None = None

    def default_target(self, source: str, legacy_fallback: str) -> str | None:
        settings = self.settings()
        selected = (
            settings.selected_tasklist_ids if source == "tasks" else settings.selected_calendar_ids
        )
        if selected is not None:
            if settings.google_resource_account_id != self.current_account_id("google_workspace"):
                return None
            return selected[0] if len(selected) == 1 else None
        return None

    def __call__(self, connector_id: str, tool_id: str, arguments: dict[str, JsonValue]) -> None:
        settings = self.settings()
        if connector_id == "github" and (
            tool_id.startswith("github_") or tool_id == "search_by_recovery_fingerprint"
        ):
            repositories = settings.selected_github_repositories
            if repositories is None:
                raise _not_selected()
            account = self.current_account_id(connector_id)
            repository = arguments.get("repository")
            if not isinstance(repository, str) or not any(
                item.repository.casefold() == repository.casefold() and item.account_id == account
                for item in repositories
            ):
                raise _not_selected()
            if self.repository_access is not None:
                expected = next(
                    item
                    for item in repositories
                    if item.repository.casefold() == repository.casefold()
                )
                self.repository_access(
                    GetRepositoryAccessQuery(repository, expected_default=expected)
                )

        if connector_id != "google_workspace":
            return
        if tool_id == "search_by_recovery_fingerprint":
            resource_type = arguments.get("resource_type")
            if resource_type == "task":
                tool_id = "tasks_get_task"
            elif resource_type in {"calendar", "calendar_event"}:
                tool_id = "calendar_get_event"
            elif resource_type not in {"gmail_draft", "gmail_message", "gmail_thread"}:
                raise _not_selected()
        for prefix, key, selected in (
            ("tasks_", "task_list_id", settings.selected_tasklist_ids),
            ("calendar_", "calendar_id", settings.selected_calendar_ids),
        ):
            if not tool_id.startswith(prefix):
                continue
            if selected is None:
                raise _not_selected()
            if settings.google_resource_account_id != self.current_account_id(connector_id):
                raise _not_selected()
            if tool_id in {"tasks_list_tasklists", "calendar_list_calendars"}:
                return
            values = arguments.get("calendar_ids") if tool_id == "calendar_query_freebusy" else None
            targets = values if isinstance(values, list) else [arguments.get(key)]
            if not targets or any(
                not isinstance(target, str) or target not in selected for target in targets
            ):
                raise _not_selected()

    def browse_target(self, source: str, legacy_fallback: str) -> str | None:
        settings = self.settings()
        selected = (
            settings.selected_tasklist_ids if source == "tasks" else settings.selected_calendar_ids
        )
        if selected is not None:
            if settings.google_resource_account_id != self.current_account_id("google_workspace"):
                return None
            return next(iter(selected), None)
        return self.default_target(source, legacy_fallback)

    def project_inventory(
        self, tool_id: str, result: ConnectorReadResultV1
    ) -> ConnectorReadResultV1:
        settings = self.settings()
        selected = (
            settings.selected_tasklist_ids
            if tool_id == "tasks_list_tasklists"
            else settings.selected_calendar_ids
            if tool_id == "calendar_list_calendars"
            else None
        )
        if tool_id not in {"tasks_list_tasklists", "calendar_list_calendars"}:
            return result
        if selected is None or settings.google_resource_account_id != self.current_account_id(
            "google_workspace"
        ):
            selected = ()
        raw = result.output.get("items")
        if not isinstance(raw, list):
            return result
        items: list[JsonValue] = [
            item for item in raw if isinstance(item, dict) and item.get("resource_id") in selected
        ]
        return replace(result, output={**result.output, "items": items}, total_count=None)


@dataclass(frozen=True, slots=True)
class SelectedResourceReadPort:
    """Enforce current scope for reads, including Verification and Recovery."""

    delegate: ConnectorReadPort
    require: RequireResourceSelectionHandler

    def execute_read(
        self, binding: ValidatedConnectorToolBindingV1, tool_arguments: dict[str, JsonValue]
    ) -> ConnectorReadResultV1:
        self.require(binding.connector_id, binding.tool_id, tool_arguments)
        return self.require.project_inventory(
            binding.tool_id, self.delegate.execute_read(binding, tool_arguments)
        )


def _not_selected() -> ConnectorOperationFailure:
    return ConnectorOperationFailure(
        code=ConnectorFailureCode.PERMISSION_DENIED,
        detail_code="RESOURCE_NOT_SELECTED",
        retryable=False,
    )
