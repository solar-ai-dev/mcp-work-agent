"""Run the frozen RU development dataset through the production RU subgraph only."""

# ruff: noqa: E402 -- direct script execution adds the repository root before local imports.

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import time
import urllib.request
import warnings
from collections.abc import Mapping, Sequence
from dataclasses import asdict, fields, is_dataclass
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Lock
from typing import Any, Literal, Protocol, cast
from uuid import UUID, uuid4

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from evaluation.ru_quality_dev_grader import (
    GRADER_VERSION,
    aggregate_ru_scores,
    grade_ru_case,
)
from langchain_core.callbacks import BaseCallbackHandler
from langgraph.errors import GraphInterrupt
from langsmith import Client

from google_work_agent.adapters.langgraph.main.state import initial_graph_state
from google_work_agent.adapters.langgraph.profiles.profile_registry import GraphProfile
from google_work_agent.adapters.langgraph.subgraphs.request_understanding.graph import (
    RequestUnderstandingSubgraph,
)
from google_work_agent.adapters.langgraph.subgraphs.request_understanding.state import (
    RequestUnderstandingStateV2,
)
from google_work_agent.adapters.llm.runtime.llm_credential_router import SessionMemorySecretStore
from google_work_agent.api.composition import ProductionRuntimeConfig, build_production_runtime
from google_work_agent.application.agents.request_understanding.contracts.request_intent import (
    RequestGoalSemanticValidationError,
    RequestUnderstandingValidationError,
)
from google_work_agent.application.agents.request_understanding.detect_ambiguity import (
    RequestAmbiguityValidationError,
)
from google_work_agent.application.prompt_runtime.prompt_registry import DEVELOPMENT_SMOKE
from google_work_agent.application.tool_registry.load_signed_tool_registry import (
    load_signed_tool_registry,
)
from google_work_agent.application.use_cases.conversation.create_conversation import (
    CreateConversationCommand,
)
from google_work_agent.application.use_cases.resource.issue_selection_handle import (
    ResourceSelectionHandlePayloadV1,
)
from google_work_agent.application.use_cases.run.account_provider_dispatch import (
    provider_dispatch_execution_scope,
)
from google_work_agent.application.use_cases.run.start_run import StartRunCommand
from google_work_agent.application.use_cases.setting.update_settings import UpdateSettingsCommand
from google_work_agent.domain.canonical import calculate_canonical_json_hash
from google_work_agent.ports.llm.structured_inference_contracts import (
    LLMErrorCode,
    LLMInvocationError,
    OutputSchemaDefinition,
    PromptReference,
)
from google_work_agent.ports.llm.structured_inference_port import (
    StructuredInferencePort,
    StructuredInferenceResultV1,
)
from google_work_agent.ports.persistence.trace_event_repository import TraceEventCursor
from google_work_agent.ports.system.contracts.workflow_execution import (
    SelectedResourceRef,
    WorkflowCorrelationContext,
    WorkflowStartRequest,
)
from google_work_agent.ports.system.external_call_trace_port import (
    ExternalCallTraceFinishV1,
    ExternalCallTraceHandleV1,
    ExternalCallTracePort,
    ExternalCallTraceStartV1,
)
from google_work_agent.ports.system.settings_port import SettingsPatchV1

DEFAULT_DATASET = (
    ROOT / "evaluation" / "development_datasets" / "agent" / "ru_quality_dev_v2.jsonl"
)
DEFAULT_RESULTS_ROOT = ROOT / "evaluation" / "results"
DEFAULT_LANGSMITH_PROJECT = "google-work-agent-development"
MODEL_ID: Literal["qwen3.5:9b"] = "qwen3.5:9b"
RUNTIME_MODE: Literal["LOCAL_GPU"] = "LOCAL_GPU"
ALLOWED_RU_NODES = frozenset(
    {"identify_goal", "identify_temporal_scope", "detect_ambiguity", "finalize_intent"}
)
_PROVIDER_FAILURE_CODES = frozenset(
    {
        LLMErrorCode.PROVIDER_UNAVAILABLE,
        LLMErrorCode.PROVIDER_RATE_LIMITED,
        LLMErrorCode.PROVIDER_SERVER_ERROR,
        LLMErrorCode.INVALID_PROVIDER_RESPONSE,
    }
)
_SAFE_TRACE_VALUE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}")


class _LangSmithTraceClient(Protocol):
    def create_run(
        self,
        name: str,
        inputs: dict[str, Any],
        run_type: str,
        **kwargs: Any,
    ) -> None: ...

    def update_run(self, run_id: UUID, **kwargs: Any) -> None: ...

    def flush(self, timeout: float | None = None) -> None: ...

    def close(self, timeout: float | None = None) -> None: ...


class RuEvaluationLangSmithTrace(BaseCallbackHandler):
    """Emit payload-free root and external-call traces for one evaluation case."""

    def __init__(
        self,
        *,
        api_key: str,
        project_name: str,
        experiment_id: str,
        case_id: str,
        code_sha: str,
        model_id: str,
        model_digest: str,
        runtime_mode: str,
        product_run_id: str,
        client: _LangSmithTraceClient | None = None,
    ) -> None:
        metadata = {
            "experiment_id": experiment_id,
            "case_id": case_id,
            "code_sha": code_sha,
            "model_id": model_id,
            "model_digest": model_digest,
            "runtime_mode": runtime_mode,
            "domain_run_id": product_run_id,
        }
        if not api_key.strip():
            raise ValueError("LangSmith API key is required")
        if not _SAFE_TRACE_VALUE.fullmatch(project_name):
            raise ValueError("LangSmith project name must be a safe opaque identifier")
        if any(not _SAFE_TRACE_VALUE.fullmatch(value) for value in metadata.values()):
            raise ValueError("RU evaluation trace metadata must use safe opaque identifiers")
        self._client = client or Client(
            api_url="https://api.smith.langchain.com",
            api_key=api_key.strip(),
            auto_batch_tracing=False,
            hide_inputs=True,
            hide_outputs=True,
            omit_traced_runtime_info=True,
        )
        self._project_name = project_name
        self._metadata = metadata
        self._product_run_id = product_run_id
        self._lock = Lock()
        self._root: tuple[UUID, str] | None = None
        self._children: dict[UUID, tuple[UUID, str]] = {}
        self.root_trace_id: str | None = None
        self.trace_error: str | None = None

    def on_chain_start(
        self,
        serialized: Any,
        inputs: Any,
        *,
        run_id: UUID,
        parent_run_id: UUID | None = None,
        metadata: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> None:
        del serialized, inputs, kwargs
        if parent_run_id is not None or (metadata or {}).get("product_run_id") != (
            self._product_run_id
        ):
            return
        started_at = datetime.now(UTC)
        dotted_order = _trace_dotted_order(started_at, run_id)
        try:
            self._client.create_run(
                "ru_quality_dev_case",
                {},
                "chain",
                id=run_id,
                trace_id=run_id,
                dotted_order=dotted_order,
                project_name=self._project_name,
                start_time=started_at,
                extra={"metadata": dict(self._metadata)},
                tags=["google-work-agent", "ru-quality-dev", "evaluation"],
            )
        except Exception as error:
            self.trace_error = type(error).__name__
            return
        with self._lock:
            self._root = (run_id, dotted_order)
            self.root_trace_id = str(run_id)

    def begin_external_call(
        self, command: ExternalCallTraceStartV1
    ) -> ExternalCallTraceHandleV1 | None:
        if command.schema_version != 1 or command.domain_run_id != self._product_run_id:
            return None
        with self._lock:
            root = self._root
        if root is None:
            return None
        root_run_id, root_dotted_order = root
        child_run_id = uuid4()
        started_at = datetime.now(UTC)
        dotted_order = _trace_dotted_order(
            started_at,
            child_run_id,
            parent_dotted_order=root_dotted_order,
        )
        metadata = dict(self._metadata)
        metadata["external_call_kind"] = command.call_kind
        for name in (
            "operation",
            "provider",
            "model_id",
            "prompt_id",
            "prompt_version",
            "prompt_content_hash",
            "output_schema_id",
            "connector_id",
            "tool_id",
            "effect",
        ):
            value = getattr(command, name)
            if isinstance(value, str) and _SAFE_TRACE_VALUE.fullmatch(value):
                metadata[name] = value
        name = (
            "llm:schema_repair"
            if command.call_kind == "LLM_SCHEMA_REPAIR"
            else "llm:structured_inference"
            if command.call_kind == "LLM_INFERENCE"
            else "connector:read"
        )
        run_type: Literal["llm", "tool"] = (
            "llm" if command.call_kind.startswith("LLM_") else "tool"
        )
        try:
            self._client.create_run(
                name,
                {},
                run_type,
                id=child_run_id,
                trace_id=root_run_id,
                dotted_order=dotted_order,
                parent_run_id=root_run_id,
                project_name=self._project_name,
                start_time=started_at,
                extra={"metadata": metadata},
                tags=["google-work-agent", "ru-quality-dev", "external-dispatch"],
            )
        except Exception as error:
            self.trace_error = type(error).__name__
            return None
        with self._lock:
            self._children[child_run_id] = (root_run_id, dotted_order)
        return ExternalCallTraceHandleV1(1, str(child_run_id))

    def finish_external_call(
        self,
        handle: ExternalCallTraceHandleV1,
        result: ExternalCallTraceFinishV1,
    ) -> None:
        if handle.schema_version != 1 or result.schema_version != 1:
            return
        try:
            child_run_id = UUID(handle.trace_run_id)
        except ValueError:
            return
        with self._lock:
            active = self._children.pop(child_run_id, None)
        if active is None:
            return
        root_run_id, dotted_order = active
        outputs: dict[str, object] = {
            "status": result.status,
            "duration_ms": max(0, result.duration_ms),
        }
        for name in ("input_tokens", "output_tokens", "total_tokens"):
            value = getattr(result, name)
            if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
                outputs[name] = value
        error_type = (
            result.error_type
            if isinstance(result.error_type, str)
            and _SAFE_TRACE_VALUE.fullmatch(result.error_type)
            else None
        )
        try:
            self._client.update_run(
                child_run_id,
                trace_id=root_run_id,
                dotted_order=dotted_order,
                parent_run_id=root_run_id,
                end_time=datetime.now(UTC),
                error=(
                    None
                    if result.status == "COMPLETED"
                    else f"SAFE_ERROR_TYPE:{error_type or 'ExternalCallError'}"
                ),
                outputs=outputs,
            )
        except Exception as error:
            self.trace_error = type(error).__name__

    def on_chain_end(self, outputs: Any, *, run_id: UUID, **kwargs: Any) -> None:
        del outputs, kwargs
        self._finish_root(run_id, error_type=None)

    def on_chain_error(self, error: BaseException, *, run_id: UUID, **kwargs: Any) -> None:
        del kwargs
        self._finish_root(
            run_id,
            error_type=(None if isinstance(error, GraphInterrupt) else type(error).__name__),
        )

    def flush(self) -> None:
        self._client.flush(timeout=5.0)

    def close(self) -> None:
        self._client.close(timeout=5.0)

    def _finish_root(self, run_id: UUID, *, error_type: str | None) -> None:
        with self._lock:
            root = self._root
            if root is None or root[0] != run_id:
                return
            self._root = None
        safe_error_type = (
            error_type
            if isinstance(error_type, str) and _SAFE_TRACE_VALUE.fullmatch(error_type)
            else None
        )
        try:
            self._client.update_run(
                run_id,
                trace_id=run_id,
                dotted_order=root[1],
                end_time=datetime.now(UTC),
                error=(
                    None
                    if safe_error_type is None
                    else f"SAFE_ERROR_TYPE:{safe_error_type}"
                ),
                outputs={},
            )
        except Exception as error:
            self.trace_error = type(error).__name__


def _trace_dotted_order(
    started_at: datetime,
    run_id: UUID,
    *,
    parent_dotted_order: str | None = None,
) -> str:
    current = started_at.strftime("%Y%m%dT%H%M%S%fZ") + str(run_id)
    return current if parent_dotted_order is None else f"{parent_dotted_order}.{current}"


class RecordingInferencePort:
    """Observe production typed inference results without changing routing."""

    def __init__(self, delegate: StructuredInferencePort) -> None:
        self._delegate = delegate
        self._lock = Lock()
        self._next_sequence = 0
        self.calls: list[dict[str, object]] = []

    def infer(
        self,
        requested_mode: Literal["AUTO", "LOCAL_GPU", "API_LLM"],
        prompt_ref: PromptReference,
        input_projection: Mapping[str, object],
        output_schema_ref: OutputSchemaDefinition,
    ) -> StructuredInferenceResultV1:
        with self._lock:
            sequence = self._next_sequence
            self._next_sequence += 1
        started = time.perf_counter()
        record: dict[str, object] = {
            "sequence": sequence,
            "requested_mode": requested_mode,
            "prompt_ref": _prompt_ref_projection(prompt_ref),
            "output_schema_id": output_schema_ref.schema_version,
        }
        try:
            result = self._delegate.infer(
                requested_mode,
                prompt_ref,
                input_projection,
                output_schema_ref,
            )
        except Exception as error:
            record.update(
                {
                    "latency_ms": int((time.perf_counter() - started) * 1000),
                    "error": _exception_projection(error),
                }
            )
            with self._lock:
                self.calls.append(record)
            raise
        record.update(
            {
                "provider": result.provider,
                "model": result.model,
                "actual_runtime": result.actual_runtime,
                "latency_ms": result.latency_ms,
                "input_tokens": result.input_tokens,
                "output_tokens": result.output_tokens,
                "fallback_reason": result.fallback_reason,
                "typed_output": _json_value(result.structured_output),
            }
        )
        with self._lock:
            self.calls.append(record)
        return result


class RecordingExternalCallTrace:
    """Mirror safe external spans to LangSmith while retaining local call evidence."""

    def __init__(self, delegate: ExternalCallTracePort) -> None:
        self._delegate = delegate
        self._lock = Lock()
        self._active: dict[str, tuple[ExternalCallTraceHandleV1 | None, dict[str, object]]] = {}
        self.calls: list[dict[str, object]] = []

    def begin_external_call(
        self, command: ExternalCallTraceStartV1
    ) -> ExternalCallTraceHandleV1 | None:
        local_id = str(uuid4())
        delegate_handle = self._delegate.begin_external_call(command)
        record: dict[str, object] = {
            "local_call_id": local_id,
            "call_kind": command.call_kind,
            "operation": command.operation,
            "provider": command.provider,
            "model_id": command.model_id,
            "prompt_id": command.prompt_id,
            "prompt_version": command.prompt_version,
            "prompt_content_hash": command.prompt_content_hash,
            "output_schema_id": command.output_schema_id,
            "started_at_monotonic": time.perf_counter(),
        }
        with self._lock:
            self._active[local_id] = (delegate_handle, record)
        return ExternalCallTraceHandleV1(1, local_id)

    def finish_external_call(
        self,
        handle: ExternalCallTraceHandleV1,
        result: ExternalCallTraceFinishV1,
    ) -> None:
        with self._lock:
            active = self._active.pop(handle.trace_run_id, None)
        if active is None:
            return
        delegate_handle, record = active
        record.pop("started_at_monotonic", None)
        record.update(
            {
                "status": result.status,
                "duration_ms": result.duration_ms,
                "input_tokens": result.input_tokens,
                "output_tokens": result.output_tokens,
                "total_tokens": result.total_tokens,
                "error_type": result.error_type,
                "safe_error_code": result.safe_error_code,
                "safe_semantic_output": _json_value(result.safe_semantic_output),
            }
        )
        with self._lock:
            self.calls.append(record)
        if delegate_handle is not None:
            self._delegate.finish_external_call(delegate_handle, result)


class RuNodeTimingCallback(BaseCallbackHandler):
    """Capture case root trace ID and each production RU node latency."""

    def __init__(self, product_run_id: str) -> None:
        self._product_run_id = product_run_id
        self._lock = Lock()
        self._active: dict[UUID, tuple[str, float]] = {}
        self.root_trace_id: str | None = None
        self.node_latencies: list[dict[str, object]] = []

    def on_chain_start(
        self,
        serialized: Any,
        inputs: Any,
        *,
        run_id: UUID,
        parent_run_id: UUID | None = None,
        metadata: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> None:
        del serialized, inputs
        metadata = metadata or {}
        if parent_run_id is None and metadata.get("product_run_id") == self._product_run_id:
            self.root_trace_id = str(run_id)
        node = metadata.get("langgraph_node")
        if isinstance(node, str) and node in ALLOWED_RU_NODES and kwargs.get("name") == node:
            with self._lock:
                self._active[run_id] = (node, time.perf_counter())

    def on_chain_end(self, outputs: Any, *, run_id: UUID, **kwargs: Any) -> None:
        del outputs, kwargs
        self._finish(run_id, "COMPLETED")

    def on_chain_error(self, error: BaseException, *, run_id: UUID, **kwargs: Any) -> None:
        del kwargs
        status = "INTERRUPTED" if isinstance(error, GraphInterrupt) else "FAILED"
        self._finish(run_id, status)

    def _finish(self, run_id: UUID, status: str) -> None:
        with self._lock:
            active = self._active.pop(run_id, None)
        if active is None:
            return
        node, started = active
        with self._lock:
            self.node_latencies.append(
                {
                    "node": node,
                    "latency_ms": int((time.perf_counter() - started) * 1000),
                    "status": status,
                }
            )


def load_ru_cases(
    dataset_path: Path,
    *,
    case_ids: Sequence[str] = (),
    run_all: bool = False,
) -> list[dict[str, object]]:
    """Strictly select explicit case IDs or the whole dataset, never implicitly all."""

    if run_all == bool(case_ids):
        raise ValueError("specify either one or more --case-id values or --all")
    rows: list[dict[str, object]] = []
    seen: set[str] = set()
    with dataset_path.open("r", encoding="utf-8") as stream:
        for line_no, raw_line in enumerate(stream, start=1):
            if not raw_line.strip():
                continue
            try:
                row = json.loads(raw_line)
            except json.JSONDecodeError as error:
                raise ValueError(f"invalid dataset JSON at line {line_no}") from error
            if not isinstance(row, dict):
                raise ValueError(f"dataset line {line_no} must be an object")
            case_id = row.get("case_id")
            if not isinstance(case_id, str) or not case_id or case_id in seen:
                raise ValueError(f"invalid or duplicate case_id at line {line_no}")
            if not isinstance(row.get("user_request"), str):
                raise ValueError(f"case {case_id} has no user_request")
            seen.add(case_id)
            rows.append(row)
    if run_all:
        return rows
    by_id = {cast(str, row["case_id"]): row for row in rows}
    if len(set(case_ids)) != len(case_ids):
        raise ValueError("case IDs must be unique")
    missing = [case_id for case_id in case_ids if case_id not in by_id]
    if missing:
        raise ValueError(f"unknown case IDs: {', '.join(missing)}")
    return [by_id[case_id] for case_id in case_ids]


def classify_execution_exception(error: Exception) -> dict[str, object]:
    """Keep RU semantic/contract failures out of infra/runtime buckets."""

    reason_code = getattr(error, "reason_code", None)
    affected = getattr(error, "affected_field_paths", ())
    if isinstance(
        error,
        (
            RequestGoalSemanticValidationError,
            RequestAmbiguityValidationError,
            RequestUnderstandingValidationError,
        ),
    ):
        category = "RU_SEMANTIC_CONTRACT"
    elif (semantic_value_error := _classify_semantic_validator_value_error(error)) is not None:
        category = "RU_SEMANTIC_CONTRACT"
        reason_code, affected = semantic_value_error
    elif isinstance(error, LLMInvocationError):
        reason_code = error.code.value
        if error.code == LLMErrorCode.PROVIDER_TIMEOUT:
            category = "TIMEOUT"
        elif error.code == LLMErrorCode.OUTPUT_SCHEMA_INVALID:
            category = "RU_SCHEMA_CONTRACT"
        elif error.code in _PROVIDER_FAILURE_CODES:
            category = "PROVIDER_FAILURE"
        else:
            category = "RUNTIME_FAILURE"
    elif isinstance(error, TimeoutError):
        category = "TIMEOUT"
        reason_code = "TIMEOUT"
    else:
        category = "RUNTIME_FAILURE"
        reason_code = reason_code or type(error).__name__
    return {
        "category": category,
        "type": type(error).__name__,
        "reason_code": reason_code,
        "affected_field_paths": list(affected) if isinstance(affected, (list, tuple)) else [],
        "message": str(error),
    }


def _classify_semantic_validator_value_error(
    error: Exception,
) -> tuple[str, tuple[str, ...]] | None:
    if not isinstance(error, ValueError):
        return None
    message = str(error)
    source_status_failures = {
        "source status resource is not present in source reads": (
            "EVAL_SOURCE_STATUS_RESOURCE_MISMATCH",
            ("$.source_statuses.statuses[].source_resource_type",),
        ),
        "source status is not valid for its bound source resource": (
            "EVAL_SOURCE_STATUS_VALUE_MISMATCH",
            (
                "$.source_statuses.statuses[].value",
                "$.source_statuses.statuses[].source_resource_type",
            ),
        ),
        "source status provenance source is unavailable": (
            "EVAL_SOURCE_STATUS_PROVENANCE_UNAVAILABLE",
            ("$.source_statuses.statuses[].source",),
        ),
        "source status binding is duplicated": (
            "EVAL_SOURCE_STATUS_DUPLICATED",
            ("$.source_statuses.statuses",),
        ),
    }
    if message in source_status_failures:
        return source_status_failures[message]
    semantic_text = re.fullmatch(
        r"(?:request goal|source dependency) candidate is invalid: "
        r"(?P<path>\$\..+) has no semantic text",
        message,
    )
    if semantic_text is not None:
        return (
            "EVAL_RU_SEMANTIC_TEXT_INVALID",
            (semantic_text.group("path"),),
        )
    return None


def evaluate_cases(
    cases: Sequence[Mapping[str, object]],
    *,
    dataset_path: Path,
    results_path: Path,
    langsmith_api_key: str,
    langsmith_project: str,
    experiment_id: str,
) -> dict[str, object]:
    """Build one isolated production runtime and execute only the compiled RU subgraph."""

    product_sha = _git_head()
    model_digest = _ollama_model_digest(MODEL_ID)
    if model_digest is None:
        raise RuntimeError(f"model digest is unavailable for {MODEL_ID}")
    with TemporaryDirectory(
        prefix="gwa-ru-quality-dev-", ignore_cleanup_errors=True
    ) as runtime_directory:
        config = ProductionRuntimeConfig.development(
            runtime_root=Path(runtime_directory),
            working_directory=ROOT,
            mcp_manifest_version="2026-08-07.p0",
            keyring_store=SessionMemorySecretStore(),
        )
        container = build_production_runtime(
            **{field.name: getattr(config, field.name) for field in fields(config)},
            bootstrap_secret=uuid4().hex,
            service_instance_id=f"ru-evaluation-{uuid4()}",
        )
        try:
            runtime = cast(Any, container.structured_inference_port)
            if runtime is None or container.update_settings_handler is None:
                raise RuntimeError("production local LLM runtime is unavailable")
            container.update_settings_handler(
                UpdateSettingsCommand(
                    str(uuid4()),
                    SettingsPatchV1(
                        schema_version=1,
                        preferred_local_model_id=MODEL_ID,
                        preferred_llm_mode=RUNTIME_MODE,
                        external_llm_consent=False,
                    ),
                )
            )
            results: list[dict[str, object]] = []
            for case in cases:
                try:
                    result = _evaluate_case(
                        case,
                        container=container,
                        langsmith_api_key=langsmith_api_key,
                        langsmith_project=langsmith_project,
                        experiment_id=experiment_id,
                        code_sha=product_sha,
                        model_digest=model_digest,
                    )
                except Exception as error:
                    result = _failed_case_result(case, error)
                results.append(result)
                print(
                    json.dumps(
                        {
                            "case_id": result["case_id"],
                            "verdict": cast(Mapping[str, object], result["grade"])["verdict"],
                            "failure_cluster": cast(Mapping[str, object], result["grade"])[
                                "failure_cluster"
                            ],
                            "trace_id": cast(Mapping[str, object], result["observation"])[
                                "langsmith"
                            ],
                            "execution_failure": cast(Mapping[str, object], result["observation"])[
                                "execution_failure"
                            ],
                        },
                        ensure_ascii=False,
                    ),
                    flush=True,
                )
        finally:
            for close in reversed(container.shutdown_callbacks):
                close()

    aggregation = aggregate_ru_scores(results)
    readiness_reasons = _batch_blockers(results)
    payload = {
        "schema_version": 1,
        "artifact_kind": "RU_DEVELOPMENT_DATASET_DRY_RUN",
        "official_baseline": False,
        "created_at_utc": datetime.now(UTC).isoformat(),
        "dataset": {
            "path": dataset_path.relative_to(ROOT).as_posix(),
            "sha256": _normalized_sha256(dataset_path),
            "selected_case_ids": [item["case_id"] for item in results],
        },
        "execution": {
            "product_sha": product_sha,
            "experiment_id": experiment_id,
            "model_id": MODEL_ID,
            "model_digest": model_digest,
            "runtime_mode": RUNTIME_MODE,
            "graph_boundary": "PRODUCTION_REQUEST_UNDERSTANDING_SUBGRAPH_ONLY",
            "prompt_execution_scope": DEVELOPMENT_SMOKE,
            "connector_prerequisites": "NOT_INVOKED",
            "confirmation_controller": "STOP_AFTER_TYPED_RU_CONFIRMATION",
            "downstream_stages": [],
            "langsmith_project": langsmith_project,
        },
        "grader": {
            "version": GRADER_VERSION,
            "sha256": _normalized_sha256(ROOT / "evaluation" / "ru_quality_dev_grader.py"),
            "canonical_grader_v8_reused": False,
        },
        "runner_sha256": _normalized_sha256(Path(__file__)),
        "cases": results,
        "aggregation": aggregation,
        "batch_readiness": {
            "decision": "GO" if not readiness_reasons else "BLOCKED",
            "reasons": readiness_reasons,
        },
    }
    _write_json_atomic(results_path, payload)
    return payload


def _evaluate_case(
    case: Mapping[str, object],
    *,
    container: Any,
    langsmith_api_key: str,
    langsmith_project: str,
    experiment_id: str,
    code_sha: str,
    model_digest: str,
) -> dict[str, object]:
    request = _create_persisted_request(container, case)
    case_id = cast(str, case["case_id"])
    langsmith_trace = RuEvaluationLangSmithTrace(
        api_key=langsmith_api_key,
        project_name=langsmith_project,
        experiment_id=experiment_id,
        case_id=case_id,
        code_sha=code_sha,
        model_id=MODEL_ID,
        model_digest=model_digest,
        runtime_mode=RUNTIME_MODE,
        product_run_id=request.run_id,
    )
    inference = RecordingInferencePort(
        cast(StructuredInferencePort, container.structured_inference_port)
    )
    external_trace = RecordingExternalCallTrace(langsmith_trace)
    previous_external_trace = container.structured_inference_port.external_call_trace
    container.structured_inference_port.external_call_trace = external_trace
    timing = RuNodeTimingCallback(request.run_id)
    production_runtime = cast(Any, container.workflow_runtime)
    graph = RequestUnderstandingSubgraph(
        llm_runtime=inference,
        tool_catalog=load_signed_tool_registry(),
        prompt_manifest_path=None,
        prompt_execution_scope=DEVELOPMENT_SMOKE,
        id_factory=container.id_generator.new_uuid,
        graph_profile=GraphProfile(container.graph_profile),
        transition_run=production_runtime._transition_run,
        merge_decision=production_runtime._merge_decision,
        confirm_inline=_stop_at_ru_confirmation_boundary,
        connector_prerequisites=None,
    ).build()
    state = cast(
        RequestUnderstandingStateV2,
        initial_graph_state(
            request,
            graph_profile=GraphProfile(container.graph_profile),
            graph_version=container.graph_version,
            initial_target="request_understanding",
        ),
    )
    updates: list[Mapping[str, object]] = []
    failure: dict[str, object] | None = None
    started = time.perf_counter()
    config = {
        "callbacks": [langsmith_trace, timing],
        "metadata": {
            "product_run_id": request.run_id,
            "graph_profile": container.graph_profile,
            "graph_version": container.graph_version,
        },
    }
    try:
        with provider_dispatch_execution_scope(
            run_id=request.run_id,
            now_ms=container.clock.now_ms,
        ):
            for update in graph.stream(state, config=config, stream_mode="updates"):
                if isinstance(update, Mapping):
                    updates.append(update)
    except GraphInterrupt:
        pass
    except Exception as error:
        failure = classify_execution_exception(error)
    finally:
        langsmith_trace.flush()
        langsmith_trace.close()
        container.structured_inference_port.external_call_trace = previous_external_trace

    projection = _project_observation(
        request=request,
        updates=updates,
        inference_calls=inference.calls,
        external_calls=external_trace.calls,
        node_latencies=timing.node_latencies,
        trace_id=langsmith_trace.root_trace_id,
        total_latency_ms=int((time.perf_counter() - started) * 1000),
        failure=failure,
        container=container,
    )
    binding_failure = _runtime_binding_failure(projection)
    if projection["execution_failure"] is None and binding_failure is not None:
        projection["execution_failure"] = binding_failure
    projection["langsmith"] = _verify_langsmith_trace(
        api_key=langsmith_api_key,
        project_name=langsmith_project,
        trace_id=langsmith_trace.root_trace_id,
        experiment_id=experiment_id,
        case_id=case_id,
        code_sha=code_sha,
        model_id=MODEL_ID,
        runtime_mode=RUNTIME_MODE,
    )
    grade = grade_ru_case(case, projection)
    return {
        "case_id": case["case_id"],
        "semantic_family": case["semantic_family"],
        "difficulty": case["difficulty"],
        "observation": projection,
        "grade": grade,
    }


def _create_persisted_request(container: Any, case: Mapping[str, object]) -> WorkflowStartRequest:
    conversation_id = str(uuid4())
    account_id = "ru-evaluation-local"
    create_payload = {
        "kind": "ru_evaluation_conversation",
        "conversation_id": conversation_id,
        "account_id": account_id,
    }
    container.create_conversation_handler(
        CreateConversationCommand(
            command_id=str(uuid4()),
            request_hash=calculate_canonical_json_hash(create_payload),
            conversation_id=conversation_id,
            account_id=account_id,
            title="RU development evaluation",
            api_contract_version=container.api_contract_version,
        )
    )
    now_ms = container.clock.now_ms()
    selections = tuple(
        ResourceSelectionHandlePayloadV1(
            schema_version=1,
            service_instance_id=container.service_instance_id,
            session_digest=hashlib.sha256(conversation_id.encode("utf-8")).hexdigest(),
            account_id=account_id,
            connector_id=cast(str, item["connector_id"]),
            resource_type=cast(str, item["resource_type"]),
            resource_id=cast(str, item["resource_id"]),
            parent_resource_id=cast(str | None, item.get("parent_resource_id")),
            version_token=None,
            issued_at_ms=now_ms,
            expires_at_ms=now_ms + 86_400_000,
        )
        for item in (
            cast(Mapping[str, object], value)
            for value in cast(Sequence[object], case.get("selected_resource_refs", ()))
        )
    )
    start_payload = {
        "kind": "ru_evaluation_start",
        "conversation_id": conversation_id,
        "request_text": case["user_request"],
        "entry_mode": case["entry_mode"],
        "requested_mode": RUNTIME_MODE,
        "selected_resources": [_json_value(item) for item in selections],
    }
    started = container.start_run_handler(
        StartRunCommand(
            command_id=str(uuid4()),
            request_hash=calculate_canonical_json_hash(start_payload),
            conversation_id=conversation_id,
            request_text=cast(str, case["user_request"]),
            entry_mode=cast(str, case["entry_mode"]),
            requested_mode=RUNTIME_MODE,
            api_contract_version=container.api_contract_version,
            resolved_resource_selections=selections,
        )
    )
    if not started.applied:
        raise RuntimeError(f"StartRun failed: {started.result_code}")
    with container.read_unit_of_work_factory() as unit_of_work:
        run = unit_of_work.runs.get(started.run_id)
        if run is None:
            raise RuntimeError("persisted evaluation Run is missing")
        selected_records = unit_of_work.resource_refs.list_for_run_bounded(started.run_id, limit=20)
    selected_resources = tuple(
        SelectedResourceRef(
            resource_ref_id=item.id,
            connector_id=item.connector_id,
            resource_type=item.resource_type,
            resource_id=item.resource_id,
            parent_resource_id=item.parent_resource_id,
        )
        for item in selected_records
    )
    return WorkflowStartRequest(
        run_id=started.run_id,
        conversation_id=conversation_id,
        workflow_key=started.workflow_key,
        entry_mode=cast(str, case["entry_mode"]),
        requested_mode=RUNTIME_MODE,
        request_text=cast(str, case["user_request"]),
        selected_resource_ids=tuple(item.resource_id for item in selected_resources),
        selected_resources=selected_resources,
        user_message_id=started.user_message_id,
        correlation=WorkflowCorrelationContext(str(uuid4()), None, container.api_contract_version),
        run_budget=cast(Mapping[str, object], json.loads(run.budget_json)),
    )


def _project_observation(
    *,
    request: WorkflowStartRequest,
    updates: Sequence[Mapping[str, object]],
    inference_calls: Sequence[Mapping[str, object]],
    external_calls: Sequence[Mapping[str, object]],
    node_latencies: Sequence[Mapping[str, object]],
    trace_id: str | None,
    total_latency_ms: int,
    failure: Mapping[str, object] | None,
    container: Any,
) -> dict[str, object]:
    folded: dict[str, object] = {}
    node_sequence: list[str] = []
    for update in updates:
        for node, raw_patch in update.items():
            if node == "__interrupt__":
                continue
            node_sequence.append(node)
            if isinstance(raw_patch, Mapping):
                for key, value in raw_patch.items():
                    if key == "user_interrupt" and value is None and folded.get(key) is not None:
                        continue
                    folded[key] = value
    completed_calls = [call for call in inference_calls if call.get("typed_output") is not None]
    prompt_refs = {
        json.dumps(call["prompt_ref"], sort_keys=True): call["prompt_ref"]
        for call in inference_calls
        if isinstance(call.get("prompt_ref"), Mapping)
    }
    with container.read_unit_of_work_factory() as unit_of_work:
        run = unit_of_work.runs.get(request.run_id)
        trace_events = unit_of_work.traces.list_page(TraceEventCursor(run_id=request.run_id), 500)
    typed_output = {
        "request_intent": _json_value(folded.get("request_intent")),
        "goal_candidate": _json_value(folded.get("goal_candidate")),
        "ambiguity_candidate": _json_value(folded.get("ambiguity_candidate")),
        "workflow_phase": folded.get("workflow_phase"),
        "user_interrupt": _json_value(folded.get("user_interrupt")),
    }
    downstream_nodes = [node for node in node_sequence if node not in ALLOWED_RU_NODES]
    connector_calls = [call for call in external_calls if call.get("call_kind") == "CONNECTOR_READ"]
    return {
        "run_context": {
            "run_id": request.run_id,
            "conversation_id": request.conversation_id,
            "persisted": run is not None,
            "final_run_status": None if run is None else run.status.value,
            "trace_event_count": len(trace_events),
        },
        "node_sequence": node_sequence,
        "node_latencies_ms": list(node_latencies),
        "total_latency_ms": total_latency_ms,
        "typed_ru_output": typed_output,
        "provider_calls": sorted(
            [_json_value(call) for call in inference_calls],
            key=lambda item: cast(int, cast(Mapping[str, object], item).get("sequence", 0)),
        ),
        "external_call_summary": {
            "count": len(external_calls),
            "schema_repair_count": sum(
                call.get("call_kind") == "LLM_SCHEMA_REPAIR" for call in external_calls
            ),
            "connector_call_count": len(connector_calls),
        },
        "prompt_refs": list(prompt_refs.values()),
        "actual_models": sorted(
            {
                cast(str, call["model"])
                for call in completed_calls
                if isinstance(call.get("model"), str)
            }
        ),
        "actual_runtimes": sorted(
            {
                cast(str, call["actual_runtime"])
                for call in completed_calls
                if isinstance(call.get("actual_runtime"), str)
            }
        ),
        "actual_providers": sorted(
            {
                cast(str, call["provider"])
                for call in completed_calls
                if isinstance(call.get("provider"), str)
            }
        ),
        "downstream_node_count": len(downstream_nodes),
        "downstream_nodes": downstream_nodes,
        "execution_failure": None if failure is None else dict(failure),
        "langsmith": {"trace_id": trace_id, "verified": False},
    }


def _runtime_binding_failure(observation: Mapping[str, object]) -> dict[str, object] | None:
    if observation.get("downstream_node_count") != 0:
        return _synthetic_runtime_failure("DOWNSTREAM_BOUNDARY_VIOLATION")
    external_summary = cast(Mapping[str, object], observation.get("external_call_summary", {}))
    if external_summary.get("connector_call_count") != 0:
        return _synthetic_runtime_failure("CONNECTOR_BOUNDARY_VIOLATION")
    calls = cast(Sequence[Mapping[str, object]], observation.get("provider_calls", ()))
    completed = [call for call in calls if call.get("typed_output") is not None]
    if completed and any(
        call.get("model") != MODEL_ID
        or call.get("actual_runtime") != RUNTIME_MODE
        or call.get("provider") != "ollama"
        or call.get("fallback_reason") is not None
        for call in completed
    ):
        return _synthetic_runtime_failure("MODEL_BINDING_MISMATCH")
    return None


def _stop_at_ru_confirmation_boundary(
    state: RequestUnderstandingStateV2,
) -> tuple[None, dict[str, object]]:
    del state
    return None, {
        "__target__": "end",
        "__workflow_control__": {
            "schema_version": 1,
            "stage": "RU_EVALUATION_BOUNDARY",
            "reason": "CONFIRMATION_OBSERVED",
        },
    }


def _synthetic_runtime_failure(reason_code: str) -> dict[str, object]:
    return {
        "category": "RUNTIME_FAILURE",
        "type": "EvaluationBoundaryError",
        "reason_code": reason_code,
        "affected_field_paths": [],
        "message": reason_code,
    }


def _verify_langsmith_trace(
    *,
    api_key: str,
    project_name: str,
    trace_id: str | None,
    experiment_id: str,
    case_id: str,
    code_sha: str,
    model_id: str,
    runtime_mode: str,
) -> dict[str, object]:
    result: dict[str, object] = {"trace_id": trace_id, "verified": False, "url": None}
    if trace_id is None:
        result["verification_error"] = "TRACE_ID_MISSING"
        return result
    client = Client(api_key=api_key)
    for attempt in range(5):
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", DeprecationWarning)
                run = client.read_run(trace_id, load_child_runs=True)
                url = client.get_run_url(run=run, project_name=project_name)
            expected_metadata = {
                "experiment_id": experiment_id,
                "case_id": case_id,
                "code_sha": code_sha,
                "model_id": model_id,
                "runtime_mode": runtime_mode,
            }
            root_metadata = _langsmith_run_metadata(run)
            children = _langsmith_child_runs(run)
            llm_children = [
                child for child in children if getattr(child, "run_type", None) == "llm"
            ]
            root_matches = all(
                root_metadata.get(key) == value for key, value in expected_metadata.items()
            )
            child_matches = any(
                all(
                    _langsmith_run_metadata(child).get(key) == value
                    for key, value in expected_metadata.items()
                )
                for child in llm_children
            )
            if not root_matches or not child_matches:
                result["verification_error"] = "TRACE_BINDING_MISMATCH"
                if attempt < 4:
                    time.sleep(1)
                continue
            result.update(
                {
                    "verified": True,
                    "run_name": run.name,
                    "child_run_count": len(children),
                    "child_llm_run_count": len(llm_children),
                    "binding_verified": True,
                    "url": url,
                }
            )
            break
        except Exception as error:
            result["verification_error"] = type(error).__name__
            if attempt < 4:
                time.sleep(1)
    return result


def _langsmith_run_metadata(run: Any) -> Mapping[str, object]:
    extra = getattr(run, "extra", None)
    if not isinstance(extra, Mapping):
        return {}
    metadata = extra.get("metadata")
    return metadata if isinstance(metadata, Mapping) else {}


def _langsmith_child_runs(run: Any) -> list[Any]:
    result: list[Any] = []
    pending = list(getattr(run, "child_runs", None) or [])
    while pending:
        child = pending.pop(0)
        result.append(child)
        pending.extend(getattr(child, "child_runs", None) or [])
    return result


def _batch_blockers(results: Sequence[Mapping[str, object]]) -> list[str]:
    blockers: set[str] = set()
    for result in results:
        observation = cast(Mapping[str, object], result["observation"])
        failure = cast(Mapping[str, object], observation.get("execution_failure") or {})
        if failure.get("category") in {"TIMEOUT", "PROVIDER_FAILURE", "RUNTIME_FAILURE"}:
            blockers.add(cast(str, failure["category"]))
        if observation.get("downstream_node_count") != 0:
            blockers.add("DOWNSTREAM_BOUNDARY_VIOLATION")
        langsmith = cast(Mapping[str, object], observation.get("langsmith") or {})
        if langsmith.get("verified") is not True:
            blockers.add("LANGSMITH_TRACE_UNVERIFIED")
    return sorted(blockers)


def _failed_case_result(case: Mapping[str, object], error: Exception) -> dict[str, object]:
    observation: dict[str, object] = {
        "run_context": {"persisted": False},
        "node_sequence": [],
        "node_latencies_ms": [],
        "total_latency_ms": 0,
        "typed_ru_output": {
            "request_intent": None,
            "goal_candidate": None,
            "ambiguity_candidate": None,
            "workflow_phase": None,
            "user_interrupt": None,
        },
        "provider_calls": [],
        "external_call_summary": {
            "count": 0,
            "schema_repair_count": 0,
            "connector_call_count": 0,
        },
        "prompt_refs": [],
        "actual_models": [],
        "actual_runtimes": [],
        "actual_providers": [],
        "downstream_node_count": 0,
        "downstream_nodes": [],
        "execution_failure": classify_execution_exception(error),
        "langsmith": {
            "trace_id": None,
            "verified": False,
            "verification_error": "CASE_SETUP_FAILED",
        },
    }
    return {
        "case_id": case["case_id"],
        "semantic_family": case["semantic_family"],
        "difficulty": case["difficulty"],
        "observation": observation,
        "grade": grade_ru_case(case, observation),
    }


def _prompt_ref_projection(prompt_ref: PromptReference) -> dict[str, object]:
    return {
        "prompt_bundle_version": prompt_ref.prompt_bundle_version,
        "prompt_id": prompt_ref.prompt_id,
        "prompt_version": prompt_ref.prompt_version,
        "content_hash": prompt_ref.content_hash,
        "input_schema_version": prompt_ref.input_schema_version,
        "output_schema_version": prompt_ref.output_schema_version,
    }


def _exception_projection(error: Exception) -> dict[str, object]:
    return {
        "type": type(error).__name__,
        "reason_code": getattr(getattr(error, "code", None), "value", None)
        or getattr(error, "reason_code", None),
        "message": str(error),
    }


def _json_value(value: object) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Enum):
        return value.value
    if is_dataclass(value) and not isinstance(value, type):
        return _json_value(asdict(value))
    if isinstance(value, Mapping):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_json_value(item) for item in value]
    return str(value)


def _normalized_sha256(path: Path) -> str:
    content = path.read_text(encoding="utf-8").replace("\r\n", "\n").replace("\r", "\n")
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _ollama_model_digest(model_id: str) -> str | None:
    try:
        with urllib.request.urlopen("http://127.0.0.1:11434/api/tags", timeout=5) as response:
            payload = json.loads(response.read())
    except (OSError, ValueError, json.JSONDecodeError):
        return None
    if not isinstance(payload, Mapping):
        return None
    for raw_model in payload.get("models", []):
        if not isinstance(raw_model, Mapping):
            continue
        if raw_model.get("name") == model_id and isinstance(raw_model.get("digest"), str):
            return cast(str, raw_model["digest"])
    return None


def _git_head() -> str:
    return subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _write_json_atomic(path: Path, payload: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _default_results_path() -> Path:
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    return (
        DEFAULT_RESULTS_ROOT
        / f"ru-quality-dev-{datetime.now(UTC).strftime('%Y%m%d')}"
        / f"ru-quality-dev-{timestamp}.json"
    )


def _parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--case-id", action="append", default=[])
    parser.add_argument("--all", action="store_true", help="explicitly execute all dataset cases")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--langsmith-project")
    parser.add_argument("--experiment-id")
    return parser.parse_args()


def read_ru_evaluation_langsmith_configuration(
    *,
    project_name: str | None,
    experiment_id: str | None,
    environment: Mapping[str, str] | None = None,
    env_file: Path | None = None,
) -> tuple[str, str, str]:
    """Load explicit evaluation tracing without enabling ambient LangChain tracing."""

    values = os.environ if environment is None else environment
    if _environment_flag(values, "LANGSMITH_TRACING") or _environment_flag(
        values, "LANGCHAIN_TRACING_V2"
    ):
        raise ValueError("automatic LangSmith tracing is not permitted")
    api_key = values.get("LANGSMITH_API_KEY", "").strip()
    if not api_key:
        api_key = _read_environment_file_value(
            ROOT / ".env.local" if env_file is None else env_file,
            "LANGSMITH_API_KEY",
        )
    if not api_key:
        raise ValueError("RU evaluation requires LANGSMITH_API_KEY")
    selected_project = (
        project_name
        or values.get("LANGSMITH_PROJECT")
        or DEFAULT_LANGSMITH_PROJECT
    ).strip()
    selected_experiment = (
        experiment_id
        or values.get("GWA_LANGSMITH_EXPERIMENT_ID")
        or f"ru-quality-dev-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}"
    ).strip()
    if not _SAFE_TRACE_VALUE.fullmatch(selected_project):
        raise ValueError("LangSmith project name must be a safe opaque identifier")
    if not _SAFE_TRACE_VALUE.fullmatch(selected_experiment):
        raise ValueError("LangSmith experiment ID must be a safe opaque identifier")
    return api_key, selected_project, selected_experiment


def _environment_flag(environment: Mapping[str, str], name: str) -> bool:
    return environment.get(name, "").strip().casefold() in {"1", "true", "yes", "on"}


def _read_environment_file_value(path: Path, name: str) -> str:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        return ""
    for raw_line in lines:
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        if key.strip() == name:
            return value.strip().strip("\"'")
    return ""


def main() -> None:
    arguments = _parse_arguments()
    dataset_path = arguments.dataset.resolve()
    cases = load_ru_cases(dataset_path, case_ids=arguments.case_id, run_all=arguments.all)
    api_key, project, experiment_id = read_ru_evaluation_langsmith_configuration(
        project_name=arguments.langsmith_project,
        experiment_id=arguments.experiment_id,
    )
    results_path = (arguments.output or _default_results_path()).resolve()
    payload = evaluate_cases(
        cases,
        dataset_path=dataset_path,
        results_path=results_path,
        langsmith_api_key=api_key,
        langsmith_project=project,
        experiment_id=experiment_id,
    )
    print(
        json.dumps(
            {
                "results_path": str(results_path),
                "aggregation": payload["aggregation"],
                "batch_readiness": payload["batch_readiness"],
            },
            ensure_ascii=False,
        ),
        flush=True,
    )


if __name__ == "__main__":
    main()
