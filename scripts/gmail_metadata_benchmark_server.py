"""Dedicated loopback product server for Gmail metadata benchmark confirmation."""

from __future__ import annotations

import json
import os
import secrets
import time
import uuid
from pathlib import Path
from typing import NoReturn

import uvicorn
from launcher.bootstrap_secret import create_bootstrap_secret
from scripts.run_development import development_runtime_config

from google_work_agent.api.app import create_app

CONFIG_ENVIRONMENT = "GWA_GMAIL_METADATA_BENCHMARK_SERVER_CONFIG"


class _BackendTimingMiddleware:
    def __init__(self, application, timing_path: Path) -> None:  # type: ignore[no-untyped-def]
        self._application = application
        self._timing_path = timing_path
        self._operation_index = 0

    async def __call__(self, scope, receive, send) -> None:  # type: ignore[no-untyped-def]
        if scope["type"] != "http" or scope["path"] != "/api/v1/resources/gmail":
            await self._application(scope, receive, send)
            return
        self._operation_index += 1
        operation_index = self._operation_index
        started = time.perf_counter_ns()
        status_code = 500

        async def timed_send(message):  # type: ignore[no-untyped-def]
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = int(message["status"])
            await send(message)
            if message["type"] == "http.response.body" and not message.get("more_body", False):
                row = {
                    "operation_index": operation_index,
                    "backend_wall_ms": round((time.perf_counter_ns() - started) / 1_000_000, 4),
                    "status_code": status_code,
                }
                with self._timing_path.open("a", encoding="utf-8", newline="\n") as stream:
                    stream.write(json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n")

        await self._application(scope, receive, timed_send)


def _write_private_descriptor(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
        json.dump(payload, stream, sort_keys=True)
        stream.write("\n")


def main() -> NoReturn:
    config_path = Path(os.environ[CONFIG_ENVIRONMENT]).resolve()
    config = json.loads(config_path.read_text(encoding="utf-8"))
    host = "127.0.0.1"
    port = int(config["port"])
    descriptor_path = Path(str(config["descriptor_path"])).resolve()
    timing_path = Path(str(config["timing_path"])).resolve()
    timing_path.parent.mkdir(parents=True, exist_ok=True)
    service_instance_id = f"gmail-benchmark-{uuid.uuid4()}"
    bootstrap_secret = create_bootstrap_secret()
    application = create_app(
        production_config=development_runtime_config(
            mcp_module_name="scripts.gmail_metadata_benchmark_mcp"
        ),
        host=host,
        port=port,
        service_instance_id=service_instance_id,
        bootstrap_secret=bootstrap_secret,
    )
    _write_private_descriptor(
        descriptor_path,
        {
            "base_url": f"http://{host}:{port}",
            "bootstrap_secret": bootstrap_secret,
            "service_instance_id": service_instance_id,
            "process_id": os.getpid(),
            "nonce": secrets.token_hex(16),
        },
    )
    try:
        uvicorn.run(
            _BackendTimingMiddleware(application, timing_path),
            host=host,
            port=port,
            log_level="warning",
        )
    finally:
        descriptor_path.unlink(missing_ok=True)
    raise SystemExit(0)


if __name__ == "__main__":
    main()
