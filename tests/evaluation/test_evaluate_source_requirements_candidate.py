"""Source owner comparison registration/fake-wire checks; no real model or Provider."""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from dataclasses import asdict, replace
from pathlib import Path
from typing import Any

import pytest
from evaluation.dataset_v8 import load_cases
from scripts import evaluate_source_requirements_candidate as runner
from scripts.ru_observation import object_hash

from google_work_agent.adapters.llm.ollama import transport
from google_work_agent.application.prompt_runtime.prompt_registry import PromptRegistry
from google_work_agent.application.tool_registry.load_signed_tool_registry import (
    load_development_tool_registry,
)


@pytest.fixture
def registry() -> PromptRegistry:
    return PromptRegistry()


def _synthetic() -> list[dict[str, Any]]:
    candidates = runner.source_ops.build_source_dependency_candidates(
        load_development_tool_registry()
    )
    return runner.synthetic_cases([dict(candidate) for candidate in candidates])


def _candidate_output() -> dict[str, Any]:
    return {
        "source_dependencies": [
            {
                "resource_type": source["resource_type"],
                "dependency": "SOURCE_REQUIRED",
                "requirements": [
                    {
                        "required_information": ["message_history"],
                        "target_scope": "SINGULAR",
                        "work_unit_ids": ["work-1"],
                    },
                    {
                        "required_information": ["subject"],
                        "target_scope": "CRITERIA",
                        "work_unit_ids": ["work-2"],
                    },
                ],
            }
            if source["resource_type"] == "GMAIL_THREAD"
            else {"resource_type": source["resource_type"], "dependency": "SOURCE_NOT_REQUIRED"}
            for source in _synthetic()[0]["input"]["source_candidates"]
        ]
    }


def _prepared_case(registry: PromptRegistry) -> dict[str, Any]:
    case = _synthetic()[0]
    product_ref = registry.lookup_for_evaluation(runner.PROMPT_ID)
    candidate_ref = replace(
        product_ref,
        prompt_version="source-requirements-v1-evaluation",
        output_schema_version=runner.CANDIDATE_SCHEMA_VERSION,
        content_hash=hashlib.sha256(
            runner.candidate_source_text(registry.source_text(runner.PROMPT_ID)).encode()
        ).hexdigest(),
    )
    case["arms"] = {
        arm: {
            "input": deepcopy(case["input"]),
            "schema": asdict(schema),
            "prompt_ref": asdict(product_ref if arm == "baseline" else candidate_ref),
            "new_call": True,
        }
        for arm, schema in runner._schemas(case["input"], False).items()
    }
    return case


def _baseline_document(registry: PromptRegistry) -> dict[str, Any]:
    canonical = load_cases()
    controls = []
    for case_id in runner.CONTROL_IDS:
        projection = deepcopy(_synthetic()[0]["input"])
        request = canonical[case_id].raw["canonical_user_prompt"]
        projection["user_request"] = request
        projection["goal_candidate"]["goal"] = request
        projection["requested_work"] = {
            "work_units": [
                {
                    "unit_id": "work-1",
                    "request_provenance": [
                        {
                            "source": "USER_REQUEST",
                            "source_text": request,
                            "start_offset": 0,
                            "end_offset": len(request),
                        }
                    ],
                }
            ],
            "work_relations": [],
        }
        output = {
            "source_dependencies": [
                {"resource_type": source["resource_type"], "dependency": "SOURCE_NOT_REQUIRED"}
                for source in projection["source_candidates"]
            ]
        }
        schema = runner._schemas(projection, False)["baseline"]
        first = {
            "prompt_id": runner.PROMPT_ID,
            "model": runner.MODEL_ID,
            "temperature": 0.05,
            "seed": 20260923,
            "timeout_seconds": 180,
            "input": projection,
            "input_sha256": object_hash(projection),
            "schema_sha256": object_hash(schema.json_schema),
            "instruction_sha256": hashlib.sha256(
                runner.owner_instruction(projection, "baseline", registry).encode()
            ).hexdigest(),
            "content": json.dumps(output),
            "input_tokens": 10,
            "output_tokens": 20,
        }
        controls.append({"case_id": case_id, "transport_calls": [first], "atomic": []})
    return {
        "binding": {
            "model_id": runner.MODEL_ID,
            "model_digest": "TEST_ONLY_NOT_EXECUTED",
            "think": False,
            "num_ctx": 16384,
            "dataset_sha256": runner.normalized_sha256(runner.DEFAULT_DATASET_PATH),
            "fixture_sha256": runner.normalized_sha256(runner.DEFAULT_PROVIDER_FIXTURE_PATH),
        },
        "cases": controls,
    }


def _write_baseline(tmp_path: Path, document: Any, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(runner, "ROOT", tmp_path)
    path = tmp_path / "evaluation/results/frozen/raw.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(document, ensure_ascii=False), encoding="utf-8")
    return path


def test_frozen_reuse_preserves_real_owner_input_and_all_attempts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, registry: PromptRegistry
) -> None:
    original = _baseline_document(registry)
    path = _write_baseline(tmp_path, original, monkeypatch)
    controls, binding = runner.load_frozen_controls(path, registry)
    assert binding == original["binding"]
    assert len(controls) == 3
    for case, row in zip(controls, original["cases"], strict=True):
        assert case["input"] == row["transport_calls"][0]["input"]
        assert case["baseline_record"] == row
        assert case["baseline_record_sha256"] == object_hash(row)
        assert case["baseline_current_gate"] == "PASS_STRUCTURE_ONLY_SEMANTIC_REVIEW_PENDING"


@pytest.mark.parametrize(
    "field,value",
    [
        ("temperature", 0.0),
        ("seed", 123),
        ("model", "different"),
        ("input_sha256", "changed"),
        ("schema_sha256", "changed"),
        ("instruction_sha256", "changed"),
    ],
)
def test_frozen_reuse_rejects_actual_runtime_and_artifact_mismatch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    registry: PromptRegistry,
    field: str,
    value: Any,
) -> None:
    original = _baseline_document(registry)
    original["cases"][0]["transport_calls"][0][field] = value
    path = _write_baseline(tmp_path, original, monkeypatch)
    with pytest.raises(ValueError, match="changed|reproduced"):
        runner.load_frozen_controls(path, registry)


def test_frozen_reuse_rejects_semantic_rerun_as_schema_repair(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, registry: PromptRegistry
) -> None:
    original = _baseline_document(registry)
    original["cases"][0]["transport_calls"] *= 2
    path = _write_baseline(tmp_path, original, monkeypatch)
    with pytest.raises(ValueError, match="bounded repair"):
        runner.load_frozen_controls(path, registry)


def test_historical_repair_and_current_guard_outcome_are_kept_separate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, registry: PromptRegistry
) -> None:
    original = _baseline_document(registry)
    row = original["cases"][1]
    row["status"] = "SOURCE_RETURNED"
    first_call = row["transport_calls"][0]
    repaired = json.loads(first_call["content"])
    first_raw = deepcopy(repaired)
    first_raw["source_dependencies"].pop()
    first_raw["source_dependencies"][0].update(
        dependency="SOURCE_REQUIRED",
        required_information=["message_history"],
        target_scope="SINGULAR",
        work_unit_ids=["work-1"],
    )
    schema = runner._schemas(first_call["input"], False)["baseline"]
    _, errors = runner._parse(first_raw, schema)
    first_call["content"] = json.dumps(first_raw)
    repair_input = runner._repair_input(first_call["input"], first_raw, errors, registry)
    repair_call = {
        **deepcopy(first_call),
        "input": repair_input,
        "input_sha256": object_hash(repair_input),
        "content": json.dumps(repaired),
        "instruction_sha256": hashlib.sha256(
            runner.owner_instruction(repair_input, "baseline", registry).encode()
        ).hexdigest(),
    }
    row["transport_calls"].append(repair_call)
    row["source_output"] = repaired
    path = _write_baseline(tmp_path, original, monkeypatch)
    cases, _ = runner.load_frozen_controls(path, registry)
    case = cases[1]
    assert case["baseline_record"] == row
    assert case["baseline_record"]["status"] == "SOURCE_RETURNED"
    assert case["baseline_current_gate"] == "FAIL"
    assert case["baseline_revalidation"][1]["current_repair_guard_changes"]
    assert "current_observation" not in case["baseline_revalidation"][1]
    assert case["baseline_revalidation"][0]["raw_output"] == first_raw


def test_preregistration_locks_seven_first_calls_and_isolates_gold(
    monkeypatch: pytest.MonkeyPatch, registry: PromptRegistry
) -> None:
    controls = []
    for case_id in runner.CONTROL_IDS:
        control = deepcopy(_synthetic()[0])
        control.update(
            case_id=case_id,
            origin="RECORDED_PRODUCT_SOURCE_OWNER_INPUT",
            baseline_record={"transport_calls": [{}]},
            baseline_revalidation=[],
        )
        controls.append(control)
    monkeypatch.setattr(
        runner,
        "load_frozen_controls",
        lambda path, registry: (deepcopy(controls), {"model_digest": "TEST_ONLY_NOT_EXECUTED"}),
    )
    original_hash = runner.normalized_sha256
    monkeypatch.setattr(
        runner,
        "normalized_sha256",
        lambda path: (
            "TEST_BASELINE_HASH" if path == runner.DEFAULT_BASELINE_RAW else original_hash(path)
        ),
    )
    plan = runner.make_plan()
    assert len(plan["cases"]) == 5
    assert plan["max_new_first_calls"] == 7
    assert plan["max_new_calls_with_schema_repair"] == 14
    assert plan["runtime_policy"]["temperature"] == 0.05
    assert plan["runtime_policy"]["semantic_revision_budget"] == 0
    assert plan["runtime_policy"]["rerun_to_pass"] == 0
    assert plan["model_evaluation"] == "NOT_RUN"
    assert sum(arm["new_call"] for case in plan["cases"] for arm in case["arms"].values()) == 7
    assert "scripts/ru_observation.py" in plan["source_hashes"]
    for case in plan["cases"]:
        assert case["arms"]["baseline"]["input"] == case["arms"]["candidate"]["input"]
        for arm in ("baseline", "candidate"):
            wire_input = json.dumps(case["arms"][arm]["input"])
            assert "evaluation_authority" not in wire_input
            assert "evaluation_gold" not in wire_input
            assert "independent_outputs" not in wire_input
            assert "expected" not in wire_input


def test_prompt_only_changes_required_payload_wording_not_input_or_responsibility(
    registry: PromptRegistry,
) -> None:
    case = _synthetic()[0]
    source = registry.source_text(runner.PROMPT_ID)
    candidate = runner.candidate_source_text(source)
    for before, after in reversed(runner._SHAPE_REPLACEMENTS):
        assert candidate.count(after) == 1
        candidate = candidate.replace(after, before, 1)
    assert candidate == source
    baseline = runner.owner_instruction(case["input"], "baseline", registry)
    changed = runner.owner_instruction(case["input"], "candidate", registry)
    marker = "Allowed current-Run input projection (JSON):\n"
    assert baseline.partition(marker)[2] == changed.partition(marker)[2]
    assert "Output effect, Tool, Query, 정책, 실행 계획은 판정하지 않는다." in changed
    with pytest.raises(ValueError, match="wording changed"):
        runner.candidate_source_text("not the original Product source")


def test_same_resource_binding_observation_distinguishes_cross_product_without_fake_pass() -> None:
    case = _synthetic()[0]
    raw = _candidate_output()
    result = runner.observed_semantics(raw, case, "candidate")
    assert result["structural_validation"] == "PASS"
    assert result["semantic_evaluation"] == "PENDING_EVIDENCE_REVIEW"
    assert result["business_success"] == "NOT_EVALUATED"
    works = result["work_binding_projection"]
    assert works["work-1"][0]["required_information"] == ["message_history"]
    assert works["work-1"][0]["target_scope"] == "SINGULAR"
    assert works["work-2"][0]["required_information"] == ["subject"]
    baseline = deepcopy(raw)
    item = baseline["source_dependencies"][0]
    item.pop("requirements")
    item.update(
        required_information=["message_history", "subject"],
        target_scope="CRITERIA",
        work_unit_ids=["work-1", "work-2"],
    )
    observed = runner.observed_semantics(baseline, case, "baseline")
    assert observed["work_binding_projection"]["work-1"][0]["required_information"] == [
        "message_history",
        "subject",
    ]
    assert observed["semantic_evaluation"] == "PENDING_EVIDENCE_REVIEW"


def _fake_wire(monkeypatch: pytest.MonkeyPatch, outputs: list[Any]) -> list[dict[str, Any]]:
    calls = []

    def post(**kwargs: Any) -> dict[str, Any]:
        calls.append(deepcopy(kwargs))
        value = outputs.pop(0)
        if isinstance(value, Exception):
            raise value
        return {
            "response": json.dumps(value),
            "model": runner.MODEL_ID,
            "prompt_eval_count": 30,
            "eval_count": 20,
            "total_duration": 1000000,
        }

    monkeypatch.setattr(transport, "_post_json", post)
    return calls


def test_fake_wire_actual_options_match_source_005_and_observe_first_result(
    monkeypatch: pytest.MonkeyPatch, registry: PromptRegistry
) -> None:
    output = _candidate_output()
    wire = _fake_wire(monkeypatch, [output])
    result = runner.run_arm(
        _prepared_case(registry), "candidate", transport.OllamaHTTPClient(), registry
    )
    assert len(wire) == 1
    assert wire[0]["payload"]["options"] == {
        "num_ctx": 16384,
        "temperature": 0.05,
        "seed": 20260923,
    }
    assert wire[0]["payload"]["think"] is False
    assert wire[0]["timeout_seconds"] == 180
    assert result["attempts"][0]["raw_output"] == output
    assert result["metrics"]["calls"] == 1
    assert result["final"]["semantic_evaluation"] == "PENDING_EVIDENCE_REVIEW"


def test_schema_repair_once_retains_first_output_and_cannot_mutate_valid_requirement(
    monkeypatch: pytest.MonkeyPatch, registry: PromptRegistry
) -> None:
    first = _candidate_output()
    del first["source_dependencies"][0]["requirements"][1]["target_scope"]
    repaired = _candidate_output()
    repaired["source_dependencies"][0]["requirements"][0]["required_information"] = ["subject"]
    wire = _fake_wire(monkeypatch, [first, repaired])
    result = runner.run_arm(
        _prepared_case(registry), "candidate", transport.OllamaHTTPClient(), registry
    )
    assert len(wire) == 2
    assert result["attempts"][0]["raw_output"] == first
    assert result["attempts"][1]["out_of_scope_repair_changes"]
    assert result["final"]["structural_validation"] == "FAIL"
    assert "unaffected" in result["final"]["error"]


@pytest.mark.parametrize("outputs", [[{}, {}], [TimeoutError("test timeout")]])
def test_no_rerun_or_transport_retry_after_terminal_failure(
    monkeypatch: pytest.MonkeyPatch, registry: PromptRegistry, outputs: list[Any]
) -> None:
    expected = len(outputs)
    wire = _fake_wire(monkeypatch, list(outputs))
    result = runner.run_arm(
        _prepared_case(registry), "candidate", transport.OllamaHTTPClient(), registry
    )
    assert len(wire) == expected
    assert result["final"]["structural_validation"] == "FAIL"


def test_frozen_baseline_cannot_be_executed_again(registry: PromptRegistry) -> None:
    case = _prepared_case(registry)
    case["arms"]["baseline"]["new_call"] = False
    with pytest.raises(ValueError, match="another baseline call is forbidden"):
        runner.run_arm(case, "baseline", transport.OllamaHTTPClient(), registry)


def test_semantic_text_validation_failure_does_not_trigger_repair_or_revision(
    monkeypatch: pytest.MonkeyPatch, registry: PromptRegistry
) -> None:
    output = _candidate_output()
    output["source_dependencies"][0]["requirements"][0]["required_information"] = [" []{} "]
    wire = _fake_wire(monkeypatch, [output])
    result = runner.run_arm(
        _prepared_case(registry), "candidate", transport.OllamaHTTPClient(), registry
    )
    assert len(wire) == 1
    assert result["final"]["structural_validation"] == "FAIL"
