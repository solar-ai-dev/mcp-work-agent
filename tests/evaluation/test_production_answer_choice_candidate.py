"""088 actual router/assembly/Planning gates with synthetic HTTP responses only.

No Provider data or model is called. Shape, dispatch and authority checks here
do not establish that a generated answer preserves the user's business meaning.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from copy import deepcopy
from dataclasses import replace
from itertools import count
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import Mock

import pytest
from scripts import evaluate_read_answer_handoff as handoff
from scripts import evaluate_task_completion_fact as history
from scripts import production_answer_choice_candidate as candidate
from tests.support.llm_runtime import runtime_selection, settings_view

from google_work_agent.adapters.langgraph.confirmation_llm_runtime import (
    ConfirmationAwareLLMRuntime,
)
from google_work_agent.adapters.langgraph.profiles.profile_registry import GraphProfile
from google_work_agent.adapters.llm.ollama import transport
from google_work_agent.adapters.llm.ollama.structured_inference import (
    OllamaStructuredInferenceAdapter,
)
from google_work_agent.adapters.llm.runtime.prompt_repair_schema_repairer import (
    PromptRepairSchemaRepairer,
)
from google_work_agent.adapters.llm.runtime.structured_inference_router import (
    StructuredInferenceRuntimeRouter,
)
from google_work_agent.adapters.system.memory.retrieval_evidence_store import RunScopedEvidenceStore
from google_work_agent.application.prompt_runtime.assemble_prompt import (
    PromptAssemblyError,
    assemble_prompt,
)
from google_work_agent.application.prompt_runtime.prompt_registry import (
    DEVELOPMENT_SMOKE,
    EVALUATION,
    PRODUCT_RELEASE,
    PromptRegistry,
)
from google_work_agent.application.use_cases.run.account_provider_dispatch import (
    account_provider_dispatch,
    current_provider_dispatch_run_id,
    provider_dispatch_budget_scope,
    provider_dispatch_execution_scope,
)
from google_work_agent.application.use_cases.run.guard_run_budget import build_default_run_budget
from google_work_agent.ports.llm.structured_inference_contracts import (
    ApprovedModelInfo,
    LLMInvocationError,
    RuntimePolicy,
)
from google_work_agent.ports.system.contracts.workflow_execution import (
    WorkflowCorrelationContext,
    WorkflowStartRequest,
)
from google_work_agent.ports.system.external_call_trace_port import ExternalCallTraceHandleV1

RUN_ID = "088-synthetic-run"


@pytest.fixture
def task_input() -> tuple[dict[str, Any], dict[str, Any]]:
    return history.synthetic_completed()


def _harness(
    monkeypatch: pytest.MonkeyPatch,
    projection: dict[str, Any],
    snapshots: dict[str, Any],
    responses: list[Any],
    *,
    used: int = 0,
    repair_budget: int = 1,
    snapshot_fault: str | None = None,
) -> SimpleNamespace:
    calls: list[dict[str, Any]] = []

    def post(**kwargs: Any) -> dict[str, Any]:
        calls.append(deepcopy(kwargs))
        assert len(calls) <= len(responses), "unbudgeted fake dispatch"
        value = responses[len(calls) - 1]
        return {
            "response": value if isinstance(value, str) else json.dumps(value),
            "model": "qwen3.5:9b",
            "prompt_eval_count": 11,
            "eval_count": 7,
            "total_duration": 1_000_000,
            "thinking": "HIDDEN_NOT_FOR_STATE_OR_TRACE",
        }

    monkeypatch.setattr(transport, "_post_json", post)
    registry = PromptRegistry()
    model = ApprovedModelInfo("qwen3.5:9b", "OLLAMA", "1", "1")
    leaf = OllamaStructuredInferenceAdapter(
        "ollama",
        transport.OllamaHTTPClient(),
        "http://127.0.0.1:11434",
        model.model_id,
        assemble_instruction_text=lambda ref, value: assemble_prompt(
            ref,
            value,
            registry=registry,
            execution_scope=EVALUATION,
        ),
    )
    provider = candidate.decorate_answer_choice_provider(leaf)
    trace = Mock()
    trace.begin_external_call.side_effect = [
        ExternalCallTraceHandleV1(1, f"trace-{index}") for index in range(4)
    ]
    events = Mock()
    router = StructuredInferenceRuntimeRouter(
        settings_service=lambda: settings_view(
            preferred_llm_mode="LOCAL_GPU",
            preferred_local_model_id=model.model_id,
        ),
        runtime_selection=runtime_selection(deployment_profile="LOCAL_CAPABLE", model=model),
        status_service=cast(Any, SimpleNamespace(get_model_for_prompt=lambda _id: model)),
        credential_service=cast(Any, SimpleNamespace()),
        hardware_probe=cast(
            Any,
            SimpleNamespace(
                probe=lambda: SimpleNamespace(
                    architecture="AMD64",
                    cpu_logical_cores=8,
                    ram_total_bytes=16 * 1024**3,
                    gpu_present=True,
                    gpu_name="fixture",
                    vram_total_bytes=8 * 1024**3,
                    local_runtime_eligible=True,
                    local_runtime_reason_codes=(),
                )
            ),
        ),
        api_provider_name="unused",
        api_provider=provider,
        ollama_provider_factory=lambda _model: provider,
        runtime_policy=RuntimePolicy(
            sampling_seed=20260923,
            structured_output_repair_budget=repair_budget,
        ),
        before_provider_dispatch=account_provider_dispatch,
        run_context_provider=current_provider_dispatch_run_id,
        schema_repairer=PromptRepairSchemaRepairer(execution_scope=EVALUATION),
        external_call_trace=trace,
        event_recorder=events,
    )
    store = RunScopedEvidenceStore()
    store.put(run_id=RUN_ID, evidence_drafts=cast(Any, deepcopy(projection["evidence"])))
    for item in projection["evidence"]:
        ref = item.get("evidence_ref") or item.get("evidence_id")
        if ref not in snapshots or snapshot_fault == "missing":
            continue
        snapshot = deepcopy(snapshots[ref])
        if snapshot_fault == "stale":
            snapshot["title"] = "Changed without a matching version"
        store.put_resource_snapshot(
            run_id="foreign-run" if snapshot_fault == "foreign" else RUN_ID,
            resource_handle=item["resource_handle"],
            source_version_ref=item["locator"]["source_version_ref"],
            snapshot=snapshot,
        )
    budget = build_default_run_budget()
    budget["llm_calls_used"] = used
    state: dict[str, Any] = {
        "run_id": RUN_ID,
        "user_request": projection["user_request"],
        "request_intent": deepcopy(projection["request_intent"]),
        "tool_route_plan": {"output_plan": {"output_mode": "ANSWER", "output_routes": []}},
        "retrieval_result": {
            **{
                key: deepcopy(value)
                for key, value in projection.items()
                if key not in {"user_request", "request_intent", "answer_outline", "evidence"}
            },
            "evidence_refs": [item["evidence_id"] for item in projection["evidence"]],
        },
        "evidence": deepcopy(projection["evidence"]),
        "answer_outline": deepcopy(projection["answer_outline"]),
        "retry_budget": budget,
        "trace_context": {},
        "__request__": WorkflowStartRequest(
            RUN_ID,
            "conversation",
            "workflow",
            "AGENT_SEARCH",
            "LOCAL_GPU",
            projection["user_request"],
            (),
            WorkflowCorrelationContext("req", None, "v1"),
            budget,
        ),
    }
    observations: list[dict[str, object]] = []
    identifiers = count(1)
    graph = candidate.AnswerChoicePlanningSubgraph(
        observations=observations,
        llm_runtime=router,
        prompt_execution_scope=EVALUATION,
        evidence_store=store,
        id_factory=lambda: f"artifact-{next(identifiers)}",
        graph_profile=GraphProfile.SIX_ROLE_BASELINE,
        merge_decision=lambda current, update, _decision: {**current, **update},
    )
    return SimpleNamespace(
        graph=graph,
        state=state,
        budget=budget,
        calls=calls,
        observations=observations,
        router=router,
        events=events,
        trace=trace,
        provider=provider,
        registry=registry,
    )


def _run(harness: SimpleNamespace, *, compiled: bool = False) -> dict[str, Any]:
    with (
        provider_dispatch_execution_scope(run_id=RUN_ID),
        provider_dispatch_budget_scope(harness.budget),
    ):
        if compiled:
            return cast(dict[str, Any], harness.graph.build().invoke(harness.state))
        return cast(dict[str, Any], harness.graph._compose_answer_node(harness.state))


def _fact() -> dict[str, Any]:
    return {"mode": "FACT_REFERENCES", "items": [{"evidence_ref": "e-task", "field": "status"}]}


def _prose(answer: str = "작업은 완료되었고 장비 수령 항목을 확인해야 합니다.") -> dict[str, Any]:
    return {"mode": "PROSE", "schema_version": 2, "answer": answer, "evidence_refs": ["e-task"]}


@pytest.mark.parametrize("response", [_fact(), _prose()], ids=["facts", "prose"])
def test_compiled_planning__actual_router_and_registry__materializes_without_second_call(
    monkeypatch: pytest.MonkeyPatch,
    task_input: tuple[dict[str, Any], dict[str, Any]],
    response: dict[str, Any],
) -> None:
    projection, snapshots = task_input
    before = deepcopy(task_input)
    harness = _harness(monkeypatch, projection, snapshots, [response])
    result = _run(harness, compiled=True)
    assert len(harness.calls) == result["retry_budget"]["llm_calls_used"] == 1
    assert result["trace_context"]["llm_call_count"] == 1
    answer = result["planning_result"]
    assert answer["evidence_refs"] == ["e-task"]
    assert answer["answer"] == (
        "상태: 완료" if response["mode"] == "FACT_REFERENCES" else response["answer"]
    )
    payload = harness.calls[0]["payload"]
    body = json.loads(payload["prompt"])
    assert body["prompt_ref"]["prompt_id"] == candidate.EVALUATION_SLOT
    assert result["trace_context"]["prompt_refs"][-1]["prompt_id"] == candidate.EVALUATION_SLOT
    assert (
        harness.observations[-1]["trace_prompt_ref"]["content_hash"]
        == body["prompt_ref"]["content_hash"]
    )
    assert body["input"] == projection and task_input == before
    assert "Product-wide context:" in payload["system"]
    assert "Allowed current-Run input projection (JSON):" in payload["system"]
    assert "source_snapshots" not in body["input"]
    assert all(next(iter(branch["properties"])) == "mode" for branch in payload["format"]["oneOf"])
    assert "HIDDEN_NOT_FOR_STATE_OR_TRACE" not in repr(
        (result, harness.observations, harness.events.mock_calls)
    )
    assert candidate._active_registry.get() is None
    assert candidate._active_invocation.get() is None


def test_compose__catalog_absent_calendar__delegates_exact_product_wire(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = next(
        case for case in handoff.fixtures() if case["case_id"] == "SYNTHETIC_CALENDAR_LOCATION"
    )
    projection: dict[str, Any] = {}

    def capture(prompt_id: str, prompt_input: Mapping[str, object]) -> Mapping[str, object]:
        assert prompt_id == "planning.compose_answer"
        projection.update(deepcopy(prompt_input))
        raise handoff._CapturedFirst

    with pytest.raises(handoff._CapturedFirst):
        handoff._pipeline(case, capture, {})
    original = handoff._wire_projection(projection)["wire_payload"]
    value = {"schema_version": 2, "answer": "일정 시간과 장소입니다.", "evidence_refs": ["e-event"]}
    harness = _harness(monkeypatch, projection, case["pipeline_input"]["source_snapshots"], [value])
    result = _run(harness)
    assert len(harness.calls) == 1
    assert json.dumps(harness.calls[0]["payload"]) == json.dumps(original)
    assert result["planning_result"]["answer"] == value["answer"]


def test_compose__schema_invalid_first__uses_existing_repair_and_counts_both_dispatches(
    monkeypatch: pytest.MonkeyPatch,
    task_input: tuple[dict[str, Any], dict[str, Any]],
) -> None:
    harness = _harness(monkeypatch, *task_input, ["{", _fact()])
    result = _run(harness)
    assert len(harness.calls) == result["retry_budget"]["llm_calls_used"] == 2
    assert result["trace_context"]["llm_call_count"] == 2
    first, repair = [json.loads(call["payload"]["prompt"]) for call in harness.calls]
    assert first["prompt_ref"] == repair["prompt_ref"]
    assert set(repair["input"]) == {"base_projection", "candidate_output", "failure_record"}
    assert repair["input"]["base_projection"] == task_input[0]
    assert "Bounded failure instruction" in harness.calls[1]["payload"]["system"]
    completed = [
        call.kwargs["attributes"]
        for call in harness.events.record.call_args_list
        if call.kwargs["event_name"] == "LLM_CALL_COMPLETED"
    ]
    assert completed[-1]["input_tokens"] == 22 and completed[-1]["output_tokens"] == 14
    assert harness.trace.begin_external_call.call_count == 2


def test_compose__schema_repair_also_invalid__stops_after_existing_bound(
    monkeypatch: pytest.MonkeyPatch,
    task_input: tuple[dict[str, Any], dict[str, Any]],
) -> None:
    harness = _harness(monkeypatch, *task_input, ["{", "{"])
    with pytest.raises(LLMInvocationError):
        _run(harness)
    assert len(harness.calls) == harness.budget["llm_calls_used"] == 2


def test_compose__invalid_prose__keeps_product_semantic_repair_owner(
    monkeypatch: pytest.MonkeyPatch,
    task_input: tuple[dict[str, Any], dict[str, Any]],
) -> None:
    repair = {
        "schema_version": 1,
        "sections": [
            {
                "heading": "메모",
                "items": [{"label": "확인", "value": "장비 수령 항목을 확인할 것."}],
            },
        ],
        "evidence_refs": ["e-task"],
    }
    harness = _harness(monkeypatch, *task_input, [_prose('{"sections":[]}'), repair])
    result = _run(harness)
    bodies = [json.loads(call["payload"]["prompt"]) for call in harness.calls]
    assert len(bodies) == result["retry_budget"]["llm_calls_used"] == 2
    assert bodies[0]["prompt_ref"]["prompt_id"] == candidate.EVALUATION_SLOT
    assert bodies[1]["prompt_ref"]["prompt_id"] == "planning.compose_answer"
    assert (
        bodies[1]["input"]["failure_record"]["failure_reason_code"]
        == "COMPOSE_ANSWER_PROSE_INVALID"
    )
    assert bodies[1]["input"]["candidate_output"] is None
    assert "mode" not in bodies[1]["output_schema"]["properties"]
    assert "장비 수령 항목" in result["planning_result"]["answer"]


def test_compose__exhausted_budget__rejects_before_http_dispatch(
    monkeypatch: pytest.MonkeyPatch,
    task_input: tuple[dict[str, Any], dict[str, Any]],
) -> None:
    harness = _harness(monkeypatch, *task_input, [_fact()], used=100)
    with pytest.raises(LLMInvocationError, match="ABSOLUTE_LLM_LIMIT_EXHAUSTED"):
        _run(harness)
    assert harness.calls == [] and harness.budget["llm_calls_used"] == 100


@pytest.mark.parametrize("fault", ["foreign", "stale", "missing"])
def test_compose__unbound_snapshot__does_not_offer_or_materialize_fact_output(
    monkeypatch: pytest.MonkeyPatch,
    task_input: tuple[dict[str, Any], dict[str, Any]],
    fault: str,
) -> None:
    harness = _harness(monkeypatch, *task_input, [_fact()], snapshot_fault=fault, repair_budget=0)
    with pytest.raises(LLMInvocationError):
        _run(harness)
    assert len(harness.calls) == 1
    body = json.loads(harness.calls[0]["payload"]["prompt"])
    assert body["prompt_ref"]["prompt_id"] == "planning.compose_answer"
    assert "oneOf" not in body["output_schema"]
    assert "mode" not in body["output_schema"]["properties"]


@pytest.mark.parametrize("tamper", ["request", "field", "ref"])
def test_evaluation_registry__input_or_reference_tamper__fails_before_generation(
    task_input: tuple[dict[str, Any], dict[str, Any]],
    tamper: str,
) -> None:
    projection = deepcopy(task_input[0])
    product = PromptRegistry()
    registry = candidate._EvaluationRegistry(
        product_registry=product,
        product_ref=product.lookup_for_evaluation("planning.compose_answer"),
        projection=projection,
    )
    ref = registry.prompt_ref
    if tamper == "request":
        projection["user_request"] += " changed"
    elif tamper == "field":
        projection["expected_answer"] = "not permitted"
    else:
        ref = replace(ref, content_hash="0" * 64)
    with pytest.raises((ValueError, PromptAssemblyError)):
        assemble_prompt(ref, projection, registry=cast(Any, registry), execution_scope=EVALUATION)


@pytest.mark.parametrize("change_sibling", [False, True])
def test_schema_repair__declared_prose_union__preserves_unaffected_citation_authority(
    monkeypatch: pytest.MonkeyPatch,
    task_input: tuple[dict[str, Any], dict[str, Any]],
    change_sibling: bool,
) -> None:
    first = {**_prose(), "answer": 42}
    repair = {**_prose(), "evidence_refs": [] if change_sibling else ["e-task"]}
    harness = _harness(monkeypatch, *task_input, [first, repair])
    if change_sibling:
        with pytest.raises(LLMInvocationError, match="outside the reported failure scope"):
            _run(harness)
    else:
        assert _run(harness)["planning_result"]["evidence_refs"] == ["e-task"]
    assert len(harness.calls) == harness.budget["llm_calls_used"] == 2
    repair_input = json.loads(harness.calls[1]["payload"]["prompt"])["input"]
    assert "$.answer" in repair_input["failure_record"]["affected_field_paths"]
    assert candidate._active_registry.get() is None
    assert candidate._active_invocation.get() is None


def test_semantic_callable__physical_invocation_closed__cannot_dispatch_again(
    monkeypatch: pytest.MonkeyPatch,
    task_input: tuple[dict[str, Any], dict[str, Any]],
) -> None:
    harness = _harness(monkeypatch, *task_input, [_fact()])
    captured: list[Any] = []
    original = harness.graph._semantic_invoker

    def capture(state: Any) -> Any:
        invoke = original(state)
        captured.append(invoke)
        return invoke

    monkeypatch.setattr(harness.graph, "_semantic_invoker", capture)
    _run(harness)
    assert len(captured) == 1
    with pytest.raises(ValueError, match="escaped its physical invocation"):
        captured[0]("planning.compose_answer", task_input[0])
    assert len(harness.calls) == 1


def test_compose__different_active_run__rejects_before_dispatch(
    monkeypatch: pytest.MonkeyPatch,
    task_input: tuple[dict[str, Any], dict[str, Any]],
) -> None:
    harness = _harness(monkeypatch, *task_input, [_fact()])
    with (
        provider_dispatch_execution_scope(run_id="different-run"),
        provider_dispatch_budget_scope(harness.budget),
        pytest.raises(ValueError, match="Run differs"),
    ):
        harness.graph._compose_answer_node(harness.state)
    assert harness.calls == []
    assert candidate._active_registry.get() is None
    assert candidate._active_invocation.get() is None


def test_compose__ineligible_hardware__retains_product_predispatch_gate(
    monkeypatch: pytest.MonkeyPatch,
    task_input: tuple[dict[str, Any], dict[str, Any]],
) -> None:
    harness = _harness(monkeypatch, *task_input, [_fact()])
    hardware = harness.router.hardware_probe.probe()
    hardware.local_runtime_eligible = False
    hardware.local_runtime_reason_codes = ("TEST_UNAVAILABLE",)
    harness.router.hardware_probe.probe = lambda: hardware
    with pytest.raises(LLMInvocationError):
        _run(harness)
    assert harness.calls == []


def test_compose__pending_confirmation__delegates_original_owner_without_fact_branch(
    monkeypatch: pytest.MonkeyPatch,
    task_input: tuple[dict[str, Any], dict[str, Any]],
) -> None:
    response = {key: value for key, value in _prose().items() if key != "mode"}
    harness = _harness(monkeypatch, *task_input, [response])
    wrapped = ConfirmationAwareLLMRuntime(harness.router)
    wrapped.register(
        run_id=RUN_ID,
        origin_target="planning.outline_answer",
        response={
            "schema_version": 1,
            "response_kind": "FREE_TEXT",
            "selected_option": None,
            "free_text": "확인한 메모를 알려줘.",
        },
    )
    harness.graph._llm_runtime = wrapped
    result = _run(harness)
    assert result["planning_result"]["answer"] == response["answer"]
    body = json.loads(harness.calls[0]["payload"]["prompt"])
    assert body["prompt_ref"]["prompt_id"] == "planning.compose_answer"
    assert "oneOf" not in body["output_schema"]
    assert harness.observations[-1]["events"][0]["reason"] == "EXISTING_CONFIRMATION"


@pytest.mark.parametrize("scope", [None, PRODUCT_RELEASE, DEVELOPMENT_SMOKE])
def test_construct_candidate__scope_not_explicit_evaluation__fails_closed(
    scope: str | None,
) -> None:
    kwargs: dict[str, Any] = {} if scope is None else {"prompt_execution_scope": scope}
    with pytest.raises(ValueError, match="explicitly use EVALUATION"):
        candidate.AnswerChoicePlanningSubgraph(**kwargs)
