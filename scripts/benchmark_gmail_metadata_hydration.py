"""Reproducible Gmail metadata hydration benchmark and raw-result aggregator."""

from __future__ import annotations

import argparse
import concurrent.futures
import ctypes
import hashlib
import hmac
import json
import math
import os
import platform
import random
import secrets
import subprocess
import sys
import tempfile
import threading
import time
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, NoReturn, cast

import httpx

from google_work_agent.adapters.connectors.google.gmail.threads import search_threads
from google_work_agent.adapters.connectors.google.workspace.mcp_server.composition import (
    compose_server_state,
)
from google_work_agent.adapters.connectors.google.workspace.mcp_server.credential_provider import (
    _OAuthReauthenticationRequired,
    _WorkspaceToolError,
)
from google_work_agent.adapters.connectors.google.workspace.mcp_server.project_registry import (
    ToolContractViolation,
    validate_tool_input,
    validate_tool_output,
)

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RESULT_DIR = ROOT / "evaluation" / "results" / "gmail-metadata-hydration-20260914-7afac9f5"
FIXTURE_REF = "gmail_fixed_historical_page_v1"
FIXED_QUERY = "after:2026/09/06 before:2026/09/08 -in:spam -in:trash"
SEED = 20260913
BOOTSTRAP_SEED = 20260914
PERCENTILE_METHOD = "linear_type7"
PACING_SECONDS = 16.2
QUOTA_UNITS_PER_JOB = 810
RESOURCE_SAMPLE_INTERVAL_SECONDS = 0.2
PROVIDER_LANE = "LIVE_PROVIDER_SWEEP"
LOCAL_LANE = "LIVE_LOCAL_API_CONFIRM"
CONCURRENT_LANE = "LIVE_LOCAL_API_J2"


@dataclass(frozen=True, slots=True)
class BenchmarkConfig:
    config_id: str
    transport: str
    batch_size: int | None
    http_concurrency_limit: int

    def hydration_config(self) -> search_threads.GmailMetadataHydrationConfig:
        return search_threads.GmailMetadataHydrationConfig(
            transport=cast(Any, self.transport),
            batch_size=self.batch_size,
            http_concurrency_limit=self.http_concurrency_limit,
        )


CONFIGS = (
    BenchmarkConfig("S1", "INDIVIDUAL", None, 1),
    BenchmarkConfig("S3_BASELINE", "INDIVIDUAL", None, 3),
    BenchmarkConfig("S5", "INDIVIDUAL", None, 5),
    BenchmarkConfig("S10", "INDIVIDUAL", None, 10),
    BenchmarkConfig("B5W1", "BATCH", 5, 1),
    BenchmarkConfig("B5W2", "BATCH", 5, 2),
    BenchmarkConfig("B5W4", "BATCH", 5, 4),
    BenchmarkConfig("B10W1", "BATCH", 10, 1),
    BenchmarkConfig("B10W2", "BATCH", 10, 2),
    BenchmarkConfig("B20W1", "BATCH", 20, 1),
)
CONFIG_BY_ID = {config.config_id: config for config in CONFIGS}


def _json_line(payload: Mapping[str, object]) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _canonical_result_payload(payload: Mapping[str, object]) -> str:
    items = payload.get("items")
    normalized_items = []
    if isinstance(items, list):
        for item in items:
            if not isinstance(item, dict):
                normalized_items.append(item)
                continue
            normalized_items.append(
                {
                    key: value
                    for key, value in item.items()
                    if key not in {"selection_handle", "link_url"}
                }
            )
    return json.dumps(
        {"items": normalized_items},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _append_jsonl(path: Path, rows: Iterable[Mapping[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as stream:
        for row in rows:
            stream.write(_json_line(row) + "\n")


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class TrialObserver:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._config_id = ""
        self._http_index = 0
        self._active: dict[int, int] = {}
        self._in_flight = 0
        self._max_in_flight = 0
        self._http_rows: list[dict[str, object]] = []
        self._batch_rows: list[dict[str, object]] = []
        self._phases: dict[str, object] = {}
        self._message_count_total = 0
        self._started_envelopes = 0
        self._finished_envelopes = 0

    def begin(self, config_id: str) -> None:
        with self._lock:
            self._config_id = config_id
            self._http_index = 0
            self._active = {}
            self._in_flight = 0
            self._max_in_flight = 0
            self._http_rows = []
            self._batch_rows = []
            self._phases = {}
            self._message_count_total = 0
            self._started_envelopes = 0
            self._finished_envelopes = 0

    def on_http_started(self, *, kind: str, method: str, inner_count: int | None) -> None:
        with self._lock:
            self._http_index += 1
            self._active[threading.get_ident()] = self._http_index
            self._in_flight += 1
            self._max_in_flight = max(self._max_in_flight, self._in_flight)
            self._started_envelopes += 1
            self._http_rows.append(
                {
                    "attempt_index": self._http_index,
                    "kind": kind,
                    "method": method,
                    "inner_count": inner_count,
                    "in_flight_at_start": self._in_flight,
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
            attempt_index = self._active.pop(threading.get_ident(), 0)
            row = next(
                (item for item in self._http_rows if item["attempt_index"] == attempt_index),
                None,
            )
            if row is None:
                row = {
                    "attempt_index": 0,
                    "kind": kind,
                    "method": method,
                    "inner_count": inner_count,
                    "instrumentation_error": "FINISH_WITHOUT_START",
                }
                self._http_rows.append(row)
            row.update(
                {
                    "status_code": status_code,
                    "response_body_bytes": response_body_bytes,
                    "duration_ms": round(duration_ms, 4),
                    "safe_error_code": safe_error_code,
                }
            )
            self._in_flight = max(0, self._in_flight - 1)
            self._finished_envelopes += 1

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
            self._batch_rows.append(
                {
                    "ordinal": ordinal,
                    "status_code": status_code,
                    "response_body_bytes": response_body_bytes,
                    "result_seen": result_seen,
                    "safe_error_code": safe_error_code,
                }
            )

    def on_provider_payload(self, *, kind: str, message_count: int | None) -> None:
        if kind == "GMAIL_THREAD_GET" and message_count is not None:
            with self._lock:
                self._message_count_total += message_count

    def on_phase_finished(self, *, phase: str, duration_ms: float, status: str) -> None:
        with self._lock:
            self._phases[f"{phase.lower()}_wall_ms"] = round(duration_ms, 4)
            if status != "SUCCESS":
                self._phases[f"{phase.lower()}_status"] = status

    def finish(self) -> dict[str, object]:
        with self._lock:
            valid = (
                self._started_envelopes == self._finished_envelopes
                and self._in_flight == 0
                and all("instrumentation_error" not in row for row in self._http_rows)
            )
            return {
                "http_rows": list(self._http_rows),
                "batch_rows": list(self._batch_rows),
                "phases": dict(self._phases),
                "message_count_total": self._message_count_total,
                "max_in_flight_http": self._max_in_flight,
                "instrumentation_valid": valid,
            }


def _provider_worker() -> NoReturn:
    state = compose_server_state()
    observer = TrialObserver()
    state.provider_read_observer = observer
    print(_json_line({"worker_ready": True, "process_id": os.getpid()}), flush=True)
    for raw_line in sys.stdin:
        try:
            command = cast(dict[str, object], json.loads(raw_line))
            if command.get("command") == "shutdown":
                break
            if command.get("command") != "run":
                raise ValueError("unsupported command")
            config = CONFIG_BY_ID[str(command["config_id"])]
            observer.begin(config.config_id)
            arguments: dict[str, object] = {
                "query": str(command["query"]),
                "page_size": 20,
                "include_thread_metadata": True,
            }
            started = time.perf_counter_ns()
            safe_error_code: str | None = None
            result: dict[str, object] | None = None
            try:
                validate_tool_input("gmail_search_threads", arguments)
                result = search_threads._gmail_search_threads(
                    state,
                    arguments,
                    hydration_config=config.hydration_config(),
                )
                validate_tool_output("gmail_search_threads", result)
                execution_outcome = "SUCCESS"
            except _OAuthReauthenticationRequired:
                safe_error_code = "REAUTH_REQUIRED"
                execution_outcome = "AUTH_ERROR"
            except _WorkspaceToolError as error:
                safe_error_code = error.safe_code
                execution_outcome = _outcome_for_safe_code(error.safe_code)
            except ToolContractViolation:
                safe_error_code = "CONTRACT_MISMATCH"
                execution_outcome = "CONTRACT_FAILURE"
            except Exception:
                safe_error_code = "UNEXPECTED_PROVIDER_FAILURE"
                execution_outcome = "PROVIDER_FAILURE"
            wall_ms = (time.perf_counter_ns() - started) / 1_000_000
            observed = observer.finish()
            items = result.get("items") if isinstance(result, dict) else None
            result_count = len(items) if isinstance(items, list) else 0
            canonical = _canonical_result_payload(result) if result is not None else ""
            key = bytes.fromhex(str(command["hmac_key"]))
            response = {
                "execution_outcome": execution_outcome,
                "safe_error_code": safe_error_code,
                "provider_operation_wall_ms": round(wall_ms, 4),
                "result_count": result_count,
                "logical_json_bytes": len(canonical.encode("utf-8")),
                "dataset_hmac": hmac.new(
                    key, canonical.encode("utf-8"), hashlib.sha256
                ).hexdigest(),
                "connection_state": state.connection_state.value,
                "provider_write_send_count": 0,
                **observed,
            }
        except Exception:
            response = {
                "execution_outcome": "HARNESS_FAILURE",
                "safe_error_code": "HARNESS_COMMAND_FAILED",
                "provider_write_send_count": 0,
                "instrumentation_valid": False,
                "http_rows": [],
                "batch_rows": [],
                "phases": {},
            }
        print(_json_line(response), flush=True)
    raise SystemExit(0)


def _outcome_for_safe_code(safe_code: str) -> str:
    if safe_code in {"REAUTH_REQUIRED", "OAUTH_NOT_CONNECTED"}:
        return "AUTH_ERROR"
    if safe_code == "RATE_LIMITED":
        return "RATE_LIMIT"
    if safe_code == "TIMEOUT":
        return "TIMEOUT"
    if safe_code == "INVALID_MCP_OUTPUT":
        return "PARSE_ERROR"
    return "PROVIDER_ERROR"


class _FileTime(ctypes.Structure):
    _fields_ = [("low", ctypes.c_ulong), ("high", ctypes.c_ulong)]


class _ProcessMemoryCountersEx(ctypes.Structure):
    _fields_ = [
        ("cb", ctypes.c_ulong),
        ("page_fault_count", ctypes.c_ulong),
        ("peak_working_set_size", ctypes.c_size_t),
        ("working_set_size", ctypes.c_size_t),
        ("quota_peak_paged_pool_usage", ctypes.c_size_t),
        ("quota_paged_pool_usage", ctypes.c_size_t),
        ("quota_peak_non_paged_pool_usage", ctypes.c_size_t),
        ("quota_non_paged_pool_usage", ctypes.c_size_t),
        ("pagefile_usage", ctypes.c_size_t),
        ("peak_pagefile_usage", ctypes.c_size_t),
        ("private_usage", ctypes.c_size_t),
    ]


class _MemoryStatusEx(ctypes.Structure):
    _fields_ = [
        ("dwLength", ctypes.c_ulong),
        ("dwMemoryLoad", ctypes.c_ulong),
        ("ullTotalPhys", ctypes.c_ulonglong),
        ("ullAvailPhys", ctypes.c_ulonglong),
        ("ullTotalPageFile", ctypes.c_ulonglong),
        ("ullAvailPageFile", ctypes.c_ulonglong),
        ("ullTotalVirtual", ctypes.c_ulonglong),
        ("ullAvailVirtual", ctypes.c_ulonglong),
        ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
    ]


def _total_ram_bytes() -> int | None:
    if os.name != "nt":
        return None
    status = _MemoryStatusEx()
    status.dwLength = ctypes.sizeof(status)
    if ctypes.WinDLL("kernel32", use_last_error=True).GlobalMemoryStatusEx(ctypes.byref(status)):
        return int(status.ullTotalPhys)
    return None


def _filetime_value(value: _FileTime) -> int:
    return int((value.high << 32) | value.low)


def _process_snapshot(process_id: int) -> dict[str, int | None]:
    if os.name != "nt":
        return {
            "cpu_counter_100ns": None,
            "working_set_bytes": None,
            "private_bytes": None,
            "handle_count": None,
            "os_threads": None,
        }
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    psapi = ctypes.WinDLL("psapi", use_last_error=True)
    kernel32.OpenProcess.restype = ctypes.c_void_p
    kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
    kernel32.GetProcessTimes.argtypes = [
        ctypes.c_void_p,
        ctypes.POINTER(_FileTime),
        ctypes.POINTER(_FileTime),
        ctypes.POINTER(_FileTime),
        ctypes.POINTER(_FileTime),
    ]
    kernel32.GetProcessHandleCount.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_ulong)]
    psapi.GetProcessMemoryInfo.argtypes = [
        ctypes.c_void_p,
        ctypes.POINTER(_ProcessMemoryCountersEx),
        ctypes.c_ulong,
    ]
    handle = kernel32.OpenProcess(0x0410, False, process_id)
    if not handle:
        return {
            "cpu_counter_100ns": None,
            "working_set_bytes": None,
            "private_bytes": None,
            "handle_count": None,
            "os_threads": None,
        }
    try:
        creation = _FileTime()
        exit_time = _FileTime()
        kernel = _FileTime()
        user = _FileTime()
        cpu_counter: int | None = None
        if kernel32.GetProcessTimes(
            handle,
            ctypes.byref(creation),
            ctypes.byref(exit_time),
            ctypes.byref(kernel),
            ctypes.byref(user),
        ):
            cpu_counter = _filetime_value(kernel) + _filetime_value(user)
        memory = _ProcessMemoryCountersEx()
        memory.cb = ctypes.sizeof(memory)
        has_memory = bool(
            psapi.GetProcessMemoryInfo(handle, ctypes.byref(memory), ctypes.sizeof(memory))
        )
        handle_count = ctypes.c_ulong()
        has_handles = bool(kernel32.GetProcessHandleCount(handle, ctypes.byref(handle_count)))
        return {
            "cpu_counter_100ns": cpu_counter,
            "working_set_bytes": int(memory.working_set_size) if has_memory else None,
            "private_bytes": int(memory.private_usage) if has_memory else None,
            "handle_count": int(handle_count.value) if has_handles else None,
            "os_threads": _windows_thread_count(process_id),
        }
    finally:
        kernel32.CloseHandle(handle)


class _ThreadEntry32(ctypes.Structure):
    _fields_ = [
        ("dwSize", ctypes.c_ulong),
        ("cntUsage", ctypes.c_ulong),
        ("th32ThreadID", ctypes.c_ulong),
        ("th32OwnerProcessID", ctypes.c_ulong),
        ("tpBasePri", ctypes.c_long),
        ("tpDeltaPri", ctypes.c_long),
        ("dwFlags", ctypes.c_ulong),
    ]


class _ProcessEntry32(ctypes.Structure):
    _fields_ = [
        ("dwSize", ctypes.c_ulong),
        ("cntUsage", ctypes.c_ulong),
        ("th32ProcessID", ctypes.c_ulong),
        ("th32DefaultHeapID", ctypes.POINTER(ctypes.c_ulong)),
        ("th32ModuleID", ctypes.c_ulong),
        ("cntThreads", ctypes.c_ulong),
        ("th32ParentProcessID", ctypes.c_ulong),
        ("pcPriClassBase", ctypes.c_long),
        ("dwFlags", ctypes.c_ulong),
        ("szExeFile", ctypes.c_wchar * 260),
    ]


def _windows_thread_count(process_id: int) -> int | None:
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateToolhelp32Snapshot.restype = ctypes.c_void_p
    kernel32.Thread32First.argtypes = [ctypes.c_void_p, ctypes.POINTER(_ThreadEntry32)]
    kernel32.Thread32Next.argtypes = [ctypes.c_void_p, ctypes.POINTER(_ThreadEntry32)]
    kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
    snapshot = kernel32.CreateToolhelp32Snapshot(0x00000004, 0)
    if snapshot == ctypes.c_void_p(-1).value:
        return None
    count = 0
    try:
        entry = _ThreadEntry32()
        entry.dwSize = ctypes.sizeof(entry)
        available = kernel32.Thread32First(snapshot, ctypes.byref(entry))
        while available:
            if entry.th32OwnerProcessID == process_id:
                count += 1
            available = kernel32.Thread32Next(snapshot, ctypes.byref(entry))
        return count
    finally:
        kernel32.CloseHandle(snapshot)


def _windows_descendants(parent_process_id: int) -> list[int]:
    if os.name != "nt":
        return []
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateToolhelp32Snapshot.restype = ctypes.c_void_p
    kernel32.Process32FirstW.argtypes = [ctypes.c_void_p, ctypes.POINTER(_ProcessEntry32)]
    kernel32.Process32NextW.argtypes = [ctypes.c_void_p, ctypes.POINTER(_ProcessEntry32)]
    kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
    snapshot = kernel32.CreateToolhelp32Snapshot(0x00000002, 0)
    if snapshot == ctypes.c_void_p(-1).value:
        return []
    parents: dict[int, int] = {}
    try:
        entry = _ProcessEntry32()
        entry.dwSize = ctypes.sizeof(entry)
        available = kernel32.Process32FirstW(snapshot, ctypes.byref(entry))
        while available:
            parents[int(entry.th32ProcessID)] = int(entry.th32ParentProcessID)
            available = kernel32.Process32NextW(snapshot, ctypes.byref(entry))
    finally:
        kernel32.CloseHandle(snapshot)
    descendants: list[int] = []
    frontier = [parent_process_id]
    while frontier:
        current = frontier.pop()
        children = [pid for pid, parent in parents.items() if parent == current]
        descendants.extend(children)
        frontier.extend(children)
    return descendants


class ResourceSampler:
    def __init__(self, process_id: int) -> None:
        self._process_id = process_id
        self._stop = threading.Event()
        self._rows: list[dict[str, object]] = []
        self._started_ns = 0
        self._thread: threading.Thread | None = None

    def start(self) -> dict[str, int | None]:
        self._started_ns = time.perf_counter_ns()
        initial = _process_snapshot(self._process_id)
        self._rows = [{"relative_ms": 0.0, **initial}]
        self._thread = threading.Thread(target=self._sample_loop, daemon=True)
        self._thread.start()
        return initial

    def stop(self) -> tuple[dict[str, int | None], list[dict[str, object]]]:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2)
        final = _process_snapshot(self._process_id)
        self._rows.append(
            {
                "relative_ms": round((time.perf_counter_ns() - self._started_ns) / 1_000_000, 4),
                **final,
            }
        )
        return final, self._rows

    def _sample_loop(self) -> None:
        while not self._stop.wait(RESOURCE_SAMPLE_INTERVAL_SECONDS):
            self._rows.append(
                {
                    "relative_ms": round(
                        (time.perf_counter_ns() - self._started_ns) / 1_000_000, 4
                    ),
                    **_process_snapshot(self._process_id),
                }
            )


def _worker_command() -> list[str]:
    return [sys.executable, str(Path(__file__).resolve()), "provider-worker"]


def _provider_worker_environment() -> dict[str, str]:
    environment = os.environ.copy()
    environment["GOOGLE_OAUTH_ENV"] = "DEVELOPMENT"
    if not environment.get("GOOGLE_OAUTH_CLIENT_ID", "").strip():
        env_file = ROOT / ".env.local"
        if env_file.exists():
            for raw_line in env_file.read_text(encoding="utf-8").splitlines():
                key, separator, value = raw_line.partition("=")
                if separator and key.strip() == "GOOGLE_OAUTH_CLIENT_ID":
                    environment["GOOGLE_OAUTH_CLIENT_ID"] = value.strip().strip("\"'")
                    break
    environment.setdefault("GOOGLE_OAUTH_CLIENT_ID", "development-client-id")
    return environment


def _read_worker_response(
    worker: subprocess.Popen[str],
    *,
    target_process_id: int,
    command: Mapping[str, object],
) -> tuple[dict[str, object], dict[str, int | None], list[dict[str, object]]]:
    if worker.stdin is None or worker.stdout is None:
        raise RuntimeError("provider worker pipes are unavailable")
    sampler = ResourceSampler(target_process_id)
    initial = sampler.start()
    worker.stdin.write(_json_line(command) + "\n")
    worker.stdin.flush()
    line = worker.stdout.readline()
    final, samples = sampler.stop()
    if not line:
        raise RuntimeError("provider worker stopped without a response")
    response = cast(dict[str, object], json.loads(line))
    response["resource_initial"] = initial
    response["resource_final"] = final
    return response, initial, samples


def _balanced_blocks(block_count: int) -> list[tuple[int, list[BenchmarkConfig]]]:
    blocks: list[tuple[int, list[BenchmarkConfig]]] = []
    for cycle_start in range(0, block_count, len(CONFIGS)):
        cycle = list(CONFIGS)
        random.Random(SEED + cycle_start).shuffle(cycle)
        for offset in range(min(len(CONFIGS), block_count - cycle_start)):
            blocks.append((cycle_start + offset + 1, cycle[offset:] + cycle[:offset]))
    return blocks


def _warmup_schedule(warmups: int) -> list[BenchmarkConfig]:
    schedule: list[BenchmarkConfig] = []
    for round_index in range(warmups):
        values = list(CONFIGS)
        random.Random(SEED - round_index - 1).shuffle(values)
        schedule.extend(values)
    return schedule


def _git_output(*arguments: str) -> str:
    return subprocess.check_output(
        ["git", *arguments], cwd=ROOT, text=True, encoding="utf-8"
    ).strip()


def _manifest(result_dir: Path, *, warmups: int, blocks: int) -> dict[str, object]:
    relevant_sources = [
        ROOT / "src/google_work_agent/adapters/connectors/google/gmail/threads/search_threads.py",
        ROOT
        / (
            "src/google_work_agent/adapters/connectors/google/workspace/mcp_server/"
            "credential_provider.py"
        ),
        Path(__file__).resolve(),
        ROOT / "scripts/gmail_metadata_benchmark_mcp.py",
        ROOT / "scripts/gmail_metadata_benchmark_server.py",
    ]
    source_hashes = {
        str(path.relative_to(ROOT)).replace("\\", "/"): _sha256_file(path)
        for path in relevant_sources
    }
    config_payload = [asdict(config) for config in CONFIGS]
    config_hash = hashlib.sha256(_json_line({"configs": config_payload}).encode()).hexdigest()
    return {
        "schema_version": 1,
        "session_id": result_dir.name,
        "created_at_utc": datetime.now(UTC).isoformat(),
        "lane": PROVIDER_LANE,
        "fixture_ref": FIXTURE_REF,
        "fixture_query_persisted": False,
        "resource_ids_persisted": False,
        "provider_write_send_count": 0,
        "git": {
            "branch": _git_output("branch", "--show-current"),
            "local_head": _git_output("rev-parse", "HEAD"),
            "remote_head": _git_output("rev-parse", "@{upstream}"),
            "working_tree_at_session_start": _git_output("status", "--short"),
        },
        "source_hashes": source_hashes,
        "config_hash": config_hash,
        "configs": config_payload,
        "planned": {
            "warmups_per_config": warmups,
            "measured_attempts_per_config": blocks,
            "j": 1,
        },
        "statistics": {
            "percentile_method": PERCENTILE_METHOD,
            "paired_block_bootstrap_resamples": 5000,
            "paired_block_bootstrap_seed": BOOTSTRAP_SEED,
            "tie_threshold": "max(50ms, 10% of fastest valid p95)",
        },
        "quota": {
            "threads_list_units": 10,
            "threads_get_units": 40,
            "logical_units_per_page_job": QUOTA_UNITS_PER_JOB,
            "verified_project_applied_quota": False,
            "conservative_documented_user_quota_per_minute": 6000,
            "allocated_fraction": 0.5,
            "allocated_units_per_minute": 3000,
            "minimum_page_start_interval_seconds": PACING_SECONDS,
        },
        "runtime": {
            "platform": platform.platform(),
            "windows_build": platform.version(),
            "processor": platform.processor() or os.environ.get("PROCESSOR_IDENTIFIER"),
            "logical_cpu_count": os.cpu_count(),
            "total_ram_bytes": _total_ram_bytes(),
            "python": sys.version,
            "http_client": "Python urllib.request",
            "resource_sampler": "Windows ctypes controller",
            "resource_sample_interval_ms": RESOURCE_SAMPLE_INTERVAL_SECONDS * 1000,
            "power_mode": "not changed; independently unverifiable",
            "network_vpn_proxy": "not changed by harness; independently unverifiable",
            "loaded_product_source": str(Path(search_threads.__file__).resolve()),
        },
        "measurement_boundaries": {
            "provider_operation_wall_ms": "P4-P0",
            "list_wall_ms": "P2-P1",
            "detail_wall_ms": "P3-P2",
            "projection_wall_ms": "P4-P3",
            "cpu_scope": "provider diagnostic worker process",
            "sampler_scope": "separate controller thread/process, excluded from target counters",
        },
    }


def _provider_sweep(arguments: argparse.Namespace) -> int:
    result_dir = arguments.result_dir.resolve()
    result_dir.mkdir(parents=True, exist_ok=True)
    raw_paths = [
        result_dir / "trials.jsonl",
        result_dir / "http_attempts.jsonl",
        result_dir / "batch_parts.jsonl",
        result_dir / "resources.jsonl",
    ]
    if any(path.exists() and path.stat().st_size for path in raw_paths):
        raise RuntimeError("provider sweep raw files already contain data")
    manifest = _manifest(result_dir, warmups=arguments.warmups, blocks=arguments.blocks)
    _write_json(result_dir / "experiment_manifest.json", manifest)
    worker = subprocess.Popen(
        _worker_command(),
        cwd=ROOT,
        env=_provider_worker_environment(),
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        bufsize=1,
    )
    if worker.stdout is None:
        raise RuntimeError("provider worker stdout is unavailable")
    ready = cast(dict[str, Any], json.loads(worker.stdout.readline()))
    if ready.get("worker_ready") is not True:
        raise RuntimeError("provider worker did not report readiness")
    worker_process_id = int(ready["process_id"])
    hmac_key = secrets.token_bytes(32).hex()
    schedule: list[tuple[str, int | None, BenchmarkConfig]] = [
        ("WARMUP", None, config) for config in _warmup_schedule(arguments.warmups)
    ]
    for block_index, configs in _balanced_blocks(arguments.blocks):
        schedule.extend(("MEASURED", block_index, config) for config in configs)
    last_started = 0.0
    expected_hmac: str | None = None
    expected_message_count: int | None = None
    rate_limit_jobs = 0
    started_counts = {config.config_id: 0 for config in CONFIGS}
    try:
        for overall_index, (sample_kind, block, config) in enumerate(schedule, start=1):
            delay = max(0.0, arguments.pacing_seconds - (time.monotonic() - last_started))
            if delay:
                time.sleep(delay)
            started_at = datetime.now(UTC).isoformat()
            last_started = time.monotonic()
            started_counts[config.config_id] += 1
            trial_id = (
                f"warmup-{started_counts[config.config_id]:03d}-{config.config_id}"
                if sample_kind == "WARMUP"
                else f"block-{block:03d}-{config.config_id}"
            )
            command = {
                "command": "run",
                "config_id": config.config_id,
                "query": FIXED_QUERY,
                "hmac_key": hmac_key,
            }
            try:
                response, initial, samples = _read_worker_response(
                    worker, target_process_id=worker_process_id, command=command
                )
            except Exception:
                response = {
                    "execution_outcome": "HARNESS_FAILURE",
                    "safe_error_code": "PROVIDER_WORKER_FAILED",
                    "provider_write_send_count": 0,
                    "instrumentation_valid": False,
                    "http_rows": [],
                    "batch_rows": [],
                    "phases": {},
                }
                initial = {}
                samples = []
            http_rows = cast(list[dict[str, object]], response.pop("http_rows", []))
            batch_rows = cast(list[dict[str, object]], response.pop("batch_rows", []))
            phases = cast(dict[str, object], response.pop("phases", {}))
            final = cast(dict[str, int | None], response.pop("resource_final", {}))
            response.pop("resource_initial", None)
            cpu_start = initial.get("cpu_counter_100ns")
            cpu_end = final.get("cpu_counter_100ns")
            cpu_ms = (
                (cpu_end - cpu_start) / 10_000
                if isinstance(cpu_start, int) and isinstance(cpu_end, int)
                else None
            )
            observed_hmac = response.get("dataset_hmac")
            data_matches = False
            if response.get("execution_outcome") == "SUCCESS" and isinstance(observed_hmac, str):
                if expected_hmac is None:
                    expected_hmac = observed_hmac
                data_matches = observed_hmac == expected_hmac
            result_count = response.get("result_count")
            message_count = response.get("message_count_total")
            if expected_message_count is None and isinstance(message_count, int):
                expected_message_count = message_count
            envelope_rows = [row for row in http_rows if row.get("attempt_index")]
            logical_operations = _logical_api_operation_count(envelope_rows)
            expected_http_attempts = (
                21
                if config.transport == "INDIVIDUAL"
                else 1 + math.ceil(20 / cast(int, config.batch_size))
            )
            expected_batch_parts = 20 if config.transport == "BATCH" else 0
            instrumentation_valid = (
                response.get("instrumentation_valid") is True
                and len(envelope_rows) == expected_http_attempts
                and logical_operations == 21
                and len(batch_rows) == expected_batch_parts
                and message_count == expected_message_count
                and all(row.get("kind") != "GOOGLE_API_WRITE" for row in envelope_rows)
            )
            comparable = (
                response.get("execution_outcome") == "SUCCESS"
                and result_count == 20
                and data_matches
                and instrumentation_valid
            )
            response.pop("dataset_hmac", None)
            trial = {
                "schema_version": 1,
                "trial_id": trial_id,
                "lane": PROVIDER_LANE,
                "sample_kind": sample_kind,
                "block": block,
                "config_id": config.config_id,
                "started_at_utc": started_at,
                "planned_attempt_ordinal": overall_index,
                "pacing_seconds": arguments.pacing_seconds,
                "execution_outcome": response.get("execution_outcome"),
                "safe_error_code": response.get("safe_error_code"),
                "measurement_validity": "COMPARABLE" if comparable else "INVALID",
                "result_count": result_count,
                "data_contract_match": data_matches,
                "instrumentation_valid": instrumentation_valid,
                "provider_operation_wall_ms": response.get("provider_operation_wall_ms"),
                **phases,
                "cpu_ms_per_job": round(cpu_ms, 4) if cpu_ms is not None else None,
                "working_set_idle_bytes": initial.get("working_set_bytes"),
                "working_set_peak_bytes": _max_sample(samples, "working_set_bytes"),
                "private_idle_bytes": initial.get("private_bytes"),
                "private_peak_bytes": _max_sample(samples, "private_bytes"),
                "private_end_bytes": final.get("private_bytes"),
                "os_threads_idle": initial.get("os_threads"),
                "os_threads_peak": _max_sample(samples, "os_threads"),
                "os_threads_end": final.get("os_threads"),
                "handles_idle": initial.get("handle_count"),
                "handles_peak": _max_sample(samples, "handle_count"),
                "handles_end": final.get("handle_count"),
                "logical_json_bytes": response.get("logical_json_bytes"),
                "message_count_total": message_count,
                "observed_data_http_attempts": len(envelope_rows),
                "observed_logical_api_operations": logical_operations,
                "max_in_flight_http": response.get("max_in_flight_http"),
                "provider_write_send_count": response.get("provider_write_send_count", 0),
                "retry_count": 0,
                "auth_refresh_http_count": 0,
                "executor_wait_ms": None,
                "context_switches": None,
                "gc_metrics": None,
            }
            _append_jsonl(result_dir / "trials.jsonl", [trial])
            _append_jsonl(
                result_dir / "http_attempts.jsonl",
                ({"trial_id": trial_id, "lane": PROVIDER_LANE, **row} for row in http_rows),
            )
            _append_jsonl(
                result_dir / "batch_parts.jsonl",
                ({"trial_id": trial_id, "lane": PROVIDER_LANE, **row} for row in batch_rows),
            )
            _append_jsonl(
                result_dir / "resources.jsonl",
                (
                    {
                        "trial_id": trial_id,
                        "lane": PROVIDER_LANE,
                        "process_role": "PROVIDER_DIAGNOSTIC_WORKER",
                        "sample_interval_ms": RESOURCE_SAMPLE_INTERVAL_SECONDS * 1000,
                        **row,
                    }
                    for row in samples
                ),
            )
            if response.get("execution_outcome") == "RATE_LIMIT":
                rate_limit_jobs += 1
            if overall_index % 10 == 0 or not comparable:
                print(
                    f"progress={overall_index}/{len(schedule)} trial={trial_id} "
                    f"outcome={trial['execution_outcome']} comparable={comparable}",
                    flush=True,
                )
            if response.get("execution_outcome") == "AUTH_ERROR":
                print("BLOCKED: REAUTH", flush=True)
                break
            if rate_limit_jobs >= 3:
                print("STOPPED: RATE_LIMIT_REPEATED_3", flush=True)
                break
            if response.get("execution_outcome") == "HARNESS_FAILURE":
                print("STOPPED: HARNESS_FAILURE", flush=True)
                break
            if response.get("execution_outcome") == "SUCCESS" and not comparable:
                print("STOPPED: DATA_OR_INSTRUMENTATION_CHANGED", flush=True)
                break
    finally:
        if worker.stdin is not None and worker.poll() is None:
            try:
                worker.stdin.write(_json_line({"command": "shutdown"}) + "\n")
                worker.stdin.flush()
                worker.wait(timeout=10)
            except (BrokenPipeError, subprocess.TimeoutExpired):
                worker.terminate()
        if worker.stderr is not None:
            stderr = worker.stderr.read().strip()
            if stderr:
                _write_json(
                    result_dir / "provider_worker_stderr.json",
                    {
                        "safe_summary": "provider worker emitted stderr",
                        "line_count": len(stderr.splitlines()),
                    },
                )
    _summarize_provider(result_dir)
    return 0


def _max_sample(rows: Sequence[Mapping[str, object]], field: str) -> int | None:
    values = [value for row in rows if isinstance((value := row.get(field)), int)]
    return max(values) if values else None


def _logical_api_operation_count(rows: Sequence[Mapping[str, object]]) -> int:
    return sum(_as_int(row.get("inner_count"), default=1) for row in rows)


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [
        cast(dict[str, Any], json.loads(line))
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _percentile(values: Sequence[float], quantile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * quantile
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def _mean(values: Sequence[float]) -> float | None:
    return sum(values) / len(values) if values else None


def _wilson(failures: int, total: int) -> tuple[float | None, float | None]:
    if total == 0:
        return None, None
    z = 1.959963984540054
    proportion = failures / total
    denominator = 1 + z * z / total
    center = (proportion + z * z / (2 * total)) / denominator
    margin = (
        z
        * math.sqrt(proportion * (1 - proportion) / total + z * z / (4 * total * total))
        / denominator
    )
    lower = 0.0 if failures == 0 else max(0.0, center - margin)
    upper = 1.0 if failures == total else min(1.0, center + margin)
    return lower, upper


def _paired_bootstrap(
    baseline: Mapping[int, float], candidate: Mapping[int, float]
) -> dict[str, object]:
    common = sorted(set(baseline) & set(candidate))
    if not common:
        return {"n_pairs": 0, "delta_p95_ms": None, "reduction_pct": None, "ci95": None}
    base_values = [baseline[index] for index in common]
    candidate_values = [candidate[index] for index in common]
    base_p95 = cast(float, _percentile(base_values, 0.95))
    candidate_p95 = cast(float, _percentile(candidate_values, 0.95))
    deltas: list[float] = []
    reductions: list[float] = []
    rng = random.Random(BOOTSTRAP_SEED)
    for _ in range(5000):
        positions = [rng.randrange(len(common)) for _ in common]
        sample_base = [base_values[position] for position in positions]
        sample_candidate = [candidate_values[position] for position in positions]
        sampled_base_p95 = cast(float, _percentile(sample_base, 0.95))
        sampled_candidate_p95 = cast(float, _percentile(sample_candidate, 0.95))
        delta = sampled_candidate_p95 - sampled_base_p95
        deltas.append(delta)
        reductions.append(100 * (sampled_base_p95 - sampled_candidate_p95) / sampled_base_p95)
    return {
        "n_pairs": len(common),
        "paired_baseline_p95_ms": round(base_p95, 4),
        "paired_candidate_p95_ms": round(candidate_p95, 4),
        "delta_p95_ms": round(candidate_p95 - base_p95, 4),
        "reduction_pct": round(100 * (base_p95 - candidate_p95) / base_p95, 4),
        "delta_p95_ci95_ms": [
            round(cast(float, _percentile(deltas, 0.025)), 4),
            round(cast(float, _percentile(deltas, 0.975)), 4),
        ],
        "reduction_ci95_pct": [
            round(cast(float, _percentile(reductions, 0.025)), 4),
            round(cast(float, _percentile(reductions, 0.975)), 4),
        ],
    }


def _as_int(value: object, *, default: int = 0) -> int:
    return int(value) if isinstance(value, (int, float, str)) else default


def _summarize_provider(result_dir: Path) -> dict[str, object]:
    trials = [
        row
        for row in _read_jsonl(result_dir / "trials.jsonl")
        if row.get("lane") == PROVIDER_LANE and row.get("sample_kind") == "MEASURED"
    ]
    baseline_by_block = {
        int(row["block"]): float(row["provider_operation_wall_ms"])
        for row in trials
        if row.get("config_id") == "S3_BASELINE" and row.get("measurement_validity") == "COMPARABLE"
    }
    summaries: list[dict[str, Any]] = []
    for config in CONFIGS:
        attempted = [row for row in trials if row.get("config_id") == config.config_id]
        comparable = [row for row in attempted if row.get("measurement_validity") == "COMPARABLE"]
        walls = [float(row["provider_operation_wall_ms"]) for row in comparable]
        cpu = [float(row["cpu_ms_per_job"]) for row in comparable if row.get("cpu_ms_per_job")]
        http_counts = [float(row["observed_data_http_attempts"]) for row in comparable]
        failures = len(attempted) - len(comparable)
        wilson_low, wilson_high = _wilson(failures, len(attempted))
        by_block = {
            int(row["block"]): float(row["provider_operation_wall_ms"]) for row in comparable
        }
        p95 = _percentile(walls, 0.95)
        summaries.append(
            {
                **asdict(config),
                "planned": 100,
                "attempted": len(attempted),
                "comparable": len(comparable),
                "success": sum(row.get("execution_outcome") == "SUCCESS" for row in attempted),
                "contract_failures": sum(
                    row.get("execution_outcome") == "CONTRACT_FAILURE" for row in attempted
                ),
                "parse_or_api_errors": sum(
                    row.get("execution_outcome")
                    in {"PARSE_ERROR", "PROVIDER_ERROR", "PROVIDER_FAILURE"}
                    for row in attempted
                ),
                "timeout_jobs": sum(row.get("execution_outcome") == "TIMEOUT" for row in attempted),
                "rate_limit_jobs": sum(
                    row.get("execution_outcome") == "RATE_LIMIT" for row in attempted
                ),
                "failure_rate": failures / len(attempted) if attempted else None,
                "failure_rate_wilson95": [wilson_low, wilson_high],
                "operation_mean_ms": _mean(walls),
                "operation_p50_ms": _percentile(walls, 0.5),
                "operation_p95_ms": p95,
                "operation_p99_reference_ms": _percentile(walls, 0.99),
                "list_p95_ms": _percentile(
                    [float(row["list_wall_ms"]) for row in comparable], 0.95
                ),
                "detail_p95_ms": _percentile(
                    [float(row["detail_wall_ms"]) for row in comparable], 0.95
                ),
                "projection_p95_ms": _percentile(
                    [float(row["projection_wall_ms"]) for row in comparable], 0.95
                ),
                "actual_http_mean": _mean(http_counts),
                "actual_http_range": [min(http_counts), max(http_counts)] if http_counts else None,
                "actual_logical_mean": _mean(
                    [float(row["observed_logical_api_operations"]) for row in comparable]
                ),
                "max_in_flight_observed": max(
                    [int(row["max_in_flight_http"]) for row in comparable], default=None
                ),
                "cpu_ms_per_job_mean": _mean(cpu),
                "working_set_peak_mib": _bytes_peak(comparable, "working_set_peak_bytes"),
                "private_peak_mib": _bytes_peak(comparable, "private_peak_bytes"),
                "os_threads_peak": max(
                    [
                        int(row["os_threads_peak"])
                        for row in comparable
                        if row.get("os_threads_peak")
                    ],
                    default=None,
                ),
                "handles_peak": max(
                    [int(row["handles_peak"]) for row in comparable if row.get("handles_peak")],
                    default=None,
                ),
                "paired_vs_s3": (
                    _paired_bootstrap(baseline_by_block, by_block)
                    if config.config_id != "S3_BASELINE"
                    else None
                ),
                "status": "COMPLETE" if len(attempted) == 100 else "INCOMPLETE",
            }
        )
    finalists = _select_finalists(summaries)
    output = {
        "schema_version": 1,
        "lane": PROVIDER_LANE,
        "percentile_method": PERCENTILE_METHOD,
        "configs": summaries,
        "finalists": finalists,
        "provider_write_send_count": sum(
            int(row.get("provider_write_send_count") or 0) for row in trials
        ),
    }
    _write_json(result_dir / "summary_provider.json", output)
    _write_provider_csv(result_dir / "summary_provider.csv", summaries)
    _write_provider_charts(result_dir, summaries)
    return output


def _bytes_peak(rows: Sequence[Mapping[str, Any]], field: str) -> float | None:
    values = [int(row[field]) for row in rows if row.get(field)]
    return max(values) / (1024 * 1024) if values else None


def _select_finalists(summaries: Sequence[Mapping[str, Any]]) -> list[str]:
    valid = [
        row
        for row in summaries
        if row.get("status") == "COMPLETE"
        and row.get("comparable") == row.get("attempted")
        and isinstance(row.get("operation_p95_ms"), (int, float))
    ]
    if not valid:
        return []
    pareto: list[Mapping[str, Any]] = []
    for candidate in valid:
        dominated = any(
            other is not candidate
            and float(other["operation_p95_ms"]) <= float(candidate["operation_p95_ms"])
            and float(other["cpu_ms_per_job_mean"] or math.inf)
            <= float(candidate["cpu_ms_per_job_mean"] or math.inf)
            and float(other["private_peak_mib"] or math.inf)
            <= float(candidate["private_peak_mib"] or math.inf)
            and (
                float(other["operation_p95_ms"]) < float(candidate["operation_p95_ms"])
                or float(other["cpu_ms_per_job_mean"] or math.inf)
                < float(candidate["cpu_ms_per_job_mean"] or math.inf)
                or float(other["private_peak_mib"] or math.inf)
                < float(candidate["private_peak_mib"] or math.inf)
            )
            for other in valid
        )
        if not dominated:
            pareto.append(candidate)
    fastest = min(float(row["operation_p95_ms"]) for row in pareto)
    tie = max(50.0, fastest * 0.10)
    eligible = [row for row in pareto if float(row["operation_p95_ms"]) <= fastest + tie]
    eligible.sort(
        key=lambda row: (
            float(row["cpu_ms_per_job_mean"] or math.inf),
            float(row["private_peak_mib"] or math.inf),
            int(row["max_in_flight_observed"] or 999),
            float(row["operation_p95_ms"]),
        )
    )
    return [str(row["config_id"]) for row in eligible[:2]]


def _write_provider_csv(path: Path, summaries: Sequence[Mapping[str, Any]]) -> None:
    fields = [
        "config_id",
        "planned",
        "attempted",
        "comparable",
        "success",
        "failure_rate",
        "operation_mean_ms",
        "operation_p50_ms",
        "operation_p95_ms",
        "operation_p99_reference_ms",
        "list_p95_ms",
        "detail_p95_ms",
        "actual_http_mean",
        "actual_logical_mean",
        "max_in_flight_observed",
        "cpu_ms_per_job_mean",
        "working_set_peak_mib",
        "private_peak_mib",
        "os_threads_peak",
        "status",
    ]
    lines = [",".join(fields)]
    for row in summaries:
        lines.append(
            ",".join("" if row.get(field) is None else str(row[field]) for field in fields)
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_provider_charts(result_dir: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    valid = [row for row in rows if row.get("operation_p95_ms") is not None]
    if not valid:
        return
    width, height = 900, 480
    margin = 70
    max_latency = max(float(row["operation_p95_ms"]) for row in valid) * 1.1
    bar_width = (width - 2 * margin) / max(1, len(valid))
    elements = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}">',
        '<rect width="100%" height="100%" fill="white"/>',
        '<text x="450" y="24" text-anchor="middle" font-family="sans-serif" '
        'font-size="16">LIVE_PROVIDER_SWEEP latency and HTTP envelopes</text>',
    ]
    for index, row in enumerate(valid):
        x = margin + index * bar_width
        p50 = float(row["operation_p50_ms"])
        p95 = float(row["operation_p95_ms"])
        h95 = (height - 2 * margin) * p95 / max_latency
        h50 = (height - 2 * margin) * p50 / max_latency
        elements.extend(
            [
                f'<rect x="{x + 4:.1f}" y="{height - margin - h95:.1f}" '
                f'width="{bar_width / 2 - 6:.1f}" height="{h95:.1f}" fill="#f59e0b"/>',
                f'<rect x="{x + bar_width / 2:.1f}" y="{height - margin - h50:.1f}" '
                f'width="{bar_width / 2 - 6:.1f}" height="{h50:.1f}" fill="#2563eb"/>',
                f'<text x="{x + bar_width / 2:.1f}" y="{height - 48}" '
                f'text-anchor="middle" font-family="sans-serif" font-size="10">'
                f"{row['config_id']}</text>",
                f'<text x="{x + bar_width / 2:.1f}" y="{height - 34}" '
                f'text-anchor="middle" font-family="sans-serif" font-size="9">'
                f"HTTP {float(row['actual_http_mean']):.0f}</text>",
            ]
        )
    elements.append("</svg>")
    (result_dir / "provider_latency_http.svg").write_text("\n".join(elements), encoding="utf-8")
    cpu_values = [
        (float(row["cpu_ms_per_job_mean"]), float(row["operation_p95_ms"]), row["config_id"])
        for row in valid
        if row.get("cpu_ms_per_job_mean") is not None
    ]
    if not cpu_values:
        return
    max_cpu = max(item[0] for item in cpu_values) * 1.1
    scatter = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}">',
        '<rect width="100%" height="100%" fill="white"/>',
        '<text x="450" y="24" text-anchor="middle" font-family="sans-serif" '
        'font-size="16">LIVE_PROVIDER_SWEEP p95 vs CPU ms/job</text>',
    ]
    for cpu, latency, label in cpu_values:
        x = margin + (width - 2 * margin) * cpu / max_cpu
        y = height - margin - (height - 2 * margin) * latency / max_latency
        scatter.extend(
            [
                f'<circle cx="{x:.1f}" cy="{y:.1f}" r="5" fill="#7c3aed"/>',
                f'<text x="{x + 7:.1f}" y="{y - 5:.1f}" font-family="sans-serif" '
                f'font-size="10">{label}</text>',
            ]
        )
    scatter.append("</svg>")
    (result_dir / "provider_p95_cpu.svg").write_text("\n".join(scatter), encoding="utf-8")


@dataclass(slots=True)
class LocalServer:
    process: subprocess.Popen[str]
    client: httpx.Client
    config: BenchmarkConfig
    subblock: int
    event_path: Path
    timing_path: Path
    mcp_config_path: Path
    temp_directory: tempfile.TemporaryDirectory[str]
    service_process_id: int
    mcp_process_ids: list[int]


def _free_loopback_port() -> int:
    import socket

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def _start_local_server(
    result_dir: Path,
    *,
    config: BenchmarkConfig,
    lane: str,
    subblock: int,
) -> LocalServer:
    temp_directory = tempfile.TemporaryDirectory(prefix="gwa-gmail-benchmark-")
    temp_root = Path(temp_directory.name).resolve()
    port = _free_loopback_port()
    descriptor_path = temp_root / "launch.json"
    server_config_path = temp_root / "server-config.json"
    mcp_config_path = (
        Path(tempfile.gettempdir()) / "gwa-gmail-metadata-benchmark-config.json"
    ).resolve()
    if mcp_config_path.exists():
        temp_directory.cleanup()
        raise RuntimeError("another Gmail metadata benchmark MCP configuration is active")
    event_path = result_dir / f".{lane}-{config.config_id}-{subblock:03d}-mcp.tmp.jsonl"
    timing_path = result_dir / f".{lane}-{config.config_id}-{subblock:03d}-timing.tmp.jsonl"
    _write_json(
        mcp_config_path,
        {
            **asdict(config),
            "event_path": str(event_path),
        },
    )
    _write_json(
        server_config_path,
        {
            "port": port,
            "descriptor_path": str(descriptor_path),
            "timing_path": str(timing_path),
        },
    )
    environment = os.environ.copy()
    existing_python_path = environment.get("PYTHONPATH", "")
    environment["PYTHONPATH"] = str(ROOT) + (
        os.pathsep + existing_python_path if existing_python_path else ""
    )
    environment["GWA_GMAIL_METADATA_BENCHMARK_SERVER_CONFIG"] = str(server_config_path)
    process = subprocess.Popen(
        [sys.executable, str(ROOT / "scripts/gmail_metadata_benchmark_server.py")],
        cwd=ROOT,
        env=environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
    )
    deadline = time.monotonic() + 60
    descriptor: dict[str, Any] | None = None
    while time.monotonic() < deadline:
        if process.poll() is not None:
            break
        if descriptor_path.exists():
            try:
                descriptor = cast(
                    dict[str, Any], json.loads(descriptor_path.read_text(encoding="utf-8"))
                )
                break
            except (OSError, json.JSONDecodeError):
                pass
        time.sleep(0.1)
    if descriptor is None:
        process.terminate()
        stdout, stderr = process.communicate(timeout=10)
        mcp_config_path.unlink(missing_ok=True)
        temp_directory.cleanup()
        raise RuntimeError(
            "local benchmark server failed to start: "
            f"stdout={len(stdout)} stderr={len(stderr)} detail={stderr[-4000:]}"
        )
    base_url = str(descriptor["base_url"])
    common_headers = {
        "Origin": base_url,
        "Sec-Fetch-Site": "same-origin",
        "Sec-Fetch-Mode": "cors",
        "Sec-Fetch-Dest": "empty",
        "X-API-Contract-Version": "1",
    }
    client = httpx.Client(base_url=base_url, headers=common_headers, timeout=60)
    while time.monotonic() < deadline:
        try:
            ready = client.get("/health/ready")
            if ready.status_code == 200 and ready.json().get("status") == "READY":
                break
        except (httpx.HTTPError, json.JSONDecodeError):
            pass
        time.sleep(0.2)
    else:
        _stop_local_server_process(process)
        client.close()
        stdout, stderr = process.communicate(timeout=10)
        mcp_config_path.unlink(missing_ok=True)
        temp_directory.cleanup()
        raise RuntimeError(
            "local benchmark server did not become ready: "
            f"stdout={len(stdout)} stderr={len(stderr)} detail={stderr[-4000:]}"
        )
    bootstrap = client.post(
        "/api/v1/session/bootstrap",
        json={
            "schema_version": 1,
            "bootstrap_secret": descriptor["bootstrap_secret"],
            "frontend_api_contract_version": "1",
        },
    )
    if bootstrap.status_code != 200:
        _stop_local_server_process(process)
        client.close()
        mcp_config_path.unlink(missing_ok=True)
        temp_directory.cleanup()
        raise RuntimeError(f"local session bootstrap failed with {bootstrap.status_code}")
    descriptor_path.unlink(missing_ok=True)
    return LocalServer(
        process=process,
        client=client,
        config=config,
        subblock=subblock,
        event_path=event_path,
        timing_path=timing_path,
        mcp_config_path=mcp_config_path,
        temp_directory=temp_directory,
        service_process_id=int(descriptor["process_id"]),
        mcp_process_ids=[],
    )


def _stop_local_server_process(process: subprocess.Popen[str]) -> None:
    descendants = _windows_descendants(process.pid)
    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=15)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=10)
    for process_id in reversed(descendants):
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.OpenProcess.restype = ctypes.c_void_p
        kernel32.TerminateProcess.argtypes = [ctypes.c_void_p, ctypes.c_uint]
        kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
        handle = kernel32.OpenProcess(0x0001, False, process_id)
        if handle:
            kernel32.TerminateProcess(handle, 1)
            kernel32.CloseHandle(handle)


def _stop_local_server(server: LocalServer, result_dir: Path, *, lane: str) -> None:
    server.client.close()
    _stop_local_server_process(server.process)
    _collect_local_mcp_events(server, result_dir, lane=lane)
    if server.process.stdout is not None:
        server.process.stdout.close()
    if server.process.stderr is not None:
        stderr = server.process.stderr.read().strip()
        if stderr:
            _append_jsonl(
                result_dir / "local_server_process_events.jsonl",
                [
                    {
                        "lane": lane,
                        "config_id": server.config.config_id,
                        "subblock": server.subblock,
                        "safe_event": "STDERR_EMITTED",
                        "line_count": len(stderr.splitlines()),
                    }
                ],
            )
        server.process.stderr.close()
    server.event_path.unlink(missing_ok=True)
    server.timing_path.unlink(missing_ok=True)
    server.mcp_config_path.unlink(missing_ok=True)
    server.temp_directory.cleanup()


def _collect_local_mcp_events(server: LocalServer, result_dir: Path, *, lane: str) -> None:
    rows = _read_jsonl(server.event_path)
    http_rows: list[dict[str, object]] = []
    batch_rows: list[dict[str, object]] = []
    phase_rows: list[dict[str, object]] = []
    for row in rows:
        common = {
            "lane": lane,
            "config_id": server.config.config_id,
            "subblock": server.subblock,
            "operation_index": row.get("operation_index"),
        }
        if row.get("record_type") in {"HTTP_STARTED", "HTTP_FINISHED"}:
            http_rows.append({**common, **row})
        elif row.get("record_type") == "BATCH_PART":
            batch_rows.append({**common, **row})
        elif row.get("record_type") == "PHASE":
            phase_rows.append({**common, **row})
    _append_jsonl(result_dir / "http_attempts.jsonl", http_rows)
    _append_jsonl(result_dir / "batch_parts.jsonl", batch_rows)
    _append_jsonl(result_dir / "local_provider_phases.jsonl", phase_rows)


def _local_gmail_request(client: httpx.Client) -> tuple[int, dict[str, Any], float]:
    started = time.perf_counter_ns()
    response = client.get(
        "/api/v1/resources/gmail",
        params={
            "query": FIXED_QUERY,
            "page_size": 20,
            "include_thread_metadata": "true",
        },
    )
    client_wall_ms = (time.perf_counter_ns() - started) / 1_000_000
    try:
        payload = cast(dict[str, Any], response.json())
    except json.JSONDecodeError:
        payload = {}
    return response.status_code, payload, client_wall_ms


def _timing_row(path: Path, operation_index: int) -> dict[str, Any] | None:
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        row = next(
            (
                item
                for item in reversed(_read_jsonl(path))
                if item.get("operation_index") == operation_index
            ),
            None,
        )
        if row is not None:
            return row
        time.sleep(0.02)
    return None


class MultiResourceSampler:
    def __init__(self, processes: Mapping[str, int]) -> None:
        self._processes = dict(processes)
        self._samplers = {role: ResourceSampler(pid) for role, pid in self._processes.items()}
        self.initial: dict[str, dict[str, int | None]] = {}

    def start(self) -> None:
        self.initial = {role: sampler.start() for role, sampler in self._samplers.items()}

    def stop(self) -> tuple[dict[str, dict[str, int | None]], list[dict[str, object]]]:
        final: dict[str, dict[str, int | None]] = {}
        rows: list[dict[str, object]] = []
        for role, sampler in self._samplers.items():
            role_final, role_rows = sampler.stop()
            final[role] = role_final
            rows.extend({"process_role": role, **row} for row in role_rows)
        return final, rows

    def cpu_ms(self, final: Mapping[str, Mapping[str, int | None]]) -> float | None:
        total = 0.0
        observed = False
        for role, initial in self.initial.items():
            start = initial.get("cpu_counter_100ns")
            end = final.get(role, {}).get("cpu_counter_100ns")
            if isinstance(start, int) and isinstance(end, int):
                total += (end - start) / 10_000
                observed = True
        return total if observed else None


def _local_process_roles(server: LocalServer) -> dict[str, int]:
    descendants = _windows_descendants(server.service_process_id)
    if not server.mcp_process_ids and descendants:
        process_ids = ",".join(str(process_id) for process_id in descendants)
        command = (
            f"$ids=@({process_ids}); Get-CimInstance Win32_Process | "
            "Where-Object { $ids -contains [int]$_.ProcessId } | "
            "Select-Object ProcessId,ParentProcessId,CommandLine | ConvertTo-Json -Compress"
        )
        completed = subprocess.run(
            ["powershell", "-NoProfile", "-Command", command],
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=15,
            check=False,
        )
        if completed.returncode == 0 and completed.stdout.strip():
            payload = json.loads(completed.stdout)
            process_rows = payload if isinstance(payload, list) else [payload]
            matching_rows = [
                row
                for row in process_rows
                if isinstance(row, dict)
                and "scripts.gmail_metadata_benchmark_mcp" in str(row.get("CommandLine", ""))
            ]
            matching_parents = {int(row.get("ParentProcessId", 0)) for row in matching_rows}
            server.mcp_process_ids = [
                int(row["ProcessId"])
                for row in matching_rows
                if int(row["ProcessId"]) not in matching_parents
            ]
    roles = {"LOCAL_API_SERVICE": server.service_process_id}
    for index, process_id in enumerate(server.mcp_process_ids, start=1):
        roles[f"GOOGLE_MCP_{index}"] = process_id
    return roles


def _record_local_request(
    server: LocalServer,
    result_dir: Path,
    *,
    lane: str,
    sample_kind: str,
    trial_id: str,
    block: int | None,
    operation_index: int,
    hmac_key: bytes,
    expected_hmac: str | None,
) -> tuple[dict[str, object], str | None]:
    sampler = MultiResourceSampler(_local_process_roles(server))
    sampler.start()
    status_code, payload, client_wall_ms = _local_gmail_request(server.client)
    final, resources = sampler.stop()
    backend = _timing_row(server.timing_path, operation_index)
    items = payload.get("items") if isinstance(payload, dict) else None
    canonical = _canonical_result_payload(payload)
    observed_hmac = hmac.new(hmac_key, canonical.encode("utf-8"), hashlib.sha256).hexdigest()
    if (
        expected_hmac is None
        and status_code == 200
        and isinstance(items, list)
        and len(items) == 20
    ):
        expected_hmac = observed_hmac
    data_matches = observed_hmac == expected_hmac
    cpu_ms = sampler.cpu_ms(final)
    comparable = (
        status_code == 200
        and isinstance(items, list)
        and len(items) == 20
        and data_matches
        and backend is not None
    )
    trial = {
        "schema_version": 1,
        "trial_id": trial_id,
        "lane": lane,
        "sample_kind": sample_kind,
        "block": block,
        "subblock": server.subblock,
        "config_id": server.config.config_id,
        "operation_index": operation_index,
        "started_at_utc": datetime.now(UTC).isoformat(),
        "execution_outcome": "SUCCESS" if status_code == 200 else "API_ERROR",
        "safe_error_code": None if status_code == 200 else f"HTTP_{status_code}",
        "measurement_validity": "COMPARABLE" if comparable else "INVALID",
        "result_count": len(items) if isinstance(items, list) else 0,
        "data_contract_match": data_matches,
        "backend_wall_ms": backend.get("backend_wall_ms") if backend else None,
        "client_wall_ms": round(client_wall_ms, 4),
        "service_mcp_cpu_ms_per_job": round(cpu_ms, 4) if cpu_ms is not None else None,
        "provider_write_send_count": 0,
        "retry_count": 0,
    }
    _append_jsonl(result_dir / "trials.jsonl", [trial])
    _append_jsonl(
        result_dir / "resources.jsonl",
        (
            {
                "trial_id": trial_id,
                "lane": lane,
                "config_id": server.config.config_id,
                "subblock": server.subblock,
                **row,
            }
            for row in resources
        ),
    )
    return trial, expected_hmac


def _finalist_configs(result_dir: Path) -> list[BenchmarkConfig]:
    summary = cast(
        dict[str, Any],
        json.loads((result_dir / "summary_provider.json").read_text(encoding="utf-8")),
    )
    config_ids = ["S3_BASELINE", *cast(list[str], summary.get("finalists", []))]
    return [CONFIG_BY_ID[config_id] for config_id in dict.fromkeys(config_ids)]


def _local_confirm(arguments: argparse.Namespace) -> int:
    result_dir = arguments.result_dir.resolve()
    if any(
        row.get("lane") == LOCAL_LANE and row.get("sample_kind") == "MEASURED"
        for row in _read_jsonl(result_dir / "trials.jsonl")
    ):
        raise RuntimeError("local confirmation raw trials already exist")
    configs = _finalist_configs(result_dir)
    hmac_key = secrets.token_bytes(32)
    expected_hmac: str | None = None
    last_started = 0.0
    total = len(configs) * 100
    completed = 0
    blocked = False
    for subblock in range(1, 11):
        for config in configs:
            server = _start_local_server(
                result_dir, config=config, lane=LOCAL_LANE, subblock=subblock
            )
            try:
                for position in range(0, 11):
                    delay = max(0.0, arguments.pacing_seconds - (time.monotonic() - last_started))
                    if delay:
                        time.sleep(delay)
                    last_started = time.monotonic()
                    sample_kind = "WARMUP" if position == 0 else "MEASURED"
                    block = (subblock - 1) * 10 + position if position else None
                    trial_id = (
                        f"local-warmup-{subblock:02d}-{config.config_id}"
                        if position == 0
                        else f"local-{block:03d}-{config.config_id}"
                    )
                    trial, expected_hmac = _record_local_request(
                        server,
                        result_dir,
                        lane=LOCAL_LANE,
                        sample_kind=sample_kind,
                        trial_id=trial_id,
                        block=block,
                        operation_index=position + 1,
                        hmac_key=hmac_key,
                        expected_hmac=expected_hmac,
                    )
                    if sample_kind == "MEASURED":
                        completed += 1
                    if trial["safe_error_code"] in {"HTTP_401", "HTTP_403"}:
                        print("BLOCKED: REAUTH_OR_PERMISSION", flush=True)
                        blocked = True
                        break
                    if (
                        trial["execution_outcome"] == "SUCCESS"
                        and trial["measurement_validity"] != "COMPARABLE"
                    ):
                        print("STOPPED: LOCAL_DATA_OR_TIMING_CHANGED", flush=True)
                        blocked = True
                        break
                    if completed % 10 == 0 and sample_kind == "MEASURED":
                        print(
                            f"local-progress={completed}/{total} trial={trial_id} "
                            f"validity={trial['measurement_validity']}",
                            flush=True,
                        )
            finally:
                _stop_local_server(server, result_dir, lane=LOCAL_LANE)
            if blocked:
                break
        if blocked:
            break
    _summarize_backend(result_dir)
    return 1 if blocked else 0


def _summarize_backend(result_dir: Path) -> dict[str, object]:
    trials = [
        row
        for row in _read_jsonl(result_dir / "trials.jsonl")
        if row.get("lane") == LOCAL_LANE and row.get("sample_kind") == "MEASURED"
    ]
    configs = _finalist_configs(result_dir)
    baseline_by_block = {
        int(row["block"]): float(row["backend_wall_ms"])
        for row in trials
        if row.get("config_id") == "S3_BASELINE" and row.get("measurement_validity") == "COMPARABLE"
    }
    summaries: list[dict[str, Any]] = []
    for config in configs:
        attempted = [row for row in trials if row.get("config_id") == config.config_id]
        comparable = [row for row in attempted if row.get("measurement_validity") == "COMPARABLE"]
        walls = [float(row["backend_wall_ms"]) for row in comparable]
        failures = len(attempted) - len(comparable)
        low, high = _wilson(failures, len(attempted))
        by_block = {int(row["block"]): float(row["backend_wall_ms"]) for row in comparable}
        summaries.append(
            {
                **asdict(config),
                "planned": 100,
                "attempted": len(attempted),
                "comparable": len(comparable),
                "success": sum(row.get("execution_outcome") == "SUCCESS" for row in attempted),
                "backend_mean_ms": _mean(walls),
                "backend_p50_ms": _percentile(walls, 0.5),
                "backend_p95_ms": _percentile(walls, 0.95),
                "backend_p99_reference_ms": _percentile(walls, 0.99),
                "client_p95_ms": _percentile(
                    [float(row["client_wall_ms"]) for row in comparable], 0.95
                ),
                "failure_rate": failures / len(attempted) if attempted else None,
                "failure_rate_wilson95": [low, high],
                "service_mcp_cpu_ms_per_job_mean": _mean(
                    [
                        float(row["service_mcp_cpu_ms_per_job"])
                        for row in comparable
                        if row.get("service_mcp_cpu_ms_per_job") is not None
                    ]
                ),
                "paired_vs_s3": (
                    _paired_bootstrap(baseline_by_block, by_block)
                    if config.config_id != "S3_BASELINE"
                    else None
                ),
                "status": "COMPLETE" if len(attempted) == 100 else "INCOMPLETE",
            }
        )
    valid = [
        row
        for row in summaries
        if row["status"] == "COMPLETE" and row["attempted"] == row["comparable"]
    ]
    selected = None
    if valid:
        fastest = min(float(row["backend_p95_ms"]) for row in valid)
        tie = max(50.0, fastest * 0.10)
        eligible = [row for row in valid if float(row["backend_p95_ms"]) <= fastest + tie]
        eligible.sort(
            key=lambda row: (
                float(row["service_mcp_cpu_ms_per_job_mean"] or math.inf),
                int(row["http_concurrency_limit"]),
                float(row["backend_p95_ms"]),
            )
        )
        selected = str(eligible[0]["config_id"])
    output = {
        "schema_version": 1,
        "lane": LOCAL_LANE,
        "percentile_method": PERCENTILE_METHOD,
        "configs": summaries,
        "selected_config": selected,
        "provider_write_send_count": sum(
            int(row.get("provider_write_send_count") or 0) for row in trials
        ),
    }
    _write_json(result_dir / "summary_backend.json", output)
    return output


def _selected_concurrent_configs(result_dir: Path) -> list[BenchmarkConfig]:
    summary = cast(
        dict[str, Any],
        json.loads((result_dir / "summary_backend.json").read_text(encoding="utf-8")),
    )
    selected = summary.get("selected_config")
    if not isinstance(selected, str):
        raise RuntimeError("local confirmation did not select a valid config")
    identifiers = list(dict.fromkeys(["S3_BASELINE", selected]))
    return [CONFIG_BY_ID[identifier] for identifier in identifiers]


def _probe(client: httpx.Client) -> tuple[float, bool]:
    started = time.perf_counter_ns()
    try:
        response = client.get("/health/ready", timeout=5)
        success = response.status_code == 200
    except httpx.HTTPError:
        success = False
    return (time.perf_counter_ns() - started) / 1_000_000, success


def _concurrent_episode(
    server: LocalServer,
    result_dir: Path,
    *,
    episode_index: int,
    first_operation_index: int,
    hmac_key: bytes,
    expected_hmac: str | None,
) -> tuple[dict[str, object], str | None]:
    roles = _local_process_roles(server)
    sampler = MultiResourceSampler(roles)
    sampler.start()
    stop_probe = threading.Event()
    probe_rows: list[dict[str, object]] = []

    def probe_loop() -> None:
        while not stop_probe.is_set():
            duration_ms, success = _probe(server.client)
            probe_rows.append(
                {
                    "lane": CONCURRENT_LANE,
                    "config_id": server.config.config_id,
                    "episode": episode_index,
                    "probe_kind": "DURING",
                    "duration_ms": round(duration_ms, 4),
                    "success": success,
                }
            )
            stop_probe.wait(1.0)

    probe_thread = threading.Thread(target=probe_loop, daemon=True)
    probe_thread.start()
    submitted_ns = time.perf_counter_ns()
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(_local_gmail_request, server.client) for _ in range(2)]
        responses = [future.result() for future in futures]
    episode_wall_ms = (time.perf_counter_ns() - submitted_ns) / 1_000_000
    stop_probe.set()
    probe_thread.join(timeout=2)
    final, resources = sampler.stop()
    cpu_ms = sampler.cpu_ms(final)
    comparable_jobs = 0
    successful_jobs = 0
    job_walls: list[float] = []
    client_walls: list[float] = []
    result_hmacs: list[str] = []
    for offset, (status_code, payload, client_wall_ms) in enumerate(responses):
        items = payload.get("items") if isinstance(payload, dict) else None
        canonical = _canonical_result_payload(payload)
        observed_hmac = hmac.new(hmac_key, canonical.encode("utf-8"), hashlib.sha256).hexdigest()
        if (
            expected_hmac is None
            and status_code == 200
            and isinstance(items, list)
            and len(items) == 20
        ):
            expected_hmac = observed_hmac
        timing = _timing_row(server.timing_path, first_operation_index + offset)
        matches = observed_hmac == expected_hmac
        comparable = (
            status_code == 200
            and isinstance(items, list)
            and len(items) == 20
            and matches
            and timing is not None
        )
        successful_jobs += int(status_code == 200)
        comparable_jobs += int(comparable)
        client_walls.append(client_wall_ms)
        result_hmacs.append(observed_hmac)
        if timing is not None:
            job_walls.append(float(timing["backend_wall_ms"]))
        _append_jsonl(
            result_dir / "trials.jsonl",
            [
                {
                    "schema_version": 1,
                    "trial_id": f"j2-{episode_index:03d}-{server.config.config_id}-{offset + 1}",
                    "lane": CONCURRENT_LANE,
                    "sample_kind": "MEASURED",
                    "config_id": server.config.config_id,
                    "episode": episode_index,
                    "job_in_episode": offset + 1,
                    "subblock": server.subblock,
                    "operation_index": first_operation_index + offset,
                    "execution_outcome": "SUCCESS" if status_code == 200 else "API_ERROR",
                    "safe_error_code": None if status_code == 200 else f"HTTP_{status_code}",
                    "measurement_validity": "COMPARABLE" if comparable else "INVALID",
                    "result_count": len(items) if isinstance(items, list) else 0,
                    "data_contract_match": matches,
                    "backend_wall_ms": timing.get("backend_wall_ms") if timing else None,
                    "client_wall_ms": round(client_wall_ms, 4),
                    "provider_write_send_count": 0,
                }
            ],
        )
    episode = {
        "schema_version": 1,
        "lane": CONCURRENT_LANE,
        "config_id": server.config.config_id,
        "episode": episode_index,
        "j": 2,
        "submitted_jobs": 2,
        "successful_jobs": successful_jobs,
        "comparable_jobs": comparable_jobs,
        "episode_wall_ms": round(episode_wall_ms, 4),
        "burst_goodput_pages_per_second": round(comparable_jobs / (episode_wall_ms / 1000), 6),
        "backend_job_wall_ms": job_walls,
        "client_job_wall_ms": [round(value, 4) for value in client_walls],
        "episode_service_mcp_cpu_ms": round(cpu_ms, 4) if cpu_ms is not None else None,
        "cpu_ms_per_successful_page": (
            round(cpu_ms / successful_jobs, 4) if cpu_ms is not None and successful_jobs else None
        ),
        "job_admission_wait_ms": None,
        "mcp_queue_wait_ms": None,
        "job_queue_peak": None,
        "job_queue_end": None,
        "provider_write_send_count": 0,
    }
    _append_jsonl(result_dir / "episodes.jsonl", [episode])
    _append_jsonl(result_dir / "probe_samples.jsonl", probe_rows)
    _append_jsonl(
        result_dir / "resources.jsonl",
        (
            {
                "lane": CONCURRENT_LANE,
                "config_id": server.config.config_id,
                "episode": episode_index,
                "subblock": server.subblock,
                **row,
            }
            for row in resources
        ),
    )
    return episode, expected_hmac


def _concurrent_confirm(arguments: argparse.Namespace) -> int:
    result_dir = arguments.result_dir.resolve()
    if any(
        row.get("lane") == CONCURRENT_LANE for row in _read_jsonl(result_dir / "episodes.jsonl")
    ):
        raise RuntimeError("concurrent confirmation episodes already exist")
    configs = _selected_concurrent_configs(result_dir)
    hmac_key = secrets.token_bytes(32)
    expected_hmac: str | None = None
    last_episode_started = 0.0
    episode_by_config = {config.config_id: 0 for config in configs}
    blocked = False
    for subblock in range(1, 11):
        for config in configs:
            server = _start_local_server(
                result_dir, config=config, lane=CONCURRENT_LANE, subblock=subblock
            )
            try:
                for index in range(100):
                    duration_ms, success = _probe(server.client)
                    _append_jsonl(
                        result_dir / "probe_samples.jsonl",
                        [
                            {
                                "lane": CONCURRENT_LANE,
                                "config_id": config.config_id,
                                "subblock": subblock,
                                "probe_kind": "IDLE" if subblock == 1 else "RESTART_WARMUP",
                                "probe_index": index + 1,
                                "duration_ms": round(duration_ms, 4),
                                "success": success,
                            }
                        ],
                    )
                    if subblock != 1 and index == 0:
                        break
                warmup_delay = max(
                    0.0,
                    arguments.episode_pacing_seconds - (time.monotonic() - last_episode_started),
                )
                if warmup_delay:
                    time.sleep(warmup_delay)
                last_episode_started = time.monotonic()
                warmup, expected_hmac = _record_local_request(
                    server,
                    result_dir,
                    lane=CONCURRENT_LANE,
                    sample_kind="WARMUP",
                    trial_id=f"j2-warmup-{subblock:02d}-{config.config_id}",
                    block=None,
                    operation_index=1,
                    hmac_key=hmac_key,
                    expected_hmac=expected_hmac,
                )
                if warmup["measurement_validity"] != "COMPARABLE":
                    blocked = True
                    print("STOPPED: J2_WARMUP_INVALID", flush=True)
                for local_episode in range(5):
                    if blocked:
                        break
                    delay = max(
                        0.0,
                        arguments.episode_pacing_seconds
                        - (time.monotonic() - last_episode_started),
                    )
                    if delay:
                        time.sleep(delay)
                    last_episode_started = time.monotonic()
                    episode_by_config[config.config_id] += 1
                    episode_index = episode_by_config[config.config_id]
                    episode, expected_hmac = _concurrent_episode(
                        server,
                        result_dir,
                        episode_index=episode_index,
                        first_operation_index=2 + local_episode * 2,
                        hmac_key=hmac_key,
                        expected_hmac=expected_hmac,
                    )
                    if episode["comparable_jobs"] != 2:
                        blocked = True
                        print("STOPPED: J2_EPISODE_INVALID", flush=True)
                        break
                    print(
                        f"j2-progress={config.config_id}:{episode_index}/50 "
                        f"episode_wall_ms={episode['episode_wall_ms']}",
                        flush=True,
                    )
                time.sleep(3)
                settled = {
                    role: _process_snapshot(process_id)
                    for role, process_id in _local_process_roles(server).items()
                }
                _append_jsonl(
                    result_dir / "resource_settled.jsonl",
                    [
                        {
                            "lane": CONCURRENT_LANE,
                            "config_id": config.config_id,
                            "subblock": subblock,
                            "process_role": role,
                            **snapshot,
                        }
                        for role, snapshot in settled.items()
                    ],
                )
            finally:
                _stop_local_server(server, result_dir, lane=CONCURRENT_LANE)
            if blocked:
                break
        if blocked:
            break
    _summarize_concurrent(result_dir)
    return 1 if blocked else 0


def _summarize_concurrent(result_dir: Path) -> dict[str, object]:
    episodes = [
        row
        for row in _read_jsonl(result_dir / "episodes.jsonl")
        if row.get("lane") == CONCURRENT_LANE
    ]
    trials = [
        row
        for row in _read_jsonl(result_dir / "trials.jsonl")
        if row.get("lane") == CONCURRENT_LANE and row.get("sample_kind") == "MEASURED"
    ]
    probes = [
        row
        for row in _read_jsonl(result_dir / "probe_samples.jsonl")
        if row.get("lane") == CONCURRENT_LANE
    ]
    summaries: list[dict[str, object]] = []
    for config in _selected_concurrent_configs(result_dir):
        config_episodes = [row for row in episodes if row.get("config_id") == config.config_id]
        config_trials = [row for row in trials if row.get("config_id") == config.config_id]
        backend_walls = [
            float(row["backend_wall_ms"])
            for row in config_trials
            if row.get("measurement_validity") == "COMPARABLE"
        ]
        idle_probes = [
            float(row["duration_ms"])
            for row in probes
            if row.get("config_id") == config.config_id
            and row.get("probe_kind") == "IDLE"
            and row.get("success") is True
        ]
        during_probes = [
            float(row["duration_ms"])
            for row in probes
            if row.get("config_id") == config.config_id
            and row.get("probe_kind") == "DURING"
            and row.get("success") is True
        ]
        burst_seconds = sum(float(row["episode_wall_ms"]) for row in config_episodes) / 1000
        successful = sum(int(row["successful_jobs"]) for row in config_episodes)
        summaries.append(
            {
                **asdict(config),
                "j": 2,
                "episodes": len(config_episodes),
                "actual_jobs": len(config_trials),
                "successful_jobs": successful,
                "backend_p95_ms": _percentile(backend_walls, 0.95),
                "burst_goodput_pages_per_second": (
                    successful / burst_seconds if burst_seconds else None
                ),
                "cpu_ms_per_successful_page_mean": _mean(
                    [
                        float(row["cpu_ms_per_successful_page"])
                        for row in config_episodes
                        if row.get("cpu_ms_per_successful_page") is not None
                    ]
                ),
                "idle_probe_p95_ms": _percentile(idle_probes, 0.95),
                "during_probe_p95_ms": _percentile(during_probes, 0.95),
                "probe_timeouts": sum(
                    row.get("config_id") == config.config_id and row.get("success") is not True
                    for row in probes
                ),
                "job_admission_wait_ms": None,
                "mcp_queue_wait_ms": None,
                "job_queue_peak_end": None,
                "provider_write_send_count": 0,
                "status": "COMPLETE" if len(config_episodes) == 50 else "INCOMPLETE",
            }
        )
    output = {
        "schema_version": 1,
        "lane": CONCURRENT_LANE,
        "configs": summaries,
        "unsupported_metrics": [
            "job_admission_wait_ms",
            "mcp_queue_wait_ms",
            "job_queue_peak_end",
            "system_cpu_pct",
            "context_switches",
            "gc_metrics",
        ],
        "provider_write_send_count": 0,
    }
    _write_json(result_dir / "summary_resource_efficiency.json", output)
    return output


def _finalize_report(result_dir: Path) -> None:
    provider = cast(
        dict[str, Any],
        json.loads((result_dir / "summary_provider.json").read_text(encoding="utf-8")),
    )
    backend = cast(
        dict[str, Any],
        json.loads((result_dir / "summary_backend.json").read_text(encoding="utf-8")),
    )
    resource = cast(
        dict[str, Any],
        json.loads((result_dir / "summary_resource_efficiency.json").read_text(encoding="utf-8")),
    )
    selected = str(backend.get("selected_config"))
    selected_config = CONFIG_BY_ID[selected]
    provider_row = next(
        row
        for row in cast(list[dict[str, Any]], provider["configs"])
        if row["config_id"] == selected
    )
    backend_row = next(
        row
        for row in cast(list[dict[str, Any]], backend["configs"])
        if row["config_id"] == selected
    )
    resource_row = next(
        row
        for row in cast(list[dict[str, Any]], resource["configs"])
        if row["config_id"] == selected
    )
    lines = [
        "# Gmail metadata hydration benchmark decision",
        "",
        f"- Selected: `{selected}` (transport={selected_config.transport}, "
        f"B={selected_config.batch_size}, W={selected_config.http_concurrency_limit})",
        f"- Provider sweep: {provider_row['attempted']}/100 attempted, "
        f"p95={float(provider_row['operation_p95_ms']):.2f}ms, "
        f"HTTP mean={float(provider_row['actual_http_mean']):.2f}",
        f"- Local API confirmation: {backend_row['attempted']}/100 attempted, "
        f"p95={float(backend_row['backend_p95_ms']):.2f}ms",
        f"- J=2: {resource_row['episodes']}/50 episodes, "
        f"backend p95={float(resource_row['backend_p95_ms']):.2f}ms, "
        f"during-probe p95={float(resource_row['during_probe_p95_ms']):.2f}ms",
        "- Provider Gmail WRITE/SEND: 0",
        "- Dataset query, resource IDs, Gmail text, OAuth material, and Authorization headers "
        "were not persisted.",
        "",
        "Selection follows contract/reliability first, Pareto filtering, then the predeclared "
        "tie range `max(50ms, 10% of fastest valid p95)` with CPU and implementation "
        "simplicity as tie-breakers. The conclusion is local to this PC, account, fixed N=20 "
        "metadata fixture, and observed network period.",
        "",
        "Reaggregate:",
        "",
        "```powershell",
        ".\\.venv\\Scripts\\python.exe scripts\\benchmark_gmail_metadata_hydration.py "
        f'summarize-provider --result-dir "{result_dir}"',
        ".\\.venv\\Scripts\\python.exe scripts\\benchmark_gmail_metadata_hydration.py "
        f'summarize-backend --result-dir "{result_dir}"',
        ".\\.venv\\Scripts\\python.exe scripts\\benchmark_gmail_metadata_hydration.py "
        f'summarize-concurrent --result-dir "{result_dir}"',
        "```",
    ]
    (result_dir / "decision.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    manifest_path = result_dir / "experiment_manifest.json"
    manifest = cast(dict[str, Any], json.loads(manifest_path.read_text(encoding="utf-8")))
    manifest["completed_at_utc"] = datetime.now(UTC).isoformat()
    manifest["selected_config"] = asdict(selected_config)
    manifest["provider_write_send_count"] = 0
    manifest["raw_artifacts"] = [
        "trials.jsonl",
        "http_attempts.jsonl",
        "batch_parts.jsonl",
        "resources.jsonl",
        "episodes.jsonl",
        "probe_samples.jsonl",
    ]
    _write_json(manifest_path, manifest)


def _parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("provider-worker")
    sweep = subparsers.add_parser("provider-sweep")
    sweep.add_argument("--result-dir", type=Path, default=DEFAULT_RESULT_DIR)
    sweep.add_argument("--warmups", type=int, default=5)
    sweep.add_argument("--blocks", type=int, default=100)
    sweep.add_argument("--pacing-seconds", type=float, default=PACING_SECONDS)
    summarize = subparsers.add_parser("summarize-provider")
    summarize.add_argument("--result-dir", type=Path, default=DEFAULT_RESULT_DIR)
    local = subparsers.add_parser("local-confirm")
    local.add_argument("--result-dir", type=Path, default=DEFAULT_RESULT_DIR)
    local.add_argument("--pacing-seconds", type=float, default=PACING_SECONDS)
    concurrent = subparsers.add_parser("concurrent-confirm")
    concurrent.add_argument("--result-dir", type=Path, default=DEFAULT_RESULT_DIR)
    concurrent.add_argument("--episode-pacing-seconds", type=float, default=PACING_SECONDS * 2)
    summarize_backend = subparsers.add_parser("summarize-backend")
    summarize_backend.add_argument("--result-dir", type=Path, default=DEFAULT_RESULT_DIR)
    summarize_concurrent = subparsers.add_parser("summarize-concurrent")
    summarize_concurrent.add_argument("--result-dir", type=Path, default=DEFAULT_RESULT_DIR)
    finalize = subparsers.add_parser("finalize-report")
    finalize.add_argument("--result-dir", type=Path, default=DEFAULT_RESULT_DIR)
    return parser.parse_args()


def main() -> NoReturn:
    arguments = _parse_arguments()
    if arguments.command == "provider-worker":
        _provider_worker()
    if arguments.command == "provider-sweep":
        raise SystemExit(_provider_sweep(arguments))
    if arguments.command == "summarize-provider":
        _summarize_provider(arguments.result_dir.resolve())
        raise SystemExit(0)
    if arguments.command == "local-confirm":
        raise SystemExit(_local_confirm(arguments))
    if arguments.command == "concurrent-confirm":
        raise SystemExit(_concurrent_confirm(arguments))
    if arguments.command == "summarize-backend":
        _summarize_backend(arguments.result_dir.resolve())
        raise SystemExit(0)
    if arguments.command == "summarize-concurrent":
        _summarize_concurrent(arguments.result_dir.resolve())
        raise SystemExit(0)
    if arguments.command == "finalize-report":
        _finalize_report(arguments.result_dir.resolve())
        raise SystemExit(0)
    raise SystemExit(2)


if __name__ == "__main__":
    main()
