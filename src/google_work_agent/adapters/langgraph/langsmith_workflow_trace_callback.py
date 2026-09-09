"""Export safe LangGraph execution metadata to an opt-in LangSmith project."""

from __future__ import annotations

import logging
import re
from collections.abc import Mapping
from datetime import UTC, datetime
from hashlib import sha256
from threading import Lock
from typing import Any, Literal, Protocol
from uuid import UUID

from langchain_core.callbacks import BaseCallbackHandler
from langgraph.errors import GraphInterrupt
from langsmith import Client

from google_work_agent.ports.llm.structured_inference_contracts import LLMInvocationError

_LOGGER = logging.getLogger(__name__)
_SAFE_VALUE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}")
_SAFE_FIELD_PATH = re.compile(r"[$A-Za-z0-9_.\[\]-]{1,160}")
_TRACE_BINDING_KEYS = frozenset(
    {
        "code_sha",
        "experiment_id",
        "model_digest",
        "model_id",
        "prompt_content_hash",
        "prompt_id",
        "prompt_version",
        "question_id",
    }
)
type _LangSmithRunType = Literal[
    "tool",
    "chain",
    "llm",
    "retriever",
    "embedding",
    "prompt",
    "parser",
]


class _LangSmithClient(Protocol):
    def create_run(
        self,
        name: str,
        inputs: dict[str, Any],
        run_type: _LangSmithRunType,
        *,
        project_name: str | None = None,
        **kwargs: Any,
    ) -> None: ...

    def update_run(self, run_id: UUID, **kwargs: Any) -> None: ...

    def flush(self, timeout: float | None = None) -> None: ...

    def close(self, timeout: float | None = None) -> None: ...


class LangSmithWorkflowTraceCallback(BaseCallbackHandler):
    """Record graph and node timing without exporting workflow inputs or outputs."""

    def __init__(
        self,
        *,
        client: _LangSmithClient,
        project_name: str,
        trace_binding: Mapping[str, str] | None = None,
    ) -> None:
        if not _SAFE_VALUE.fullmatch(project_name):
            raise ValueError("LangSmith project name must be a safe opaque identifier")
        self._client = client
        self._project_name = project_name
        self._trace_binding = _validated_trace_binding(trace_binding or {})
        self._parents: dict[UUID, UUID] = {}
        self._active: dict[UUID, tuple[UUID, UUID | None, dict[str, object]]] = {}
        self._lock = Lock()
        self._closed = False

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
        safe_metadata = self._safe_metadata(metadata or {})
        domain_run_id = safe_metadata.get("domain_run_id")
        if domain_run_id is None:
            return
        node = safe_metadata.get("graph_node")
        is_root = parent_run_id is None
        is_node = isinstance(node, str) and kwargs.get("name") == node
        with self._lock:
            if self._closed:
                return
            if parent_run_id is not None:
                self._parents[run_id] = parent_run_id
            if not is_root and not is_node:
                return
            parent_trace = self._nearest_active(parent_run_id)
            trace_id = run_id if parent_trace is None else parent_trace[0]
            traced_parent_id = None if parent_trace is None else parent_trace[1]
        name = "production_langgraph" if is_root else f"node:{node}"
        tags = ["google-work-agent", "development-observability", "langgraph"]
        tags.append("graph" if is_root else "node")
        try:
            self._client.create_run(
                name,
                {},
                "chain",
                id=run_id,
                trace_id=trace_id,
                parent_run_id=traced_parent_id,
                project_name=self._project_name,
                start_time=datetime.now(UTC),
                extra={"metadata": safe_metadata},
                tags=tags,
            )
        except Exception:
            _LOGGER.warning("LangSmith workflow trace start unavailable")
            return
        with self._lock:
            if not self._closed:
                self._active[run_id] = (trace_id, traced_parent_id, safe_metadata)

    def on_chain_end(self, outputs: Any, *, run_id: UUID, **kwargs: Any) -> None:
        del outputs, kwargs
        active = self._finish_tracking(run_id)
        if active is None:
            return
        try:
            self._client.update_run(
                run_id,
                trace_id=active[0],
                end_time=datetime.now(UTC),
                outputs={},
            )
        except Exception:
            _LOGGER.warning("LangSmith workflow trace completion unavailable")

    def on_chain_error(self, error: BaseException, *, run_id: UUID, **kwargs: Any) -> None:
        del kwargs
        active = self._finish_tracking(run_id)
        if active is None:
            return
        metadata = dict(active[2])
        tags = ["google-work-agent", "development-observability", "langgraph"]
        if isinstance(error, GraphInterrupt):
            metadata["outcome"] = "INTERRUPTED"
            tags.append("interrupted")
            safe_error = None
        else:
            error_type = type(error).__name__
            metadata["error_type"] = (
                error_type if _SAFE_VALUE.fullmatch(error_type) else "Exception"
            )
            safe_error_code = _safe_error_code(error)
            if safe_error_code is not None:
                metadata["safe_error_code"] = safe_error_code
            affected_field_paths = _safe_affected_field_paths(error)
            if affected_field_paths:
                metadata["affected_field_path_hashes"] = [
                    sha256(path.encode("utf-8")).hexdigest()[:16]
                    for path in affected_field_paths
                ]
            if isinstance(error, LLMInvocationError):
                metadata["provider_dispatch_occurred"] = error.provider_dispatch_occurred
            tags.append("failed")
            safe_error = f"SAFE_ERROR_TYPE:{metadata['error_type']}"
        try:
            self._client.update_run(
                run_id,
                trace_id=active[0],
                end_time=datetime.now(UTC),
                error=safe_error,
                outputs={},
                extra={"metadata": metadata},
                tags=tags,
            )
        except Exception:
            _LOGGER.warning("LangSmith workflow trace failure unavailable")

    def flush(self) -> None:
        with self._lock:
            if self._closed:
                return
        try:
            self._client.flush(timeout=5.0)
        except Exception:
            _LOGGER.warning("LangSmith workflow trace flush unavailable")

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
        try:
            self._client.flush(timeout=5.0)
            self._client.close(timeout=5.0)
        except Exception:
            _LOGGER.warning("LangSmith workflow trace close unavailable")

    def _finish_tracking(
        self, run_id: UUID
    ) -> tuple[UUID, UUID | None, dict[str, object]] | None:
        with self._lock:
            self._parents.pop(run_id, None)
            return self._active.pop(run_id, None)

    def _nearest_active(self, run_id: UUID | None) -> tuple[UUID, UUID] | None:
        current = run_id
        visited: set[UUID] = set()
        while current is not None and current not in visited:
            visited.add(current)
            active = self._active.get(current)
            if active is not None:
                return active[0], current
            current = self._parents.get(current)
        return None

    def _safe_metadata(self, metadata: Mapping[str, object]) -> dict[str, object]:
        product_run_id = metadata.get("product_run_id")
        if not isinstance(product_run_id, str) or not _SAFE_VALUE.fullmatch(product_run_id):
            return {}
        result: dict[str, object] = {
            "domain_run_id": product_run_id,
            **self._trace_binding,
        }
        for source, target in (
            ("graph_profile", "graph_profile"),
            ("graph_version", "graph_version"),
            ("langgraph_node", "graph_node"),
        ):
            value = metadata.get(source)
            if isinstance(value, str) and _SAFE_VALUE.fullmatch(value):
                result[target] = value
        namespace = metadata.get("langgraph_checkpoint_ns")
        if isinstance(namespace, str) and namespace:
            result["checkpoint_namespace_hash"] = sha256(namespace.encode("utf-8")).hexdigest()[
                :16
            ]
        return result


def create_langsmith_workflow_trace_callback(
    *,
    api_key: str,
    project_name: str,
    trace_binding: Mapping[str, str] | None = None,
) -> LangSmithWorkflowTraceCallback:
    """Build the only LangSmith client with raw payload export disabled."""

    if not api_key.strip():
        raise ValueError("LangSmith API key is required")
    client = Client(
        api_url="https://api.smith.langchain.com",
        api_key=api_key.strip(),
        auto_batch_tracing=True,
        hide_inputs=True,
        hide_outputs=True,
        omit_traced_runtime_info=True,
    )
    return LangSmithWorkflowTraceCallback(
        client=client,
        project_name=project_name,
        trace_binding=trace_binding,
    )


def _validated_trace_binding(value: Mapping[str, str]) -> dict[str, str]:
    if not value:
        return {}
    if set(value) != _TRACE_BINDING_KEYS:
        raise ValueError("LangSmith trace binding must contain the complete safe field set")
    result = dict(value)
    if any(not _SAFE_VALUE.fullmatch(item) for item in result.values()):
        raise ValueError("LangSmith trace binding values must be safe opaque identifiers")
    return result


def _safe_error_code(error: BaseException) -> str | None:
    if isinstance(error, LLMInvocationError):
        return error.code.value
    reason_code = getattr(error, "reason_code", None)
    if isinstance(reason_code, str) and _SAFE_VALUE.fullmatch(reason_code):
        return reason_code
    return None


def _safe_affected_field_paths(error: BaseException) -> tuple[str, ...]:
    value = getattr(error, "affected_field_paths", ())
    if not isinstance(value, (list, tuple)):
        return ()
    return tuple(
        path
        for path in value[:16]
        if isinstance(path, str) and _SAFE_FIELD_PATH.fullmatch(path)
    )


__all__ = [
    "LangSmithWorkflowTraceCallback",
    "create_langsmith_workflow_trace_callback",
]
