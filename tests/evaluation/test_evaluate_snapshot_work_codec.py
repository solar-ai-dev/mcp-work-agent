"""Fake-wire composition gates, not actual-model or semantic quality results."""

from __future__ import annotations

import json
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest
from scripts import evaluate_snapshot_work_codec as runner
from tests.support.llm_runtime import runtime_selection

from google_work_agent.adapters.llm.ollama import transport
from google_work_agent.application.agents.request_understanding.identify_source_dependencies import (  # noqa: E501
    build_source_dependency_candidates,
)
from google_work_agent.application.use_cases.run.account_provider_dispatch import (
    current_provider_dispatch_run_id,
)
from google_work_agent.ports.llm.structured_inference_contracts import ApprovedModelInfo


def test_fixed_core3_plan_keeps_product_prompt_schema_runtime_and_no_joint_owner() -> None:
    prior = runner.components.CASE_IDS
    plan = runner.build_plan("a" * 64, reference_time_ms=1790553600000)
    runner.validate_plan(plan)
    assert prior == runner.components.CASE_IDS
    assert [case["case_id"] for case in plan["cases"]] == list(runner.CASE_IDS)
    assert plan["arms"] == ["production", "work-span-codec-v35"]
    assert plan["planned_case_arms"] == 6
    assert plan["trials_per_case_arm"] == 1
    assert plan["runtime"]["temperature_override"] is None
    assert plan["runtime"]["joint_authority_temperature"] is None
    assert plan["runtime"]["seed"] == runner.shared.SEED
    assert plan["bounds"]["provider_dispatch_attempts"] == 20
    assert plan["bounds"]["wall_seconds"] == 600
    assert plan["work_contract"]["goal_output_joint_authority"] is False
    assert plan["work_contract"]["token_reference_candidate"] is False
    assert plan["provider_reads"] == plan["provider_writes"] == 0
    assert plan["semantic_grader"].startswith("UNREVIEWED")
    for binding in plan["cases"]:
        case = runner.snapshot.load_case(binding["case_id"])
        assert binding["request_sha256"] == runner.object_hash(case["canonical_user_prompt"])
        assert binding["selected_bindings"] == case["selected_resource_bindings"]
        assert binding["fault_profile"] is None


@pytest.mark.parametrize("field", ["arm", "prompt", "schema", "runtime", "candidate", "request"])
def test_mutated_preregistration_is_rejected(field: str) -> None:
    plan = runner.build_plan("a" * 64, reference_time_ms=1790553600000)
    if field == "arm":
        plan["arms"][1] = runner.shared.CANDIDATE
    elif field in {"prompt", "schema"}:
        plan["work_contract"][
            f"both_arms_{'prompt_ref' if field == 'prompt' else 'output_schema_sha256'}"
        ] = "changed"
    elif field == "runtime":
        plan["runtime"]["temperature_override"] = 0
    elif field == "candidate":
        plan["work_contract"]["candidate_version"] = "different"
    else:
        plan["cases"][0]["request_sha256"] = "different"
    with pytest.raises(ValueError, match="binding changed"):
        runner.validate_plan(plan)


@pytest.fixture
def fake_hardware(monkeypatch: pytest.MonkeyPatch) -> None:
    original = runner.snapshot.snapshot_production_runtime

    @contextmanager
    def runtime(*args: Any, **kwargs: Any) -> Any:
        with original(*args, **kwargs) as (container, boundary):
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

    monkeypatch.setattr(runner.snapshot, "snapshot_production_runtime", runtime)
    monkeypatch.setattr(
        runner.shared.OllamaHTTPClient,
        "list_installed_models",
        lambda _self: [SimpleNamespace(model_id=runner.shared.MODEL_ID, digest="a" * 64)],
    )


def _responses(case: dict[str, Any], *, whitespace: bool, confirmation: bool) -> dict[str, Any]:
    text = case["canonical_user_prompt"]
    constraints: dict[str, Any] = {
        name: []
        for name in (
            "search_terms",
            "business_concepts",
            "person",
            "sender",
            "recipient",
            "subject",
            "period",
        )
    }
    constraints.update(
        coverage_requirement={"value": "NOT_COLLECTION", "work_unit_ids": ["work-1"]},
        additional_constraints=[],
    )
    prefix = "request_understanding."
    source_candidates = build_source_dependency_candidates(
        runner.shared.composition.load_development_tool_registry()
    )
    return {
        prefix + "identify_requested_work": {
            "schema_version": 1,
            "work_units": [{"request_spans": [" ".join(text) if whitespace else text]}],
        },
        prefix + "identify_goal": {
            "goal": text,
            "completion_conditions": ["상태와 기한 답변"],
            "constraints": constraints,
            "analysis_requirement": "NONE",
        },
        prefix + "identify_effect_prohibitions": {
            "effect_prohibitions": [
                {
                    "effect": effect,
                    "prohibition": "FORBIDDEN" if effect == "CREATE" else "NOT_FORBIDDEN",
                    "work_unit_ids": ["work-1"],
                }
                for effect in ("CREATE", "UPDATE", "SEND", "DELETE")
            ]
        },
        prefix + "identify_source_dependencies": {
            "source_dependencies": [
                {
                    "resource_type": item["resource_type"],
                    "dependency": "SOURCE_REQUIRED",
                    "required_information": ["status", "due"],
                    "target_scope": "SINGULAR",
                    "work_unit_ids": ["work-1"],
                }
                if item["resource_type"] == "TASK"
                else {"resource_type": item["resource_type"], "dependency": "SOURCE_NOT_REQUIRED"}
                for item in source_candidates
            ]
        },
        prefix + "identify_output_responsibilities": {"output_responsibilities": []},
        prefix + "identify_source_status": {"statuses": []},
        prefix + "detect_ambiguity": {
            "missing_information_owner": "USER" if confirmation else "CONNECTOR",
            "missing_fields": ["user_scope"] if confirmation else ["status", "due"],
        },
    }


@pytest.mark.usefixtures("fake_hardware")
@pytest.mark.parametrize(
    "arm,whitespace,confirmation",
    [
        ("production", False, False),
        (runner.CANDIDATE, False, False),
        ("production", True, False),
        (runner.CANDIDATE, True, False),
        (runner.CANDIDATE, True, True),
    ],
)
def test_actual_composed_codec_only_keeps_budget_observer_and_confirmation_stop(
    monkeypatch: pytest.MonkeyPatch, arm: str, whitespace: bool, confirmation: bool
) -> None:
    plan = runner.build_plan("a" * 64, reference_time_ms=1790553600000)
    binding = plan["cases"][0]
    case = runner.snapshot.load_case(binding["case_id"])
    answers = _responses(case, whitespace=whitespace, confirmation=confirmation)
    output = runner.shared.RESULTS_ROOT / f"work-codec-component-fake-{uuid4().hex}"
    contexts: list[str | None] = []
    original_decorate = runner.shared.TrialObservation.decorate
    observations: list[Any] = []

    def capture(observation: Any, provider: Any) -> Any:
        observations.append(observation)
        return original_decorate(observation, provider)

    def wire(**_kwargs: Any) -> dict[str, Any]:
        contexts.append(current_provider_dispatch_run_id())
        slot = observations[-1].calls[-1]["prompt_id"]
        assert slot in answers, slot
        return {
            "response": json.dumps(answers[slot]),
            "model": runner.shared.MODEL_ID,
            "prompt_eval_count": 2,
            "eval_count": 3,
            "total_duration": 1_000_000,
        }

    monkeypatch.setattr(runner.shared.TrialObservation, "decorate", capture)
    monkeypatch.setattr(transport, "_post_json", wire)
    runner.run_arm(plan, binding, arm, output)
    report = json.loads((output / "raw.json").read_text(encoding="utf-8"))
    calls = json.loads((output / "calls.json").read_text(encoding="utf-8"))["calls"]
    assert report["metrics"]["actual_wire_calls"] == len(contexts)
    assert set(contexts) == {report["run_id"]}
    assert report["provider_reads"] == report["provider_writes"] == 0
    assert report["provider_read_attempts"] == report["provider_write_attempts"] == 0
    assert report["semantic_verdict"] == "UNREVIEWED"
    assert calls[0]["prompt_ref"] == plan["work_contract"]["both_arms_prompt_ref"]
    assert set(calls[0]["input"]) == {"user_request"}
    assert calls[0]["input"]["user_request"] == case["canonical_user_prompt"]
    assert calls[0]["wire_options"]["seed"] == runner.shared.SEED
    assert "temperature" not in calls[0]["wire_options"]
    assert all(not call["prompt_id"].startswith("evaluation.") for call in calls)
    if arm == "production" and whitespace:
        assert len(calls) == 1
        assert report["state"] == "COMPONENT_ERROR"
        assert "exactly once" in report["error"]
        return
    assert len(calls) == 7
    state = report["last_state"]
    if confirmation:
        assert report["state"] == "COMPONENT_CONFIRMATION_BOUNDARY"
        assert report["durable_confirmation_executed"] is False
        assert state.get("tool_route_plan") is None
    else:
        assert report["state"] == "COMPONENT_RETURNED", report
        assert state["tool_route_plan"]["output_plan"]["output_mode"] == "ANSWER"
        assert state["retry_budget"]["llm_calls_used"] == len(calls)
        assert len(state["tool_route_plan"]["input_plan"]["input_routes"]) == 1
    if arm == runner.CANDIDATE:
        event = report["candidate_events"][0]
        assert event["codec_sha256"] == plan["work_contract"]["candidate_code_sha256"]
        assert event["events"][0]["bindings"][0]["binding_mode"] == (
            "WHITESPACE_SELECTOR" if whitespace else "EXACT"
        )


def test_old_joint_authority_candidate_is_not_accepted() -> None:
    with (
        pytest.raises(ValueError, match="standalone"),
        runner.candidate_scope(runner.shared.CANDIDATE, SimpleNamespace(), []),
    ):
        pytest.fail("not reached")


def test_parent_executor_reuses_sequential_exclusive_claim(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(runner.shared, "RESULTS_ROOT", tmp_path)
    plan = runner.build_plan("a" * 64, reference_time_ms=1790553600000)
    path = tmp_path / "plan.json"
    runner.shared.write_json(path, plan)
    observed: list[Any] = []
    original_arm = runner.components.run_arm
    original_validate = runner.components.validate_plan

    class FakeProcess:
        exitcode = 0

        def __init__(self, *, target: Any, args: Any) -> None:
            assert target is runner.run_arm
            self.args = args

        def start(self) -> None:
            registered, binding, arm, output = self.args
            runner.validate_plan(registered)
            observed.append((binding["case_id"], arm))
            runner.shared.write_json(output / "raw.json", {"state": "COMPONENT_RETURNED"})

        def join(self, timeout: int) -> None:
            assert timeout == 600
            observed.append("JOINED")

        def is_alive(self) -> bool:
            return False

    monkeypatch.setattr(
        runner.components.multiprocessing,
        "get_context",
        lambda _: SimpleNamespace(Process=FakeProcess),
    )
    assert runner.execute_plan(path, tmp_path / "output") == 0
    assert observed == [
        item for case in runner.CASE_IDS for arm in runner.ARMS for item in ((case, arm), "JOINED")
    ]
    assert runner.components.run_arm is original_arm
    assert runner.components.validate_plan is original_validate
    with pytest.raises(FileExistsError):
        runner.execute_plan(path, tmp_path / "duplicate")
