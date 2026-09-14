from __future__ import annotations

from typing import Any

from evaluation.dataset_v8 import load_cases
from scripts.execute_canonical_v8 import _fault_target_reached


def test_fault_target_reached__requires_trigger_prerequisite() -> None:
    case = load_cases()["CASE-STRESS-018"]
    verification_only: list[dict[str, Any]] = [
        {
            "kind": "CONNECTOR_READ",
            "tool_id": "tasks_get_task",
            "outcome": "SUCCESS",
        }
    ]

    assert _fault_target_reached(case, verification_only) is False

    after_applied_update: list[dict[str, Any]] = [
        {
            "kind": "CONNECTOR_WRITE",
            "tool_id": "tasks_update_task",
            "outcome": "SUCCESS",
            "effect_applied": True,
        },
        *verification_only,
    ]

    assert _fault_target_reached(case, after_applied_update) is True
