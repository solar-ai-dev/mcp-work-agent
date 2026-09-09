from __future__ import annotations

import pytest

from google_work_agent.adapters.langgraph.main.cancel_resolution_runtime_callbacks import (
    CancelResolutionRuntimeCallbacks,
)


def test_cancel_resolution_callbacks__reject_calls__before_binding() -> None:
    callbacks = CancelResolutionRuntimeCallbacks()

    with pytest.raises(RuntimeError, match="not bound"):
        callbacks.settle_pending_action("action-1", 3)
    with pytest.raises(RuntimeError, match="not bound"):
        callbacks.reconcile_inflight_action("action-1")
    with pytest.raises(RuntimeError, match="not bound"):
        callbacks.verify_executed_action("action-1")
    with pytest.raises(RuntimeError, match="not bound"):
        callbacks.resolve_unknown_action("action-1")


def test_cancel_resolution_callbacks__dispatch_exact_arguments__after_binding() -> None:
    calls: list[tuple[object, ...]] = []

    def settle(action_id: str, version: int) -> bool:
        calls.append(("settle", action_id, version))
        return True

    def reconcile(action_id: str) -> bool:
        calls.append(("reconcile", action_id))
        return False

    def verify(action_id: str) -> bool:
        calls.append(("verify", action_id))
        return True

    def resolve_unknown(action_id: str) -> bool:
        calls.append(("unknown", action_id))
        return False

    callbacks = CancelResolutionRuntimeCallbacks()
    callbacks.bind(
        settle_pending_action=settle,
        reconcile_inflight_action=reconcile,
        verify_executed_action=verify,
        resolve_unknown_action=resolve_unknown,
    )

    assert callbacks.settle_pending_action("action-1", 3) is True
    assert callbacks.reconcile_inflight_action("action-2") is False
    assert callbacks.verify_executed_action("action-3") is True
    assert callbacks.resolve_unknown_action("action-4") is False
    assert calls == [
        ("settle", "action-1", 3),
        ("reconcile", "action-2"),
        ("verify", "action-3"),
        ("unknown", "action-4"),
    ]


def test_cancel_resolution_callbacks__after_binding__reject_rebinding() -> None:
    callbacks = CancelResolutionRuntimeCallbacks()
    callbacks.bind(
        settle_pending_action=lambda _action_id, _version: True,
        reconcile_inflight_action=lambda _action_id: True,
        verify_executed_action=lambda _action_id: True,
        resolve_unknown_action=lambda _action_id: True,
    )

    with pytest.raises(RuntimeError, match="already bound"):
        callbacks.bind(
            settle_pending_action=lambda _action_id, _version: False,
            reconcile_inflight_action=lambda _action_id: False,
            verify_executed_action=lambda _action_id: False,
            resolve_unknown_action=lambda _action_id: False,
        )
