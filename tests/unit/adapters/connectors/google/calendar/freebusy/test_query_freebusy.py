from typing import Any

import pytest

from google_work_agent.adapters.connectors.google.calendar.freebusy.query_freebusy import (
    QueryFreebusyOperation,
)
from google_work_agent.adapters.connectors.google.workspace.mcp_server import credential_provider


@pytest.fixture(autouse=True)
def oauth_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GOOGLE_OAUTH_ENV", "DEVELOPMENT")


@pytest.mark.parametrize(
    "response",
    [
        {},
        {"calendars": {}},
        {"calendars": {"primary": {}}},
        {"calendars": {"primary": {"busy": [], "errors": [{"reason": "notFound"}]}}},
        {"calendars": {"primary": {"busy": [], "errors": [{"reason": "internalError"}]}}},
        {"calendars": {"primary": {"busy": [], "errors": [{"reason": "newProviderError"}]}}},
        {"calendars": {"primary": {"busy": [None]}}},
    ],
)
def test_query_freebusy__failed_or_missing_calendar__never_returns_empty_success(
    monkeypatch: pytest.MonkeyPatch,
    response: dict[str, Any],
) -> None:
    monkeypatch.setattr(credential_provider, "_google_api_post", lambda *_: response)
    with pytest.raises(credential_provider._WorkspaceToolError):
        QueryFreebusyOperation().execute(
            credential_provider.GoogleWorkspaceCredentialProvider(),
            {
                "calendar_ids": ["primary"],
                "time_min": "2026-09-10T10:00:00+09:00",
                "time_max": "2026-09-10T11:00:00+09:00",
            },
        )


def test_query_freebusy__explicit_empty_busy__is_success(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        credential_provider,
        "_google_api_post",
        lambda *_: {
            "calendars": {"primary": {"busy": []}},
        },
    )
    assert QueryFreebusyOperation().execute(
        credential_provider.GoogleWorkspaceCredentialProvider(),
        {
            "calendar_ids": ["primary"],
            "time_min": "2026-09-10T10:00:00+09:00",
            "time_max": "2026-09-10T11:00:00+09:00",
        },
    ) == {"calendars": [{"calendar_id": "primary", "intervals": []}]}
