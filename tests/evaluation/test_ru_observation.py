"""Evaluation-only runtime envelope tests; no model or Provider is called."""

from __future__ import annotations

import json
from copy import deepcopy
from typing import Any

import pytest
from scripts.ru_observation import (
    metrics,
    observe_local_calls,
    source_chat_envelope,
    thinking_envelope,
)

from google_work_agent.adapters.llm.ollama import transport
from google_work_agent.ports.llm.structured_inference_contracts import (
    OutputSchemaDefinition,
    PromptReference,
)

_TARGET = "request_understanding.identify_source_dependencies"


def _invoke(prompt_id: str) -> Any:
    return transport.OllamaHTTPClient().invoke_structured(
        endpoint="http://127.0.0.1:11434",
        model_id="test-model",
        prompt_ref=PromptReference(
            prompt_id=prompt_id,
            prompt_version="v1",
            content_hash="test-hash",
            prompt_bundle_version="test",
            agent_role="test",
            subgraph_name="test",
            node_name="test",
            node_state="test",
            purpose="test",
            input_schema_version="test",
            output_schema_version="test",
        ),
        prompt_input={"user_request": "자료의 상태를 알려줘."},
        output_schema=OutputSchemaDefinition("test", {"type": "object"}),
        timeout_seconds=180,
        instruction_text="Unchanged instruction.",
        sampling_temperature=0.0,
        sampling_seed=4,
    )


def test_envelope_changes_only_think_and_records_no_thinking_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sent: list[dict[str, Any]] = []
    response: dict[str, Any] = {
        "response": '{"source_dependencies": []}',
        "thinking": "private reasoning must never be recorded",
        "model": "test-model",
        "prompt_eval_count": 41,
        "eval_count": 73,
        "total_duration": 53000000,
    }

    def dispatch(**kwargs: Any) -> Any:
        sent.append(deepcopy(kwargs))
        return deepcopy(response)

    monkeypatch.setattr(transport, "_post_json", dispatch)
    _invoke(_TARGET)
    records: list[dict[str, Any]] = []
    with observe_local_calls(records), thinking_envelope(records, {_TARGET}):
        result = _invoke(_TARGET)
    baseline, candidate = sent
    expected = deepcopy(baseline)
    expected["payload"]["think"] = True
    assert candidate == expected
    assert baseline["payload"]["think"] is False
    assert result.content == response["response"]
    assert records[0]["think_requested"] is True
    assert records[0]["thinking_present"] is True
    assert records[0]["thinking_char_count"] == len(response["thinking"])
    assert response["thinking"] not in json.dumps(records)
    assert metrics(records) == {
        "calls": 1,
        "input_tokens": 41,
        "output_tokens": 73,
        "reported_latency_ms": 53,
        "missing_usage_calls": 0,
    }
    assert transport._post_json is dispatch


@pytest.mark.parametrize("prompt_id", [_TARGET + ".repair", "request_understanding.identify_goal"])
def test_nonmatching_prompt_is_unchanged(monkeypatch: pytest.MonkeyPatch, prompt_id: str) -> None:
    sent: list[dict[str, Any]] = []

    def dispatch(**kwargs: Any) -> Any:
        sent.append(deepcopy(kwargs))
        return {"response": "{}", "thinking": "not retained"}

    monkeypatch.setattr(transport, "_post_json", dispatch)
    records: list[dict[str, Any]] = []
    with observe_local_calls(records), thinking_envelope(records, {_TARGET}):
        _invoke(prompt_id)
    assert sent[0]["payload"]["think"] is False
    assert "think_requested" not in records[0]
    assert "thinking_present" not in records[0]
    assert "not retained" not in json.dumps(records)


@pytest.mark.parametrize("thinking", [None, ""])
def test_missing_thinking_is_reported_without_fabricating_content(
    monkeypatch: pytest.MonkeyPatch, thinking: str | None
) -> None:
    monkeypatch.setattr(
        transport, "_post_json", lambda **kwargs: {"response": "{}", "thinking": thinking}
    )
    records: list[dict[str, Any]] = []
    with observe_local_calls(records), thinking_envelope(records, {_TARGET}):
        _invoke(_TARGET)
    assert records[0]["thinking_present"] is False
    assert records[0]["thinking_char_count"] == 0


def test_failed_attempt_keeps_observer_error_and_restores_transport(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def dispatch(**kwargs: Any) -> Any:
        assert kwargs["payload"]["think"] is True
        raise TimeoutError("bounded test timeout")

    monkeypatch.setattr(transport, "_post_json", dispatch)
    records: list[dict[str, Any]] = []
    with (
        pytest.raises(TimeoutError),
        observe_local_calls(records),
        thinking_envelope(records, {_TARGET}),
    ):
        _invoke(_TARGET)
    assert records[0]["think_requested"] is True
    assert records[0]["error_type"] == "TimeoutError"
    assert "thinking_present" not in records[0]
    assert transport._post_json is dispatch


@pytest.mark.parametrize("thinking", [False, True])
def test_source_chat_keeps_payload_meaning_and_usage_without_recording_reasoning(
    monkeypatch: pytest.MonkeyPatch, thinking: bool
) -> None:
    sent: list[dict[str, Any]] = []

    def dispatch(**kwargs: Any) -> Any:
        sent.append(deepcopy(kwargs))
        if kwargs["path"] == "/api/generate":
            return {"response": "{}"}
        return {
            "message": {
                "role": "assistant",
                "content": '{"source_dependencies": []}',
                "thinking": "private chat reasoning",
            },
            "model": "test-model",
            "prompt_eval_count": 53,
            "eval_count": 87,
            "total_duration": 65000000,
        }

    monkeypatch.setattr(transport, "_post_json", dispatch)
    _invoke(_TARGET)
    records: list[dict[str, Any]] = []
    with observe_local_calls(records), source_chat_envelope(records, thinking):
        result = _invoke(_TARGET)
    baseline, candidate = sent
    expected = deepcopy(baseline)
    expected["path"] = "/api/chat"
    payload = expected["payload"]
    system = payload.pop("system")
    prompt = payload.pop("prompt")
    payload["messages"] = [
        {"role": "system", "content": system},
        {"role": "user", "content": prompt},
    ]
    payload["think"] = thinking
    assert candidate == expected
    assert result.content == '{"source_dependencies": []}'
    assert records[0]["envelope"] == "SOURCE_CHAT"
    assert records[0]["think_requested"] is thinking
    assert records[0]["thinking_present"] is True
    assert records[0]["thinking_char_count"] == len("private chat reasoning")
    assert "private chat reasoning" not in json.dumps(records)
    assert metrics(records) == {
        "calls": 1,
        "input_tokens": 53,
        "output_tokens": 87,
        "reported_latency_ms": 65,
        "missing_usage_calls": 0,
    }
    assert transport._post_json is dispatch


def test_source_chat_does_not_change_other_prompts(monkeypatch: pytest.MonkeyPatch) -> None:
    sent: list[dict[str, Any]] = []

    def dispatch(**kwargs: Any) -> Any:
        sent.append(deepcopy(kwargs))
        return {"response": "{}"}

    monkeypatch.setattr(transport, "_post_json", dispatch)
    records: list[dict[str, Any]] = []
    with observe_local_calls(records), source_chat_envelope(records, True):
        _invoke(_TARGET + ".other")
    assert sent[0]["path"] == "/api/generate"
    assert sent[0]["payload"]["think"] is False
    assert "messages" not in sent[0]["payload"]
    assert "envelope" not in records[0]


def test_source_chat_preserves_empty_final_response(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        transport,
        "_post_json",
        lambda **kwargs: {
            "message": {"content": "", "thinking": "private"},
            "eval_count": 101,
        },
    )
    records: list[dict[str, Any]] = []
    with observe_local_calls(records), source_chat_envelope(records, True):
        result = _invoke(_TARGET)
    assert result.content == ""
    assert records[0]["content"] == ""
    assert records[0]["output_tokens"] == 101
    assert "private" not in json.dumps(records)
