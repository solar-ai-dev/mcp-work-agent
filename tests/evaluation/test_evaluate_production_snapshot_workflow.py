from __future__ import annotations

import json
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import dataclass, replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest
from scripts import evaluate_production_snapshot_workflow as runner
from scripts.production_snapshot_runtime import SnapshotBoundary, snapshot_production_runtime

from google_work_agent.ports.llm.structured_inference_contracts import (
    ActualRuntime,
    LLMInvocationError,
    OutputSchemaDefinition,
    PromptReference,
    ProviderResponsePayload,
    RuntimePolicy,
)
from google_work_agent.ports.system.contracts.workflow_execution import SelectedResourceRef
from google_work_agent.ports.system.settings_port import SettingsPatchV1


def _kwargs() -> dict[str, Any]:
    return {
        "prompt_ref": PromptReference(
            "v1",
            "owner.first",
            "v1",
            "a" * 64,
            "owner",
            "subgraph",
            "node",
            "RUNNING",
            "FIRST",
            "1",
            "1",
        ),
        "prompt_input": {"user_request": "fixture request"},
        "output_schema": OutputSchemaDefinition("1", {"type": "object"}),
        "runtime_policy": RuntimePolicy(sampling_temperature=0.05, sampling_seed=runner.SEED),
        "api_key": "not-to-be-recorded",
    }


class FakeProvider:
    provider_name = "ollama"
    model_id = runner.MODEL_ID
    runtime = ActualRuntime.LOCAL_GPU

    def __init__(self, *, assembly_error: bool = False) -> None:
        self.operations: list[str] = []
        self.assembly_error = assembly_error

    def _invoke(self, operation: str, kwargs: dict[str, Any]) -> ProviderResponsePayload:
        if self.assembly_error:
            raise ValueError("instruction assembly failed")
        self.operations.append(operation)
        runner.ollama_transport._post_json(
            endpoint="http://127.0.0.1:11434",
            path="/api/generate",
            payload={
                "model": self.model_id,
                "options": {"seed": runner.SEED, "temperature": 0.05},
                "prompt": json.dumps(kwargs["prompt_input"]),
                "think": False,
            },
            timeout_seconds=180,
        )
        return ProviderResponsePayload({"output": "fixture"}, self.model_id, None, 4, 2, 7)

    def invoke_structured(self, **kwargs: Any) -> ProviderResponsePayload:
        return self._invoke("structured", kwargs)

    def invoke_tool_call(self, **kwargs: Any) -> ProviderResponsePayload:
        return self._invoke("tool", kwargs)


def test_shared_attempt_cap_counts_structured_and_tool_including_repair(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    wires: list[dict[str, Any]] = []
    monkeypatch.setattr(runner.ollama_transport, "_post_json", lambda **kw: wires.append(kw))
    observation, provider = runner.TrialObservation(tmp_path), FakeProvider()
    wrapped = observation.decorate(provider)
    with observation.wire_observer():
        for index in range(20):
            invoke = wrapped.invoke_structured if index % 2 == 0 else wrapped.invoke_tool_call
            invoke(**_kwargs())
        with pytest.raises(LLMInvocationError, match="EXPERIMENT_BOUND_REACHED"):
            wrapped.invoke_structured(**_kwargs())
    assert len(wires) == len(provider.operations) == 20
    assert observation.metrics()["actual_wire_calls"] == 20
    assert observation.metrics()["provider_dispatch_attempts"] == 20
    assert observation.metrics()["input_tokens"] == 80
    recorded = json.loads((tmp_path / "calls.json").read_text(encoding="utf-8"))
    assert "not-to-be-recorded" not in json.dumps(recorded)
    assert recorded["calls"][0]["input"] == _kwargs()["prompt_input"]
    assert recorded["calls"][0]["wire_options"]["seed"] == runner.SEED


def test_pre_wire_failure_is_not_an_actual_llm_call(tmp_path: Path) -> None:
    observation = runner.TrialObservation(tmp_path)
    with pytest.raises(ValueError, match="assembly failed"):
        observation.decorate(FakeProvider(assembly_error=True)).invoke_structured(**_kwargs())
    assert observation.metrics()["actual_wire_calls"] == 0
    assert observation.metrics()["provider_dispatch_attempts"] == 1
    assert observation.calls[0]["error_type"] == "ValueError"


@pytest.mark.parametrize("mutation", ["provider_name", "model_id", "seed"])
def test_wrong_runtime_binding_is_rejected_before_delegate(
    tmp_path: Path,
    mutation: str,
) -> None:
    observation, provider, kwargs = runner.TrialObservation(tmp_path), FakeProvider(), _kwargs()
    if mutation == "seed":
        kwargs["runtime_policy"] = RuntimePolicy(sampling_seed=1)
    else:
        setattr(provider, mutation, "wrong")
    with pytest.raises(RuntimeError):
        observation.decorate(provider).invoke_structured(**kwargs)
    assert provider.operations == []
    assert observation.calls == []


def test_wall_bound_stops_before_new_dispatch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    observation, provider = runner.TrialObservation(tmp_path), FakeProvider()
    monkeypatch.setattr(runner.time, "monotonic", lambda: observation.started + 601)
    with pytest.raises(LLMInvocationError, match="WALL_TIMEOUT"):
        observation.decorate(provider).invoke_structured(**_kwargs())
    assert provider.operations == []
    assert observation.bound_reason == "WALL_TIMEOUT"


class FakeExecutor:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def begin_shutdown(self) -> None:
        self.calls.append("shutdown")

    def await_drained(self, _milliseconds: int) -> bool:
        self.calls.append("drain")
        return len(self.calls) >= 4


def test_fence_waits_for_real_drain_even_after_exception() -> None:
    executor = FakeExecutor()
    container = SimpleNamespace(
        schedule_run_execution=SimpleNamespace(_workflow_execution=executor)
    )
    with pytest.raises(ValueError, match="failure"), runner.drain_before_guard_release(container):
        raise ValueError("failure")
    assert executor.calls == ["shutdown", "drain", "drain", "drain"]


def test_final_observation_runs_only_after_worker_drain() -> None:
    executor = FakeExecutor()
    container = SimpleNamespace(
        schedule_run_execution=SimpleNamespace(_workflow_execution=executor)
    )
    with runner.drain_before_guard_release(
        container, on_drained=lambda: executor.calls.append("observe-final")
    ):
        assert executor.calls == []
    assert executor.calls == ["shutdown", "drain", "drain", "drain", "observe-final"]


def test_plan_is_fixed_and_detects_contract_changes(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(runner, "_head", lambda: "a" * 40)
    monkeypatch.setattr(runner, "_tree_hash", lambda _path: "b" * 64)
    monkeypatch.setattr(runner, "file_hash", lambda _path: "c" * 64)
    plan = runner.build_plan("d" * 64)
    runner.validate_plan(plan)
    assert plan["case_id"] == "CASE-CORE-005"
    assert plan["trials"] == 1
    assert plan["runtime"]["reference_time"] is None
    assert plan["resource_scope"]["selected_tasklist_ids"] == ["a2YzbGhEU0psMnlHY1B4ag"]
    assert plan["resource_scope"]["selected_calendar_ids"] is None
    plan["bounds"]["provider_dispatch_attempts"] = 21
    with pytest.raises(ValueError, match="bounds"):
        runner.validate_plan(plan)


def test_candidate_and_all_implementation_inputs_are_preregistered(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(runner, "_head", lambda: "a" * 40)
    monkeypatch.setattr(runner, "_tree_hash", lambda _path: "b" * 64)
    monkeypatch.setattr(runner, "file_hash", lambda _path: "c" * 64)
    plan = runner.build_plan("d" * 64, candidate=runner.CANDIDATE)
    runner.validate_plan(plan)
    assert plan["runtime"]["joint_authority_temperature"] == 0.0
    assert plan["runtime"]["temperature_override"] is None
    assert "scripts/production_goal_output_candidate.py" in plan["dependency_sha256"]
    assert "evaluation/request_semantic_authority_candidate.py" in plan["dependency_sha256"]
    assert any("modality" in path for path in plan["dependency_sha256"])
    plan["candidate"] = None
    with pytest.raises(ValueError, match="mismatch"):
        runner.validate_plan(plan)
    with pytest.raises(ValueError, match="unregistered"):
        runner.build_plan("d" * 64, candidate="unknown")


@dataclass
class FakeSettings:
    preferred_local_model_id: str | None = None
    preferred_llm_mode: str = "LOCAL_GPU"
    google_resource_account_id: str | None = None
    selected_tasklist_ids: tuple[str, ...] | None = None
    selected_calendar_ids: tuple[str, ...] | None = None


@dataclass
class FakeStart:
    run_id: str = "run-1"
    handoff_id: str = "handoff-1"
    applied: bool = True
    result_code: str = "APPLIED"


@dataclass
class FakeSnapshot:
    status: str
    messages: tuple[object, ...] = ()


@pytest.mark.parametrize(
    "status", ["COMPLETED", "WAITING_APPROVAL", "WAITING_CONFIRMATION", "BLOCKED"]
)
def test_trial_collects_snapshot_without_approving_or_resuming(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    status: str,
) -> None:
    calls: list[str] = []
    executor = FakeExecutor()
    fixture = SnapshotBoundary(
        runner.load_case(runner.CASE_ID), runner.composition.load_development_tool_registry()
    )
    scope = runner.selected_task_scope(fixture.case, fixture.resources)
    selected = scope["selected_resource_binding"]
    persisted_selection = SelectedResourceRef(
        "persisted-ref", "google_workspace", "task", selected["resource_id"], selected["parent_id"]
    )
    settings_state = FakeSettings()

    class Schedule:
        _workflow_execution = executor

        def __call__(self, command: object) -> Any:
            calls.append("schedule")
            return SimpleNamespace(accepted=True)

    @contextmanager
    def read_uow() -> Any:
        yield SimpleNamespace(
            evidence=SimpleNamespace(list_for_run=lambda _: ()),
            runs=SimpleNamespace(get=lambda _: None),
        )

    def update(settings: Any, **kwargs: Any) -> FakeSettings:
        nonlocal settings_state
        assert settings.preferred_local_model_id == runner.MODEL_ID
        assert settings.max_run_execution_ms is None
        assert settings.max_connector_calls_per_run is None
        calls.append("settings")
        assert settings.selected_calendar_ids is None
        settings_state = FakeSettings(
            runner.MODEL_ID,
            google_resource_account_id=settings.google_resource_account_id,
            selected_tasklist_ids=settings.selected_tasklist_ids,
        )
        return settings_state

    def start(_command: object) -> FakeStart:
        calls.append("start")
        return FakeStart()

    container = SimpleNamespace(
        settings_port=SimpleNamespace(get_settings=lambda: settings_state, update_settings=update),
        current_account_id_provider=lambda: fixture.account_id,
        create_conversation_handler=lambda cmd: calls.append("conversation"),
        issue_selection_handle=lambda cmd: cmd,
        resolve_selection_handle=lambda query: query.selection_handle,
        start_run_handler=start,
        schedule_run_execution=Schedule(),
        get_run_snapshot_handler=lambda query: FakeSnapshot(status),
        get_execution_context_handler=lambda query: SimpleNamespace(
            selected_resources=(persisted_selection,)
        ),
        read_unit_of_work_factory=read_uow,
    )
    boundary = SimpleNamespace(
        account_id=fixture.account_id,
        resources=fixture.resources,
        registry=fixture.registry,
        read_results=[{"tool_id": "tasks_get_task"}],
        events=[],
        provider=SimpleNamespace(write_calls=[]),
    )

    @contextmanager
    def runtime(*args: Any, **kwargs: Any) -> Any:
        assert kwargs["sampling_seed"] == runner.SEED
        assert kwargs["allow_loopback_model"] is True
        yield container, boundary

    monkeypatch.setattr(runner, "validate_plan", lambda _: None)
    monkeypatch.setattr(runner, "snapshot_production_runtime", runtime)
    monkeypatch.setattr(
        runner.OllamaHTTPClient,
        "list_installed_models",
        lambda _: (SimpleNamespace(model_id=runner.MODEL_ID, digest="d" * 64),),
    )
    runner.run_trial(
        {"trial_id": "trial", "model": {"digest": "d" * 64}, "resource_scope": scope}, tmp_path
    )
    report = json.loads((tmp_path / "raw.json").read_text(encoding="utf-8"))
    assert report["state"] == ("COMPLETED_OBSERVATION" if status == "COMPLETED" else "PRODUCT_STOP")
    assert report["semantic_verdict"] == "UNREVIEWED"
    assert report["run_id"] == "run-1"
    assert report["provider_write_count"] == report["provider_write_attempts"] == 0
    assert report["metrics"]["actual_wire_calls"] == 0
    assert report["read_results"] == boundary.read_results
    assert report["drained_snapshot"]["status"] == status
    assert report["drained_persisted_run"] is None
    assert report["selection_preflight"]["validated_container_refs"] == {
        "persisted-ref": [selected["parent_id"]]
    }
    assert calls == ["settings", "conversation", "start", "schedule"]


@pytest.mark.parametrize("missing", ["task", "task_list"])
def test_scope_requires_real_selected_task_and_parent_snapshot(missing: str) -> None:
    case = runner.load_case(runner.CASE_ID)
    resources = runner._case_resources(case)
    resources = [item for item in resources if item["resource_type"] != missing]
    with pytest.raises(runner.SnapshotProvisioningError, match="snapshot"):
        runner.selected_task_scope(case, resources)


@pytest.mark.parametrize("mutation", ["account_email", "parent_id", "authority"])
def test_scope_rejects_missing_account_parent_or_reread_authority(mutation: str) -> None:
    case = deepcopy(runner.load_case(runner.CASE_ID))
    resources = runner._case_resources(case)
    case["selected_resource_bindings"][0][mutation] = None
    with pytest.raises(runner.SnapshotProvisioningError, match="authority"):
        runner.selected_task_scope(case, resources)


def test_actual_settings_scope_and_signed_selection_pass_before_scheduling() -> None:
    root = runner.RESULTS_ROOT / f"snapshot-scope-preflight-{uuid4().hex}" / "runtime"
    with snapshot_production_runtime(root) as (container, boundary):
        scope = runner.selected_task_scope(boundary.case, boundary.resources)
        original_resources = deepcopy(boundary.resources)
        with pytest.raises(runner.SnapshotProvisioningError):
            runner.verify_prepared_scope(container, scope)
        settings = container.settings_port.update_settings(
            SettingsPatchV1(
                1,
                selected_tasklist_ids=tuple(scope["selected_tasklist_ids"]),
                google_resource_account_id=scope["google_resource_account_id"],
            ),
            operation_ref=str(uuid4()),
        )
        runner.verify_prepared_scope(container, scope)
        assert settings.selected_calendar_ids is None
        assert settings.default_tasklist_id == scope["selected_tasklist_ids"][0]
        assert settings.default_calendar_id is None
        scheduled: list[object] = []

        def accept_schedule(command: object) -> Any:
            scheduled.append(command)
            return SimpleNamespace(accepted=True)

        prepared_container = replace(
            container,
            schedule_run_execution=accept_schedule,
        )
        report: dict[str, Any] = {}
        result = runner.start_case(
            prepared_container, boundary, boundary.case, scope=scope, report=report
        )
        assert result.applied and len(scheduled) == 1
        assert report["selection_preflight"]["status"] == "READY"
        assert list(report["selection_preflight"]["validated_container_refs"].values()) == [
            scope["selected_tasklist_ids"]
        ]
        assert boundary.resources == original_resources
        assert boundary.read_results == []
        assert boundary.provider.write_calls == []
        wrong_account = replace(container, current_account_id_provider=lambda: "different-account")
        with pytest.raises(runner.SnapshotProvisioningError, match="account"):
            runner.verify_prepared_scope(wrong_account, scope)


def test_admitted_parent_mismatch_fails_before_any_schedule() -> None:
    fixture = SnapshotBoundary(
        runner.load_case(runner.CASE_ID), runner.composition.load_development_tool_registry()
    )
    scope = runner.selected_task_scope(fixture.case, fixture.resources)
    selected = scope["selected_resource_binding"]
    settings = FakeSettings(
        google_resource_account_id=fixture.account_id,
        selected_tasklist_ids=tuple(scope["selected_tasklist_ids"]),
    )
    container = SimpleNamespace(
        current_account_id_provider=lambda: fixture.account_id,
        settings_port=SimpleNamespace(get_settings=lambda: settings),
        get_execution_context_handler=lambda _: SimpleNamespace(
            selected_resources=(
                SelectedResourceRef(
                    "real-ref", "google_workspace", "task", selected["resource_id"], "wrong-parent"
                ),
            )
        ),
    )
    with pytest.raises(runner.SnapshotProvisioningError, match="identity"):
        runner.preflight_admitted_selection(container, fixture, "run", scope)
    assert fixture.read_results == []
    assert fixture.provider.write_calls == []


def test_unregistered_scope_is_environment_error_before_model_or_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    boundary = SnapshotBoundary(
        runner.load_case(runner.CASE_ID), runner.composition.load_development_tool_registry()
    )
    container = SimpleNamespace(
        schedule_run_execution=SimpleNamespace(_workflow_execution=FakeExecutor())
    )

    @contextmanager
    def runtime(*args: Any, **kwargs: Any) -> Any:
        yield container, boundary

    monkeypatch.setattr(runner, "validate_plan", lambda _: None)
    monkeypatch.setattr(runner, "snapshot_production_runtime", runtime)
    monkeypatch.setattr(
        runner.OllamaHTTPClient,
        "list_installed_models",
        lambda _: pytest.fail("environment gate must precede the model endpoint"),
    )
    runner.run_trial({"resource_scope": {}}, tmp_path)
    report = json.loads((tmp_path / "raw.json").read_text(encoding="utf-8"))
    assert report["state"] == "ENV_NOT_PROVISIONED"
    assert report["run_id"] is None
    assert report["metrics"]["actual_wire_calls"] == 0
    assert report["metrics"]["provider_dispatch_attempts"] == 0
    assert boundary.read_results == []
    assert boundary.provider.write_calls == []


def test_external_deadline_terminates_only_trial_child_and_duplicate_trial_is_rejected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan = {"trial_id": str(uuid4()), "head_sha": "head", "product_tree_sha256": "tree"}
    plan_path = tmp_path / "registered.json"
    plan_path.write_text(json.dumps(plan), encoding="utf-8")
    output = tmp_path / "trial"
    operations: list[object] = []

    class Process:
        exitcode = -1

        def start(self) -> None:
            operations.append("start")
            runner.write_json(output / "raw.json", {"state": "RUNNING", "run_id": "run-1"})

        def join(self, timeout: int) -> None:
            operations.append(("join", timeout))

        def is_alive(self) -> bool:
            return True

        def terminate(self) -> None:
            operations.append("terminate")

    monkeypatch.setattr(runner, "RESULTS_ROOT", tmp_path)
    monkeypatch.setattr(runner, "validate_plan", lambda _: None)
    monkeypatch.setattr(runner, "_head", lambda: "head")
    monkeypatch.setattr(runner, "_tree_hash", lambda _: "tree")
    monkeypatch.setattr(
        runner.multiprocessing,
        "get_context",
        lambda _: SimpleNamespace(
            Process=lambda **_: Process(),
        ),
    )
    assert runner.execute_plan(plan_path, output) == 2
    report = json.loads((output / "raw.json").read_text(encoding="utf-8"))
    assert report["state"] == "EXPERIMENT_BOUND_REACHED"
    assert report["bound_reason"] == "EXTERNAL_WALL_TIMEOUT"
    assert report["state_before_external_timeout"] == "RUNNING"
    assert report["run_id"] == "run-1"
    assert operations == ["start", ("join", 600), "terminate", ("join", 10)]
    with pytest.raises(FileExistsError):
        runner.execute_plan(plan_path, tmp_path / "second-output")
    assert operations.count("start") == 1
