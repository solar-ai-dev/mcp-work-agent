"""V43 orchestration, sealed replay, and fail-closed handoff; HTTP is fake."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest
from scripts import evaluate_source_membership_boundary as runner

# Reuse the existing Product-assembled Source fixtures, not a second fake contract.
from tests.evaluation.test_evaluate_output_format_ablation import (  # noqa: F401
    frozen,
    frozen_concise_source,
    frozen_source,
    presence_plan,
)


@pytest.fixture
def plan(
    presence_plan: dict[str, Any],  # noqa: F811 - pytest injects the imported fixture
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> dict[str, Any]:
    rows = []
    for case in presence_plan["cases"]:
        call = case["source_call"]
        baseline = {
            "case_id": case["case_id"],
            "arm": "schema_constrained",
            "state": "RETURNED",
            "wire_request_count": 1,
            "wire_sha256": call["wire_sha256"],
            "wire_options": call["wire_options"],
            "wire_think": call["wire_think"],
            "input_sha256": call["input_sha256"],
            "prompt_ref": call["prompt_ref"],
            "model": call["model"],
            "content": call["content"],
            "input_tokens": 100,
            "output_tokens": 20,
            "latency_ms": 30,
            "validation": runner.existing.validate_response(call["content"], case),
        }
        rows.extend(
            [
                baseline,
                {
                    **deepcopy(baseline),
                    "arm": "source_presence_zero",
                    "content": "UNUSED_BAD_ARM",
                },
            ]
        )
    path = tmp_path / "v42.json"
    runner.write_json(
        path,
        {
            "binding": presence_plan,
            "completed": True,
            "actual_http_calls": 10,
            "reused_http_calls": 0,
            "results": rows,
        },
    )
    monkeypatch.setattr(runner, "BASELINE_SHA256", runner.existing.file_hash(path))
    monkeypatch.setattr(runner, "head", lambda: "fixed-head")
    monkeypatch.setattr(runner, "RESULTS", tmp_path / "results")
    monkeypatch.setattr(
        runner.existing,
        "inspect_diagnostic_model",
        lambda mode: deepcopy(presence_plan["model"]),
    )
    return runner.make_plan(presence_plan["model"], baseline_path=path)


def test_plan_binds_core_reuse_and_two_distinct_synthetic_controls(plan: dict[str, Any]) -> None:
    assert len(plan["cases"]) == 7
    assert plan["policy"]["max_http_generation_calls"] == 16
    assert plan["policy"]["reused_core_baseline_calls"] == 5
    assert plan["policy"]["new_core_calls_max"] == 10
    assert plan["policy"]["new_synthetic_calls_max"] == 6
    assert len(plan["execution_order"]) == 9
    assert [c["case_id"] for c in plan["cases"][:5]] == list(runner.CORE_IDS)
    for case in plan["cases"]:
        assert "presence_penalty" not in case["payload"]["options"]
        assert case["membership_payload"]["options"] == case["payload"]["options"]
        assert case["membership_payload"]["think"] is False
        stage = json.loads(case["membership_payload"]["prompt"])
        assert stage["input"] == case["source_call"]["input"]
        assert not {"case_id", "review", "fixture_binding"} & stage["input"].keys()
        if case["group"] == "core":
            assert case["baseline"]["new_call"] is False
            assert case["baseline"]["content"] != "UNUSED_BAD_ARM"
        else:
            assert case["source_call"]["source_call_kind"] == "SYNTHETIC_INPUT_NOT_OBSERVED"
            assert not {"state", "content", "input_tokens", "output_tokens", "call_index"} & (
                case["source_call"].keys()
            )
            assert case["provider_fixture_claim"] is False
    assert "docs/canonical/15-agent-capability-failure-prompt-contract.md" in plan["source_hashes"]
    assert all(
        p.relative_to(runner.ROOT).as_posix() in plan["source_hashes"]
        for p in runner.candidate.PROMPT_PATHS.values()
    )


def _fake_post(*, payload: dict[str, Any], selected: bool, **kwargs: Any) -> dict[str, Any]:
    assert kwargs["path"] == "/api/generate"
    assert kwargs["endpoint"] == runner.existing.OLLAMA_FIXED_LOOPBACK_ENDPOINT
    assert "presence_penalty" not in payload["options"]
    body = json.loads(payload["prompt"])
    projection = body["input"]
    catalog = projection["source_candidates"]
    version = body["prompt_ref"]["prompt_version"]
    if version == "evaluation-v43-membership":
        value = {
            "resource_decisions": {
                c["resource_type"]: "SOURCE_REQUIRED"
                if selected and c["resource_type"] == "TASK"
                else "SOURCE_NOT_REQUIRED"
                for c in catalog
            }
        }
    elif version == "evaluation-v43-details":
        assert projection["resource_decisions"]["TASK"] == "SOURCE_REQUIRED"
        value = {
            "source_details": {
                "TASK": {
                    "required_information": ["task_identity"],
                    "target_scope": "SINGULAR",
                    "work_unit_ids": ["work-1"],
                }
            }
        }
    else:
        value = {
            "source_dependencies": [
                {
                    "resource_type": c["resource_type"],
                    "dependency": "SOURCE_NOT_REQUIRED",
                }
                for c in catalog
            ]
        }
    return {
        "response": json.dumps(value),
        "model": payload["model"],
        "done": True,
        "prompt_eval_count": 11,
        "eval_count": 7,
        "total_duration": 5_000_000,
        "thinking": "must not be persisted",
    }


@pytest.mark.parametrize(("selected", "count"), [(False, 9), (True, 16)])
def test_conditional_details_calls_strict_projection_and_core_synthetic_metrics(
    plan: dict[str, Any],
    selected: bool,
    count: int,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output = runner.RESULTS / "trial"
    dispatches = []

    def post(**kwargs: Any) -> dict[str, Any]:
        saved = json.loads((output / "raw.json").read_text(encoding="utf-8"))
        assert saved["calls"][-1]["state"] == "DISPATCH_STARTED"
        assert saved["calls"][-1]["payload"] == kwargs["payload"]
        dispatches.append(kwargs["payload"])
        return _fake_post(selected=selected, **kwargs)

    monkeypatch.setattr(runner.existing.transport, "_post_json", post)
    raw = runner.execute_plan(plan, output, plan_sha256=runner.object_hash(plan))
    assert raw["completed"] and raw["actual_http_calls"] == count == len(dispatches)
    assert raw["reused_http_calls"] == 5
    assert raw["new_call_metrics"]["output_tokens"] == count * 7
    assert raw["metrics_by_group"]["core"]["baseline"]["calls"] == 5
    assert raw["metrics_by_group"]["synthetic"]["baseline"]["calls"] == 2
    assert len(raw["results"]) == 9
    assert all(r["semantic_verdict"] == "UNREVIEWED" for r in raw["results"])
    assert all(r["validation"]["structural_result"] == "VALIDATED" for r in raw["results"])
    for call in raw["calls"]:
        assert "must not be persisted" not in json.dumps(call)
        if call["stage"] == "details":
            assert call["parent_membership_sha256"] == runner.object_hash(call["parent_membership"])
            actual_input = json.loads(call["payload"]["prompt"])["input"]
            assert (
                actual_input["resource_decisions"]
                == call["parent_membership"]["resource_decisions"]
            )
    with pytest.raises((ValueError, FileExistsError)):
        runner.execute_plan(plan, runner.RESULTS / "second", plan_sha256=runner.object_hash(plan))
    assert len(dispatches) == count


@pytest.mark.parametrize("content", ["```json\n{}\n```", '{"resource_decisions":{}}'])
def test_invalid_membership_preserves_raw_and_never_dispatches_details(
    plan: dict[str, Any],
    content: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def post(**kwargs: Any) -> dict[str, Any]:
        body = json.loads(kwargs["payload"]["prompt"])
        assert body["prompt_ref"]["prompt_version"] != "evaluation-v43-details"
        if body["prompt_ref"]["prompt_version"] == "evaluation-v43-membership":
            return {"response": content}
        return _fake_post(selected=False, **kwargs)

    monkeypatch.setattr(runner.existing.transport, "_post_json", post)
    raw = runner.execute_plan(
        plan, runner.RESULTS / "invalid", plan_sha256=runner.object_hash(plan)
    )
    assert raw["actual_http_calls"] == 9
    failed = [r for r in raw["results"] if r["arm"] == "membership_details"]
    assert len(failed) == 7 and all(r["details_skipped"] == "MEMBERSHIP_FAILED" for r in failed)
    assert all(c["content"] == content for c in raw["calls"] if c["stage"] == "membership")


def test_http_errors_are_persisted_without_retry_or_details(
    plan: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def post(**kwargs: Any) -> Any:
        raise TimeoutError("fake timeout")

    monkeypatch.setattr(runner.existing.transport, "_post_json", post)
    raw = runner.execute_plan(
        plan, runner.RESULTS / "timeout", plan_sha256=runner.object_hash(plan)
    )
    assert raw["actual_http_calls"] == 9
    assert all(c["state"] == "ERROR" and c["error_type"] == "TimeoutError" for c in raw["calls"])


@pytest.mark.parametrize("drift", ["head", "model", "origin", "plan", "controls"])
def test_drift_is_rejected_before_any_generation(
    plan: dict[str, Any],
    drift: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    expected = runner.object_hash(plan)
    if drift == "head":
        monkeypatch.setattr(runner, "head", lambda: "changed-head")
    elif drift == "model":
        model = {**plan["model"], "model_digest": "changed"}
        monkeypatch.setattr(runner.existing, "inspect_diagnostic_model", lambda mode: model)
    elif drift == "plan":
        plan["policy"]["max_http_generation_calls"] = 17
    elif drift == "origin":
        path = Path(plan["baseline_path"])
        original = json.loads(path.read_text(encoding="utf-8"))
        original["results"][0]["content"] = "{}"
        runner.write_json(path, original)
    else:
        # Use a private copy, never mutate the repository's synthetic control data.
        path = Path(plan["baseline_path"]).parent / "controls.json"
        controls = json.loads(Path(plan["controls_path"]).read_text(encoding="utf-8"))
        controls["controls"][0]["input"]["expected"] = "must not enter Prompt"
        runner.write_json(path, controls)
        plan["controls_path"] = str(path)
        expected = runner.object_hash(plan)

    def forbidden(**kwargs: Any) -> Any:
        raise AssertionError("no generation allowed on drift")

    monkeypatch.setattr(runner.existing.transport, "_post_json", forbidden)
    with pytest.raises(ValueError):
        runner.execute_plan(plan, runner.RESULTS / "drift", plan_sha256=expected)
