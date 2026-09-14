"""Resolve user relative periods into provider-neutral retrieval bounds."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from datetime import datetime, timedelta
from typing import Literal, TypedDict
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


class ResolvedTemporalRange(TypedDict):
    kind: Literal["TEMPORAL_RANGE"]
    axis: Literal["MESSAGE_TIME", "EVENT_TIME"]
    start_local: str
    end_local: str
    timezone: str


def resolve_relative_period(
    constraints: object,
    *,
    now_ms: int,
    timezone: str,
) -> ResolvedTemporalRange | None:
    """Resolve one supported relative period from current user-local time."""

    periods = _relative_periods(constraints)
    if len(periods) != 1:
        return None
    axes = (
        {
            value
            for item in constraints
            if isinstance(item, Mapping)
            if item.get("kind") == "TIME" and item.get("field") == "temporal_axis"
            for value in (
                item["value"] if isinstance(item.get("value"), list) else [item.get("value")]
            )
            if isinstance(value, str)
        }
        if isinstance(constraints, list)
        else set()
    )
    if axes == {"MESSAGE_TIME"}:
        axis: Literal["MESSAGE_TIME", "EVENT_TIME"] = "MESSAGE_TIME"
    elif axes == {"EVENT_TIME"}:
        axis = "EVENT_TIME"
    else:
        # An older intent without an axis is not evidence of message-time meaning.
        return None
    try:
        local_now = datetime.fromtimestamp(now_ms / 1_000, tz=ZoneInfo(timezone))
    except (OSError, OverflowError, ValueError, ZoneInfoNotFoundError):
        return None

    today = local_now.replace(hour=0, minute=0, second=0, microsecond=0)
    period = periods[0]
    if period == "오늘":
        start, end = today, today + timedelta(days=1)
    elif period == "어제":
        start, end = today - timedelta(days=1), today
    elif period == "그제":
        start, end = today - timedelta(days=2), today - timedelta(days=1)
    elif period in {"지난주", "이번주", "다음주"}:
        this_week = today - timedelta(days=today.weekday())
        offset = {"지난주": -7, "이번주": 0, "다음주": 7}[period]
        start = this_week + timedelta(days=offset)
        end = start + timedelta(days=7)
    elif period in {"지난달", "이번달"}:
        this_month = today.replace(day=1)
        if period == "지난달":
            end = this_month
            start = (this_month - timedelta(days=1)).replace(day=1)
        else:
            start = this_month
            end = (this_month.replace(day=28) + timedelta(days=4)).replace(day=1)
    elif period == "최근":
        start, end = today - timedelta(days=30), today + timedelta(days=1)
    else:
        month = re.fullmatch(r"(?:(\d{4})년)?(1[0-2]|[1-9])월(첫째주)?", period)
        if month is None:
            return None
        year = int(month[1]) if month[1] else today.year
        if not month[1]:
            month_number = int(month[2])
            if axis == "MESSAGE_TIME":
                # Future receipt windows are not the implicit target of a past-mail read.
                year -= int(month_number > today.month)
            else:
                # Discovery hypothesis only: this does not establish a source event's year.
                windows = [
                    today.replace(year=candidate_year, month=month_number, day=1)
                    for candidate_year in (today.year - 1, today.year, today.year + 1)
                    if 1 <= candidate_year <= 9999
                ]
                def distance(start: datetime) -> tuple[int, int]:
                    end = (
                        start + timedelta(days=7) if month[3]
                        else (start.replace(day=28) + timedelta(days=4)).replace(day=1)
                    )
                    days = 0 if start <= today < end else min(
                        abs((start - today).days), abs((end - timedelta(days=1) - today).days),
                    )
                    return days, start.year
                year = min(windows, key=distance).year
        try:
            start = today.replace(year=year, month=int(month[2]), day=1)
            end = (
                start + timedelta(days=7)
                if month[3]
                else (start.replace(day=28) + timedelta(days=4)).replace(day=1)
            )
        except ValueError:
            return None

    return {
        "kind": "TEMPORAL_RANGE",
        "axis": axis,
        "start_local": start.replace(tzinfo=None).isoformat(),
        "end_local": end.replace(tzinfo=None).isoformat(),
        "timezone": timezone,
    }


def _relative_periods(constraints: object) -> list[str]:
    if not isinstance(constraints, Sequence) or isinstance(constraints, (str, bytes)):
        return []
    result: list[str] = []
    for item in constraints:
        if not isinstance(item, Mapping):
            continue
        if item.get("kind") != "DATE" or item.get("field") != "period":
            continue
        raw = item.get("value")
        values = raw if isinstance(raw, list) else [raw]
        result.extend(
            str(value).replace(" ", "")
            for value in values
            if isinstance(value, str) and value.strip()
        )
    return list(dict.fromkeys(result))


__all__ = ["ResolvedTemporalRange", "resolve_relative_period"]
