"""Installed connector connection routes over canonical Application use cases."""

import logging
from typing import NoReturn

from fastapi import APIRouter, Header, Request

from google_work_agent.api.dependencies.access_control import enforce_access
from google_work_agent.api.dependencies.contract_version import (
    enforce_supported_api_contract_version,
)
from google_work_agent.api.dependencies.google_connections import (
    ConnectorConnectionDependencies,
    GoogleRouteDependency,
)
from google_work_agent.api.errors.api_request_error import ApiRequestError
from google_work_agent.api.schemas.google_connections.disconnect_google import (
    RevokeConnectionRequestV1,
    RevokeResultV1,
)
from google_work_agent.api.schemas.google_connections.get_google_connection import (
    ConnectionMetadataV1,
)
from google_work_agent.api.schemas.google_connections.start_google_oauth import (
    AuthorizationStartV1,
    StartAuthorizationRequestV1,
)
from google_work_agent.api.security.cookies import local_session_cookie_name
from google_work_agent.api.security.sessions import calculate_session_digest
from google_work_agent.application.use_cases.connection.get_connection_status import (
    GetConnectionStatusHandler,
    GetConnectionStatusQuery,
)
from google_work_agent.application.use_cases.connection.revoke_connection import (
    RevokeConnectionCommand,
    RevokeConnectionHandler,
)
from google_work_agent.application.use_cases.connection.start_authorization import (
    StartAuthorizationCommand,
    StartAuthorizationHandler,
)
from google_work_agent.application.use_cases.operational_replay import (
    OperationalCommandConflict,
    OperationalCommandUncertain,
)
from google_work_agent.application.use_cases.resource.list_repositories import (
    ListRepositoriesQuery,
    ListRepositoriesResult,
)
from google_work_agent.ports.connector.connector_failure import (
    ConnectorFailureCode,
    ConnectorOperationFailure,
)
from google_work_agent.ports.system.api_access_port import EndpointPolicy

router = APIRouter(prefix="/api/v1/connections")
logger = logging.getLogger(__name__)


@router.get("/github/repositories", response_model=ListRepositoriesResult)
def list_github_repositories(
    request: Request,
    dependencies: GoogleRouteDependency,
    cursor: str | None = None,
    x_api_contract_version: str | None = Header(default=None),
) -> ListRepositoriesResult:
    enforce_access(request, policy=EndpointPolicy.API_SESSION_REQUIRED)
    enforce_supported_api_contract_version(
        supported_version=dependencies.api_contract_version,
        request_id=request.state.request_id,
        request_version=x_api_contract_version,
    )
    connection = _resolve_connector(dependencies, "github", request.state.request_id)
    handler = dependencies.list_repositories_handler
    if handler is None:
        raise ApiRequestError(
            error_code="SERVICE_BUSY",
            status_code=503,
            user_message="GitHub Repository 연결 준비가 필요합니다.",
            request_id=request.state.request_id,
            detail_code="GITHUB_REPOSITORIES_UNAVAILABLE",
        )
    try:
        account_id = connection.current_account_id()
        session_token = request.cookies.get(
            local_session_cookie_name(dependencies.service_instance_id)
        )
        if account_id is None or session_token is None:
            raise ConnectorOperationFailure(
                code=ConnectorFailureCode.AUTH_REQUIRED,
                detail_code="GITHUB_ACCOUNT_NOT_CONNECTED",
            )
        return handler(
            ListRepositoriesQuery(calculate_session_digest(session_token), account_id, cursor)
        )
    except ConnectorOperationFailure as error:
        logger.warning(
            "github_repository_listing_failed code=%s request_id=%s",
            error.detail_code,
            request.state.request_id,
            extra={
                "request_id": request.state.request_id,
                "detail_code": error.detail_code,
                "connector_id": "github",
                "failure_code": error.code.value,
            },
        )
        _raise_connector_failure(error, request_id=request.state.request_id)


@router.post(
    "/{connector_name}/start",
    response_model=AuthorizationStartV1,
    response_model_exclude_none=True,
    response_model_exclude_defaults=True,
)
def start_google_oauth(
    connector_name: str,
    payload: StartAuthorizationRequestV1,
    request: Request,
    dependencies: GoogleRouteDependency,
    x_api_contract_version: str | None = Header(default=None),
) -> AuthorizationStartV1:
    enforce_access(request, policy=EndpointPolicy.API_SESSION_REQUIRED)
    enforce_supported_api_contract_version(
        supported_version=dependencies.api_contract_version,
        request_id=request.state.request_id,
        request_version=x_api_contract_version,
    )
    connection = _resolve_connector(dependencies, connector_name, request.state.request_id)
    handler = connection.start_authorization_handler
    if not isinstance(handler, StartAuthorizationHandler):
        raise ApiRequestError(
            error_code="SERVICE_BUSY",
            user_message="The connector OAuth provider is not configured.",
            status_code=503,
            request_id=request.state.request_id,
            detail_code="CONNECTOR_OAUTH_UNAVAILABLE",
        )
    try:
        started = handler(
            StartAuthorizationCommand(
                command_id=payload.command_id,
                connector_id=connection.connector_id,
                environment=dependencies.oauth_environment,
                requested_scopes=connection.requested_scopes,
            )
        ).authorization
    except (OperationalCommandConflict, OperationalCommandUncertain) as error:
        _raise_operational_failure(error, request_id=request.state.request_id)
    except ConnectorOperationFailure as error:
        _raise_connector_failure(error, request_id=request.state.request_id)
    return AuthorizationStartV1(
        schema_version=started.schema_version,
        authorization_url=started.authorization_url,
        callback_id=started.callback_id,
        flow_kind=started.flow_kind,
        verification_uri=started.verification_uri,
        user_code=started.user_code,
        expires_at_ms=started.expires_at_ms,
        poll_interval_seconds=started.poll_interval_seconds,
    )


@router.get("/{connector_name}/status", response_model=ConnectionMetadataV1)
def get_google_connection(
    connector_name: str,
    request: Request,
    dependencies: GoogleRouteDependency,
    x_api_contract_version: str | None = Header(default=None),
) -> ConnectionMetadataV1:
    enforce_access(request, policy=EndpointPolicy.API_SESSION_REQUIRED)
    enforce_supported_api_contract_version(
        supported_version=dependencies.api_contract_version,
        request_id=request.state.request_id,
        request_version=x_api_contract_version,
    )
    connection = _resolve_connector(dependencies, connector_name, request.state.request_id)
    handler = connection.get_connection_status_handler
    if not isinstance(handler, GetConnectionStatusHandler):
        raise ApiRequestError(
            error_code="SERVICE_BUSY",
            user_message="The connector connection provider is not configured.",
            status_code=503,
            request_id=request.state.request_id,
            detail_code="CONNECTOR_CONNECTION_UNAVAILABLE",
        )
    try:
        result = handler(GetConnectionStatusQuery(connector_id=connection.connector_id)).connection
    except ConnectorOperationFailure as error:
        _raise_connector_failure(error, request_id=request.state.request_id)
    return ConnectionMetadataV1(
        schema_version=result.schema_version,
        connector_id=result.connector_id,
        account_id=result.account_id,
        display_email=result.display_email,
        connection_status=result.connection_status,
        granted_scopes=list(result.granted_scopes),
        missing_required_scopes=list(result.missing_required_scopes),
        authorization_status=result.authorization_status,
        detail_code=result.detail_code,
    )


@router.post("/{connector_name}/disconnect", response_model=RevokeResultV1)
def disconnect_google(
    connector_name: str,
    payload: RevokeConnectionRequestV1,
    request: Request,
    dependencies: GoogleRouteDependency,
    x_api_contract_version: str | None = Header(default=None),
) -> RevokeResultV1:
    enforce_access(request, policy=EndpointPolicy.API_SESSION_REQUIRED)
    enforce_supported_api_contract_version(
        supported_version=dependencies.api_contract_version,
        request_id=request.state.request_id,
        request_version=x_api_contract_version,
    )
    connection = _resolve_connector(dependencies, connector_name, request.state.request_id)
    handler = connection.revoke_connection_handler
    if not isinstance(handler, RevokeConnectionHandler):
        raise ApiRequestError(
            error_code="SERVICE_BUSY",
            user_message="The connector disconnect provider is not configured.",
            status_code=503,
            request_id=request.state.request_id,
            detail_code="CONNECTOR_DISCONNECT_UNAVAILABLE",
        )
    try:
        account_id = connection.current_account_id()
        if account_id is None:
            raise ApiRequestError(
                error_code="CONFLICT",
                user_message="No connected account is available to disconnect.",
                status_code=409,
                request_id=request.state.request_id,
                detail_code="CONNECTOR_ACCOUNT_NOT_CONNECTED",
            )
        result = handler(
            RevokeConnectionCommand(
                command_id=payload.command_id,
                connector_id=connection.connector_id,
                account_id=account_id,
            )
        ).revocation
    except (OperationalCommandConflict, OperationalCommandUncertain) as error:
        _raise_operational_failure(error, request_id=request.state.request_id)
    except ConnectorOperationFailure as error:
        _raise_connector_failure(error, request_id=request.state.request_id)
    return RevokeResultV1(
        schema_version=result.schema_version,
        revocation_attempted=result.revocation_attempted,
        local_credential_deleted=result.local_credential_deleted,
        connection_status=result.connection_status,
    )


def _raise_operational_failure(
    error: OperationalCommandConflict | OperationalCommandUncertain,
    *,
    request_id: str,
) -> None:
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
        detail_code=("OPERATION_COMMAND_CONFLICT" if conflict else "OPERATION_RESULT_UNCERTAIN"),
    ) from error


def _raise_connector_failure(error: ConnectorOperationFailure, *, request_id: str) -> NoReturn:
    if error.code is ConnectorFailureCode.CONFIGURATION_ERROR:
        if error.detail_code == "GOOGLE_OAUTH_CLIENT_ID_MISSING":
            user_message = "The connector OAuth client ID is not configured."
        else:
            user_message = "The connector configuration is invalid."
        raise ApiRequestError(
            error_code="CONFIGURATION_ERROR",
            user_message=user_message,
            status_code=503,
            request_id=request_id,
            retryable=False,
            detail_code=error.detail_code,
        ) from error

    mapping = {
        ConnectorFailureCode.INVALID_ARGUMENT: ("INVALID_ARGUMENT", 422),
        ConnectorFailureCode.AUTH_REQUIRED: ("AUTH_REQUIRED", 401),
        ConnectorFailureCode.PERMISSION_DENIED: ("PERMISSION_DENIED", 403),
        ConnectorFailureCode.NOT_FOUND: ("NOT_FOUND", 404),
        ConnectorFailureCode.RATE_LIMITED: ("UPSTREAM_UNAVAILABLE", 429),
        ConnectorFailureCode.UPSTREAM_UNAVAILABLE: ("UPSTREAM_UNAVAILABLE", 502),
        ConnectorFailureCode.TIMEOUT: ("UPSTREAM_UNAVAILABLE", 504),
        ConnectorFailureCode.CONNECTION_UNAVAILABLE: ("SERVICE_BUSY", 503),
        ConnectorFailureCode.MALFORMED_RESPONSE: ("UPSTREAM_UNAVAILABLE", 502),
    }
    error_code, status_code = mapping.get(error.code, ("UPSTREAM_UNAVAILABLE", 502))
    raise ApiRequestError(
        error_code=error_code,
        user_message="The connector request could not be completed.",
        status_code=status_code,
        request_id=request_id,
        retryable=error.retryable,
        detail_code=error.detail_code,
    ) from error


def _resolve_connector(
    dependencies: GoogleRouteDependency,
    connector_name: str,
    request_id: str,
) -> ConnectorConnectionDependencies:
    try:
        return dependencies.resolve(connector_name)
    except LookupError as error:
        raise ApiRequestError(
            error_code="NOT_FOUND",
            user_message="The requested connector is not installed.",
            status_code=404,
            request_id=request_id,
            detail_code="CONNECTOR_NOT_INSTALLED",
        ) from error
