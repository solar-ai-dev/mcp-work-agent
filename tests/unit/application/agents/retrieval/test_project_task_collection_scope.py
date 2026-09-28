"""Task collection scope follows typed business consumers, not prose or policy labels."""

from copy import deepcopy
from typing import Any, cast

import pytest

from google_work_agent.application.agents.retrieval.project_task_collection_scope import (
    project_task_collection_scope,
)
from google_work_agent.application.agents.tool_routing.contracts.tool_route_plan import (
    InputToolRouteV1,
)


def _route(*units: str) -> InputToolRouteV1:
    return {
        "route_id": "task-read",
        "resource_type": "TASK",
        "connector_id": "google_workspace",
        "allowed_read_tool_ids": ["tasks_list_tasks"],
        "required": True,
        "reason_codes": ["POLICY_TASK_DUPLICATE_CHECK"],
        "work_unit_ids": list(units),
    }


def _source(*units: str, resource: str = "TASK") -> dict[str, Any]:
    return {
        "resource_type": resource,
        "required_information": ["title", "completion_status"],
        "target_scope": "CRITERIA",
        "work_unit_ids": list(units),
    }


def _status(value: str, *units: str, resource: str = "TASK") -> dict[str, Any]:
    return {
        "kind": "SCOPE",
        "field": "status",
        "value": value,
        "source_resource_type": resource,
        "work_unit_ids": list(units),
        "provenance": {
            "source": "USER_REQUEST",
            "start_offset": 0,
            "end_offset": len(value),
            "source_text": value,
        },
    }


def _intent(
    sources: list[dict[str, Any]], constraints: list[dict[str, Any]] | None = None
) -> dict[str, Any]:
    return {
        "schema_version": 3,
        "resource_responsibilities": {"source_reads": sources, "outputs": []},
        "constraints": constraints or [],
    }


@pytest.mark.parametrize("resource", [None, "TASK_LIST", "GMAIL_THREAD"])
def test_project_task_collection_scope__no_task_source__keeps_policy_scope(
    resource: str | None,
) -> None:
    sources = [] if resource is None else [_source("work-1", resource=resource)]
    intent = _intent(sources, [_status("COMPLETED", "work-1")])
    assert project_task_collection_scope(intent, _route("work-1")) == "INCOMPLETE"


def test_project_task_collection_scope__other_work_source__keeps_policy_scope() -> None:
    intent = _intent([_source("work-business")])
    assert project_task_collection_scope(intent, _route("work-policy")) == "INCOMPLETE"


def test_project_task_collection_scope__unfiltered_source_prose__does_not_narrow() -> None:
    source = _source("work-1")
    source["required_information"] = ["진행 중인 작업의 제목과 상태"]
    intent = _intent([source])
    assert project_task_collection_scope(intent, _route("work-1")) == "ANY"


@pytest.mark.parametrize(
    ("value", "expected"),
    [("INCOMPLETE", "INCOMPLETE"), ("COMPLETED", "ANY"), ("ANY", "ANY")],
)
def test_project_task_collection_scope__typed_task_status__preserves_collection_scope(
    value: str, expected: str
) -> None:
    intent = _intent([_source("work-1")], [_status(value, "work-1")])
    route = _route("work-1")
    original = deepcopy((intent, route))
    assert project_task_collection_scope(intent, route) == expected
    assert (intent, route) == original


@pytest.mark.parametrize(
    ("second_status", "expected"),
    [(None, "ANY"), ("COMPLETED", "ANY"), ("ANY", "ANY"), ("INCOMPLETE", "INCOMPLETE")],
)
def test_project_task_collection_scope__shared_business_read__preserves_each_work_scope(
    second_status: str | None, expected: str
) -> None:
    constraints = [_status("INCOMPLETE", "work-1")]
    if second_status is not None:
        constraints.append(_status(second_status, "work-2"))
    intent = _intent([_source("work-1"), _source("work-2")], constraints)
    assert project_task_collection_scope(intent, _route("work-1", "work-2")) == expected


def test_project_task_collection_scope__one_shared_status__binds_all_consumers() -> None:
    intent = _intent([_source("work-1", "work-2")], [_status("INCOMPLETE", "work-1", "work-2")])
    assert project_task_collection_scope(intent, _route("work-1", "work-2")) == "INCOMPLETE"


@pytest.mark.parametrize("other_value", ["COMPLETED", "ANY"])
def test_project_task_collection_scope__mixed_statuses__keeps_completed_observations(
    other_value: str,
) -> None:
    intent = _intent(
        [_source("work-1")],
        [_status("INCOMPLETE", "work-1"), _status(other_value, "work-1")],
    )
    assert project_task_collection_scope(intent, _route("work-1")) == "ANY"


@pytest.mark.parametrize("reasons", [[], ["REQUESTED_INPUT"], ["POLICY_TASK_DUPLICATE_CHECK"]])
def test_project_task_collection_scope__shared_policy_route__uses_business_work(
    reasons: list[str],
) -> None:
    route = _route("work-source", "work-policy")
    route["reason_codes"] = reasons
    intent = _intent([_source("work-source")], [_status("INCOMPLETE", "work-policy")])
    assert project_task_collection_scope(intent, route) == "ANY"
    intent["constraints"] = [
        _status("INCOMPLETE", "work-source"),
        _status("ANY", "work-policy"),
    ]
    assert project_task_collection_scope(intent, route) == "INCOMPLETE"


def test_project_task_collection_scope__other_work_status__is_ignored() -> None:
    intent = _intent([_source("work-1")], [_status("INCOMPLETE", "work-2")])
    assert project_task_collection_scope(intent, _route("work-1")) == "ANY"
    intent["constraints"] = [_status("INCOMPLETE", "work-1"), _status("COMPLETED", "work-2")]
    assert project_task_collection_scope(intent, _route("work-1")) == "INCOMPLETE"


@pytest.mark.parametrize(
    "different_field",
    [{"kind": "TARGET"}, {"field": "title"}, {"source_resource_type": "TASK_LIST"}],
)
def test_project_task_collection_scope__other_constraint_fields__are_ignored(
    different_field: dict[str, str],
) -> None:
    status = {**_status("INCOMPLETE", "work-1"), **different_field}
    intent = _intent([_source("work-1")], [status])
    assert project_task_collection_scope(intent, _route("work-1")) == "ANY"


@pytest.mark.parametrize("binding", [None, []])
def test_project_task_collection_scope__v3_unbound_status__is_not_global(
    binding: list[str] | None,
) -> None:
    status = _status("INCOMPLETE", "work-1")
    if binding is None:
        status.pop("work_unit_ids")
    else:
        status["work_unit_ids"] = binding
    intent = _intent([_source("work-1")], [status])
    assert project_task_collection_scope(intent, _route("work-1")) == "ANY"


@pytest.mark.parametrize("value", [None, "INCOMPLETE", "COMPLETED", "ANY"])
def test_project_task_collection_scope__unbound_legacy__preserves_scope_without_new_ids(
    value: str | None,
) -> None:
    source = _source()
    source.pop("work_unit_ids")
    constraints = [] if value is None else [_status(value)]
    for constraint in constraints:
        constraint.pop("work_unit_ids")
    intent = _intent([source], constraints)
    intent["schema_version"] = 2
    route = _route()
    cast(dict[str, Any], route).pop("work_unit_ids")
    original = deepcopy((intent, route))
    assert project_task_collection_scope(intent, route) == (
        "INCOMPLETE" if value == "INCOMPLETE" else "ANY"
    )
    assert (intent, route) == original
