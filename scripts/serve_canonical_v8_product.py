"""Serve one isolated Canonical v8 Case through the real Product composition."""

from __future__ import annotations

import argparse
import json
import os
import signal
import socket
import threading
import time
from collections.abc import Callable, Mapping, Sequence
from contextlib import suppress
from pathlib import Path
from typing import Any, cast

from evaluation.harness.case_runtime import CanonicalCaseRuntime
from evaluation.harness.fault_adapters import (
    FaultApplyingAdapter,
    FaultInjectingConnectorAdapter,
    FaultInjectingLLMProviderAdapter,
    InjectedCallResult,
    InjectedFaultError,
)
from evaluation.harness.stateful_provider import StatefulSimulatedProvider
from launcher.allocate_dynamic_port import allocate_dynamic_port
from launcher.bootstrap_secret import create_bootstrap_secret
from launcher.development_entrypoint import (
    DEVELOPMENT_GITHUB_APP_CLIENT_ID,
    MCP_MANIFEST_VERSION,
    PROJECT_ROOT,
    read_development_google_oauth_client_id,
    read_development_langsmith_environment,
    read_development_sampling_environment,
)
from launcher.open_product_ui import build_product_ui_url
from launcher.readiness import wait_for_service_ready
from uvicorn import Config, Server

from google_work_agent.adapters.llm.runtime.llm_credential_router import SessionMemorySecretStore
from google_work_agent.api.app import create_app
from google_work_agent.api.composition import DevelopmentRuntimeBindings, ProductionRuntimeConfig
from google_work_agent.ports.connector.connector_failure import (
    ConnectorFailureCode,
    ConnectorOperationFailure,
)
from google_work_agent.ports.connector.connector_read_port import ConnectorReadResultV1
from google_work_agent.ports.connector.connector_write_port import ConnectorWriteResultV1
from google_work_agent.ports.connector.mcp_client_port import (
    MCPClientPortError,
    MCPClientPortErrorCode,
)
from google_work_agent.ports.llm.structured_inference_contracts import (
    LLMErrorCode,
    LLMInvocationError,
)

PROVIDER_SNAPSHOT = (
    PROJECT_ROOT / "evaluation/datasets/e2e/fixtures/google_workspace/provider-snapshot-v8.json"
)


class _CaseClock:
    def __init__(self, now_ms: Callable[[], int]) -> None:
        self._now_ms = now_ms

    def now_ms(self) -> int:
        return self._now_ms()


class _ThreadServiceProbe:
    def __init__(self, thread: threading.Thread, exit_code: list[int]) -> None:
        self._thread = thread
        self._exit_code = exit_code

    def poll(self) -> int | None:
        return None if self._thread.is_alive() else self._exit_code[0]


class _Recorder:
    def __init__(self, path: Path) -> None:
        self._path = path
        self._lock = threading.Lock()

    def record(self, payload: dict[str, Any]) -> None:
        safe = {"schema_version": 1, **payload}
        with self._lock:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            with self._path.open("a", encoding="utf-8", newline="\n") as stream:
                stream.write(json.dumps(safe, ensure_ascii=False, sort_keys=True) + "\n")


class _ObservedRead:
    def __init__(self, delegate: Any, recorder: _Recorder) -> None:
        self._delegate = delegate
        self._recorder = recorder

    def execute_read(self, binding: Any, tool_arguments: dict[str, Any]) -> Any:
        started = time.monotonic()
        payload: dict[str, Any] = {
            "kind": "CONNECTOR_READ",
            "tool_id": str(binding.tool_id),
            "arguments": _safe_read_arguments(tool_arguments),
        }
        try:
            result = self._delegate.execute_read(binding, tool_arguments)
            payload["outcome"] = "SUCCESS"
            payload["result_count"] = getattr(result, "total_count", None)
            return result
        except Exception as error:
            payload["outcome"] = "ERROR"
            payload["safe_code"] = _safe_error_code(error)
            raise
        finally:
            payload["duration_ms"] = max(0, int((time.monotonic() - started) * 1_000))
            self._recorder.record(payload)


class _ObservedWrite:
    def __init__(
        self, delegate: Any, recorder: _Recorder, simulated: StatefulSimulatedProvider | None
    ) -> None:
        self._delegate = delegate
        self._recorder = recorder
        self._simulated = simulated

    def execute_write(
        self, binding: Any, tool_arguments: dict[str, Any], claim_token: dict[str, Any]
    ) -> Any:
        tool_id = str(binding.tool_id)
        prior = 0 if self._simulated is None else self._simulated.effect_counts.get(tool_id, 0)
        started = time.monotonic()
        payload: dict[str, Any] = {
            "kind": "CONNECTOR_WRITE",
            "tool_id": tool_id,
            "before_approval": False,
        }
        try:
            result = self._delegate.execute_write(binding, tool_arguments, claim_token)
            payload["outcome"] = "SUCCESS" if getattr(result, "success", False) else "ERROR"
            payload["safe_code"] = getattr(result, "safe_error_code", None) or getattr(
                result, "error_code", None
            )
            payload["delivery_certainty"] = getattr(result, "delivery_certainty", None)
            return result
        except Exception as error:
            payload["outcome"] = "ERROR"
            payload["safe_code"] = _safe_error_code(error)
            raise
        finally:
            current = (
                prior if self._simulated is None else self._simulated.effect_counts.get(tool_id, 0)
            )
            payload["effect_applied"] = current > prior
            payload["effect_count"] = current
            payload["duration_ms"] = max(0, int((time.monotonic() - started) * 1_000))
            self._recorder.record(payload)


class _ObservedLLM:
    def __init__(self, delegate: Any, recorder: _Recorder) -> None:
        self._delegate = delegate
        self._recorder = recorder

    @property
    def provider_name(self) -> str:
        return str(self._delegate.provider_name)

    @property
    def runtime(self) -> Any:
        return self._delegate.runtime

    def invoke_structured(self, **kwargs: Any) -> Any:
        return self._invoke("STRUCTURED", lambda: self._delegate.invoke_structured(**kwargs))

    def invoke_tool_call(self, **kwargs: Any) -> Any:
        return self._invoke("TOOL_CALL", lambda: self._delegate.invoke_tool_call(**kwargs))

    def _invoke(self, operation: str, delegate: Callable[[], Any]) -> Any:
        started = time.monotonic()
        payload: dict[str, Any] = {
            "kind": "LLM",
            "operation": operation,
            "provider": self.provider_name,
        }
        try:
            result = delegate()
            payload["outcome"] = "SUCCESS"
            payload["model"] = str(getattr(result, "model", ""))
            return result
        except Exception as error:
            payload["outcome"] = "ERROR"
            payload["safe_code"] = _safe_error_code(error)
            raise
        finally:
            payload["duration_ms"] = max(0, int((time.monotonic() - started) * 1_000))
            self._recorder.record(payload)


def _connector_failure(error: InjectedFaultError) -> ConnectorOperationFailure:
    mapping = {
        "RATE_LIMITED": ConnectorFailureCode.RATE_LIMITED,
        "UPSTREAM_5XX": ConnectorFailureCode.UPSTREAM_UNAVAILABLE,
        "REAUTH_REQUIRED": ConnectorFailureCode.AUTH_REQUIRED,
        "TIMEOUT": ConnectorFailureCode.TIMEOUT,
    }
    code = mapping.get(error.safe_code, ConnectorFailureCode.UPSTREAM_UNAVAILABLE)
    return ConnectorOperationFailure(
        code, error.safe_code, retryable=code is not ConnectorFailureCode.AUTH_REQUIRED
    )


def _connector_write_result(result: InjectedCallResult) -> ConnectorWriteResultV1:
    return ConnectorWriteResultV1(
        1,
        False,
        cast(Any, result.delivery_certainty),
        None,
        {},
        result.safe_code,
        result.safe_code,
    )


def _simulated_read_result(
    tool_id: str, output: dict[str, Any], call_no: int
) -> ConnectorReadResultV1:
    return ConnectorReadResultV1(1, tool_id, f"simulated-{call_no}", output, None, None)


def _simulated_write_result(
    tool_id: str, item: dict[str, Any], call_no: int
) -> ConnectorWriteResultV1:
    return ConnectorWriteResultV1(
        1,
        True,
        None,
        f"simulated-{call_no}",
        {
            "tool_id": tool_id,
            "resource_type": str(item["resource_type"]),
            "resource_id": str(item["resource_id"]),
            "version": str(item["version"]),
        },
        None,
        None,
    )


def _mcp_failure(error: InjectedFaultError) -> MCPClientPortError:
    return MCPClientPortError(
        code=MCPClientPortErrorCode.PROCESS_UNAVAILABLE,
        message=error.safe_code,
    )


def _llm_failure(error: InjectedFaultError) -> LLMInvocationError:
    return LLMInvocationError(
        LLMErrorCode.LOCAL_UNAVAILABLE,
        error.safe_code,
        runtime_prerequisite=True,
    )


def _case_resources(case: Mapping[str, Any]) -> list[dict[str, Any]]:
    document = json.loads(PROVIDER_SNAPSHOT.read_text(encoding="utf-8"))
    packs = document.get("resource_packs", {})
    result: list[dict[str, Any]] = []
    for pack_name in case.get("resource_packs", []):
        pack = packs.get(pack_name, {}) if isinstance(packs, dict) else {}
        resources = pack.get("resources", []) if isinstance(pack, dict) else []
        for raw in resources:
            if not isinstance(raw, dict) or raw.get("resource_type") not in {
                "gmail_thread",
                "gmail_draft",
                "task_list",
                "task",
                "calendar",
                "calendar_event",
            }:
                continue
            identity = {"resource_type", "resource_id", "parent_id", "version"}
            payload = {key: value for key, value in raw.items() if key not in identity}
            resource_type = str(raw["resource_type"])
            if resource_type == "calendar":
                payload["summary"] = str(payload.get("title") or raw["resource_id"])
                payload["primary"] = bool(payload.get("primary", False))
            elif resource_type == "calendar_event":
                payload = _calendar_event_payload(payload, resource_id=str(raw["resource_id"]))
            elif resource_type == "gmail_thread":
                payload = _gmail_thread_payload(payload)
            result.append(
                {
                    "resource_type": resource_type,
                    "resource_id": raw["resource_id"],
                    "parent_id": raw.get("parent_id"),
                    "version": str(raw.get("version") or raw.get("etag") or "1"),
                    "payload": payload,
                }
            )
    return result


def _calendar_event_payload(payload: Mapping[str, Any], *, resource_id: str) -> dict[str, Any]:
    start = payload.get("start")
    end = payload.get("end")
    start_value = _calendar_boundary(start)
    end_value = _calendar_boundary(end)
    timezone_name = (
        start.get("timeZone")
        if isinstance(start, Mapping)
        else end.get("timeZone")
        if isinstance(end, Mapping)
        else None
    )
    return {
        **payload,
        "title": str(payload.get("title") or resource_id),
        "start": start_value,
        "end": end_value,
        "timezone": str(timezone_name or "UTC"),
        "attendees": [
            str(attendee.get("email"))
            for attendee in payload.get("attendees", [])
            if isinstance(attendee, Mapping) and attendee.get("email")
        ],
    }


def _calendar_boundary(value: Any) -> Any:
    if not isinstance(value, Mapping):
        return value
    return value.get("dateTime") or value.get("date")


def _gmail_thread_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    messages = payload.get("messages")
    message_items = (
        [dict(item) for item in messages if isinstance(item, Mapping)]
        if isinstance(messages, list)
        else []
    )
    first = message_items[0] if message_items else {}
    bodies = [str(item["body"]) for item in message_items if item.get("body")]
    return {
        **payload,
        "subject": str(payload.get("subject") or first.get("subject") or ""),
        "sender_name": first.get("sender_name"),
        "sender_email": first.get("sender_email"),
        "received_at": first.get("received_at"),
        "message_ids": [
            str(item["message_id"]) for item in message_items if item.get("message_id")
        ],
        "body": "\n\n".join(bodies) or None,
        "messages": message_items,
        "message_count": len(message_items),
    }


def _runtime_bindings(
    runtime: CanonicalCaseRuntime, recorder: _Recorder
) -> tuple[DevelopmentRuntimeBindings, FaultApplyingAdapter | None]:
    resources = _case_resources(runtime.case)
    fault = (
        runtime.fault_adapter(fixture_provider=lambda _directive: resources)
        if runtime.fault_harness is not None
        else None
    )
    if fault is not None:
        static_rule = next(
            (
                rule
                for rule in fault.harness.profile.rules
                if rule.boundary == "FIXTURE_PRECONDITION"
            ),
            None,
        )
        if static_rule is not None:
            bound = fault.invoke(
                boundary=static_rule.boundary,
                connector=static_rule.connector,
                operation=static_rule.operations[0],
                delegate=lambda: resources,
            )
            if not isinstance(bound, list):
                raise RuntimeError("fixture precondition must bind a resource list")
            resources = bound
    simulated: StatefulSimulatedProvider | None = None
    if runtime.evaluation_mode == "SIMULATED_PROVIDER":
        simulated = runtime.simulated_provider(
            initial_resources=resources,
            read_result_factory=_simulated_read_result,
            write_result_factory=_simulated_write_result,
        )

    def checkpoints() -> frozenset[str]:
        if fault is None:
            return frozenset()
        values = {
            "WRITE_RESULT_UNKNOWN"
            for record in fault.records
            if record.outcome_kind in {"LOSE_RESPONSE", "RETURN_UNKNOWN"}
        }
        return frozenset(values)

    read_boundary = "CONNECTOR_READ_RESULT"
    if runtime.fault_harness is not None:
        read_boundary = next(
            (
                rule.boundary
                for rule in runtime.fault_harness.profile.rules
                if rule.boundary in {"CONNECTOR_READ_RESULT", "RECOVERY_READ", "VERIFICATION_READ"}
            ),
            read_boundary,
        )

    def decorate_read(delegate: Any) -> Any:
        active: Any = delegate
        if simulated is not None:
            simulated_read: Any = simulated
            if fault is not None:
                simulated_read = FaultInjectingConnectorAdapter(
                    fault_adapter=fault,
                    read_delegate=simulated,
                    read_boundary=read_boundary,
                    checkpoints=checkpoints,
                    read_error_factory=_connector_failure,
                )
            active = simulated_read
        elif fault is not None:
            active = FaultInjectingConnectorAdapter(
                fault_adapter=fault,
                read_delegate=delegate,
                read_boundary=read_boundary,
                checkpoints=checkpoints,
                read_error_factory=_connector_failure,
            )
        return _ObservedRead(active, recorder)

    def decorate_write(delegate: Any) -> Any:
        active: Any = simulated if simulated is not None else delegate
        if fault is not None:
            active = FaultInjectingConnectorAdapter(
                fault_adapter=fault,
                write_delegate=active,
                checkpoints=checkpoints,
                write_result_factory=_connector_write_result,
            )
        return _ObservedWrite(active, recorder, simulated)

    def decorate_llm(delegate: Any) -> Any:
        active: Any = delegate
        if fault is not None:
            active = FaultInjectingLLMProviderAdapter(
                fault_adapter=fault,
                delegate=delegate,
                error_factory=_llm_failure,
            )
        return _ObservedLLM(active, recorder)

    def decorate_mcp(delegate: Any) -> Any:
        if fault is None:
            return delegate
        from evaluation.harness.fault_adapters import FaultInjectingMCPClientAdapter

        return FaultInjectingMCPClientAdapter(
            fault_adapter=fault,
            delegate=delegate,
            error_factory=_mcp_failure,
        )

    return (
        DevelopmentRuntimeBindings(
            clock=None if runtime.business_time is None else _CaseClock(runtime.product_now_ms),
            connector_read_decorator=decorate_read,
            connector_write_decorator=decorate_write,
            mcp_client_decorator=decorate_mcp,
            llm_provider_decorator=decorate_llm,
        ),
        fault,
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Serve one isolated Canonical v8 Product Case")
    parser.add_argument("--case-id", required=True)
    parser.add_argument("--runtime-root", type=Path, required=True)
    parser.add_argument("--launch-descriptor", type=Path, required=True)
    parser.add_argument("--observation-log", type=Path, required=True)
    parser.add_argument("--startup-timeout", type=float, default=45.0)
    arguments = parser.parse_args(argv)
    runtime = CanonicalCaseRuntime.for_case(arguments.case_id)
    recorder = _Recorder(arguments.observation_log.resolve())
    bindings, fault = _runtime_bindings(runtime, recorder)
    reservation = allocate_dynamic_port()
    port = reservation.port
    bootstrap_secret = create_bootstrap_secret()
    service_instance_id = f"eval-{os.getpid()}-{os.urandom(8).hex()}"
    server_holder: list[Server] = []
    stop_requested = threading.Event()

    def handle_stop_signal(_signum: int, _frame: Any) -> None:
        stop_requested.set()
        if server_holder:
            server_holder[0].should_exit = True

    signal.signal(signal.SIGINT, handle_stop_signal)
    if hasattr(signal, "SIGBREAK"):
        signal.signal(signal.SIGBREAK, handle_stop_signal)
    server_socket: socket.socket | None = None
    thread: threading.Thread | None = None
    exit_code = [1]
    descriptor = arguments.launch_descriptor.resolve()
    try:
        langsmith_api_key, langsmith_project_name, trace_binding = (
            read_development_langsmith_environment()
        )
        temperature, seed = read_development_sampling_environment()
        config = ProductionRuntimeConfig.development(
            runtime_root=arguments.runtime_root.resolve(),
            working_directory=PROJECT_ROOT,
            mcp_manifest_version=MCP_MANIFEST_VERSION,
            oauth_client_id=read_development_google_oauth_client_id(),
            github_oauth_client_id=os.environ.get(
                "GITHUB_APP_CLIENT_ID", DEVELOPMENT_GITHUB_APP_CLIENT_ID
            ),
            github_oauth_scope=os.environ.get("GITHUB_APP_SCOPE", ""),
            keyring_store=SessionMemorySecretStore(),
            langsmith_api_key=langsmith_api_key,
            langsmith_project_name=langsmith_project_name,
            langsmith_trace_binding=trace_binding,
            sampling_temperature=temperature,
            sampling_seed=seed,
            runtime_bindings=bindings,
        )

        def request_process_exit() -> None:
            if server_holder:
                server_holder[0].should_exit = True

        application = create_app(
            production_config=config,
            host="127.0.0.1",
            port=port,
            bootstrap_secret=bootstrap_secret,
            service_instance_id=service_instance_id,
            request_process_exit=request_process_exit,
        )
        server = Server(
            Config(
                application,
                host="127.0.0.1",
                port=port,
                access_log=False,
                proxy_headers=False,
                server_header=False,
                date_header=False,
                log_level="warning",
            )
        )
        server_holder.append(server)
        if stop_requested.is_set():
            server.should_exit = True
        server_socket = reservation.take_socket()

        def run_server() -> None:
            try:
                server.run(sockets=[server_socket])
                exit_code[0] = 0
            except Exception as error:
                print(f"Canonical v8 service failed: {_safe_error_code(error)}", flush=True)

        thread = threading.Thread(target=run_server, name="canonical-v8-product")
        thread.start()
        readiness = wait_for_service_ready(
            _ThreadServiceProbe(thread, exit_code),  # type: ignore[arg-type]
            port=port,
            service_instance_id=service_instance_id,
            expected_release_version=config.release_version,
            expected_api_contract_version=config.api_contract_version,
            timeout_seconds=arguments.startup_timeout,
        )
        _write_descriptor(
            descriptor,
            {
                "schema_version": 1,
                "base_url": f"http://127.0.0.1:{port}",
                "bootstrap_url": build_product_ui_url(
                    port=port,
                    bootstrap_secret=bootstrap_secret,
                    service_instance_id=service_instance_id,
                ),
                "service_instance_id": service_instance_id,
                "readiness_state": readiness.state,
                "evaluation_mode": runtime.evaluation_mode,
            },
        )
        bootstrap_secret = ""
        while thread.is_alive():
            thread.join(timeout=0.5)
        return exit_code[0]
    except KeyboardInterrupt:
        return 0
    finally:
        if fault is not None:
            for record in fault.records:
                recorder.record(
                    {
                        "kind": "FAULT",
                        "profile_name": record.profile_name,
                        "rule_id": record.rule_id,
                        "boundary": record.boundary,
                        "operation": record.operation,
                        "outcome": record.outcome_kind,
                        "safe_code": record.safe_code,
                        "effect_applied": record.effect_applied,
                        "delegate_called": record.delegate_called,
                        "product_success_payload_visible": record.product_success_payload_visible,
                    }
                )
        if server_holder:
            server_holder[0].should_exit = True
        if thread is not None and thread.is_alive():
            thread.join(timeout=15)
        if server_socket is not None:
            with suppress(OSError):
                server_socket.close()
        reservation.release()
        descriptor.unlink(missing_ok=True)


def _safe_read_arguments(arguments: Mapping[str, Any]) -> dict[str, Any]:
    allowed = {
        "query",
        "page_size",
        "time_min",
        "time_max",
        "status_scope",
        "include_thread_metadata",
    }
    return {key: arguments[key] for key in allowed if key in arguments}


def _safe_error_code(error: BaseException) -> str:
    code = getattr(error, "code", None)
    value = getattr(code, "value", code)
    if isinstance(value, str) and value:
        return value
    detail = getattr(error, "detail_code", None)
    return detail if isinstance(detail, str) and detail else type(error).__name__.upper()


def _write_descriptor(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    with temporary.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(payload, stream, sort_keys=True, separators=(",", ":"))
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.chmod(temporary, 0o600)
    os.replace(temporary, path)


if __name__ == "__main__":
    raise SystemExit(main())
