"""Unit tests for WP3 UNKNOWN_RESULT recovery: fingerprint embedding + search."""

from __future__ import annotations

from typing import cast

import pytest
from tests.support.claim_context import sign_claim_context

from google_work_agent.adapters.connectors.google.workspace.mcp_server import (
    credential_provider as server,
)
from google_work_agent.adapters.connectors.google.workspace.mcp_server import (
    entrypoint as verified_server,
)
from google_work_agent.adapters.connectors.google.workspace.mcp_server.credential_provider import (
    GoogleOAuthSettings,
)
from google_work_agent.domain.canonical import calculate_canonical_json_hash

SESSION_KEY = "22" * 32
SERVICE_INSTANCE_ID = "svc-recovery-1"


def _state() -> server.GoogleWorkspaceCredentialProvider:
    state = server.GoogleWorkspaceCredentialProvider(keyring=_MemorySecretStorePort())
    state.oauth_settings = GoogleOAuthSettings(
        google_oauth_client_id="desktop-client",
    )
    state.session_key = SESSION_KEY
    state.service_instance_id = SERVICE_INSTANCE_ID
    return state


class _MemorySecretStorePort:
    def put(self, key: str, secret_bytes: bytes) -> None:
        del key, secret_bytes

    def get(self, key: str) -> bytes | None:
        del key
        return None

    def delete(self, key: str) -> None:
        del key


def _build_claim(
    *,
    state: server.GoogleWorkspaceCredentialProvider,
    tool_name: str,
    execution_arguments: dict[str, object],
) -> dict[str, object]:
    issued_at_ms = server._now_ms()
    claim: dict[str, object] = {
        "claim_version": 2,
        "action_id": "action-1",
        "approval_id": "approval-1",
        "execution_attempt_id": "attempt-1",
        "tool_name": tool_name,
        "connector_id": "google_workspace",
        "approval_arguments_hash": calculate_canonical_json_hash(execution_arguments),
        "execution_arguments_hash": calculate_canonical_json_hash(execution_arguments),
        "service_instance_id": state.service_instance_id,
        "mcp_process_instance_id": state.process_instance_id,
        "issued_at_ms": issued_at_ms,
        "expires_at_ms": issued_at_ms + 30_000,
        "nonce": "nonce-recovery-1",
    }
    session_key = state.session_key
    assert session_key is not None
    claim["signature"] = sign_claim_context(session_key, claim)
    return claim


# --------------------------------------------------------------------------
# Marker embedding at CREATE / SEND time
# --------------------------------------------------------------------------


def test_gmail_create__draft_embeds_recovery__marker_in_body(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    def google_api_call(
        _state: server.GoogleWorkspaceCredentialProvider,
        method: str,
        url: str,
        *,
        params: dict[str, str] | None = None,
        body: dict[str, object] | None = None,
    ) -> dict[str, object]:
        captured["body"] = body
        return {"id": "draft-1", "message": {"id": "msg-1", "threadId": "thread-1"}}

    monkeypatch.setattr(server, "_google_api_call", google_api_call)
    state = _state()
    payload: dict[str, object] = {
        "to": ["a@example.com"],
        "subject": "Hi",
        "body": "Body text",
        "recovery_fingerprint": "fp-create-1",
    }
    claim = _build_claim(
        state=state, tool_name="gmail_create_draft", execution_arguments={"payload": payload}
    )

    verified_server._tool_call(
        state,
        tool_name="gmail_create_draft",
        arguments={"payload": payload, "claim_context": claim},
    )

    body = cast(dict[str, object], captured["body"])
    message = cast(dict[str, object], body["message"])
    raw_bytes = server._b64url_decode(cast(str, message["raw"]))
    assert server._recovery_marker("fp-create-1").encode("utf-8") in raw_bytes


def test_gmail_update__draft_never__embeds_a_marker(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    def google_api_call(
        _state: server.GoogleWorkspaceCredentialProvider,
        method: str,
        url: str,
        *,
        params: dict[str, str] | None = None,
        body: dict[str, object] | None = None,
    ) -> dict[str, object]:
        captured["body"] = body
        return {"id": "draft-1", "message": {"id": "msg-1", "threadId": "thread-1"}}

    monkeypatch.setattr(server, "_google_api_call", google_api_call)
    state = _state()
    payload: dict[str, object] = {"to": ["a@example.com"], "subject": "Hi", "body": "Body text"}
    payload.update(cc=[], bcc=[], attachments=[], thread_id=None, in_reply_to=None, references=None)
    claim = _build_claim(
        state=state,
        tool_name="gmail_update_draft",
        execution_arguments={"draft_id": "draft-1", "payload": payload},
    )

    verified_server._tool_call(
        state,
        tool_name="gmail_update_draft",
        arguments={"draft_id": "draft-1", "payload": payload, "claim_context": claim},
    )

    body = cast(dict[str, object], captured["body"])
    message = cast(dict[str, object], body["message"])
    raw_bytes = server._b64url_decode(cast(str, message["raw"]))
    assert server.RECOVERY_MARKER_PREFIX.encode("utf-8") not in raw_bytes


def test_tasks_create__task_embeds_recovery__marker_in_notes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    def google_api_call(
        _state: server.GoogleWorkspaceCredentialProvider,
        method: str,
        url: str,
        *,
        params: dict[str, str] | None = None,
        body: dict[str, object] | None = None,
    ) -> dict[str, object]:
        captured["body"] = body
        return {"id": "task-1", "title": "Follow up"}

    monkeypatch.setattr(server, "_google_api_call", google_api_call)
    state = _state()
    payload: dict[str, object] = {
        "title": "Follow up",
        "notes": "Call customer",
        "recovery_fingerprint": "fp-task-1",
    }
    claim = _build_claim(
        state=state,
        tool_name="tasks_create_task",
        execution_arguments={"task_list_id": "list-1", "payload": payload},
    )

    verified_server._tool_call(
        state,
        tool_name="tasks_create_task",
        arguments={"task_list_id": "list-1", "payload": payload, "claim_context": claim},
    )

    body = cast(dict[str, object], captured["body"])
    notes = cast(str, body["notes"])
    assert notes.startswith("Call customer")
    assert server._recovery_marker("fp-task-1") in notes


def test_calendar_create__event_embeds_recovery__marker_in_description(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    def google_api_call(
        _state: server.GoogleWorkspaceCredentialProvider,
        method: str,
        url: str,
        *,
        params: dict[str, str] | None = None,
        body: dict[str, object] | None = None,
    ) -> dict[str, object]:
        captured["body"] = body
        return {"id": "event-1", "summary": "Review"}

    monkeypatch.setattr(server, "_google_api_call", google_api_call)
    state = _state()
    payload: dict[str, object] = {
        "title": "Review",
        "start": "2026-08-10T09:00:00+09:00",
        "end": "2026-08-10T10:00:00+09:00",
        "recovery_fingerprint": "fp-event-1",
    }
    claim = _build_claim(
        state=state,
        tool_name="calendar_create_event",
        execution_arguments={"calendar_id": "primary", "payload": payload},
    )

    verified_server._tool_call(
        state,
        tool_name="calendar_create_event",
        arguments={"calendar_id": "primary", "payload": payload, "claim_context": claim},
    )

    body = cast(dict[str, object], captured["body"])
    assert server._recovery_marker("fp-event-1") in cast(str, body["description"])


@pytest.mark.parametrize("draft_id", [None, "draft-1"])
@pytest.mark.parametrize("fingerprint", [None, "fp-send-1"])
def test_gmail_send__dispatches_approved_mime__without_hidden_draft_write(
    monkeypatch: pytest.MonkeyPatch, draft_id: str | None, fingerprint: str | None,
) -> None:
    from email import policy
    from email.parser import BytesParser

    calls: list[str] = []
    payload: dict[str, object] = {
        "to": ["a@example.com"], "cc": ["c@example.com"], "bcc": ["b@example.com"],
        "subject": "Hi", "body": "Original body",
        "recovery_fingerprint": fingerprint,
    }

    def unexpected(*args: object, **kwargs: object) -> dict[str, object]:
        pytest.fail("SEND must not perform a separate Draft UPDATE")

    def send(
        state: server.GoogleWorkspaceCredentialProvider, url: str, body: dict[str, object],
    ) -> dict[str, object]:
        calls.append(url)
        message = body if draft_id is None else cast(dict[str, object], body["message"])
        parsed = BytesParser(policy=policy.default).parsebytes(
            server._b64url_decode(cast(str, message["raw"]))
        )
        assert parsed["To"] == "a@example.com"
        assert parsed["Cc"] == "c@example.com"
        assert parsed["Bcc"] == "b@example.com"
        assert parsed["Subject"] == "Hi"
        assert "Original body" in parsed.get_content()
        if fingerprint:
            assert server._recovery_marker(fingerprint) in parsed.get_content()
        else:
            assert server.RECOVERY_MARKER_PREFIX not in parsed.get_content()
        return {"id": "sent-1", "threadId": "thread-1"}

    monkeypatch.setattr(server, "_google_api_call", unexpected)
    monkeypatch.setattr(server, "_google_api_post", send)
    state = _state()
    arguments: dict[str, object] = {"payload": payload}
    if draft_id:
        arguments["draft_id"] = draft_id
    claim = _build_claim(state=state, tool_name="gmail_send", execution_arguments=arguments)
    verified_server._tool_call(state, tool_name="gmail_send",
                               arguments={**arguments, "claim_context": claim})
    endpoint = "drafts/send" if draft_id else "messages/send"
    assert calls == [f"https://gmail.googleapis.com/gmail/v1/users/me/{endpoint}"]


# --------------------------------------------------------------------------
# search_by_recovery_fingerprint
# --------------------------------------------------------------------------


def test_search_gmail_draft__returns_full_snapshot__for_a_single_match(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    responses = [
        {"drafts": [{"id": "draft-1"}]},
        {
            "id": "draft-1",
            "message": {
                "id": "msg-1",
                "threadId": "thread-1",
                "payload": {"headers": [{"name": "Subject", "value": "Hi"}]},
            },
        },
    ]

    def google_api(
        _state: server.GoogleWorkspaceCredentialProvider,
        url: str,
        params: dict[str, str] | None = None,
    ) -> dict[str, object]:
        return cast(dict[str, object], responses.pop(0))

    monkeypatch.setattr(server, "_google_api", google_api)
    result = verified_server._tool_call(
        _state(),
        tool_name="search_by_recovery_fingerprint",
        arguments={"resource_type": "gmail_draft", "recovery_fingerprint": "fp-1"},
    )
    items = cast(list[dict[str, object]], result["items"])
    assert len(items) == 1
    assert items[0]["resource_id"] == "draft-1"


def test_search_gmail_draft__returns_no_candidates__when_zero_matches(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(server, "_google_api", lambda *a, **k: {"drafts": []})
    result = verified_server._tool_call(
        _state(),
        tool_name="search_by_recovery_fingerprint",
        arguments={"resource_type": "gmail_draft", "recovery_fingerprint": "fp-missing"},
    )
    assert result["items"] == []


def test_search_gmail__draft_returns_all__candidates_when_ambiguous(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        server, "_google_api", lambda *a, **k: {"drafts": [{"id": "d1"}, {"id": "d2"}]}
    )
    result = verified_server._tool_call(
        _state(),
        tool_name="search_by_recovery_fingerprint",
        arguments={"resource_type": "gmail_draft", "recovery_fingerprint": "fp-dup"},
    )
    items = cast(list[dict[str, object]], result["items"])
    assert {item["resource_id"] for item in items} == {"d1", "d2"}


def test_search_gmail_message__returns_full_snapshot__for_a_single_match(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    responses = [
        {"messages": [{"id": "msg-1"}]},
        {
            "id": "msg-1",
            "threadId": "thread-1",
            "historyId": "5",
            "labelIds": ["SENT"],
            "payload": {
                "headers": [{"name": "Subject", "value": "Sent"}], "mimeType": "text/plain",
                "body": {"data": server._b64url_encode(
                    server._recovery_marker("fp-send-1").encode()
                )},
            },
        },
    ]

    def google_api(
        _state: server.GoogleWorkspaceCredentialProvider,
        url: str,
        params: dict[str, str] | None = None,
    ) -> dict[str, object]:
        return cast(dict[str, object], responses.pop(0))

    monkeypatch.setattr(server, "_google_api", google_api)
    result = verified_server._tool_call(
        _state(),
        tool_name="search_by_recovery_fingerprint",
        arguments={"resource_type": "gmail_message", "recovery_fingerprint": "fp-send-1"},
    )
    items = cast(list[dict[str, object]], result["items"])
    assert items[0]["resource_id"] == "msg-1"
    assert cast(dict[str, object], items[0]["payload"])["subject"] == "Sent"
    assert cast(dict[str, object], items[0]["payload"])["sent"] is True


def test_search_tasks__uses_bound_list__and_filters_by_marker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    marker = server._recovery_marker("fp-task-1")
    responses: dict[str, dict[str, object]] = {
        "https://tasks.googleapis.com/tasks/v1/lists/list-1/tasks": {
            "items": [
                {"id": "task-1", "title": "Match", "notes": f"context\n\n{marker}"},
                {"id": "task-2", "title": "No match", "notes": "unrelated"},
            ]
        },
    }

    def google_api(
        _state: server.GoogleWorkspaceCredentialProvider,
        url: str,
        params: dict[str, str] | None = None,
    ) -> dict[str, object]:
        return responses[url]

    monkeypatch.setattr(server, "_google_api", google_api)
    result = verified_server._tool_call(
        _state(),
        tool_name="search_by_recovery_fingerprint",
        arguments={
            "resource_type": "task",
            "recovery_fingerprint": "fp-task-1",
            "task_list_id": "list-1",
        },
    )
    items = cast(list[dict[str, object]], result["items"])
    assert len(items) == 1
    assert items[0]["resource_id"] == "task-1"
    assert items[0]["parent_id"] == "list-1"


def test_search_calendar_events__uses_bound_calendar__with_query(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    responses: dict[str, dict[str, object]] = {
        "https://www.googleapis.com/calendar/v3/calendars/primary/events": {
            "items": [{"id": "event-1", "summary": "Review"}]
        },
    }

    def google_api(
        _state: server.GoogleWorkspaceCredentialProvider,
        url: str,
        params: dict[str, str] | None = None,
    ) -> dict[str, object]:
        if url.endswith("/events"):
            assert params is not None and "q" in params
        return responses[url]

    monkeypatch.setattr(server, "_google_api", google_api)
    result = verified_server._tool_call(
        _state(),
        tool_name="search_by_recovery_fingerprint",
        arguments={
            "resource_type": "calendar_event",
            "recovery_fingerprint": "fp-event-1",
            "calendar_id": "primary",
        },
    )
    items = cast(list[dict[str, object]], result["items"])
    assert len(items) == 1
    assert items[0]["resource_id"] == "event-1"
    assert items[0]["parent_id"] == "primary"


def test_search_by__recovery_fingerprint_rejects__unknown_resource_type(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(server, "_google_api", lambda *a, **k: pytest.fail("must not call Google"))
    with pytest.raises(server._WorkspaceToolError) as exc_info:
        verified_server._tool_call(
            _state(),
            tool_name="search_by_recovery_fingerprint",
            arguments={"resource_type": "task_list", "recovery_fingerprint": "fp-1"},
        )
    assert exc_info.value.safe_code == "INVALID_ARGUMENT"
