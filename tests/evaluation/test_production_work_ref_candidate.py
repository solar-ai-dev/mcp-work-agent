"""Fake-wire checks, not model-quality scores, for the inactive Work ref owner."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from langgraph.graph import END, START, StateGraph
from scripts import production_goal_output_candidate as goal_candidate
from scripts import production_work_ref_candidate as candidate
from tests.evaluation import test_production_goal_output_candidate as goal_tests
from tests.evaluation.test_production_goal_output_candidate import _runtime

from google_work_agent.adapters.langgraph.confirmation_llm_runtime import (
    ConfirmationAwareLLMRuntime,
)
from google_work_agent.application.agents.request_understanding.identify_requested_work import (
    validate_requested_work_candidate,
)
from google_work_agent.application.prompt_runtime.assemble_prompt import assemble_prompt
from google_work_agent.application.prompt_runtime.prompt_registry import EVALUATION, PromptRegistry
from google_work_agent.application.tool_registry.load_signed_tool_registry import (
    load_development_tool_registry,
)
from google_work_agent.application.use_cases.run.account_provider_dispatch import (
    provider_dispatch_budget_scope,
    provider_dispatch_execution_scope,
)
from google_work_agent.application.use_cases.run.guard_run_budget import build_default_run_budget
from google_work_agent.ports.llm.structured_inference_contracts import LLMInvocationError


def _refs(*ranges: tuple[str, str]) -> dict[str, Any]:
    return {
        "work_units": [
            {"ranges": [{"start_token_id": start, "end_token_id": end}]} for start, end in ranges
        ]
    }


def _setup(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, responses: list[Any]) -> Any:
    original = goal_candidate.decorate_goal_output_provider
    monkeypatch.setattr(
        goal_candidate,
        "decorate_goal_output_provider",
        lambda leaf: candidate.decorate_work_ref_provider(original(leaf)),
    )
    return _runtime(tmp_path, monkeypatch, responses)


def _identify(owner: Any, request: str, runtime: Any | None = None) -> Any:
    return owner.identify(
        llm_runtime=owner.router if runtime is None else runtime,
        requested_mode="LOCAL_GPU",
        prompt_ref=owner.product_ref,
        user_request=request,
    )


def test_exact_unicode_whitespace_and_reading_order_are_preserved() -> None:
    request = "8월  12일\nname@gmail.com에 보내고\t상태를 확인해."
    work = candidate.materialize_work_definition(
        _refs(("t005", "t006"), ("t001", "t004")), user_request=request
    )
    assert [unit["unit_id"] for unit in work["work_units"]] == ["work-1", "work-2"]
    spans = [unit["request_provenance"][0] for unit in work["work_units"]]
    assert spans[0]["source_text"] == "8월  12일\nname@gmail.com에 보내고"
    assert spans[1]["source_text"] == "상태를 확인해."
    for span in spans:
        assert request[span["start_offset"] : span["end_offset"]] == span["source_text"]
    assert work["work_relations"] == []


def test_repeated_literal_uses_explicit_occurrence_not_unique_string_lookup() -> None:
    request = "검토해. 검토해."
    with pytest.raises(ValueError, match="exactly once"):
        validate_requested_work_candidate(
            {"schema_version": 1, "work_units": [{"request_spans": ["검토해."]}]},
            user_request=request,
        )
    work = candidate.materialize_work_definition(
        _refs(("t001", "t001"), ("t002", "t002")), user_request=request
    )
    spans = [unit["request_provenance"][0] for unit in work["work_units"]]
    assert [span["start_offset"] for span in spans] == [0, 5]
    assert [span["source_text"] for span in spans] == ["검토해.", "검토해."]


@pytest.mark.parametrize(
    "refs",
    [
        _refs(("t003", "t001")),
        _refs(("t001", "t002"), ("t002", "t003")),
        _refs(("t000", "t001")),
        _refs(("t001", "t999")),
        {"work_units": []},
        {"work_units": [{"ranges": []}]},
        {
            "work_units": [
                {
                    "ranges": [
                        {"start_token_id": "t001", "end_token_id": "t002"},
                        {"start_token_id": "t002", "end_token_id": "t003"},
                    ]
                }
            ]
        },
        {**_refs(("t001", "t001")), "effect": "CREATE"},
    ],
)
def test_invalid_closed_ranges_fail_without_semantic_correction(refs: Any) -> None:
    with pytest.raises(ValueError):
        candidate.materialize_work_definition(refs, user_request="alpha beta gamma")


def test_projection_does_not_force_one_decomposition_or_invent_missing_semantics() -> None:
    request = "Project 메일을 요약하고 일정을 확인해. 보내지는 마."
    tokens = candidate._request_tokens(request)
    whole = candidate.materialize_work_definition(
        _refs(("t001", tokens[-1]["token_id"])), user_request=request
    )
    multiple = candidate.materialize_work_definition(
        _refs(("t001", "t003"), ("t004", "t007")), user_request=request
    )
    assert len(whole["work_units"]) == 1 and len(multiple["work_units"]) == 2
    # Structural acceptance is not a claim that either decomposition preserves all meaning.
    assert "Project" not in multiple["work_units"][1]["request_provenance"][0]["source_text"]
    assert all(set(unit) == {"unit_id", "request_provenance"} for unit in multiple["work_units"])
    assert whole["work_relations"] == multiple["work_relations"] == []


def test_actual_router_one_call_keeps_budget_observer_assembly_and_full_request(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    request = "Project 메일을 요약해. 발송하지 마."
    raw = _refs(("t001", "t005"))
    router, observation, calls, checks = _setup(tmp_path, monkeypatch, [raw])
    owner = candidate.ConnectedWorkRefCandidate(delegate=router, run_id="run-1")
    budget = build_default_run_budget()
    with (
        observation.wire_observer(),
        provider_dispatch_execution_scope(run_id="run-1"),
        provider_dispatch_budget_scope(budget),
    ):
        result = _identify(owner, request)
    payload = calls[0]["payload"]
    assert json.loads(payload["prompt"])["input"]["user_request"] == request
    assert "Product-wide context:" in payload["system"]
    assert "`ranges`" in payload["system"] and "`request_spans`" not in payload["system"]
    assert payload["options"]["seed"] == 20260923
    assert budget["llm_calls_used"] == len(calls) == observation.metrics()["actual_wire_calls"] == 1
    assert checks == ["hardware", "runtime"]
    assert observation.calls[0]["prompt_id"] == candidate.EVALUATION_SLOT
    assert owner.events[0]["router_validated_output"] == raw
    assert owner.events[0]["materialized_work_definition"] == result
    assert owner.product_ref == PromptRegistry().lookup_for_evaluation(candidate.WORK_SLOT)
    assert owner.prompt_ref.content_hash != owner.product_ref.content_hash
    assert "Source, Output, Effect, Constraint" in owner.instruction


@pytest.mark.parametrize("change_valid_start", [False, True])
def test_schema_repair_retains_existing_scope_guard_and_observation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, change_valid_start: bool
) -> None:
    first = {"work_units": [{"ranges": [{"start_token_id": "t001"}]}]}
    repaired = _refs(("t002" if change_valid_start else "t001", "t003"))
    router, observation, calls, _ = _setup(tmp_path, monkeypatch, [first, repaired])
    owner = candidate.ConnectedWorkRefCandidate(delegate=router, run_id="run-1")
    budget = build_default_run_budget()
    with (
        observation.wire_observer(),
        provider_dispatch_execution_scope(run_id="run-1"),
        provider_dispatch_budget_scope(budget),
    ):
        if change_valid_start:
            with pytest.raises(LLMInvocationError, match="outside the reported failure scope"):
                _identify(owner, "alpha beta gamma")
        else:
            assert (
                _identify(owner, "alpha beta gamma")["work_units"][0]["request_provenance"][0][
                    "source_text"
                ]
                == "alpha beta gamma"
            )
    assert len(calls) == budget["llm_calls_used"] == 2
    assert "Bounded failure instruction" in calls[1]["payload"]["system"]
    assert (
        json.loads(calls[1]["payload"]["prompt"])["input"]["base_projection"]["user_request"]
        == "alpha beta gamma"
    )


def test_zero_budget_wrong_run_closed_reuse_and_pending_confirmation_fail_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    router, observation, calls, _ = _setup(tmp_path, monkeypatch, [])
    wrapper = ConfirmationAwareLLMRuntime(router)
    owner = candidate.ConnectedWorkRefCandidate(delegate=wrapper, run_id="run-1")
    budget = build_default_run_budget()
    budget["llm_calls_used"] = budget["absolute_llm_call_limit"]
    with (
        observation.wire_observer(),
        provider_dispatch_execution_scope(run_id="other"),
        pytest.raises(ValueError, match="Run invocation"),
    ):
        _identify(owner, "alpha")
    with (
        observation.wire_observer(),
        provider_dispatch_execution_scope(run_id="run-1"),
        provider_dispatch_budget_scope(budget),
    ):
        wrapper.register(
            run_id="run-1",
            origin_target="request.detect_ambiguity",
            response={"response_text": "confirmed"},
        )
        with pytest.raises(ValueError, match="Run invocation"):
            _identify(owner, "alpha")
        fresh = candidate.ConnectedWorkRefCandidate(delegate=router, run_id="run-1")
        with pytest.raises(LLMInvocationError):
            _identify(fresh, "alpha")
        with pytest.raises(ValueError, match="Run invocation"):
            _identify(fresh, "alpha")
        owner.close()
        with pytest.raises(ValueError, match="Run invocation"):
            _identify(owner, "alpha")
    assert calls == []


def test_registered_assembly_rejects_changed_original_or_token_projection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    router, _, _, _ = _setup(tmp_path, monkeypatch, [])
    owner = candidate.ConnectedWorkRefCandidate(delegate=router, run_id="run-1")
    projection = {
        "user_request": "alpha",
        "request_tokens": [{"token_id": "t001", "text": "alpha"}],
    }
    registry = candidate._EvaluationRegistry(owner, projection)
    assert "alpha" in assemble_prompt(
        owner.prompt_ref, projection, registry=registry, execution_scope=EVALUATION
    )
    for field in ("user_request", "request_tokens"):
        changed = deepcopy(projection)
        changed[field] = "changed"
        with pytest.raises(ValueError):
            assemble_prompt(
                owner.prompt_ref, changed, registry=registry, execution_scope=EVALUATION
            )
    with pytest.raises(LookupError):
        registry.lookup_for_evaluation("unregistered")


@pytest.mark.parametrize("goal_bridge_outer", [False, True])
def test_compiled_operation_scoping_restores_and_composes_without_resume_changes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, goal_bridge_outer: bool
) -> None:
    router, observation, calls, _ = _setup(tmp_path, monkeypatch, [_refs(("t001", "t001"))])

    def projected(_: Any) -> dict[str, Any]:
        return {"request": SimpleNamespace(run_id="run-1")}

    monkeypatch.setattr(candidate, "project_identify_goal_input", projected)
    monkeypatch.setattr(goal_candidate, "project_identify_goal_input", projected)
    original_owner = candidate.goal_owner.identify_requested_work
    seen = []

    def original(state: Any, *, llm_runtime: Any) -> Any:
        seen.append(llm_runtime)
        if state.get("goal_candidate") is not None:
            return state
        return {
            "work": candidate.goal_owner.identify_requested_work(
                llm_runtime=llm_runtime,
                requested_mode="LOCAL_GPU",
                prompt_ref=PromptRegistry().lookup_for_evaluation(candidate.WORK_SLOT),
                user_request="alpha",
            )
        }

    monkeypatch.setattr(candidate.ru_graph, "identify_goal_node", original)
    graph = StateGraph(dict)
    graph.add_node(
        "work", lambda state: candidate.ru_graph.identify_goal_node(state, llm_runtime=router)
    )
    graph.add_edge(START, "work")
    graph.add_edge("work", END)
    compiled, events = graph.compile(), []
    work_scope = candidate.work_ref_node_candidate(observations=events)
    goal_scope = goal_candidate.goal_output_node_candidate(
        tool_catalog=load_development_tool_registry(),
        model_id="qwen3.5:9b",
        sampling_seed=20260923,
        observations=[],
    )
    outer, inner = (goal_scope, work_scope) if goal_bridge_outer else (work_scope, goal_scope)
    with (
        observation.wire_observer(),
        outer,
        inner,
        provider_dispatch_execution_scope(run_id="run-1"),
    ):
        assert compiled.invoke({})["work"]["work_units"][0]["unit_id"] == "work-1"
        assert compiled.invoke({"goal_candidate": {"preserved": True}})["goal_candidate"] == {
            "preserved": True
        }
    assert len(calls) == len(events) == 1
    assert seen[-1] is router
    assert candidate.ru_graph.identify_goal_node is original
    assert candidate.goal_owner.identify_requested_work is original_owner
    assert candidate._active_owner.get() is candidate._active_registry.get() is None


def test_actual_product_goal_node_consumes_work_refs_without_changing_other_owner_calls(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Reuse the existing compiled Product RU gate, replacing only its fake Work reply."""
    from google_work_agent.adapters.langgraph.subgraphs.request_understanding.nodes import (
        identify_goal_node as physical_owner,
    )

    # This frozen v34 candidate predates the fresh-only Product codec option.
    # Explicitly retain its original exact-only caller and supporting-owner API.
    historical_owner = physical_owner.identify_goal_with_budget
    historical_identify = candidate.ConnectedWorkRefCandidate.identify

    def exact_baseline(**kwargs: Any) -> Any:
        kwargs["allow_whitespace_work_selector"] = False
        return historical_owner(**kwargs)

    def historical_work_api(self: Any, **kwargs: Any) -> Any:
        assert not kwargs.pop("allow_whitespace_selector", False)
        return historical_identify(self, **kwargs)

    monkeypatch.setattr(physical_owner, "identify_goal_with_budget", exact_baseline)
    monkeypatch.setattr(candidate.ConnectedWorkRefCandidate, "identify", historical_work_api)
    original_runtime = goal_tests._runtime
    original_decorator = goal_candidate.decorate_goal_output_provider
    monkeypatch.setattr(
        goal_candidate,
        "decorate_goal_output_provider",
        lambda leaf: candidate.decorate_work_ref_provider(original_decorator(leaf)),
    )

    def runtime(path: Path, patcher: pytest.MonkeyPatch, replies: list[Any]) -> Any:
        request = replies[0]["work_units"][0]["request_spans"][0]
        tokens = candidate._request_tokens(request)
        replaced = [_refs(("t001", tokens[-1]["token_id"])), *replies[1:]]
        return original_runtime(path, patcher, replaced)

    monkeypatch.setattr(goal_tests, "_runtime", runtime)
    events: list[dict[str, Any]] = []
    with candidate.work_ref_node_candidate(observations=events):
        goal_tests.test_actual_product_identify_goal_node_consumes_cached_output_in_compiled_graph(
            tmp_path, monkeypatch
        )
    assert len(events) == 1
    work = events[0]["events"][0]["materialized_work_definition"]
    assert work["work_units"][0]["unit_id"] == "work-1"
    assert work["work_units"][0]["request_provenance"][0]["source_text"] == (
        "Read the selected task."
    )
