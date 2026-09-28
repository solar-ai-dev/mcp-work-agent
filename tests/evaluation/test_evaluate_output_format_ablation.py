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
