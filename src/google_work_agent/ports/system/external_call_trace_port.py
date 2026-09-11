"""Safe tracing contract for actual external dispatches within one workflow Run."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal, Protocol

type ExternalCallKind = Literal[
    "LLM_INFERENCE",
    "LLM_SCHEMA_REPAIR",
    "CONNECTOR_READ",
]
type ExternalCallStatus = Literal["COMPLETED", "FAILED"]


@dataclass(frozen=True, slots=True, kw_only=True)
class ExternalCallTraceStartV1:
    schema_version: Literal[1]
    domain_run_id: str | None
    call_kind: ExternalCallKind
    operation: str
    provider: str | None = None
    model_id: str | None = None
    prompt_id: str | None = None
    prompt_version: str | None = None
    prompt_content_hash: str | None = None
    output_schema_id: str | None = None
    connector_id: str | None = None
    tool_id: str | None = None
    effect: str | None = None
    safe_semantic_input: Mapping[str, object] | None = None


@dataclass(frozen=True, slots=True)
class ExternalCallTraceHandleV1:
    schema_version: Literal[1]
    trace_run_id: str


@dataclass(frozen=True, slots=True, kw_only=True)
class ExternalCallTraceFinishV1:
    schema_version: Literal[1]
    status: ExternalCallStatus
    duration_ms: int
    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None
    result_count: int | None = None
    has_next_page: bool | None = None
    error_type: str | None = None
    safe_error_code: str | None = None
    safe_semantic_output: Mapping[str, object] | None = None


class ExternalCallTracePort(Protocol):
    """Project one actual provider/Connector call without business payloads."""

    def begin_external_call(
        self, command: ExternalCallTraceStartV1
    ) -> ExternalCallTraceHandleV1 | None: ...

    def finish_external_call(
        self,
        handle: ExternalCallTraceHandleV1,
        result: ExternalCallTraceFinishV1,
    ) -> None: ...


__all__ = [
    "ExternalCallTraceFinishV1",
    "ExternalCallTraceHandleV1",
    "ExternalCallTracePort",
    "ExternalCallTraceStartV1",
]
