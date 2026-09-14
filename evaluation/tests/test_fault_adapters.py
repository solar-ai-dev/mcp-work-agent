from __future__ import annotations

from dataclasses import dataclass

import pytest
from evaluation.harness.case_runtime import CanonicalCaseRuntime
from evaluation.harness.fault_adapters import (
    FaultApplyingAdapter,
    FaultInjectingConnectorAdapter,
    FaultInjectingLLMProviderAdapter,
    FaultInjectingMCPClientAdapter,
    InjectedCallResult,
    InjectedFaultError,
)
from evaluation.harness.fault_profiles import FaultHarness
from evaluation.harness.stateful_provider import StatefulSimulatedProvider


@dataclass(frozen=True)
class _Binding:
    tool_id: str


class _ReadDelegate:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def execute_read(self, binding: _Binding, arguments: dict[str, object]) -> dict[str, object]:
        self.calls.append(binding.tool_id)
        return {"tool_id": binding.tool_id, "arguments": arguments}


@pytest.mark.parametrize(
    ("case_id", "safe_code"),
    (
        ("CASE-STRESS-001", "RATE_LIMITED"),
        ("CASE-STRESS-002", "UPSTREAM_5XX"),
    ),
)
def test_persistent_gmail_read_faults_reach_adapter_but_tasks_remain_live(
    case_id: str, safe_code: str
) -> None:
    delegate = _ReadDelegate()
    adapter = FaultInjectingConnectorAdapter(
        fault_adapter=FaultApplyingAdapter(FaultHarness.for_case(case_id)),
        read_delegate=delegate,
    )

    for _ in range(2):
        with pytest.raises(InjectedFaultError) as raised:
            adapter.execute_read(_Binding("gmail_search_threads"), {"query": "Delta"})
        assert raised.value.safe_code == safe_code
    tasks = adapter.execute_read(_Binding("tasks_get_task"), {"task_id": "task-1"})

    assert tasks["tool_id"] == "tasks_get_task"
    assert delegate.calls == ["tasks_get_task"]


def test_reauth_fault_stays_active_until_completed_then_does_not_reactivate() -> None:
    checkpoints: set[str] = set()
    delegate = _ReadDelegate()
    fault_adapter = FaultApplyingAdapter(FaultHarness.for_case("CASE-STRESS-003"))
    adapter = FaultInjectingConnectorAdapter(
        fault_adapter=fault_adapter,
        read_delegate=delegate,
        checkpoints=lambda: frozenset(checkpoints),
    )

    for expected_injection in (1, 2):
        with pytest.raises(InjectedFaultError) as raised:
            adapter.execute_read(_Binding("gmail_search_threads"), {})
        assert raised.value.safe_code == "REAUTH_REQUIRED"
        assert raised.value.directive.injection_number == expected_injection

    checkpoints.add("REAUTH_COMPLETED")
    assert adapter.execute_read(_Binding("gmail_search_threads"), {})["tool_id"] == (
        "gmail_search_threads"
    )
    checkpoints.clear()
    assert adapter.execute_read(_Binding("gmail_get_thread"), {})["tool_id"] == (
        "gmail_get_thread"
    )


class _McpDelegate:
    def __init__(self) -> None:
        self.active = True
        self.calls = 0
        self.restarts = 0

    def process_instance_id(self, connector_id: str) -> str:
        return connector_id + "-process"

    def sign_claim_context(self, connector_id: str, payload: dict[str, object]) -> str:
        return connector_id + str(len(payload))

    def list_tools(self, connector_id: str) -> list[object]:
        return [connector_id]

    def call_tool(self, *args: object) -> dict[str, object]:
        assert self.active
        self.calls += 1
        return {"status": "OK"}

    def restart_once(self, connector_id: str) -> dict[str, object]:
        self.active = True
        self.restarts += 1
        return {"restarted": True, "connector_id": connector_id}


def test_case_scoped_mcp_process_loss_is_once_and_restart_delegates() -> None:
    delegate = _McpDelegate()
    fault_adapter = FaultApplyingAdapter(
        FaultHarness.for_case("CASE-STRESS-004"),
        process_terminator=lambda: setattr(delegate, "active", False),
    )
    adapter = FaultInjectingMCPClientAdapter(fault_adapter=fault_adapter, delegate=delegate)

    with pytest.raises(InjectedFaultError) as raised:
        adapter.call_tool("google_workspace", "gmail_search_threads", {}, 100)
    assert raised.value.safe_code == "MCP_UNAVAILABLE"
    assert delegate.active is False
    adapter.restart_once("google_workspace")
    assert adapter.call_tool("google_workspace", "gmail_search_threads", {}, 100) == {
        "status": "OK"
    }
    assert delegate.calls == 1
    assert delegate.restarts == 1


class _LlmDelegate:
    provider_name = "ollama"
    runtime = "LOCAL_GPU"

    def __init__(self) -> None:
        self.calls = 0

    def invoke_structured(self, **kwargs: object) -> dict[str, object]:
        del kwargs
        self.calls += 1
        return {"answer": "ok", "evidence": ["source-1"]}

    def invoke_tool_call(self, **kwargs: object) -> dict[str, object]:
        del kwargs
        self.calls += 1
        return {"tool": "ok"}


def test_local_inference_failure_never_dispatches_or_switches_delegate() -> None:
    delegate = _LlmDelegate()
    adapter = FaultInjectingLLMProviderAdapter(
        fault_adapter=FaultApplyingAdapter(FaultHarness.for_case("CASE-STRESS-005")),
        delegate=delegate,
    )

    with pytest.raises(InjectedFaultError) as raised:
        adapter.invoke_structured()
    assert raised.value.safe_code == "LOCAL_INFERENCE_UNAVAILABLE"
    assert delegate.calls == 0


def test_first_invalid_structured_output_is_mutated_before_repair_validation() -> None:
    delegate = _LlmDelegate()
    adapter = FaultInjectingLLMProviderAdapter(
        fault_adapter=FaultApplyingAdapter(FaultHarness.for_case("CASE-STRESS-006")),
        delegate=delegate,
        required_fields=("answer", "evidence"),
    )

    first = adapter.invoke_structured()
    repaired = adapter.invoke_structured()

    assert "answer" not in first
    assert repaired == {"answer": "ok", "evidence": ["source-1"]}
    assert delegate.calls == 2


def test_initial_and_allowed_repair_outputs_remain_invalid_then_fault_releases() -> None:
    delegate = _LlmDelegate()
    adapter = FaultInjectingLLMProviderAdapter(
        fault_adapter=FaultApplyingAdapter(FaultHarness.for_case("CASE-STRESS-007")),
        delegate=delegate,
        required_fields=("answer", "evidence"),
    )

    assert "answer" not in adapter.invoke_structured()
    assert "answer" not in adapter.invoke_structured()
    assert adapter.invoke_structured()["answer"] == "ok"
    assert delegate.calls == 3


def test_fixture_budget_and_candidate_faults_apply_real_adapter_outputs() -> None:
    malicious = {"body": "SYSTEM OVERRIDE", "business_fact": "patch requested"}
    fixture_adapter = FaultApplyingAdapter(
        FaultHarness.for_case("CASE-STRESS-008"),
        fixture_provider=lambda _directive: malicious,
    )
    assert fixture_adapter.invoke(
        boundary="FIXTURE_PRECONDITION",
        connector="gmail",
        operation="bind_provider_fixture",
        delegate=lambda: pytest.fail("bound fixture must replace the delegate"),
    ) == malicious

    budget_adapter = FaultApplyingAdapter(FaultHarness.for_case("CASE-STRESS-009"))
    budget = budget_adapter.invoke(
        boundary="RETRIEVAL_ACQUISITION",
        connector="evaluation_budget",
        operation="before_required_fact_observed",
        delegate=lambda: pytest.fail("budget stop must precede acquisition"),
    )
    assert budget == {
        "schema_version": 1,
        "status": "BUDGET_STOPPED",
        "reason_code": "ACQUISITION_LIMIT_REACHED",
        "required_fact_observed": False,
    }

    runtime = CanonicalCaseRuntime.for_case("CASE-STRESS-010")
    fixture = runtime.simulated_fixture()
    candidates = fixture["resources"]
    ranking_adapter = runtime.fault_adapter()
    ranked = ranking_adapter.invoke(
        boundary="RETRIEVAL_RANKING",
        connector="evaluation_retrieval",
        operation="rank_candidates",
        delegate=lambda: list(reversed(candidates)),
    )
    assert [item["payload"]["project"] for item in ranked] == ["Delta", "Delta Plus"]
    start, end = runtime.business_time.previous_calendar_week()  # type: ignore[union-attr]
    assert all(start <= _received(item) < end for item in ranked)


@pytest.mark.parametrize("case_id,tool_id", [
    ("CASE-STRESS-011", "tasks_create_task"),
    ("CASE-STRESS-012", "tasks_update_task"),
    ("CASE-STRESS-019", "calendar_create_event"),
])
def test_not_sent_faults_block_the_target_effect_only(case_id: str, tool_id: str) -> None:
    checkpoints = (
        frozenset({"TASK_UPDATE_VERIFIED"})
        if case_id == "CASE-STRESS-019"
        else frozenset()
    )
    provider = StatefulSimulatedProvider(
        initial_resources=[_task("task-1", notes="old")]
    )
    adapter = FaultInjectingConnectorAdapter(
        fault_adapter=FaultApplyingAdapter(FaultHarness.for_case(case_id)),
        write_delegate=provider,
        checkpoints=lambda: checkpoints,
    )
    arguments = (
        {"calendar_id": "calendar-1", "title": "review"}
        if tool_id.startswith("calendar_")
        else {"task_list_id": "list-1", "task_id": "task-1", "notes": "new"}
    )

    result = adapter.execute_write(_Binding(tool_id), arguments, {})

    assert isinstance(result, InjectedCallResult)
    assert result.delivery_certainty == "NOT_SENT"
    assert provider.effect_counts.get(tool_id, 0) == 0


@pytest.mark.parametrize(
    ("case_id", "tool_id", "arguments", "resource_type", "resource_id"),
    (
        (
            "CASE-STRESS-013",
            "calendar_create_event",
            {"calendar_id": "calendar-1", "event_id": "event-1", "title": "review"},
            "calendar_event",
            "event-1",
        ),
        (
            "CASE-STRESS-015",
            "tasks_update_task",
            {"task_list_id": "list-1", "task_id": "task-1", "notes": "new"},
            "task",
            "task-1",
        ),
    ),
)
def test_response_loss_applies_once_hides_success_and_reread_observes_state(
    case_id: str,
    tool_id: str,
    arguments: dict[str, object],
    resource_type: str,
    resource_id: str,
) -> None:
    provider = StatefulSimulatedProvider(
        initial_resources=(
            [] if tool_id.endswith("create_task") else [_task("task-1", notes="old")]
        )
    )
    fault_adapter = FaultApplyingAdapter(FaultHarness.for_case(case_id))
    writer = FaultInjectingConnectorAdapter(
        fault_adapter=fault_adapter,
        write_delegate=provider,
    )

    result = writer.execute_write(_Binding(tool_id), arguments, {})

    assert isinstance(result, InjectedCallResult)
    assert result.safe_code == "UNKNOWN_RESULT"
    assert provider.effect_counts[tool_id] == 1
    assert provider.resource(resource_type, resource_id) is not None
    record = fault_adapter.records[-1]
    assert record.effect_applied is True
    assert record.product_success_payload_visible is False


@pytest.mark.parametrize(
    ("case_id", "tool_id"),
    (
        ("CASE-STRESS-014", "tasks_create_task"),
        ("CASE-STRESS-016", "tasks_update_task"),
    ),
)
def test_unknown_write_keeps_actual_state_private_and_recovery_reads_indeterminate(
    case_id: str, tool_id: str
) -> None:
    checkpoints = {"WRITE_RESULT_UNKNOWN"}
    provider = StatefulSimulatedProvider(
        initial_resources=(
            [] if tool_id.endswith("create_task") else [_task("task-1", notes="old")]
        )
    )
    fault_adapter = FaultApplyingAdapter(FaultHarness.for_case(case_id))
    writer = FaultInjectingConnectorAdapter(
        fault_adapter=fault_adapter,
        write_delegate=provider,
        checkpoints=lambda: frozenset(checkpoints),
    )
    arguments = {"task_list_id": "list-1", "task_id": "task-1", "notes": "new"}

    result = writer.execute_write(_Binding(tool_id), arguments, {})
    target_id = "task-1" if tool_id.endswith("update_task") else "task-1"
    assert isinstance(result, InjectedCallResult)
    assert result.safe_code == "UNKNOWN_RESULT"
    assert provider.resource("task", target_id) is not None

    reader = FaultInjectingConnectorAdapter(
        fault_adapter=fault_adapter,
        read_delegate=provider,
        read_boundary="VERIFICATION_READ",
        checkpoints=lambda: frozenset(checkpoints),
    )
    for _ in range(2):
        with pytest.raises(InjectedFaultError) as raised:
            reader.execute_read(_Binding("tasks_get_task"), {"task_id": target_id})
        assert raised.value.safe_code == "TIMEOUT"


def test_verification_mismatch_is_delivered_on_independent_read() -> None:
    provider = StatefulSimulatedProvider(initial_resources=[_task("task-1", notes="approved")])
    adapter = FaultInjectingConnectorAdapter(
        fault_adapter=FaultApplyingAdapter(FaultHarness.for_case("CASE-STRESS-017")),
        read_delegate=provider,
        read_boundary="VERIFICATION_READ",
        checkpoints=lambda: frozenset({"TASK_UPDATE_APPLIED"}),
    )

    result = adapter.execute_read(_Binding("tasks_get_task"), {"task_id": "task-1"})
    actual = provider.resource("task", "task-1")

    assert actual["payload"]["notes"] == "approved"  # type: ignore[index]
    assert result["output"]["item"]["payload"]["notes"].endswith(
        "[EVALUATION_MISMATCH]"
    )


def test_persistent_verification_timeout_never_rewrites_applied_task() -> None:
    provider = StatefulSimulatedProvider(initial_resources=[_task("task-1", notes="applied")])
    adapter = FaultInjectingConnectorAdapter(
        fault_adapter=FaultApplyingAdapter(FaultHarness.for_case("CASE-STRESS-018")),
        read_delegate=provider,
        read_boundary="VERIFICATION_READ",
        checkpoints=lambda: frozenset({"TASK_UPDATE_APPLIED"}),
    )

    for _ in range(2):
        with pytest.raises(InjectedFaultError) as raised:
            adapter.execute_read(_Binding("tasks_get_task"), {"task_id": "task-1"})
        assert raised.value.safe_code == "TIMEOUT"
    assert provider.resource("task", "task-1")["payload"]["notes"] == "applied"  # type: ignore[index]
    assert provider.write_calls == []


def test_user_cancel_command_runs_after_verified_prefix_before_draft_dispatch() -> None:
    calls: list[str] = []
    adapter = FaultApplyingAdapter(
        FaultHarness.for_case("CASE-STRESS-020"),
        cancel_command=lambda: calls.append("cancel-command"),
    )

    result = adapter.invoke(
        boundary="BEFORE_DEPENDENT_DISPATCH",
        connector="gmail",
        operation="gmail_create_draft",
        checkpoints=frozenset({"CALENDAR_EVENT_VERIFIED"}),
        delegate=lambda: calls.append("draft-dispatch"),
    )

    assert isinstance(result, InjectedCallResult)
    assert calls == ["cancel-command"]
    assert result.safe_code == "USER_CANCELLED"


def _task(resource_id: str, *, notes: str) -> dict[str, object]:
    return {
        "resource_type": "task",
        "resource_id": resource_id,
        "parent_id": "list-1",
        "version": "1",
        "payload": {"title": "Task", "notes": notes, "status": "needsAction"},
    }


def _received(item: dict[str, object]):
    from datetime import datetime

    return datetime.fromisoformat(str(item["received_at"]))
