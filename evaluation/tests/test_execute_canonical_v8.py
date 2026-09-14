from __future__ import annotations

from typing import Any

from evaluation.dataset_v8 import load_cases
from scripts import execute_canonical_v8
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


def test_frozen_metadata__binds_execution_runner_and_public_client(
    monkeypatch: Any,
) -> None:
    monkeypatch.setattr(execute_canonical_v8, "_git", lambda *args: "a" * 40)
    monkeypatch.setattr(
        execute_canonical_v8, "_ollama_digest", lambda model_id: f"digest:{model_id}"
    )

    metadata = execute_canonical_v8._frozen_metadata(
        full_run=False,
        case_timeout=300,
        startup_timeout=90,
    )

    assert metadata["execution_runner_sha256"] == execute_canonical_v8.normalized_sha256(
        execute_canonical_v8.EXECUTION_RUNNER
    )
    assert metadata["public_client_sha256"] == execute_canonical_v8.normalized_sha256(
        execute_canonical_v8.PUBLIC_CLIENT
    )
