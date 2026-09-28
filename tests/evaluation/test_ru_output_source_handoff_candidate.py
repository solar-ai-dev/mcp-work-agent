"""V20 direct handoff checks use fake transport only, not model evaluation."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest
from scripts.ru_observation import object_hash
from scripts.ru_output_source_handoff_candidate import (
    EVALUATION_SOURCE_PROMPT_ID,
    GOAL_PROMPT_ID,
    PROHIBITION_PROMPT_ID,
    SOURCE_PROMPT_ID,
    OutputSourceHandoffCandidate,
)

from google_work_agent.adapters.llm.ollama import transport
from google_work_agent.application.agents.request_understanding import (
    identify_effect_prohibitions as prohibition_ops,
)
from google_work_agent.application.agents.request_understanding import (
    identify_output_responsibilities as output_ops,
)
from google_work_agent.application.agents.request_understanding import (
    identify_source_dependencies as source_ops,
)
from google_work_agent.application.agents.request_understanding.contracts import (
    request_goal_candidate_schema as goal_schema,
)
from google_work_agent.application.prompt_runtime.assemble_prompt import assemble_prompt
from google_work_agent.application.prompt_runtime.prompt_registry import EVALUATION, PromptRegistry
from google_work_agent.application.tool_registry.load_signed_tool_registry import (
    load_development_tool_registry,
)
from google_work_agent.ports.llm.structured_inference_port import StructuredInferenceResultV1


def _result(raw: Any) -> StructuredInferenceResultV1:
    return StructuredInferenceResultV1(
        schema_version=1,
        structured_output=deepcopy(raw),
        provider="TEST",
        model="test",
        actual_runtime="LOCAL_GPU",
        input_tokens=1,
        output_tokens=1,
        latency_ms=1,
        fallback_reason=None,
    )


def _fixture() -> tuple[dict[str, Any], dict[str, Any], Any]:
    registry = load_development_tool_registry()
    constraints: dict[str, Any] = {
        key: []
        for key in (
            "search_terms",
            "business_concepts",
            "person",
            "sender",
            "recipient",
            "subject",
            "period",
        )
    }
    constraints["coverage_requirement"] = {"value": "LIMITED_ITEMS", "work_unit_ids": ["work-1"]}
    constraints["additional_constraints"] = []
    goal = {
        "goal": "자료에 근거해 새 초안을 준비한다.",
        "completion_conditions": ["승인 전 초안을 준비한다."],
        "constraints": constraints,
        "analysis_requirement": "NONE",
    }
    raw = {
        **deepcopy(goal),
        "requested_result_mode": "EXTERNAL_CHANGE",
        "requested_outputs": [
            {"resource_type": "GMAIL_DRAFT", "effect": "CREATE", "work_unit_ids": ["work-1"]}
        ],
    }
    context = {
        "user_request": "기존 작업과 초안을 확인하고 별도 초안을 준비해줘.",
        "selected_resource_refs": [{"resource_type": "gmail_draft", "resource_id": "selected"}],
        "requested_work": {"work_units": [{"unit_id": "work-1"}, {"unit_id": "work-2"}]},
        "run_reference_time": {
            "reference_time": "2026-09-01T09:00:00+09:00",
            "timezone": "Asia/Seoul",
        },
    }
    effects = prohibition_ops.build_effect_prohibition_candidates(
        output_ops.build_output_responsibility_candidates(registry)
    )
    prohibitions = {
        "effect_prohibitions": [
            {
                "effect": effect["effect"],
                "prohibition": "NOT_FORBIDDEN",
                "work_unit_ids": ["work-1"],
            }
            for effect in effects
        ]
    }
    source = {
        **deepcopy(context),
        "goal_candidate": deepcopy(goal),
        "source_candidates": list(source_ops.build_source_dependency_candidates(registry)),
    }
    record = {
        "case_id": "synthetic-read-write-control",
        "atomic": [
            {
                "sequence": 2,
                "prompt_id": GOAL_PROMPT_ID,
                "attempt": "FIRST",
                "input": deepcopy(context),
                "structured_output": deepcopy(goal),
            },
            {
                "sequence": 3,
                "prompt_id": PROHIBITION_PROMPT_ID,
                "attempt": "FIRST",
                "input": {**deepcopy(context), "goal_candidate": deepcopy(goal)},
                "structured_output": prohibitions,
            },
            {
                "sequence": 4,
                "prompt_id": SOURCE_PROMPT_ID,
                "attempt": "FIRST",
                "input": deepcopy(source),
            },
        ],
        "semantic_candidate_events": [
            {
                "operation": "GOAL_OUTPUT_AUTHORITY",
                "attempt": "FIRST",
                "raw_output": raw,
                "projected_goal_output": deepcopy(goal),
            }
        ],
    }
    return {"cases": [record]}, source, registry


def _candidate(tmp_path: Path, payload: Any, registry: Any, **kwargs: Any) -> Any:
    path = tmp_path / "actual-authority.json"
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return OutputSourceHandoffCandidate(
        authority_replay_path=path,
        delegate=None,
        tool_catalog=registry,
        model_id="test",
        sampling_seed=4,
        **kwargs,
    )


def _source_output(source: Any) -> dict[str, Any]:
    return {
        "source_dependencies": [
            {
                "resource_type": item["resource_type"],
                "dependency": "SOURCE_REQUIRED",
                "required_information": [item["owned_fact_kinds"][0]],
                "target_scope": "CRITERIA",
                "work_unit_ids": ["work-1"],
            }
            if item["resource_type"] in {"TASK", "GMAIL_DRAFT"}
            else {"resource_type": item["resource_type"], "dependency": "SOURCE_NOT_REQUIRED"}
            for item in source["source_candidates"]
        ]
    }


def _run(candidate: Any, source: Any) -> Any:
    return candidate.infer(
        "LOCAL_GPU",
        PromptRegistry().lookup_for_evaluation(SOURCE_PROMPT_ID),
        source,
        source_ops.build_source_dependency_output_schema(
            source["source_candidates"], work_unit_ids=("work-1", "work-2")
        ),
    )


def _fake_transport(monkeypatch: Any, responses: list[Any]) -> list[Any]:
    calls: list[Any] = []

    def dispatch(**kwargs: Any) -> Any:
        calls.append(deepcopy(kwargs["payload"]))
        raw = responses[len(calls) - 1]
        return {
            "response": json.dumps(raw),
            "model": "test",
            "prompt_eval_count": 3,
            "eval_count": 5,
            "total_duration": 1000000,
        }

    monkeypatch.setattr(transport, "_post_json", dispatch)
    return calls


def test_frozen_handoff_reuses_actual_authorities_and_preserves_all_source_choices(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    payload, source, registry = _fixture()
    original = deepcopy(source)
    candidate = _candidate(tmp_path, payload, registry)
    expected = _source_output(source)
    calls = _fake_transport(monkeypatch, [expected])
    result = _run(candidate, source)
    assert result.structured_output == expected
    assert source == original
    assert len(calls) == 1
    wire = json.loads(calls[0]["prompt"])
    assert wire["prompt_ref"]["prompt_id"] == EVALUATION_SOURCE_PROMPT_ID
    authority = wire["input"].pop("confirmed_output_authority")
    assert wire["input"] == source
    assert (
        authority["output_responsibilities"]
        == payload["cases"][0]["semantic_candidate_events"][0]["raw_output"]["requested_outputs"]
    )
    assert (
        calls[0]["format"]
        == source_ops.build_source_dependency_output_schema(
            source["source_candidates"], work_unit_ids=("work-1", "work-2")
        ).json_schema
    )
    baseline = assemble_prompt(
        PromptRegistry().lookup_for_evaluation(SOURCE_PROMPT_ID), source, execution_scope=EVALUATION
    )
    assert calls[0]["system"].startswith(baseline)
    event = candidate.events[-1]
    assert event["authority_validation"] == "VALID"
    assert event["authority_origin"] == "FROZEN_V4_RAW"
    assert event["source_base_input_sha256"] == object_hash(source)
    assert event["validated_source_output"] == expected
    assert len(event["provider_attempts"]) == len(event["transport_attempts"]) == 1
    assert event["authority_replay_sha256"] == candidate.binding["authority_replay_sha256"]
    assert event["evaluation_input_contract_sha256"] == object_hash(candidate.input_contract)
    assert candidate.source_sampling["temperature"] == 0.05
    assert candidate.binding["source_sampling_sha256"] == object_hash(candidate.source_sampling)
    assert event["source_sampling_sha256"] == candidate.binding["source_sampling_sha256"]
    assert event["transport_attempts"][0]["temperature"] == candidate.source_sampling["temperature"]
    assert calls[0]["options"]["temperature"] == candidate.source_sampling["temperature"]
    assert calls[0]["options"]["seed"] == candidate.source_sampling["seed"]


@pytest.mark.parametrize(
    "key",
    [
        "user_request",
        "selected_resource_refs",
        "requested_work",
        "run_reference_time",
        "goal_candidate",
        "source_candidates",
    ],
)
def test_replay_rejects_changed_owner_input_before_dispatch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, key: str
) -> None:
    payload, source, registry = _fixture()
    candidate = _candidate(tmp_path, payload, registry)
    source[key] = "changed"
    calls = _fake_transport(monkeypatch, [])
    with pytest.raises(ValueError, match="identical frozen"):
        _run(candidate, source) if key != "source_candidates" else candidate.infer(
            "LOCAL_GPU", PromptRegistry().lookup_for_evaluation(SOURCE_PROMPT_ID), source, None
        )
    assert calls == []
    assert candidate.events[-1]["authority_validation"] == "REJECTED"


@pytest.mark.parametrize(
    "mismatch", ["goal_context", "prohibition_context", "unlinked_output", "order"]
)
def test_replay_requires_real_sequential_same_context_authority(
    tmp_path: Path, mismatch: str
) -> None:
    payload, source, registry = _fixture()
    case = payload["cases"][0]
    if mismatch == "goal_context":
        case["atomic"][0]["input"]["user_request"] = "another request"
    elif mismatch == "prohibition_context":
        case["atomic"][1]["input"]["run_reference_time"] = None
    elif mismatch == "unlinked_output":
        case["semantic_candidate_events"][0]["projected_goal_output"] = {}
    else:
        case["atomic"][1]["sequence"] = 5
    with pytest.raises(ValueError):
        _candidate(tmp_path, payload, registry)


@pytest.mark.parametrize("forbidden_unit", ["work-1", "work-2"])
def test_existing_output_validator_enforces_only_applicable_prohibitions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, forbidden_unit: str
) -> None:
    payload, source, registry = _fixture()
    for item in payload["cases"][0]["atomic"][1]["structured_output"]["effect_prohibitions"]:
        if item["effect"] == "CREATE":
            item.update(prohibition="FORBIDDEN", work_unit_ids=[forbidden_unit])
    candidate = _candidate(tmp_path, payload, registry)
    calls = _fake_transport(monkeypatch, [_source_output(source)])
    if forbidden_unit == "work-1":
        with pytest.raises(output_ops.ProhibitedOutputResponsibilityDecisionError):
            _run(candidate, source)
        assert calls == []
        assert candidate.events[-1]["authority_validation"] == "REJECTED"
    else:
        _run(candidate, source)
        assert len(calls) == 1
        assert candidate.events[-1]["authority_validation"] == "VALID"


@pytest.mark.parametrize("valid_after_repair", [True, False])
def test_source_cannot_edit_output_and_repair_remains_bounded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, valid_after_repair: bool
) -> None:
    payload, source, registry = _fixture()
    candidate = _candidate(tmp_path, payload, registry)
    valid = _source_output(source)
    invalid = {**deepcopy(valid), "requested_outputs": []}
    calls = _fake_transport(monkeypatch, [invalid, valid if valid_after_repair else invalid])
    if valid_after_repair:
        assert _run(candidate, source).structured_output == valid
    else:
        with pytest.raises(ValueError, match="candidate structured output is invalid"):
            _run(candidate, source)
    assert len(calls) == 2
    event = candidate.events[-1]
    assert len(event["transport_attempts"]) == 2
    assert [item["attempt"] for item in event["transport_attempts"]] == ["FIRST", "SCHEMA_REPAIR"]
    assert all(item["temperature"] == 0.05 for item in event["transport_attempts"])
    first, repair = [json.loads(item["prompt"])["input"] for item in calls]
    assert (
        repair["base_projection"]["confirmed_output_authority"]
        == first["confirmed_output_authority"]
    )
    assert repair["candidate_output"] == invalid
    assert candidate.additional_provider_call_count == 1
    assert (
        event["cached_goal_output"]
        == payload["cases"][0]["semantic_candidate_events"][0]["raw_output"]
    )


def test_compiled_path_uses_live_v4_cache_and_reset_discards_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload, source, registry = _fixture()
    case = payload["cases"][0]
    raw = case["semantic_candidate_events"][0]["raw_output"]

    class Delegate:
        def infer(self, mode: Any, prompt: Any, projection: Any, schema: Any) -> Any:
            assert prompt.prompt_id == PROHIBITION_PROMPT_ID
            return _result(case["atomic"][1]["structured_output"])

    candidate = OutputSourceHandoffCandidate(
        delegate=Delegate(), tool_catalog=registry, model_id="test", sampling_seed=4
    )
    calls = _fake_transport(monkeypatch, [raw, _source_output(source)])
    prompt_registry = PromptRegistry()
    candidate.infer(
        "LOCAL_GPU",
        prompt_registry.lookup_for_evaluation(GOAL_PROMPT_ID),
        case["atomic"][0]["input"],
        goal_schema.identify_goal_output_schema(("work-1", "work-2")),
    )
    candidate.infer(
        "LOCAL_GPU",
        prompt_registry.lookup_for_evaluation(PROHIBITION_PROMPT_ID),
        case["atomic"][1]["input"],
        None,
    )
    _run(candidate, source)
    assert len(calls) == 2
    assert candidate.events[-1]["authority_origin"] == "LIVE_V4_CACHE"
    assert candidate.events[-1]["cached_goal_output"] == raw
    candidate.reset_case()
    with pytest.raises(ValueError, match="identical frozen"):
        _run(candidate, source)
    assert len(calls) == 2


def test_product_input_allowlist_is_not_extended(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    payload, source, registry = _fixture()
    candidate = _candidate(tmp_path, payload, registry)
    calls = _fake_transport(monkeypatch, [])
    source["confirmed_output_authority"] = {"output_responsibilities": []}
    with pytest.raises(ValueError, match="unknown Product Prompt fields"):
        _run(candidate, source)
    assert calls == []


@pytest.mark.parametrize("identical_authority", [True, False])
def test_duplicate_raw_inputs_merge_only_identical_authorities(
    tmp_path: Path, identical_authority: bool
) -> None:
    payload, source, registry = _fixture()
    duplicate = deepcopy(payload["cases"][0])
    duplicate["case_id"] = "second-synthetic-record"
    if not identical_authority:
        duplicate["semantic_candidate_events"][0]["raw_output"]["requested_outputs"][0][
            "effect"
        ] = "UPDATE"
    payload["cases"].append(duplicate)
    if identical_authority:
        candidate = _candidate(tmp_path, payload, registry)
        record = candidate._authority(source)
        assert record["origin_case_ids"] == [
            "synthetic-read-write-control",
            "second-synthetic-record",
        ]
    else:
        with pytest.raises(ValueError, match="ambiguous authority"):
            _candidate(tmp_path, payload, registry)


def test_live_partial_cache_cannot_fall_back_to_frozen_authority(tmp_path: Path) -> None:
    payload, source, registry = _fixture()
    candidate = _candidate(tmp_path, payload, registry)
    candidate._goal_output = deepcopy(
        payload["cases"][0]["semantic_candidate_events"][0]["raw_output"]
    )
    with pytest.raises(ValueError, match="no replay fallback"):
        _run(candidate, source)
    assert candidate.events[-1]["transport_attempts"] == []
