from __future__ import annotations

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
