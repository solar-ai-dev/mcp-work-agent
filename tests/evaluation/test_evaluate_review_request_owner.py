"""Sealed direct Review diagnostics; fake responses are not semantic passes."""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from scripts import evaluate_review_request_owner as runner


def _response(*findings: dict[str, Any]) -> str:
    return json.dumps(
        {"schema_version": 1, "dimension": runner.PROMPT_ID, "findings": list(findings)}
    )


def _finding(kind: str = "ISSUE") -> dict[str, Any]:
    finding = {
        "dimension": runner.PROMPT_ID,
        "code": "DIAGNOSTIC",
        "finding_kind": kind,
        "description": "현재 의미를 검토합니다.",
        "evidence_refs": ["synthetic-user-message"],
        "affected_action_ids": ["synthetic-action"],
        "affected_route_ids": ["synthetic-route"],
        "required_information": [],
    }
    if kind == runner.candidate.REQUEST_SEMANTICS_ISSUE:
        finding.update(
            work_unit_ids=["work-1"], semantic_field_paths=["$.resource_responsibilities.outputs"]
        )
    return finding


@pytest.fixture
def plan(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """No ignored local artifact dependency; real Product assembly is retained."""
    control = runner.synthetic_controls()[0]
    canonical = {"case_id": "CASE-CORE-005", "canonical_user_prompt": control["user_request"]}
    dataset = tmp_path / "cases.jsonl"
    fixture = tmp_path / "snapshot.json"
    dataset.write_text(json.dumps(canonical), encoding="utf-8")
    fixture.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(runner, "DEFAULT_DATASET_PATH", dataset)
    monkeypatch.setattr(runner, "DEFAULT_PROVIDER_FIXTURE_PATH", fixture)
    monkeypatch.setattr(
        runner, "load_cases", lambda: {"CASE-CORE-005": SimpleNamespace(raw=canonical)}
    )
    monkeypatch.setattr(runner, "RESULTS", tmp_path / "results")
    monkeypatch.setattr(runner, "head", lambda: "fixed-review-head")
    runtime = {"model": "qwen3.5:9b", "temperature": None, "seed": 20260923}
    built = runner.build_payloads(control["input"], control["user_request"], runtime)
    wire = built["payloads"]["production"]
    model = {
        "model_id": runtime["model"],
        "model_digest": "fixed-digest",
        "ollama_version_response": {"version": "0.34.0"},
    }
    call = {
        "prompt_id": runner.PROMPT_ID,
        "call_index": 14,
        "state": "RETURNED",
        "wire_request_count": 1,
        "wire_path": "/api/generate",
        "input": control["input"],
        "input_sha256": runner.object_hash(control["input"]),
        "runtime_policy": {"local_timeout_seconds": 180},
        **runtime,
        "prompt_ref": built["prompt_refs"]["production"],
        "wire_sha256": runner.object_hash(wire),
        "wire_options": wire["options"],
        "output_schema": wire["format"],
    }
    origin = tmp_path / "historical"
    runner.write_json(origin / "calls.json", {"calls": [call]})
    runner.write_json(
        origin / "raw.json",
        {
            "plan": {
                "dataset_sha256": runner.existing.file_hash(dataset),
                "snapshot_sha256": runner.existing.file_hash(fixture),
                "case_sha256": runner.object_hash(canonical),
                "model": {"id": model["model_id"], "digest": model["model_digest"]},
            }
        },
    )
    monkeypatch.setattr(
        runner,
        "ORIGIN_HASHES",
        {name: runner.existing.file_hash(origin / name) for name in ("raw.json", "calls.json")},
    )
    monkeypatch.setattr(runner.existing, "inspect_diagnostic_model", lambda _: deepcopy(model))
    return runner.make_plan(model, origin=origin)


def test_fixed_plan_changes_only_review_owner_contract(plan: dict[str, Any]) -> None:
    assert len(plan["cases"]) == 4
    assert len(plan["execution_order"]) == plan["policy"]["max_http_generation_calls"] == 8
    assert plan["policy"]["repairs"] == plan["policy"]["retries"] == 0
    assert plan["policy"]["reused_scores"] == 0
    core, correct, wrong_title, missing = plan["cases"]
    assert core["origin_call_index"] == 14
    assert core["input_sha256"] == runner.object_hash(core["input"])
    changed_plan = deepcopy(correct["input"])
    changed_plan["planning_result"]["actions"][0]["arguments"]["payload"]["title"] = "무관한 메모"
    assert wrong_title["input"] == changed_plan
    assert missing["input"]["request_intent"]["requested_effect_hints"] == ["READ", "UPDATE"]
    assert all(e["origin_type"] == "USER_MESSAGE" for e in missing["input"]["evidence"])
    registry = runner.PromptRegistry()
    role = registry.source_text(runner.PROMPT_ID).rstrip()
    combined = role + "\n\n" + runner.SUFFIX.read_text(encoding="utf-8").rstrip()
    for case in plan["cases"]:
        base, candidate = (case["payloads"][arm] for arm in runner.ARMS)
        assert {key for key in base if base[key] != candidate[key]} == {
            "system",
            "prompt",
            "format",
        }
        base_input = json.loads(base["prompt"])["input"]
        candidate_input = json.loads(candidate["prompt"])["input"]
        assert base_input == case["input"]
        assert candidate_input == {**base_input, "user_request": case["user_request"]}
        assert base["options"] == {"num_ctx": 16384, "seed": 20260923}
        assert "temperature" not in base["options"]
        assert base["think"] is False and base["stream"] is False
        assert (
            case["prompt_refs"]["request_owner"]["content_hash"]
            == hashlib.sha256(combined.encode()).hexdigest()
        )
        for forbidden in (
            "case_id",
            "evaluation_gold",
            "expectedKind",
            "input_construction",
            "group",
        ):
            assert forbidden not in candidate_input
    assert runner.SUFFIX.relative_to(runner.ROOT).as_posix() in plan["source_hashes"]


def test_historical_byte_tamper_is_rejected(plan: dict[str, Any]) -> None:
    path = Path(plan["origin"]) / "calls.json"
    path.write_text(path.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="historical original"):
        runner.make_plan(plan["model"], origin=Path(plan["origin"]))


def test_execute_preserves_firsts_before_validation_and_never_scores_fake_answers(
    plan: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output = runner.RESULTS / "trial"
    seen = []

    def post(**kwargs: Any) -> dict[str, Any]:
        raw = runner._read(output / "raw.json")
        assert raw["completed"] is False
        assert raw["calls"][-1]["state"] == "DISPATCH_STARTED"
        seen.append(kwargs)
        assert kwargs["timeout_seconds"] == 180
        assert kwargs["endpoint"] == runner.existing.OLLAMA_FIXED_LOOPBACK_ENDPOINT
        return {
            "response": _response(),
            "thinking": "MUST_NOT_BE_STORED",
            "prompt_eval_count": 7,
            "eval_count": 2,
            "total_duration": 3_000_000,
        }

    monkeypatch.setattr(runner.existing.transport, "_post_json", post)
    raw = runner.execute_plan(plan, output, plan_sha256=runner.object_hash(plan))
    assert len(seen) == raw["actual_http_calls"] == 8
    assert raw["metrics_by_group"]["core"]["production"]["calls"] == 1
    assert raw["metrics_by_group"]["synthetic"]["request_owner"]["calls"] == 3
    assert raw["semantic_verdict"] == "UNREVIEWED"
    assert raw["provider_calls"] == raw["graph_calls"] == 0
    for row in raw["calls"]:
        assert row["validation"]["wire_schema"] == "VALID"
        assert row["validation"]["closed_context"] == "VALID"
        assert row["validation"]["semantic_verdict"] == "UNREVIEWED"
    assert "MUST_NOT_BE_STORED" not in (output / "raw.json").read_text(encoding="utf-8")
    with pytest.raises(ValueError, match="prior partial"):
        runner.execute_plan(plan, output, plan_sha256=runner.object_hash(plan))
    with pytest.raises(FileExistsError):
        runner.execute_plan(plan, runner.RESULTS / "rerun", plan_sha256=runner.object_hash(plan))


def test_failed_first_is_preserved_without_repair_or_retry(
    plan: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    attempts = []

    def post(**kwargs: Any) -> dict[str, Any]:
        attempts.append(kwargs)
        if len(attempts) == 1:
            raise TimeoutError("synthetic transport timeout")
        return {"response": "```json\n{}\n```"}

    monkeypatch.setattr(runner.existing.transport, "_post_json", post)
    raw = runner.execute_plan(plan, runner.RESULTS / "failed", plan_sha256=runner.object_hash(plan))
    assert len(attempts) == 8
    assert raw["calls"][0]["error_type"] == "TimeoutError"
    assert all(r["validation"]["strict_json"] == "INVALID" for r in raw["calls"][1:])
    assert raw["completed"] is True  # Finished the fixed attempts, not business success.
    assert raw["business_success"] == "NOT_EVALUATED"


def test_interruption_leaves_partial_raw_and_claim(
    plan: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def interrupt(**_: Any) -> None:
        raise KeyboardInterrupt

    monkeypatch.setattr(runner.existing.transport, "_post_json", interrupt)
    output = runner.RESULTS / "interrupted"
    with pytest.raises(KeyboardInterrupt):
        runner.execute_plan(plan, output, plan_sha256=runner.object_hash(plan))
    raw = runner._read(output / "raw.json")
    assert raw["completed"] is False and len(raw["calls"]) == 1
    assert raw["calls"][0]["state"] == "DISPATCH_STARTED"
    with pytest.raises(FileExistsError):
        runner.execute_plan(plan, runner.RESULTS / "retry", plan_sha256=runner.object_hash(plan))


def test_seal_payload_drift_and_output_escape_reject_before_generation(
    plan: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    def forbidden(**_: Any) -> None:
        pytest.fail("model must not be called")

    monkeypatch.setattr(runner.existing.transport, "_post_json", forbidden)
    output = runner.RESULTS / "rejected"
    with pytest.raises(ValueError, match="sealed plan"):
        runner.execute_plan(plan, output, plan_sha256="wrong")
    changed = deepcopy(plan)
    changed["cases"][0]["payloads"]["request_owner"]["options"]["seed"] = 1
    with pytest.raises(ValueError, match="drift"):
        runner.execute_plan(changed, output, plan_sha256=runner.object_hash(changed))
    with pytest.raises(ValueError, match="dedicated"):
        runner.execute_plan(plan, tmp_path / "outside", plan_sha256=runner.object_hash(plan))
    assert not output.exists()


@pytest.mark.parametrize("arm", runner.ARMS)
def test_closed_evidence_diagnostic_is_identical_for_both_arms(
    plan: dict[str, Any],
    arm: str,
) -> None:
    finding = _finding()
    finding["evidence_refs"] = ["segment-is-not-evidence-id"]
    result = runner.validate_response(_response(finding), plan["cases"][1], arm)
    assert result["wire_schema"] == result["product_shape"] == "VALID"
    assert result["closed_context"] == "INVALID"


def test_new_finding_does_not_silently_expand_baseline_wire_admission(plan: dict[str, Any]) -> None:
    case = plan["cases"][1]
    content = _response(_finding(runner.candidate.REQUEST_SEMANTICS_ISSUE))
    base = runner.validate_response(content, case, "production")
    candidate = runner.validate_response(content, case, "request_owner")
    assert base["wire_schema"] == base["product_shape"] == "INVALID"
    assert base["closed_context"] == "VALID" and base["candidate_projections"] == []
    assert candidate["wire_schema"] == candidate["closed_context"] == "VALID"
    assert candidate["product_shape"] == "INVALID"
    observation = candidate["candidate_projections"][0]["observations"][0]
    assert (
        observation["semantic_values"]["$.resource_responsibilities.outputs"]
        == case["input"]["request_intent"]["resource_responsibilities"]["outputs"]
    )
    assert candidate["semantic_verdict"] == "UNREVIEWED"


def _bind_prior_baseline(
    plan: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> Path:
    prior = runner.RESULTS / "prior.json"
    runner.write_json(
        prior,
        {
            "binding": plan,
            "completed": True,
            "calls": [
                {
                    "case_id": c["case_id"],
                    "arm": "production",
                    "state": "RETURNED",
                    "payload": c["payloads"]["production"],
                    "content": _response(),
                }
                for c in plan["cases"]
            ],
        },
    )
    monkeypatch.setattr(runner, "PRIOR_RAW", prior)
    monkeypatch.setattr(runner, "PRIOR_RAW_HASH", runner.existing.file_hash(prior))
    return prior


def test_partition_reuses_exact_baseline_and_generates_only_four_firsts(
    plan: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prior = _bind_prior_baseline(plan, monkeypatch)
    before = prior.read_bytes()
    partition_plan = runner.make_plan(
        plan["model"],
        origin=Path(plan["origin"]),
        profile="partition_v2",
    )
    assert len(partition_plan["reused_baseline"]) == 4
    assert partition_plan["policy"]["max_http_generation_calls"] == 4
    calls: list[dict[str, Any]] = []

    def post(**kwargs: Any) -> dict[str, Any]:
        calls.append(kwargs)
        return {
            "response": json.dumps(
                {
                    "schema_version": 2,
                    "dimension": runner.PROMPT_ID,
                    "request_intent_findings": [],
                    "planning_findings": [],
                }
            )
        }

    monkeypatch.setattr(runner.existing.transport, "_post_json", post)
    raw = runner.execute_plan(
        partition_plan,
        runner.RESULTS / "partition",
        plan_sha256=runner.object_hash(partition_plan),
    )
    assert len(calls) == raw["actual_http_calls"] == 4
    assert all(row["arm"] == "request_owner" for row in raw["calls"])
    assert all(row["validation"]["closed_context"] == "VALID" for row in raw["calls"])
    assert all(row["validation"]["product_shape"] == "INVALID" for row in raw["calls"])
    assert raw["reused_baseline"] == partition_plan["reused_baseline"]
    assert raw["metrics_by_group"]["core"]["production"]["calls"] == 0
    assert prior.read_bytes() == before


def test_partition_cannot_reuse_a_different_baseline_wire(
    plan: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prior = _bind_prior_baseline(plan, monkeypatch)
    data = runner._read(prior)
    data["calls"][0]["payload"]["options"]["seed"] = 1
    runner.write_json(prior, data)
    monkeypatch.setattr(runner, "PRIOR_RAW_HASH", runner.existing.file_hash(prior))
    with pytest.raises(ValueError, match="exact current Product wire"):
        runner.make_plan(plan["model"], origin=Path(plan["origin"]), profile="partition_v2")
