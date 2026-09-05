"""Candidate-only temporal matches against the already resolved query window."""

from __future__ import annotations

import re
from datetime import date, datetime, time, timedelta
from email.utils import parsedate_to_datetime
from typing import TypedDict
from zoneinfo import ZoneInfo

from google_work_agent.application.agents.retrieval.contracts.query_plan import (
    TemporalRangeConstraintV1,
)
from google_work_agent.application.agents.retrieval.normalize_segments import SourceSegment

_EVENT_DATE = re.compile(
    r"(?<!\d)(?:(?P<year>\d{4})\s*(?:년\s*|[-/.]))?"
    r"(?P<month>1[0-2]|0?[1-9])\s*(?:월\s*|[-/.])"
    r"(?P<day>3[01]|[12]\d|0?[1-9])(?:일)?(?!\d)"
)
_HEADER_PREFIXES = ("Message:", "From:", "To:", "Received:", "Sender name:", "Sender email:")


class EventDateCandidateV1(TypedDict):
    source_text: str
    candidate_date: str
    year_explicit: bool
    date_intersects_window: bool


def project_event_date_candidates(
    text: str, constraint: TemporalRangeConstraintV1,
) -> list[EventDateCandidateV1]:
    """Compare source date mentions, without deciding which mention is an event.

    A yearless date is only a candidate year drawn from the search target.
    A matching day does not prove that an event occurs, or lasts wholly, within it.
    """
    if constraint["axis"] != "EVENT_TIME":
        return []
    zone = ZoneInfo(constraint["timezone"])
    start_value, end_value = constraint["start_local"], constraint["end_local"]
    start = datetime.fromisoformat(start_value).replace(tzinfo=zone) if start_value else None
    end = datetime.fromisoformat(end_value).replace(tzinfo=zone) if end_value else None
    body = "\n".join(line for line in text.splitlines() if not line.startswith(_HEADER_PREFIXES))
    candidates: list[EventDateCandidateV1] = []
    seen: set[tuple[str, str]] = set()
    for match in _EVENT_DATE.finditer(body):
        year = match.group("year")
        years = [int(year)] if year else (
            range(start.year, min(start.year + 4, end.year) + 1)
            if start is not None and end is not None else ()
        )
        for candidate_year in years:
            try:
                candidate = date(candidate_year, int(match.group("month")), int(match.group("day")))
                day_start = datetime.combine(candidate, time.min, zone)
                day_end = day_start + timedelta(days=1)
            except (ValueError, OverflowError):
                continue
            key = (match.group(), candidate.isoformat())
            if key in seen:
                continue
            seen.add(key)
            candidates.append({
                "source_text": match.group(), "candidate_date": candidate.isoformat(),
                "year_explicit": year is not None,
                "date_intersects_window": (
                    (start is None or start < day_end) and (end is None or day_start < end)
                ),
            })
    return candidates


def match_temporal_evidence(
    segment: SourceSegment, constraint: TemporalRangeConstraintV1,
) -> bool:
    """Never reinterpret a receipt timestamp as an event mentioned in the body."""
    zone = ZoneInfo(constraint["timezone"])
    start_value, end_value = constraint["start_local"], constraint["end_local"]
    start = datetime.fromisoformat(start_value).replace(tzinfo=zone) if start_value else None
    end = datetime.fromisoformat(end_value).replace(tzinfo=zone) if end_value else None
    if constraint["axis"] == "MESSAGE_TIME":
        raw = segment.locator.get("received_at")
        if not isinstance(raw, str):
            return False
        try:
            received = datetime.fromisoformat(raw)
        except ValueError:
            try:
                received = parsedate_to_datetime(raw)
            except (ValueError, TypeError, OverflowError):
                return False
        # An offset-less provider value is not a known instant.
        return (
            received.tzinfo is not None
            and (start is None or start <= received) and (end is None or received < end)
        )

    return any(item["date_intersects_window"] for item in project_event_date_candidates(
        segment.text, constraint,
    ))
