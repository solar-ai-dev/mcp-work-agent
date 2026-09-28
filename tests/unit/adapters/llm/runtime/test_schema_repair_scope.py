from __future__ import annotations

from copy import deepcopy

import pytest

from google_work_agent.adapters.llm.runtime.schema_repair_scope import (
    find_out_of_scope_schema_repair_changes,
)
from google_work_agent.application.agents.request_understanding import (
    identify_source_dependencies,
)


def _source_schema() -> dict[str, object]:
    return dict(
        identify_source_dependencies.build_source_dependency_output_schema(
            [
                {
                    "resource_type": "TASK",
                    "read_tool_ids": ["task-list"],
                    "owned_fact_kinds": ["title"],
                },
                {
                    "resource_type": "CALENDAR_EVENT",
                    "read_tool_ids": ["event-list"],
                    "owned_fact_kinds": ["start"],
                },
                {
                    "resource_type": "GMAIL_DRAFT",
                    "read_tool_ids": ["draft-search"],
                    "owned_fact_kinds": ["body"],
                },
            ],
            work_unit_ids=("work-1",),
        ).json_schema
    )


def _required(resource_type: str, information: str) -> dict[str, object]:
    return {
        "resource_type": resource_type,
        "dependency": "SOURCE_REQUIRED",
        "required_information": [information],
        "target_scope": "CRITERIA",
        "work_unit_ids": ["work-1"],
    }


def test_array_shape_repair__may_fill_missing_identity__without_changing_siblings() -> None:
    failed = {
        "source_dependencies": [
            _required("TASK", "title"),
            _required("TASK", "title"),
            _required("GMAIL_DRAFT", "body"),
        ]
    }
    repaired = {
        "source_dependencies": [
            _required("CALENDAR_EVENT", "start"),
            _required("GMAIL_DRAFT", "body"),
            _required("TASK", "title"),
        ]
    }

    assert (
        find_out_of_scope_schema_repair_changes(
            failed_output=failed,
            repaired_output=repaired,
            affected_field_paths=["$.source_dependencies"],
            output_schema=_source_schema(),
        )
        == ()
    )


def test_array_shape_repair__unaffected_semantic_decision__is_rejected() -> None:
    failed = {
        "source_dependencies": [
            _required("TASK", "title"),
            _required("TASK", "title"),
            _required("GMAIL_DRAFT", "body"),
        ]
    }
    repaired = {
        "source_dependencies": [
            _required("TASK", "title"),
            _required("CALENDAR_EVENT", "start"),
            {
                "resource_type": "GMAIL_DRAFT",
                "dependency": "SOURCE_NOT_REQUIRED",
            },
        ]
    }

    assert find_out_of_scope_schema_repair_changes(
        failed_output=failed,
        repaired_output=repaired,
        affected_field_paths=["$.source_dependencies"],
        output_schema=_source_schema(),
    ) == (
        "$.source_dependencies[2].dependency",
        "$.source_dependencies[2].required_information",
        "$.source_dependencies[2].target_scope",
        "$.source_dependencies[2].work_unit_ids",
    )


def test_source_dependency_reorder__resource_type_identity__is_stable() -> None:
    failed = {
        "source_dependencies": [
            _required("TASK", "title"),
            {
                "resource_type": "CALENDAR_EVENT",
                "dependency": "SOURCE_REQUIRED",
                "required_information": "start",
                "target_scope": "CRITERIA",
                "work_unit_ids": ["work-1"],
            },
            _required("GMAIL_DRAFT", "body"),
        ]
    }
    repaired = {
        "source_dependencies": [
            _required("GMAIL_DRAFT", "body"),
            _required("CALENDAR_EVENT", "start"),
            _required("TASK", "title"),
        ]
    }

    assert (
        find_out_of_scope_schema_repair_changes(
            failed_output=failed,
            repaired_output=repaired,
            affected_field_paths=["$.source_dependencies[1].required_information"],
            output_schema=_source_schema(),
        )
        == ()
    )


def test_route_query_reorder__route_id_identity__is_stable() -> None:
    route_schema = {
        "type": "object",
        "required": ["route_queries"],
        "properties": {
            "route_queries": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": ["route_id", "operation", "reason_codes"],
                    "properties": {
                        "route_id": {"type": "string"},
                        "operation": {"type": "string"},
                        "reason_codes": {
                            "type": "array",
                            "items": {"type": "string"},
                        },
                    },
                },
            }
        },
    }
    failed = {
        "route_queries": [
            {"route_id": "route-a", "operation": "SEARCH", "reason_codes": "initial"},
            {"route_id": "route-b", "operation": "NEXT_PAGE", "reason_codes": ["page"]},
        ]
    }
    repaired = {
        "route_queries": [
            {"route_id": "route-b", "operation": "NEXT_PAGE", "reason_codes": ["page"]},
            {"route_id": "route-a", "operation": "SEARCH", "reason_codes": ["initial"]},
        ]
    }

    assert (
        find_out_of_scope_schema_repair_changes(
            failed_output=failed,
            repaired_output=repaired,
            affected_field_paths=["$.route_queries[0].reason_codes"],
            output_schema=route_schema,
        )
        == ()
    )


@pytest.mark.parametrize("chosen_dependency", ["SOURCE_REQUIRED", "SOURCE_NOT_REQUIRED"])
def test_conflicting_duplicate__repair_decides_only_ambiguous_group(
    chosen_dependency: str,
) -> None:
    failed = {
        "source_dependencies": [
            _required("TASK", "title"),
            {"resource_type": "TASK", "dependency": "SOURCE_NOT_REQUIRED"},
            _required("GMAIL_DRAFT", "body"),
        ]
    }
    task = (
        _required("TASK", "title")
        if chosen_dependency == "SOURCE_REQUIRED"
        else {"resource_type": "TASK", "dependency": "SOURCE_NOT_REQUIRED"}
    )
    repaired = {
        "source_dependencies": [
            _required("CALENDAR_EVENT", "start"),
            _required("GMAIL_DRAFT", "body"),
            task,
        ]
    }

    assert (
        find_out_of_scope_schema_repair_changes(
            failed_output=failed,
            repaired_output=repaired,
            affected_field_paths=["$.source_dependencies"],
            output_schema=_source_schema(),
        )
        == ()
    )


def test_conflicting_duplicate__unambiguous_sibling_cannot_be_dropped() -> None:
    failed = {
        "source_dependencies": [
            _required("TASK", "title"),
            {"resource_type": "TASK", "dependency": "SOURCE_NOT_REQUIRED"},
            _required("GMAIL_DRAFT", "body"),
            _required("CALENDAR_EVENT", "start"),
        ]
    }
    repaired = {
        "source_dependencies": [
            {"resource_type": name, "dependency": "SOURCE_NOT_REQUIRED"}
            for name in ("TASK", "CALENDAR_EVENT", "GMAIL_DRAFT")
        ]
    }

    assert find_out_of_scope_schema_repair_changes(
        failed_output=failed,
        repaired_output=repaired,
        affected_field_paths=["$.source_dependencies"],
        output_schema=_source_schema(),
    ) == tuple(
        f"$.source_dependencies[{index}].{field}"
        for index in (2, 3)
        for field in ("dependency", "required_information", "target_scope", "work_unit_ids")
    )


@pytest.mark.parametrize(
    ("field", "value"),
    [("required_information", ["subject"]), ("target_scope", "SINGULAR")],
)
def test_conflicting_duplicate__valid_sibling_values_remain_frozen(
    field: str, value: object
) -> None:
    failed = {
        "source_dependencies": [
            _required("TASK", "title"),
            {"resource_type": "TASK", "dependency": "SOURCE_NOT_REQUIRED"},
            _required("GMAIL_DRAFT", "body"),
        ]
    }
    repaired_draft = {**_required("GMAIL_DRAFT", "body"), field: value}
    repaired = {
        "source_dependencies": [
            repaired_draft,
            _required("CALENDAR_EVENT", "start"),
            _required("TASK", "title"),
        ]
    }

    changes = find_out_of_scope_schema_repair_changes(
        failed_output=failed,
        repaired_output=repaired,
        affected_field_paths=["$.source_dependencies"],
        output_schema=_source_schema(),
    )
    assert changes
    assert all(path.startswith(f"$.source_dependencies[2].{field}") for path in changes)


def test_conflicting_duplicate__does_not_expand_narrow_reported_scope() -> None:
    failed = {
        "source_dependencies": [
            _required("TASK", "title"),
            {"resource_type": "TASK", "dependency": "SOURCE_NOT_REQUIRED"},
            _required("GMAIL_DRAFT", "body"),
        ]
    }
    repaired = {
        "source_dependencies": [
            _required("TASK", "title"),
            _required("GMAIL_DRAFT", "body"),
            _required("CALENDAR_EVENT", "start"),
        ]
    }

    assert find_out_of_scope_schema_repair_changes(
        failed_output=failed,
        repaired_output=repaired,
        affected_field_paths=["$.source_dependencies[2].required_information"],
        output_schema=_source_schema(),
    ) == ("$.source_dependencies", "$.source_dependencies[0]")


def test_conflicting_route_duplicate__cannot_rewrite_other_route_operation() -> None:
    schema = {
        "type": "object",
        "properties": {
            "route_queries": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": ["route_id", "operation"],
                    "properties": {
                        "route_id": {"type": "string"},
                        "operation": {"type": "string"},
                    },
                },
            }
        },
    }
    failed = {
        "route_queries": [
            {"route_id": "route-a", "operation": "SEARCH"},
            {"route_id": "route-a", "operation": "NEXT_PAGE"},
            {"route_id": "route-b", "operation": "DETAIL_FETCH"},
        ]
    }
    repaired = {
        "route_queries": [
            {"route_id": "route-b", "operation": "DETAIL_FETCH"},
            {"route_id": "route-a", "operation": "SEARCH"},
        ]
    }
    assert (
        find_out_of_scope_schema_repair_changes(
            failed_output=failed,
            repaired_output=repaired,
            affected_field_paths=["$.route_queries"],
            output_schema=schema,
        )
        == ()
    )

    changed = deepcopy(repaired)
    changed["route_queries"][0]["operation"] = "SEARCH"
    assert find_out_of_scope_schema_repair_changes(
        failed_output=failed,
        repaired_output=changed,
        affected_field_paths=["$.route_queries"],
        output_schema=schema,
    ) == ("$.route_queries[2].operation",)


@pytest.mark.parametrize(
    "unidentified",
    [
        None,
        "invalid-item",
        {},
        {"resource_type": None},
        {"resource_type": []},
        {"resource_type": True},
    ],
)
def test_unidentifiable_item__does_not_remove_known_peer_authority(
    unidentified: object,
) -> None:
    failed = {"source_dependencies": [_required("TASK", "title"), unidentified]}
    repaired = {
        "source_dependencies": [
            _required("CALENDAR_EVENT", "start"),
            _required("GMAIL_DRAFT", "body"),
            _required("TASK", "title"),
        ]
    }
    assert find_out_of_scope_schema_repair_changes(
        failed_output=failed,
        repaired_output=repaired,
        affected_field_paths=["$.source_dependencies"],
        output_schema=_source_schema(),
    ) == ()

    changed = deepcopy(repaired)
    changed["source_dependencies"][2] = {
        "resource_type": "TASK",
        "dependency": "SOURCE_NOT_REQUIRED",
    }
    assert find_out_of_scope_schema_repair_changes(
        failed_output=failed,
        repaired_output=changed,
        affected_field_paths=["$.source_dependencies"],
        output_schema=_source_schema(),
    ) == tuple(
        f"$.source_dependencies[0].{field}"
        for field in ("dependency", "required_information", "target_scope", "work_unit_ids")
    )


def test_unidentifiable_route__retains_prior_positional_scope_restrictions() -> None:
    schema = {
        "type": "object",
        "properties": {
            "route_queries": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": ["route_id", "operation"],
                    "properties": {
                        "route_id": {"type": "string"},
                        "operation": {"type": "string"},
                    },
                },
            }
        },
    }
    failed = {
        "route_queries": [
            {"route_id": None, "operation": "SEARCH"},
            {"route_id": "route-b", "operation": "DETAIL_FETCH"},
        ]
    }
    repaired = {
        "route_queries": [
            {"route_id": "route-a", "operation": "SEARCH"},
            {"route_id": "route-b", "operation": "DETAIL_FETCH"},
        ]
    }
    assert find_out_of_scope_schema_repair_changes(
        failed_output=failed,
        repaired_output=repaired,
        affected_field_paths=["$.route_queries[0].route_id"],
        output_schema=schema,
    ) == ()

    changed = deepcopy(repaired)
    changed["route_queries"][0]["operation"] = "NEXT_PAGE"
    assert find_out_of_scope_schema_repair_changes(
        failed_output=failed,
        repaired_output=changed,
        affected_field_paths=["$.route_queries[0].route_id"],
        output_schema=schema,
    ) == ("$.route_queries[0].operation",)

    assert find_out_of_scope_schema_repair_changes(
        failed_output=failed,
        repaired_output={"route_queries": repaired["route_queries"][:1]},
        affected_field_paths=["$.route_queries"],
        output_schema=schema,
    ) == ("$.route_queries[1]",)


def test_identified_array__still_rejects_unrequired_new_identity() -> None:
    failed = {"source_dependencies": [_required("TASK", "title")]}
    repaired = {
        "source_dependencies": [
            _required("TASK", "title"),
            _required("GITHUB_ISSUE", "body"),
        ]
    }
    assert find_out_of_scope_schema_repair_changes(
        failed_output=failed,
        repaired_output=repaired,
        affected_field_paths=["$.source_dependencies"],
        output_schema=_source_schema(),
    ) == ("$.source_dependencies",)
