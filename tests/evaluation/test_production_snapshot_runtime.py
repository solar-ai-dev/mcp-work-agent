from __future__ import annotations

import json
import socket
import subprocess
import threading
from dataclasses import replace
from pathlib import Path
from typing import Any, cast
from uuid import uuid4

import pytest
from scripts.production_snapshot_runtime import (
    PROJECT_ROOT,
    SnapshotBoundary,
    SnapshotSafetyError,
    load_case,
    snapshot_production_runtime,
)

from google_work_agent.api import composition
from google_work_agent.application.use_cases.conversation.create_conversation import (
    CreateConversationCommand,
)
from google_work_agent.application.use_cases.resource.issue_selection_handle import (
    IssueSelectionHandleCommand,
)
from google_work_agent.application.use_cases.resource.resolve_selection_handle import (
    ResolveSelectionHandleQuery,
)
from google_work_agent.application.use_cases.run.schedule_run_execution import (
    ScheduleRunExecutionCommand,
)
from google_work_agent.application.use_cases.run.start_run import StartRunCommand
from google_work_agent.ports.llm.structured_inference_contracts import (
    LLMErrorCode,
    LLMInvocationError,
)


def _root() -> Path:
    return PROJECT_ROOT / "evaluation/results" / f"snapshot-preflight-{uuid4().hex}" / "runtime"


def test_core005_snapshot_and_identity_are_complete() -> None:
    boundary = SnapshotBoundary(
        load_case("CASE-CORE-005"), composition.load_development_tool_registry()
    )
    selected = boundary.case["selected_resource_bindings"][0]
    binding = boundary.registry.bind_required("google_workspace", "tasks_get_task", "READ")
    result = boundary.execute_read(
        binding,
        {
            "task_id": selected["resource_id"],
            "task_list_id": selected["parent_id"],
        },
    )
    item = result.output["item"]
    assert item["resource_id"] == selected["resource_id"]
    assert item["parent_id"] == selected["parent_id"]
    assert item["payload"]["status"] == "needsAction"
    assert item["payload"]["due"] == "2026-08-10T00:00:00.000Z"
    assert item["payload"]["notes"] == "입사자 계정 발급과 장비 수령 항목을 확인할 것."
    document = json.loads(
        (
            PROJECT_ROOT
            / ("evaluation/datasets/e2e/fixtures/google_workspace/provider-snapshot-v8.json")
        ).read_text(encoding="utf-8")
    )
    original = next(
        resource
        for resource in document["resource_packs"]["ION"]["resources"]
        if resource["resource_id"] == selected["resource_id"]
    )
    for key in ("title", "notes", "due", "status"):
        assert item["payload"][key] == original[key]
    assert boundary.provider.write_calls == []
    assert boundary.read_results[0]["result"]["output"]["item"] == item
    item["payload"]["notes"] = "not the recorded snapshot"
    assert boundary.read_results[0]["result"]["output"]["item"]["payload"]["notes"] == (
        original["notes"]
    )


def test_sampling_seed_is_bound_at_composition_not_mutated_after_start(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = composition.build_production_runtime
    observed: list[int | None] = []

    def build(**kwargs: Any) -> Any:
        observed.append(kwargs.get("development_sampling_seed"))
        return original(**kwargs)

    monkeypatch.setattr(composition, "build_production_runtime", build)
    with snapshot_production_runtime(_root(), sampling_seed=20260923):
        assert observed == [20260923]


def test_actual_production_composition_is_local_before_any_connector_start() -> None:
    with snapshot_production_runtime(_root()) as (container, boundary):
        assert type(container.workflow_runtime).__name__ == "LangGraphWorkflowRuntime"
        assert container.current_account_id_provider() == boundary.account_id
        selected = boundary.case["selected_resource_bindings"][0]
        handle = container.issue_selection_handle(
            IssueSelectionHandleCommand(
                "a" * 64,
                boundary.account_id,
                "google_workspace",
                "task",
                selected["resource_id"],
                selected["parent_id"],
                None,
            )
        )
        resolved = container.resolve_selection_handle(
            ResolveSelectionHandleQuery(
                handle,
                "a" * 64,
                boundary.account_id,
                expected_resource_id=selected["resource_id"],
                expected_parent_resource_id=selected["parent_id"],
                require_parent_match=True,
            )
        )
        assert resolved.resource_id == selected["resource_id"]
        assert boundary.events == [
            {
                "boundary": "local_auth_status",
                "connector_id": "google_workspace",
            }
        ]
        for call in (
            lambda: composition.GoogleWorkspaceConnector.start(cast(Any, None)),
            lambda: composition.GitHubConnector.start(cast(Any, None)),
            lambda: composition.OsKeyringSecretStoreAdapter(service_name="forbidden"),
            lambda: subprocess.Popen(["never-start"]),
            lambda: socket.create_connection(("127.0.0.1", 11434)),
            lambda: socket.create_connection(("example.com", 443)),
            lambda: boundary.execute_write(None, {}, {}),
            lambda: boundary.start_authorization("google_workspace", None, (), "never"),
        ):
            with pytest.raises(SnapshotSafetyError):
                call()
        assert boundary.provider.write_calls == []


def test_read_without_exact_registry_binding_and_non_fixture_connector_fail_closed() -> None:
    boundary = SnapshotBoundary(
        load_case("CASE-CORE-005"), composition.load_development_tool_registry()
    )
    binding = boundary.registry.bind_required("google_workspace", "tasks_get_task", "READ")
    with pytest.raises(SnapshotSafetyError, match="registry_binding_mismatch"):
        boundary.execute_read(replace(binding, registry_entry_hash="0" * 64), {})
    with pytest.raises(SnapshotSafetyError, match="non_fixture_connector_read"):
        boundary.execute_read(replace(binding, connector_id="github"), {})
    unsupported = boundary.registry.bind_required("google_workspace", "gmail_get_message", "READ")
    with pytest.raises(ValueError, match="unsupported"):
        boundary.execute_read(unsupported, {})


def test_existing_runtime_and_non_evaluation_paths_are_not_opened(tmp_path: Path) -> None:
    with (
        pytest.raises(ValueError, match="evaluation/results"),
        snapshot_production_runtime(tmp_path),
    ):
        pytest.fail("must not construct")
    root = _root()
    root.mkdir(parents=True)
    with pytest.raises(ValueError, match="empty"), snapshot_production_runtime(root.parent):
        pytest.fail("must not construct")


def test_durable_start_reaches_actual_main_graph_without_model_or_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reached = threading.Event()
    captured: list[str] = []

    def stop_inference(_self: object, *args: object, **kwargs: object) -> object:
        ref = cast(Any, args[1] if len(args) >= 2 else kwargs["prompt_ref"])
        captured.append(str(ref.prompt_id))
        reached.set()
        raise LLMInvocationError(LLMErrorCode.LOCAL_UNAVAILABLE, "PREFLIGHT_NO_MODEL")

    monkeypatch.setattr(composition.StructuredInferenceRuntimeRouter, "infer", stop_inference)
    with snapshot_production_runtime(_root()) as (container, boundary):
        conversation_id = str(uuid4())
        container.create_conversation_handler(
            CreateConversationCommand(
                str(uuid4()),
                "a" * 64,
                conversation_id,
                boundary.account_id,
                "Isolated preflight",
                "1",
            )
        )
        selected = boundary.case["selected_resource_bindings"][0]
        handle = container.issue_selection_handle(
            IssueSelectionHandleCommand(
                "a" * 64,
                boundary.account_id,
                "google_workspace",
                "task",
                selected["resource_id"],
                selected["parent_id"],
                None,
            )
        )
        resolved = container.resolve_selection_handle(
            ResolveSelectionHandleQuery(
                handle,
                "a" * 64,
                boundary.account_id,
            )
        )
        result = container.start_run_handler(
            StartRunCommand(
                str(uuid4()),
                "b" * 64,
                conversation_id,
                boundary.case["canonical_user_prompt"],
                "RESOURCE_SELECTED",
                "LOCAL_GPU",
                "1",
                (resolved,),
            )
        )
        assert result.applied
        admitted = container.schedule_run_execution(ScheduleRunExecutionCommand(result.handoff_id))
        assert admitted.accepted
        assert reached.wait(10), "actual compiled graph did not reach its inference boundary"
    assert len(captured) == 1
    assert all(prompt.startswith("request_understanding.") for prompt in captured)
    assert boundary.provider.read_calls == []
    assert boundary.provider.write_calls == []
    assert not any(event.get("decision") == "DENY" for event in boundary.events)


def test_canonical_nested_fault_profile_is_rejected_before_runtime_creation() -> None:
    root = _root()
    with (
        pytest.raises(ValueError, match="fault profiles"),
        snapshot_production_runtime(root, case_id="CASE-STRESS-001"),
    ):
        pytest.fail("must not construct an unfaulted Stress runtime")
    assert not root.exists()


def test_missing_snapshot_pack_or_wrong_parent_never_fabricates_selection() -> None:
    registry = composition.load_development_tool_registry()
    for missing_packs in ([], ["NO_SUCH_PACK"]):
        case = load_case("CASE-CORE-005")
        case["resource_packs"] = missing_packs
        with pytest.raises(SnapshotSafetyError, match="complete local snapshot"):
            SnapshotBoundary(case, registry)
    case = load_case("CASE-CORE-005")
    case["selected_resource_bindings"][0]["parent_id"] = "wrong-parent"
    with pytest.raises(SnapshotSafetyError, match="complete local snapshot"):
        SnapshotBoundary(case, registry)


def test_model_enabled_transport_allows_only_fixed_loopback_and_product_gpu_probe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: list[tuple[str, object]] = []

    def fake_connect(_socket: object, address: object) -> None:
        observed.append(("connect", address))

    def fake_popen(args: object, **_kwargs: object) -> str:
        observed.append(("process", args))
        return "fixture-no-process"

    monkeypatch.setattr(socket.socket, "connect", fake_connect)
    monkeypatch.setattr(subprocess, "Popen", fake_popen)
    with snapshot_production_runtime(_root(), allow_loopback_model=True) as (_container, boundary):
        with socket.socket() as sock:
            sock.connect(("127.0.0.1", 11434))
            for address in (("127.0.0.1", 8000), ("1.1.1.1", 11434)):
                with pytest.raises(SnapshotSafetyError):
                    sock.connect(address)
        with pytest.raises(SnapshotSafetyError):
            socket.getaddrinfo("mail.google.com", 443)
        command = ["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader,nounits"]
        assert cast(Any, subprocess.Popen(command)) == "fixture-no-process"
        for options in ({"shell": True}, {"executable": "other.exe"}):
            with pytest.raises(SnapshotSafetyError):
                subprocess.Popen(command, **cast(Any, options))
        with pytest.raises(SnapshotSafetyError):
            subprocess.Popen(["python", "-m", "some_mcp_server"])
        assert boundary.provider.read_calls == []
    assert observed == [("connect", ("127.0.0.1", 11434)), ("process", command)]
