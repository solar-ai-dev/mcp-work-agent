"""No-model checks for a field-order-only evaluation candidate."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from typing import Any, cast

import pytest
from evaluation.request_semantic_authority_candidate import (
    GoalOutputModalityAuthorityCandidate,
    _goal_output_modality_schema,
)
from scripts.ru_ordered_authority_candidate import (
    SCHEMA_VERSION,
    OrderedGoalOutputAuthorityCandidate,
    ordered_authority_schema,
)

from google_work_agent.application.agents.request_understanding import (
    identify_output_responsibilities as output_ops,
)
from google_work_agent.application.tool_registry.load_signed_tool_registry import (
    load_development_tool_registry,
)
from google_work_agent.ports.llm.output_schema_validation import validate_output_schema
from google_work_agent.ports.llm.structured_inference_contracts import (
    OutputSchemaDefinition,
    PromptReference,
)
from google_work_agent.ports.llm.structured_inference_port import StructuredInferenceResultV1


def _schemas() -> tuple[OutputSchemaDefinition, OutputSchemaDefinition]:
    candidates = output_ops.build_output_responsibility_candidates(load_development_tool_registry())
    return (
        _goal_output_modality_schema(
            work_unit_ids=("work-1", "work-2"), output_candidates=candidates
        ),
        ordered_authority_schema(work_unit_ids=("work-1", "work-2"), output_candidates=candidates),
    )


def _raw() -> dict[str, Any]:
    return {
        "goal": "요청된 자료를 확인한다.",
        "completion_conditions": ["근거를 답한다."],
        "constraints": {
            "search_terms": [],
            "business_concepts": [],
            "person": [],
            "sender": [],
            "recipient": [],
            "subject": [],
            "period": [],
            "coverage_requirement": {"value": "NOT_COLLECTION", "work_unit_ids": ["work-1"]},
            "additional_constraints": [],
        },
        "analysis_requirement": "NONE",
        "requested_result_mode": "ANSWER_ONLY",
        "requested_outputs": [],
    }


def _prompt(prompt_id: str) -> PromptReference:
    return PromptReference(
        prompt_bundle_version="test",
        prompt_id=prompt_id,
        prompt_version="test",
        content_hash="test",
        agent_role="request_understanding",
        subgraph_name="request_understanding",
        node_name="identify_goal",
        node_state="test",
        purpose="test",
        input_schema_version="test",
        output_schema_version="test",
    )


def test_only_root_property_and_required_order_changes() -> None:
    baseline, ordered = _schemas()
    assert ordered.schema_version == SCHEMA_VERSION
    leading = ["requested_result_mode", "requested_outputs"]
    assert list(cast(dict[str, object], ordered.json_schema["properties"]))[:2] == leading
    assert cast(list[str], ordered.json_schema["required"])[:2] == leading
    restored = dict(deepcopy(ordered.json_schema))
    restored["required"] = baseline.json_schema["required"]
    assert restored == baseline.json_schema
    assert list(cast(dict[str, object], baseline.json_schema["properties"]))[0] == "goal"


@pytest.mark.parametrize("mode", ["ANSWER_ONLY", "EXTERNAL_CHANGE", "INVALID"])
@pytest.mark.parametrize("has_output", [False, True])
@pytest.mark.parametrize("work_id", ["work-1", "unknown"])
def test_accepted_values_and_invalid_values_are_identical(
    mode: str, has_output: bool, work_id: str
) -> None:
    baseline, ordered = _schemas()
    value = _raw()
    value["requested_result_mode"] = mode
    if has_output:
        value["requested_outputs"] = [
            {"resource_type": "TASK", "effect": "CREATE", "work_unit_ids": [work_id]}
        ]
    baseline_errors = validate_output_schema(value, baseline.json_schema)
    candidate_errors = validate_output_schema(value, ordered.json_schema)
    assert sorted(candidate_errors) == sorted(baseline_errors)
    expected_valid = mode == "ANSWER_ONLY" and not has_output
    expected_valid |= mode == "EXTERNAL_CHANGE" and has_output and work_id == "work-1"
    assert (not candidate_errors) == expected_valid


class _Delegate:
    def infer(self, *args: Any, **kwargs: Any) -> Any:
        raise AssertionError("Output cache must not call the delegate")


def test_v4_prompt_input_projection_and_output_cache_are_preserved(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    catalog = load_development_tool_registry()
    arguments = {
        "delegate": _Delegate(),
        "tool_catalog": catalog,
        "model_id": "test",
        "sampling_seed": 7,
    }
    baseline = GoalOutputModalityAuthorityCandidate(**arguments)
    candidate = OrderedGoalOutputAuthorityCandidate(**arguments)
    assert candidate._goal_output_instruction == baseline._goal_output_instruction
    assert candidate._goal_output_prompt_version == baseline._goal_output_prompt_version
    assert (
        candidate.binding["goal_output_prompt_sha256"]
        == baseline.binding["goal_output_prompt_sha256"]
    )
    value = _raw()
    value["requested_result_mode"] = "EXTERNAL_CHANGE"
    outputs = [
        {"resource_type": "TASK", "effect": "CREATE", "work_unit_ids": ["work-1"]},
        {"resource_type": "TASK", "effect": "CREATE", "work_unit_ids": ["work-2"]},
    ]
    value["requested_outputs"] = deepcopy(outputs)
    seen: list[dict[str, Any]] = []

    def invoke(**kwargs: Any) -> Any:
        seen.append(kwargs)
        return (
            deepcopy(value),
            StructuredInferenceResultV1(
                schema_version=1,
                structured_output=deepcopy(value),
                provider="TEST",
                model="test",
                actual_runtime="LOCAL_GPU",
                input_tokens=10,
                output_tokens=20,
                latency_ms=30,
                fallback_reason=None,
            ),
            [],
        )

    monkeypatch.setattr(candidate, "_invoke_candidate", invoke)
    projection = {
        "user_request": "서로 다른 두 업무를 준비해줘.",
        "requested_work": {"work_units": [{"unit_id": "work-1"}, {"unit_id": "work-2"}]},
    }
    goal_prompt = _prompt("request_understanding.identify_goal")
    goal = candidate.infer("LOCAL_GPU", goal_prompt, projection, _schemas()[0])
    assert len(seen) == 1
    assert seen[0]["prompt_input"] == {
        **projection,
        "output_candidates": candidate._output_candidates,
    }
    assert set(goal.structured_output) == {
        "goal",
        "completion_conditions",
        "constraints",
        "analysis_requirement",
    }
    output_prompt = replace(
        goal_prompt, prompt_id="request_understanding.identify_output_responsibilities"
    )
    for _ in range(2):
        result = candidate.infer("LOCAL_GPU", output_prompt, projection, _schemas()[0])
        assert result.structured_output == {"output_responsibilities": outputs}
        assert result.provider == "EVALUATION_CACHE"
        assert (result.input_tokens, result.output_tokens, result.latency_ms) == (0, 0, 0)
        cast(list[object], result.structured_output["output_responsibilities"]).clear()
    assert len(seen) == 1
    assert candidate.cached_response_count == 2
    candidate.reset_case()
    assert candidate._goal_output is None
    assert candidate.cached_response_count == 0
