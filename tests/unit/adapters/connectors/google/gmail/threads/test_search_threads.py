from __future__ import annotations

import io
import json
import threading
import time
from email.message import Message
from http import HTTPStatus
from typing import cast
from urllib.error import HTTPError, URLError
from urllib.request import Request

import pytest

from google_work_agent.adapters.connectors.google.gmail.threads import search_threads
from google_work_agent.adapters.connectors.google.workspace.mcp_server import (
    credential_provider as workspace,
)
from google_work_agent.ports.connector.contracts.delivery_certainty import DeliveryCertainty


def test_production_hydration_config__uses_selected_b20w1__by_default() -> None:
    assert (
        search_threads.GmailMetadataHydrationConfig(
            transport="BATCH",
            batch_size=20,
            http_concurrency_limit=1,
        )
    ) == search_threads.GMAIL_METADATA_HYDRATION_CONFIG


@pytest.mark.parametrize("count", [0, 1, 20, 50, 51, 100])
def test_individual_hydration__for_synthetic_page_sizes__preserves_count_order_and_http_shape(
    monkeypatch: pytest.MonkeyPatch,
    count: int,
) -> None:
    thread_ids = [f"thread-{index}" for index in range(count)]
    calls: list[str] = []

    def google_api(
        _state: workspace.GoogleWorkspaceCredentialProvider,
        url: str,
        _params: object = None,
    ) -> dict[str, object]:
        calls.append(url)
        if url.endswith("/threads"):
            return {"threads": [{"id": thread_id} for thread_id in thread_ids]}
        thread_id = url.rsplit("/", 1)[-1]
        return _thread_payload(thread_id)

    monkeypatch.setattr(workspace, "_google_api", google_api)
    payload = search_threads._gmail_search_threads(
        _state(),
        {"query": "fixed", "page_size": min(100, max(1, count))},
        hydration_config=search_threads.GmailMetadataHydrationConfig(
            transport="INDIVIDUAL",
            batch_size=None,
            http_concurrency_limit=3,
        ),
    )

    assert [item["resource_id"] for item in cast(list[dict[str, object]], payload["items"])] == (
        thread_ids
    )
    assert len(calls) == 1 + count


@pytest.mark.parametrize("count", [0, 1, 20, 50, 51, 100])
def test_batch_hydration__for_synthetic_page_sizes__preserves_count_order_and_http_shape(
    monkeypatch: pytest.MonkeyPatch,
    count: int,
) -> None:
    thread_ids = [f"thread-{index}" for index in range(count)]
    batch_sizes: list[int] = []

    def google_api(
        _state: workspace.GoogleWorkspaceCredentialProvider,
        url: str,
        _params: object = None,
    ) -> dict[str, object]:
        if url.endswith("/threads"):
            return {"threads": [{"id": value} for value in thread_ids]}
        return _thread_payload(url.rsplit("/", 1)[-1])

    monkeypatch.setattr(workspace, "_google_api", google_api)

    def batch_get(
        _state: workspace.GoogleWorkspaceCredentialProvider,
        targets: tuple[str, ...],
    ) -> tuple[workspace._GoogleBatchGetResult, ...]:
        batch_sizes.append(len(targets))
        return tuple(
            workspace._GoogleBatchGetResult(
                ordinal=ordinal,
                status_code=200,
                response_body_bytes=100,
                payload=_thread_payload(f"thread-{sum(batch_sizes[:-1]) + ordinal}"),
            )
            for ordinal in range(len(targets))
        )

    monkeypatch.setattr(workspace, "_google_batch_get", batch_get)
    payload = search_threads._gmail_search_threads(
        _state(),
        {"query": "fixed", "page_size": min(100, max(1, count))},
        hydration_config=search_threads.GmailMetadataHydrationConfig(
            transport="BATCH",
            batch_size=20,
            http_concurrency_limit=1,
        ),
    )

    assert [item["resource_id"] for item in cast(list[dict[str, object]], payload["items"])] == (
        thread_ids
    )
    expected_batch_sizes = (
        [] if count <= 1 else [20] * (count // 20) + ([count % 20] if count % 20 else [])
    )
    assert batch_sizes == expected_batch_sizes


def test_metadata_disabled__never_dispatches_detail__or_batch_http(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0

    def google_api(*_args: object, **_kwargs: object) -> dict[str, object]:
        nonlocal calls
        calls += 1
        return {"threads": [{"id": "thread-1"}]}

    monkeypatch.setattr(workspace, "_google_api", google_api)
    monkeypatch.setattr(
        workspace,
        "_google_batch_get",
        lambda *_args, **_kwargs: pytest.fail("metadata-disabled must not batch"),
    )

    result = search_threads._gmail_search_threads(
        _state(),
        {"query": "fixed", "page_size": 20, "include_thread_metadata": False},
        hydration_config=search_threads.GmailMetadataHydrationConfig("BATCH", 20, 1),
    )

    assert calls == 1
    assert cast(list[dict[str, object]], result["items"])[0]["payload"] == {}


def test_one_way_hydration__does_not_create__executor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        workspace,
        "_google_api",
        lambda _state, url, _params=None: (
            {"threads": [{"id": "thread-1"}, {"id": "thread-2"}]}
            if url.endswith("/threads")
            else _thread_payload(url.rsplit("/", 1)[-1])
        ),
    )
    monkeypatch.setattr(
        search_threads,
        "ThreadPoolExecutor",
        lambda **_kwargs: pytest.fail("W=1 must execute on the calling thread"),
    )

    result = search_threads._gmail_search_threads(
        _state(),
        {"query": "fixed", "page_size": 20},
        hydration_config=search_threads.GmailMetadataHydrationConfig("INDIVIDUAL", None, 1),
    )

    assert len(cast(list[object], result["items"])) == 2


def test_bounded_hydration__never_exceeds_configured__http_concurrency(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    active = 0
    peak = 0
    lock = threading.Lock()

    monkeypatch.setattr(
        workspace,
        "_google_api",
        lambda *_args, **_kwargs: {"threads": [{"id": f"thread-{i}"} for i in range(20)]},
    )

    def metadata(**_kwargs: object) -> dict[str, object]:
        nonlocal active, peak
        with lock:
            active += 1
            peak = max(peak, active)
        time.sleep(0.005)
        with lock:
            active -= 1
        return {"subject": "safe"}

    monkeypatch.setattr(workspace, "_gmail_thread_list_metadata", metadata)
    search_threads._gmail_search_threads(
        _state(),
        {"query": "fixed", "page_size": 20},
        hydration_config=search_threads.GmailMetadataHydrationConfig("INDIVIDUAL", None, 5),
    )

    assert peak == 5


def test_second_batch_failure__fails_whole_page__without_individual_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0
    monkeypatch.setattr(
        workspace,
        "_google_api",
        lambda *_args, **_kwargs: {"threads": [{"id": f"thread-{i}"} for i in range(20)]},
    )

    def batch_get(
        _state: workspace.GoogleWorkspaceCredentialProvider,
        targets: tuple[str, ...],
    ) -> tuple[workspace._GoogleBatchGetResult, ...]:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise workspace._WorkspaceToolError("UPSTREAM_5XX")
        return tuple(
            workspace._GoogleBatchGetResult(i, 200, 100, _thread_payload(f"thread-{i}"))
            for i in range(len(targets))
        )

    monkeypatch.setattr(workspace, "_google_batch_get", batch_get)
    monkeypatch.setattr(
        workspace,
        "_gmail_thread_list_metadata",
        lambda **_kwargs: pytest.fail("batch failure must not fall back to individual GET"),
    )

    with pytest.raises(workspace._WorkspaceToolError, match="UPSTREAM_5XX"):
        search_threads._gmail_search_threads(
            _state(),
            {"query": "fixed", "page_size": 20},
            hydration_config=search_threads.GmailMetadataHydrationConfig("BATCH", 10, 1),
        )
    assert calls == 2


def test_google_batch_get__correlates_parts__and_preserves_request_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    response = _batch_response(
        [(1, 200, _thread_payload("thread-2")), (0, 200, _thread_payload("thread-1"))]
    )
    captured: list[Request] = []

    def urlopen(request: Request, timeout: float) -> _Response:
        del timeout
        captured.append(request)
        return response

    monkeypatch.setattr(workspace, "urlopen", urlopen)

    result = workspace._google_batch_get(
        _authorized_state(),
        (
            "/gmail/v1/users/me/threads/thread-1?format=metadata",
            "/gmail/v1/users/me/threads/thread-2?format=metadata",
        ),
    )

    assert [item.ordinal for item in result] == [0, 1]
    request_body = cast(bytes, captured[0].data)
    assert b"GET /gmail/v1/users/me/threads/thread-1?format=metadata HTTP/1.1" in request_body
    assert b"Authorization" not in request_body


@pytest.mark.parametrize(
    ("status_code", "error_body", "expected"),
    [
        (401, {}, "REAUTH_REQUIRED"),
        (403, {}, "PERMISSION_DENIED"),
        (403, {"error": {"errors": [{"reason": "userRateLimitExceeded"}]}}, "RATE_LIMITED"),
        (404, {}, "NOT_FOUND"),
        (429, {}, "RATE_LIMITED"),
        (500, {}, "UPSTREAM_5XX"),
    ],
)
def test_google_batch_get__maps_inner_errors__and_never_returns_partial_page(
    monkeypatch: pytest.MonkeyPatch,
    status_code: int,
    error_body: dict[str, object],
    expected: str,
) -> None:
    monkeypatch.setattr(
        workspace,
        "urlopen",
        lambda *_args, **_kwargs: _batch_response([(0, status_code, error_body)]),
    )

    with pytest.raises(workspace._WorkspaceToolError, match=expected):
        workspace._google_batch_get(
            _authorized_state(),
            ("/gmail/v1/users/me/threads/thread-1?format=metadata",),
        )


@pytest.mark.parametrize(
    ("status_code", "error_body", "expected"),
    [
        (401, {}, "REAUTH_REQUIRED"),
        (403, {}, "PERMISSION_DENIED"),
        (403, {"error": {"errors": [{"reason": "rateLimitExceeded"}]}}, "RATE_LIMITED"),
        (404, {}, "NOT_FOUND"),
        (429, {}, "RATE_LIMITED"),
        (503, {}, "UPSTREAM_5XX"),
    ],
)
def test_google_batch_get__maps_outer__errors(
    monkeypatch: pytest.MonkeyPatch,
    status_code: int,
    error_body: dict[str, object],
    expected: str,
) -> None:
    body = json.dumps(error_body).encode("utf-8")
    headers = Message()
    monkeypatch.setattr(
        workspace,
        "urlopen",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            HTTPError(
                "https://gmail.googleapis.com/batch",
                status_code,
                "error",
                headers,
                io.BytesIO(body),
            )
        ),
    )

    with pytest.raises(workspace._WorkspaceToolError, match=expected):
        workspace._google_batch_get(
            _authorized_state(),
            ("/gmail/v1/users/me/threads/thread-1?format=metadata",),
        )


@pytest.mark.parametrize(
    "fault",
    [
        "WRONG_CONTENT_TYPE",
        "MALFORMED_MIME",
        "MALFORMED_JSON",
        "MISSING",
        "DUPLICATE",
        "UNEXPECTED",
    ],
)
def test_google_batch_get__rejects_malformed__or_uncorrelated_parts(
    monkeypatch: pytest.MonkeyPatch,
    fault: str,
) -> None:
    if fault == "WRONG_CONTENT_TYPE":
        response = _Response(b"{}", content_type="application/json")
    elif fault == "MALFORMED_MIME":
        response = _Response(b"not-multipart", content_type="multipart/mixed; boundary=batch_x")
    elif fault == "MALFORMED_JSON":
        response = _batch_response([(0, 200, b"{")])
    elif fault == "MISSING":
        response = _batch_response([(0, 200, {})])
    elif fault == "DUPLICATE":
        response = _batch_response([(0, 200, {}), (0, 200, {})])
    else:
        response = _batch_response([(0, 200, {}), (2, 200, {})])
    monkeypatch.setattr(workspace, "urlopen", lambda *_args, **_kwargs: response)
    targets = (
        "/gmail/v1/users/me/threads/thread-1?format=metadata",
        "/gmail/v1/users/me/threads/thread-2?format=metadata",
    )

    with pytest.raises(workspace._WorkspaceToolError, match="INVALID_MCP_OUTPUT"):
        workspace._google_batch_get(_authorized_state(), targets)


def test_google_batch_get__rejects_oversized__outer_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(workspace, "GMAIL_BATCH_RESPONSE_MAX_BYTES", 10)
    monkeypatch.setattr(
        workspace,
        "urlopen",
        lambda *_args, **_kwargs: _Response(
            b"x" * 11,
            content_type="multipart/mixed; boundary=batch_x",
        ),
    )
    with pytest.raises(workspace._WorkspaceToolError, match="INVALID_MCP_OUTPUT"):
        workspace._google_batch_get(
            _authorized_state(),
            ("/gmail/v1/users/me/threads/thread-1?format=metadata",),
        )


@pytest.mark.parametrize(
    ("raised", "expected"),
    [(TimeoutError(), "TIMEOUT"), (URLError("offline"), "MCP_UNAVAILABLE")],
)
def test_google_batch_get__maps_transport__failure(
    monkeypatch: pytest.MonkeyPatch,
    raised: Exception,
    expected: str,
) -> None:
    monkeypatch.setattr(
        workspace,
        "urlopen",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(raised),
    )
    with pytest.raises(workspace._WorkspaceToolError, match=expected):
        workspace._google_batch_get(
            _authorized_state(),
            ("/gmail/v1/users/me/threads/thread-1?format=metadata",),
        )


def test_hydration_config__rejects_invalid__or_ambiguous_values() -> None:
    with pytest.raises(ValueError):
        search_threads.GmailMetadataHydrationConfig("INDIVIDUAL", 1, 1)
    with pytest.raises(ValueError):
        search_threads.GmailMetadataHydrationConfig("BATCH", None, 1)
    with pytest.raises(ValueError):
        search_threads.GmailMetadataHydrationConfig("BATCH", 51, 1)
    with pytest.raises(ValueError):
        search_threads.GmailMetadataHydrationConfig("BATCH", 20, 0)


def _thread_payload(thread_id: str) -> dict[str, object]:
    return {
        "snippet": f"Snippet {thread_id}",
        "messages": [
            {
                "internalDate": "1780000000000",
                "payload": {
                    "headers": [
                        {"name": "From", "value": "Sender <sender@example.com>"},
                        {"name": "Subject", "value": f"Subject {thread_id}"},
                        {"name": "Date", "value": "Mon, 7 Sep 2026 09:00:00 +0900"},
                    ]
                },
            }
        ],
    }


def _state() -> workspace.GoogleWorkspaceCredentialProvider:
    return workspace.GoogleWorkspaceCredentialProvider(keyring=_MemorySecretStore())


def _authorized_state() -> workspace.GoogleWorkspaceCredentialProvider:
    state = _state()
    state.access_token = "test-token"
    state.access_token_expires_at_ms = 2**63 - 1
    state.account_email = "test@example.com"
    state.account_id = "account"
    return state


class _MemorySecretStore:
    def put(self, key: str, secret_bytes: bytes) -> None:
        del key, secret_bytes

    def get(self, key: str) -> bytes | None:
        del key
        return None

    def delete(self, key: str) -> None:
        del key


class _Response:
    def __init__(
        self,
        body: bytes,
        *,
        content_type: str,
        status_code: int = 200,
    ) -> None:
        self._body = body
        self.status = status_code
        self.headers = Message()
        self.headers["Content-Type"] = content_type

    def read(self, amount: int = -1) -> bytes:
        return self._body if amount < 0 else self._body[:amount]

    def getcode(self) -> int:
        return self.status

    def __enter__(self) -> _Response:
        return self

    def __exit__(self, *_args: object) -> None:
        return None


def _batch_response(
    parts: list[tuple[int, int, dict[str, object] | bytes]],
) -> _Response:
    boundary = "batch_response"
    chunks: list[bytes] = []
    for ordinal, status_code, payload in parts:
        body = payload if isinstance(payload, bytes) else json.dumps(payload).encode("utf-8")
        reason = HTTPStatus(status_code).phrase
        chunks.append(
            (
                f"--{boundary}\r\n"
                "Content-Type: application/http\r\n"
                f"Content-ID: <response-item-{ordinal}>\r\n\r\n"
                f"HTTP/1.1 {status_code} {reason}\r\n"
                "Content-Type: application/json\r\n\r\n"
            ).encode("ascii")
            + body
            + b"\r\n"
        )
    chunks.append(f"--{boundary}--\r\n".encode("ascii"))
    return _Response(
        b"".join(chunks),
        content_type=f"multipart/mixed; boundary={boundary}",
    )


def test_batch_failure_certainty__is_may_have_been_sent__for_read_transport() -> None:
    error = workspace._WorkspaceToolError(
        "INVALID_MCP_OUTPUT",
        delivery_certainty=DeliveryCertainty.MAY_HAVE_BEEN_SENT,
    )
    assert error.delivery_certainty is DeliveryCertainty.MAY_HAVE_BEEN_SENT
