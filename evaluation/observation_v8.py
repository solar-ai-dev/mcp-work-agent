"""Safe normalized public observation for Canonical v8 grading."""

from __future__ import annotations

from typing import Any


def normalize_public_observation(
    *, case_id: str, snapshot: dict[str, Any], call_records: list[dict[str, Any]], latency_ms: int
) -> dict[str, Any]:
    raw_run = snapshot.get("run")
    run: dict[str, Any] = raw_run if isinstance(raw_run, dict) else {}
    raw_messages = snapshot.get("messages")
    messages: list[Any] = raw_messages if isinstance(raw_messages, list) else []
    assistant_messages = [
        str(item.get("content", ""))
        for item in messages
        if isinstance(item, dict)
        and str(item.get("role", "")).lower() == "assistant"
    ]
    raw_actions = snapshot.get("actions")
    actions: list[Any] = raw_actions if isinstance(raw_actions, list) else []
    reads = [record for record in call_records if record.get("kind") == "CONNECTOR_READ"]
    writes = [record for record in call_records if record.get("kind") == "CONNECTOR_WRITE"]
    llm = [record for record in call_records if record.get("kind") == "LLM"]
    return {
        "schema_version": 1,
        "case_id": case_id,
        "run_id": run.get("run_id"),
        "public_status": run.get("status"),
        "terminal_result_kind": snapshot.get("terminal_result_kind"),
        "assistant_final_message": assistant_messages[-1] if assistant_messages else "",
        "pending_interrupt": snapshot.get("pending_interrupt"),
        "actions": actions,
        "context_preview": snapshot.get("context_preview"),
        "error": snapshot.get("error"),
        "execution_status": snapshot.get("execution_status"),
        "verification_summary": snapshot.get("verification_summary"),
        "recovery_summary": snapshot.get("recovery_summary"),
        "started_at_ms": run.get("started_at_ms"),
        "finished_at_ms": run.get("finished_at_ms"),
        "latency_ms": latency_ms,
        "llm_call_count": len(llm),
        "connector_read_count": len(reads),
        "connector_write_count": len(writes),
        "connector_calls": call_records,
        "write_dispatch_count": len(writes),
    }


__all__ = ["normalize_public_observation"]
