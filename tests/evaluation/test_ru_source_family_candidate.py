"""Two-stage Source family selection with fake inference, no Provider execution."""

from __future__ import annotations

import json
from copy import deepcopy
from typing import Any

import pytest
from evaluation.request_semantic_authority_candidate import AtomicSemanticAuthorityCandidate
from scripts.ru_source_family_candidate import SourceFamilyCandidate, family_catalog, family_schema

from google_work_agent.adapters.llm.ollama import transport
from google_work_agent.application.agents.request_understanding import (
    identify_source_dependencies as source_ops,
)
from google_work_agent.application.agents.tool_routing.bind_registry_candidates import (
    coarse_resource_category,
)
from google_work_agent.application.tool_registry.load_signed_tool_registry import (
    load_development_tool_registry,
)
from google_work_agent.ports.llm.output_schema_validation import validate_output_schema
from google_work_agent.ports.llm.structured_inference_contracts import PromptReference
from google_work_agent.ports.llm.structured_inference_port import StructuredInferenceResultV1


def _result(value: dict[str, Any]) -> StructuredInferenceResultV1:
    return StructuredInferenceResultV1(
        schema_version=1,
        structured_output=deepcopy(value),
        provider="TEST",
        model="test",
        actual_runtime="LOCAL_GPU",
        input_tokens=10,
        output_tokens=20,
        latency_ms=30,
        fallback_reason=None,
    )


def _prompt() -> PromptReference:
    return PromptReference(
        prompt_bundle_version="test",
        prompt_id="request_understanding.identify_source_dependencies",
        prompt_version="unchanged",
        content_hash="unchanged",
        agent_role="test",
        subgraph_name="test",
        node_name="test",
        node_state="test",
        purpose="test",
        input_schema_version="test",
        output_schema_version="test",
    )


class _Delegate:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self.invalid = False

    def infer(self, mode: Any, prompt: Any, projection: Any, schema: Any) -> Any:
        self.calls.append(
            {"mode": mode, "prompt": prompt, "input": deepcopy(projection), "schema": schema}
        )
        base = projection.get("base_projection", projection)
        values = []
        for item in base["source_candidates"]:
            if item["resource_type"] == "TASK":
                values.append(
                    {
                        "resource_type": "TASK",
                        "dependency": "SOURCE_REQUIRED",
                        "required_information": ["due"],
                        "target_scope": "CRITERIA",
                        "work_unit_ids": ["work-1"],
                    }
                )
            else:
                values.append(
                    {"resource_type": item["resource_type"], "dependency": "SOURCE_NOT_REQUIRED"}
                )
        if self.invalid:
            values.append({"resource_type": "GMAIL_MESSAGE", "dependency": "SOURCE_NOT_REQUIRED"})
        return _result({"source_dependencies": values})


def _setup(monkeypatch: pytest.MonkeyPatch, families: list[str]) -> tuple[Any, Any, Any, Any, Any]:
    registry = load_development_tool_registry()
    delegate = _Delegate()
    candidate = SourceFamilyCandidate(
        delegate=delegate, tool_catalog=registry, model_id="test", sampling_seed=4
    )
    candidates = list(source_ops.build_source_dependency_candidates(registry))
    projection = {
        "user_request": "원문을 그대로 사용한다.",
        "selected_resource_refs": [
            {"resource_type": "gmail_message", "resource_id": "selected-id"}
        ],
        "requested_work": {"work_units": [{"unit_id": "work-1"}]},
        "goal_candidate": {"goal": "생성된 Goal은 family 단계에 전달하지 않는다."},
        "source_candidates": candidates,
    }
    seen = []

    def invoke(**kwargs: Any) -> Any:
        seen.append(deepcopy(kwargs))
        raw = {"source_families": families}
        return (
            raw,
            _result(raw),
            [{"attempt": "FIRST", "structured_output": raw, "schema_errors": []}],
        )

    monkeypatch.setattr(candidate, "_invoke_candidate", invoke)
    schema = source_ops.build_source_dependency_output_schema(candidates, work_unit_ids=("work-1",))
    return candidate, delegate, projection, schema, seen


def test_family_catalog_and_schema_reuse_only_registered_categories() -> None:
    candidates = source_ops.build_source_dependency_candidates(load_development_tool_registry())
    catalog = family_catalog(candidates)
    assert {entry["family"] for entry in catalog} == {
        coarse_resource_category(item["resource_type"]) for item in candidates
    }
    schema = family_schema(["TASK", "CALENDAR"])
    assert not validate_output_schema({"source_families": []}, schema.json_schema)
    assert not validate_output_schema({"source_families": ["TASK", "CALENDAR"]}, schema.json_schema)
    for value in (["TASK", "TASK"], ["EMAIL"], ["GITHUB"], ["TASK_LIST"]):
        assert validate_output_schema({"source_families": value}, schema.json_schema)


def test_two_stages_keep_original_request_and_single_subset_owner_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    candidate, delegate, projection, schema, seen = _setup(monkeypatch, ["TASK", "CALENDAR"])
    original = deepcopy(projection)
    result = candidate.infer("LOCAL_GPU", _prompt(), projection, schema)
    assert projection == original
    assert len(seen) == 1
    first_input = seen[0]["prompt_input"]
    assert set(first_input) == {
        "user_request",
        "selected_resource_refs",
        "requested_work",
        "available_source_families",
    }
    assert first_input["user_request"] == projection["user_request"]
    assert len(delegate.calls) == 1
    second = delegate.calls[0]
    assert second["prompt"] == _prompt()
    assert second["input"]["user_request"] == projection["user_request"]
    assert second["input"]["goal_candidate"] == projection["goal_candidate"]
    assert {
        coarse_resource_category(item["resource_type"])
        for item in second["input"]["source_candidates"]
    } == {"TASK", "CALENDAR"}
    assert len(result.structured_output["source_dependencies"]) == len(
        projection["source_candidates"]
    )
    task = next(
        item
        for item in result.structured_output["source_dependencies"]
        if item["resource_type"] == "TASK"
    )
    assert task["work_unit_ids"] == ["work-1"]
    assert task["required_information"] == ["due"]
    assert not validate_output_schema(result.structured_output, schema.json_schema)
    assert (result.input_tokens, result.output_tokens, result.latency_ms) == (20, 40, 60)
    assert candidate.additional_provider_call_count == 1
    assert candidate.events[0]["raw_output"] == {"source_families": ["TASK", "CALENDAR"]}
    assert candidate.events[1]["raw_output"] != candidate.events[1]["materialized_output"]


def test_empty_family_choice_skips_stage_two_without_inventing_selected_source(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    candidate, delegate, projection, schema, _ = _setup(monkeypatch, [])
    result = candidate.infer("LOCAL_GPU", _prompt(), projection, schema)
    assert not delegate.calls
    assert all(
        item["dependency"] == "SOURCE_NOT_REQUIRED"
        for item in result.structured_output["source_dependencies"]
    )
    assert candidate.events[0]["source_owner_skipped"] is True
    assert candidate.additional_provider_call_count == 0
    assert result.input_tokens == 10


def test_empty_family_choice_cannot_weaken_caller_at_least_one_requirement(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    candidate, delegate, projection, _, _ = _setup(monkeypatch, [])
    schema = source_ops.build_source_dependency_output_schema(
        projection["source_candidates"], work_unit_ids=("work-1",), require_at_least_one_source=True
    )
    with pytest.raises(ValueError, match="caller schema"):
        candidate.infer("LOCAL_GPU", _prompt(), projection, schema)
    assert not delegate.calls


def test_subset_owner_cannot_return_excluded_resources(monkeypatch: pytest.MonkeyPatch) -> None:
    candidate, delegate, projection, schema, _ = _setup(monkeypatch, ["TASK"])
    delegate.invalid = True
    with pytest.raises(ValueError, match="source dependency candidate is invalid"):
        candidate.infer("LOCAL_GPU", _prompt(), projection, schema)
    assert candidate.events[-1]["error_type"] == "ValueError"
    assert "raw_output" in candidate.events[-1]


def test_revision_preserves_failure_context_and_filters_prior_candidate_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    candidate, delegate, projection, schema, _ = _setup(monkeypatch, ["TASK"])
    revision = {
        "base_projection": projection,
        "candidate_output": {
            "source_dependencies": [
                {"resource_type": item["resource_type"], "dependency": "SOURCE_NOT_REQUIRED"}
                for item in projection["source_candidates"]
            ]
        },
        "failure_record": {
            "reason_code": "TEST",
            "affected_field_paths": ["$.source_dependencies"],
        },
    }
    original = deepcopy(revision)
    candidate.infer("LOCAL_GPU", _prompt(), revision, schema)
    assert revision == original
    assert delegate.calls[0]["input"]["failure_record"] == revision["failure_record"]
    assert all(
        coarse_resource_category(item["resource_type"]) == "TASK"
        for item in delegate.calls[0]["input"]["candidate_output"]["source_dependencies"]
    )
    assert candidate.events[0]["attempt"] == "REVISION"


def test_family_failure_is_preserved_and_stops_subset_owner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    candidate, delegate, projection, schema, _ = _setup(monkeypatch, ["UNKNOWN"])
    with pytest.raises(ValueError, match="Source-family"):
        candidate.infer("LOCAL_GPU", _prompt(), projection, schema)
    assert candidate.events[0]["raw_output"] == {"source_families": ["UNKNOWN"]}
    assert candidate.events[0]["error_type"] == "ValueError"
    assert not delegate.calls


@pytest.mark.parametrize("repair_valid", [False, True])
def test_family_first_output_and_schema_repair_are_preserved_without_live_calls(
    monkeypatch: pytest.MonkeyPatch, repair_valid: bool
) -> None:
    candidate, delegate, projection, schema, _ = _setup(monkeypatch, ["TASK"])
    monkeypatch.setattr(
        candidate,
        "_invoke_candidate",
        AtomicSemanticAuthorityCandidate._invoke_candidate.__get__(candidate),
    )
    calls = []

    def dispatch(**kwargs: Any) -> Any:
        calls.append(deepcopy(kwargs))
        value = ["TASK"] if repair_valid and len(calls) == 2 else ["UNKNOWN"]
        return {
            "response": json.dumps({"source_families": value}),
            "model": "test",
            "prompt_eval_count": 3,
            "eval_count": 5,
            "total_duration": 1000000,
        }

    monkeypatch.setattr(transport, "_post_json", dispatch)
    if repair_valid:
        candidate.infer("LOCAL_GPU", _prompt(), projection, schema)
        assert len(delegate.calls) == 1
    else:
        with pytest.raises(ValueError, match="candidate structured output is invalid"):
            candidate.infer("LOCAL_GPU", _prompt(), projection, schema)
        assert not delegate.calls
        assert candidate.events[0]["error_type"] == "ValueError"
    assert len(calls) == 2
    attempts = candidate.events[0]["transport_attempts"]
    assert len(attempts) == 2
    assert json.loads(attempts[0]["content"]) == {"source_families": ["UNKNOWN"]}
    assert attempts[1]["input"]["candidate_output"] == {"source_families": ["UNKNOWN"]}
    assert attempts[1]["input"]["schema_errors"]
