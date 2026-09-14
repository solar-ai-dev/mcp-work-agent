"""Exact late-bound callbacks used by Application cancel resolution."""

from __future__ import annotations

from collections.abc import Callable

SettlePendingCancelAction = Callable[[str, int], bool]
ResolveCancelAction = Callable[[str], bool]


class CancelResolutionRuntimeCallbacks:
    """Bind the runtime-owned cancel operations once without dynamic name lookup."""

    def __init__(self) -> None:
        self._settle_pending_action: SettlePendingCancelAction | None = None
        self._reconcile_inflight_action: ResolveCancelAction | None = None
        self._verify_executed_action: ResolveCancelAction | None = None
        self._resolve_unknown_action: ResolveCancelAction | None = None

    def bind(
        self,
        *,
        settle_pending_action: SettlePendingCancelAction,
        reconcile_inflight_action: ResolveCancelAction,
        verify_executed_action: ResolveCancelAction,
        resolve_unknown_action: ResolveCancelAction,
    ) -> None:
        if self._settle_pending_action is not None:
            raise RuntimeError("cancel resolution runtime callbacks are already bound")
        self._settle_pending_action = settle_pending_action
        self._reconcile_inflight_action = reconcile_inflight_action
        self._verify_executed_action = verify_executed_action
        self._resolve_unknown_action = resolve_unknown_action

    def settle_pending_action(self, action_id: str, version: int) -> bool:
        callback = self._settle_pending_action
        if callback is None:
            raise RuntimeError("cancel resolution runtime callbacks are not bound")
        return callback(action_id, version)

    def reconcile_inflight_action(self, action_id: str) -> bool:
        callback = self._reconcile_inflight_action
        if callback is None:
            raise RuntimeError("cancel resolution runtime callbacks are not bound")
        return callback(action_id)

    def verify_executed_action(self, action_id: str) -> bool:
        callback = self._verify_executed_action
        if callback is None:
            raise RuntimeError("cancel resolution runtime callbacks are not bound")
        return callback(action_id)

    def resolve_unknown_action(self, action_id: str) -> bool:
        callback = self._resolve_unknown_action
        if callback is None:
            raise RuntimeError("cancel resolution runtime callbacks are not bound")
        return callback(action_id)


__all__ = ["CancelResolutionRuntimeCallbacks"]
