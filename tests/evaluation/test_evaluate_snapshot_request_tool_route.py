from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest
from scripts import evaluate_snapshot_request_tool_route as runner
from scripts import production_goal_output_candidate as bridge
from tests.support.llm_runtime import runtime_selection

from google_work_agent.adapters.llm.ollama import transport
from google_work_agent.application.agents.request_understanding.identify_source_dependencies import (  # noqa: E501
    build_source_dependency_candidates,
)
from google_work_agent.application.use_cases.run.account_provider_dispatch import (
    current_provider_dispatch_run_id,
    provider_dispatch_execution_scope,
)
from google_work_agent.ports.llm.structured_inference_contracts import ApprovedModelInfo
from google_work_agent.ports.system.settings_port import SettingsPatchV1


@pytest.fixture
def interrupted_pair(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[Path, dict[str, Any]]:
    monkeypatch.setattr(runner.shared, "RESULTS_ROOT", tmp_path)
    original = runner.build_plan("a" * 64, reference_time_ms=1790553600000)
    original["head_sha"] = "historical-head"
    script_key = Path(runner.__file__).relative_to(runner.shared.PROJECT_ROOT).as_posix()
    original["dependency_sha256"][script_key] = "historical-runner-hash"
    parent = tmp_path / "original"
    runner.shared.write_json(parent / "plan.json", original)
    runner.shared.write_json(
        tmp_path / ".snapshot-component-trials" / f"{original['trial_id']}.json",
        {"plan_sha256": runner.object_hash(original), "output": str(parent)},
    )
    for index, identity in enumerate(runner._execution_identities(original)[:10]):
        directory = parent / identity["case_id"] / identity["arm"]
        runner.shared.write_json(
            directory / "raw.json",
            {"state": "COMPONENT_RETURNED" if index < 9 else "RUNNING"},
        )
        runner.shared.write_json(directory / "calls.json", {"calls": [{"index": index}]})
    return parent, original


def test_continuation_binds_parent_evidence_and_only_six_never_started_arms(
    interrupted_pair: tuple[Path, dict[str, Any]],
) -> None:
    parent, original = interrupted_pair
    previous = {str(path): path.read_bytes() for path in parent.rglob("*") if path.is_file()}
    plan = runner.build_continuation_plan(parent)
    runner.validate_plan(plan)
    continuation = plan["continuation"]
    assert continuation["parent_plan_sha256"] == runner.object_hash(original)
    assert continuation["parent_plan_file_sha256"] == runner.shared.file_hash(parent / "plan.json")
    assert len(continuation["observed"]) == 10
    assert [item["continuation_observation"] for item in continuation["observed"]].count(
        "INTERRUPTED"
    ) == 1
    assert continuation["remaining"] == [
        {"case_id": case_id, "arm": arm}
        for case_id in ("CASE-CORE-025", "CASE-CORE-035", "CASE-CORE-059")
        for arm in runner.ARMS
    ]
    assert all(item["raw_sha256"] and item["calls_sha256"] for item in continuation["observed"])
    assert all(not item["rerun_allowed"] for item in continuation["observed"])
    assert previous == {
        str(path): path.read_bytes() for path in parent.rglob("*") if path.is_file()
    }
    assert plan["cases"] == original["cases"]
    assert plan["bounds"] == original["bounds"]


def test_even_empty_existing_arm_directory_is_not_reexecuted(
    interrupted_pair: tuple[Path, dict[str, Any]],
) -> None:
    parent, _ = interrupted_pair
    (parent / "CASE-CORE-025" / "production").mkdir(parents=True)
    plan = runner.build_continuation_plan(parent)
    assert len(plan["continuation"]["remaining"]) == 5
    observed = plan["continuation"]["observed"][-1]
    assert observed["continuation_observation"] == "INTERRUPTED"
    assert observed["raw_sha256"] is None and observed["calls_sha256"] is None


@pytest.mark.parametrize(
    "changed",
    [
        "product_tree_sha256",
        "prompt_tree_sha256",
        "dataset_sha256",
        "snapshot_sha256",
        "tool_registry_sha256",
        "runtime",
        "candidate",
    ],
)
def test_continuation_rejects_changed_frozen_product_candidate_data_or_runtime(
    interrupted_pair: tuple[Path, dict[str, Any]], changed: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    parent, _ = interrupted_pair
    build = runner.build_plan

    def altered(*args: Any, **kwargs: Any) -> dict[str, Any]:
        current = build(*args, **kwargs)
        if changed == "runtime":
            current["runtime"]["seed"] += 1
        elif changed == "candidate":
            current["dependency_sha256"]["scripts/production_goal_output_candidate.py"] = "changed"
        else:
            current[changed] = "changed"
        return current

    monkeypatch.setattr(runner, "build_plan", altered)
    with pytest.raises(ValueError, match="Product/candidate/data/runtime"):
        runner.build_continuation_plan(parent)


def test_continuation_rejects_parent_plan_tampering_against_original_claim(
    interrupted_pair: tuple[Path, dict[str, Any]],
) -> None:
    parent, original = interrupted_pair
    original["head_sha"] = "changed-after-execution"
    runner.shared.write_json(parent / "plan.json", original)
    with pytest.raises(ValueError, match="original execution claim"):
        runner.build_continuation_plan(parent)


@pytest.mark.parametrize("filename", ["raw.json", "calls.json"])
def test_continuation_rejects_parent_observation_changes_after_registration(
    interrupted_pair: tuple[Path, dict[str, Any]],
    filename: str,
) -> None:
    parent, _ = interrupted_pair
    plan = runner.build_continuation_plan(parent)
    path = parent / "CASE-CORE-023" / runner.shared.CANDIDATE / filename
    runner.shared.write_json(path, {"state": "COMPONENT_RETURNED", "calls": []})
    with pytest.raises(ValueError, match="binding changed"):
        runner.validate_plan(plan)


def test_continuation_executes_only_remaining_sequentially_and_claims_each_identity_once(
    interrupted_pair: tuple[Path, dict[str, Any]], monkeypatch: pytest.MonkeyPatch
) -> None:
    parent, _ = interrupted_pair
    parent_bytes = {str(path): path.read_bytes() for path in parent.rglob("*") if path.is_file()}
    plan = runner.build_continuation_plan(parent)
    stale_second = runner.build_continuation_plan(parent)
    plan_path = parent.parent / "continue-plan.json"
    runner.shared.write_json(plan_path, plan)
    events: list[tuple[str, Any]] = []

    class FakeProcess:
        exitcode = 0

        def __init__(self, *, target: Any, args: Any) -> None:
            assert target is runner.run_arm
            self.args = args

        def start(self) -> None:
            child_plan, binding, arm, output = self.args
            runner.validate_plan(child_plan)
            events.append(("start", (binding["case_id"], arm)))
            runner.shared.write_json(output / "raw.json", {"state": "COMPONENT_RETURNED"})

        def join(self, timeout: int) -> None:
            events.append(("join", timeout))

        def is_alive(self) -> bool:
            return False

    def context(method: str) -> Any:
        assert method == "spawn"
        return SimpleNamespace(Process=FakeProcess)

    monkeypatch.setattr(runner.multiprocessing, "get_context", context)
    output = parent.parent / "continued"
    assert runner.execute_plan(plan_path, output) == 0
    expected = [(item["case_id"], item["arm"]) for item in plan["continuation"]["remaining"]]
    assert [item[1] for item in events if item[0] == "start"] == expected
    assert [item[0] for item in events] == ["start", "join"] * 6
    assert [item[1] for item in events if item[0] == "join"] == [600] * 6
    assert parent_bytes == {
        str(path): path.read_bytes() for path in parent.rglob("*") if path.is_file()
    }
    assert (
        json.loads((output / "continuation-observations.json").read_text(encoding="utf-8"))
        == (plan["continuation"])
    )
    with pytest.raises(FileExistsError):
        runner.execute_plan(plan_path, parent.parent / "duplicate")
    with pytest.raises(ValueError, match="binding changed"):
        runner.validate_plan(stale_second)
    assert runner.build_continuation_plan(parent)["continuation"]["remaining"] == []


def test_fixed_pair_plan_binds_original_inputs_time_and_all_dependencies() -> None:
    plan = runner.build_plan("a" * 64, reference_time_ms=1790553600000)
    assert len(plan["cases"]) == 8
    assert plan["trials_per_case_arm"] == 1 and len(plan["arms"]) == 2
    assert plan["bounds"]["provider_dispatch_attempts"] == 20
    assert plan["bounds"]["wall_seconds"] == 600
    runner.validate_plan(plan)
    for binding in plan["cases"]:
        case = runner.snapshot.load_case(binding["case_id"])
        assert binding["request_sha256"] == runner.object_hash(case["canonical_user_prompt"])
        assert binding["selected_bindings"] == case["selected_resource_bindings"]
        assert binding["fault_profile"] is None
        if case.get("evaluation_context") is None:
            assert binding["effective_reference_time_ms"] == 1790553600000
            assert binding["case_reference_time"] is None
        else:
            assert binding["reference_time_source"] == "CASE"
    changed = deepcopy(plan)
    changed["cases"][0]["entry_mode"] = "AGENT_SEARCH"
    with pytest.raises(ValueError, match="binding changed"):
        runner.validate_plan(changed)


@pytest.mark.parametrize("change", ["fault", "account", "pack", "split", "time"])
def test_missing_or_unsafe_case_binding_fails_before_runtime(change: str) -> None:
    case = runner.snapshot.load_case("CASE-CORE-005")
    if change == "fault":
        case["evaluation_gold"]["fault_profile"] = "unexpected"
    elif change == "account":
        case["selected_resource_bindings"][0]["account_email"] = "other@example.invalid"
    elif change == "pack":
        case["resource_packs"] = ["does-not-exist"]
    elif change == "split":
        case["split"] = "HOLDOUT"
    else:
        case["evaluation_context"] = {"run_reference_time": "2026-08-07T09:00:00"}
    with pytest.raises(ValueError):
        runner.case_binding(case, 1)


def test_search_account_authority_and_zero_connector_boundary() -> None:
    case = runner.snapshot.load_case("CASE-CORE-009")
    binding = runner.case_binding(case, 1)
    registry = runner.shared.composition.load_development_tool_registry()
    with runner.component_boundary(binding["account_id"]):
        boundary = runner.snapshot.SnapshotBoundary(case, registry)
        assert boundary.account_id == binding["account_id"]
        for operation in (boundary.execute_read, boundary.execute_write):
            with pytest.raises(runner.snapshot.SnapshotSafetyError):
                operation(None, {})
        assert boundary.provider.read_calls == boundary.provider.write_calls == []
    with runner.component_boundary("other@example.invalid"):
        boundary = runner.snapshot.SnapshotBoundary(case, registry)
        with pytest.raises(runner.snapshot.SnapshotSafetyError, match="account"):
            _ = boundary.account_id


@pytest.mark.parametrize("arm", runner.ARMS)
@pytest.mark.parametrize("confirmation", [False, True])
def test_actual_composed_components_keep_run_context_budget_and_stop_before_retrieval(
    monkeypatch: pytest.MonkeyPatch,
    arm: str,
    confirmation: bool,
) -> None:
    root = runner.shared.RESULTS_ROOT / f"paired-component-fake-{uuid4().hex}"
    case = runner.snapshot.load_case("CASE-CORE-005")
    binding = runner.case_binding(case, 1790553600000)
    observation = runner.shared.TrialObservation(root)
    events: list[dict[str, object]] = []
    wire_contexts: list[str | None] = []
    source_candidates = build_source_dependency_candidates(
        runner.shared.composition.load_development_tool_registry()
    )
    constraints: dict[str, Any] = {
        field: []
        for field in (
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
    goal = {
        "goal": case["canonical_user_prompt"],
        "completion_conditions": ["상태와 기한 답변"],
        "constraints": constraints,
        "analysis_requirement": "NONE",
    }

    def wire(**_kwargs: Any) -> dict[str, Any]:
        wire_contexts.append(current_provider_dispatch_run_id())
        event = observation.calls[-1]
        prompt = event["prompt_id"]
        if prompt.endswith("identify_requested_work"):
            raw: Any = {
                "schema_version": 1,
                "work_units": [{"request_spans": [case["canonical_user_prompt"]]}],
            }
        elif prompt == bridge.EVALUATION_SLOT:
            raw = {**goal, "requested_outputs": [], "requested_result_mode": "ANSWER_ONLY"}
        elif prompt == bridge.GOAL_SLOT:
            raw = goal
        elif prompt.endswith("identify_effect_prohibitions"):
            raw = {
                "effect_prohibitions": [
                    {
                        "effect": effect,
                        "prohibition": "FORBIDDEN" if effect == "CREATE" else "NOT_FORBIDDEN",
                        "work_unit_ids": ["work-1"],
                    }
                    for effect in ("CREATE", "UPDATE", "SEND", "DELETE")
                ]
            }
        elif prompt.endswith("identify_source_dependencies"):
            raw = {
                "source_dependencies": [
                    {
                        "resource_type": item["resource_type"],
                        "dependency": "SOURCE_REQUIRED",
                        "required_information": ["status", "due"],
                        "target_scope": "SINGULAR",
                        "work_unit_ids": ["work-1"],
                    }
                    if item["resource_type"] == "TASK"
                    else {
                        "resource_type": item["resource_type"],
                        "dependency": "SOURCE_NOT_REQUIRED",
                    }
                    for item in source_candidates
                ]
            }
        elif prompt == bridge.OUTPUT_SLOT:
            raw = {"output_responsibilities": []}
        elif prompt.endswith("identify_source_status"):
            raw = {"statuses": []}
        elif prompt.endswith("detect_ambiguity"):
            raw = {
                "missing_information_owner": "USER" if confirmation else "CONNECTOR",
                "missing_fields": ["user_scope"] if confirmation else ["status", "due"],
            }
        else:
            raise AssertionError(f"unexpected fake gate model slot: {prompt}")
        return {
            "response": json.dumps(raw),
            "model": runner.shared.MODEL_ID,
            "prompt_eval_count": 1,
            "eval_count": 1,
            "total_duration": 1_000_000,
        }

    monkeypatch.setattr(transport, "_post_json", wire)
    with (
        observation.wire_observer(),
        runner.shared.candidate_scope(
            None if arm == "production" else arm, observation, events
        ) as decorate,
        runner.component_boundary(binding["account_id"]),
        runner.snapshot.snapshot_production_runtime(
            root / "runtime",
            case_id=case["case_id"],
            sampling_seed=runner.shared.SEED,
            llm_provider_decorator=decorate,
        ) as (container, boundary),
    ):
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
        container.settings_port.update_settings(
            SettingsPatchV1(
                1, preferred_llm_mode="LOCAL_GPU", preferred_local_model_id=runner.shared.MODEL_ID
            ),
            operation_ref=str(uuid4()),
        )
        request = runner.admit_request(container, boundary, case, binding)
        assert request.request_text == case["canonical_user_prompt"]
        assert request.run_budget["started_at_ms"] == binding["effective_reference_time_ms"]
        assert (
            request.selected_resources[0].resource_id
            == binding["selected_bindings"][0]["resource_id"]
        )
        graph = runner.compile_components(container.workflow_runtime)
        with provider_dispatch_execution_scope(
            run_id=request.run_id,
            now_ms=lambda: binding["effective_reference_time_ms"],
        ):
            if confirmation:
                with pytest.raises(runner.ComponentConfirmationBoundary) as stop:
                    graph.invoke(
                        container.workflow_runtime._initial_state(request),
                        config={"configurable": {"thread_id": request.run_id}},
                    )
                result = stop.value.observed_state
                assert stop.value.semantic_owner == "REQUEST_UNDERSTANDING"
            else:
                result = graph.invoke(
                    container.workflow_runtime._initial_state(request),
                    config={"configurable": {"thread_id": request.run_id}},
                )
        if confirmation:
            assert result.get("tool_route_plan") is None
            assert result["user_interrupt"]["interrupt_kind"] == "CONFIRMATION"
            assert result["user_interrupt"]["question"]
        else:
            assert result["tool_route_plan"]["output_plan"]["output_mode"] == "ANSWER"
            assert len(result["tool_route_plan"]["input_plan"]["input_routes"]) == 1
            assert result["retry_budget"]["llm_calls_used"] == len(wire_contexts)
        assert set(wire_contexts) == {request.run_id}
        assert boundary.provider.read_calls == boundary.provider.write_calls == []
        assert all("retrieval" not in item["prompt_id"] for item in observation.calls)
        assert not any(item.get("decision") == "DENY" for item in boundary.events)
    assert len(wire_contexts) == (7 if arm == "production" else 6)
