"""No-model checks for current-request Goal projection with unchanged v11 decisions."""

from __future__ import annotations

import json
from copy import deepcopy
from dataclasses import replace
from typing import Any, cast

import pytest
from scripts.ru_ordered_authority_candidate import OrderedGoalOutputAuthorityCandidate
from scripts.ru_request_grounded_goal_candidate import (
    SCHEMA_VERSION,
    RequestGroundedGoalCandidate,
    request_grounded_goal_instruction,
)

from google_work_agent.adapters.llm.ollama.transport import OllamaHTTPClient
from google_work_agent.application.tool_registry.load_signed_tool_registry import (
    load_development_tool_registry,
)
from google_work_agent.ports.llm.output_schema_validation import validate_output_schema
from google_work_agent.ports.llm.structured_inference_contracts import (
    OutputSchemaDefinition,
    PromptReference,
    ProviderResponsePayload,
)


class _Delegate:
    def infer(self, *args: Any, **kwargs: Any) -> Any:
        raise AssertionError("Goal and cached Output must not call the delegate")


class _Client:
    def __init__(self, outputs: list[dict[str, Any]]) -> None:
        self.outputs = deepcopy(outputs)
        self.calls: list[dict[str, Any]] = []

    def invoke_structured(self, **kwargs: Any) -> ProviderResponsePayload:
        self.calls.append(deepcopy(kwargs))
        return ProviderResponsePayload(
            content=json.dumps(self.outputs.pop(0), ensure_ascii=False),
            model="test",
            input_tokens=10,
            output_tokens=20,
            latency_ms=30,
            provider_request_id=None,
        )


def _raw() -> dict[str, Any]:
    return {
        "requested_result_mode": "EXTERNAL_CHANGE",
        "requested_outputs": [
            {"resource_type": "TASK", "effect": "CREATE", "work_unit_ids": ["work-1"]},
            {"resource_type": "TASK", "effect": "CREATE", "work_unit_ids": ["work-2"]},
        ],
        "completion_conditions": ["요청한 작성안을 각각 준비한다."],
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
    }


def _prompt() -> PromptReference:
    return PromptReference(
        prompt_bundle_version="test",
        prompt_id="request_understanding.identify_goal",
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


def _setup(
    outputs: list[dict[str, Any]] | None = None,
) -> tuple[RequestGroundedGoalCandidate, OrderedGoalOutputAuthorityCandidate, _Client]:
    client = _Client(outputs if outputs is not None else [_raw()])
    arguments = {
        "delegate": _Delegate(),
        "tool_catalog": load_development_tool_registry(),
        "model_id": "test",
        "sampling_seed": 7,
        "client": cast(OllamaHTTPClient, client),
    }
    return (
        RequestGroundedGoalCandidate(**arguments),
        OrderedGoalOutputAuthorityCandidate(**arguments),
        client,
    )


def _schema(candidate: OrderedGoalOutputAuthorityCandidate) -> OutputSchemaDefinition:
    return candidate._build_goal_output_schema(
        work_unit_ids=("work-1", "work-2"), output_candidates=candidate._output_candidates
    )


def _input() -> dict[str, Any]:
    return {
        "user_request": "  첫 작성안, 두 번째 작성안을 준비해줘.\n전송은 하지 마.  ",
        "requested_work": {"work_units": [{"unit_id": "work-1"}, {"unit_id": "work-2"}]},
    }


def test_schema_removes_only_goal_and_preserves_v11_order() -> None:
    candidate, baseline, _ = _setup()
    actual = _schema(candidate)
    expected = cast(dict[str, Any], deepcopy(dict(_schema(baseline).json_schema)))
    expected["properties"].pop("goal")
    expected["required"].remove("goal")
    assert actual.schema_version == SCHEMA_VERSION
    assert actual.json_schema == expected
    assert list(actual.json_schema["properties"]) == list(expected["properties"])
    assert list(actual.json_schema["properties"])[:2] == [
        "requested_result_mode", "requested_outputs"
    ]
    assert "goal" in cast(dict[str, object], _schema(baseline).json_schema["properties"])
    assert not validate_output_schema(_raw(), actual.json_schema)
    assert validate_output_schema({**_raw(), "goal": "model rewrite"}, actual.json_schema)


@pytest.mark.parametrize("field,value", [
    ("requested_result_mode", "INVALID"),
    ("requested_outputs", []),
    ("analysis_requirement", "INVALID"),
    ("completion_conditions", "not an array"),
])
def test_remaining_validation_matches_v11(field: str, value: object) -> None:
    candidate, baseline, _ = _setup()
    raw = _raw()
    raw[field] = value
    candidate_errors = validate_output_schema(raw, _schema(candidate).json_schema)
    baseline_errors = validate_output_schema(
        {**raw, "goal": "model goal"}, _schema(baseline).json_schema
    )
    assert candidate_errors
    assert candidate_errors == baseline_errors


def test_prompt_changes_only_goal_generation_responsibility() -> None:
    candidate, baseline, _ = _setup()
    before = baseline._goal_output_instruction.splitlines()
    after = candidate._goal_output_instruction.splitlines()
    assert len(before) == len(after)
    changed = [(left, right) for left, right in zip(before, after, strict=True) if left != right]
    assert len(changed) == 2
    assert "goal은 실행기" in changed[0][1]
    assert changed[1][0].replace("- goal, ", "- ") == changed[1][1]
    assert candidate.binding["goal_output_prompt_sha256"] != baseline.binding[
        "goal_output_prompt_sha256"
    ]
    assert candidate.binding["baseline_goal_output_prompt_sha256"] == baseline.binding[
        "goal_output_prompt_sha256"
    ]
    with pytest.raises(ValueError, match="unchanged v11"):
        request_grounded_goal_instruction("changed upstream instruction")


def test_exact_request_projection_raw_events_and_output_cache_are_distinct() -> None:
    raw = _raw()
    candidate, _, client = _setup([raw])
    projection = _input()
    original = deepcopy(projection)
    result = candidate.infer("LOCAL_GPU", _prompt(), projection, _schema(candidate))
    assert projection == original
    assert result.structured_output == {
        "goal": projection["user_request"],
        **{field: raw[field] for field in (
            "completion_conditions", "constraints", "analysis_requirement"
        )},
    }
    assert len(client.calls) == 1
    call = client.calls[0]
    assert call["prompt_input"] == {
        **original, "output_candidates": candidate._output_candidates
    }
    assert (call["sampling_temperature"], call["sampling_seed"]) == (0.0, 7)
    event = cast(dict[str, Any], candidate.events[0])
    assert event["raw_output"] == raw
    assert "goal" not in event["raw_output"]
    assert "goal" not in event["provider_attempts"][0]["structured_output"]
    assert event["deterministic_projected_goal"] == projection["user_request"]
    assert event["projected_goal_output"] == result.structured_output
    assert event["goal_projection_source"] == "user_request"
    assert candidate._goal_output == raw
    assert (result.input_tokens, result.output_tokens, result.latency_ms) == (10, 20, 30)
    cast(list[object], result.structured_output["completion_conditions"]).clear()
    assert event["raw_output"]["completion_conditions"] == raw["completion_conditions"]
    assert event["projected_goal_output"]["completion_conditions"] == raw["completion_conditions"]
    for _ in range(2):
        output = candidate.infer(
            "LOCAL_GPU",
            replace(_prompt(), prompt_id="request_understanding.identify_output_responsibilities"),
            projection,
            _schema(candidate),
        )
        assert output.structured_output == {"output_responsibilities": raw["requested_outputs"]}
        assert output.provider == "EVALUATION_CACHE"
        assert (output.input_tokens, output.output_tokens, output.latency_ms) == (0, 0, 0)
        cast(list[object], output.structured_output["output_responsibilities"]).clear()
    assert len(client.calls) == 1
    assert candidate.cached_response_count == 2
    candidate.reset_case()
    assert candidate._goal_output is None
    assert candidate.events == []
    assert candidate.cached_response_count == 0


def test_schema_repair_retains_actual_invalid_model_goal_without_projected_goal_pollution() -> None:
    invalid = {**_raw(), "goal": "모델이 허용되지 않은 goal을 생성했다."}
    candidate, _, client = _setup([invalid, _raw()])
    result = candidate.infer("LOCAL_GPU", _prompt(), _input(), _schema(candidate))
    assert len(client.calls) == 2
    repair = client.calls[1]
    assert repair["prompt_input"]["candidate_output"] == invalid
    assert "goal" not in repair["output_schema"].json_schema["properties"]
    attempts = cast(list[dict[str, Any]], candidate.events[0]["provider_attempts"])
    assert attempts[0]["structured_output"]["goal"] == invalid["goal"]
    assert attempts[0]["schema_errors"]
    assert "goal" not in attempts[1]["structured_output"]
    assert candidate.events[0]["raw_output"] == _raw()
    assert result.structured_output["goal"] == _input()["user_request"]
    assert candidate.additional_provider_call_count == 1
    assert (result.input_tokens, result.output_tokens, result.latency_ms) == (20, 40, 60)


@pytest.mark.parametrize("request_value", [None, 123])
def test_missing_current_request_fails_before_inference(request_value: object) -> None:
    candidate, _, client = _setup()
    projection = {**_input(), "user_request": request_value}
    with pytest.raises(ValueError, match="current user_request"):
        candidate.infer("LOCAL_GPU", _prompt(), projection, _schema(candidate))
    assert client.calls == []


def test_confirmation_and_revision_payload_are_not_rewritten() -> None:
    candidate, _, client = _setup()
    projection = {
        **_input(),
        "confirmation_response": {"text": "확인 응답은 원문에 합치지 않는다."},
        "failure_record": {"code": "test"},
        "prior_goal_candidate": {"goal": "보존된 기존 의미"},
    }
    original = deepcopy(projection)
    result = candidate.infer("LOCAL_GPU", _prompt(), projection, _schema(candidate))
    assert result.structured_output["goal"] == original["user_request"]
    assert projection == original
    for field, value in original.items():
        assert client.calls[0]["prompt_input"][field] == value
    assert candidate.events[0]["attempt"] == "REVISION"
