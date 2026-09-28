"""Existing Source scope representation; no natural-language interpretation."""

from __future__ import annotations

from copy import deepcopy
from typing import Any, cast

import pytest
from evaluation.request_semantic_authority_candidate import _goal_output_modality_schema
from scripts.ru_source_scope_candidate import SOURCE_CATEGORIES, source_scope_candidate

from google_work_agent.application.agents.request_understanding.contracts import (
    request_goal_candidate_schema as goal_schema,
)
from google_work_agent.application.agents.tool_routing.resolve_policy_preconditions import (
    _explicit_source_scope,
)
from google_work_agent.ports.llm.output_schema_validation import validate_output_schema


def _raw(*additional: dict[str, Any]) -> dict[str, Any]:
    constraints: dict[str, Any] = {
        field: []
        for field in (
            "search_terms",
            "business_concepts",
            "person",
            "sender",
            "recipient",
            "subject",
            "period",
        )
    }
    constraints["coverage_requirement"] = {
        "value": "NOT_COLLECTION",
        "work_unit_ids": ["work-1", "work-2"],
    }
    constraints["additional_constraints"] = list(additional)
    return {
        "goal": "두 업무의 자료를 각각 확인한다.",
        "completion_conditions": ["각각 근거로 답한다."],
        "constraints": constraints,
        "analysis_requirement": "NONE",
    }


def _constraint(field: str, value: Any, work_id: str = "work-1") -> dict[str, Any]:
    return {"field": field, "value": value, "work_unit_ids": [work_id]}


@pytest.mark.parametrize("field", ["required_sources", "forbidden_sources"])
@pytest.mark.parametrize("value", [*SOURCE_CATEGORIES, list(SOURCE_CATEGORIES)])
def test_existing_source_categories_are_available_only_inside_context(
    field: str, value: Any
) -> None:
    baseline = goal_schema.identify_goal_output_schema(("work-1", "work-2"))
    value = _raw(_constraint(field, value))
    assert validate_output_schema(value, baseline.json_schema)
    with source_scope_candidate():
        schema = goal_schema.identify_goal_output_schema(("work-1", "work-2"))
        assert not validate_output_schema(value, schema.json_schema)
        assert not validate_output_schema(
            value, goal_schema.IDENTIFY_GOAL_OUTPUT_SCHEMA.json_schema
        )
    assert goal_schema.identify_goal_output_schema(("work-1", "work-2")) == baseline
    assert field not in goal_schema._ADDITIONAL_CONSTRAINT_FIELD_KINDS


@pytest.mark.parametrize("value", ["GITHUB", "GMAIL_THREAD", "unknown", [], ["EMAIL", "unknown"]])
def test_scope_values_are_closed_without_changing_other_constraint_values(value: Any) -> None:
    with source_scope_candidate():
        schema = goal_schema.identify_goal_output_schema(("work-1", "work-2"))
        assert validate_output_schema(
            _raw(_constraint("required_sources", value)), schema.json_schema
        )
        assert not validate_output_schema(
            _raw(_constraint("title", "any requested title")), schema.json_schema
        )


def test_goal_output_v4_and_repair_share_the_extended_schema() -> None:
    with source_scope_candidate():
        schema = _goal_output_modality_schema(
            work_unit_ids=("work-1", "work-2"),
            output_candidates=({"resource_type": "TASK", "allowed_output_effects": ["CREATE"]},),
        )
        value = {
            **_raw(_constraint("forbidden_sources", ["EMAIL"])),
            "requested_outputs": [],
            "requested_result_mode": "ANSWER_ONLY",
        }
        assert not validate_output_schema(value, schema.json_schema)
        invalid = deepcopy(value)
        invalid["constraints"]["additional_constraints"][0]["value"] = "GMAIL_THREAD"
        assert validate_output_schema(invalid, schema.json_schema)
        assert not validate_output_schema(value, schema.json_schema)


def test_normalizer_preserves_kind_value_and_work_binding_for_existing_consumer() -> None:
    additional = [
        _constraint("required_sources", "TASK"),
        _constraint("forbidden_sources", ["EMAIL"]),
        _constraint("required_sources", ["EMAIL"], "work-2"),
    ]
    with source_scope_candidate():
        candidate = goal_schema.validate_request_goal_candidate(
            _raw(*additional),
            resource_responsibilities={
                "source_reads": [
                    {
                        "resource_type": resource,
                        "required_information": ["status"],
                        "target_scope": "CRITERIA",
                        "work_unit_ids": [unit],
                    }
                    for resource, unit in (("TASK", "work-1"), ("GMAIL_THREAD", "work-2"))
                ],
                "outputs": [],
            },
            effect_prohibitions={"effect_prohibitions": []},
            requested_work={"work_units": [], "work_relations": []},
            work_unit_ids=("work-1", "work-2"),
            schema=goal_schema.identify_goal_output_schema(("work-1", "work-2")),
        )
    scoped = [item for item in candidate["constraints"] if item["kind"] == "SCOPE"]
    assert scoped == [{"kind": "SCOPE", **item} for item in additional]
    assert _explicit_source_scope(cast(Any, candidate), work_unit_id="work-1") == (
        frozenset({"TASK"}),
        frozenset({"EMAIL"}),
    )
    assert _explicit_source_scope(cast(Any, candidate), work_unit_id="work-2") == (
        frozenset({"EMAIL"}),
        frozenset(),
    )


def test_context_restores_shared_schema_and_mapping_after_exception() -> None:
    schema_before = deepcopy(goal_schema.IDENTIFY_GOAL_OUTPUT_SCHEMA.json_schema)
    fields_before = deepcopy(goal_schema._ADDITIONAL_CONSTRAINT_FIELD_KINDS)
    with pytest.raises(RuntimeError), source_scope_candidate():
        raise RuntimeError("bounded test failure")
    assert goal_schema.IDENTIFY_GOAL_OUTPUT_SCHEMA.json_schema == schema_before
    assert fields_before == goal_schema._ADDITIONAL_CONSTRAINT_FIELD_KINDS
