"""Canonical closed TERMINAL_COMMIT dispatcher."""

from __future__ import annotations

from collections.abc import Callable, Mapping

from google_work_agent.adapters.langgraph.main.nodes.response_synthesis_node import (
    TerminalCommitIntentV1,
    validate_terminal_commit_intent,
)

type TerminalHandler = Callable[[Mapping[str, object], TerminalCommitIntentV1], object]
type RebuildTerminalIntent = Callable[
    [Mapping[str, object], Mapping[str, object]], TerminalCommitIntentV1
]

_TERMINAL_STATUSES = frozenset({"COMPLETED", "BLOCKED", "FAILED", "CANCELLED"})


def terminal_commit_node(
    state: Mapping[str, object],
    *,
    read_terminal_facts: Callable[[str], Mapping[str, object]],
    complete_answer_only: TerminalHandler,
    complete_read_only: TerminalHandler,
    complete_write: TerminalHandler,
    block_run: TerminalHandler,
    finalize_cancel: TerminalHandler,
    resolve_recovery: TerminalHandler,
    rebuild_terminal_intent: RebuildTerminalIntent | None = None,
) -> dict[str, object]:
    """Invoke exactly one existing lifecycle handler, or verify its durable replay."""

    run_id = state.get("run_id")
    if not isinstance(run_id, str) or not run_id:
        raise ValueError("run_id is required")
    intent = validate_terminal_commit_intent(state.get("terminal_commit_intent"))
    before = read_terminal_facts(run_id)
    if _is_committed(before):
        _verify_committed(before, intent)
        return _target_patch("finalize")

    handlers = {
        "COMPLETE_ANSWER_ONLY": complete_answer_only,
        "COMPLETE_READ_ONLY": complete_read_only,
        "COMPLETE_WRITE": complete_write,
        "BLOCK_RUN": block_run,
        "FINALIZE_CANCEL": finalize_cancel,
        "RECOVERY_ACCEPT_PARTIAL": resolve_recovery,
        "RECOVERY_CANCEL": resolve_recovery,
        "RECOVERY_FAIL": resolve_recovery,
    }
    handler = handlers.get(intent["kind"])
    if handler is None:
        raise ValueError("terminal commit kind has no registered handler")
    result = handler(state, intent)
    after = read_terminal_facts(run_id)
    if getattr(result, "applied", None) is not False:
        _verify_committed(after, intent)
        return _target_patch("finalize")
    if _is_committed(after):
        _verify_committed(after, intent)
        return _target_patch("finalize")

    target = _current_control_target(after)
    if target != "domain_reconcile":
        return _target_patch(target)
    if rebuild_terminal_intent is None or not _can_rebuild_write_intent(after):
        return _target_patch("domain_reconcile")

    fresh_intent = rebuild_terminal_intent(state, after)
    if fresh_intent["expected_run_version"] <= intent["expected_run_version"]:
        return _target_patch("domain_reconcile")
    fresh_handler = handlers.get(fresh_intent["kind"])
    if fresh_handler is None:
        raise ValueError("rebuilt terminal commit kind has no registered handler")
    fresh_result = fresh_handler(state, fresh_intent)
    final_facts = read_terminal_facts(run_id)
    if _is_committed(final_facts):
        _verify_committed(final_facts, fresh_intent)
        return _target_patch("finalize")
    if getattr(fresh_result, "applied", None) is False:
        return _target_patch(_current_control_target(final_facts))
    _verify_committed(final_facts, fresh_intent)
    return _target_patch("finalize")


def _is_committed(facts: Mapping[str, object]) -> bool:
    return facts.get("status") in _TERMINAL_STATUSES


def _can_rebuild_write_intent(facts: Mapping[str, object]) -> bool:
    if facts.get("cancel_intent_active") is True:
        return False
    if facts.get("status") in {"CANCEL_REQUESTED", "RECOVERY_REQUIRED", "REAUTH_REQUIRED"}:
        return False
    effects = facts.get("action_effect_types")
    statuses = facts.get("action_statuses")
    return (
        isinstance(effects, (list, tuple))
        and bool(effects)
        and all(effect in {"CREATE", "UPDATE", "SEND", "DELETE"} for effect in effects)
        and isinstance(statuses, (list, tuple))
        and bool(statuses)
        and all(
            status in {"VERIFIED", "REJECTED", "CANCELLED", "DEPENDENCY_BLOCKED", "BLOCKED"}
            for status in statuses
        )
    )


def _current_control_target(facts: Mapping[str, object]) -> str:
    status = facts.get("status")
    if status == "CANCEL_REQUESTED" or (
        status == "VERIFYING" and facts.get("cancel_intent_active") is True
    ):
        return "cancel_resolution"
    if status == "RECOVERY_REQUIRED":
        return "recovery"
    return "domain_reconcile"


def _target_patch(target: str) -> dict[str, object]:
    return {
        "__logical_target__": target,
        "__target__": target,
        "workflow_phase": "TERMINAL_COMMIT",
        "terminal_commit_intent": None,
    }


def _verify_committed(facts: Mapping[str, object], intent: TerminalCommitIntentV1) -> None:
    status = facts.get("status")
    result_kind = facts.get("terminal_result_kind")
    final_message_count = facts.get("final_message_count")
    version = facts.get("version")
    if status not in _TERMINAL_STATUSES:
        raise RuntimeError("terminal lifecycle handler did not commit a terminal Run")
    if result_kind not in {"SUCCESS", "PARTIAL", "BLOCKED", "FAILED", "CANCELLED"}:
        raise RuntimeError("terminal Run is missing terminal_result_kind")
    if final_message_count != 1:
        raise RuntimeError("terminal Run must have exactly one final ASSISTANT Message")
    if not isinstance(version, int) or version < intent["expected_run_version"]:
        raise RuntimeError("terminal Run version is older than terminal intent")


__all__ = ["terminal_commit_node"]
