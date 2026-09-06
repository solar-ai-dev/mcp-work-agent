"""Settings, backup, restore, and shutdown routes over exact Application owners."""

from __future__ import annotations

from dataclasses import asdict
from typing import NoReturn

from fastapi import APIRouter, Header, Request

from google_work_agent.api.dependencies.access_control import enforce_access
from google_work_agent.api.dependencies.contract_version import (
    enforce_supported_api_contract_version,
)
from google_work_agent.api.dependencies.runtime_operation import enforce_runtime_operation
from google_work_agent.api.dependencies.settings import SettingsRouteDependency
from google_work_agent.api.errors.api_request_error import ApiRequestError
from google_work_agent.api.schemas.settings.create_backup import (
    BackupResponse,
    CreateBackupRequestV1,
)
from google_work_agent.api.schemas.settings.create_restore_plan import (
    RestorePlanRequest,
    RestorePlanResponse,
)
from google_work_agent.api.schemas.settings.get_settings import SettingsResponse
from google_work_agent.api.schemas.settings.list_backups import BackupListResponse
from google_work_agent.api.schemas.settings.request_shutdown import (
    RequestShutdownRequestV1,
    ShutdownResponse,
)
from google_work_agent.api.schemas.settings.update_settings import PatchSettingsRequest
from google_work_agent.application.use_cases.backup.create_backup import (
    CreateBackupCommand,
    CreateBackupHandler,
)
from google_work_agent.application.use_cases.backup.list_backups import (
    ListBackupsHandler,
    ListBackupsQuery,
)
from google_work_agent.application.use_cases.backup.restore_backup import (
    RestoreBackupCommand,
    RestoreBackupHandler,
)
from google_work_agent.application.use_cases.operational_replay import (
    OperationalCommandConflict,
    OperationalCommandUncertain,
)
from google_work_agent.application.use_cases.setting.get_settings import (
    GetSettingsHandler,
    GetSettingsQuery,
)
from google_work_agent.application.use_cases.setting.update_settings import (
    UpdateSettingsCommand,
    UpdateSettingsHandler,
)
from google_work_agent.application.use_cases.shutdown.request_shutdown import (
    RequestShutdownCommand,
    RequestShutdownHandler,
)
from google_work_agent.ports.connector.connector_failure import (
    ConnectorFailureCode,
    ConnectorOperationFailure,
)
from google_work_agent.ports.system.api_access_port import EndpointPolicy
from google_work_agent.ports.system.settings_port import (
    PanelPreferencesV1,
    SettingsPatchV1,
)

router = APIRouter(prefix="/api/v1")


def _contract(
    request: Request,
    dependencies: SettingsRouteDependency,
    version: str | None,
    operation: str,
) -> None:
    enforce_access(request, policy=EndpointPolicy.API_SESSION_REQUIRED)
    enforce_supported_api_contract_version(
        supported_version=dependencies.api_contract_version,
        request_id=request.state.request_id,
        request_version=version,
    )
    enforce_runtime_operation(request, operation=operation)


@router.get("/settings", response_model=SettingsResponse)
def get_settings(
    request: Request,
    dependencies: SettingsRouteDependency,
    x_api_contract_version: str | None = Header(default=None),
) -> SettingsResponse:
    _contract(request, dependencies, x_api_contract_version, "SETTINGS")
    handler = dependencies.get_settings_handler
    if not isinstance(handler, GetSettingsHandler):
        _raise_service_unavailable(request, "SETTINGS_READ_UNAVAILABLE")
    result = handler(GetSettingsQuery())
    return SettingsResponse.model_validate(asdict(result.settings))


@router.put("/settings", response_model=SettingsResponse)
def patch_settings(
    payload: PatchSettingsRequest,
    request: Request,
    dependencies: SettingsRouteDependency,
    x_api_contract_version: str | None = Header(default=None),
) -> SettingsResponse:
    _contract(request, dependencies, x_api_contract_version, "SETTINGS")
    handler = dependencies.update_settings_handler
    if not isinstance(handler, UpdateSettingsHandler):
        _raise_service_unavailable(request, "SETTINGS_UPDATE_UNAVAILABLE")
    values = payload.settings_patch.model_dump()
    github_repository = values.pop("default_github_repository")
    panel = values.pop("panel_preferences")
    settings_patch = SettingsPatchV1(
        **values,
        clear_default_calendar="default_calendar_id" in payload.settings_patch.model_fields_set
        and values["default_calendar_id"] is None,
        clear_default_tasklist="default_tasklist_id" in payload.settings_patch.model_fields_set
        and values["default_tasklist_id"] is None,
        panel_preferences=None if panel is None else PanelPreferencesV1(**panel),
    )
    try:
        result = handler(
            UpdateSettingsCommand(
                command_id=payload.command_id,
                settings_patch=settings_patch,
                github_repository=github_repository,
                github_repository_supplied="default_github_repository"
                in payload.settings_patch.model_fields_set,
            )
        )
    except (OperationalCommandConflict, OperationalCommandUncertain) as error:
        _raise_operational_failure(error, request_id=request.state.request_id)
    except ValueError as error:
        _raise_invalid_argument(request, str(error), "SETTINGS_VALIDATION_FAILED")
    except ConnectorOperationFailure as error:
        error_code, status_code = {
            ConnectorFailureCode.AUTH_REQUIRED: ("AUTH_REQUIRED", 401),
            ConnectorFailureCode.PERMISSION_DENIED: ("PERMISSION_DENIED", 403),
            ConnectorFailureCode.NOT_FOUND: ("NOT_FOUND", 404),
            ConnectorFailureCode.INVALID_ARGUMENT: ("INVALID_ARGUMENT", 422),
            ConnectorFailureCode.RATE_LIMITED: ("UPSTREAM_UNAVAILABLE", 429),
            ConnectorFailureCode.TIMEOUT: ("UPSTREAM_UNAVAILABLE", 504),
            ConnectorFailureCode.CONNECTION_UNAVAILABLE: ("SERVICE_BUSY", 503),
            ConnectorFailureCode.CONFIGURATION_ERROR: ("CONFIGURATION_ERROR", 503),
        }.get(error.code, ("UPSTREAM_UNAVAILABLE", 502))
        raise ApiRequestError(
            error_code=error_code,
            status_code=status_code,
            user_message=(
                "GitHub 계정과 Repository 접근 권한을 확인한 뒤 다시 선택해 주세요."
                if status_code in {401, 403, 404}
                else "Repository 접근 상태를 확인하지 못해 설정을 저장하지 않았습니다."
            ),
            request_id=request.state.request_id,
            retryable=error.retryable,
            detail_code=error.detail_code,
        ) from error
    return SettingsResponse.model_validate(asdict(result.settings))


@router.get("/backups", response_model=BackupListResponse)
def list_backups(
    request: Request,
    dependencies: SettingsRouteDependency,
    x_api_contract_version: str | None = Header(default=None),
) -> BackupListResponse:
    _contract(request, dependencies, x_api_contract_version, "BACKUP")
    handler = dependencies.list_backups_handler
    if not isinstance(handler, ListBackupsHandler):
        _raise_service_unavailable(request, "BACKUP_LIST_UNAVAILABLE")
    result = handler(ListBackupsQuery())
    return BackupListResponse(
        schema_version=1,
        items=[BackupResponse.model_validate(asdict(item)) for item in result.backups],
    )


@router.post("/backups", response_model=BackupResponse)
def create_backup(
    payload: CreateBackupRequestV1,
    request: Request,
    dependencies: SettingsRouteDependency,
    x_api_contract_version: str | None = Header(default=None),
) -> BackupResponse:
    _contract(request, dependencies, x_api_contract_version, "BACKUP")
    handler = dependencies.create_backup_handler
    if not isinstance(handler, CreateBackupHandler):
        _raise_service_unavailable(request, "BACKUP_CREATE_UNAVAILABLE")
    try:
        result = handler(CreateBackupCommand(command_id=payload.command_id))
    except (OperationalCommandConflict, OperationalCommandUncertain) as error:
        _raise_operational_failure(error, request_id=request.state.request_id)
    except ValueError as error:
        _raise_invalid_argument(request, str(error), "BACKUP_BLOCKED", status_code=409)
    return BackupResponse.model_validate(asdict(result.backup))


@router.post("/restore", response_model=RestorePlanResponse)
def restore_backup(
    payload: RestorePlanRequest,
    request: Request,
    dependencies: SettingsRouteDependency,
    x_api_contract_version: str | None = Header(default=None),
) -> RestorePlanResponse:
    _contract(request, dependencies, x_api_contract_version, "RESTORE")
    if not dependencies.safe_mode_enabled:
        _raise_invalid_argument(
            request,
            "restore requires the offline Safe Mode core",
            "RESTORE_REQUIRES_SAFE_MODE",
            status_code=409,
        )
    handler = dependencies.restore_backup_handler
    if not isinstance(handler, RestoreBackupHandler):
        _raise_service_unavailable(request, "BACKUP_RESTORE_UNAVAILABLE")
    try:
        result = handler(
            RestoreBackupCommand(
                command_id=payload.command_id,
                backup_ref=payload.backup_ref,
            )
        )
    except (OperationalCommandConflict, OperationalCommandUncertain) as error:
        _raise_operational_failure(error, request_id=request.state.request_id)
    except ValueError as error:
        _raise_invalid_argument(request, str(error), "RESTORE_INVALID")
    return RestorePlanResponse.model_validate(asdict(result.restore))


@router.post("/control/shutdown", response_model=ShutdownResponse)
def shutdown(
    payload: RequestShutdownRequestV1,
    request: Request,
    dependencies: SettingsRouteDependency,
    x_api_contract_version: str | None = Header(default=None),
) -> ShutdownResponse:
    _contract(request, dependencies, x_api_contract_version, "SHUTDOWN")
    handler = dependencies.request_shutdown_handler
    if not isinstance(handler, RequestShutdownHandler):
        _raise_service_unavailable(request, "SHUTDOWN_UNAVAILABLE")
    try:
        result = handler(RequestShutdownCommand(command_id=payload.command_id))
    except (OperationalCommandConflict, OperationalCommandUncertain) as error:
        _raise_operational_failure(error, request_id=request.state.request_id)
    return ShutdownResponse.model_validate(asdict(result.shutdown))


def _raise_service_unavailable(request: Request, detail_code: str) -> NoReturn:
    raise ApiRequestError(
        error_code="SERVICE_BUSY",
        user_message="The requested operational service is not available.",
        status_code=503,
        request_id=request.state.request_id,
        detail_code=detail_code,
    )


def _raise_invalid_argument(
    request: Request,
    message: str,
    detail_code: str,
    *,
    status_code: int = 422,
) -> NoReturn:
    raise ApiRequestError(
        error_code="INVALID_ARGUMENT" if status_code == 422 else "CONFLICT",
        user_message=message,
        status_code=status_code,
        request_id=request.state.request_id,
        detail_code=detail_code,
    )


def _raise_operational_failure(
    error: OperationalCommandConflict | OperationalCommandUncertain,
    *,
    request_id: str,
) -> NoReturn:
    conflict = isinstance(error, OperationalCommandConflict)
    raise ApiRequestError(
        error_code="CONFLICT" if conflict else "SERVICE_BUSY",
        user_message=(
            "The command identity conflicts with an earlier request."
            if conflict
            else "The previous operation result is not yet known."
        ),
        status_code=409 if conflict else 503,
        request_id=request_id,
        retryable=not conflict,
        detail_code="OPERATION_COMMAND_CONFLICT" if conflict else "OPERATION_RESULT_UNCERTAIN",
    ) from error


__all__ = ["router"]
