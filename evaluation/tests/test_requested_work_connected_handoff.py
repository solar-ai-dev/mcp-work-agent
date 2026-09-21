from __future__ import annotations

from copy import deepcopy

import pytest
from evaluation.requested_work_connected_handoff import (
    default_connected_scenarios,
    default_tool_bindings,
    project_connected_handoff,
    validate_connected_handoff,
)


def _scenario(scenario_id: str) -> dict[str, object]:
    return next(
        deepcopy(item)
        for item in default_connected_scenarios()
        if item["scenario_id"] == scenario_id
    )


@pytest.mark.parametrize("scenario", default_connected_scenarios())
def test_connected_handoff_closes_all_item_owned_bindings(
    scenario: dict[str, object],
) -> None:
    result = project_connected_handoff(scenario, tool_bindings=default_tool_bindings())

    assert validate_connected_handoff(scenario, result) == []
    expected = scenario["expected"]
    assert isinstance(expected, dict)
    assert all(result["metrics"][name] == value for name, value in expected.items())
    assert result["metrics"]["provider_write_count"] == 0
    assert result["metrics"]["llm_call_count"] == 0


def test_shared_read_keeps_two_work_bindings_without_duplicate_provider_read() -> None:
    scenario = _scenario("SHARED_READ_TWO_WORK_UNITS")

    result = project_connected_handoff(scenario, tool_bindings=default_tool_bindings())

    assert result["metrics"]["provider_read_count"] == 1
    assert result["input_routes"][0]["work_unit_ids"] == ["work-1", "work-2"]
    assert (
        result["retrieval_requirements"][0]["source_responsibilities"]
        == scenario["source_responsibilities"]
    )
    assert result["retrieval_coverage"][0]["work_unit_ids"] == ["work-1", "work-2"]
    assert result["planned_specifications"][0]["evidence_refs"] == ["evidence:input-1"]


def test_multi_work_answer_keeps_one_planning_input_with_per_work_evidence() -> None:
    scenario = _scenario("SHARED_READ_MULTI_WORK_ANSWER")

    result = project_connected_handoff(scenario, tool_bindings=default_tool_bindings())

    assert result["metrics"]["provider_read_count"] == 1
    assert result["metrics"]["answer_planning_input_count"] == 1
    assert result["answer_planning_inputs"] == [
        {
            "work_unit_ids": ["work-1", "work-2"],
            "evidence_by_work_unit": [
                {"work_unit_id": "work-1", "evidence_refs": ["evidence:input-1"]},
                {"work_unit_id": "work-2", "evidence_refs": ["evidence:input-1"]},
            ],
        }
    ]


def test_distinct_results_share_capability_selection_but_not_output_route() -> None:
    scenario = _scenario("DISTINCT_RESULTS_SAME_WRITE_CAPABILITY")

    result = project_connected_handoff(scenario, tool_bindings=default_tool_bindings())

    assert result["metrics"]["output_capability_selection_count"] == 1
    assert result["metrics"]["output_route_count"] == 2
    assert result["metrics"]["planning_specification_count"] == 2
    assert [route["work_unit_ids"] for route in result["output_routes"]] == [
        ["work-1"],
        ["work-2"],
    ]
    assert len({route["selected_tool_id"] for route in result["output_routes"]}) == 1


def test_simple_request_does_not_gain_extra_routes_or_calls() -> None:
    scenario = _scenario("SIMPLE_READ")

    result = project_connected_handoff(scenario, tool_bindings=default_tool_bindings())

    assert result["metrics"] == {
        "input_route_count": 1,
        "query_plan_count": 1,
        "provider_read_count": 1,
        "output_capability_selection_count": 0,
        "output_route_count": 0,
        "answer_planning_input_count": 1,
        "planning_specification_count": 0,
        "provider_write_count": 0,
        "llm_call_count": 0,
    }


def test_unknown_work_unit_reference_is_rejected_before_route_projection() -> None:
    scenario = _scenario("SIMPLE_READ")
    scenario["source_responsibilities"][0]["work_unit_ids"] = ["unknown"]

    with pytest.raises(ValueError, match="contains unknown IDs"):
        project_connected_handoff(scenario, tool_bindings=default_tool_bindings())


def test_validator_detects_binding_loss_at_retrieval_handoff() -> None:
    scenario = _scenario("SHARED_READ_TWO_WORK_UNITS")
    result = project_connected_handoff(scenario, tool_bindings=default_tool_bindings())
    result["retrieval_coverage"][0]["work_unit_ids"] = ["work-1"]

    assert validate_connected_handoff(scenario, result) == [
        "retrieval coverage lost binding for input-1"
    ]


def test_validator_detects_planning_output_merge() -> None:
    scenario = _scenario("DISTINCT_RESULTS_SAME_WRITE_CAPABILITY")
    result = project_connected_handoff(scenario, tool_bindings=default_tool_bindings())
    result["output_routes"] = result["output_routes"][:1]

    assert "output routes merged or reordered distinct owner items" in validate_connected_handoff(
        scenario, result
    )


def test_exact_duplicate_owner_item_is_rejected_but_same_capability_is_not() -> None:
    scenario = _scenario("DISTINCT_RESULTS_SAME_WRITE_CAPABILITY")
    scenario["output_responsibilities"].append(deepcopy(scenario["output_responsibilities"][0]))

    with pytest.raises(ValueError, match="duplicates an owner item"):
        project_connected_handoff(scenario, tool_bindings=default_tool_bindings())
