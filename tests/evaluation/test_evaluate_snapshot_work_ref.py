"""Fake transport checks only; no model, semantic grader, or Provider execution."""

from __future__ import annotations

import json
from contextlib import contextmanager
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest
from scripts import evaluate_snapshot_work_ref as runner
from tests.support.llm_runtime import runtime_selection

from google_work_agent.adapters.llm.ollama import transport
from google_work_agent.application.use_cases.run.account_provider_dispatch import (
    current_provider_dispatch_run_id,
)
from google_work_agent.ports.llm.structured_inference_contracts import ApprovedModelInfo


def test_fixed_five_case_plan_preserves_requests_and_registers_only_work_owner() -> None:
    original_cases = runner.components.CASE_IDS
    plan = runner.build_plan("a" * 64, reference_time_ms=1790553600000)
    runner.validate_plan(plan)
    assert original_cases == runner.components.CASE_IDS
    assert [case["case_id"] for case in plan["cases"]] == list(runner.CASE_IDS)
    assert plan["planned_first_calls"] == 10
    assert plan["owner_invocations_per_case_arm"] == plan["trials_per_case_arm"] == 1
    assert plan["semantic_revision_calls"] == 0
    assert plan["runtime"]["temperature_override"] is None
    assert plan["runtime"]["seed"] == runner.shared.SEED
    assert plan["provider_reads"] == plan["provider_writes"] == 0
    assert plan["bounds"]["wall_seconds"] == 600
    assert plan["prompt_binding"]["baseline_prompt_ref"]["prompt_id"] == runner.candidate.WORK_SLOT
    for binding in plan["cases"]:
        case = runner.snapshot.load_case(binding["case_id"])
        assert binding["request_sha256"] == runner.object_hash(case["canonical_user_prompt"])
        assert binding["selected_bindings"] == case["selected_resource_bindings"]
        assert binding["fault_profile"] is None
        assert "evaluation_gold" not in binding
    assert "CASE-CORE-049" in [item["case_id"] for item in plan["cases"]]


@pytest.mark.parametrize("field", ["runtime", "candidate", "case", "prompt", "model"])
def test_plan_changes_are_rejected_before_runtime(field: str) -> None:
    plan = runner.build_plan("a" * 64, reference_time_ms=1790553600000)
    changed = deepcopy(plan)
    if field == "runtime":
        changed["runtime"]["temperature_override"] = 0
    elif field == "candidate":
        changed["dependency_sha256"]["scripts/production_work_ref_candidate.py"] = "changed"
    elif field == "case":
        changed["cases"][0]["request_sha256"] = "changed"
    elif field == "prompt":
        changed["prompt_binding"]["candidate_prompt_sha256"] = "changed"
    else:
        changed["model"]["id"] = "other-model"
    with pytest.raises(ValueError, match="binding changed"):
        runner.validate_plan(changed)


@pytest.mark.parametrize("arm", runner.ARMS)
@pytest.mark.parametrize("repair", [False, True])
def test_actual_snapshot_owner_keeps_run_budget_raw_and_zero_connector_dispatch(
    monkeypatch: pytest.MonkeyPatch, arm: str, repair: bool
) -> None:
    output = runner.shared.RESULTS_ROOT / f"work-ref-owner-fake-{uuid4().hex}"
    plan = runner.build_plan("a" * 64, reference_time_ms=1790553600000)
    binding = plan["cases"][0]
    case = runner.snapshot.load_case(binding["case_id"])
    request = case["canonical_user_prompt"]
    contexts: list[str | None] = []
    product_runtime = runner.snapshot.snapshot_production_runtime

    @contextmanager
    def configured_runtime(*args: Any, **kwargs: Any) -> Any:
        with product_runtime(*args, **kwargs) as (container, boundary):
            router = container.structured_inference_port
            model = ApprovedModelInfo(runner.shared.MODEL_ID, "OLLAMA", "1", "1")
            router.runtime_selection = runtime_selection(
                deployment_profile="LOCAL_CAPABLE", model=model
            )
            router.status_service = SimpleNamespace(get_model_for_prompt=lambda _: model)
            router.hardware_probe = SimpleNamespace(
                probe=lambda: SimpleNamespace(
                    architecture="AMD64",
                    cpu_logical_cores=8,
                    ram_total_bytes=16 * 1024**3,
                    gpu_present=True,
                    gpu_name="fake-test-only",
                    vram_total_bytes=8 * 1024**3,
                    local_runtime_eligible=True,
                    local_runtime_reason_codes=(),
                )
            )
            yield container, boundary

    def wire(**_kwargs: Any) -> dict[str, Any]:
        contexts.append(current_provider_dispatch_run_id())
        if repair and len(contexts) == 1:
            value: Any = {}
        elif arm == "production":
            value = {"schema_version": 1, "work_units": [{"request_spans": [request]}]}
        else:
            tokens = runner.candidate._request_tokens(request)
            value = {
                "work_units": [
                    {
                        "ranges": [
                            {
                                "start_token_id": tokens[0]["token_id"],
                                "end_token_id": tokens[-1]["token_id"],
                            }
                        ]
                    }
                ]
            }
        return {
            "response": json.dumps(value),
            "model": runner.shared.MODEL_ID,
            "prompt_eval_count": 2,
            "eval_count": 3,
            "total_duration": 1_000_000,
        }

    monkeypatch.setattr(runner.snapshot, "snapshot_production_runtime", configured_runtime)
    monkeypatch.setattr(
        runner.shared.OllamaHTTPClient,
        "list_installed_models",
        lambda _self: [SimpleNamespace(model_id=runner.shared.MODEL_ID, digest="a" * 64)],
    )
    monkeypatch.setattr(transport, "_post_json", wire)
    runner.run_arm(plan, binding, arm, output)
    result = json.loads((output / "raw.json").read_text(encoding="utf-8"))
    calls = json.loads((output / "calls.json").read_text(encoding="utf-8"))["calls"]
    assert result["state"] == "OWNER_RETURNED", result
    assert result["structural_status"] == "VALID_WORK_DEFINITION"
    assert result["semantic_verdict"] == "UNREVIEWED"
    assert set(contexts) == {result["run_id"]}
    assert len(contexts) == (2 if repair else 1)
    assert result["run_budget_after"]["llm_calls_used"] == len(contexts)
    assert result["metrics"]["provider_dispatch_attempts"] == len(contexts)
    assert result["metrics"]["actual_wire_calls"] == len(contexts)
    assert result["metrics"]["input_tokens"] == 2 * len(contexts)
    assert result["provider_reads"] == result["provider_writes"] == 0
    assert result["provider_read_attempts"] == result["provider_write_attempts"] == 0
    assert (
        result["requested_work"]["work_units"][0]["request_provenance"][0]["source_text"] == request
    )
    assert result["actual_router_policy"]["sampling_temperature"] is None
    assert calls[0]["wire_options"]["seed"] == runner.shared.SEED
    assert "temperature" not in calls[0]["wire_options"]
    initial = {key: value for key, value in calls[0]["input"].items() if not key.startswith("_")}
    assert initial["user_request"] == request
    assert set(initial) == (
        {"user_request"} if arm == "production" else {"user_request", "request_tokens"}
    )
    assert all("identify_requested_work" in call["prompt_id"] for call in calls)
    if arm != "production":
        assert (
            result["candidate_events"][0]["materialized_work_definition"]
            == result["requested_work"]
        )


def test_parent_executor_reuses_exclusive_claim_and_original_case_arm_order(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(runner.shared, "RESULTS_ROOT", tmp_path)
    plan = runner.build_plan("a" * 64, reference_time_ms=1790553600000)
    plan_path = tmp_path / "registration.json"
    runner.shared.write_json(plan_path, plan)
    observed: list[Any] = []
    original_validate, original_arm = runner.components.validate_plan, runner.components.run_arm

    class FakeProcess:
        exitcode = 0

        def __init__(self, *, target: Any, args: Any) -> None:
            assert target is runner.run_arm
            self.args = args

        def start(self) -> None:
            registered, binding, arm, output = self.args
            runner.validate_plan(registered)
            observed.append((binding["case_id"], arm))
            runner.shared.write_json(output / "raw.json", {"state": "OWNER_RETURNED"})

        def join(self, bound: int) -> None:
            assert bound == 600
            observed.append("JOINED")

        def is_alive(self) -> bool:
            return False

    monkeypatch.setattr(
        runner.components.multiprocessing,
        "get_context",
        lambda _: SimpleNamespace(Process=FakeProcess),
    )
    assert runner.execute_plan(plan_path, tmp_path / "output") == 0
    assert observed == [
        item
        for case_id in runner.CASE_IDS
        for arm in runner.ARMS
        for item in ((case_id, arm), "JOINED")
    ]
    assert runner.components.validate_plan is original_validate
    assert runner.components.run_arm is original_arm
    with pytest.raises(FileExistsError):
        runner.execute_plan(plan_path, tmp_path / "duplicate")
