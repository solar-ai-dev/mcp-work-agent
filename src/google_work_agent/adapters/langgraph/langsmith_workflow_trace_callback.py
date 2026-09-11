"""Export safe LangGraph execution metadata to an opt-in LangSmith project."""

from __future__ import annotations

import logging
import re
from collections.abc import Mapping
from datetime import UTC, datetime
from hashlib import sha256
from threading import Lock
from typing import Any, Literal, NamedTuple, Protocol
from uuid import UUID, uuid4

from langchain_core.callbacks import BaseCallbackHandler
from langgraph.errors import GraphInterrupt
from langsmith import Client

from google_work_agent.adapters.langgraph.langsmith_llm_semantic_projection import (
    sanitize_llm_semantic_projection,
)
from google_work_agent.adapters.langgraph.langsmith_workflow_io_projection import (
    project_langsmith_workflow_payload,
)
from google_work_agent.ports.llm.structured_inference_contracts import LLMInvocationError
from google_work_agent.ports.system.external_call_trace_port import (
    ExternalCallTraceFinishV1,
    ExternalCallTraceHandleV1,
    ExternalCallTracePort,
    ExternalCallTraceStartV1,
)

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


class _ActiveTrace(NamedTuple):
    trace_id: UUID
    parent_run_id: UUID | None
    metadata: dict[str, object]
    dotted_order: str


class _NearestActiveTrace(NamedTuple):
    trace_id: UUID
    run_id: UUID
    dotted_order: str


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


class LangSmithWorkflowTraceCallback(BaseCallbackHandler, ExternalCallTracePort):
    """Record graph and node timing with bounded safe input/output projections."""

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
        self._active: dict[UUID, _ActiveTrace] = {}
        self._external_active: dict[UUID, _ActiveTrace] = {}
        self._roots_by_domain_run_id: dict[str, UUID] = {}
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
        del serialized
        safe_metadata = self._safe_metadata(metadata or {})
        domain_run_id = safe_metadata.get("domain_run_id")
        if not isinstance(domain_run_id, str):
            return
        node = safe_metadata.get("graph_node")
        is_root = parent_run_id is None
        is_node = isinstance(node, str) and kwargs.get("name") == node
        start_time = datetime.now(UTC)
        with self._lock:
            if self._closed:
                return
            if parent_run_id is not None:
                self._parents[run_id] = parent_run_id
            if not is_root and not is_node:
                return
            parent_trace = self._nearest_active(parent_run_id)
            trace_id = run_id if parent_trace is None else parent_trace.trace_id
            traced_parent_id = None if parent_trace is None else parent_trace.run_id
            dotted_order = _dotted_order(
                start_time=start_time,
                run_id=run_id,
                parent_dotted_order=(None if parent_trace is None else parent_trace.dotted_order),
            )
        name = "production_langgraph" if is_root else f"node:{node}"
        tags = ["google-work-agent", "development-observability", "langgraph"]
        tags.append("graph" if is_root else "node")
        try:
            self._client.create_run(
                name,
                {"workflow": project_langsmith_workflow_payload(inputs)},
                "chain",
                id=run_id,
                trace_id=trace_id,
                dotted_order=dotted_order,
                parent_run_id=traced_parent_id,
                project_name=self._project_name,
                start_time=start_time,
                extra={"metadata": safe_metadata},
                tags=tags,
            )
        except Exception:
            _LOGGER.warning("LangSmith workflow trace start unavailable")
            return
        with self._lock:
            if not self._closed:
                self._active[run_id] = _ActiveTrace(
                    trace_id=trace_id,
                    parent_run_id=traced_parent_id,
                    metadata=safe_metadata,
                    dotted_order=dotted_order,
                )
                if is_root:
                    self._roots_by_domain_run_id[domain_run_id] = run_id

    def begin_external_call(
        self, command: ExternalCallTraceStartV1
    ) -> ExternalCallTraceHandleV1 | None:
        """Create a payload-free LLM/tool child under the active workflow root."""

        if command.schema_version != 1:
            return None
        domain_run_id = command.domain_run_id
        if not isinstance(domain_run_id, str) or not _SAFE_VALUE.fullmatch(domain_run_id):
            return None
        start_time = datetime.now(UTC)
        trace_run_id = uuid4()
        with self._lock:
            if self._closed:
                return None
            root_run_id = self._roots_by_domain_run_id.get(domain_run_id)
            root = None if root_run_id is None else self._active.get(root_run_id)
            if root is None or root_run_id is None:
                return None
            dotted_order = _dotted_order(
                start_time=start_time,
                run_id=trace_run_id,
                parent_dotted_order=root.dotted_order,
            )
            safe_metadata = _external_call_metadata(command, root.metadata)
            inputs = {"call": _external_call_input(command)}
            name, run_type, kind_tag = _external_run_identity(command.call_kind)
        try:
            self._client.create_run(
                name,
                inputs,
                run_type,
                id=trace_run_id,
                trace_id=root.trace_id,
                dotted_order=dotted_order,
                parent_run_id=root_run_id,
                project_name=self._project_name,
                start_time=start_time,
                extra={"metadata": safe_metadata},
                tags=[
                    "google-work-agent",
                    "development-observability",
                    "external-dispatch",
                    kind_tag,
                ],
            )
        except Exception:
            _LOGGER.warning("LangSmith external call trace start unavailable")
            return None
        with self._lock:
            if self._closed:
                return None
            self._external_active[trace_run_id] = _ActiveTrace(
                trace_id=root.trace_id,
                parent_run_id=root_run_id,
                metadata=safe_metadata,
                dotted_order=dotted_order,
            )
        return ExternalCallTraceHandleV1(1, str(trace_run_id))

    def finish_external_call(
        self,
        handle: ExternalCallTraceHandleV1,
        result: ExternalCallTraceFinishV1,
    ) -> None:
        """Complete one external child span without changing product execution."""

        if handle.schema_version != 1 or result.schema_version != 1:
            return
        try:
            trace_run_id = UUID(handle.trace_run_id)
        except ValueError:
            return
        with self._lock:
            active = self._external_active.pop(trace_run_id, None)
        if active is None:
            return
        metadata = dict(active.metadata)
        error_type = _safe_optional_value(result.error_type)
        safe_error_code = _safe_optional_value(result.safe_error_code)
        if error_type is not None:
            metadata["error_type"] = error_type
        if safe_error_code is not None:
            metadata["safe_error_code"] = safe_error_code
        output = _external_call_output(result)
        try:
            self._client.update_run(
                trace_run_id,
                trace_id=active.trace_id,
                dotted_order=active.dotted_order,
                parent_run_id=active.parent_run_id,
                end_time=datetime.now(UTC),
                error=(
                    None
                    if result.status == "COMPLETED"
                    else f"SAFE_ERROR_TYPE:{error_type or 'ExternalCallError'}"
                ),
                outputs={"call": output},
                extra={"metadata": metadata},
                tags=[
                    "google-work-agent",
                    "development-observability",
                    "external-dispatch",
                    result.status.lower(),
                ],
            )
        except Exception:
            _LOGGER.warning("LangSmith external call trace completion unavailable")

    def on_chain_end(self, outputs: Any, *, run_id: UUID, **kwargs: Any) -> None:
        del kwargs
        active = self._finish_tracking(run_id)
        if active is None:
            return
        try:
            self._client.update_run(
                run_id,
                trace_id=active.trace_id,
                dotted_order=active.dotted_order,
                parent_run_id=active.parent_run_id,
                end_time=datetime.now(UTC),
                outputs={"workflow": project_langsmith_workflow_payload(outputs)},
            )
        except Exception:
            _LOGGER.warning("LangSmith workflow trace completion unavailable")

    def on_chain_error(self, error: BaseException, *, run_id: UUID, **kwargs: Any) -> None:
        del kwargs
        active = self._finish_tracking(run_id)
        if active is None:
            return
        metadata = dict(active.metadata)
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
                metadata["validation_stage"] = "POST_INFERENCE_VALIDATION"
                if safe_error_code is not None:
                    metadata["validation_rule"] = safe_error_code
                metadata["affected_field_paths"] = list(affected_field_paths)
                metadata["affected_field_path_hashes"] = [
                    sha256(path.encode("utf-8")).hexdigest()[:16] for path in affected_field_paths
                ]
            if isinstance(error, LLMInvocationError):
                metadata["provider_dispatch_occurred"] = error.provider_dispatch_occurred
            tags.append("failed")
            safe_error = f"SAFE_ERROR_TYPE:{metadata['error_type']}"
        try:
            self._client.update_run(
                run_id,
                trace_id=active.trace_id,
                dotted_order=active.dotted_order,
                parent_run_id=active.parent_run_id,
                end_time=datetime.now(UTC),
                error=safe_error,
                outputs={"workflow": project_langsmith_workflow_payload({})},
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

    def _finish_tracking(self, run_id: UUID) -> _ActiveTrace | None:
        with self._lock:
            self._parents.pop(run_id, None)
            active = self._active.pop(run_id, None)
            if active is not None:
                domain_run_id = active.metadata.get("domain_run_id")
                if (
                    isinstance(domain_run_id, str)
                    and self._roots_by_domain_run_id.get(domain_run_id) == run_id
                ):
                    self._roots_by_domain_run_id.pop(domain_run_id, None)
            return active

    def _nearest_active(self, run_id: UUID | None) -> _NearestActiveTrace | None:
        current = run_id
        visited: set[UUID] = set()
        while current is not None and current not in visited:
            visited.add(current)
            active = self._active.get(current)
            if active is not None:
                return _NearestActiveTrace(
                    trace_id=active.trace_id,
                    run_id=current,
                    dotted_order=active.dotted_order,
                )
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
            result["checkpoint_namespace_hash"] = sha256(namespace.encode("utf-8")).hexdigest()[:16]
        return result


def create_langsmith_workflow_trace_callback(
    *,
    api_key: str,
    project_name: str,
    trace_binding: Mapping[str, str] | None = None,
) -> LangSmithWorkflowTraceCallback:
    """Build the only LangSmith client used by the safe workflow projection."""

    if not api_key.strip():
        raise ValueError("LangSmith API key is required")
    client = Client(
        api_url="https://api.smith.langchain.com",
        api_key=api_key.strip(),
        auto_batch_tracing=True,
        hide_inputs=False,
        hide_outputs=False,
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
        path for path in value[:16] if isinstance(path, str) and _SAFE_FIELD_PATH.fullmatch(path)
    )


def _dotted_order(
    *,
    start_time: datetime,
    run_id: UUID,
    parent_dotted_order: str | None,
) -> str:
    current = start_time.strftime("%Y%m%dT%H%M%S%fZ") + str(run_id)
    if parent_dotted_order is None:
        return current
    return f"{parent_dotted_order}.{current}"


def _external_run_identity(
    call_kind: str,
) -> tuple[str, Literal["llm", "tool"], str]:
    if call_kind == "LLM_INFERENCE":
        return "llm:structured_inference", "llm", "llm"
    if call_kind == "LLM_SCHEMA_REPAIR":
        return "llm:schema_repair", "llm", "llm"
    return "connector:read", "tool", "connector"


def _external_call_metadata(
    command: ExternalCallTraceStartV1,
    root_metadata: Mapping[str, object],
) -> dict[str, object]:
    result = dict(root_metadata)
    result["external_call_kind"] = command.call_kind
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
        value = _safe_optional_value(getattr(command, name))
        if value is not None:
            result[name] = value
    return result


def _external_call_input(command: ExternalCallTraceStartV1) -> dict[str, object]:
    result: dict[str, object] = {
        "schema_version": 1,
        "call_kind": command.call_kind,
    }
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
        value = _safe_optional_value(getattr(command, name))
        if value is not None:
            result[name] = value
    semantic_input = sanitize_llm_semantic_projection(command.safe_semantic_input)
    if semantic_input is not None:
        result["semantic_input"] = semantic_input
    return result


def _external_call_output(result: ExternalCallTraceFinishV1) -> dict[str, object]:
    output: dict[str, object] = {
        "schema_version": 1,
        "status": result.status,
        "duration_ms": max(0, result.duration_ms),
    }
    for name in ("input_tokens", "output_tokens", "total_tokens", "result_count"):
        value = getattr(result, name)
        if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
            output[name] = value
    if isinstance(result.has_next_page, bool):
        output["has_next_page"] = result.has_next_page
    if (error_type := _safe_optional_value(result.error_type)) is not None:
        output["error_type"] = error_type
    if (error_code := _safe_optional_value(result.safe_error_code)) is not None:
        output["safe_error_code"] = error_code
    semantic_output = sanitize_llm_semantic_projection(result.safe_semantic_output)
    if semantic_output is not None:
        output["semantic_output"] = semantic_output
    return output


def _safe_optional_value(value: object) -> str | None:
    return value if isinstance(value, str) and _SAFE_VALUE.fullmatch(value) else None


__all__ = [
    "LangSmithWorkflowTraceCallback",
    "create_langsmith_workflow_trace_callback",
]
