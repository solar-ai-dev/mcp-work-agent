from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from json import loads
from pathlib import Path
from typing import Any, cast

import pytest
from evaluation.harness.case_runtime import CanonicalCaseRuntime
from evaluation.harness.fault_adapters import (
    FaultApplyingAdapter,
    FaultInjectingConnectorAdapter,
    FaultInjectingLLMProviderAdapter,
    InjectedCallResult,
    InjectedFaultError,
)
from evaluation.harness.fault_profiles import FaultHarness, load_fault_profiles
from evaluation.harness.stateful_provider import StatefulSimulatedProvider
from tests.support.checkpoint import sqlite_checkpoint
from tests.support.fakes import DeterministicUUID
from tests.support.llm_runtime import runtime_selection, settings_view

from google_work_agent.adapters.langgraph.registry.node_registry import NodeRegistry
from google_work_agent.adapters.langgraph.registry.resume_target_registry import (
    ResumeTargetRegistry,
)
from google_work_agent.adapters.langgraph.subgraphs.retrieval.nodes.execute_read_node import (
    execute_read_node,
)
from google_work_agent.adapters.langgraph.subgraphs.retrieval.projections import (
    execute_read_projection,
)
from google_work_agent.adapters.llm.runtime.prompt_repair_schema_repairer import (
    PromptRepairSchemaRepairer,
)
from google_work_agent.adapters.llm.runtime.structured_inference_router import (
    StructuredInferenceRuntimeRouter,
)
from google_work_agent.adapters.persistence.connection import connect_sqlite
from google_work_agent.adapters.persistence.migration import apply_migrations
from google_work_agent.adapters.persistence.sqlite.unit_of_work import (
    sqlite_unit_of_work_factory,
)
from google_work_agent.adapters.system.memory.run_retrieval_cache import (
    InMemoryRunRetrievalCache,
)
from google_work_agent.application.agents.project_run_reference_time import (
    project_run_reference_time,
)
from google_work_agent.application.agents.retrieval.contracts.query_plan import (
    SourceFetchPlanV1,
    TemporalRangeConstraintV1,
)
from google_work_agent.application.agents.retrieval.execute_read import RetrievalReadExecutionV1
from google_work_agent.application.agents.retrieval.resolve_gmail_query_periods import (
    resolve_gmail_query_periods,
)
from google_work_agent.application.agents.tool_routing.contracts.tool_route_plan import (
    InputToolRouteV1,
)
from google_work_agent.application.tool_registry.load_signed_tool_registry import (
    load_signed_tool_registry,
)
from google_work_agent.application.use_cases.execution_attempt.classify_dispatch_result import (
    ClassifyDispatchResultHandler,
    ClassifyDispatchResultQueryV1,
)
from google_work_agent.application.use_cases.execution_attempt.dispatch_connector_write import (
    DispatchConnectorWriteResultV1,
)
from google_work_agent.application.use_cases.run.continue_cancel_resolution import (
    ContinueCancelResolutionCommandV1,
    ContinueCancelResolutionResultV1,
)
from google_work_agent.application.use_cases.run.guard_run_budget import (
    GuardRunBudgetHandler,
    GuardRunBudgetQueryV1,
    RunBudgetDeltaV1,
    build_default_run_budget,
)
from google_work_agent.application.use_cases.run.request_cancel import (
    RequestCancelCommand,
    RequestCancelHandler,
)
from google_work_agent.application.use_cases.run.start_run import (
    StartRunCommand,
    StartRunHandler,
)
from google_work_agent.application.use_cases.verification.verify_effect import (
    SelectedResourceRefV1,
    VerifyEffectHandler,
    VerifyEffectQueryV1,
)
from google_work_agent.application.use_cases.verification.write_verification_projection import (
    build_expected_verification_projection,
)
from google_work_agent.ports.connector.connector_failure import (
    ConnectorFailureCode,
    ConnectorOperationFailure,
)
from google_work_agent.ports.connector.connector_read_port import ConnectorReadResultV1
from google_work_agent.ports.connector.connector_write_port import ConnectorWriteResultV1
from google_work_agent.ports.llm.structured_inference_contracts import (
    ActualRuntime,
    ApprovedModelInfo,
    LLMErrorCode,
    LLMInvocationError,
    OutputSchemaDefinition,
    PromptReference,
    ProviderResponsePayload,
    RuntimePolicy,
)
from google_work_agent.ports.persistence.unit_of_work import UnitOfWork
from google_work_agent.ports.system.contracts.workflow_handoff import RunExecutionAcceptedV1
from google_work_agent.ports.system.hardware_probe_port import HardwareProfileV1


@dataclass
class _ReadDelegate:
    calls: int = 0

    def execute_read(self, binding: Any, arguments: dict[str, object]) -> ConnectorReadResultV1:
        del arguments
        self.calls += 1
        return ConnectorReadResultV1(
            1,
            binding.tool_id,
            f"request-{self.calls}",
            {"items": [{"resource_id": "evaluation-thread"}]},
            None,
            1,
        )


@pytest.mark.parametrize(
    ("case_id", "expected_code"),
    (
        ("CASE-STRESS-001", ConnectorFailureCode.RATE_LIMITED),
        ("CASE-STRESS-002", ConnectorFailureCode.UPSTREAM_UNAVAILABLE),
    ),
)
def test_fault_adapter__transient_failures__reach_execute_read_node(
    case_id: str, expected_code: ConnectorFailureCode
) -> None:
    delegate = _ReadDelegate()
    adapter = FaultInjectingConnectorAdapter(
        fault_adapter=FaultApplyingAdapter(FaultHarness.for_case(case_id)),
        read_delegate=delegate,
        read_error_factory=_connector_failure,
    )

    with pytest.raises(ConnectorOperationFailure) as raised:
        execute_read_node(_read_state(adapter, handle=case_id))

    assert raised.value.code is expected_code
    assert delegate.calls == 0


def test_connector_fault_operations__current_signed_registry__contain_tools() -> None:
    registered = {entry.tool_id for entry in load_signed_tool_registry().entries}
    connector_operations = {
        operation
        for profile in load_fault_profiles().values()
        for rule in profile.rules
        if rule.boundary
        in {
            "CONNECTOR_READ_RESULT",
            "CONNECTOR_PRE_DISPATCH",
            "CONNECTOR_POST_EFFECT",
            "CONNECTOR_DISPATCH_RESULT",
            "VERIFICATION_READ",
            "BEFORE_DEPENDENT_DISPATCH",
        }
        for operation in rule.operations
    }

    assert connector_operations <= registered


def test_reauth_fault__execute_read_node__persists_until_checkpoint() -> None:
    checkpoints: set[str] = set()
    delegate = _ReadDelegate()
    adapter = FaultInjectingConnectorAdapter(
        fault_adapter=FaultApplyingAdapter(FaultHarness.for_case("CASE-STRESS-003")),
        read_delegate=delegate,
        checkpoints=lambda: frozenset(checkpoints),
        read_error_factory=_connector_failure,
    )

    for index in range(2):
        with pytest.raises(ConnectorOperationFailure) as raised:
            execute_read_node(_read_state(adapter, handle=f"auth-{index}"))
        assert raised.value.code is ConnectorFailureCode.AUTH_REQUIRED
    checkpoints.add("REAUTH_COMPLETED")
    state = _read_state(adapter, handle="auth-completed")
    result = cast(
        RetrievalReadExecutionV1,
        execute_read_node(state)["read_execution"],
    )
    read_inputs = state["operation_inputs"]["execute_read"]
    cache = cast(InMemoryRunRetrievalCache, read_inputs["read_result_cache"])

    assert result.status == "COMPLETE"
    assert result.provider_called is True
    assert delegate.calls == 1
    assert cache.resolve_read_result("auth-completed", "run", "gmail", "q" * 64).status == (
        "EXHAUSTED"
    )


@pytest.mark.parametrize("case_id", ("CASE-CORE-033", "CASE-CORE-035"))
def test_fixed_case_time__start_run_and_gmail_query__preserve_projection(
    tmp_path: Path, case_id: str
) -> None:
    tick = [100.0]
    runtime = CanonicalCaseRuntime.for_case(case_id, monotonic=lambda: tick[0])
    database_path = _database(tmp_path / f"{case_id}.db")
    handler = StartRunHandler(
        unit_of_work_factory=sqlite_unit_of_work_factory(database_path),
        checkpoint_port=sqlite_checkpoint(database_path),
        now_ms=runtime.business_now_ms,
        id_factory=iter(("run", "message", "workflow", "handoff")).__next__,
        graph_profile="SIX_ROLE_BASELINE",
        graph_version="evaluation",
        tool_registry=load_signed_tool_registry(),
    )
    started = handler(
        StartRunCommand(
            "command",
            "a" * 64,
            "conversation",
            "이번 주 Gmail을 확인해줘",
            "AGENT_SEARCH",
            "LOCAL_GPU",
            "1",
        )
    )
    with connect_sqlite(database_path) as connection:
        budget = loads(
            connection.execute(
                "SELECT budget_json FROM runs WHERE id = ?", (started.run_id,)
            ).fetchone()[0]
        )
    reference = project_run_reference_time(budget)
    assert reference is not None
    resolved = resolve_gmail_query_periods(
        prompt_input={"request_intent": {"constraints": _relative_constraints("이번주")}},
        frozen_routes=(_gmail_route(),),
        now_ms=budget["started_at_ms"],
        timezone=reference["timezone"],
    )
    plan = _gmail_plan(resolved["gmail"])
    _, arguments = execute_read_projection.project_connector_call(
        plan, route=_gmail_route(), page_size=20
    )
    query = arguments["query"]

    assert reference["reference_time"] == "2026-08-07T09:00:00+09:00"
    assert isinstance(query, str)
    assert "after:1785682800" in query
    assert "before:1786287600" in query
    tick[0] = 100.125
    guard = GuardRunBudgetHandler()(
        GuardRunBudgetQueryV1(
            1,
            started.run_id,
            budget,
            RunBudgetDeltaV1(1, "CONNECTOR_CALL", 1),
            runtime.product_now_ms(),
        )
    )
    assert guard.allowed is True
    assert guard.elapsed_ms == 125


def test_delta_fixture__product_query__shares_last_week_window() -> None:
    runtime = CanonicalCaseRuntime.for_case("CASE-STRESS-010")
    resolved = resolve_gmail_query_periods(
        prompt_input={"request_intent": {"constraints": _relative_constraints("지난주")}},
        frozen_routes=(_gmail_route(),),
        now_ms=runtime.business_now_ms(),
        timezone="Asia/Seoul",
    )
    start_local = resolved["gmail"]["start_local"]
    end_local = resolved["gmail"]["end_local"]
    assert start_local is not None and end_local is not None
    start = datetime.fromisoformat(start_local + "+09:00")
    end = datetime.fromisoformat(end_local + "+09:00")
    fixture = runtime.simulated_fixture()

    assert (start.date().isoformat(), end.date().isoformat()) == (
        "2026-09-14",
        "2026-09-21",
    )
    assert all(
        start <= datetime.fromisoformat(item["received_at"]) < end
        for item in fixture["resources"]
    )


@pytest.mark.parametrize(
    ("case_id", "expected_attempts", "expected_error"),
    (
        ("CASE-STRESS-006", 2, None),
        ("CASE-STRESS-007", None, LLMErrorCode.OUTPUT_SCHEMA_INVALID),
    ),
)
def test_schema_faults__product_validation_and_repair__receive_injections(
    case_id: str,
    expected_attempts: int | None,
    expected_error: LLMErrorCode | None,
) -> None:
    prompt = _prompt()
    delegate = _LLMDelegate()
    provider = FaultInjectingLLMProviderAdapter(
        fault_adapter=FaultApplyingAdapter(FaultHarness.for_case(case_id)),
        delegate=delegate,
        required_fields=("answer",),
    )
    router = _llm_router(
        provider,
        PromptRepairSchemaRepairer(prompt_loader=lambda *_args, **_kwargs: prompt),
    )

    if expected_error is not None:
        with pytest.raises(LLMInvocationError) as raised:
            router.infer("LOCAL_GPU", prompt, {"request": "test"}, _schema())
        assert raised.value.code is expected_error
    else:
        result = router.infer("LOCAL_GPU", prompt, {"request": "test"}, _schema())
        assert result.structured_output == {"answer": "ok"}
        assert expected_attempts == 2
    assert delegate.calls == 2


def test_local_inference_failure__product_router__does_not_fallback() -> None:
    prompt = _prompt()
    delegate = _LLMDelegate()
    provider = FaultInjectingLLMProviderAdapter(
        fault_adapter=FaultApplyingAdapter(FaultHarness.for_case("CASE-STRESS-005")),
        delegate=delegate,
        error_factory=lambda error: LLMInvocationError(
            LLMErrorCode.LOCAL_UNAVAILABLE,
            error.safe_code,
            runtime_prerequisite=True,
        ),
    )
    router = _llm_router(
        provider,
        PromptRepairSchemaRepairer(prompt_loader=lambda *_args, **_kwargs: prompt),
    )

    with pytest.raises(LLMInvocationError) as raised:
        router.infer("LOCAL_GPU", prompt, {"request": "test"}, _schema())

    assert raised.value.code is LLMErrorCode.LOCAL_UNAVAILABLE
    assert delegate.calls == 0


@pytest.mark.parametrize(
    ("case_id", "tool_id", "delivery", "disposition"),
    (
        ("CASE-STRESS-011", "tasks_create_task", "NOT_SENT", "MARK_FAILED"),
        (
            "CASE-STRESS-013",
            "calendar_create_event",
            "MAY_HAVE_BEEN_SENT",
            "MARK_UNKNOWN_RESULT",
        ),
    ),
)
def test_write_fault_result__product_dispatch_classifier__receives_result(
    case_id: str, tool_id: str, delivery: str, disposition: str
) -> None:
    provider = StatefulSimulatedProvider()
    adapter = FaultInjectingConnectorAdapter(
        fault_adapter=FaultApplyingAdapter(FaultHarness.for_case(case_id)),
        write_delegate=provider,
        write_result_factory=_connector_write_result,
    )
    binding = load_signed_tool_registry().bind_required(
        "google_workspace",
        tool_id,
        "CREATE",
    )
    arguments = (
        {"task_list_id": "list", "task_id": "task", "title": "Task"}
        if tool_id.startswith("tasks_")
        else {"calendar_id": "calendar", "event_id": "event", "title": "Review"}
    )
    connector_result = adapter.execute_write(binding, arguments, {})
    decision = ClassifyDispatchResultHandler()(
        ClassifyDispatchResultQueryV1(
            1,
            DispatchConnectorWriteResultV1(connector_result),
        )
    )

    assert connector_result.delivery_certainty == delivery
    assert decision.disposition == disposition
    assert provider.effect_counts.get(tool_id, 0) == (1 if case_id == "CASE-STRESS-013" else 0)


def test_verification_mismatch__product_verifier__detects_difference() -> None:
    provider = StatefulSimulatedProvider(
        initial_resources=[_task_resource(notes="approved")],
        read_result_factory=_simulated_read_result,
    )
    reader = FaultInjectingConnectorAdapter(
        fault_adapter=FaultApplyingAdapter(FaultHarness.for_case("CASE-STRESS-017")),
        read_delegate=provider,
        read_boundary="VERIFICATION_READ",
        checkpoints=lambda: frozenset({"TASK_UPDATE_APPLIED"}),
        read_error_factory=_connector_failure,
    )
    result = VerifyEffectHandler(
        connector_read=reader,
        tool_registry=load_signed_tool_registry(),
    )(_task_verification_query())
    stored = provider.resource("task", "task")

    assert result.status == "MISMATCH"
    assert result.reason_codes == ["EXPECTED_EFFECT_MISMATCH"]
    assert stored is not None
    assert stored["payload"]["notes"] == "approved"


def test_verification_timeout__product_verifier__receives_without_rewrite() -> None:
    provider = StatefulSimulatedProvider(
        initial_resources=[_task_resource(notes="approved")],
        read_result_factory=_simulated_read_result,
    )
    reader = FaultInjectingConnectorAdapter(
        fault_adapter=FaultApplyingAdapter(FaultHarness.for_case("CASE-STRESS-018")),
        read_delegate=provider,
        read_boundary="VERIFICATION_READ",
        checkpoints=lambda: frozenset({"TASK_UPDATE_APPLIED"}),
        read_error_factory=_connector_failure,
    )
    verifier = VerifyEffectHandler(
        connector_read=reader,
        tool_registry=load_signed_tool_registry(),
    )

    with pytest.raises(ConnectorOperationFailure) as raised:
        verifier(_task_verification_query())

    assert raised.value.code is ConnectorFailureCode.TIMEOUT
    assert provider.write_calls == []


def test_cancel_fault__before_draft_dispatch__invokes_product_cancel_command(
    tmp_path: Path,
) -> None:
    database_path = _cancel_database(tmp_path / "cancel.db")
    factory = sqlite_unit_of_work_factory(database_path, now_ms=lambda: 10)
    continued: list[str] = []

    def continue_cancel(
        command: ContinueCancelResolutionCommandV1,
    ) -> ContinueCancelResolutionResultV1:
        continued.append(command.run_id)
        return ContinueCancelResolutionResultV1(1, "FINALIZED", "CANCELLED")

    cancel = RequestCancelHandler(
        unit_of_work_factory=cast(Callable[[], UnitOfWork], factory),
        now_ms=lambda: 10,
        checkpoint_port=sqlite_checkpoint(database_path),
        id_generator=DeterministicUUID(prefix="handoff"),
        resume_target_registry=ResumeTargetRegistry(NodeRegistry(graph_version="v1"), "v1"),
        schedule_run_execution=lambda _command: RunExecutionAcceptedV1(1, True, "ACCEPTED"),
        continue_cancel_resolution=continue_cancel,
    )
    cancel_results = []
    adapter = FaultApplyingAdapter(
        FaultHarness.for_case("CASE-STRESS-020"),
        cancel_command=lambda: cancel_results.append(
            cancel(RequestCancelCommand("run", 0, "cancel", "b" * 64))
        ),
    )
    result = adapter.invoke(
        boundary="BEFORE_DEPENDENT_DISPATCH",
        connector="gmail",
        operation="gmail_create_draft",
        checkpoints=frozenset({"CALENDAR_EVENT_VERIFIED"}),
        delegate=lambda: pytest.fail("draft dispatch must remain blocked"),
    )

    assert isinstance(result, InjectedCallResult)
    assert cancel_results[0].current_status == "CANCEL_REQUESTED"
    assert continued == ["run"]


def _read_state(reader: Any, *, handle: str) -> dict[str, Any]:
    plan: SourceFetchPlanV1 = cast(
        SourceFetchPlanV1,
        {
            "schema_version": 1,
            "route_id": "gmail",
            "connector_id": "google_workspace",
            "resource_type": "GMAIL_THREAD",
            "operation_kind": "SEARCH",
            "effective_constraints": [],
            "query_identity_hash": "q" * 64,
            "prior_read_result_handle": None,
            "detail_candidate_ref": None,
        },
    )
    return {
        "operation_inputs": {
            "execute_read": {
                "plan": plan,
                "run_id": "run",
                "binding": load_signed_tool_registry().bind_required(
                    "google_workspace", "gmail_search_threads", "READ"
                ),
                "tool_arguments": {
                    "query": "",
                    "page_size": 20,
                    "include_thread_metadata": True,
                },
                "connector_reader": reader,
                "read_result_cache": InMemoryRunRetrievalCache(),
                "read_result_handle": handle,
                "run_budget": build_default_run_budget(max_execution_ms=1_000),
                "now_ms": 0,
                "prior_query_attempts": [],
            }
        }
    }


def _connector_failure(error: InjectedFaultError) -> ConnectorOperationFailure:
    mapping = {
        "RATE_LIMITED": ConnectorFailureCode.RATE_LIMITED,
        "UPSTREAM_5XX": ConnectorFailureCode.UPSTREAM_UNAVAILABLE,
        "REAUTH_REQUIRED": ConnectorFailureCode.AUTH_REQUIRED,
        "TIMEOUT": ConnectorFailureCode.TIMEOUT,
    }
    return ConnectorOperationFailure(mapping[error.safe_code], error.safe_code, retryable=True)


def _connector_write_result(result: InjectedCallResult) -> ConnectorWriteResultV1:
    delivery = cast(Any, result.delivery_certainty)
    return ConnectorWriteResultV1(1, False, delivery, None, {}, result.safe_code)


def _simulated_read_result(
    tool_id: str, output: dict[str, Any], call_no: int
) -> ConnectorReadResultV1:
    return ConnectorReadResultV1(1, tool_id, f"simulated-{call_no}", output, None, None)


def _task_resource(*, notes: str) -> dict[str, object]:
    return {
        "resource_type": "task",
        "resource_id": "task",
        "parent_id": "list",
        "version": "1",
        "payload": {"title": "Task", "notes": notes, "status": "needsAction"},
    }


def _task_verification_query() -> VerifyEffectQueryV1:
    expected = build_expected_verification_projection(
        tool_name="tasks_update_task",
        arguments={
            "task_list_id": "list",
            "task_id": "task",
            "payload": {"notes": "approved"},
        },
    )
    return VerifyEffectQueryV1(
        "run",
        "action",
        "attempt",
        "UPDATE",
        expected,
        SelectedResourceRefV1(
            1,
            "ref",
            "google_workspace",
            "task",
            "task",
            "list",
        ),
    )


def _gmail_route() -> InputToolRouteV1:
    return {
        "route_id": "gmail",
        "resource_type": "GMAIL_THREAD",
        "connector_id": "google_workspace",
        "allowed_read_tool_ids": ["gmail_search_threads", "gmail_get_thread"],
        "required": True,
        "reason_codes": ["USER_REQUEST"],
    }


def _gmail_plan(temporal: TemporalRangeConstraintV1) -> SourceFetchPlanV1:
    return cast(
        SourceFetchPlanV1,
        {
            "schema_version": 1,
            "route_id": "gmail",
            "connector_id": "google_workspace",
            "resource_type": "GMAIL_THREAD",
            "operation_kind": "SEARCH",
            "effective_constraints": [temporal],
            "query_identity_hash": "q" * 64,
            "prior_read_result_handle": None,
            "detail_candidate_ref": None,
        },
    )


def _relative_constraints(period: str) -> list[dict[str, object]]:
    return [
        {"kind": "DATE", "field": "period", "value": [period]},
        {"kind": "TIME", "field": "temporal_axis", "value": ["MESSAGE_TIME"]},
    ]


def _database(path: Path) -> Path:
    with connect_sqlite(path) as connection:
        apply_migrations(connection)
        connection.execute(
            "INSERT INTO google_accounts (id, email, connected_at_ms) "
            "VALUES ('account', 'evaluation@example.com', 1)"
        )
        connection.execute(
            "INSERT INTO conversations VALUES "
            "('conversation', 'account', 'Evaluation', 1, 1)"
        )
    return path


def _cancel_database(path: Path) -> Path:
    with connect_sqlite(path) as connection:
        apply_migrations(connection, now_ms=lambda: 1)
        connection.execute(
            "INSERT INTO google_accounts VALUES "
            "('account', 'evaluation@example.com', NULL, 1, NULL)"
        )
        connection.execute(
            "INSERT INTO conversations VALUES "
            "('conversation', 'account', 'Evaluation', 1, 1)"
        )
        connection.execute(
            "INSERT INTO runs ("
            "id, conversation_id, entry_mode, status, langgraph_thread_id, "
            "requested_mode, actual_runtime, budget_json, version, started_at_ms, "
            "finished_at_ms) VALUES ("
            "'run', 'conversation', 'AGENT_SEARCH', 'CREATED', 'thread', "
            "'AUTO', NULL, '{}', 0, 1, NULL)"
        )
        connection.commit()
    return path


class _LLMDelegate:
    provider_name = "ollama"
    runtime = ActualRuntime.LOCAL_GPU

    def __init__(self) -> None:
        self.calls = 0

    def invoke_structured(self, **kwargs: object) -> ProviderResponsePayload:
        del kwargs
        self.calls += 1
        return ProviderResponsePayload({"answer": "ok"}, "qwen3.5:9b", None, 1, 1, 1)


class _Status:
    def get_model_for_prompt(self, _prompt_id: str) -> ApprovedModelInfo:
        return ApprovedModelInfo("qwen3.5:9b", "OLLAMA", "1", "1")


class _Credential:
    pass


class _Hardware:
    def probe(self) -> HardwareProfileV1:
        return HardwareProfileV1(
            1,
            8,
            16 * 1024**3,
            True,
            "gpu",
            8 * 1024**3,
            True,
            "1",
            True,
            "WINDOWS",
            "AMD64",
            (),
        )


def _llm_router(
    provider: Any, repairer: PromptRepairSchemaRepairer
) -> StructuredInferenceRuntimeRouter:
    model = ApprovedModelInfo("qwen3.5:9b", "OLLAMA", "1", "1")
    return StructuredInferenceRuntimeRouter(
        settings_service=lambda: settings_view(preferred_llm_mode="LOCAL_GPU"),
        runtime_selection=runtime_selection(deployment_profile="LOCAL_CAPABLE", model=model),
        status_service=cast(Any, _Status()),
        credential_service=cast(Any, _Credential()),
        hardware_probe=_Hardware(),
        api_provider_name="api",
        api_provider=provider,
        ollama_provider_factory=lambda _model: provider,
        runtime_policy=RuntimePolicy(),
        schema_repairer=repairer,
    )


def _prompt() -> PromptReference:
    return PromptReference(
        "1",
        "evaluation",
        "1",
        "hash",
        "role",
        "graph",
        "node",
        "state",
        "evaluation",
        "1",
        "1",
    )


def _schema() -> OutputSchemaDefinition:
    return OutputSchemaDefinition(
        "1",
        {
            "type": "object",
            "required": ["answer"],
            "properties": {"answer": {"type": "string"}},
            "additionalProperties": False,
        },
    )
