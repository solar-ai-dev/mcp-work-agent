"""Format-only wire invariants and exact Product validators; HTTP is always fake."""

from __future__ import annotations

import json
from copy import deepcopy
from dataclasses import asdict
from pathlib import Path
from typing import Any

import pytest
from scripts import evaluate_output_format_ablation as runner

from google_work_agent.application.prompt_runtime.assemble_prompt import assemble_prompt
from google_work_agent.application.prompt_runtime.prompt_registry import EVALUATION, PromptRegistry


def _dump(path: Path, value: Any) -> None:
    runner.write_json(path, value, exclusive=True)


@pytest.fixture
def frozen(tmp_path: Path) -> tuple[Path, dict[str, Any]]:
    registry = PromptRegistry()
    ref = registry.lookup_for_evaluation(runner.PROMPT_ID)
    canonical = runner.load_cases()
    root = tmp_path / "source"
    model = {"model_id": "qwen3.5:9b", "model_digest": "fake-test-digest"}
    source_plan: dict[str, Any] = {
        "model": {"id": model["model_id"], "digest": model["model_digest"]},
        "dataset_sha256": runner.file_hash(runner.DEFAULT_DATASET_PATH),
        "snapshot_sha256": runner.file_hash(runner.DEFAULT_PROVIDER_FIXTURE_PATH),
        "cases": [],
    }
    pending = []
    for case_id, arm in runner.SOURCES:
        request = canonical[case_id].raw["canonical_user_prompt"]
        binding = {
            "case_id": case_id,
            "case_sha256": runner.object_hash(canonical[case_id].raw),
            "effective_reference_time_ms": 1_000,
            "fault_profile": None,
        }
        source_plan["cases"].append(binding)
        projection = {
            "user_request": request,
            "selected_resource_refs": [],
            "run_reference_time": {"now_utc": "2026-09-28T00:00:00Z"},
            "requested_work": {
                "work_units": [
                    {
                        "unit_id": "work-1",
                        "request_provenance": [
                            {
                                "source": "USER_REQUEST",
                                "start_offset": 0,
                                "end_offset": len(request),
                                "source_text": request,
                            }
                        ],
                    }
                ],
                "work_relations": [],
            },
            "goal_candidate": {"goal": request},
            "output_candidates": [
                {
                    "resource_type": "TASK",
                    "allowed_output_effects": ["CREATE", "UPDATE"],
                }
            ],
            "effect_prohibitions": [
                {"effect": "CREATE", "prohibition": "FORBIDDEN", "work_unit_ids": ["work-1"]}
            ],
        }
        schema = runner.build_output_responsibility_output_schema(
            projection["output_candidates"], work_unit_ids=["work-1"]
        )
        options = {"num_ctx": 16_384, "temperature": 0.0, "seed": 20260923}
        # An independent historical wire fixture; reconstruct_payload must use
        # actual Product transport and match it, not trust this fixture blindly.
        payload = {
            "model": model["model_id"],
            "system": assemble_prompt(
                ref, projection, registry=registry, execution_scope=EVALUATION
            ),
            "prompt": json.dumps(
                {
                    "prompt_ref": {
                        "prompt_id": ref.prompt_id,
                        "prompt_version": ref.prompt_version,
                        "content_hash": ref.content_hash,
                    },
                    "input": projection,
                    "output_schema": schema.json_schema,
                },
                sort_keys=True,
                ensure_ascii=False,
            ),
            "stream": False,
            "think": False,
            "format": schema.json_schema,
            "options": options,
        }
        call = {
            "call_index": 5,
            "prompt_id": runner.PROMPT_ID,
            "prompt_ref": asdict(ref),
            "input": projection,
            "input_sha256": runner.object_hash(projection),
            "runtime_policy": {
                "local_timeout_seconds": 180,
                "sampling_temperature": 0.0,
                "sampling_seed": 20260923,
            },
            "temperature": 0.0,
            "seed": 20260923,
            "model": model["model_id"],
            "state": "RETURNED",
            "wire_request_count": 1,
            "output_schema": schema.json_schema,
            "wire_path": "/api/generate",
            "wire_options": options,
            "wire_think": False,
            "wire_sha256": runner.object_hash(payload),
            "content": '{"output_responsibilities":[]}',
        }
        pending.append((case_id, arm, binding, call))
    _dump(root / "plan.json", source_plan)
    for case_id, arm, binding, call in pending:
        _dump(root / case_id / arm / "calls.json", {"calls": [call]})
        _dump(
            root / case_id / arm / "raw.json",
            {
                "case_binding": binding,
                "arm": arm,
                "plan_sha256": runner.object_hash(source_plan),
            },
        )
    return root, model


def test_plan_reconstructs_product_payload_and_removes_only_top_level_format(
    frozen: tuple[Path, dict[str, Any]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, model = frozen
    before = {path: runner.file_hash(path) for path in root.rglob("*.json")}

    def forbidden(**_kwargs: Any) -> Any:
        raise AssertionError("dry plan must not send HTTP")

    monkeypatch.setattr(runner.transport, "_post_json", forbidden)
    plan = runner.make_plan(model, source_root=root)
    assert len(plan["execution_order"]) == 6
    assert len({(row["case_id"], row["arm"]) for row in plan["execution_order"]}) == 6
    assert plan["policy"]["schema_repairs"] == plan["policy"]["http_retries"] == 0
    for case in plan["cases"]:
        original = runner.payload_for(case, "schema_constrained")
        candidate = runner.payload_for(case, "format_omitted")
        assert set(original) - set(candidate) == {"format"}
        assert candidate == {k: v for k, v in original.items() if k != "format"}
        assert runner.object_hash(original) == case["source_call"]["wire_sha256"]
        assert runner.object_hash(candidate) == case["candidate_wire_sha256"]
        assert json.loads(candidate["prompt"])["output_schema"] == original["format"]
        assert json.loads(candidate["prompt"])["input"] == case["source_call"]["input"]
    assert before == {path: runner.file_hash(path) for path in root.rglob("*.json")}


@pytest.mark.parametrize("field", ["wire_sha256", "input_sha256", "wire_think", "wire_options"])
def test_reconstruction_fails_closed_on_historical_wire_drift(
    frozen: tuple[Path, dict[str, Any]],
    field: str,
) -> None:
    root, model = frozen
    case = runner.make_plan(model, source_root=root)["cases"][0]
    call = deepcopy(case["source_call"])
    call[field] = None
    with pytest.raises(ValueError):
        runner.reconstruct_payload(call)


def test_changed_model_and_source_case_binding_reject_before_generation(
    frozen: tuple[Path, dict[str, Any]],
) -> None:
    root, model = frozen
    with pytest.raises(ValueError, match="digest"):
        runner.make_plan({**model, "model_digest": "changed"}, source_root=root)
    path = root / runner.SOURCES[0][0] / runner.SOURCES[0][1] / "raw.json"
    value = json.loads(path.read_text(encoding="utf-8"))
    value["case_binding"]["case_sha256"] = "changed"
    runner.write_json(path, value)
    with pytest.raises(ValueError, match="provenance"):
        runner.make_plan(model, source_root=root)


@pytest.mark.parametrize("arm", runner.ARMS)
@pytest.mark.parametrize(
    ("content", "expected"),
    [
        ('{"output_responsibilities":[]}', "VALIDATED"),
        ('```json\n{"output_responsibilities":[]}\n```', "INVALID_JSON"),
        ('{"output_responsibilities":[{"resource_type":"TASK"}]}', "INVALID_SCHEMA"),
        (
            '{"output_responsibilities":[{"resource_type":"TASK","effect":"CREATE",'
            '"work_unit_ids":["work-1"]}]}',
            "OWNER_REJECTED",
        ),
    ],
)
def test_single_http_first_uses_original_schema_and_owner_without_repair(
    frozen: tuple[Path, dict[str, Any]],
    monkeypatch: pytest.MonkeyPatch,
    arm: str,
    content: str,
    expected: str,
) -> None:
    root, model = frozen
    case = runner.make_plan(model, source_root=root)["cases"][0]
    # This synthetic owner fixture carries its prohibition in the actual wire;
    # the same owner validates it even without constrained decoding.
    calls, snapshots = [], []

    def post(**kwargs: Any) -> dict[str, Any]:
        calls.append(kwargs)
        assert snapshots[-1]["state"] == "DISPATCH_STARTED"
        return {
            "response": content,
            "model": model["model_id"],
            "done": True,
            "prompt_eval_count": 123,
            "eval_count": 9,
            "total_duration": 25_000_000,
            "thinking": "NEVER PERSIST THIS HIDDEN TEXT",
        }

    monkeypatch.setattr(runner.transport, "_post_json", post)
    record = runner.run_arm(case, arm, persist=lambda row: snapshots.append(deepcopy(row)))
    assert len(calls) == 1
    assert calls[0]["path"] == "/api/generate" and calls[0]["timeout_seconds"] == 180
    assert calls[0]["payload"] == runner.payload_for(case, arm)
    assert record["validation"]["structural_result"] == expected
    assert record["semantic_verdict"] == "UNREVIEWED"
    assert record["content"] == content and record["output_tokens"] == 9
    assert record["schema_repairs"] == record["http_retries"] == 0
    assert record["thinking_present"] and record["thinking_characters"] > 0
    assert "NEVER PERSIST" not in json.dumps(snapshots)


@pytest.mark.parametrize("arm", runner.ARMS)
def test_timeout_is_stored_with_no_retry(
    frozen: tuple[Path, dict[str, Any]],
    monkeypatch: pytest.MonkeyPatch,
    arm: str,
) -> None:
    root, model = frozen
    case = runner.make_plan(model, source_root=root)["cases"][0]
    calls, saved = [], []

    def post(**kwargs: Any) -> Any:
        calls.append(kwargs)
        raise TimeoutError("bounded timeout")

    monkeypatch.setattr(runner.transport, "_post_json", post)
    result = runner.run_arm(case, arm, persist=lambda row: saved.append(deepcopy(row)))
    assert len(calls) == 1 and len(saved) == 2
    assert result["state"] == "ERROR" and result["error_type"] == "TimeoutError"
    assert result["wire_request_count"] == 1 and result["semantic_verdict"] == "UNREVIEWED"


def test_six_calls_sequential_incremental_persistence_and_no_overwrite_or_rerun(
    frozen: tuple[Path, dict[str, Any]],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, model = frozen
    plan = runner.make_plan(model, source_root=root)
    output = tmp_path / "results" / "trial"
    monkeypatch.setattr(runner, "RESULTS", output.parent)
    calls = []

    def post(**kwargs: Any) -> dict[str, Any]:
        saved = json.loads((output / "raw.json").read_text(encoding="utf-8"))
        assert saved["results"][-1]["state"] == "DISPATCH_STARTED"
        assert all(row["state"] == "RETURNED" for row in saved["results"][:-1])
        calls.append(kwargs)
        return {"response": '{"output_responsibilities":[]}', "eval_count": 10}

    monkeypatch.setattr(runner.transport, "_post_json", post)
    result = runner.execute_plan(plan, output, plan_sha256=runner.object_hash(plan))
    assert len(calls) == result["actual_http_calls"] == 6 and result["completed"]
    assert [row["case_id"] for row in result["results"]] == [
        item["case_id"] for item in plan["execution_order"]
    ]
    assert all(row["semantic_verdict"] == "UNREVIEWED" for row in result["results"])
    assert result["metrics_by_arm"]["schema_constrained"]["output_tokens"] == 30
    with pytest.raises(ValueError, match="prior partial/failed"):
        runner.execute_plan(plan, output, plan_sha256=runner.object_hash(plan))
    with pytest.raises(FileExistsError):
        runner.execute_plan(plan, output.parent / "another", plan_sha256=runner.object_hash(plan))
    assert len(calls) == 6


def test_cli_drift_rejects_before_http(
    frozen: tuple[Path, dict[str, Any]],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, model = frozen
    plan = runner.make_plan(model, source_root=root)
    saved = tmp_path / "plan.json"
    _dump(saved, plan)
    monkeypatch.setattr(runner, "RESULTS", tmp_path)
    monkeypatch.setattr(runner, "inspect_model", lambda _: model)
    monkeypatch.setattr(runner, "make_plan", lambda _, **_kwargs: {**plan, "head_sha": "changed"})
    monkeypatch.setattr(
        "sys.argv",
        [
            "runner",
            "--result-dir",
            str(tmp_path / "output"),
            "--execute-plan",
            str(saved),
            "--expected-plan-sha256",
            runner.object_hash(plan),
        ],
    )
    with pytest.raises(ValueError, match="binding changed"):
        runner.main()


def test_extra_trial_and_validator_input_drift_reject_before_dispatch(
    frozen: tuple[Path, dict[str, Any]],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, model = frozen
    plan = runner.make_plan(model, source_root=root)
    monkeypatch.setattr(runner, "RESULTS", tmp_path)
    changed = deepcopy(plan)
    changed["execution_order"].append(changed["execution_order"][0])
    with pytest.raises(ValueError, match="mode-bound one-shot"):
        runner.execute_plan(changed, tmp_path / "extra", plan_sha256=runner.object_hash(changed))
    case = plan["cases"][0]
    case["source_call"]["input"]["effect_prohibitions"] = []
    with pytest.raises(ValueError, match="validator authority"):
        runner.payload_for(case, "format_omitted")


def _write_baseline(plan: dict[str, Any], path: Path) -> None:
    rows = []
    for entry in plan["execution_order"]:
        case = next(item for item in plan["cases"] if item["case_id"] == entry["case_id"])
        content = '{"output_responsibilities":[]}'
        rows.append(
            {
                "case_id": entry["case_id"],
                "arm": entry["arm"],
                "state": "RETURNED",
                "wire_request_count": 1,
                "wire_sha256": runner.object_hash(runner.payload_for(case, entry["arm"])),
                "input_sha256": case["source_call"]["input_sha256"],
                "wire_options": case["payload"]["options"],
                "wire_think": case["payload"]["think"],
                "format_present": "format" in runner.payload_for(case, entry["arm"]),
                "schema_repairs": 0,
                "http_retries": 0,
                "input_tokens": 100,
                "output_tokens": 10,
                "latency_ms": 20,
                "content": content,
                "validation": runner.validate_response(content, case),
                "semantic_verdict": "UNREVIEWED",
            }
        )
    _dump(
        path, {"binding": plan, "results": rows, "completed": True, "actual_http_calls": len(rows)}
    )


@pytest.fixture
def json_plan(
    frozen: tuple[Path, dict[str, Any]],
    tmp_path: Path,
) -> tuple[dict[str, Any], Path]:
    root, model = frozen
    baseline = tmp_path / "baseline.json"
    _write_baseline(runner.make_plan(model, source_root=root), baseline)
    return runner.make_plan(
        model, source_root=root, candidate_mode="json", baseline_raw=baseline
    ), baseline


def test_json_mode_changes_only_format_value_and_reuses_bound_baseline(
    json_plan: tuple[dict[str, Any], Path],
) -> None:
    plan, baseline = json_plan
    assert plan["candidate_mode"] == "json"
    assert plan["policy"]["max_http_generation_calls"] == 3
    assert plan["policy"]["reused_baseline_calls"] == 3
    assert plan["arms"] == ["schema_constrained", "format_json"]
    assert [entry["arm"] for entry in plan["execution_order"]] == ["format_json"] * 3
    assert plan["reused_baseline"]["sha256"] == runner.file_hash(baseline)
    for case, reused in zip(plan["cases"], plan["reused_baseline"]["records"], strict=True):
        original = runner.payload_for(case, "schema_constrained")
        candidate = runner.payload_for(case, "format_json")
        assert candidate == {**original, "format": "json"}
        assert runner.object_hash(candidate) == case["candidate_wire_sha256"]
        assert json.loads(candidate["prompt"])["output_schema"] == original["format"]
        assert reused["new_call"] is False
        assert reused["row_sha256"] == runner.object_hash(reused["record"])
        with pytest.raises(ValueError, match="unregistered format arm"):
            runner.payload_for(case, "format_omitted")


def test_json_executes_only_three_new_calls_and_keeps_reused_usage_separate(
    json_plan: tuple[dict[str, Any], Path],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan, baseline = json_plan
    before = runner.file_hash(baseline)
    monkeypatch.setattr(runner, "RESULTS", tmp_path)
    sent = []

    def post(**kwargs: Any) -> dict[str, Any]:
        assert kwargs["payload"]["format"] == "json" and kwargs["timeout_seconds"] == 180
        sent.append(kwargs)
        return {"response": '{"output_responsibilities":[]}', "eval_count": 4}

    monkeypatch.setattr(runner.transport, "_post_json", post)
    result = runner.execute_plan(plan, tmp_path / "json-run", plan_sha256=runner.object_hash(plan))
    assert len(sent) == result["actual_http_calls"] == 3
    assert result["reused_http_calls"] == 3
    assert result["new_call_metrics"]["output_tokens"] == 12
    assert result["reused_call_metrics"]["output_tokens"] == 30
    assert all(row["new_call"] is False for row in result["reused_results"])
    assert all(row["new_call"] is True for row in result["results"])
    assert result["metrics_by_arm"]["schema_constrained"]["calls"] == 3
    assert result["metrics_by_arm"]["format_json"]["calls"] == 3
    assert runner.file_hash(baseline) == before


@pytest.mark.parametrize(
    "content,expected",
    [
        ('{"output_responsibilities":[]}', "VALIDATED"),
        ('```json\n{"output_responsibilities":[]}\n```', "INVALID_JSON"),
        ('{"output_responsibilities":[{"resource_type":"TASK"}]}', "INVALID_SCHEMA"),
        (
            '{"output_responsibilities":[{"resource_type":"TASK","effect":"CREATE",'
            '"work_unit_ids":["work-1"]}]}',
            "OWNER_REJECTED",
        ),
    ],
)
def test_json_mode_keeps_identical_strict_postvalidation_without_repair(
    json_plan: tuple[dict[str, Any], Path],
    monkeypatch: pytest.MonkeyPatch,
    content: str,
    expected: str,
) -> None:
    plan, _ = json_plan
    calls = []

    def post(**kwargs: Any) -> dict[str, Any]:
        calls.append(kwargs)
        return {"response": content}

    monkeypatch.setattr(runner.transport, "_post_json", post)
    record = runner.run_arm(plan["cases"][0], "format_json", persist=lambda _: None)
    assert len(calls) == 1 and record["validation"]["structural_result"] == expected
    assert record["content"] == content and record["semantic_verdict"] == "UNREVIEWED"
    assert record["schema_repairs"] == 0


@pytest.mark.parametrize("changed", ["wire", "code", "model", "rowhash"])
def test_json_reuse_rejects_drift_in_original_authority_before_any_new_call(
    json_plan: tuple[dict[str, Any], Path],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    changed: str,
) -> None:
    plan, path = json_plan
    monkeypatch.setattr(runner, "RESULTS", tmp_path)
    raw = json.loads(path.read_text(encoding="utf-8"))
    if changed == "wire":
        raw["results"][0]["wire_sha256"] = "changed"
    elif changed == "code":
        raw["binding"]["source_hashes"][
            "src/google_work_agent/adapters/llm/ollama/transport.py"
        ] = "changed"
    elif changed == "model":
        raw["binding"]["model"]["model_digest"] = "changed"
    else:
        raw["results"][0]["output_tokens"] += 1
    runner.write_json(path, raw)
    with pytest.raises(ValueError, match="reused baseline"):
        runner.execute_plan(plan, tmp_path / "no-run", plan_sha256=runner.object_hash(plan))
    assert not (tmp_path / "no-run").exists()


def test_json_mode_cannot_reintroduce_three_new_baseline_calls(
    json_plan: tuple[dict[str, Any], Path],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan, _ = json_plan
    monkeypatch.setattr(runner, "RESULTS", tmp_path)
    plan["execution_order"].append({"case_id": "CASE-CORE-005", "arm": "schema_constrained"})
    with pytest.raises(ValueError, match="mode-bound"):
        runner.execute_plan(plan, tmp_path / "extra", plan_sha256=runner.object_hash(plan))


@pytest.mark.parametrize(
    "prefix,suffix", [("```json\n", "\n```"), (" \t```json\r\n", "\r\n```\r\n")]
)
def test_single_json_fence_keeps_raw_strict_failure_and_uses_same_owner(
    frozen: tuple[Path, dict[str, Any]],
    prefix: str,
    suffix: str,
) -> None:
    root, model = frozen
    case = runner.make_plan(model, source_root=root)["cases"][0]
    body = '  {"output_responsibilities":[]}  '
    content = prefix + body + suffix
    assert runner.unwrap_single_json_fence(content) == body
    result = runner.validate_fenced_response(content, case)
    assert result["raw_content"] == content
    assert result["strict_validation"]["structural_result"] == "INVALID_JSON"
    assert result["candidate_validation"] == runner.validate_response(body, case)
    assert result["candidate_validation"]["structural_result"] == "VALIDATED"
    assert result["admission"] == "SINGLE_JSON_FENCE_UNWRAPPED"
    assert result["semantic_verdict"] == "UNREVIEWED" and result["model_calls"] == 0


@pytest.mark.parametrize(
    "content",
    [
        "Here is JSON:\n```json\n{}\n```",
        "```json\n{}\n```\nExplanation.",
        "```\n{}\n```",
        "```JSON\n{}\n```",
        "```javascript\n{}\n```",
        "```json \n{}\n```",
        "```json\n{}\n``",
        "```json\n{}",
        "```json\n{}\n```\n```json\n{}\n```",
        "```json\n```json\n{}\n```\n```",
        '```json\n{"text":"```"}\n```',
        "```json {} ```",
        "\ufeff```json\n{}\n```",
    ],
)
def test_fence_admission_rejects_prose_multiple_nested_truncated_and_other_tags(
    frozen: tuple[Path, dict[str, Any]],
    content: str,
) -> None:
    root, model = frozen
    case = runner.make_plan(model, source_root=root)["cases"][0]
    with pytest.raises(ValueError, match="single complete"):
        runner.unwrap_single_json_fence(content)
    result = runner.validate_fenced_response(content, case)
    assert result["admission"] == "FENCE_REJECTED"
    assert result["candidate_validation"] == result["strict_validation"]


@pytest.mark.parametrize(
    "body,status",
    [
        ('{"output_responsibilities":[]}\n{"output_responsibilities":[]}', "INVALID_JSON"),
        ('{"output_responsibilities": [', "INVALID_JSON"),
        ('{"output_responsibilities":[{"resource_type":"TASK"}]}', "INVALID_SCHEMA"),
        (
            '{"output_responsibilities":[{"resource_type":"TASK","effect":"CREATE",'
            '"work_unit_ids":["work-1"]}]}',
            "OWNER_REJECTED",
        ),
    ],
)
def test_unwrapped_duplicate_json_schema_and_prohibition_failures_are_not_repaired(
    frozen: tuple[Path, dict[str, Any]],
    body: str,
    status: str,
) -> None:
    root, model = frozen
    case = runner.make_plan(model, source_root=root)["cases"][0]
    result = runner.validate_fenced_response(f"```json\n{body}\n```", case)
    assert result["candidate_validation"]["structural_result"] == status
    assert result["strict_validation"]["structural_result"] == "INVALID_JSON"
    assert result["model_calls"] == 0 and result["semantic_verdict"] == "UNREVIEWED"


def test_plain_json_controls_are_identical_and_no_extraction_is_attempted(
    frozen: tuple[Path, dict[str, Any]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, model = frozen
    case = runner.make_plan(model, source_root=root)["cases"][0]

    def forbidden(_content: str) -> str:
        raise AssertionError("strict-valid JSON must remain unchanged")

    monkeypatch.setattr(runner, "unwrap_single_json_fence", forbidden)
    for content in ('{"output_responsibilities":[]}', '{"invalid":true}'):
        result = runner.validate_fenced_response(content, case)
        assert result["candidate_validation"] == result["strict_validation"]
        assert result["admission"] == "STRICT_JSON_UNCHANGED"


def test_offline_raw_regrade_preserves_original_failures_and_skips_reused_rows(
    frozen: tuple[Path, dict[str, Any]],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, model = frozen
    old_plan = runner.make_plan(model, source_root=root)
    old_path = tmp_path / "omitted.json"
    _write_baseline(old_plan, old_path)
    old = json.loads(old_path.read_text(encoding="utf-8"))
    for row in old["results"]:
        if row["arm"] == "format_omitted":
            row["content"] = f"```json\n{row['content']}\n```"
            case = next(case for case in old_plan["cases"] if case["case_id"] == row["case_id"])
            row["validation"] = runner.validate_response(row["content"], case)
    runner.write_json(old_path, old)
    new_plan = runner.make_plan(
        model, source_root=root, candidate_mode="json", baseline_raw=old_path
    )
    new_path = tmp_path / "json-mode.json"
    _write_baseline(new_plan, new_path)
    before = [runner.file_hash(path) for path in (old_path, new_path)]

    def forbidden(*_args: Any, **_kwargs: Any) -> Any:
        raise AssertionError("offline revalidation must not inspect or call the model")

    monkeypatch.setattr(runner, "inspect_model", forbidden)
    monkeypatch.setattr(runner.transport, "_post_json", forbidden)
    report = runner.regrade_fenced_raw([old_path, new_path])
    assert report["summary"]["strict"] == {"INVALID_JSON": 3, "VALIDATED": 3}
    assert report["summary"]["candidate"] == {"VALIDATED": 6}
    assert report["summary"]["reused_observations"] == 6
    assert all(row["historical_validation"] == row["strict_validation"] for row in report["rows"])
    assert report["model_calls"] == report["provider_calls"] == 0
    assert before == [runner.file_hash(path) for path in (old_path, new_path)]
    with pytest.raises(ValueError, match="counted twice"):
        runner.regrade_fenced_raw([old_path, old_path])


@pytest.fixture
def frozen_core5(
    frozen: tuple[Path, dict[str, Any]], tmp_path: Path
) -> tuple[Path, dict[str, Any]]:
    original_root, model = frozen
    template = json.loads(
        (original_root / "CASE-CORE-005/production/calls.json").read_text(encoding="utf-8")
    )["calls"][0]
    root = tmp_path / "core5-sources"
    canonical = runner.load_cases()
    plans: dict[str, dict[str, Any]] = {}
    pending = []
    for case_id, directory in runner.CORE5_SOURCES:
        request = canonical[case_id].raw["canonical_user_prompt"]
        reference = (canonical[case_id].raw.get("evaluation_context") or {}).get(
            "run_reference_time"
        )
        binding = {
            "case_id": case_id,
            "case_sha256": runner.object_hash(canonical[case_id].raw),
            "request_sha256": runner.object_hash(request),
            "effective_reference_time_ms": 1786060800000,
            "case_reference_time": reference,
            "reference_time_source": "CASE" if reference else "PREREGISTERED_PAIR_START",
            "fault_profile": None,
        }
        plan = plans.setdefault(
            directory,
            {
                "head_sha": "historical-" + directory,
                "preregistered_reference_time_ms": 1786060800000,
                "model": {"id": model["model_id"], "digest": model["model_digest"]},
                "dataset_sha256": runner.file_hash(runner.DEFAULT_DATASET_PATH),
                "snapshot_sha256": runner.file_hash(runner.DEFAULT_PROVIDER_FIXTURE_PATH),
                "cases": [],
            },
        )
        plan["cases"].append(binding)
        call = deepcopy(template)
        call["prompt_ref"].update(prompt_version="1.1.0", content_hash="historical-content-hash")
        call["wire_sha256"] = "historical-wire-" + case_id
        call["input"]["user_request"] = request
        call["input"]["run_reference_time"] = {
            "reference_time": "2026-08-07T09:00:00+09:00",
            "timezone": "Asia/Seoul",
        }
        call["input"]["goal_candidate"]["goal"] = request
        call["input"]["requested_work"]["work_units"][0]["request_provenance"] = [
            {
                "source": "USER_REQUEST",
                "start_offset": 0,
                "end_offset": len(request),
                "source_text": request,
            }
        ]
        call["input_sha256"] = runner.object_hash(call["input"])
        revision = deepcopy(call)
        revision["input"]["base_projection"] = {"output_responsibilities": []}
        calls = [{"prompt_id": "unrelated"}] * 4 + [call, revision]
        pending.append((case_id, directory, binding, calls))
    for directory, plan in plans.items():
        _dump(root / directory / "plan.json", plan)
    for case_id, directory, binding, calls in pending:
        destination = root / directory / case_id / "production"
        _dump(destination / "calls.json", {"calls": calls})
        _dump(
            destination / "raw.json",
            {
                "case_binding": binding,
                "arm": "production",
                "plan_sha256": runner.object_hash(plans[directory]),
            },
        )
    return root, model


def test_core5_rebinds_current_prompt_without_reusing_historical_wire_or_scores(
    frozen_core5: tuple[Path, dict[str, Any]], monkeypatch: pytest.MonkeyPatch
) -> None:
    root, model = frozen_core5
    before = {path: runner.file_hash(path) for path in root.rglob("*.json")}

    def forbidden(**_kwargs: Any) -> Any:
        raise AssertionError("dry plan must not inspect or generate with the model")

    monkeypatch.setattr(runner, "inspect_model", forbidden)
    monkeypatch.setattr(runner.transport, "_post_json", forbidden)
    plan = runner.make_plan(model, input_set="core5", core5_root=root)
    assert len(plan["cases"]) == 5 and len(plan["source_plans"]) == 2
    assert plan["policy"]["max_http_generation_calls"] == 10
    assert plan["policy"]["reused_baseline_calls"] == 0
    assert plan["historical_response_reuse"] is plan["historical_score_reuse"] is False
    assert "source_plan_path" not in plan and "reused_baseline" not in plan
    assert runner.CORE5_CRITERIA in plan["source_hashes"]
    assert [(row["case_id"], row["arm"]) for row in plan["execution_order"]] == [
        ("CASE-CORE-009", "schema_constrained"),
        ("CASE-CORE-009", "format_omitted"),
        ("CASE-CORE-019", "format_omitted"),
        ("CASE-CORE-019", "schema_constrained"),
        ("CASE-CORE-023", "schema_constrained"),
        ("CASE-CORE-023", "format_omitted"),
        ("CASE-CORE-025", "format_omitted"),
        ("CASE-CORE-025", "schema_constrained"),
        ("CASE-CORE-059", "schema_constrained"),
        ("CASE-CORE-059", "format_omitted"),
    ]
    for case in plan["cases"]:
        first = case["source_call"]
        assert first["call_index"] == 5 and case["source_call_array_index"] == 4
        assert case["source_call_sha256"] == runner.object_hash(first)
        assert case["historical_prompt_ref"] == first["prompt_ref"]
        assert set(case["prompt_ref_diff"]) == {"prompt_version", "content_hash"}
        assert case["historical_wire_sha256"] != case["baseline_wire_sha256"]
        assert case["historical_response_reused"] is case["historical_score_reused"] is False
        baseline = runner.payload_for(case, "schema_constrained")
        candidate = runner.payload_for(case, "format_omitted")
        assert candidate == {k: v for k, v in baseline.items() if k != "format"}
        prompt = json.loads(baseline["prompt"])
        assert prompt["input"] == first["input"]
        assert prompt["output_schema"] == first["output_schema"]
        assert baseline["options"] == first["wire_options"]
        assert baseline["think"] == first["wire_think"]
        assert runner.object_hash(baseline) == case["baseline_wire_sha256"]
        assert runner.object_hash(candidate) == case["candidate_wire_sha256"]
        with pytest.raises(ValueError, match="PromptRef differs"):
            runner.reconstruct_payload(first)
    assert before == {path: runner.file_hash(path) for path in before}


@pytest.mark.parametrize("drift", ["duplicate_first", "schema", "prompt_owner", "runtime", "clock"])
def test_core5_first_call_and_contract_drift_reject_before_dispatch(
    frozen_core5: tuple[Path, dict[str, Any]], drift: str
) -> None:
    root, model = frozen_core5
    case_id, directory = runner.CORE5_SOURCES[0]
    path = root / directory / case_id / "production/calls.json"
    raw = json.loads(path.read_text(encoding="utf-8"))
    call = raw["calls"][4]
    if drift == "duplicate_first":
        raw["calls"].append(deepcopy(call))
    elif drift == "schema":
        call["output_schema"]["required"] = []
    elif drift == "prompt_owner":
        call["prompt_ref"]["input_schema_version"] = "changed"
    elif drift == "runtime":
        call["wire_options"]["num_ctx"] = 4096
    else:
        call["input"]["run_reference_time"]["reference_time"] = "2026-08-08T09:00:00+09:00"
        call["input_sha256"] = runner.object_hash(call["input"])
    runner.write_json(path, raw)
    with pytest.raises(ValueError):
        runner.make_plan(model, input_set="core5", core5_root=root)


@pytest.mark.parametrize("field", ["model", "dataset_sha256", "snapshot_sha256"])
def test_core5_each_source_plan_must_match_same_model_and_dataset(
    frozen_core5: tuple[Path, dict[str, Any]], field: str
) -> None:
    root, model = frozen_core5
    path = root / runner.CORE5_SOURCES[-1][1] / "plan.json"
    value = json.loads(path.read_text(encoding="utf-8"))
    if field == "model":
        value[field]["digest"] = "different-digest"
    else:
        value[field] = "changed"
    runner.write_json(path, value)
    with pytest.raises(ValueError):
        runner.make_plan(model, input_set="core5", core5_root=root)


@pytest.mark.parametrize("field", ["case_reference_time", "fault_profile", "reference_time_source"])
def test_core5_canonical_clock_and_nested_fault_authority_are_checked(
    frozen_core5: tuple[Path, dict[str, Any]], field: str
) -> None:
    root, model = frozen_core5
    case_id, directory = runner.CORE5_SOURCES[0]
    plan_path = root / directory / "plan.json"
    source_plan = json.loads(plan_path.read_text(encoding="utf-8"))
    binding = source_plan["cases"][0]
    binding[field] = "changed"
    runner.write_json(plan_path, source_plan)
    raw_path = root / directory / case_id / "production/raw.json"
    raw = json.loads(raw_path.read_text(encoding="utf-8"))
    raw.update(case_binding=binding, plan_sha256=runner.object_hash(source_plan))
    runner.write_json(raw_path, raw)
    with pytest.raises(ValueError, match="reference time/request/fault"):
        runner.make_plan(model, input_set="core5", core5_root=root)


def test_core5_first_selection_is_not_an_array_index_assumption(
    frozen_core5: tuple[Path, dict[str, Any]],
) -> None:
    root, model = frozen_core5
    case_id, directory = runner.CORE5_SOURCES[0]
    path = root / directory / case_id / "production/calls.json"
    raw = json.loads(path.read_text(encoding="utf-8"))
    raw["calls"].insert(1, raw["calls"].pop(4))
    runner.write_json(path, raw)
    plan = runner.make_plan(model, input_set="core5", core5_root=root)
    assert plan["cases"][0]["source_call_array_index"] == 1
    assert plan["cases"][0]["source_call"]["call_index"] == 5


def test_core5_runs_ten_new_calls_preserving_strict_failure_and_separate_admission(
    frozen_core5: tuple[Path, dict[str, Any]], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, model = frozen_core5
    plan = runner.make_plan(model, input_set="core5", core5_root=root)
    monkeypatch.setattr(runner, "RESULTS", tmp_path)
    output = tmp_path / "new-trial"
    calls = []

    def post(**kwargs: Any) -> dict[str, Any]:
        saved = json.loads((output / "raw.json").read_text(encoding="utf-8"))
        assert saved["results"][-1]["state"] == "DISPATCH_STARTED"
        assert kwargs["timeout_seconds"] == 180
        calls.append(kwargs)
        body = '{"output_responsibilities":[]}'
        if "format" not in kwargs["payload"]:
            body = f"```json\n{body}\n```"
        return {"response": body, "eval_count": 5, "load_duration": 7_000_000}

    monkeypatch.setattr(runner.transport, "_post_json", post)
    result = runner.execute_plan(plan, output, plan_sha256=runner.object_hash(plan))
    assert len(calls) == result["actual_http_calls"] == 10
    assert result["reused_http_calls"] == 0 and result["reused_results"] == []
    assert result["new_call_metrics"]["output_tokens"] == 50
    for row in result["results"]:
        assert row["new_call"] and row["historical_response_reused"] is False
        assert row["schema_repairs"] == row["http_retries"] == 0
        assert row["load_duration_ms"] == 7 and row["prompt_eval_duration_ms"] is None
        assert row["semantic_verdict"] == "UNREVIEWED"
        if row["arm"] == "format_omitted":
            assert row["validation"]["structural_result"] == "INVALID_JSON"
            assert row["fence_validation"]["strict_validation"] == row["validation"]
            assert (
                row["fence_validation"]["candidate_validation"]["structural_result"] == "VALIDATED"
            )
            assert row["fence_validation"]["raw_content"] == row["content"]
        else:
            assert row["validation"]["structural_result"] == "VALIDATED"
            assert "fence_validation" not in row
    with pytest.raises(ValueError, match="prior partial/failed"):
        runner.execute_plan(plan, output, plan_sha256=runner.object_hash(plan))
    with pytest.raises(FileExistsError):
        runner.execute_plan(plan, tmp_path / "repeat", plan_sha256=runner.object_hash(plan))
    assert len(calls) == 10


@pytest.mark.parametrize("drift", ["extra_call", "json_mode", "budget", "case_order"])
def test_core5_fixed_pair_budget_rejects_extra_or_reused_baseline_calls(
    frozen_core5: tuple[Path, dict[str, Any]],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    drift: str,
) -> None:
    root, model = frozen_core5
    plan = runner.make_plan(model, input_set="core5", core5_root=root)
    monkeypatch.setattr(runner, "RESULTS", tmp_path)
    if drift == "extra_call":
        plan["execution_order"].append(plan["execution_order"][0])
    elif drift == "json_mode":
        plan["candidate_mode"] = "json"
    elif drift == "budget":
        plan["policy"]["max_http_generation_calls"] = 11
    else:
        plan["cases"].reverse()
    with pytest.raises(ValueError, match="registered"):
        runner.execute_plan(plan, tmp_path / "no-run", plan_sha256=runner.object_hash(plan))
    assert not (tmp_path / "no-run").exists()


@pytest.fixture
def frozen_source(frozen: tuple[Path, dict[str, Any]]) -> tuple[Path, dict[str, Any]]:
    root, model = frozen
    plan_path = root / "plan.json"
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    plan["preregistered_reference_time_ms"] = 1786060800000
    registry = PromptRegistry()
    ref = registry.lookup_for_evaluation(runner.SOURCE_PROMPT_ID)
    canonical = runner.load_cases()
    for binding, (case_id, arm) in zip(plan["cases"], runner.SOURCES, strict=True):
        reference = (canonical[case_id].raw.get("evaluation_context") or {}).get(
            "run_reference_time"
        )
        binding.update(
            request_sha256=runner.object_hash(canonical[case_id].raw["canonical_user_prompt"]),
            case_reference_time=reference,
            effective_reference_time_ms=1786060800000,
            reference_time_source="CASE" if reference else "PREREGISTERED_PAIR_START",
        )
        calls_path = root / case_id / arm / "calls.json"
        previous = json.loads(calls_path.read_text(encoding="utf-8"))["calls"][0]
        call = deepcopy(previous)
        call.update(call_index=4, prompt_id=runner.SOURCE_PROMPT_ID, prompt_ref=asdict(ref))
        projection = call["input"]
        del projection["output_candidates"], projection["effect_prohibitions"]
        projection["run_reference_time"] = {
            "reference_time": "2026-08-07T09:00:00+09:00",
            "timezone": "Asia/Seoul",
        }
        projection["source_candidates"] = [
            {
                "resource_type": "TASK",
                "read_tool_ids": ["tasks_get_task"],
                "owned_fact_kinds": ["task_identity", "title", "due", "completion_status"],
            },
            {
                "resource_type": "GMAIL_DRAFT",
                "read_tool_ids": ["gmail_get_draft"],
                "owned_fact_kinds": ["draft_identity", "body"],
            },
        ]
        schema = runner.build_source_dependency_output_schema(
            projection["source_candidates"], work_unit_ids=["work-1"]
        )
        options = {"num_ctx": 16384, "temperature": 0.05, "seed": 20260923}
        payload = {
            "model": model["model_id"],
            "system": assemble_prompt(
                ref, projection, registry=registry, execution_scope=EVALUATION
            ),
            "prompt": json.dumps(
                {
                    "prompt_ref": {
                        "prompt_id": ref.prompt_id,
                        "prompt_version": ref.prompt_version,
                        "content_hash": ref.content_hash,
                    },
                    "input": projection,
                    "output_schema": schema.json_schema,
                },
                sort_keys=True,
                ensure_ascii=False,
            ),
            "stream": False,
            "think": False,
            "format": schema.json_schema,
            "options": options,
        }
        call.update(
            input_sha256=runner.object_hash(projection),
            output_schema=schema.json_schema,
            temperature=0.05,
            wire_options=options,
            wire_sha256=runner.object_hash(payload),
            content=json.dumps(
                {
                    "source_dependencies": [
                        {
                            "resource_type": "TASK",
                            "dependency": "SOURCE_REQUIRED",
                            "required_information": [
                                "task_identity",
                                "title",
                                "due",
                                "completion_status",
                            ],
                            "target_scope": "SINGULAR",
                            "work_unit_ids": ["work-1"],
                        },
                        {"resource_type": "GMAIL_DRAFT", "dependency": "SOURCE_NOT_REQUIRED"},
                    ]
                }
            ),
            input_tokens=100,
            output_tokens=20,
            latency_ms=30,
            wall_latency_ms=32,
        )
        call["runtime_policy"]["sampling_temperature"] = 0.05
        runner.write_json(calls_path, {"calls": [call, previous]})
    runner.write_json(plan_path, plan)
    for binding, (case_id, arm) in zip(plan["cases"], runner.SOURCES, strict=True):
        runner.write_json(
            root / case_id / arm / "raw.json",
            {
                "case_binding": binding,
                "arm": arm,
                "plan_sha256": runner.object_hash(plan),
            },
        )
    return root, model


def test_source_plan_reuses_three_exact_firsts_without_regenerating_baseline(
    frozen_source: tuple[Path, dict[str, Any]], monkeypatch: pytest.MonkeyPatch
) -> None:
    root, model = frozen_source
    before = {path: runner.file_hash(path) for path in root.rglob("*.json")}

    def forbidden(**_kwargs: Any) -> Any:
        raise AssertionError("Source dry-plan must never call a model")

    monkeypatch.setattr(runner.transport, "_post_json", forbidden)
    plan = runner.make_plan(model, source_root=root, owner="source")
    assert plan["owner"] == "source"
    assert plan["policy"]["max_http_generation_calls"] == 3
    assert plan["policy"]["reused_baseline_calls"] == 3
    assert [row["arm"] for row in plan["execution_order"]] == ["format_omitted"] * 3
    assert runner.SOURCE_CRITERIA in plan["source_hashes"]
    for case, prior in zip(plan["cases"], plan["reused_source_baseline"], strict=True):
        assert (
            prior["new_call"] is False and prior["origin_row_sha256"] == case["source_call_sha256"]
        )
        assert prior["validation_origin"] == "CURRENT_OWNER_REVALIDATION_OF_ORIGINAL_FIRST"
        assert prior["semantic_verdict"] == "UNREVIEWED"
        payload = runner.payload_for(case, "schema_constrained")
        candidate = runner.payload_for(case, "format_omitted")
        assert runner.object_hash(payload) == case["source_call"]["wire_sha256"]
        assert candidate == {k: v for k, v in payload.items() if k != "format"}
        assert candidate["options"] == {"num_ctx": 16384, "temperature": 0.05, "seed": 20260923}
        assert prior["source_observations"]["decisions"][0]["full_capability_inventory_selected"]
        assert (
            prior["source_observations"]["business_review"]["unnecessary_source_use"]
            == "UNREVIEWED"
        )
    assert before == {path: runner.file_hash(path) for path in before}


@pytest.mark.parametrize(
    "mutation", ["missing", "duplicate", "unknown_work", "empty_information", "new_source"]
)
def test_source_same_exact_set_and_work_binding_owner_reject_invalid_firsts(
    frozen_source: tuple[Path, dict[str, Any]], mutation: str
) -> None:
    root, model = frozen_source
    case = runner.make_plan(model, source_root=root, owner="source")["cases"][0]
    value = json.loads(case["source_call"]["content"])
    rows = value["source_dependencies"]
    if mutation == "missing":
        rows.pop()
    elif mutation == "duplicate":
        rows[1] = deepcopy(rows[0])
    elif mutation == "unknown_work":
        rows[0]["work_unit_ids"] = ["invented-work"]
    elif mutation == "empty_information":
        rows[0]["required_information"] = ["{}"]
    else:
        rows[1]["resource_type"] = "CALENDAR_EVENT"
    content = json.dumps(value)
    result = runner.validate_fenced_response(f"```json\n{content}\n```", case)
    assert result["strict_validation"]["structural_result"] == "INVALID_JSON"
    assert result["candidate_validation"]["structural_result"] in {
        "INVALID_SCHEMA",
        "OWNER_REJECTED",
    }
    assert result["candidate_validation"] == runner.validate_response(content, case)
    assert result["model_calls"] == 0


def test_source_executes_three_only_and_preserves_baseline_usage_and_strict_raw(
    frozen_source: tuple[Path, dict[str, Any]], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, model = frozen_source
    plan = runner.make_plan(model, source_root=root, owner="source")
    before = {path: runner.file_hash(path) for path in root.rglob("*.json")}
    monkeypatch.setattr(runner, "RESULTS", tmp_path)
    output = tmp_path / "source-trial"
    calls = []

    def post(**kwargs: Any) -> dict[str, Any]:
        payload = kwargs["payload"]
        assert "format" not in payload and kwargs["timeout_seconds"] == 180
        assert payload["options"]["temperature"] == 0.05
        calls.append(kwargs)
        content = plan["cases"][len(calls) - 1]["source_call"]["content"]
        return {"response": f"```json\n{content}\n```", "eval_count": 4}

    monkeypatch.setattr(runner.transport, "_post_json", post)
    result = runner.execute_plan(plan, output, plan_sha256=runner.object_hash(plan))
    assert result["actual_http_calls"] == len(calls) == 3
    assert result["reused_http_calls"] == 3 and result["new_call_metrics"]["output_tokens"] == 12
    assert result["reused_call_metrics"]["output_tokens"] == 60
    assert all(row["new_call"] is False for row in result["reused_results"])
    for row in result["results"]:
        assert row["validation"]["structural_result"] == "INVALID_JSON"
        assert row["fence_validation"]["candidate_validation"]["structural_result"] == "VALIDATED"
        assert row["fence_validation"]["raw_content"] == row["content"]
        assert row["strict_source_observations"]["decisions"] == []
        assert len(row["source_observations"]["decisions"]) == 2
        assert (
            row["source_observations"]["business_review"]["new_output_as_existing_source"]
            == "UNREVIEWED"
        )
    assert before == {path: runner.file_hash(path) for path in before}
    with pytest.raises(ValueError, match="prior partial/failed"):
        runner.execute_plan(plan, output, plan_sha256=runner.object_hash(plan))
    assert len(calls) == 3


@pytest.mark.parametrize(
    "drift", ["prompt_hash", "wire_hash", "temperature", "new_baseline", "origin_file"]
)
def test_source_reuse_rejects_drift_or_extra_baseline_generation(
    frozen_source: tuple[Path, dict[str, Any]],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    drift: str,
) -> None:
    root, model = frozen_source
    monkeypatch.setattr(runner, "RESULTS", tmp_path)
    plan = runner.make_plan(model, source_root=root, owner="source")
    case = plan["cases"][0]
    if drift == "new_baseline":
        plan["execution_order"].insert(0, {"case_id": case["case_id"], "arm": "schema_constrained"})
    elif drift == "origin_file":
        path = Path(case["source_calls_path"])
        document = json.loads(path.read_text(encoding="utf-8"))
        document["calls"][0]["output_tokens"] += 1
        runner.write_json(path, document)
    else:
        call = deepcopy(case["source_call"])
        if drift == "prompt_hash":
            call["prompt_ref"]["content_hash"] = "changed"
        elif drift == "wire_hash":
            call["wire_sha256"] = "changed"
        else:
            call["wire_options"]["temperature"] = 0.0
        with pytest.raises(ValueError):
            runner.reconstruct_payload(call)
        return
    with pytest.raises(ValueError):
        runner.execute_plan(plan, tmp_path / "no-call", plan_sha256=runner.object_hash(plan))
    assert not (tmp_path / "no-call").exists()


@pytest.fixture
def frozen_concise_source(
    frozen_source: tuple[Path, dict[str, Any]], tmp_path: Path
) -> tuple[Path, dict[str, Any]]:
    original, model = frozen_source
    template_plan = json.loads((original / "plan.json").read_text(encoding="utf-8"))
    template = json.loads(
        (original / "CASE-CORE-005/production/calls.json").read_text(encoding="utf-8")
    )["calls"][0]
    root = tmp_path / "concise-sources"
    canonical = runner.load_cases()
    registry = PromptRegistry()
    ref = registry.lookup_for_evaluation(runner.SOURCE_PROMPT_ID)
    plans: dict[str, dict[str, Any]] = {}
    pending = []
    for case_id, arm, directory in runner.SOURCE_CONCISE_SOURCES:
        plan = plans.setdefault(directory, {**deepcopy(template_plan), "cases": []})
        plan["head_sha"] = "historical-" + directory
        request = canonical[case_id].raw["canonical_user_prompt"]
        reference = (canonical[case_id].raw.get("evaluation_context") or {}).get(
            "run_reference_time"
        )
        binding = {
            **deepcopy(template_plan["cases"][0]),
            "case_id": case_id,
            "case_sha256": runner.object_hash(canonical[case_id].raw),
            "request_sha256": runner.object_hash(request),
            "case_reference_time": reference,
            "reference_time_source": "CASE" if reference else "PREREGISTERED_PAIR_START",
            "fault_profile": canonical[case_id].raw["evaluation_gold"]["fault_profile"],
        }
        plan["cases"].append(binding)
        call = deepcopy(template)
        projection = call["input"]
        projection["user_request"] = projection["goal_candidate"]["goal"] = request
        projection["requested_work"]["work_units"][0]["request_provenance"][0].update(
            end_offset=len(request), source_text=request
        )
        payload = {
            "model": model["model_id"],
            "system": assemble_prompt(
                ref, projection, registry=registry, execution_scope=EVALUATION
            ),
            "prompt": json.dumps(
                {
                    "prompt_ref": {
                        key: asdict(ref)[key]
                        for key in ("prompt_id", "prompt_version", "content_hash")
                    },
                    "input": projection,
                    "output_schema": call["output_schema"],
                },
                sort_keys=True,
                ensure_ascii=False,
            ),
            "stream": False,
            "think": False,
            "format": call["output_schema"],
            "options": call["wire_options"],
        }
        call.update(
            input_sha256=runner.object_hash(projection), wire_sha256=runner.object_hash(payload)
        )
        pending.append((case_id, arm, directory, binding, call))
    for directory, plan in plans.items():
        _dump(root / directory / "plan.json", plan)
    for case_id, arm, directory, binding, call in pending:
        destination = root / directory / case_id / arm
        _dump(destination / "calls.json", {"calls": [call]})
        _dump(
            destination / "raw.json",
            {
                "case_binding": binding,
                "arm": arm,
                "plan_sha256": runner.object_hash(plans[directory]),
            },
        )
    return root, model


def test_concise_source_plan_changes_only_instruction_and_artifact_identity(
    frozen_concise_source: tuple[Path, dict[str, Any]], monkeypatch: pytest.MonkeyPatch
) -> None:
    root, model = frozen_concise_source
    before = {path: runner.file_hash(path) for path in root.rglob("*.json")}

    def forbidden(**_kwargs: Any) -> Any:
        raise AssertionError("dry plan must never generate")

    monkeypatch.setattr(runner.transport, "_post_json", forbidden)
    plan = runner.make_plan(model, core5_root=root, owner="source", candidate_mode="concise")
    assert plan["kind"] == "FROZEN_SOURCE_FIRST_INSTRUCTION_BURDEN_DIAGNOSTIC"
    assert [row["case_id"] for row in plan["cases"]] == [
        "CASE-CORE-005",
        "CASE-CORE-009",
        "CASE-CORE-017",
        "CASE-CORE-049",
        "CASE-CORE-059",
    ]
    assert len(plan["source_plans"]) == 3
    assert plan["semantic_score_reuse"] is False
    assert plan["policy"]["max_http_generation_calls"] == 5
    assert plan["policy"]["reused_baseline_calls"] == 5
    assert plan["policy"]["codec_admission"] == 0
    assert runner.SOURCE_CONCISE_PATH in plan["source_hashes"]
    assert runner.SOURCE_CONCISE_CRITERIA in plan["source_hashes"]
    product_source = PromptRegistry().source_text(runner.SOURCE_PROMPT_ID).rstrip()
    concise_source = (runner.ROOT / runner.SOURCE_CONCISE_PATH).read_text(encoding="utf-8").rstrip()
    for case, prior in zip(plan["cases"], plan["reused_source_baseline"], strict=True):
        original = runner.payload_for(case, "schema_constrained")
        candidate = runner.payload_for(case, "source_concise")
        assert {k: v for k, v in candidate.items() if k not in {"prompt", "system"}} == {
            k: v for k, v in original.items() if k not in {"prompt", "system"}
        }
        assert candidate["system"] == concise_source + original["system"][len(product_source) :]
        original_body, candidate_body = (
            json.loads(original["prompt"]),
            json.loads(candidate["prompt"]),
        )
        assert {k: v for k, v in candidate_body.items() if k != "prompt_ref"} == {
            k: v for k, v in original_body.items() if k != "prompt_ref"
        }
        assert candidate_body["prompt_ref"]["prompt_id"] == runner.SOURCE_PROMPT_ID
        assert candidate_body["prompt_ref"]["prompt_version"] == "evaluation-source-concise-v41"
        assert candidate_body["prompt_ref"]["content_hash"] == case["candidate_source_sha256"]
        assert original_body["prompt_ref"]["content_hash"] != case["candidate_source_sha256"]
        assert case["fence_admission"] == "NONE_STRICT_ONLY"
        assert (
            prior["new_call"] is False and prior["origin_row_sha256"] == case["source_call_sha256"]
        )
    assert before == {path: runner.file_hash(path) for path in before}


def test_concise_source_runs_only_five_new_calls_with_strict_validation_no_codec(
    frozen_concise_source: tuple[Path, dict[str, Any]],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, model = frozen_concise_source
    plan = runner.make_plan(model, core5_root=root, owner="source", candidate_mode="concise")
    monkeypatch.setattr(runner, "RESULTS", tmp_path)
    calls = []

    def no_codec(*_args: Any, **_kwargs: Any) -> Any:
        raise AssertionError("concise instruction trial does not admit a fence codec")

    def post(**kwargs: Any) -> dict[str, Any]:
        calls.append(kwargs)
        assert kwargs["timeout_seconds"] == 180
        assert kwargs["payload"]["options"]["temperature"] == 0.05
        assert isinstance(kwargs["payload"]["format"], dict)
        content = plan["cases"][len(calls) - 1]["source_call"]["content"]
        return {"response": f"```json\n{content}\n```", "eval_count": 4}

    monkeypatch.setattr(runner, "validate_fenced_response", no_codec)
    monkeypatch.setattr(runner.transport, "_post_json", post)
    output = tmp_path / "concise-trial"
    result = runner.execute_plan(plan, output, plan_sha256=runner.object_hash(plan))
    assert result["actual_http_calls"] == len(calls) == 5
    assert result["reused_http_calls"] == 5
    assert result["new_call_metrics"]["output_tokens"] == 20
    assert result["reused_call_metrics"]["output_tokens"] == 100
    for row in result["results"]:
        assert row["validation"]["structural_result"] == "INVALID_JSON"
        assert "fence_validation" not in row
        assert row["prompt_ref"]["prompt_id"] == runner.SOURCE_PROMPT_ID
        assert row["prompt_ref"]["prompt_version"] == "evaluation-source-concise-v41"
        assert row["semantic_verdict"] == "UNREVIEWED"
        assert row["source_observations"]["decisions"] == []
    with pytest.raises(ValueError, match="prior partial/failed"):
        runner.execute_plan(plan, output, plan_sha256=runner.object_hash(plan))
    assert len(calls) == 5


@pytest.mark.parametrize(
    "drift", ["extra_case", "extra_baseline", "order", "budget", "candidate_ref"]
)
def test_concise_source_fixed_plan_rejects_drift_before_calls(
    frozen_concise_source: tuple[Path, dict[str, Any]],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    drift: str,
) -> None:
    root, model = frozen_concise_source
    plan = runner.make_plan(model, core5_root=root, owner="source", candidate_mode="concise")
    monkeypatch.setattr(runner, "RESULTS", tmp_path)
    if drift == "extra_case":
        plan["cases"].append(deepcopy(plan["cases"][0]))
    elif drift == "extra_baseline":
        plan["execution_order"].append({"case_id": "CASE-CORE-005", "arm": "schema_constrained"})
    elif drift == "order":
        plan["execution_order"].reverse()
    elif drift == "budget":
        plan["policy"]["max_http_generation_calls"] += 1
    else:
        plan["cases"][0]["candidate_prompt_ref"]["content_hash"] = "changed"
    with pytest.raises(ValueError):
        runner.execute_plan(plan, tmp_path / "never-created", plan_sha256=runner.object_hash(plan))
    assert not (tmp_path / "never-created").exists()


def test_concise_source_is_not_an_output_owner_or_schema_mutation(
    frozen: tuple[Path, dict[str, Any]], frozen_concise_source: tuple[Path, dict[str, Any]]
) -> None:
    root, model = frozen
    with pytest.raises(ValueError, match="combination"):
        runner.make_plan(model, source_root=root, candidate_mode="concise")
    output_case = runner.make_plan(model, source_root=root)["cases"][0]
    with pytest.raises(ValueError, match="Source owner"):
        runner.concise_source_payload(output_case["payload"], output_case["source_call"])
    root, model = frozen_concise_source
    case = runner.make_plan(model, core5_root=root, owner="source", candidate_mode="concise")[
        "cases"
    ][0]
    with pytest.raises(ValueError, match="prefix"):
        runner.concise_source_payload(
            {**case["payload"], "system": "different"}, case["source_call"]
        )
    # A valid plain JSON first still goes through the original exact-set owner.
    assert (
        runner.validate_response(case["source_call"]["content"], case)["structural_result"]
        == "VALIDATED"
    )
    changed = json.loads(case["source_call"]["content"])
    changed["source_dependencies"].pop()
    assert (
        runner.validate_response(json.dumps(changed), case)["structural_result"] == "INVALID_SCHEMA"
    )
