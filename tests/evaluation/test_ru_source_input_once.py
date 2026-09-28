"""V22 wire-envelope checks: fake transport only, no model or Provider I/O."""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from typing import Any

import pytest
from scripts.ru_observation import metrics, observe_local_calls, source_input_once_envelope

from google_work_agent.adapters.llm.ollama import transport
from google_work_agent.application.prompt_runtime.assemble_prompt import assemble_prompt
from google_work_agent.application.prompt_runtime.contracts.failure_record import (
    build_failure_record_v1,
)
from google_work_agent.application.prompt_runtime.prompt_registry import EVALUATION, PromptRegistry
from google_work_agent.ports.llm.structured_inference_contracts import OutputSchemaDefinition

_SOURCE_ID = "request_understanding.identify_source_dependencies"


def _input() -> dict[str, Any]:
    return {
        "user_request": "기존 자료의 상태를 알려줘. 외부 변경은 하지 마.",
        "selected_resource_refs": [],
        "requested_work": {"work_units": [{"unit_id": "work-1"}]},
        "goal_candidate": {"goal": "기존 자료의 상태를 확인한다."},
        "source_candidates": [],
        "run_reference_time": {"reference_time": "2026-09-01T09:00:00+09:00"},
    }


def _invoke(projection: Any, *, instruction: str | None = None, prompt_id: str = _SOURCE_ID) -> Any:
    from dataclasses import replace

    registry = PromptRegistry()
    prompt = registry.lookup_for_evaluation(_SOURCE_ID)
    instruction = (
        instruction
        if instruction is not None
        else assemble_prompt(prompt, projection, registry=registry, execution_scope=EVALUATION)
    )
    return transport.OllamaHTTPClient().invoke_structured(
        endpoint="http://127.0.0.1:11434",
        model_id="test-model",
        prompt_ref=replace(prompt, prompt_id=prompt_id),
        prompt_input=projection,
        output_schema=OutputSchemaDefinition("test", {"type": "object"}),
        timeout_seconds=180,
        instruction_text=instruction,
        sampling_temperature=0.05,
        sampling_seed=20260923,
    )


def _transport(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    sent: list[dict[str, Any]] = []

    def dispatch(**kwargs: Any) -> Any:
        sent.append(deepcopy(kwargs))
        return {
            "response": "{}",
            "prompt_eval_count": 39,
            "eval_count": 7,
            "total_duration": 45000000,
        }

    monkeypatch.setattr(transport, "_post_json", dispatch)
    return sent


def test_first_removes_only_exact_input_copy_and_preserves_product_assembly(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sent = _transport(monkeypatch)
    projection = _input()
    _invoke(projection)
    records: list[dict[str, Any]] = []
    with observe_local_calls(records), source_input_once_envelope(records):
        _invoke(projection)
    baseline, candidate = sent
    expected = deepcopy(baseline)
    wire_prompt = json.loads(expected["payload"]["prompt"])
    assert wire_prompt.pop("input") == projection
    expected["payload"]["prompt"] = json.dumps(wire_prompt, sort_keys=True, ensure_ascii=False)
    assert candidate == expected
    assert "output_schema" in wire_prompt
    assert records[0]["input_copy_action"] == "FIRST_REMOVED"
    assert (
        records[0]["wire_prompt_before_sha256"]
        == hashlib.sha256(baseline["payload"]["prompt"].encode()).hexdigest()
    )
    assert (
        records[0]["wire_prompt_after_sha256"]
        == hashlib.sha256(candidate["payload"]["prompt"].encode()).hexdigest()
    )
    assert records[0]["temperature"] == 0.05
    assert records[0]["seed"] == 20260923
    assert metrics(records) == {
        "calls": 1,
        "input_tokens": 39,
        "output_tokens": 7,
        "reported_latency_ms": 45,
        "missing_usage_calls": 0,
    }


def test_repair_keeps_complete_original_envelope(monkeypatch: pytest.MonkeyPatch) -> None:
    sent = _transport(monkeypatch)
    projection = {
        "base_projection": _input(),
        "candidate_output": {"source_dependencies": []},
        "failure_record": build_failure_record_v1(
            failure_id="synthetic-source:1",
            failure_reason_code="OUTPUT_SCHEMA_INVALID",
            failure_origin="LLM_OUTPUT",
            detected_by="RUNTIME_SCHEMA_VALIDATOR",
            runtime_disposition="RETRYABLE",
            experiment_disposition="RUN_REPAIR",
            affected_field_paths=["$.source_dependencies"],
        ),
    }
    _invoke(projection)
    records: list[dict[str, Any]] = []
    with observe_local_calls(records), source_input_once_envelope(records):
        _invoke(projection)
    assert sent[1] == sent[0]
    assert records[0]["input_copy_action"] == "REPAIR_UNCHANGED"
    assert records[0]["wire_prompt_before_sha256"] == records[0]["wire_prompt_after_sha256"]


@pytest.mark.parametrize(
    "instruction", ["unrelated instruction", "Allowed current-Run input projection (JSON):\n{}"]
)
def test_first_missing_identical_copy_fails_before_dispatch(
    monkeypatch: pytest.MonkeyPatch,
    instruction: str,
) -> None:
    sent = _transport(monkeypatch)
    records: list[dict[str, Any]] = []
    with (
        pytest.raises(ValueError, match="no identical assembled system copy"),
        observe_local_calls(records),
        source_input_once_envelope(records),
    ):
        _invoke(_input(), instruction=instruction)
    assert not sent
    assert records[0]["error_type"] == "ValueError"
    assert metrics(records)["missing_usage_calls"] == 1


@pytest.mark.parametrize(
    "prompt_id",
    [
        _SOURCE_ID + ".repair",
        "evaluation.refine_selected_source_families",
        "request_understanding.identify_goal",
    ],
)
def test_other_candidate_or_product_prompt_is_unchanged(
    monkeypatch: pytest.MonkeyPatch,
    prompt_id: str,
) -> None:
    sent = _transport(monkeypatch)
    _invoke(_input(), prompt_id=prompt_id, instruction="Unchanged instruction")
    records: list[dict[str, Any]] = []
    with observe_local_calls(records), source_input_once_envelope(records):
        _invoke(_input(), prompt_id=prompt_id, instruction="Unchanged instruction")
    assert sent[1] == sent[0]
    assert "envelope" not in records[0]


def test_timeout_keeps_actual_failure_and_restores_patch(monkeypatch: pytest.MonkeyPatch) -> None:
    def dispatch(**kwargs: Any) -> Any:
        assert "input" not in json.loads(kwargs["payload"]["prompt"])
        raise TimeoutError("synthetic timeout")

    monkeypatch.setattr(transport, "_post_json", dispatch)
    records: list[dict[str, Any]] = []
    with (
        pytest.raises(TimeoutError),
        observe_local_calls(records),
        source_input_once_envelope(records),
    ):
        _invoke(_input())
    assert records[0]["input_copy_action"] == "FIRST_REMOVED"
    assert records[0]["error_type"] == "TimeoutError"
    assert metrics(records)["missing_usage_calls"] == 1
    assert transport._post_json is dispatch
