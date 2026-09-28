"""Existing temporal derivation must consume only its confirmed work scope."""

from datetime import datetime
from typing import Any, cast
from zoneinfo import ZoneInfo

import pytest

from google_work_agent.application.agents.retrieval.resolve_calendar_query_periods import (
    resolve_calendar_query_periods,
)
from google_work_agent.application.agents.retrieval.resolve_gmail_query_periods import (
    resolve_gmail_query_periods,
)

NOW = int(datetime(2026, 9, 11, tzinfo=ZoneInfo("Asia/Seoul")).timestamp() * 1000)


def _constraint(kind: str, field: str, value: str, *units: str) -> dict[str, Any]:
    return {"kind": kind, "field": field, "value": value, "work_unit_ids": list(units)}


def _route(resource: str, *units: str) -> Any:
    return {
        "route_id": resource,
        "connector_id": "google_workspace",
        "resource_type": resource,
        "allowed_read_tool_ids": ["gmail_search_threads"] if resource == "GMAIL_THREAD" else [],
        "work_unit_ids": list(units),
        "required": True,
        "reason_codes": ["REQUESTED_INPUT"],
    }


def test_mail_and_calendar_use_their_own_work_periods() -> None:
    prompt = {"request_intent": {"schema_version": 3, "constraints": [
        _constraint("DATE", "period", "지난주", "work-1"),
        _constraint("TIME", "temporal_axis", "MESSAGE_TIME", "work-1"),
        _constraint("DATE", "period", "내일", "work-2"),
        _constraint("TIME", "temporal_axis", "EVENT_TIME", "work-2"),
    ]}}
    routes = [_route("GMAIL_THREAD", "work-1"), _route("CALENDAR_EVENT", "work-2")]
    mail = resolve_gmail_query_periods(
        prompt_input=prompt, frozen_routes=routes, now_ms=NOW, timezone="Asia/Seoul"
    )
    calendar = resolve_calendar_query_periods(
        prompt_input=prompt, frozen_routes=routes, now_ms=NOW, timezone="Asia/Seoul"
    )
    assert mail["GMAIL_THREAD"]["start_local"] == "2026-08-31T00:00:00"
    assert mail["GMAIL_THREAD"]["end_local"] == "2026-09-07T00:00:00"
    assert calendar["CALENDAR_EVENT"]["start_local"] == "2026-09-12T00:00:00"
    assert calendar["CALENDAR_EVENT"]["axis"] == "EVENT_TIME"


@pytest.mark.parametrize("resource,resolver,axis", [
    ("GMAIL_THREAD", resolve_gmail_query_periods, "MESSAGE_TIME"),
    ("CALENDAR_EVENT", resolve_calendar_query_periods, "EVENT_TIME"),
])
def test_other_work_period_is_not_a_route_filter(resource: str, resolver: Any, axis: str) -> None:
    prompt = {"request_intent": {"schema_version": 3, "constraints": [
        _constraint("DATE", "period", "내일", "work-2"),
        _constraint("TIME", "temporal_axis", axis, "work-2"),
    ]}}
    assert resolver(
        prompt_input=prompt, frozen_routes=[_route(resource, "work-1")],
        now_ms=NOW, timezone="Asia/Seoul"
    ) == {}


@pytest.mark.parametrize("resource,resolver,axis", [
    ("GMAIL_THREAD", resolve_gmail_query_periods, "MESSAGE_TIME"),
    ("CALENDAR_EVENT", resolve_calendar_query_periods, "EVENT_TIME"),
])
def test_shared_read_does_not_arbitrarily_choose_one_work_period(
    resource: str, resolver: Any, axis: str
) -> None:
    prompt = {"request_intent": {"schema_version": 3, "constraints": [
        _constraint("DATE", "period", "어제", "work-1"),
        _constraint("DATE", "period", "내일", "work-2"),
        _constraint("TIME", "temporal_axis", axis, "work-1", "work-2"),
    ]}}
    assert resolver(
        prompt_input=prompt, frozen_routes=[_route(resource, "work-1", "work-2")],
        now_ms=NOW, timezone="Asia/Seoul"
    ) == {}


@pytest.mark.parametrize("resource,resolver,axis", [
    ("GMAIL_THREAD", resolve_gmail_query_periods, "MESSAGE_TIME"),
    ("CALENDAR_EVENT", resolve_calendar_query_periods, "EVENT_TIME"),
])
def test_shared_read_does_not_apply_one_works_period_to_unconstrained_work(
    resource: str, resolver: Any, axis: str
) -> None:
    prompt = {"request_intent": {"schema_version": 3, "constraints": [
        _constraint("DATE", "period", "내일", "work-create"),
        _constraint("TIME", "temporal_axis", axis, "work-create"),
    ]}}
    assert resolver(
        prompt_input=prompt, frozen_routes=[_route(resource, "work-read", "work-create")],
        now_ms=NOW, timezone="Asia/Seoul"
    ) == {}


@pytest.mark.parametrize("resource,resolver,axis", [
    ("GMAIL_THREAD", resolve_gmail_query_periods, "MESSAGE_TIME"),
    ("CALENDAR_EVENT", resolve_calendar_query_periods, "EVENT_TIME"),
])
def test_same_period_for_shared_read_is_resolved_once(
    resource: str, resolver: Any, axis: str
) -> None:
    prompt = {"request_intent": {"schema_version": 3, "constraints": [
        _constraint("DATE", "period", "내일", "work-1", "work-2"),
        _constraint("TIME", "temporal_axis", axis, "work-1", "work-2"),
    ]}}
    resolved = resolver(
        prompt_input=prompt, frozen_routes=[_route(resource, "work-1", "work-2")],
        now_ms=NOW, timezone="Asia/Seoul"
    )
    assert list(resolved) == [resource]
    assert resolved[resource]["start_local"] == "2026-09-12T00:00:00"


@pytest.mark.parametrize("resource,resolver,axis", [
    ("GMAIL_THREAD", resolve_gmail_query_periods, "MESSAGE_TIME"),
    ("CALENDAR_EVENT", resolve_calendar_query_periods, "EVENT_TIME"),
])
def test_full_v3_missing_item_binding_is_not_global(
    resource: str, resolver: Any, axis: str
) -> None:
    constraints = [
        {"kind": "DATE", "field": "period", "value": "내일"},
        {"kind": "TIME", "field": "temporal_axis", "value": axis},
    ]
    assert resolver(
        prompt_input=cast(Any, {
            "request_intent": {"schema_version": 3, "constraints": constraints}
        }),
        frozen_routes=[_route(resource, "work-1")], now_ms=NOW, timezone="Asia/Seoul"
    ) == {}
