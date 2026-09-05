"""Connector-aware connection route dependency contract and provider."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Request

from google_work_agent.api.dependencies.request_context import get_api_container
from google_work_agent.application.use_cases.connection.get_connection_status import (
    GetConnectionStatusHandler,
)
from google_work_agent.application.use_cases.connection.revoke_connection import (
    RevokeConnectionHandler,
)
from google_work_agent.application.use_cases.connection.start_authorization import (
    StartAuthorizationHandler,
)
from google_work_agent.ports.connector.oauth_credential_port import OAuthEnvironment


@dataclass(frozen=True, slots=True)
class GoogleRouteDependencies:
    api_contract_version: str
    start_authorization_handler: StartAuthorizationHandler | None
    get_connection_status_handler: GetConnectionStatusHandler | None
    revoke_connection_handler: RevokeConnectionHandler | None
    connector_id: str
    oauth_environment: OAuthEnvironment
    requested_scopes: tuple[str, ...]
    current_account_id: Callable[[], str | None]
    connector_ids: dict[str, str]
    start_handlers: dict[str, StartAuthorizationHandler]
    status_handlers: dict[str, GetConnectionStatusHandler]
    revoke_handlers: dict[str, RevokeConnectionHandler]
    requested_scopes_by_connector: dict[str, tuple[str, ...]]
    current_account_ids: dict[str, Callable[[], str | None]]

    def resolve(self, connector_name: str) -> ConnectorConnectionDependencies:
        connector_id = self.connector_ids.get(connector_name)
        if connector_id is None:
            raise LookupError(connector_name)
        return ConnectorConnectionDependencies(
            connector_id=connector_id,
            start_authorization_handler=self.start_handlers.get(connector_id),
            get_connection_status_handler=self.status_handlers.get(connector_id),
            revoke_connection_handler=self.revoke_handlers.get(connector_id),
            requested_scopes=self.requested_scopes_by_connector.get(connector_id, ()),
            current_account_id=self.current_account_ids.get(connector_id, lambda: None),
        )


@dataclass(frozen=True, slots=True)
class ConnectorConnectionDependencies:
    connector_id: str
    start_authorization_handler: StartAuthorizationHandler | None
    get_connection_status_handler: GetConnectionStatusHandler | None
    revoke_connection_handler: RevokeConnectionHandler | None
    requested_scopes: tuple[str, ...]
    current_account_id: Callable[[], str | None]


def get_google_route_dependencies(request: Request) -> GoogleRouteDependencies:
    container = get_api_container(request)
    connector_ids = container.connection_connector_ids or {"google": container.resource_connector_id}
    return GoogleRouteDependencies(
        api_contract_version=container.api_contract_version,
        start_authorization_handler=container.start_authorization_handler,
        get_connection_status_handler=container.get_connection_status_handler,
        revoke_connection_handler=container.revoke_connection_handler,
        connector_id=container.resource_connector_id,
        oauth_environment=container.oauth_environment,
        requested_scopes=container.oauth_requested_scopes,
        current_account_id=container.current_account_id_provider,
        connector_ids=connector_ids,
        start_handlers=container.start_authorization_handlers_by_connector or {container.resource_connector_id: container.start_authorization_handler},
        status_handlers=container.get_connection_status_handlers_by_connector or {container.resource_connector_id: container.get_connection_status_handler},
        revoke_handlers=container.revoke_connection_handlers_by_connector or {container.resource_connector_id: container.revoke_connection_handler},
        requested_scopes_by_connector=container.oauth_requested_scopes_by_connector or {container.resource_connector_id: container.oauth_requested_scopes},
        current_account_ids=container.current_account_id_providers_by_connector or {container.resource_connector_id: container.current_account_id_provider},
    )


GoogleRouteDependency = Annotated[
    GoogleRouteDependencies,
    Depends(get_google_route_dependencies),
]
