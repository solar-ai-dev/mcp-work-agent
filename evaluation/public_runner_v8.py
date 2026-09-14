"""Canonical v8 one-case execution through only the public Product HTTP API."""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass
from typing import Any

from .public_client_v8 import PublicProductClientV8


@dataclass(frozen=True, slots=True)
class PublicRunResultV8:
    snapshot: dict[str, Any]
    latency_ms: int
    selection_handle_count: int


def execute_public_case(
    client: PublicProductClientV8,
    execution_input: dict[str, Any],
    *,
    auto_approve: bool,
    timeout_seconds: float = 600.0,
) -> PublicRunResultV8:
    if "evaluation_gold" in execution_input:
        raise ValueError("evaluation Gold must never enter the Product runner")
    case_id = _required_text(execution_input, "case_id")
    request_text = _required_text(execution_input, "canonical_user_prompt")
    entry_mode = _required_text(execution_input, "entry_mode")
    raw_bindings = execution_input.get("selected_resource_bindings", [])
    if not isinstance(raw_bindings, list) or not all(
        isinstance(item, dict) for item in raw_bindings
    ):
        raise ValueError(f"{case_id}: selected_resource_bindings must be objects")
    handles = client.resolve_selection_handles(raw_bindings)
    if entry_mode == "RESOURCE_SELECTED" and not handles:
        raise ValueError(f"{case_id}: RESOURCE_SELECTED requires a public selection handle")
    if entry_mode == "AGENT_SEARCH" and handles:
        raise ValueError(f"{case_id}: AGENT_SEARCH cannot receive selection handles")
    token = uuid.uuid4().hex
    conversation = client.create_conversation(
        command_id=f"eval-conversation-{token}", title=f"Canonical v8 {case_id}"
    )
    conversation_id = _required_text(conversation, "conversation_id")
    started = time.monotonic()
    started_run = client.start_run(
        command_id=f"eval-run-{token}",
        conversation_id=conversation_id,
        request_text=request_text,
        entry_mode=entry_mode,
        selected_resource_handles=handles,
    )
    run_id = _required_text(started_run, "run_id")
    snapshot = client.wait_for_observation(
        run_id,
        timeout_seconds=timeout_seconds,
        auto_approve=auto_approve,
    )
    return PublicRunResultV8(
        snapshot=snapshot,
        latency_ms=max(0, int((time.monotonic() - started) * 1_000)),
        selection_handle_count=len(handles),
    )


def _required_text(value: dict[str, Any], field: str) -> str:
    candidate = value.get(field)
    if not isinstance(candidate, str) or not candidate:
        raise ValueError(f"{field} must be a non-empty string")
    return candidate


__all__ = ["PublicRunResultV8", "execute_public_case"]
