from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest
from scripts.ru_source_family_bound_candidate import (
    BoundSourceFamilyCandidate,
    bound_family_source_schema,
)
from scripts.ru_source_family_candidate import SOURCE_PROMPT_ID, family_catalog

from google_work_agent.adapters.llm.ollama import transport
from google_work_agent.application.agents.request_understanding import (
    identify_source_dependencies as source_ops,
)
from google_work_agent.application.tool_registry.load_signed_tool_registry import (
    load_development_tool_registry,
)
from google_work_agent.ports.llm.output_schema_validation import validate_output_schema
from google_work_agent.ports.llm.structured_inference_contracts import PromptReference


def _decisions(candidates: Any, selected: set[str]) -> dict[str, Any]:
    return {
        "source_dependencies": [
            {
                "resource_type": item["resource_type"],
                "dependency": "SOURCE_REQUIRED",
                "required_information": [item["owned_fact_kinds"][0]],
                "target_scope": "CRITERIA",
                "work_unit_ids": ["work-1"],
            }
            if item["resource_type"] in selected
            else {
                "resource_type": item["resource_type"],
                "dependency": "SOURCE_NOT_REQUIRED",
            }
            for item in candidates
        ]
    }


def _setup(tmp_path: Path, families: list[str]) -> tuple[Any, Any, Any, Any]:
    registry = load_development_tool_registry()
    candidates = list(source_ops.build_source_dependency_candidates(registry))
    projection = {
        "user_request": "기존 작업과 일정만 확인해줘.",
        "selected_resource_refs": [],
        "requested_work": {"work_units": [{"unit_id": "work-1"}]},
        "goal_candidate": {"goal": "preserved"},
        "source_candidates": candidates,
    }
    first_input = {
        key: deepcopy(projection[key])
        for key in ("user_request", "selected_resource_refs", "requested_work")
    }
    first_input["available_source_families"] = family_catalog(candidates)
    replay = tmp_path / "frozen-family.json"
    replay.write_text(
        json.dumps(
            {
                "cases": [
                    {
                        "case_id": "synthetic-owner-output",
                        "semantic_candidate_events": [
                            {
                                "operation": "SOURCE_FAMILY_SELECTION",
                                "input": first_input,
                                "raw_output": {"source_families": families},
                            }
                        ],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    candidate = BoundSourceFamilyCandidate(
        family_replay_path=replay,
        delegate=None,
        tool_catalog=registry,
        model_id="test",
        sampling_seed=4,
    )
    prompt = PromptReference(
        prompt_bundle_version="test",
        prompt_id=SOURCE_PROMPT_ID,
        prompt_version="test",
        content_hash="test",
        agent_role="test",
        subgraph_name="test",
        node_name="test",
        node_state="test",
        purpose="test",
        input_schema_version="test",
        output_schema_version="test",
    )
    schema = source_ops.build_source_dependency_output_schema(candidates, work_unit_ids=("work-1",))
    return candidate, projection, prompt, schema


def test_bound_schema__requires_every_selected_family__without_deciding_subtype() -> None:
    all_candidates = source_ops.build_source_dependency_candidates(load_development_tool_registry())
    subset = [
        item
        for item in all_candidates
        if item["resource_type"]
        in {
            "TASK",
            "TASK_LIST",
            "CALENDAR",
            "CALENDAR_EVENT",
            "CALENDAR_FREEBUSY",
        }
    ]
    schema = bound_family_source_schema(
        subset, selected_families=["TASK", "CALENDAR"], work_unit_ids=("work-1",)
    )
    for selected in ({"TASK", "CALENDAR_EVENT"}, {"TASK_LIST", "CALENDAR_FREEBUSY"}):
        assert not validate_output_schema(_decisions(subset, selected), schema.json_schema)
    for selected in (set(), {"TASK"}, {"CALENDAR_EVENT"}):
        assert validate_output_schema(_decisions(subset, selected), schema.json_schema)
    with pytest.raises(ValueError, match="exactly match"):
        bound_family_source_schema(subset, selected_families=["TASK"], work_unit_ids=("work-1",))


def test_frozen_input__different_request__cannot_reuse_decision(tmp_path: Path) -> None:
    candidate, projection, prompt, schema = _setup(tmp_path, ["TASK"])
    projection["user_request"] += "다른 원문"
    with pytest.raises(ValueError, match="identical frozen"):
        candidate.infer("LOCAL_GPU", prompt, projection, schema)


def test_wrong_upstream_family__is_preserved_without_lexical_correction(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    candidate, projection, prompt, schema = _setup(tmp_path, ["EMAIL"])
    original = deepcopy(projection)
    seen = []

    def dispatch(**kwargs: Any) -> Any:
        seen.append(deepcopy(kwargs))
        actual = json.loads(kwargs["payload"]["prompt"])["input"]
        assert actual["selected_source_families"] == ["EMAIL"]
        assert actual["user_request"] == original["user_request"]
        return {
            "response": json.dumps(_decisions(actual["source_candidates"], {"GMAIL_DRAFT"})),
            "model": "test",
            "prompt_eval_count": 3,
            "eval_count": 5,
            "total_duration": 1000000,
        }

    monkeypatch.setattr(transport, "_post_json", dispatch)
    result = candidate.infer("LOCAL_GPU", prompt, projection, schema)
    assert projection == original
    assert len(seen) == 1
    assert {
        item["resource_type"]
        for item in result.structured_output["source_dependencies"]
        if item["dependency"] == "SOURCE_REQUIRED"
    } == {"GMAIL_DRAFT"}
    assert candidate.events[0]["raw_output"] == {"source_families": ["EMAIL"]}
    assert candidate.events[0]["new_provider_calls"] == 0
    assert candidate.events[0]["replay_sha256"] == candidate.binding["family_replay_sha256"]
    assert candidate.events[0]["input_sha256"]


@pytest.mark.parametrize("repair_valid", [False, True])
def test_missing_positive_binding__uses_one_bounded_repair__never_silent_fill(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    repair_valid: bool,
) -> None:
    candidate, projection, prompt, schema = _setup(tmp_path, ["TASK", "CALENDAR"])
    calls = []

    def dispatch(**kwargs: Any) -> Any:
        calls.append(deepcopy(kwargs))
        actual = json.loads(kwargs["payload"]["prompt"])["input"]
        base = actual.get("base_projection", actual)
        selected = {"TASK", "CALENDAR_EVENT"} if repair_valid and len(calls) == 2 else set()
        return {
            "response": json.dumps(_decisions(base["source_candidates"], selected)),
            "model": "test",
            "prompt_eval_count": 3,
            "eval_count": 5,
            "total_duration": 1000000,
        }

    monkeypatch.setattr(transport, "_post_json", dispatch)
    if repair_valid:
        result = candidate.infer("LOCAL_GPU", prompt, projection, schema)
        assert not validate_output_schema(result.structured_output, schema.json_schema)
    else:
        with pytest.raises(ValueError, match="candidate structured output is invalid"):
            candidate.infer("LOCAL_GPU", prompt, projection, schema)
        assert "materialized_output" not in candidate.events[-1]
    assert len(calls) == 2
    attempts = candidate.events[-1]["transport_attempts"]
    assert len(attempts) == 2
    assert all(
        item["dependency"] == "SOURCE_NOT_REQUIRED"
        for item in json.loads(attempts[0]["content"])["source_dependencies"]
    )
    assert attempts[1]["input"]["schema_errors"]
    assert attempts[1]["input"]["base_projection"]["selected_source_families"] == [
        "TASK",
        "CALENDAR",
    ]


def test_empty_upstream_selection__skips_model_without_forcing_a_family(tmp_path: Path) -> None:
    candidate, projection, prompt, schema = _setup(tmp_path, [])
    result = candidate.infer("LOCAL_GPU", prompt, projection, schema)
    assert all(
        item["dependency"] == "SOURCE_NOT_REQUIRED"
        for item in result.structured_output["source_dependencies"]
    )
    assert (result.input_tokens, result.output_tokens, result.latency_ms) == (0, 0, 0)
    assert candidate.cached_response_count == 1
