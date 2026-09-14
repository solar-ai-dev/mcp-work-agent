"""Benchmark the production Gmail READ boundary from ``execute_read_node``.

The benchmark intentionally skips upstream Agent/LLM decisions.  It materializes
one immutable SEARCH plan and registry binding, then invokes the production node
with fresh run/cache handles for every actual Google Provider READ.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import threading
import time
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass, fields
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory, gettempdir
from typing import Any, cast
from uuid import uuid4

from scripts.benchmark_gmail_metadata_hydration import (
    CONFIG_BY_ID,
    PACING_SECONDS,
    ROOT,
    SEED,
    BenchmarkConfig,
    _append_jsonl,
    _mean,
    _percentile,
    _process_snapshot,
    _read_jsonl,
    _sha256_file,
    _windows_descendants,
    _write_json,
)

from google_work_agent.adapters.langgraph.subgraphs.retrieval.nodes.execute_read_node import (
    execute_read_node,
)
from google_work_agent.adapters.langgraph.subgraphs.retrieval.projections import (
    execute_read_projection,
)
from google_work_agent.adapters.llm.runtime.llm_credential_router import SessionMemorySecretStore
from google_work_agent.api.composition import ProductionRuntimeConfig, build_production_runtime
from google_work_agent.application.agents.retrieval.build_query import (
    RouteConstraintPolicy,
    build_query,
)
from google_work_agent.application.agents.retrieval.contracts.query_plan import SourceFetchPlanV1
from google_work_agent.application.agents.tool_routing.contracts.tool_route_plan import (
    InputToolRouteV1,
)
from google_work_agent.application.tool_registry.load_signed_tool_registry import (
    load_signed_tool_registry,
)
from google_work_agent.application.use_cases.connection.get_connection_status import (
    GetConnectionStatusQuery,
)
from google_work_agent.application.use_cases.run.account_provider_dispatch import (
    provider_dispatch_execution_scope,
)
from google_work_agent.application.use_cases.run.guard_run_budget import build_default_run_budget
from google_work_agent.ports.connector.connector_read_port import (
    ConnectorReadPort,
    ConnectorReadResultV1,
    JsonValue,
)
from google_work_agent.ports.system.run_retrieval_cache_port import RunRetrievalCachePort

NODE_LANE = "LIVE_PRODUCTION_EXECUTE_READ_NODE"
NODE_CONFIG_IDS = ("S3_BASELINE", "B20W1")
RESULT_DIR = ROOT / "evaluation" / "results" / "gmail-metadata-hydration-20260914-7afac9f5"
MCP_MODULE = "scripts.gmail_metadata_benchmark_mcp"
SAMPLE_INTERVAL_SECONDS = 0.1
FIXED_START_LOCAL = "2026-06-01T00:00:00"
FIXED_END_LOCAL = "2026-07-01T00:00:00"
FIXED_TIMEZONE = "America/Los_Angeles"
EXPECTED_FIXED_QUERY = "after:1780297200 before:1782889200"

GMAIL_ROUTE: InputToolRouteV1 = {
    "route_id": "gmail-recent-threads",
    "connector_id": "google_workspace",
    "resource_type": "GMAIL_THREAD",
    "allowed_read_tool_ids": ["gmail_search_threads"],
    "required": True,
    "reason_codes": ["USER_REQUEST"],
}


@dataclass(slots=True)
class RuntimeBinding:
    config: BenchmarkConfig
    container: Any
    connector_reader: ConnectorReadPort
    cache: RunRetrievalCachePort
    registry: Any
    config_path: Path
    event_path: Path
    temp_directory: TemporaryDirectory[str]
    process_ids: tuple[int, ...]
    event_offset: int = 0


class TimedConnectorReadPort:
    """Observe the production ConnectorReadPort without changing its result."""

    def __init__(self, delegate: ConnectorReadPort) -> None:
        self._delegate = delegate
        self.wall_ms: float | None = None

    def execute_read(self, binding: Any, arguments: dict[str, JsonValue]) -> ConnectorReadResultV1:
        started = time.perf_counter_ns()
        try:
            return self._delegate.execute_read(binding, arguments)
        finally:
            self.wall_ms = (time.perf_counter_ns() - started) / 1_000_000


class CombinedResourceSampler:
    """Sample one node process and its production runtime child processes."""

    def __init__(self, process_ids: Sequence[int]) -> None:
        self._process_ids = tuple(dict.fromkeys(process_ids))
        self._stop = threading.Event()
        self._rows: list[dict[str, object]] = []
        self._thread: threading.Thread | None = None
        self._cpu_start: dict[int, int] = {}

    def start(self) -> None:
        initial = self._snapshot()
        self._cpu_start = cast(dict[int, int], initial.pop("cpu_counters"))
        self._rows = [initial]
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self) -> tuple[dict[str, object], list[dict[str, object]]]:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2)
        final = self._snapshot()
        counters = cast(dict[int, int], final.pop("cpu_counters"))
        cpu_ms = (
            sum(
                max(0, counters.get(process_id, start) - start)
                for process_id, start in self._cpu_start.items()
            )
            / 10_000
        )
        final["cpu_time_ms"] = round(cpu_ms, 4)
        self._rows.append(final)
        return final, list(self._rows)

    def _loop(self) -> None:
        while not self._stop.wait(SAMPLE_INTERVAL_SECONDS):
            row = self._snapshot()
            row.pop("cpu_counters", None)
            self._rows.append(row)

    def _snapshot(self) -> dict[str, object]:
        snapshots = {process_id: _process_snapshot(process_id) for process_id in self._process_ids}
        cpu_counters = {
            process_id: value
            for process_id, snapshot in snapshots.items()
            if isinstance((value := snapshot.get("cpu_counter_100ns")), int)
        }
        return {
            "relative_time_ns": time.perf_counter_ns(),
            "rss_bytes": _sum_metric(snapshots.values(), "working_set_bytes"),
            "private_bytes": _sum_metric(snapshots.values(), "private_bytes"),
            "thread_count": _sum_metric(snapshots.values(), "os_threads"),
            "handle_count": _sum_metric(snapshots.values(), "handle_count"),
            "process_count": len(cpu_counters),
            "cpu_counters": cpu_counters,
        }


def _sum_metric(rows: Iterable[Mapping[str, object]], key: str) -> int | None:
    values = [row.get(key) for row in rows]
    observed = [value for value in values if isinstance(value, int)]
    return sum(observed) if observed else None


def _maximum(rows: Sequence[Mapping[str, object]], key: str) -> int | None:
    values = [value for row in rows if isinstance((value := row.get(key)), int)]
    return max(values) if values else None


def _load_oauth_client_id() -> str:
    value = os.environ.get("GOOGLE_OAUTH_CLIENT_ID", "").strip()
    if value:
        return value
    env_path = ROOT / ".env.local"
    if env_path.exists():
        for raw_line in env_path.read_text(encoding="utf-8").splitlines():
            key, separator, raw_value = raw_line.partition("=")
            if separator and key.strip() == "GOOGLE_OAUTH_CLIENT_ID":
                value = raw_value.strip().strip("\"'")
                if value:
                    return value
    return "development-client-id"


def _write_mcp_config(directory: Path, config: BenchmarkConfig) -> tuple[Path, Path]:
    event_path = directory / "mcp-events.jsonl"
    config_path = Path(gettempdir()) / "gwa-gmail-metadata-benchmark-config.json"
    if config_path.exists():
        raise RuntimeError("another Gmail metadata benchmark MCP configuration is active")
    _write_json(
        config_path,
        {
            "transport": config.transport,
            "batch_size": config.batch_size,
            "http_concurrency_limit": config.http_concurrency_limit,
            "event_path": str(event_path),
        },
    )
    return config_path, event_path


def _build_runtime(config: BenchmarkConfig) -> RuntimeBinding:
    temporary = TemporaryDirectory(
        prefix=f"gwa-node-{config.config_id.lower()}-", ignore_cleanup_errors=True
    )
    directory = Path(temporary.name)
    config_path, event_path = _write_mcp_config(directory, config)
    before = set(_windows_descendants(os.getpid()))
    try:
        runtime_config = ProductionRuntimeConfig.development(
            runtime_root=directory / "runtime",
            working_directory=ROOT,
            mcp_manifest_version="2026-08-07.p0",
            oauth_client_id=_load_oauth_client_id(),
            mcp_module_name=MCP_MODULE,
            keyring_store=SessionMemorySecretStore(),
        )
        container = build_production_runtime(
            **{field.name: getattr(runtime_config, field.name) for field in fields(runtime_config)},
            bootstrap_secret=uuid4().hex,
            service_instance_id=f"node-benchmark-{config.config_id.lower()}-{uuid4()}",
        )
    except Exception:
        config_path.unlink(missing_ok=True)
        temporary.cleanup()
        raise
    descendants = tuple(sorted(set(_windows_descendants(os.getpid())) - before))
    action_gateway = cast(Any, container.action_gateway)
    workflow_runtime = cast(Any, container.workflow_runtime)
    if action_gateway is None:
        raise RuntimeError("production ConnectorReadPort is unavailable")
    return RuntimeBinding(
        config=config,
        container=container,
        connector_reader=cast(ConnectorReadPort, action_gateway.connector_reader),
        cache=cast(RunRetrievalCachePort, workflow_runtime._read_result_cache),
        registry=action_gateway.tool_registry,
        config_path=config_path,
        event_path=event_path,
        temp_directory=temporary,
        process_ids=descendants,
    )


def _close_runtime(runtime: RuntimeBinding) -> None:
    try:
        for callback in reversed(runtime.container.shutdown_callbacks):
            callback()
    finally:
        runtime.config_path.unlink(missing_ok=True)
        runtime.temp_directory.cleanup()


def _materialize_input(registry: Any) -> tuple[SourceFetchPlanV1, Any, dict[str, JsonValue]]:
    query_plan = {
        "schema_version": 2,
        "route_queries": [
            {
                "route_id": GMAIL_ROUTE["route_id"],
                "operation": "SEARCH",
                "reason_codes": ["USER_REQUEST"],
                "search_spec": {
                    "mode": "INITIAL",
                    "constraints": [
                        {
                            "kind": "TEMPORAL_RANGE",
                            "axis": "MESSAGE_TIME",
                            "start_local": FIXED_START_LOCAL,
                            "end_local": FIXED_END_LOCAL,
                            "timezone": FIXED_TIMEZONE,
                        }
                    ],
                },
                "detail_candidate_ref": None,
            }
        ],
    }
    plan = build_query(
        query_plan,
        frozen_routes=[GMAIL_ROUTE],
        route_policies={
            GMAIL_ROUTE["route_id"]: RouteConstraintPolicy(frozenset({"TEMPORAL_RANGE"}))
        },
    )[0]
    tool_id, arguments = execute_read_projection.project_connector_call(
        plan, route=GMAIL_ROUTE, page_size=20
    )
    binding = registry.bind_required("google_workspace", tool_id, "READ")
    projected_query = arguments.get("query")
    if (
        projected_query != EXPECTED_FIXED_QUERY
        or arguments.get("page_size") != 20
        or arguments.get("include_thread_metadata") is not True
    ):
        raise RuntimeError("production projection did not materialize the required Gmail input")
    return plan, binding, arguments


def _read_new_events(runtime: RuntimeBinding) -> list[dict[str, Any]]:
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        rows = _read_jsonl(runtime.event_path)
        if len(rows) > runtime.event_offset:
            new_rows = rows[runtime.event_offset :]
            runtime.event_offset = len(rows)
            return new_rows
        time.sleep(0.02)
    return []


def _identity_values(result: ConnectorReadResultV1) -> list[str]:
    items = result.output.get("items")
    if not isinstance(items, list):
        return []
    return [
        f"{item.get('resource_type', '')}:{item.get('resource_id', '')}"
        for item in items
        if isinstance(item, Mapping)
    ]


def _identity_hash(result: ConnectorReadResultV1) -> str:
    serialized = json.dumps(_identity_values(result), separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(serialized.encode()).hexdigest()


def _metadata_hash(result: ConnectorReadResultV1) -> str:
    items = result.output.get("items")
    safe_projection = [
        {
            "resource_type": item.get("resource_type"),
            "parent_id": item.get("parent_id"),
            "related_resource_ids": item.get("related_resource_ids"),
            "version": item.get("version"),
            "payload": item.get("payload"),
        }
        for item in (items if isinstance(items, list) else [])
        if isinstance(item, Mapping)
    ]
    serialized = json.dumps(
        safe_projection, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )
    return hashlib.sha256(serialized.encode()).hexdigest()


def _result_count(result: ConnectorReadResultV1) -> int:
    items = result.output.get("items")
    return len(items) if isinstance(items, list) else 0


def _run_node_trial(
    runtime: RuntimeBinding,
    *,
    plan: SourceFetchPlanV1,
    binding: Any,
    arguments: dict[str, JsonValue],
    sample_kind: str,
    trial_id: str,
    block: int | None,
    expected: tuple[int, str, str, str | None] | None,
) -> tuple[
    dict[str, object],
    tuple[int, str, str, str | None] | None,
    list[dict[str, Any]],
    list[dict[str, object]],
]:
    run_id = f"node-run-{uuid4()}"
    read_handle = f"node-read-{uuid4()}"
    observed_reader = TimedConnectorReadPort(runtime.connector_reader)
    sampler = CombinedResourceSampler((os.getpid(), *runtime.process_ids))
    sampler.start()
    started = time.perf_counter_ns()
    safe_error_code: str | None = None
    node_payload: dict[str, object] | None = None
    try:
        with provider_dispatch_execution_scope(
            run_id=run_id, now_ms=lambda: int(time.time() * 1000)
        ):
            node_payload = execute_read_node(
                {
                    "operation_inputs": {
                        "execute_read": {
                            "plan": plan,
                            "run_id": run_id,
                            "binding": binding,
                            "tool_arguments": dict(arguments),
                            "connector_reader": observed_reader,
                            "read_result_cache": runtime.cache,
                            "read_result_handle": read_handle,
                            "run_budget": build_default_run_budget(
                                started_at_ms=int(time.time() * 1000)
                            ),
                            "now_ms": int(time.time() * 1000),
                            "prior_query_attempts": [],
                        }
                    }
                }
            )
    except Exception as error:
        safe_error_code = getattr(error, "detail_code", None) or type(error).__name__
    node_latency_ms = (time.perf_counter_ns() - started) / 1_000_000
    final_resource, resource_rows = sampler.stop()
    events = _read_new_events(runtime)

    execution = None if node_payload is None else node_payload.get("read_execution")
    cache_resolution = runtime.cache.resolve_read_result(
        read_handle, run_id, plan["route_id"], plan["query_identity_hash"]
    )
    entry = cache_resolution.entry
    read_result = None if entry is None else entry.read_result
    count = _result_count(read_result) if read_result is not None else 0
    identity_hash = _identity_hash(read_result) if read_result is not None else ""
    metadata_hash = _metadata_hash(read_result) if read_result is not None else ""
    next_page_token = None if read_result is None else read_result.next_page_token
    if expected is None and read_result is not None and count == 20:
        expected = (count, identity_hash, metadata_hash, next_page_token)
    identity_matches = (
        expected is not None and count == expected[0] and identity_hash == expected[1]
    )
    metadata_matches = expected is not None and metadata_hash == expected[2]
    next_page_matches = expected is not None and next_page_token == expected[3]
    matches = identity_matches and metadata_matches and next_page_matches
    status = getattr(execution, "status", None)
    provider_called = getattr(execution, "provider_called", None)
    candidate_count = getattr(execution, "candidate_count", None)
    execution_success = (
        status == "COMPLETE"
        and provider_called is True
        and candidate_count == 20
        and cache_resolution.status in {"FOUND", "EXHAUSTED"}
        and entry is not None
    )
    event_finished = [row for row in events if row.get("record_type") == "HTTP_FINISHED"]
    batch_parts = [row for row in events if row.get("record_type") == "BATCH_PART"]
    phase_rows = [row for row in events if row.get("record_type") == "PHASE"]
    provider_wall_ms = sum(
        float(row["duration_ms"])
        for row in phase_rows
        if isinstance(row.get("duration_ms"), (int, float))
    )
    logical_calls = sum(
        int(row["inner_count"]) if isinstance(row.get("inner_count"), int) else 1
        for row in event_finished
    )
    has_429 = any(row.get("status_code") == 429 for row in [*event_finished, *batch_parts])
    has_rate_limit = has_429 or any(
        row.get("safe_error_code") == "RATE_LIMITED" for row in [*event_finished, *batch_parts]
    )
    has_5xx = any(
        isinstance(row.get("status_code"), int) and 500 <= int(row["status_code"]) <= 599
        for row in [*event_finished, *batch_parts]
    )
    has_timeout = any(row.get("safe_error_code") == "TIMEOUT" for row in event_finished)
    data_status = "MATCH" if matches else "DATASET_DRIFT"
    if safe_error_code is not None or not execution_success:
        validity = "ERROR"
    elif not matches:
        validity = "DATASET_DRIFT"
    else:
        validity = "COMPARABLE"
    trial = {
        "schema_version": 1,
        "lane": NODE_LANE,
        "sample_kind": sample_kind,
        "trial_id": trial_id,
        "block": block,
        "config_id": runtime.config.config_id,
        "started_at_utc": datetime.now(UTC).isoformat(),
        "node_status": status,
        "provider_called": provider_called,
        "candidate_count": candidate_count,
        "cache_resolution_status": cache_resolution.status,
        "cache_result_present": entry is not None,
        "resource_count": count,
        "resource_identity_order_match": identity_matches,
        "metadata_projection_match": metadata_matches,
        "next_page_token_match": next_page_matches,
        "dataset_status": data_status,
        "measurement_validity": validity,
        "safe_error_code": safe_error_code,
        "node_latency_ms": round(node_latency_ms, 4),
        "provider_wall_ms": round(provider_wall_ms, 4) if phase_rows else None,
        "mcp_wall_ms": (
            round(observed_reader.wall_ms, 4) if observed_reader.wall_ms is not None else None
        ),
        "physical_http_request_count": len(event_finished),
        "logical_provider_call_count": logical_calls,
        "cpu_time_ms": final_resource.get("cpu_time_ms"),
        "peak_rss_bytes": _maximum(resource_rows, "rss_bytes"),
        "peak_private_bytes": _maximum(resource_rows, "private_bytes"),
        "peak_thread_count": _maximum(resource_rows, "thread_count"),
        "context_switch_delta": None,
        "context_switch_unavailable_reason": "WINDOWS_PER_PROCESS_COUNTER_NOT_EXPOSED",
        "is_timeout": has_timeout,
        "is_429": has_429,
        "is_rate_limited": has_rate_limit,
        "is_5xx": has_5xx,
        "provider_write_send_count": 0,
        "retry_count": 0,
    }
    runtime.cache.discard_run(run_id)
    safe_events = [
        {
            "schema_version": 1,
            "trial_id": trial_id,
            "config_id": runtime.config.config_id,
            "record_type": row.get("record_type"),
            "attempt_index": row.get("attempt_index"),
            "ordinal": row.get("ordinal"),
            "kind": row.get("kind"),
            "method": row.get("method"),
            "inner_count": row.get("inner_count"),
            "status_code": row.get("status_code"),
            "response_body_bytes": row.get("response_body_bytes"),
            "duration_ms": row.get("duration_ms"),
            "result_seen": row.get("result_seen"),
            "safe_error_code": row.get("safe_error_code"),
        }
        for row in events
        if row.get("record_type") in {"HTTP_FINISHED", "BATCH_PART"}
    ]
    safe_resources = [
        {
            "schema_version": 1,
            "trial_id": trial_id,
            "config_id": runtime.config.config_id,
            **row,
        }
        for row in resource_rows
    ]
    return trial, expected, safe_events, safe_resources


def _append_trial_artifacts(
    result_dir: Path,
    trial: Mapping[str, object],
    events: Sequence[Mapping[str, object]] = (),
    resources: Sequence[Mapping[str, object]] = (),
) -> None:
    _append_jsonl(result_dir / "node_trials.jsonl", [trial])
    if events:
        _append_jsonl(result_dir / "node_http_attempts.jsonl", events)
    if resources:
        _append_jsonl(result_dir / "node_resources.jsonl", resources)


def _summary(result_dir: Path) -> dict[str, object]:
    rows = [
        row
        for row in _read_jsonl(result_dir / "node_trials.jsonl")
        if row.get("sample_kind") == "MEASURED"
    ]
    configs: list[dict[str, object]] = []
    for config_id in NODE_CONFIG_IDS:
        selected = [row for row in rows if row.get("config_id") == config_id]
        comparable = [row for row in selected if row.get("measurement_validity") == "COMPARABLE"]

        def values(key: str, source: Sequence[Mapping[str, object]] = comparable) -> list[float]:
            result: list[float] = []
            for row in source:
                value = row.get(key)
                if isinstance(value, (int, float)):
                    result.append(float(value))
            return result

        node_values = values("node_latency_ms")
        configs.append(
            {
                "config_id": config_id,
                "planned_attempts": 100,
                "observed_attempts": len(selected),
                "comparable_attempts": len(comparable),
                "dataset_drift_count": sum(
                    row.get("measurement_validity") == "DATASET_DRIFT" for row in selected
                ),
                "error_rate": round(
                    sum(row.get("measurement_validity") == "ERROR" for row in selected)
                    / max(1, len(selected)),
                    6,
                ),
                "timeout_rate": round(
                    sum(row.get("is_timeout") is True for row in selected) / max(1, len(selected)),
                    6,
                ),
                "rate_429": round(
                    sum(row.get("is_429") is True for row in selected) / max(1, len(selected)), 6
                ),
                "rate_limited": round(
                    sum(row.get("is_rate_limited") is True for row in selected)
                    / max(1, len(selected)),
                    6,
                ),
                "rate_5xx": round(
                    sum(row.get("is_5xx") is True for row in selected) / max(1, len(selected)), 6
                ),
                "mean_node_latency_ms": _mean(node_values),
                "p50_node_latency_ms": _percentile(node_values, 0.5),
                "p95_node_latency_ms": _percentile(node_values, 0.95),
                "mean_provider_wall_ms": _mean(values("provider_wall_ms")),
                "mean_mcp_wall_ms": _mean(values("mcp_wall_ms")),
                "mean_physical_http_request_count": _mean(values("physical_http_request_count")),
                "mean_logical_provider_call_count": _mean(values("logical_provider_call_count")),
                "mean_cpu_time_ms": _mean(values("cpu_time_ms")),
                "max_peak_rss_bytes": max(values("peak_rss_bytes"), default=None),
                "max_peak_thread_count": max(values("peak_thread_count"), default=None),
                "context_switch_delta": None,
                "provider_write_send_count": sum(
                    int(row.get("provider_write_send_count", 0)) for row in selected
                ),
                "retry_count": sum(int(row.get("retry_count", 0)) for row in selected),
            }
        )
    by_id = {row["config_id"]: row for row in configs}
    baseline = by_id["S3_BASELINE"].get("p95_node_latency_ms")
    candidate = by_id["B20W1"].get("p95_node_latency_ms")
    improvement = (
        (float(baseline) - float(candidate)) / float(baseline) * 100
        if isinstance(baseline, (int, float)) and isinstance(candidate, (int, float)) and baseline
        else None
    )
    return {
        "schema_version": 1,
        "lane": NODE_LANE,
        "configs": configs,
        "selected_config": (
            "B20W1"
            if all(row["comparable_attempts"] == 100 for row in configs)
            and by_id["B20W1"]["error_rate"] == 0
            else None
        ),
        "candidate_p95_improvement_percent": (
            round(improvement, 4) if improvement is not None else None
        ),
        "provider_micro_benchmark_reported_separately": True,
    }


def run(arguments: argparse.Namespace) -> int:
    result_dir = arguments.result_dir.resolve()
    raw_path = result_dir / "node_trials.jsonl"
    if raw_path.exists() and raw_path.stat().st_size:
        raise RuntimeError("node benchmark raw trials already exist")
    configs = [CONFIG_BY_ID[config_id] for config_id in NODE_CONFIG_IDS]
    expected: tuple[int, str, str, str | None] | None = None
    canonical_registry = load_signed_tool_registry()
    fixture_runtime = _build_runtime(CONFIG_BY_ID["S3_BASELINE"])
    try:
        registry = fixture_runtime.registry
        if registry.entries_hash != canonical_registry.entries_hash:
            raise RuntimeError("production builder registry differs from current signed registry")
        plan, binding, arguments_payload = _materialize_input(registry)
        connection = fixture_runtime.container.get_connection_status_handler(
            GetConnectionStatusQuery(connector_id="google_workspace")
        ).connection
        if connection.connection_status != "CONNECTED":
            print("BLOCKED: REAUTH", flush=True)
            return 2
        manifest = {
            "schema_version": 1,
            "lane": NODE_LANE,
            "created_at_utc": datetime.now(UTC).isoformat(),
            "node_entrypoint": (
                "google_work_agent.adapters.langgraph.subgraphs.retrieval.nodes."
                "execute_read_node.execute_read_node"
            ),
            "boundary": [
                "execute_read_node",
                "retrieval.execute_read",
                "ConnectorReadPort",
                "Google Workspace MCP",
                "gmail_search_threads",
                "Google Provider",
                "RunRetrievalCache.put_read_result",
                "execute_read_node return",
            ],
            "upstream_llm_agent_calls": 0,
            "scenario": "Gmail fixed historical threads 20",
            "fixture_ref": "gmail_fixed_historical_page_v1",
            "validated_arguments": {
                "query": "FIXED_BOUNDED_QUERY_NOT_PERSISTED",
                "page_size": arguments_payload["page_size"],
                "include_thread_metadata": arguments_payload["include_thread_metadata"],
            },
            "fixture_query_persisted": False,
            "binding": {
                "schema_version": binding.schema_version,
                "connector_id": binding.connector_id,
                "resource_type": "GMAIL_THREAD",
                "tool_id": binding.tool_id,
                "effect": binding.effect,
                "input_schema_ref": binding.input_schema_ref,
                "output_schema_ref": binding.output_schema_ref,
                "registry_entry_hash": binding.registry_entry_hash,
                "registry_entries_hash": registry.entries_hash,
            },
            "plan": {
                "operation_kind": plan["operation_kind"],
                "prior_read_result_handle": plan["prior_read_result_handle"],
                "detail_candidate_ref": plan["detail_candidate_ref"],
                "prior_query_attempts": [],
                "query_identity_hash": plan["query_identity_hash"],
            },
            "configs": [asdict(config) for config in configs],
            "planned": {
                "warmups_per_config": arguments.warmups,
                "measured_per_config": arguments.blocks,
            },
            "pacing_seconds": arguments.pacing_seconds,
            "fresh_run_namespace_and_read_handle_per_trial": True,
            "mailbox_mutation_by_harness": False,
            "provider_write_send_count": 0,
            "source_hashes": {
                str(path.relative_to(ROOT)).replace("\\", "/"): _sha256_file(path)
                for path in (
                    ROOT
                    / (
                        "src/google_work_agent/adapters/langgraph/subgraphs/retrieval/"
                        "nodes/execute_read_node.py"
                    ),
                    ROOT / "src/google_work_agent/application/agents/retrieval/execute_read.py",
                    ROOT
                    / (
                        "src/google_work_agent/adapters/connectors/google/gmail/threads/"
                        "search_threads.py"
                    ),
                    Path(__file__).resolve(),
                )
            },
            "context_switch_metric": {
                "available": False,
                "reason": (
                    "Windows per-process cumulative counter is not exposed by the bundled runtime"
                ),
            },
        }
        _write_json(result_dir / "node_experiment_manifest.json", manifest)

        fixture_trial, expected, fixture_events, fixture_resources = _run_node_trial(
            fixture_runtime,
            plan=plan,
            binding=binding,
            arguments=arguments_payload,
            sample_kind="FIXTURE_PREFLIGHT",
            trial_id="node-fixture-preflight",
            block=None,
            expected=None,
        )
        _append_trial_artifacts(result_dir, fixture_trial, fixture_events, fixture_resources)
        if (
            expected is None
            or expected[0] != 20
            or fixture_trial["measurement_validity"] != "COMPARABLE"
        ):
            print("STOPPED: DATASET_PREFLIGHT_INVALID", flush=True)
            return 3
        _write_json(
            result_dir / "node_fixture.json",
            {
                "schema_version": 1,
                "expected_resource_count": expected[0],
                "expected_resource_ids_hash": expected[1],
                "raw_resource_ids_persisted": False,
                "raw_gmail_content_persisted": False,
            },
        )
    finally:
        _close_runtime(fixture_runtime)

    if expected is None:
        raise RuntimeError("node fixture was not materialized")
    schedule: list[tuple[str, int | None, str]] = []
    for warmup in range(1, arguments.warmups + 1):
        order = list(NODE_CONFIG_IDS)
        random.Random(SEED - warmup).shuffle(order)
        schedule.extend(("WARMUP", None, config_id) for config_id in order)
    for block_index in range(1, arguments.blocks + 1):
        order = list(NODE_CONFIG_IDS)
        random.Random(SEED + block_index).shuffle(order)
        schedule.extend(("MEASURED", block_index, config_id) for config_id in order)

    last_started = time.monotonic()
    measured = 0
    for ordinal, (sample_kind, block, config_id) in enumerate(schedule, start=1):
        runtime = _build_runtime(CONFIG_BY_ID[config_id])
        try:
            if runtime.registry.entries_hash != canonical_registry.entries_hash:
                raise RuntimeError("A/B production registries differ")
            delay = max(0.0, arguments.pacing_seconds - (time.monotonic() - last_started))
            if delay:
                time.sleep(delay)
            last_started = time.monotonic()
            trial_id = (
                f"node-warmup-{ordinal:03d}-{config_id}"
                if sample_kind == "WARMUP"
                else f"node-block-{block:03d}-{config_id}"
            )
            trial, expected, trial_events, trial_resources = _run_node_trial(
                runtime,
                plan=plan,
                binding=binding,
                arguments=arguments_payload,
                sample_kind=sample_kind,
                trial_id=trial_id,
                block=block,
                expected=expected,
            )
            _append_trial_artifacts(result_dir, trial, trial_events, trial_resources)
        finally:
            _close_runtime(runtime)
        if trial["measurement_validity"] == "DATASET_DRIFT":
            print(f"STOPPED: DATASET_DRIFT trial={trial_id}", flush=True)
            break
        if trial["is_rate_limited"] is True:
            print(f"STOPPED: RATE_LIMITED trial={trial_id}", flush=True)
            break
        if sample_kind == "MEASURED":
            measured += 1
            if measured % 10 == 0:
                print(
                    f"node-progress={measured}/{arguments.blocks * 2} trial={trial_id}",
                    flush=True,
                )
    summary = _summary(result_dir)
    _write_json(result_dir / "summary_node.json", summary)
    print(json.dumps(summary, sort_keys=True), flush=True)
    return 0 if summary["selected_config"] == "B20W1" else 4


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--result-dir", type=Path, default=RESULT_DIR)
    parser.add_argument("--warmups", type=int, default=5)
    parser.add_argument("--blocks", type=int, default=100)
    parser.add_argument("--pacing-seconds", type=float, default=PACING_SECONDS)
    parser.add_argument("--aggregate-only", action="store_true")
    arguments = parser.parse_args()
    if arguments.warmups < 0 or arguments.blocks < 1 or arguments.pacing_seconds < 0:
        parser.error("warmups, blocks, and pacing must be non-negative")
    if arguments.aggregate_only:
        summary = _summary(arguments.result_dir.resolve())
        _write_json(arguments.result_dir.resolve() / "summary_node.json", summary)
        print(json.dumps(summary, sort_keys=True))
        return
    raise SystemExit(run(arguments))


if __name__ == "__main__":
    main()
