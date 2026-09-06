"""Check initial request prerequisites without opening an authentication wait."""

import logging
from collections.abc import Mapping
from dataclasses import dataclass

from google_work_agent.application.tool_registry.signed_tool_registry import SignedToolRegistry
from google_work_agent.ports.connector.connector_failure import ConnectorOperationFailure
from google_work_agent.ports.connector.oauth_credential_port import OAuthCredentialPort

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class CheckConnectorPrerequisitesQuery:
    connector_ids: tuple[str, ...]
    admitted_connector_ids: tuple[str, ...] = ()
    run_id: str | None = None
    resource_types: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class CheckConnectorPrerequisitesResult:
    admitted_connector_ids: tuple[str, ...]
    user_message: str | None


class CheckConnectorPrerequisitesHandler:
    def __init__(
        self,
        connections: Mapping[str, tuple[str, OAuthCredentialPort]],
        *,
        tool_catalog: SignedToolRegistry | None = None,
    ) -> None:
        self._connections = dict(connections)
        self._resource_connectors = {
            (entry.resource_type.upper(), entry.connector_id)
            for entry in (() if tool_catalog is None else tool_catalog.entries)
        }

    def __call__(
        self, query: CheckConnectorPrerequisitesQuery
    ) -> CheckConnectorPrerequisitesResult:
        admitted = set(query.admitted_connector_ids)
        unavailable: list[str] = []
        requested = set(query.connector_ids) | {
            connector_id
            for resource_type, connector_id in self._resource_connectors
            if resource_type in query.resource_types
        }
        for connector_id in sorted(requested - admitted):
            binding = self._connections.get(connector_id)
            if binding is None:
                unavailable.append("요청에 필요한 외부 서비스")
                continue
            label, credentials = binding
            try:
                connection = credentials.get_connection_status(connector_id)
            except ConnectorOperationFailure as error:
                _LOGGER.warning(
                    "connector_prerequisite_unavailable run_id=%s connector_id=%s code=%s",
                    query.run_id,
                    connector_id,
                    error.code.value,
                )
                unavailable.append(label)
                continue
            if (
                connection.connection_status == "CONNECTED"
                and connection.account_id
                and not connection.missing_required_scopes
            ):
                admitted.add(connector_id)
            else:
                _LOGGER.info(
                    "connector_prerequisite_unmet run_id=%s connector_id=%s status=%s",
                    query.run_id,
                    connector_id,
                    connection.connection_status,
                )
                unavailable.append(label)
        message = None
        if unavailable:
            names = ", ".join(dict.fromkeys(unavailable))
            message = (
                f"{names} 연결과 필요한 접근 권한을 확인해야 합니다. "
                "연결이 필요한 작업을 진행할 수 없어 이번 요청을 종료했습니다. "
                "설정의 계정 및 연결에서 연결·접근 설정을 완료한 뒤 요청을 다시 보내주세요. "
                "연결 후 이 요청이 자동으로 재개되지는 않습니다."
            )
        return CheckConnectorPrerequisitesResult(tuple(sorted(admitted)), message)
