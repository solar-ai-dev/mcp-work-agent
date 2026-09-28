"""Physical-node traces project dispatch usage, not semantic invoke forecasts."""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from copy import deepcopy
from dataclasses import replace
from typing import Any, cast

import pytest
from tests.unit.adapters.langgraph.test_request_understanding_budget_gate import (
    PROMPT_REF,
    _RepairingAgent,
    _state,
    _subgraph,
)
from tests.unit.adapters.langgraph.test_tool_selection_capability import (
    _candidate,
    _RecordingSelectionLLM,
)
from tests.unit.application.agents.tool_routing.test_determine_io_resources import _v3

from google_work_agent.adapters.langgraph.profiles.profile_registry import GraphProfile
from google_work_agent.adapters.langgraph.subgraphs.tool_routing.graph import ToolRoutingSubgraph
from google_work_agent.application.tool_registry.load_signed_tool_registry import (
    load_signed_tool_registry,
)
from google_work_agent.application.use_cases.run.account_provider_dispatch import (
    account_provider_dispatch,
    provider_dispatch_execution_scope,
)
from google_work_agent.application.use_cases.run.guard_run_budget import build_default_run_budget
from google_work_agent.ports.llm.structured_inference_contracts import (
    LLMErrorCode,
    LLMInvocationError,
)
from google_work_agent.ports.llm.structured_inference_port import StructuredInferenceResultV1


@pytest.fixture(autouse=True)
def _dispatch_scope() -> Iterator[None]:
    with provider_dispatch_execution_scope():
        yield


class _DispatchRuntime:
    def __init__(self, output: Mapping[str, object], *, dispatches: int = 2) -> None:
        self.output = dict(output)
        self.dispatches = dispatches
        self.invocations = 0

    def infer(self, *_args: Any, **_kwargs: Any) -> StructuredInferenceResultV1:
        self.invocations += 1
        for _ in range(self.dispatches):
            account_provider_dispatch()
        return StructuredInferenceResultV1(
            schema_version=1,
            structured_output=deepcopy(self.output),
            provider="fake",
            model="fake",
            actual_runtime="LOCAL_GPU",
            input_tokens=0,
            output_tokens=0,
            latency_ms=0,
            fallback_reason=None,
        )


def _goal() -> Any:
    return _subgraph(_RepairingAgent(structured_output_attempts=1))._identify_goal_node(
        cast(Any, _state(llm_calls_used=0))
    )["goal_candidate"]


def _ru_state() -> Any:
    goal = _goal()
    return {**_state(llm_calls_used=3), "goal_candidate": goal}


@pytest.mark.parametrize("dispatches", [1, 2, 3])
def test_fresh_work_is_included_with_repair_and_fallback_dispatches(dispatches: int) -> None:
    runtime = _RepairingAgent(structured_output_attempts=dispatches)
    result = _subgraph(runtime)._identify_goal_node(cast(Any, _state(llm_calls_used=3)))
    assert runtime.calls == 6
    assert result["retry_budget"]["llm_calls_used"] == 3 + 6 * dispatches
    assert result["trace_context"]["llm_call_count"] == 6 * dispatches


@pytest.mark.parametrize("source_missing", [False, True])
def test_confirmation_preserves_work_and_counts_only_needed_source_dispatch(
    source_missing: bool,
) -> None:
    state = _ru_state()
    if source_missing:
        state["goal_candidate"]["resource_responsibilities"]["source_reads"] = []
        state["goal_candidate"]["requested_effect_hints"] = []
        state["goal_candidate"]["requested_resource_hints"] = []
    state["ambiguity_candidate"] = {
        "requires_confirmation": True,
        "reason_codes": ["MISSING_TARGET"],
        "missing_fields": ["target_resource"],
    }
    state["prompt_context"] = {
        "confirmation_response": {
            "schema_version": 1,
            "response_kind": "FREE_TEXT",
            "selected_option": None,
            "free_text": "confirmed target",
        }
    }
    runtime = _RepairingAgent(structured_output_attempts=2)
    result = _subgraph(runtime)._identify_goal_node(state)
    expected_dispatches = 2 if source_missing else 0
    assert runtime.calls == int(source_missing)
    assert result["goal_candidate"]["requested_work"] == state["goal_candidate"]["requested_work"]
    assert result["retry_budget"]["llm_calls_used"] == 3 + expected_dispatches
    assert result["trace_context"]["llm_call_count"] == expected_dispatches
    if not source_missing:
        assert result["trace_context"]["prompt_refs"] == []


@pytest.mark.parametrize("dispatches", [1, 2, 3])
def test_temporal_trace_counts_provider_dispatches(dispatches: int) -> None:
    state = _ru_state()
    goal = state["goal_candidate"]
    goal["requested_resource_hints"] = ["GMAIL_THREAD"]
    goal["resource_responsibilities"]["source_reads"] = [
        {
            "resource_type": "GMAIL_THREAD",
            "required_information": ["body"],
            "target_scope": "CRITERIA",
            "work_unit_ids": ["work-1"],
        }
    ]
    goal["constraints"].append(
        {
            "kind": "DATE",
            "field": "period",
            "value": ["2026-08-01/2026-08-02"],
            "work_unit_ids": ["work-1"],
        }
    )
    runtime = _DispatchRuntime({"temporal_axis": "MESSAGE_TIME"}, dispatches=dispatches)
    subgraph = _subgraph(runtime)
    subgraph._identify_temporal_scope_prompt_ref = replace(
        PROMPT_REF, prompt_id="request_understanding.identify_temporal_scope"
    )
    result = subgraph._identify_temporal_scope_node(state)
    assert runtime.invocations == 1
    assert result["retry_budget"]["llm_calls_used"] == 3 + dispatches
    assert result["trace_context"]["llm_call_count"] == dispatches


def test_temporal_noop_has_no_dispatch_or_prompt_ref() -> None:
    state = _ru_state()
    runtime = _DispatchRuntime({})
    subgraph = _subgraph(runtime)
    subgraph._identify_temporal_scope_prompt_ref = PROMPT_REF
    result = subgraph._identify_temporal_scope_node(state)
    assert runtime.invocations == 0
    assert result["trace_context"]["llm_call_count"] == 0
    assert result["trace_context"]["prompt_refs"] == []


@pytest.mark.parametrize("dispatches", [1, 2, 3])
def test_ambiguity_trace_counts_provider_dispatches(dispatches: int) -> None:
    state = _ru_state()
    runtime = _DispatchRuntime(
        {"missing_information_owner": "NONE", "missing_fields": []}, dispatches=dispatches
    )
    subgraph = _subgraph(runtime)
    subgraph._connector_prerequisites = None
    subgraph._detect_ambiguity_prompt_ref = replace(
        PROMPT_REF, prompt_id="request_understanding.detect_ambiguity"
    )
    result = subgraph._detect_ambiguity_node(state)
    assert runtime.invocations == 1
    assert result["retry_budget"]["llm_calls_used"] == 3 + dispatches
    assert result["trace_context"]["llm_call_count"] == dispatches


def _route_subgraph(runtime: Any) -> ToolRoutingSubgraph:
    subgraph = object.__new__(ToolRoutingSubgraph)
    subgraph._llm_runtime = runtime
    subgraph._tool_catalog = load_signed_tool_registry()
    subgraph._select_prompt_ref = replace(
        PROMPT_REF, prompt_id="tool_routing.select_tool_if_needed"
    )
    subgraph._determine_prompt_ref = replace(
        PROMPT_REF, prompt_id="tool_routing.determine_io_resources"
    )
    subgraph._graph_profile = GraphProfile.SIX_ROLE_BASELINE
    subgraph._id_factory = lambda: "confirmation-1"
    return subgraph


def _route_state() -> Any:
    state = _state(llm_calls_used=3)
    state["trace_context"] = {
        "agent_node_log": [{"agent_subgraph_id": "tool_route", "agent_invocation_id": "route-1"}]
    }
    return state


class _DispatchSelection(_RecordingSelectionLLM):
    def __init__(self, dispatches: int) -> None:
        super().__init__()
        self.dispatches = dispatches

    def infer(self, *args: Any, **kwargs: Any) -> StructuredInferenceResultV1:
        for _ in range(self.dispatches):
            account_provider_dispatch()
        return super().infer(*args, **kwargs)


@pytest.mark.parametrize("dispatches", [1, 2, 3])
def test_shared_tool_capability_selects_once_and_traces_all_dispatches(dispatches: int) -> None:
    runtime = _DispatchSelection(dispatches)
    state = _route_state()
    state["registry_candidates"] = [_candidate("r1", "work-1"), _candidate("r2", "work-2")]
    result = _route_subgraph(runtime)._select_tool_if_needed_node(state)
    assert len(runtime.calls) == 1
    assert result["retry_budget"]["llm_calls_used"] == 3 + dispatches
    assert result["trace_context"]["llm_call_count"] == dispatches
    assert [(r["route_id"], r["work_unit_ids"]) for r in result["bound_output_routes"]] == [
        ("r1", ["work-1"]),
        ("r2", ["work-2"]),
    ]


def test_single_tool_candidate_is_zero_call() -> None:
    runtime = _DispatchSelection(2)
    state = _route_state()
    state["registry_candidates"] = [
        _candidate("r1", "work-1", eligible_tool_ids=("github_update_issue",))
    ]
    result = _route_subgraph(runtime)._select_tool_if_needed_node(state)
    assert runtime.calls == []
    assert result["retry_budget"]["llm_calls_used"] == 3
    assert result["trace_context"]["llm_call_count"] == 0
    assert result["trace_context"]["prompt_refs"] == []


def test_distinct_capabilities_count_independent_dispatches() -> None:
    runtime = _DispatchSelection(2)
    state = _route_state()
    state["registry_candidates"] = [
        _candidate("r1", "work-1"),
        _candidate("r2", "work-2", eligible_tool_ids=("github_update_issue", "other_update")),
    ]
    result = _route_subgraph(runtime)._select_tool_if_needed_node(state)
    assert len(runtime.calls) == 2
    assert result["trace_context"]["llm_call_count"] == 4
    assert result["retry_budget"]["llm_calls_used"] == 7


def test_selection_dispatch_cap_still_denies_repair_and_keeps_consumed_budget() -> None:
    runtime = _DispatchSelection(2)
    state = _route_state()
    limit = build_default_run_budget()["absolute_llm_call_limit"]
    state["retry_budget"]["llm_calls_used"] = limit - 1
    state["registry_candidates"] = [_candidate("r1", "work-1")]
    with pytest.raises(LLMInvocationError) as exc:
        _route_subgraph(runtime)._select_tool_if_needed_node(state)
    assert exc.value.code is LLMErrorCode.LLM_CALL_BUDGET_EXHAUSTED
    assert state["retry_budget"]["llm_calls_used"] == limit


@pytest.mark.parametrize("dispatches", [1, 2, 3])
@pytest.mark.parametrize("requires_inference", [False, True])
@pytest.mark.parametrize("rejected", [False, True])
def test_determine_trace_counts_dispatches_not_logical_invocations(
    dispatches: int,
    requires_inference: bool,
    rejected: bool,
) -> None:
    state = _route_state()
    state["request_intent"] = _v3(
        cast(
            Any,
            {
                "schema_version": 2,
                "meta": {"artifact_id": "intent", "revision": 1, "based_on": []},
                "goal": "create a task",
                "completion_conditions": ["task prepared"],
                "constraints": [],
                "requested_effect_hints": ["READ", "CREATE"] if requires_inference else ["CREATE"],
                "requested_resource_hints": ["TASK"],
                "analysis_requirement": "NONE",
                "ambiguity": {
                    "requires_confirmation": False,
                    "reason_codes": [],
                    "missing_fields": [],
                },
            },
        ),
        "test request",
    )
    runtime = _DispatchRuntime(
        {
            "schema_version": 1,
            "input_resource_types": ["TASK"],
            "output_resource_types": ["TASK"],
            "output_effects": ["CREATE"],
            "disposition": "NEEDS_CONFIRMATION" if rejected else "ROUTE_READY",
        },
        dispatches=dispatches,
    )
    result = _route_subgraph(runtime)._determine_io_resources_node(state)
    expected_invocations = (2 if rejected else 1) if requires_inference else 0
    expected_dispatches = dispatches * expected_invocations
    assert runtime.invocations == expected_invocations
    assert result.get("retry_budget", state["retry_budget"])["llm_calls_used"] == (
        3 + expected_dispatches
    )
    assert result["trace_context"]["llm_call_count"] == expected_dispatches
    if not requires_inference:
        assert result["trace_context"]["prompt_refs"] == []
    elif rejected:
        assert result["io_resource_candidate"] is None
        assert result["workflow_phase"] == "WAITING_CONFIRMATION"
