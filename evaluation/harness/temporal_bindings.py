"""Evaluation-only resolver for Canonical v8 fixed Run reference times."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from .fault_profiles import DEFAULT_DATASET_PATH

BOUND_STATUS = "BOUND_FIXED_RUN_REFERENCE_TIME"
NOT_REQUIRED_STATUS = "NOT_REQUIRED"


def resolve_reference_time(case: dict[str, Any]) -> datetime | None:
    """Return the frozen evaluation time without mutating Provider timestamps."""
    context = case.get("evaluation_context")
    if not isinstance(context, dict):
        return None
    value = context.get("run_reference_time")
    if not isinstance(value, str) or not value:
        return None
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{case.get('case_id')}: reference time must be timezone-aware")
    return parsed


def load_temporal_bindings(
    path: Path = DEFAULT_DATASET_PATH,
) -> dict[str, datetime]:
    result: dict[str, datetime] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        case = json.loads(line)
        value = resolve_reference_time(case)
        if value is not None:
            result[str(case["case_id"])] = value
    return result


def validate_canonical_temporal_bindings(
    path: Path = DEFAULT_DATASET_PATH,
) -> list[str]:
    failures: list[str] = []
    cases = [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    bound = 0
    for case in cases:
        case_id = str(case["case_id"])
        required = case["evaluation_gold"]["temporal_binding_required"]
        status = case["readiness"]["temporal_status"]
        try:
            reference_time = resolve_reference_time(case)
        except ValueError as error:
            failures.append(str(error))
            continue
        if required:
            bound += 1
            if status != BOUND_STATUS:
                failures.append(f"{case_id}: temporal status is not bound")
            if reference_time is None:
                failures.append(f"{case_id}: missing run_reference_time")
            context = case.get("evaluation_context", {})
            if context.get("time_zone") != "Asia/Seoul":
                failures.append(f"{case_id}: unexpected time zone")
            if context.get("provider_timestamps_mutated") is not False:
                failures.append(f"{case_id}: Provider timestamp boundary is unclear")
        elif status != NOT_REQUIRED_STATUS or reference_time is not None:
            failures.append(f"{case_id}: unnecessary temporal binding")
        if case["readiness"]["ready_for_evaluation"] != case["readiness"][
            "data_ready"
        ]:
            failures.append(f"{case_id}: ready_for_evaluation mismatch")
    if bound != 48:
        failures.append(f"Expected 48 temporal bindings, found {bound}")
    return failures


__all__ = [
    "BOUND_STATUS",
    "load_temporal_bindings",
    "resolve_reference_time",
    "validate_canonical_temporal_bindings",
]
