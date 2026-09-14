"""Project the current Run's durable reference time for semantic operations."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import TypedDict
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


class RunReferenceTimeV1(TypedDict):
    reference_time: str
    timezone: str


def project_run_reference_time(
    run_budget: Mapping[str, object], *, timezone_name: str = "Asia/Seoul"
) -> RunReferenceTimeV1 | None:
    """Return the checkpoint-stable Run start time, never the caller's current clock."""

    started_at_ms = run_budget.get("started_at_ms")
    if type(started_at_ms) is not int or started_at_ms < 0:
        return None
    try:
        zone = ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError as error:
        raise ValueError("invalid product timezone") from error
    reference = datetime.fromtimestamp(started_at_ms / 1000, tz=UTC).astimezone(zone)
    return {
        "reference_time": reference.isoformat(timespec="seconds"),
        "timezone": timezone_name,
    }


__all__ = ["RunReferenceTimeV1", "project_run_reference_time"]
