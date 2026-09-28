"""V23 uses the real repair assembly/consumer with fake Ollama transport only."""

from __future__ import annotations

import json
from copy import deepcopy
from dataclasses import replace
from types import SimpleNamespace
from typing import Any, cast

import pytest
from scripts.ru_observation import observe_local_calls
from scripts.ru_source_item_repair_candidate import (
    SOURCE_PROMPT_ID,
    SourceItemSchemaRepairer,
)

from google_work_agent.adapters.llm.ollama import transport
from google_work_agent.adapters.llm.ollama.structured_inference import (
    OllamaStructuredInferenceAdapter,
)
from google_work_agent.adapters.llm.runtime.prompt_repair_schema_repairer import (
    PromptRepairSchemaRepairer,
)
from google_work_agent.adapters.llm.runtime.structured_inference_router import (
    StructuredInferenceRuntimeRouter,
    _runtime_policy_for_prompt,
)
from google_work_agent.application.agents.request_understanding import (
    identify_source_dependencies as source_ops,
)
from google_work_agent.application.prompt_runtime.assemble_prompt import assemble_prompt
from google_work_agent.application.prompt_runtime.prompt_registry import EVALUATION, PromptRegistry
from google_work_agent.application.tool_registry.load_signed_tool_registry import (
    load_development_tool_registry,
)
from google_work_agent.ports.llm.structured_inference_contracts import (
    LLMInvocationError,
    RuntimePolicy,
)

_RESOURCES = ("GMAIL_DRAFT", "TASK", "CALENDAR_EVENT", "GMAIL_THREAD")


def _required(resource: str, work: str = "work-1") -> dict[str, Any]:
    return {
        "resource_type": resource,
        "dependency": "SOURCE_REQUIRED",
        "required_information": ["identity"],
        "target_scope": "CRITERIA",
        "work_unit_ids": [work],
    }


def _not_required(resource: str) -> dict[str, Any]:
    return {"resource_type": resource, "dependency": "SOURCE_NOT_REQUIRED"}


def _fixture() -> tuple[Any, Any, Any]:
    registry = PromptRegistry()
    prompt = registry.lookup_for_evaluation(SOURCE_PROMPT_ID)
    by_resource = {
        item["resource_type"]: item
        for item in source_ops.build_source_dependency_candidates(load_development_tool_registry())
    }
    candidates = [by_resource[key] for key in _RESOURCES]
    schema = source_ops.build_source_dependency_output_schema(candidates, work_unit_ids=["work-1"])
    projection = {
        "user_request": "작업과 일정만 확인해 새 초안을 준비해줘.",
        "selected_resource_refs": [],
        "requested_work": {"work_units": [{"unit_id": "work-1"}]},
        "run_reference_time": {"reference_time": "2026-09-01T09:00:00+09:00"},
        "goal_candidate": {"goal": "기존 자료를 확인하고 초안을 준비한다."},
        "source_candidates": deepcopy(candidates),
    }
    return prompt, schema, projection


def _run(
    monkeypatch: pytest.MonkeyPatch,
    failed: Any,
    repair: Any,
    *,
    schema_override: Any = None,
    artifacts: dict[str, Any] | None = None,
) -> tuple[Any, list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    prompt, schema, projection = _fixture()
    schema = schema_override or schema
    sent: list[dict[str, Any]] = []

    def dispatch(**kwargs: Any) -> Any:
        sent.append(deepcopy(kwargs))
        return {"response": json.dumps(repair), "prompt_eval_count": 41, "eval_count": 17}

    monkeypatch.setattr(transport, "_post_json", dispatch)
    provider = OllamaStructuredInferenceAdapter(
        provider_name="ollama",
        transport=transport.OllamaHTTPClient(),
        endpoint="http://127.0.0.1:11434",
        model_id="fake-model",
        assemble_instruction_text=lambda reference, value: assemble_prompt(
            reference,
            value,
            execution_scope=EVALUATION,
        ),
    )
    events: list[dict[str, Any]] = []
    runtime = SimpleNamespace(
        schema_repairer=SourceItemSchemaRepairer(
            PromptRepairSchemaRepairer(execution_scope=EVALUATION),
            events,
        ),
        before_provider_dispatch=lambda: None,
        _begin_llm_trace=lambda **kwargs: None,
        _finish_llm_trace=lambda *args, **kwargs: None,
    )
    calls: list[dict[str, Any]] = []
    if artifacts is not None:
        artifacts.update(events=events, sent=sent, calls=calls)
    with observe_local_calls(calls):
        result = StructuredInferenceRuntimeRouter._validate_or_repair(
            cast(Any, runtime),
            provider=provider,
            prompt_ref=prompt,
            prompt_input=projection,
            payload=failed,
            output_schema=schema,
            api_key=None,
            trace_context=cast(Any, None),
            semantic_validate=None,
            external_transfer_scope=None,
            runtime_policy=_runtime_policy_for_prompt(
                RuntimePolicy(sampling_temperature=0.0, sampling_seed=20260923),
                prompt,
            ),
        )
    return result, events, sent, calls


def test_conflicting_duplicates_and_missing_are_repaired_without_semantic_cleanup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Draft READ is semantically wrong for this request, but structurally valid:
    # the repair adapter must not use the request/Gold to turn it off.
    failed = {
        "source_dependencies": [
            _required("GMAIL_DRAFT"),
            _required("TASK"),
            _not_required("TASK"),
            _required("CALENDAR_EVENT"),
        ]
    }
    repair = {"source_dependencies": [_not_required("TASK"), _required("GMAIL_THREAD")]}
    original = deepcopy(failed)
    (merged, attempts, _), events, sent, calls = _run(monkeypatch, failed, repair)
    assert attempts == 2 and len(sent) == 1
    assert failed == original
    assert merged == {
        "source_dependencies": [
            _required("GMAIL_DRAFT"),
            _not_required("TASK"),
            _required("CALENDAR_EVENT"),
            _required("GMAIL_THREAD"),
        ]
    }
    event = events[0]
    assert event["mutable_resource_ids"] == ["TASK", "GMAIL_THREAD"]
    assert event["frozen_items_preserved"] is True
    assert event["full_schema_errors"] == []
    wire = sent[0]["payload"]
    wire_input = json.loads(wire["prompt"])["input"]
    base = wire_input["base_projection"]
    assert [item["resource_type"] for item in base["source_candidates"]] == ["TASK", "GMAIL_THREAD"]
    assert wire_input["candidate_output"] == {
        "source_dependencies": [_required("TASK"), _not_required("TASK")],
    }
    expected_system = assemble_prompt(_fixture()[0], wire_input, execution_scope=EVALUATION)
    assert wire["system"] == expected_system
    assert (
        json.dumps(base, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        in wire["system"]
    )
    assert base["user_request"] == _fixture()[2]["user_request"]
    assert wire["format"] == json.loads(wire["prompt"])["output_schema"]
    assert calls[0]["temperature"] == 0.05
    assert calls[0]["seed"] == 20260923
    assert calls[0]["timeout_seconds"] == 180
    assert calls[0]["input_tokens"] == 41 and calls[0]["output_tokens"] == 17


def test_valid_first_output_never_enters_repair(monkeypatch: pytest.MonkeyPatch) -> None:
    failed = {"source_dependencies": [_not_required(key) for key in _RESOURCES]}
    (result, attempts, payload), events, sent, calls = _run(monkeypatch, failed, {})
    assert result == failed and attempts == 1 and payload is None
    assert events == sent == calls == []


def test_unknown_work_is_repaired_only_within_known_resource(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    failed = {
        "source_dependencies": [
            _not_required("GMAIL_DRAFT"),
            _required("TASK", "unknown-work"),
            _not_required("CALENDAR_EVENT"),
            _not_required("GMAIL_THREAD"),
        ]
    }
    (merged, _, _), events, sent, _ = _run(
        monkeypatch,
        failed,
        {"source_dependencies": [_required("TASK")]},
    )
    assert events[0]["mutable_resource_ids"] == ["TASK"]
    assert merged["source_dependencies"][1]["work_unit_ids"] == ["work-1"]
    assert len(sent) == 1


@pytest.mark.parametrize(
    ("failed", "blocked_by_existing_guard"),
    [
        ("not-json", False),
        (
            {
                "source_dependencies": [
                    {"resource_type": "UNKNOWN", "dependency": "SOURCE_NOT_REQUIRED"}
                ]
            },
            True,
        ),
        ({"source_dependencies": [{"resource_type": ["TASK"]}]}, False),
    ],
)
def test_unidentifiable_input_retains_existing_full_repair(
    monkeypatch: pytest.MonkeyPatch,
    failed: Any,
    blocked_by_existing_guard: bool,
) -> None:
    repair = {"source_dependencies": [_not_required(key) for key in _RESOURCES]}
    artifacts: dict[str, Any] = {}
    if blocked_by_existing_guard:
        with pytest.raises(LLMInvocationError, match="outside the reported failure scope"):
            _run(monkeypatch, failed, repair, artifacts=artifacts)
    else:
        _run(monkeypatch, failed, repair, artifacts=artifacts)
    events, sent = artifacts["events"], artifacts["sent"]
    assert events[0]["mode"] == "FULL_REPAIR_UNCHANGED"
    base = json.loads(sent[0]["payload"]["prompt"])["input"]["base_projection"]
    assert [item["resource_type"] for item in base["source_candidates"]] == list(_RESOURCES)


def test_cross_item_candidate_contract_is_not_automatically_partitioned(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, original_schema, _ = _fixture()
    schema = deepcopy(original_schema.json_schema)
    schema["properties"]["source_dependencies"]["allOf"].append(
        {
            "contains": {
                "type": "object",
                "required": ["resource_type", "dependency"],
                "properties": {
                    "resource_type": {"const": "TASK"},
                    "dependency": {"const": "SOURCE_REQUIRED"},
                },
            },
        }
    )
    failed = {"source_dependencies": [_not_required(key) for key in _RESOURCES]}
    repair = deepcopy(failed)
    repair["source_dependencies"][1] = _required("TASK")
    artifacts: dict[str, Any] = {}
    with pytest.raises(LLMInvocationError, match="outside the reported failure scope"):
        _run(
            monkeypatch,
            failed,
            repair,
            schema_override=replace(original_schema, json_schema=schema),
            artifacts=artifacts,
        )
    events = artifacts["events"]
    assert events[0]["mode"] == "FULL_REPAIR_UNCHANGED"
    assert events[0]["reason"] == "UNRECOGNIZED_SOURCE_SCHEMA"


@pytest.mark.parametrize(
    "repair",
    [
        {"source_dependencies": []},
        {"source_dependencies": [_required("TASK"), _required("TASK")]},
        {"source_dependencies": [_required("GMAIL_DRAFT")]},
        {"source_dependencies": [_required("TASK", "unknown-work")]},
    ],
)
def test_invalid_repair_fails_without_second_repair_or_not_required_default(
    monkeypatch: pytest.MonkeyPatch,
    repair: Any,
) -> None:
    failed = {
        "source_dependencies": [
            _not_required("GMAIL_DRAFT"),
            _required("TASK", "unknown-work"),
            _not_required("CALENDAR_EVENT"),
            _not_required("GMAIL_THREAD"),
        ]
    }
    with pytest.raises(LLMInvocationError, match="localized Source repair remains invalid"):
        _run(monkeypatch, failed, repair)
