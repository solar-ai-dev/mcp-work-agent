"""Translate existing task callbacks; never execute workflow or provider operations."""

import logging
from collections.abc import Mapping
from threading import Lock
from typing import Any
from uuid import UUID

from langchain_core.callbacks import BaseCallbackHandler
from langgraph.errors import GraphInterrupt

from google_work_agent.application.use_cases.trace_event.record_run_activity import (
    ACTIVITY_ROLES,
    RecordRunActivityCommand,
    RecordRunActivityHandler,
)

_LOGGER = logging.getLogger(__name__)


class RunActivityCallback(BaseCallbackHandler):
    def __init__(self, record: RecordRunActivityHandler) -> None:
        self._record = record
        self._active: dict[UUID, tuple[str, str, str, str | None]] = {}
        self._lock = Lock()

    def on_chain_start(
        self,
        serialized: Any,
        inputs: Any,
        *,
        run_id: UUID,
        metadata: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> None:
        metadata = metadata or {}
        node = metadata.get("langgraph_node")
        namespace = metadata.get("langgraph_checkpoint_ns")
        if (
            node not in ACTIVITY_ROLES
            or kwargs.get("name") != node
            or not isinstance(namespace, str)
        ):
            return
        # Inner graph nodes have their own callbacks; only the responsibility invocation is a row.
        if not isinstance(inputs, Mapping) or not isinstance(inputs.get("run_id"), str):
            return
        plan_id = inputs.get("approved_plan_id")
        identity = (
            inputs["run_id"],
            namespace,
            node,
            plan_id if isinstance(plan_id, str) else None,
        )
        with self._lock:
            self._active[run_id] = identity
        self._emit(identity, "START", {})

    def on_chain_end(self, outputs: Any, *, run_id: UUID, **kwargs: Any) -> None:
        with self._lock:
            identity = self._active.pop(run_id, None)
        if identity is not None:
            self._emit(identity, "END", outputs if isinstance(outputs, Mapping) else {})

    def on_chain_error(self, error: BaseException, *, run_id: UUID, **kwargs: Any) -> None:
        with self._lock:
            identity = self._active.pop(run_id, None)
        if identity is not None:
            self._emit(identity, "WAIT" if isinstance(error, GraphInterrupt) else "ERROR", {})

    def _emit(
        self,
        identity: tuple[str, str, str, str | None],
        observation: Any,
        output: Mapping[str, object],
    ) -> None:
        try:
            self._record(
                RecordRunActivityCommand(
                    identity[0], identity[1], identity[2], observation, output, identity[3]
                )
            )
        except Exception:
            # Diagnostics must never convert a committed effect into a retryable command failure.
            _LOGGER.warning("Run activity observation unavailable", extra={"run_id": identity[0]})
