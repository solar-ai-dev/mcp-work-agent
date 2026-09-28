from __future__ import annotations

import json
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest
from scripts import evaluate_production_snapshot_workflow as runner

from google_work_agent.ports.llm.structured_inference_contracts import (
    ActualRuntime,
    LLMInvocationError,
    OutputSchemaDefinition,
    PromptReference,
    ProviderResponsePayload,
    RuntimePolicy,
)


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


def test_plan_is_fixed_and_detects_contract_changes(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(runner, "_head", lambda: "a" * 40)
    monkeypatch.setattr(runner, "_tree_hash", lambda _path: "b" * 64)
    monkeypatch.setattr(runner, "file_hash", lambda _path: "c" * 64)
    plan = runner.build_plan("d" * 64)
    runner.validate_plan(plan)
    assert plan["case_id"] == "CASE-CORE-005"
    assert plan["trials"] == 1
    assert plan["runtime"]["reference_time"] is None
    plan["bounds"]["provider_dispatch_attempts"] = 21
    with pytest.raises(ValueError, match="bounds"):
        runner.validate_plan(plan)


@dataclass
class FakeSettings:
    preferred_local_model_id: str | None = None
    preferred_llm_mode: str = "LOCAL_GPU"


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
        assert settings.preferred_local_model_id == runner.MODEL_ID
        assert settings.max_run_execution_ms is None
        assert settings.max_connector_calls_per_run is None
        calls.append("settings")
        return FakeSettings(runner.MODEL_ID)

    def start(_command: object) -> FakeStart:
        calls.append("start")
        return FakeStart()

    container = SimpleNamespace(
        settings_port=SimpleNamespace(get_settings=lambda: FakeSettings(), update_settings=update),
        create_conversation_handler=lambda cmd: calls.append("conversation"),
        issue_selection_handle=lambda cmd: cmd,
        resolve_selection_handle=lambda query: query.selection_handle,
        start_run_handler=start,
        schedule_run_execution=Schedule(),
        get_run_snapshot_handler=lambda query: FakeSnapshot(status),
        read_unit_of_work_factory=read_uow,
    )
    boundary = SimpleNamespace(
        account_id="fixture-account",
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
    runner.run_trial({"trial_id": "trial", "model": {"digest": "d" * 64}}, tmp_path)
    report = json.loads((tmp_path / "raw.json").read_text(encoding="utf-8"))
    assert report["state"] == ("COMPLETED_OBSERVATION" if status == "COMPLETED" else "PRODUCT_STOP")
    assert report["semantic_verdict"] == "UNREVIEWED"
    assert report["run_id"] == "run-1"
    assert report["provider_write_count"] == report["provider_write_attempts"] == 0
    assert report["metrics"]["actual_wire_calls"] == 0
    assert report["read_results"] == boundary.read_results
    assert calls == ["settings", "conversation", "start", "schedule"]


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
