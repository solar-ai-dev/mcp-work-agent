from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

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
    assert adapter.execute_read(_Binding("gmail_get_thread"), {})["tool_id"] == ("gmail_get_thread")


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
    assert (
        fixture_adapter.invoke(
            boundary="FIXTURE_PRECONDITION",
            connector="gmail",
            operation="bind_provider_fixture",
            delegate=lambda: pytest.fail("bound fixture must replace the delegate"),
        )
        == malicious
    )

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


@pytest.mark.parametrize(
    "case_id,tool_id",
    [
        ("CASE-STRESS-011", "tasks_create_task"),
        ("CASE-STRESS-012", "tasks_update_task"),
        ("CASE-STRESS-019", "calendar_create_event"),
    ],
)
def test_not_sent_faults_block_the_target_effect_only(case_id: str, tool_id: str) -> None:
    checkpoints = (
        frozenset({"TASK_UPDATE_VERIFIED"}) if case_id == "CASE-STRESS-019" else frozenset()
    )
    provider = StatefulSimulatedProvider(initial_resources=[_task("task-1", notes="old")])
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


def test_unknown_update_keeps_actual_state_private_and_recovery_reads_indeterminate() -> None:
    checkpoints = {"WRITE_RESULT_UNKNOWN"}
    provider = StatefulSimulatedProvider(initial_resources=[_task("task-1", notes="old")])
    fault_adapter = FaultApplyingAdapter(FaultHarness.for_case("CASE-STRESS-016"))
    writer = FaultInjectingConnectorAdapter(
        fault_adapter=fault_adapter,
        write_delegate=provider,
        checkpoints=lambda: frozenset(checkpoints),
    )
    tool_id = "tasks_update_task"
    arguments = {"task_list_id": "list-1", "task_id": "task-1", "notes": "new"}

    result = writer.execute_write(_Binding(tool_id), arguments, {})
    assert isinstance(result, InjectedCallResult)
    assert result.safe_code == "UNKNOWN_RESULT"
    assert provider.resource("task", "task-1") is not None

    reader = FaultInjectingConnectorAdapter(
        fault_adapter=fault_adapter,
        read_delegate=provider,
        read_boundary="VERIFICATION_READ",
        checkpoints=lambda: frozenset(checkpoints),
    )
    for _ in range(2):
        with pytest.raises(InjectedFaultError) as raised:
            reader.execute_read(
                _Binding("tasks_get_task"),
                {"task_list_id": "list-1", "task_id": "task-1"},
            )
        assert raised.value.safe_code == "TIMEOUT"


def test_verification_mismatch_is_delivered_on_independent_read() -> None:
    provider = StatefulSimulatedProvider(initial_resources=[_task("task-1", notes="approved")])
    adapter = FaultInjectingConnectorAdapter(
        fault_adapter=FaultApplyingAdapter(FaultHarness.for_case("CASE-STRESS-017")),
        read_delegate=provider,
        read_boundary="VERIFICATION_READ",
        checkpoints=lambda: frozenset({"TASK_UPDATE_APPLIED"}),
    )

    result = adapter.execute_read(
        _Binding("tasks_get_task"),
        {"task_list_id": "list-1", "task_id": "task-1"},
    )
    actual = provider.resource("task", "task-1")

    assert actual["payload"]["notes"] == "approved"  # type: ignore[index]
    assert result["output"]["item"]["payload"]["notes"].endswith("[EVALUATION_MISMATCH]")


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
            adapter.execute_read(
                _Binding("tasks_get_task"),
                {"task_list_id": "list-1", "task_id": "task-1"},
            )
        assert raised.value.safe_code == "TIMEOUT"
    assert provider.resource("task", "task-1")["payload"]["notes"] == "applied"  # type: ignore[index]
    assert provider.write_calls == []


def test_wrong_task_list_get_does_not_return_same_id_from_another_list() -> None:
    provider = StatefulSimulatedProvider(initial_resources=[_task("task-1", notes="original")])

    result = provider.execute_read(
        _Binding("tasks_get_task"),
        {"task_list_id": "list-2", "task_id": "task-1"},
    )

    assert result["output"]["item"] is None


def test_simulated_provider_lists_product_shaped_fixture_resources() -> None:
    provider = StatefulSimulatedProvider(
        initial_resources=[
            {
                "resource_type": "task_list",
                "resource_id": "list-1",
                "version": "1",
                "payload": {"title": "Atlas"},
            },
            {
                "resource_type": "gmail_thread",
                "resource_id": "thread-1",
                "version": "1",
                "payload": {"subject": "Atlas 검토", "messages": []},
            },
        ]
    )

    task_lists = provider.execute_read(_Binding("tasks_list_tasklists"), {"page_size": 100})
    threads = provider.execute_read(
        _Binding("gmail_search_threads"), {"query": "Atlas", "page_size": 20}
    )

    assert task_lists["output"]["items"][0]["payload"]["title"] == "Atlas"
    assert task_lists["output"]["items"][0]["resource_id"] == "list-1"
    assert threads["output"]["items"][0]["payload"]["subject"] == "Atlas 검토"


def test_simulated_provider_gmail_search_applies_query_semantics() -> None:
    provider = StatefulSimulatedProvider(
        initial_resources=[
            {
                "resource_type": "gmail_thread",
                "resource_id": "atlas-current",
                "version": "1",
                "payload": {
                    "subject": "[Atlas] 출고 일정 확정",
                    "messages": [
                        {
                            "body": "최종 출고는 8월 19일이며 지민이 맡습니다.",
                            "sender_email": "owner@example.test",
                            "recipients": ["team@example.test"],
                            "received_at": "2026-09-07T11:40:33+09:00",
                        }
                    ],
                },
            },
            {
                "resource_type": "gmail_thread",
                "resource_id": "other",
                "version": "1",
                "payload": {
                    "subject": "다른 프로젝트 회고",
                    "messages": [
                        {
                            "body": "과거 일정입니다.",
                            "sender_email": "other@example.test",
                            "recipients": ["team@example.test"],
                            "received_at": "2026-09-07T10:00:00+09:00",
                        }
                    ],
                },
            },
        ]
    )

    result = provider.execute_read(
        _Binding("gmail_search_threads"),
        {"query": '"Atlas" {"출고" "배송"}', "page_size": 20},
    )

    assert [item["resource_id"] for item in result["output"]["items"]] == [
        "atlas-current"
    ]


def test_simulated_provider_freebusy_reads_stored_event_state() -> None:
    provider = StatefulSimulatedProvider(
        initial_resources=[
            {
                "resource_type": "calendar_event",
                "resource_id": "event-1",
                "parent_id": "calendar-1",
                "version": "1",
                "payload": {
                    "start": "2026-08-14T10:00:00+09:00",
                    "end": "2026-08-14T11:00:00+09:00",
                    "transparency": "opaque",
                },
            }
        ]
    )

    result = provider.execute_read(
        _Binding("calendar_query_freebusy"),
        {
            "calendar_ids": ["calendar-1"],
            "time_min": "2026-08-14T09:00:00+09:00",
            "time_max": "2026-08-14T12:00:00+09:00",
        },
    )

    assert result["output"]["calendars"][0]["intervals"] == [
        {
            "start": "2026-08-14T10:00:00+09:00",
            "end": "2026-08-14T11:00:00+09:00",
            "transparency": "busy",
        }
    ]


def test_wrong_task_list_update_has_no_effect() -> None:
    provider = StatefulSimulatedProvider(initial_resources=[_task("task-1", notes="original")])

    with pytest.raises(LookupError, match="list-2/task-1"):
        provider.execute_write(
            _Binding("tasks_update_task"),
            {"task_list_id": "list-2", "task_id": "task-1", "notes": "changed"},
            {},
        )

    stored = provider.execute_read(
        _Binding("tasks_get_task"),
        {"task_list_id": "list-1", "task_id": "task-1"},
    )
    assert stored["output"]["item"]["payload"]["notes"] == "original"
    assert provider.effect_counts.get("tasks_update_task", 0) == 0


def test_wrong_calendar_get_and_update_do_not_cross_parent() -> None:
    provider = StatefulSimulatedProvider(initial_resources=[_calendar_event("event-1")])

    read = provider.execute_read(
        _Binding("calendar_get_event"),
        {"calendar_id": "calendar-2", "event_id": "event-1"},
    )
    with pytest.raises(LookupError, match="calendar-2/event-1"):
        provider.execute_write(
            _Binding("calendar_update_event"),
            {
                "calendar_id": "calendar-2",
                "event_id": "event-1",
                "title": "Changed",
            },
            {},
        )

    stored = provider.execute_read(
        _Binding("calendar_get_event"),
        {"calendar_id": "calendar-1", "event_id": "event-1"},
    )
    assert read["output"]["item"] is None
    assert stored["output"]["item"]["payload"]["title"] == "Review"
    assert provider.effect_counts.get("calendar_update_event", 0) == 0


@pytest.mark.parametrize(
    ("create_tool", "resource_type", "parent_key", "parent_id", "wrong_parent"),
    (
        ("tasks_create_task", "task", "task_list_id", "list-1", "list-2"),
        (
            "calendar_create_event",
            "calendar_event",
            "calendar_id",
            "calendar-1",
            "calendar-2",
        ),
    ),
)
def test_recovery_fingerprint_search_requires_matching_parent(
    create_tool: str,
    resource_type: str,
    parent_key: str,
    parent_id: str,
    wrong_parent: str,
) -> None:
    provider = StatefulSimulatedProvider()
    fingerprint = f"{resource_type}-fingerprint"
    provider.execute_write(
        _Binding(create_tool),
        {parent_key: parent_id, "payload": {"recovery_fingerprint": fingerprint}},
        {},
    )

    wrong = provider.execute_read(
        _Binding("search_by_recovery_fingerprint"),
        {
            "resource_type": resource_type,
            "recovery_fingerprint": fingerprint,
            parent_key: wrong_parent,
        },
    )
    correct = provider.execute_read(
        _Binding("search_by_recovery_fingerprint"),
        {
            "resource_type": resource_type,
            "recovery_fingerprint": fingerprint,
            parent_key: parent_id,
        },
    )

    assert wrong["output"]["items"] == []
    assert len(correct["output"]["items"]) == 1


def test_gmail_recovery_fingerprint_search_uses_unparented_gmail_scope() -> None:
    provider = StatefulSimulatedProvider()
    provider.execute_write(
        _Binding("gmail_create_draft"),
        {"payload": {"subject": "Review", "recovery_fingerprint": "draft-fingerprint"}},
        {},
    )

    result = provider.execute_read(
        _Binding("search_by_recovery_fingerprint"),
        {
            "resource_type": "gmail_draft",
            "recovery_fingerprint": "draft-fingerprint",
        },
    )

    assert len(result["output"]["items"]) == 1


@pytest.mark.parametrize(
    ("resource", "read_tool", "update_tool", "arguments", "field"),
    (
        (
            {
                "resource_type": "task",
                "resource_id": "task-1",
                "parent_id": "list-1",
                "version": "1",
                "payload": {
                    "title": "Task",
                    "notes": "original",
                    "status": "needsAction",
                },
            },
            "tasks_get_task",
            "tasks_update_task",
            {"task_list_id": "list-1", "task_id": "task-1", "notes": "changed"},
            "notes",
        ),
        (
            {
                "resource_type": "calendar_event",
                "resource_id": "event-1",
                "parent_id": "calendar-1",
                "version": "1",
                "payload": {"title": "Review"},
            },
            "calendar_get_event",
            "calendar_update_event",
            {"calendar_id": "calendar-1", "event_id": "event-1", "title": "Changed"},
            "title",
        ),
    ),
)
def test_normal_parent_get_and_update_succeed(
    resource: dict[str, object],
    read_tool: str,
    update_tool: str,
    arguments: dict[str, object],
    field: str,
) -> None:
    provider = StatefulSimulatedProvider(initial_resources=[resource])

    before = provider.execute_read(_Binding(read_tool), arguments)
    provider.execute_write(_Binding(update_tool), arguments, {})
    after = provider.execute_read(_Binding(read_tool), arguments)

    assert before["output"]["item"] is not None
    expected = "changed" if field == "notes" else "Changed"
    assert after["output"]["item"]["payload"][field] == expected
    assert provider.effect_counts == {update_tool: 1}


def test_new_case_runtime_has_no_prior_fault_or_simulated_write_state() -> None:
    arguments = {
        "calendar_id": "calendar-1",
        "event_id": "event-1",
        "title": "Review",
    }
    first_runtime = CanonicalCaseRuntime.for_case("CASE-STRESS-013")
    first_provider = first_runtime.simulated_provider()
    first_fault = first_runtime.fault_adapter()
    first_writer = FaultInjectingConnectorAdapter(
        fault_adapter=first_fault,
        write_delegate=first_provider,
    )

    first_result = first_writer.execute_write(_Binding("calendar_create_event"), arguments, {})

    second_runtime = CanonicalCaseRuntime.for_case("CASE-STRESS-015")
    second_provider = second_runtime.simulated_provider()
    second_fault = second_runtime.fault_adapter()
    second_writer = FaultInjectingConnectorAdapter(
        fault_adapter=second_fault,
        write_delegate=second_provider,
    )
    second_result = second_writer.execute_write(_Binding("calendar_create_event"), arguments, {})

    assert isinstance(first_result, InjectedCallResult)
    assert second_result["success"] is True
    assert first_fault.records[-1].injection_number == 1
    assert second_fault.records == ()
    assert first_provider is not second_provider
    assert second_provider.effect_counts == {"calendar_create_event": 1}


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


def _calendar_event(resource_id: str) -> dict[str, object]:
    return {
        "resource_type": "calendar_event",
        "resource_id": resource_id,
        "parent_id": "calendar-1",
        "version": "1",
        "payload": {"title": "Review"},
    }


def _received(item: dict[str, object]) -> datetime:
    return datetime.fromisoformat(str(item["received_at"]))
