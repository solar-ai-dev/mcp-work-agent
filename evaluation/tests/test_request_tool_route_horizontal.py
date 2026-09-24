import pytest
from evaluation.request_semantic_authority_candidate import (
    _atomic_semantic_schema,
    _goal_output_modality_schema,
    _goal_output_semantic_schema,
    _goal_result_mode_schema,
    _materialize_requested_work,
    _request_tokens,
)
from scripts.evaluate_request_tool_route_horizontal import _selected_case_ids

from google_work_agent.application.agents.request_understanding import (
    identify_effect_prohibitions as prohibition_ops,
)
from google_work_agent.application.agents.request_understanding import (
    identify_output_responsibilities as output_ops,
)
from google_work_agent.application.agents.request_understanding import (
    identify_source_dependencies as source_ops,
)
from google_work_agent.application.tool_registry.load_signed_tool_registry import (
    load_development_tool_registry,
)


def test_all_canonical_selection_keeps_the_fixed_92_denominator() -> None:
    case_ids = _selected_case_ids(all_canonical=True, requested=None)

    assert len(case_ids) == 92
    assert case_ids[0] == "CASE-CORE-001"
    assert case_ids[-1] == "CASE-STRESS-020"


def test_all_canonical_cannot_be_combined_with_case_selection() -> None:
    with pytest.raises(ValueError, match="cannot be combined"):
        _selected_case_ids(all_canonical=True, requested=["CASE-CORE-001"])


def test_request_local_ranges_materialize_exact_original_spans() -> None:
    request = "메일 A를 확인해서 요약하고, 그 요약으로 이슈를 작성해줘."
    tokens = _request_tokens(request)

    materialized = _materialize_requested_work(
        {
            "work_units": [
                {"ranges": [{"start_token_id": "t001", "end_token_id": "t004"}]},
                {"ranges": [{"start_token_id": "t005", "end_token_id": "t008"}]},
            ]
        },
        user_request=request,
        tokens=tokens,
    )

    assert materialized == {
        "schema_version": 1,
        "work_units": [
            {"request_spans": ["메일 A를 확인해서 요약하고,"]},
            {"request_spans": ["그 요약으로 이슈를 작성해줘."]},
        ],
    }


def test_atomic_schema_closes_all_semantic_views_over_work_units() -> None:
    catalog = load_development_tool_registry()
    sources = source_ops.build_source_dependency_candidates(catalog)
    outputs = output_ops.build_output_responsibility_candidates(catalog)
    effects = prohibition_ops.build_effect_prohibition_candidates(outputs)

    schema = _atomic_semantic_schema(
        work_unit_ids=("work-1", "work-2"),
        source_candidates=sources,
        output_candidates=outputs,
        effect_candidates=effects,
    ).json_schema

    assert set(schema["required"]) == {
        "goal",
        "completion_conditions",
        "constraints",
        "analysis_requirement",
        "explicit_prohibitions",
        "required_sources",
        "requested_outputs",
    }
    source_schema = schema["properties"]["required_sources"]
    assert len(source_schema["items"]["allOf"]) == len(sources)
    assert len(source_schema["allOf"]) == len(sources)


def test_goal_output_schema_adds_only_the_requested_output_view() -> None:
    catalog = load_development_tool_registry()
    outputs = output_ops.build_output_responsibility_candidates(catalog)

    schema = _goal_output_semantic_schema(
        work_unit_ids=("work-1", "work-2"),
        output_candidates=outputs,
    ).json_schema

    assert "requested_outputs" in schema["required"]
    assert set(schema["properties"]["requested_outputs"]["items"]["required"]) == {
        "resource_type",
        "effect",
        "work_unit_ids",
    }
    assert "required_sources" not in schema["properties"]
    assert "explicit_prohibitions" not in schema["properties"]


def test_goal_output_modality_schema_closes_answer_and_change_shapes() -> None:
    outputs = output_ops.build_output_responsibility_candidates(load_development_tool_registry())

    schema = _goal_output_modality_schema(
        work_unit_ids=("work-1",),
        output_candidates=outputs,
    ).json_schema

    assert "requested_result_mode" in schema["required"]
    assert schema["properties"]["requested_result_mode"]["enum"] == [
        "ANSWER_ONLY",
        "EXTERNAL_CHANGE",
    ]
    assert schema["allOf"][0]["then"]["properties"]["requested_outputs"] == {"maxItems": 0}
    assert schema["allOf"][1]["then"]["properties"]["requested_outputs"] == {"minItems": 1}


def test_goal_result_mode_schema_has_no_registry_output_choices() -> None:
    schema = _goal_result_mode_schema(("work-1",)).json_schema

    assert schema["properties"]["requested_result_mode"]["enum"] == [
        "ANSWER_ONLY",
        "EXTERNAL_CHANGE",
    ]
    assert "requested_outputs" not in schema["properties"]
