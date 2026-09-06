from dataclasses import replace
from typing import cast
from unittest.mock import Mock

import pytest

from google_work_agent.application.use_cases.connection.check_connector_prerequisites import (
    CheckConnectorPrerequisitesHandler,
    CheckConnectorPrerequisitesQuery,
)
from google_work_agent.ports.connector.connector_failure import (
    ConnectorFailureCode,
    ConnectorOperationFailure,
)
from google_work_agent.ports.connector.oauth_credential_port import (
    OAuthConnectionMetadata,
    OAuthCredentialPort,
)


@pytest.mark.parametrize(
    "connector_id,label",
    [
        ("google_workspace", "Google Workspace"),
        ("github", "GitHub"),
    ],
)
@pytest.mark.parametrize(
    "status",
    [
        "DISCONNECTED",
        "CONNECTING",
        "REAUTH_REQUIRED",
        "UNAVAILABLE",
        "CONNECTED",
    ],
)
def test_initial_prerequisite__checks_only_requested__connector(connector_id, label, status):
    port = Mock(spec=OAuthCredentialPort)
    port.get_connection_status.return_value = OAuthConnectionMetadata(
        1,
        connector_id,
        "account-1" if status == "CONNECTED" else None,
        None,
        status,
        (),
        (),
    )
    unused = Mock(spec=OAuthCredentialPort)
    handler = CheckConnectorPrerequisitesHandler(
        {
            connector_id: (label, port),
            "unused": ("Unused", unused),
        }
    )
    result = handler(CheckConnectorPrerequisitesQuery((connector_id, connector_id)))
    port.get_connection_status.assert_called_once_with(connector_id)
    unused.get_connection_status.assert_not_called()
    if status == "CONNECTED":
        assert result.user_message is None
        assert result.admitted_connector_ids == (connector_id,)
    else:
        assert label in result.user_message
        assert "다시 보내" in result.user_message
        assert "자동으로 재개되지는 않습니다" in result.user_message
        assert result.admitted_connector_ids == ()


def test_admitted_connector__does_not_reclassify__midrun_expiry():
    port = Mock(spec=OAuthCredentialPort)
    port.get_connection_status.side_effect = AssertionError("already admitted")
    result = CheckConnectorPrerequisitesHandler({"github": ("GitHub", port)})(
        CheckConnectorPrerequisitesQuery(("github",), ("github",))
    )
    assert result.user_message is None
    port.get_connection_status.assert_not_called()


@pytest.mark.parametrize("missing_identity", [False, True])
def test_connected_without__identity_or_scope__fails_closed(missing_identity):
    port = Mock(spec=OAuthCredentialPort)
    connection = OAuthConnectionMetadata(1, "github", "account", None, "CONNECTED", (), ())
    port.get_connection_status.return_value = (
        replace(connection, account_id=None)
        if missing_identity
        else replace(connection, missing_required_scopes=("issues",))
    )
    result = CheckConnectorPrerequisitesHandler({"github": ("GitHub", port)})(
        CheckConnectorPrerequisitesQuery(("github",))
    )
    assert result.user_message is not None
    assert result.admitted_connector_ids == ()


def test_connection_failure__omits_provider_secrets__and_does_not_retry():
    port = Mock(spec=OAuthCredentialPort)
    port.get_connection_status.side_effect = ConnectorOperationFailure(
        ConnectorFailureCode.CONFIGURATION_ERROR,
        "secret-detail",
    )
    handler = CheckConnectorPrerequisitesHandler({"github": ("GitHub", port)})
    result = handler(CheckConnectorPrerequisitesQuery(("github",)))
    assert "secret-detail" not in cast(str, result.user_message)
    port.get_connection_status.assert_called_once()


def test_no_connector__does_not_require__any_credentials():
    result = CheckConnectorPrerequisitesHandler({})(CheckConnectorPrerequisitesQuery(()))
    assert result.user_message is None


def test_unregistered_connector__requires_setup__without_raw_id():
    result = CheckConnectorPrerequisitesHandler({})(CheckConnectorPrerequisitesQuery(("internal",)))
    assert result.user_message is not None
    assert "internal" not in result.user_message
