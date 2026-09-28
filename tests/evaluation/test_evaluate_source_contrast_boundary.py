"""V44 sealed one-call comparison and baseline lineage; no real HTTP or model."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest
from scripts import evaluate_source_contrast_boundary as runner
from tests.evaluation.test_evaluate_source_membership_boundary import (  # noqa: F401
    frozen,
    frozen_concise_source,
    frozen_source,
    presence_plan,
)

from google_work_agent.application.agents.request_understanding.identify_source_dependencies import (  # noqa: E501
    build_source_dependency_candidates,
)
from google_work_agent.application.tool_registry.load_signed_tool_registry import (
    load_development_tool_registry,
)


def _negative_source(payload: dict[str, Any]) -> str:
    projection = json.loads(payload["prompt"])["input"]
    return json.dumps(
        {
            "source_dependencies": [
                {"resource_type": c["resource_type"], "dependency": "SOURCE_NOT_REQUIRED"}
                for c in projection["source_candidates"]
            ],
        }
    )


@pytest.fixture
def contrast_plan(
    membership_plan: dict[str, Any],  # noqa: F811 - imported fixture injection
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> dict[str, Any]:
    # The examples use the actual closed ten-Resource catalog. Expand the old
    # two-Resource fake fixture through the same Product builders, without
    # changing its requests, model/runtime, or creating a second Schema fixture.
    core_path = Path(membership_plan["baseline_path"])
    core_raw = runner.previous._read(core_path)
    catalog = list(build_source_dependency_candidates(load_development_tool_registry()))
    for case in core_raw["binding"]["cases"]:
        projection = deepcopy(case["source_call"]["input"])
        projection["source_candidates"] = deepcopy(catalog)
        call, payload = runner.previous._source_call(projection, case["source_call"])
        case["source_call"].update(call)
        case["payload"] = payload
        row = next(
            c
            for c in core_raw["results"]
            if c["case_id"] == case["case_id"] and c["arm"] == "schema_constrained"
        )
        content = _negative_source(payload)
        row.update(
            wire_sha256=runner.object_hash(payload),
            input_sha256=runner.object_hash(projection),
            content=content,
            validation=runner.existing.validate_response(content, case),
        )
    runner.write_json(core_path, core_raw)
    monkeypatch.setattr(runner.previous, "BASELINE_SHA256", runner.existing.file_hash(core_path))
    membership_plan = runner.previous.make_plan(membership_plan["model"], baseline_path=core_path)
    calls = []
    for case in membership_plan["cases"]:
        if case["group"] != "synthetic":
            continue
        payload = deepcopy(case["payload"])
        content = _negative_source(payload)
        calls.append(
            {
                "case_id": case["case_id"],
                "group": "synthetic",
                "arm": "baseline",
                "stage": "baseline",
                "state": "RETURNED",
                "new_call": True,
                "wire_request_count": 1,
                "payload": payload,
                "wire_sha256": runner.object_hash(payload),
                "input_sha256": runner.object_hash(case["source_call"]["input"]),
                "content": content,
                "model": payload["model"],
                "done": True,
                "input_tokens": 10,
                "output_tokens": 3,
                "latency_ms": 20,
                "validation": runner.existing.validate_response(content, case),
            }
        )
    # These candidate observations are deliberately unusable as baseline data.
    calls += [
        {"case_id": "UNUSED", "arm": "membership_details", "content": "DO_NOT_REUSE"}
        for _ in range(13)
    ]
    path = tmp_path / "v43-control-baseline.json"
    runner.write_json(
        path,
        {
            "binding": membership_plan,
            "completed": True,
            "actual_http_calls": 15,
            "calls": calls,
        },
    )
    monkeypatch.setattr(runner, "CONTROL_BASELINE_SHA256", runner.existing.file_hash(path))
    monkeypatch.setattr(runner, "RESULTS", tmp_path / "results")
    monkeypatch.setattr(runner, "head", lambda: "fixed-v44-head")
    return runner.make_plan(
        membership_plan["model"],
        baseline_path=Path(membership_plan["baseline_path"]),
        control_baseline_path=path,
    )


def test_plan_reuses_seven_baselines_and_changes_only_examples_artifact(
    contrast_plan: dict[str, Any],
) -> None:
    plan = contrast_plan
    assert plan["policy"]["max_http_generation_calls"] == 7
    assert plan["policy"]["reused_baseline_calls"] == 7
    assert len(plan["cases"]) == len(plan["execution_order"]) == 7
    assert plan["execution_order"] == [
        *runner.previous.CORE_IDS,
        *runner.previous.CONTROL_IDS,
    ]
    assert plan["semantic_verdict"] == "UNREVIEWED"
    assert plan["business_success"] == "NOT_EVALUATED"
    assert plan["baseline_reuse_limit"] == "NONCONTEMPORANEOUS_LATENCY_NOT_CAUSAL"
    for case in plan["cases"]:
        original, actual = case["payload"], case["candidate_payload"]
        before, after = json.loads(original["prompt"]), json.loads(actual["prompt"])
        assert after["input"] == before["input"] == case["source_call"]["input"]
        assert after["output_schema"] == before["output_schema"] == actual["format"]
        assert original["format"] == actual["format"]
        assert actual["options"] == original["options"]
        assert "presence_penalty" not in actual["options"]
        assert actual["think"] is False and actual["stream"] is False
        assert after["prompt_ref"]["prompt_id"] == before["prompt_ref"]["prompt_id"]
        assert after["prompt_ref"]["content_hash"] != before["prompt_ref"]["content_hash"]
        assert not {"review", "fixture_binding", "case_id", "expected"} & after["input"].keys()
        assert "membership_payload" not in case
        assert case["candidate_wire_sha256"] == runner.object_hash(actual)
        baseline = case["baseline"]
        assert baseline["new_call"] is False
        assert baseline["content"] not in {"DO_NOT_REUSE", "UNUSED_BAD_ARM"}
        assert baseline["origin_raw_sha256"] == runner.existing.file_hash(
            Path(baseline["origin_path"])
        )
    expected_files = {
        "scripts/evaluate_source_contrast_boundary.py",
        "scripts/ru_source_contrast_candidate.py",
        "evaluation/prompt_candidates/ru-source-contrast-v44/examples.json",
        "docs/canonical/15-agent-capability-failure-prompt-contract.md",
    }
    assert expected_files <= plan["source_hashes"].keys()


def test_exactly_seven_new_calls_preserve_raw_firsts_and_separate_group_metrics(
    contrast_plan: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output = runner.RESULTS / "trial"
    observed = []

    def post(**kwargs: Any) -> dict[str, Any]:
        assert kwargs["endpoint"] == runner.existing.OLLAMA_FIXED_LOOPBACK_ENDPOINT
        assert kwargs["path"] == "/api/generate"
        assert kwargs["timeout_seconds"] == 180
        saved = runner.previous._read(output / "raw.json")
        row = saved["calls"][-1]
        assert row["state"] == "DISPATCH_STARTED"
        assert row["payload"] == kwargs["payload"]
        observed.append(deepcopy(kwargs["payload"]))
        return {
            "response": _negative_source(kwargs["payload"]),
            "done": True,
            "model": kwargs["payload"]["model"],
            "prompt_eval_count": 11,
            "eval_count": 7,
            "total_duration": 5_000_000,
            "thinking": "HIDDEN_REASONING_MUST_NOT_BE_SAVED",
        }

    monkeypatch.setattr(runner.existing.transport, "_post_json", post)
    raw = runner.execute_plan(contrast_plan, output, plan_sha256=runner.object_hash(contrast_plan))
    assert raw["completed"] is True
    assert raw["actual_http_calls"] == raw["reused_http_calls"] == len(observed) == 7
    assert raw["metrics_by_group"]["core"]["baseline"] == {
        "calls": 5,
        "input_tokens": 500,
        "output_tokens": 100,
        "reported_latency_ms": 150,
        "missing_usage_calls": 0,
    }
    assert raw["metrics_by_group"]["core"]["contrastive"]["output_tokens"] == 35
    assert raw["metrics_by_group"]["synthetic"]["baseline"]["output_tokens"] == 6
    assert raw["metrics_by_group"]["synthetic"]["contrastive"]["output_tokens"] == 14
    assert "HIDDEN_REASONING_MUST_NOT_BE_SAVED" not in json.dumps(raw)
    assert all(
        c["stage"] == "FIRST" and c["semantic_verdict"] == "UNREVIEWED" for c in raw["calls"]
    )
    assert all(c["business_success"] == "NOT_EVALUATED" for c in raw["calls"])
    assert all(c["validation"]["structural_result"] == "VALIDATED" for c in raw["calls"])
    before = runner.existing.file_hash(output / "raw.json")
    with pytest.raises((ValueError, FileExistsError)):
        runner.execute_plan(
            contrast_plan,
            runner.RESULTS / "duplicate",
            plan_sha256=runner.object_hash(contrast_plan),
        )
    assert len(observed) == 7 and runner.existing.file_hash(output / "raw.json") == before


@pytest.mark.parametrize("failure", ["fence", "missing_resource", "timeout"])
def test_failed_first_is_preserved_without_retry_repair_or_codec(
    contrast_plan: dict[str, Any],
    failure: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    count = 0

    def post(**kwargs: Any) -> dict[str, Any]:
        nonlocal count
        count += 1
        if failure == "timeout":
            raise TimeoutError("synthetic wire timeout")
        content = (
            "```json\n" + _negative_source(kwargs["payload"]) + "\n```"
            if failure == "fence"
            else '{"source_dependencies":[]}'
        )
        return {"response": content}

    monkeypatch.setattr(runner.existing.transport, "_post_json", post)
    raw = runner.execute_plan(
        contrast_plan,
        runner.RESULTS / failure,
        plan_sha256=runner.object_hash(contrast_plan),
    )
    assert count == raw["actual_http_calls"] == 7
    if failure == "timeout":
        assert all(
            c["state"] == "ERROR" and c["error_type"] == "TimeoutError" for c in raw["calls"]
        )
    else:
        assert all(c["state"] == "RETURNED" for c in raw["calls"])
        assert all(c["validation"]["structural_result"] != "VALIDATED" for c in raw["calls"])
        if failure == "fence":
            assert all(c["content"].startswith("```json") for c in raw["calls"])
            assert all(c["validation"]["structural_result"] == "INVALID_JSON" for c in raw["calls"])
    assert raw["semantic_verdict"] == "UNREVIEWED"


def test_interruption_keeps_partial_trial_and_exclusive_claim(
    contrast_plan: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def interrupted(**kwargs: Any) -> Any:
        raise KeyboardInterrupt("synthetic process interruption")

    monkeypatch.setattr(runner.existing.transport, "_post_json", interrupted)
    output = runner.RESULTS / "interrupted"
    with pytest.raises(KeyboardInterrupt):
        runner.execute_plan(contrast_plan, output, plan_sha256=runner.object_hash(contrast_plan))
    partial = runner.previous._read(output / "raw.json")
    assert partial["completed"] is False and len(partial["calls"]) == 1
    assert partial["calls"][0]["state"] == "DISPATCH_STARTED"
    assert "wall_latency_ms" in partial["calls"][0]
    with pytest.raises(FileExistsError):
        runner.execute_plan(
            contrast_plan,
            runner.RESULTS / "restart",
            plan_sha256=runner.object_hash(contrast_plan),
        )


@pytest.mark.parametrize(
    "drift",
    [
        "head",
        "runtime",
        "raw_hash",
        "control_row",
        "wire",
        "validation",
        "input",
        "sealed_plan",
    ],
)
def test_hash_runtime_or_control_origin_drift_blocks_before_generation(
    contrast_plan: dict[str, Any],
    drift: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    expected = runner.object_hash(contrast_plan)
    if drift == "head":
        monkeypatch.setattr(runner, "head", lambda: "different-head")
    elif drift == "runtime":
        model = {**contrast_plan["model"], "model_digest": "different-model"}
        monkeypatch.setattr(runner.existing, "inspect_diagnostic_model", lambda mode: model)
    elif drift == "sealed_plan":
        contrast_plan["policy"]["max_http_generation_calls"] = 8
    else:
        path = Path(contrast_plan["control_baseline_path"])
        source = runner.previous._read(path)
        row = source["calls"][0]
        if drift == "raw_hash":
            source["extra"] = "changed bytes"
        elif drift == "control_row":
            source["calls"].append(deepcopy(row))
        elif drift == "wire":
            row["payload"]["options"]["temperature"] = 0.0
        elif drift == "validation":
            row["content"] = "{}"
        else:
            row["input_sha256"] = "wrong-input"
        runner.write_json(path, source)
        if drift != "raw_hash":
            # Also exercise each row-level gate independently of its outer file hash.
            monkeypatch.setattr(runner, "CONTROL_BASELINE_SHA256", runner.existing.file_hash(path))

    def forbidden(**kwargs: Any) -> Any:
        raise AssertionError("drift must not dispatch")

    monkeypatch.setattr(runner.existing.transport, "_post_json", forbidden)
    with pytest.raises(ValueError):
        runner.execute_plan(contrast_plan, runner.RESULTS / "drift", plan_sha256=expected)


def test_controls_metadata_cannot_enter_prompt_input(contrast_plan: dict[str, Any]) -> None:
    for case in contrast_plan["cases"]:
        if case["group"] != "synthetic":
            continue
        actual = json.loads(case["candidate_payload"]["prompt"])["input"]
        assert set(actual) == runner.previous.INPUT_KEYS
        assert case["control_definition"]["review"] not in actual.values()
        assert case["control_definition"]["fixture_binding"] not in actual.values()
        assert case["provider_fixture_claim"] is False
