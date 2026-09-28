"""Fake-wire gates for the existing Product router plus invocation-local v4 bridge."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest
from langgraph.graph import END, START, StateGraph
from scripts import evaluate_production_snapshot_workflow as snapshot_runner
from scripts import production_goal_output_candidate as candidate_module
from scripts.evaluate_production_snapshot_workflow import TrialObservation
from scripts.production_snapshot_runtime import PROJECT_ROOT, load_case, snapshot_production_runtime
from tests.support.llm_runtime import runtime_selection, settings_view

from google_work_agent.adapters.langgraph.confirmation_llm_runtime import (
    ConfirmationAwareLLMRuntime,
)
from google_work_agent.adapters.langgraph.main.state import initial_graph_state
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
from google_work_agent.application.agents.request_understanding import (
    identify_output_responsibilities as output_ops,
)
from google_work_agent.application.agents.request_understanding import (
    identify_source_dependencies as source_ops,
)
from google_work_agent.application.agents.request_understanding.contracts.request_goal_candidate_schema import (  # noqa: E501
    identify_goal_output_schema,
)
from google_work_agent.application.prompt_runtime.contracts.failure_record import (
    build_failure_record_v1,
)
from google_work_agent.application.prompt_runtime.prompt_registry import PromptRegistry
from google_work_agent.application.tool_registry.load_signed_tool_registry import (
    load_development_tool_registry,
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
    OutputSchemaDefinition,
    RuntimePolicy,
)
from google_work_agent.ports.system.contracts.workflow_execution import (
    WorkflowCorrelationContext,
    WorkflowStartRequest,
)
from google_work_agent.ports.system.settings_port import SettingsPatchV1


def _fixtures(external: bool = False) -> tuple[dict[str, Any], dict[str, Any]]:
    units = ["work-1", "work-2"] if external else ["work-1"]
    context: dict[str, Any] = {
        "user_request": "Prepare two separate drafts." if external else "Read the selected task.",
        "selected_resource_refs": [{"resource_ref_id": "selected-ref", "resource_id": "selected"}],
        "requested_work": {"work_units": [{"unit_id": unit} for unit in units]},
    }
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
        coverage_requirement={"value": "NOT_COLLECTION", "work_unit_ids": units},
        additional_constraints=[],
    )
    raw = {
        "goal": context["user_request"],
        "completion_conditions": ["Prepare the requested result."],
        "constraints": constraints,
        "analysis_requirement": "NONE",
        "requested_result_mode": "EXTERNAL_CHANGE" if external else "ANSWER_ONLY",
        "requested_outputs": [
            {"resource_type": "GMAIL_DRAFT", "effect": "CREATE", "work_unit_ids": [unit]}
            for unit in units
        ]
        if external
        else [],
    }
    return context, raw


def _runtime(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, responses: list[dict[str, Any]]
) -> tuple[StructuredInferenceRuntimeRouter, TrialObservation, list[dict[str, Any]], list[str]]:
    calls: list[dict[str, Any]] = []
    checks: list[str] = []

    def wire(**kwargs: Any) -> dict[str, Any]:
        calls.append(deepcopy(kwargs))
        return {
            "response": json.dumps(responses[len(calls) - 1]),
            "model": "qwen3.5:9b",
            "prompt_eval_count": 10,
            "eval_count": 5,
            "total_duration": 1_000_000,
        }

    monkeypatch.setattr(transport, "_post_json", wire)
    observation = TrialObservation(tmp_path)
    model = ApprovedModelInfo("qwen3.5:9b", "OLLAMA", "1", "1")
    leaf = OllamaStructuredInferenceAdapter(
        "ollama",
        transport.OllamaHTTPClient(),
        "http://127.0.0.1:11434",
        model.model_id,
        assemble_instruction_text=lambda _ref, _input: "unchanged Product instruction",
    )
    provider = observation.decorate(candidate_module.decorate_goal_output_provider(leaf))
    hardware = SimpleNamespace(
        architecture="AMD64",
        cpu_logical_cores=8,
        ram_total_bytes=16 * 1024**3,
        gpu_present=True,
        gpu_name="fixture",
        vram_total_bytes=8 * 1024**3,
        local_runtime_eligible=True,
        local_runtime_reason_codes=(),
    )

    def probe() -> Any:
        checks.append("hardware")
        return hardware

    router = StructuredInferenceRuntimeRouter(
        settings_service=lambda: settings_view(
            preferred_llm_mode="LOCAL_GPU", preferred_local_model_id=model.model_id
        ),
        runtime_selection=runtime_selection(deployment_profile="LOCAL_CAPABLE", model=model),
        status_service=SimpleNamespace(get_model_for_prompt=lambda _id: model),
        credential_service=SimpleNamespace(),
        hardware_probe=SimpleNamespace(probe=probe),
        api_provider_name="unused",
        api_provider=provider,
        ollama_provider_factory=lambda _model: provider,
        runtime_policy=RuntimePolicy(sampling_seed=20260923),
        before_provider_dispatch=account_provider_dispatch,
        before_runtime_dispatch=lambda _runtime: checks.append("runtime"),
        run_context_provider=current_provider_dispatch_run_id,
        schema_repairer=PromptRepairSchemaRepairer(),
    )
    return router, observation, calls, checks


def _candidate(router: Any) -> Any:
    return candidate_module.ConnectedGoalOutputCandidate(
        run_id="run-1",
        delegate=router,
        tool_catalog=load_development_tool_registry(),
        model_id="qwen3.5:9b",
        sampling_seed=20260923,
    )


def _goal(candidate: Any, context: dict[str, Any]) -> Any:
    return candidate.infer(
        "LOCAL_GPU",
        PromptRegistry().lookup_for_evaluation(candidate_module.GOAL_SLOT),
        context,
        identify_goal_output_schema(
            [unit["unit_id"] for unit in context["requested_work"]["work_units"]]
        ),
    )


def _output_input(candidate: Any, context: Any, goal: Any) -> dict[str, Any]:
    return {
        **deepcopy(context),
        "goal_candidate": deepcopy(goal.structured_output),
        "output_candidates": deepcopy(list(candidate._output_candidates)),
        "effect_prohibitions": [],
    }


def _output(candidate: Any, projection: Any) -> Any:
    return candidate.infer(
        "LOCAL_GPU",
        PromptRegistry().lookup_for_evaluation(candidate_module.OUTPUT_SLOT),
        projection,
        OutputSchemaDefinition("unused-cache-consumer-schema", {}),
    )


@pytest.mark.parametrize("external", [False, True])
def test_joint_authority_dispatches_once_then_keeps_distinct_output_binding(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, external: bool
) -> None:
    context, raw = _fixtures(external)
    router, observation, calls, checks = _runtime(tmp_path, monkeypatch, [raw])
    candidate, budget = _candidate(router), build_default_run_budget()
    with (
        observation.wire_observer(),
        provider_dispatch_execution_scope(run_id="run-1"),
        provider_dispatch_budget_scope(budget),
    ):
        goal = _goal(candidate, context)
        output = _output(candidate, _output_input(candidate, context, goal))
    assert output.structured_output["output_responsibilities"] == raw["requested_outputs"]
    assert budget["llm_calls_used"] == len(calls) == observation.metrics()["actual_wire_calls"] == 1
    assert checks == ["hardware", "runtime"]
    assert (
        observation.calls[0]["prompt_ref"]["output_schema_version"]
        == candidate_module.OUTPUT_VERSION
    )
    assert observation.calls[0]["temperature"] == 0.0
    assert "Product-wide context:" in calls[0]["payload"]["system"]
    assert candidate.cached_response_count == 1
    assert router.runtime_policy.sampling_temperature is None


def test_product_bounded_repair_and_mutation_guard_are_used(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    context, valid = _fixtures()
    first = deepcopy(valid)
    del first["analysis_requirement"]
    router, observation, calls, _ = _runtime(tmp_path, monkeypatch, [first, valid])
    budget, candidate = build_default_run_budget(), _candidate(router)
    with (
        observation.wire_observer(),
        provider_dispatch_execution_scope(run_id="run-1"),
        provider_dispatch_budget_scope(budget),
    ):
        result = _goal(candidate, context)
    assert result.structured_output["analysis_requirement"] == "NONE"
    assert budget["llm_calls_used"] == len(calls) == 2
    repair_input = json.loads(calls[1]["payload"]["prompt"])["input"]
    assert set(repair_input) == {"base_projection", "candidate_output", "failure_record"}
    assert "Bounded failure instruction" in calls[1]["payload"]["system"]
    assert candidate_module._active_registry.get() is None


def test_exhausted_product_budget_rejects_before_observer_or_wire(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    context, raw = _fixtures()
    router, observation, calls, _ = _runtime(tmp_path, monkeypatch, [raw])
    candidate, budget = _candidate(router), build_default_run_budget()
    budget["llm_calls_used"] = budget["absolute_llm_call_limit"]
    with (
        observation.wire_observer(),
        provider_dispatch_execution_scope(run_id="run-1"),
        provider_dispatch_budget_scope(budget),
        pytest.raises(LLMInvocationError),
    ):
        _goal(candidate, context)
    assert calls == observation.calls == []
    assert candidate._goal_output is None


def test_ineligible_hardware_remains_rejected_before_dispatch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    context, raw = _fixtures()
    router, observation, calls, _ = _runtime(tmp_path, monkeypatch, [raw])
    hardware = router.hardware_probe.probe()
    hardware.local_runtime_eligible = False
    hardware.local_runtime_reason_codes = ("TEST_HARDWARE_NOT_VALIDATED",)
    candidate = _candidate(router)
    with (
        observation.wire_observer(),
        provider_dispatch_execution_scope(run_id="run-1"),
        pytest.raises(LLMInvocationError),
    ):
        _goal(candidate, context)
    assert calls == observation.calls == []
    assert candidate._goal_output is None


def test_repair_cannot_rewrite_valid_goal_semantics(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    context, valid = _fixtures()
    first = deepcopy(valid)
    del first["analysis_requirement"]
    valid["goal"] = "Changed unrelated Goal"
    router, observation, calls, _ = _runtime(tmp_path, monkeypatch, [first, valid])
    candidate = _candidate(router)
    with (
        observation.wire_observer(),
        provider_dispatch_execution_scope(run_id="run-1"),
        pytest.raises(LLMInvocationError, match="outside the reported failure scope"),
    ):
        _goal(candidate, context)
    assert candidate._goal_output is None and len(calls) == 2


@pytest.mark.parametrize(
    "field", ["user_request", "selected_resource_refs", "requested_work", "goal_candidate"]
)
def test_handoff_rejects_different_request_selected_work_or_goal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, field: str
) -> None:
    context, raw = _fixtures()
    router, observation, calls, _ = _runtime(tmp_path, monkeypatch, [raw])
    candidate = _candidate(router)
    with observation.wire_observer(), provider_dispatch_execution_scope(run_id="run-1"):
        goal = _goal(candidate, context)
        projection = _output_input(candidate, context, goal)
        projection[field] = "changed"
        with pytest.raises(ValueError, match="binding"):
            _output(candidate, projection)
    assert len(calls) == 1


def test_wrong_run_closed_invocation_and_prohibition_are_fail_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    context, raw = _fixtures(True)
    router, observation, calls, _ = _runtime(tmp_path, monkeypatch, [raw])
    candidate = _candidate(router)
    with observation.wire_observer(), provider_dispatch_execution_scope(run_id="run-1"):
        goal = _goal(candidate, context)
        projection = _output_input(candidate, context, goal)
        projection["effect_prohibitions"] = [
            {"effect": "CREATE", "prohibition": "FORBIDDEN", "work_unit_ids": ["work-1"]}
        ]
        with pytest.raises(output_ops.ProhibitedOutputResponsibilityDecisionError):
            _output(candidate, projection)
    with (
        provider_dispatch_execution_scope(run_id="other-run"),
        pytest.raises(ValueError, match="Run invocation"),
    ):
        _output(candidate, projection)
    candidate.close()
    with (
        provider_dispatch_execution_scope(run_id="run-1"),
        pytest.raises(ValueError, match="Run invocation"),
    ):
        _output(candidate, projection)
    assert len(calls) == 1 and candidate._goal_output is None


def test_output_revision_cannot_overwrite_joint_authority_or_drop_prohibition(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    context, raw = _fixtures(True)
    router, observation, calls, _ = _runtime(tmp_path, monkeypatch, [raw])
    candidate = _candidate(router)
    with observation.wire_observer(), provider_dispatch_execution_scope(run_id="run-1"):
        goal = _goal(candidate, context)
        projection = _output_input(candidate, context, goal)
        projection["effect_prohibitions"] = [
            {"effect": "CREATE", "prohibition": "FORBIDDEN", "work_unit_ids": ["work-1"]}
        ]
        before = deepcopy(candidate._goal_output)
        with pytest.raises(output_ops.ProhibitedOutputResponsibilityDecisionError) as initial:
            _output(candidate, projection)
        failure = build_failure_record_v1(
            failure_reason_code=initial.value.reason_code,
            failure_origin="LLM_OUTPUT",
            detected_by="RUNTIME_DOMAIN_VALIDATOR",
            runtime_disposition="RETRYABLE",
            experiment_disposition="RUN_REVISION",
            affected_field_paths=initial.value.affected_field_paths,
        )
        with pytest.raises(output_ops.ProhibitedOutputResponsibilityDecisionError):
            output_ops.identify_output_responsibilities(
                llm_runtime=candidate,
                requested_mode="LOCAL_GPU",
                prompt_ref=PromptRegistry().lookup_for_evaluation(candidate_module.OUTPUT_SLOT),
                prompt_input=context,
                goal_candidate=goal.structured_output,
                output_candidates=candidate._output_candidates,
                effect_prohibitions={"effect_prohibitions": projection["effect_prohibitions"]},
                work_unit_ids=["work-1", "work-2"],
                candidate_output=initial.value.candidate_output,
                failure_record=failure,
            )
    assert candidate._goal_output == before == raw
    assert candidate._context == context
    assert candidate.cached_response_count == 0
    assert len(calls) == observation.metrics()["actual_wire_calls"] == 1


def test_same_work_id_different_provenance_cannot_consume_authority(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    context, raw = _fixtures()
    provenance = {
        "source": "USER_REQUEST",
        "start_offset": 0,
        "end_offset": len(context["user_request"]),
        "source_text": context["user_request"],
    }
    context["requested_work"]["work_units"][0]["request_provenance"] = [provenance]
    raw["constraints"]["business_concepts"] = [
        {"value": "selected task", "work_unit_ids": ["work-1"]}
    ]
    router, observation, calls, _ = _runtime(tmp_path, monkeypatch, [raw])
    candidate = _candidate(router)
    with observation.wire_observer(), provider_dispatch_execution_scope(run_id="run-1"):
        goal = _goal(candidate, context)
        assert goal.structured_output == {
            field: raw[field] for field in candidate_module._GOAL_FIELDS
        }
        projection = _output_input(candidate, context, goal)
        projection["requested_work"]["work_units"][0]["request_provenance"][0]["start_offset"] = 1
        with pytest.raises(ValueError, match="binding"):
            _output(candidate, projection)
        assert candidate._context == context
        assert candidate._goal_output == raw
        assert candidate._context["requested_work"] is not context["requested_work"]
        assert goal.structured_output["constraints"] is not raw["constraints"]
    assert len(calls) == 1


def test_work_source_prohibition_calls_keep_exact_product_input_and_schema(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    prompts = [
        "request_understanding.identify_requested_work",
        "request_understanding.identify_source_dependencies",
        "request_understanding.identify_effect_prohibitions",
    ]
    router, observation, calls, _ = _runtime(tmp_path, monkeypatch, [{"kept": True}] * 3)
    candidate = _candidate(router)
    projection = {"work_unit_ids": ["work-1", "work-2"], "shared_source": "opaque"}
    schema = OutputSchemaDefinition("probe-v1", {"type": "object"})
    with observation.wire_observer(), provider_dispatch_execution_scope(run_id="run-1"):
        for prompt in prompts:
            result = candidate.infer(
                "LOCAL_GPU", PromptRegistry().lookup_for_evaluation(prompt), projection, schema
            )
            assert result.structured_output == {"kept": True}
    assert len(calls) == 3
    for call in calls:
        assert json.loads(call["payload"]["prompt"])["input"] == projection
        assert call["payload"]["format"] == schema.json_schema
        assert call["payload"]["system"] == "unchanged Product instruction"


def test_compiled_physical_node_has_stack_local_handoff_and_resume_is_untouched(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    context, raw = _fixtures()
    router, observation, calls, _ = _runtime(tmp_path, monkeypatch, [raw, raw])
    captured: list[Any] = []
    events: list[dict[str, object]] = []

    def original(state: Any, *, llm_runtime: Any) -> Any:
        captured.append(llm_runtime)
        if state.get("goal_candidate") is not None:
            return dict(state)
        goal = _goal(llm_runtime, context)
        output = _output(llm_runtime, _output_input(llm_runtime, context, goal))
        return {**state, "outputs": output.structured_output}

    monkeypatch.setattr(candidate_module.ru_graph, "identify_goal_node", original)
    monkeypatch.setattr(
        candidate_module,
        "project_identify_goal_input",
        lambda _: {"request": SimpleNamespace(run_id="run-1")},
    )
    graph = StateGraph(dict)
    graph.add_node(
        "identify_goal",
        lambda state: candidate_module.ru_graph.identify_goal_node(state, llm_runtime=router),
    )
    graph.add_edge(START, "identify_goal")
    graph.add_edge("identify_goal", END)
    compiled = graph.compile()
    with (
        observation.wire_observer(),
        candidate_module.goal_output_node_candidate(
            tool_catalog=load_development_tool_registry(),
            model_id="qwen3.5:9b",
            sampling_seed=20260923,
            observations=events,
        ),
        provider_dispatch_execution_scope(run_id="run-1"),
    ):
        for _ in range(2):
            assert compiled.invoke({})["outputs"] == {"output_responsibilities": []}
        compiled.invoke({"goal_candidate": {"kept": True}})
    assert len(calls) == len(events) == 2
    assert captured[0] is not captured[1]
    assert captured[0]._closed and captured[1]._closed
    assert captured[0]._goal_output is captured[1]._goal_output is None
    assert captured[2] is router


def test_actual_product_identify_goal_node_consumes_cached_output_in_compiled_graph(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    context, raw = _fixtures()
    catalog = load_development_tool_registry()
    source_candidates = source_ops.build_source_dependency_candidates(catalog)
    output_candidates = output_ops.build_output_responsibility_candidates(catalog)
    requested = {
        "schema_version": 1,
        "work_units": [{"request_spans": [context["user_request"]]}],
    }
    prohibitions = {
        "effect_prohibitions": [
            {"effect": effect, "prohibition": "NOT_FORBIDDEN", "work_unit_ids": ["work-1"]}
            for effect in ("CREATE", "UPDATE", "SEND", "DELETE")
        ]
    }
    sources = {
        "source_dependencies": [
            {
                "resource_type": item["resource_type"],
                "dependency": "SOURCE_REQUIRED",
                "required_information": ["title"],
                "target_scope": "SINGULAR",
                "work_unit_ids": ["work-1"],
            }
            if item["resource_type"] == "TASK"
            else {"resource_type": item["resource_type"], "dependency": "SOURCE_NOT_REQUIRED"}
            for item in source_candidates
        ]
    }
    router, observation, calls, _ = _runtime(
        tmp_path, monkeypatch, [requested, raw, prohibitions, sources, {"statuses": []}]
    )
    prompts = PromptRegistry()
    kwargs: dict[str, Any] = {
        "llm_runtime": router,
        "source_dependency_candidates": source_candidates,
        "output_responsibility_candidates": output_candidates,
    }
    for argument, slot in {
        "prompt_ref": "identify_goal",
        "requested_work_prompt_ref": "identify_requested_work",
        "effect_prohibition_prompt_ref": "identify_effect_prohibitions",
        "source_dependency_prompt_ref": "identify_source_dependencies",
        "output_responsibility_prompt_ref": "identify_output_responsibilities",
        "source_status_prompt_ref": "identify_source_status",
        "work_relation_prompt_ref": "identify_work_relations",
    }.items():
        kwargs[argument] = prompts.lookup_for_evaluation(f"request_understanding.{slot}")
    request = WorkflowStartRequest(
        run_id="run-1",
        conversation_id="conversation",
        workflow_key="workflow",
        entry_mode="AGENT_SEARCH",
        requested_mode="LOCAL_GPU",
        request_text=context["user_request"],
        selected_resource_ids=[],
        correlation=WorkflowCorrelationContext("request", "command", "1"),
        run_budget=build_default_run_budget(),
    )
    state = initial_graph_state(
        request,
        graph_profile=GraphProfile.SIX_ROLE_BASELINE,
        graph_version="fake-gate",
        initial_target="request.identify_goal",
    )
    graph = StateGraph(dict)
    graph.add_node(
        "identify_goal", lambda value: candidate_module.ru_graph.identify_goal_node(value, **kwargs)
    )
    graph.add_edge(START, "identify_goal")
    graph.add_edge("identify_goal", END)
    compiled, events = graph.compile(), []
    with (
        observation.wire_observer(),
        candidate_module.goal_output_node_candidate(
            tool_catalog=catalog,
            model_id="qwen3.5:9b",
            sampling_seed=20260923,
            observations=events,
        ),
        provider_dispatch_execution_scope(run_id="run-1"),
    ):
        result = compiled.invoke(state)
    assert result["goal_candidate"]["resource_responsibilities"]["outputs"] == []
    assert result["goal_candidate"]["resource_responsibilities"]["source_reads"][0][
        "work_unit_ids"
    ] == ["work-1"]
    assert result["retry_budget"]["llm_calls_used"] == len(calls) == 5
    assert events[0]["cached_response_count"] == 1
    assert all(call["prompt_id"] != candidate_module.OUTPUT_SLOT for call in observation.calls)


def test_known_confirmation_wrapper_preserves_delegate_and_rejects_pending_context(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    context, raw = _fixtures()
    router, observation, calls, _ = _runtime(tmp_path, monkeypatch, [raw])
    wrapper = ConfirmationAwareLLMRuntime(router)
    candidate = _candidate(wrapper)
    assert candidate._delegate is wrapper and candidate._router is router
    with observation.wire_observer(), provider_dispatch_execution_scope(run_id="run-1"):
        goal = _goal(candidate, context)
        assert _output(candidate, _output_input(candidate, context, goal)).structured_output == {
            "output_responsibilities": []
        }
        wrapper.register(
            run_id="run-1",
            origin_target="request.detect_ambiguity",
            response={"response_text": "fixture confirmation"},
        )
        with pytest.raises(ValueError, match="pending confirmation"):
            _output(candidate, _output_input(candidate, context, goal))
        with pytest.raises(ValueError, match="pending confirmation"):
            _candidate(wrapper)
    assert len(calls) == 1


def test_actual_snapshot_main_graph_passes_confirmation_wrapper_to_joint_router(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = PROJECT_ROOT / "evaluation/results" / f"joint-composition-preflight-{uuid4().hex}"
    observation, events = TrialObservation(root), []
    case = load_case("CASE-CORE-005")
    _, goal = _fixtures()
    goal["goal"] = case["canonical_user_prompt"]
    replies = [
        {"schema_version": 1, "work_units": [{"request_spans": [case["canonical_user_prompt"]]}]},
        goal,
    ]

    def fake_wire(**_kwargs: Any) -> dict[str, Any]:
        index = len(observation.calls) - 1
        if index >= len(replies):
            raise RuntimeError("FAKE_GATE_STOP_AFTER_JOINT_AUTHORITY")
        return {
            "response": json.dumps(replies[index]),
            "model": "qwen3.5:9b",
            "prompt_eval_count": 1,
            "eval_count": 1,
            "total_duration": 1_000_000,
        }

    monkeypatch.setattr(transport, "_post_json", fake_wire)
    with (
        observation.wire_observer(),
        snapshot_runner.candidate_scope(snapshot_runner.CANDIDATE, observation, events) as decorate,
        snapshot_production_runtime(
            root / "runtime",
            sampling_seed=20260923,
            llm_provider_decorator=decorate,
        ) as (container, boundary),
        snapshot_runner.drain_before_guard_release(container),
    ):
        router = container.structured_inference_port
        model = ApprovedModelInfo("qwen3.5:9b", "OLLAMA", "1", "1")
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
        scope = snapshot_runner.selected_task_scope(case, boundary.resources)
        container.settings_port.update_settings(
            SettingsPatchV1(
                1,
                preferred_local_model_id=model.model_id,
                preferred_llm_mode="LOCAL_GPU",
                selected_tasklist_ids=tuple(scope["selected_tasklist_ids"]),
                google_resource_account_id=scope["google_resource_account_id"],
            ),
            operation_ref=str(uuid4()),
        )
        assert isinstance(container.workflow_runtime._llm_runtime, ConfirmationAwareLLMRuntime)
        report: dict[str, Any] = {}
        admitted = snapshot_runner.start_case(container, boundary, case, scope=scope, report=report)
        assert container.schedule_run_execution._workflow_execution.await_drained(5000)
        assert len(observation.calls) >= 2
        assert observation.calls[0]["prompt_id"] == "request_understanding.identify_requested_work"
        assert observation.calls[1]["prompt_id"] == candidate_module.EVALUATION_SLOT
        assert observation.calls[1]["state"] == "RETURNED"
        assert events[0]["run_id"] == admitted.run_id
        assert events[0]["events"][0]["operation"] == "GOAL_OUTPUT_AUTHORITY"
        assert boundary.provider.read_calls == boundary.provider.write_calls == []
        assert not any(event.get("decision") == "DENY" for event in boundary.events)
