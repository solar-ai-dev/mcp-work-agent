"""Diagnostic MCP entrypoint with one immutable Gmail hydration configuration."""

from __future__ import annotations

import json
import os
import tempfile
import threading
import time
from pathlib import Path
from typing import NoReturn

from google_work_agent.adapters.connectors.google.gmail.threads import search_threads
from google_work_agent.adapters.connectors.google.workspace.mcp_server.composition import (
    compose_server_state,
)
from google_work_agent.adapters.connectors.google.workspace.mcp_server.entrypoint import run_server

CONFIG_ENVIRONMENT = "GWA_GMAIL_METADATA_BENCHMARK_CONFIG"
DEFAULT_CONFIG_PATH = Path(tempfile.gettempdir()) / "gwa-gmail-metadata-benchmark-config.json"


class _BufferedReadObserver:
    def __init__(self, event_path: Path) -> None:
        self._event_path = event_path
        self._lock = threading.Lock()
        self._operation_index = 0
        self._event_index = 0
        self._active_http: dict[int, tuple[int, int]] = {}
        self._events: list[dict[str, object]] = []
        self._in_flight = 0
        self._max_in_flight = 0

    def on_http_started(self, *, kind: str, method: str, inner_count: int | None) -> None:
        with self._lock:
            if kind == "GMAIL_THREADS_LIST":
                self._operation_index += 1
                self._event_index = 0
                self._events = []
                self._active_http = {}
                self._in_flight = 0
                self._max_in_flight = 0
            self._event_index += 1
            attempt_index = self._event_index
            self._active_http[threading.get_ident()] = (attempt_index, time.perf_counter_ns())
            self._in_flight += 1
            self._max_in_flight = max(self._max_in_flight, self._in_flight)
            self._events.append(
                {
                    "record_type": "HTTP_STARTED",
                    "operation_index": self._operation_index,
                    "attempt_index": attempt_index,
                    "kind": kind,
                    "method": method,
                    "inner_count": inner_count,
                    "in_flight": self._in_flight,
                }
            )

    def on_http_finished(
        self,
        *,
        kind: str,
        method: str,
        inner_count: int | None,
        status_code: int | None,
        response_body_bytes: int,
        duration_ms: float,
        safe_error_code: str | None,
    ) -> None:
        with self._lock:
            active = self._active_http.pop(threading.get_ident(), (0, 0))
            self._in_flight = max(0, self._in_flight - 1)
            self._events.append(
                {
                    "record_type": "HTTP_FINISHED",
                    "operation_index": self._operation_index,
                    "attempt_index": active[0],
                    "kind": kind,
                    "method": method,
                    "inner_count": inner_count,
                    "status_code": status_code,
                    "response_body_bytes": response_body_bytes,
                    "duration_ms": round(duration_ms, 4),
                    "safe_error_code": safe_error_code,
                    "in_flight_after": self._in_flight,
                }
            )

    def on_batch_part(
        self,
        *,
        ordinal: int,
        status_code: int | None,
        response_body_bytes: int,
        result_seen: bool,
        safe_error_code: str | None,
    ) -> None:
        with self._lock:
            self._events.append(
                {
                    "record_type": "BATCH_PART",
                    "operation_index": self._operation_index,
                    "ordinal": ordinal,
                    "status_code": status_code,
                    "response_body_bytes": response_body_bytes,
                    "result_seen": result_seen,
                    "safe_error_code": safe_error_code,
                }
            )

    def on_provider_payload(self, *, kind: str, message_count: int | None) -> None:
        if kind != "GMAIL_THREAD_GET":
            return
        with self._lock:
            self._events.append(
                {
                    "record_type": "PROVIDER_PAYLOAD",
                    "operation_index": self._operation_index,
                    "kind": kind,
                    "message_count": message_count,
                }
            )

    def on_phase_finished(self, *, phase: str, duration_ms: float, status: str) -> None:
        should_flush = False
        with self._lock:
            self._events.append(
                {
                    "record_type": "PHASE",
                    "operation_index": self._operation_index,
                    "phase": phase,
                    "duration_ms": round(duration_ms, 4),
                    "status": status,
                    "max_in_flight_http": self._max_in_flight,
                }
            )
            should_flush = phase == "PROJECTION" or status == "FAILED"
        if should_flush:
            self._flush()

    def _flush(self) -> None:
        with self._lock:
            events = self._events
            self._events = []
        if not events:
            return
        self._event_path.parent.mkdir(parents=True, exist_ok=True)
        with self._event_path.open("a", encoding="utf-8", newline="\n") as stream:
            for event in events:
                stream.write(json.dumps(event, sort_keys=True, separators=(",", ":")) + "\n")


def _load_config() -> tuple[search_threads.GmailMetadataHydrationConfig, Path]:
    config_path = Path(os.environ.get(CONFIG_ENVIRONMENT, str(DEFAULT_CONFIG_PATH))).resolve()
    payload = json.loads(config_path.read_text(encoding="utf-8"))
    event_path = Path(str(payload["event_path"])).resolve()
    config = search_threads.GmailMetadataHydrationConfig(
        transport=str(payload["transport"]),  # type: ignore[arg-type]
        batch_size=(int(payload["batch_size"]) if payload.get("batch_size") is not None else None),
        http_concurrency_limit=int(payload["http_concurrency_limit"]),
    )
    return config, event_path


def main() -> NoReturn:
    config, event_path = _load_config()
    observer = _BufferedReadObserver(event_path)
    search_threads.GMAIL_METADATA_HYDRATION_CONFIG = config

    def state_factory():  # type: ignore[no-untyped-def]
        state = compose_server_state()
        state.provider_read_observer = observer
        return state

    run_server(state_factory)
    raise SystemExit(0)


if __name__ == "__main__":
    main()
