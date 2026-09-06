"""Translate existing task callbacks; never execute workflow or provider operations."""

import logging
from collections.abc import Mapping
from threading import Lock
from typing import Any
from uuid import UUID

from langchain_core.callbacks import BaseCallbackHandler
from langgraph.errors import GraphInterrupt

from google_work_agent.adapters.langgraph.activity_step_registry import (
    ActivityStepPresentation,
    resolve_activity_step,
)
from google_work_agent.application.use_cases.trace_event.record_run_activity import (
    ACTIVITY_ROLES,
    RecordRunActivityCommand,
    RecordRunActivityHandler,
)

_LOGGER = logging.getLogger(__name__)

type _ActivityIdentity = tuple[str, str, str, str | None]
type _ActiveStep = tuple[_ActivityIdentity, str, ActivityStepPresentation]


class RunActivityCallback(BaseCallbackHandler):
    def __init__(self, record: RecordRunActivityHandler) -> None:
        self._record = record
        self._active: dict[UUID, _ActivityIdentity] = {}
        self._parents: dict[UUID, UUID] = {}
        self._steps: dict[UUID, _ActiveStep] = {}
        self._lock = Lock()

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
        metadata = metadata or {}
        node = metadata.get("langgraph_node")
        namespace = metadata.get("langgraph_checkpoint_ns")
        with self._lock:
            if parent_run_id is not None:
                self._parents[run_id] = parent_run_id
        if node in ACTIVITY_ROLES and kwargs.get("name") == node and isinstance(namespace, str):
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
            return
        if (
            kwargs.get("name") != node
            or not isinstance(node, str)
            or not isinstance(namespace, str)
        ):
            return
        with self._lock:
            parent_identity = self._semantic_ancestor(parent_run_id)
            presentation = (
                resolve_activity_step(parent_identity[2], node)
                if parent_identity is not None
                else None
            )
            if parent_identity is not None and presentation is not None:
                self._steps[run_id] = (parent_identity, node, presentation)
        if parent_identity is not None and presentation is not None:
            self._emit_step(parent_identity, node, presentation, "STEP_START")

    def on_chain_end(self, outputs: Any, *, run_id: UUID, **kwargs: Any) -> None:
        with self._lock:
            step = self._steps.pop(run_id, None)
            identity = self._active.pop(run_id, None)
            self._parents.pop(run_id, None)
        if step is not None:
            self._emit_step(*step, "STEP_END")
        if identity is not None:
            self._emit(identity, "END", outputs if isinstance(outputs, Mapping) else {})

    def on_chain_error(self, error: BaseException, *, run_id: UUID, **kwargs: Any) -> None:
        with self._lock:
            step = self._steps.pop(run_id, None)
            identity = self._active.pop(run_id, None)
            self._parents.pop(run_id, None)
        observation = "STEP_WAIT" if isinstance(error, GraphInterrupt) else "STEP_ERROR"
        if step is not None:
            self._emit_step(*step, observation)
        if identity is not None:
            self._emit(identity, "WAIT" if isinstance(error, GraphInterrupt) else "ERROR", {})

    def _semantic_ancestor(self, run_id: UUID | None) -> _ActivityIdentity | None:
        current = run_id
        visited: set[UUID] = set()
        while current is not None and current not in visited:
            visited.add(current)
            identity = self._active.get(current)
            if identity is not None:
                return identity
            current = self._parents.get(current)
        return None

    def _emit_step(
        self,
        identity: _ActivityIdentity,
        step_key: str,
        presentation: ActivityStepPresentation,
        observation: Any,
    ) -> None:
        value = {
            "STEP_START": presentation.started,
            "STEP_END": presentation.completed,
            "STEP_WAIT": presentation.waiting,
            "STEP_ERROR": presentation.failed,
        }[observation]
        self._emit(
            identity,
            observation,
            {},
            detail=(step_key, presentation.label, value),
        )

    def _emit(
        self,
        identity: _ActivityIdentity,
        observation: Any,
        output: Mapping[str, object],
        *,
        detail: tuple[str, str, str] | None = None,
    ) -> None:
        try:
            self._record(
                RecordRunActivityCommand(
                    identity[0],
                    identity[1],
                    identity[2],
                    observation,
                    output,
                    identity[3],
                    detail,
                )
            )
        except Exception:
            # Diagnostics must never convert a committed effect into a retryable command failure.
            _LOGGER.warning("Run activity observation unavailable", extra={"run_id": identity[0]})
