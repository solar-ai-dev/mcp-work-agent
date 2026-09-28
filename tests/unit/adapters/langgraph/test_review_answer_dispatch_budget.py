"""Review and ANSWER account actual dispatches without charging deterministic owners."""

from collections.abc import Iterator, Mapping
from itertools import count
from typing import Any, Literal, cast

import pytest

from google_work_agent.adapters.langgraph.profiles.profile_registry import GraphProfile
from google_work_agent.adapters.langgraph.subgraphs.planning.graph import PlanningSubgraph
from google_work_agent.adapters.langgraph.subgraphs.planning.state import PlanningLocalState
from google_work_agent.adapters.langgraph.subgraphs.review.graph import ReviewSubgraph
from google_work_agent.adapters.langgraph.subgraphs.review.state import ReviewState
from google_work_agent.adapters.system.memory.retrieval_evidence_store import RunScopedEvidenceStore
from google_work_agent.application.prompt_runtime.prompt_registry import DEVELOPMENT_SMOKE
from google_work_agent.application.use_cases.run.account_provider_dispatch import (
    account_provider_dispatch,
    bind_provider_dispatch_budget,
    provider_dispatch_execution_scope,
)
from google_work_agent.application.use_cases.run.guard_run_budget import build_default_run_budget
from google_work_agent.ports.llm.structured_inference_contracts import (
    LLMInvocationError,
    OutputSchemaDefinition,
    PromptReference,
)
from google_work_agent.ports.llm.structured_inference_port import StructuredInferenceResultV1
from google_work_agent.ports.system.contracts.workflow_execution import (
    WorkflowCorrelationContext,
    WorkflowStartRequest,
)


class _DispatchRuntime:
    def __init__(self, dispatches_per_infer: int = 1) -> None:
        self.dispatches_per_infer = dispatches_per_infer
        self.calls: list[str] = []
        self.dispatches = 0

    def infer(
        self,
        requested_mode: Literal["AUTO", "LOCAL_GPU", "API_LLM"],
        prompt_ref: PromptReference,
        input_projection: Mapping[str, object],
        output_schema_ref: OutputSchemaDefinition,
    ) -> StructuredInferenceResultV1:
        self.calls.append(prompt_ref.prompt_id)
        # FIRST and repair/fallback use this same Product dispatch authority.
        # No transport, model or external Provider is instantiated.
        for _ in range(self.dispatches_per_infer):
            account_provider_dispatch()
            self.dispatches += 1
        output: dict[str, object]
        if prompt_ref.prompt_id.startswith("review."):
            output = {"schema_version": 1, "dimension": prompt_ref.prompt_id, "findings": []}
        elif prompt_ref.prompt_id == "planning.outline_answer":
            output = {"sections": ["Facts"], "evidence_refs": ["e1"]}
        else:
            output = {
                "schema_version": 2,
                "answer": "The requested fact is confirmed in the selected message.",
                "evidence_refs": ["e1"],
            }
        return StructuredInferenceResultV1(1, output, "fake", "fake", "LOCAL_GPU", 0, 0, 0, None)


@pytest.fixture(autouse=True)
def _dispatch_scope() -> Iterator[None]:
    with provider_dispatch_execution_scope():
        yield


def _common_state(used: int) -> dict[str, Any]:
    budget = build_default_run_budget()
    budget["llm_calls_used"] = used
    return {
        "run_id": "run-dispatch",
        "retry_budget": budget,
        "trace_context": {"llm_call_count": 7},
        "__request__": WorkflowStartRequest(
            "run-dispatch",
            "conversation",
            "workflow",
            "AGENT_SEARCH",
            "LOCAL_GPU",
            "Prepare the requested result.",
            (),
            WorkflowCorrelationContext("req", None, "v1"),
            budget,
        ),
    }


def _review_state(*, exact: bool, used: int = 0) -> ReviewState:
    return cast(
        ReviewState,
        {
            **_common_state(used),
            "request_intent": {
                "requested_resource_hints": ["TASK"],
                "requested_effect_hints": ["CREATE"],
                "ambiguity": {"requires_confirmation": False},
                "constraints": [{"kind": "RESOURCE", "field": "title", "value": "Requested"}],
            },
            "planning_result": {
                "actions": [
                    {
                        "route_id": "task-route",
                        "tool_id": "tasks_create_task",
                        "effect": "CREATE",
                        "arguments": {
                            "task_list_id": "list-1",
                            "payload": {"title": "Requested" if exact else "Different"},
                        },
                        "evidence_refs": [],
                    }
                ],
            },
            "work_analysis": {
                "schema_version": 2,
                "action_necessity": "REQUIRED",
                "ambiguities": [],
                "risks": [],
                "relations": [],
                "evidence_refs": [],
            },
            "evidence": [],
        },
    )


def _review_graph(runtime: _DispatchRuntime) -> ReviewSubgraph:
    ids = count(1)
    return ReviewSubgraph(
        llm_runtime=runtime,
        prompt_execution_scope=DEVELOPMENT_SMOKE,
        id_factory=lambda: f"id-{next(ids)}",
        graph_profile=GraphProfile.SIX_ROLE_BASELINE,
        merge_decision=lambda state, update, decision: {**state, **update},
        evidence_store=RunScopedEvidenceStore(),
        load_persisted_evidence=lambda state: [],
        confirm_inline=lambda state: (None, None),
        resume_target_registry=cast(Any, object()),
    )


@pytest.mark.parametrize("used", [0, 100])
def test_exact_review__at_cap_still_checks_without_llm__no_phantom_call(used: int) -> None:
    state, runtime = _review_state(exact=True, used=used), _DispatchRuntime()

    result = _review_graph(runtime)._inspect_goal_and_evidence_node(state)

    assert runtime.calls == []
    assert result["goal_evidence_result"]["findings"] == []
    assert result["retry_budget"]["llm_calls_used"] == used
    assert result["trace_context"]["llm_call_count"] == 7
    node_log = cast(list[dict[str, object]], result["trace_context"]["agent_node_log"])
    assert node_log[-1]["llm_call_id"] is None
    assert result["planning_result"] == state["planning_result"]
    assert "plan_review" not in result  # A dimension check does not grant execution/approval.


def test_nonexact_review__at_cap__semantic_check_not_skipped() -> None:
    state, runtime = _review_state(exact=False, used=100), _DispatchRuntime()

    with pytest.raises(LLMInvocationError, match="ABSOLUTE_LLM_LIMIT_EXHAUSTED"):
        _review_graph(runtime)._inspect_goal_and_evidence_node(state)

    assert runtime.calls == []
    assert state["retry_budget"]["llm_calls_used"] == 100
    assert "goal_evidence_result" not in state


def test_exact_review__does_not_merge_unrelated_previously_bound_budget() -> None:
    stale_budget = build_default_run_budget()
    stale_budget["llm_calls_used"] = 1
    bind_provider_dispatch_budget(stale_budget)
    state, runtime = _review_state(exact=True, used=100), _DispatchRuntime()

    result = _review_graph(runtime)._inspect_goal_and_evidence_node(state)

    assert runtime.calls == []
    assert result["retry_budget"]["llm_calls_used"] == 100
    assert result["trace_context"]["llm_call_count"] == 7
    assert stale_budget["llm_calls_used"] == 1


@pytest.mark.parametrize("dispatches", [1, 2])
def test_review__one_infer__trace_uses_actual_dispatch_delta(dispatches: int) -> None:
    state, runtime = _review_state(exact=False, used=3), _DispatchRuntime(dispatches)

    result = _review_graph(runtime)._inspect_goal_and_evidence_node(state)

    assert runtime.calls == ["review.inspect_goal_and_evidence"]
    assert result["retry_budget"]["llm_calls_used"] == 3 + dispatches
    assert result["trace_context"]["llm_call_count"] == 7 + dispatches
    assert result["goal_evidence_result"]["findings"] == []


def _answer_state(*, used: int = 0, analysis: bool = True) -> PlanningLocalState:
    return cast(
        PlanningLocalState,
        {
            **_common_state(used),
            "user_request": "Summarize the selected message.",
            "request_intent": {
                "goal": "Summarize selected message",
                "constraints": [],
                "ambiguity": {"requires_confirmation": False},
            },
            "output_plan": {"output_mode": "ANSWER", "output_routes": []},
            "evidence": [
                {
                    "evidence_id": "e1",
                    "resource_handle": "gmail_thread:t1",
                    "excerpt": "The fact is confirmed.",
                }
            ],
            "answer_outline": {"sections": ["Facts"], "evidence_refs": ["e1"]},
            **({"work_analysis": {}} if analysis else {}),
        },
    )


def _answer_graph(runtime: _DispatchRuntime) -> PlanningSubgraph:
    ids = count(1)
    return PlanningSubgraph(
        llm_runtime=runtime,
        prompt_execution_scope=DEVELOPMENT_SMOKE,
        id_factory=lambda: f"id-{next(ids)}",
        graph_profile=GraphProfile.SIX_ROLE_BASELINE,
        merge_decision=lambda state, update, decision: {**state, **update},
    )


@pytest.mark.parametrize("node", ["outline", "compose"])
@pytest.mark.parametrize("dispatches", [1, 2])
def test_answer__one_infer__trace_uses_actual_dispatch_delta(node: str, dispatches: int) -> None:
    state, runtime = _answer_state(used=3), _DispatchRuntime(dispatches)
    graph = _answer_graph(runtime)

    result = (
        graph._outline_answer_node(state)
        if node == "outline"
        else graph._compose_answer_node(state)
    )

    assert runtime.calls == [f"planning.{node}_answer"]
    assert result["retry_budget"]["llm_calls_used"] == 3 + dispatches
    assert result["trace_context"]["llm_call_count"] == 7 + dispatches
    if node == "compose":
        answer = cast(dict[str, object], result["planning_result"])
        assert answer["evidence_refs"] == ["e1"]
        assert result["planning_disposition"] == "ANSWER"


def test_deterministic_answer_outline__at_cap__no_preflight_needed() -> None:
    state, runtime = _answer_state(used=100, analysis=False), _DispatchRuntime()

    result = _answer_graph(runtime)._outline_answer_node(state)

    assert runtime.calls == []
    assert result["answer_outline"]["evidence_refs"] == ["e1"]
    assert state["retry_budget"]["llm_calls_used"] == 100


@pytest.mark.parametrize("node", ["outline", "compose"])
def test_answer_needs_llm__at_cap__still_denied(node: str) -> None:
    state, runtime = _answer_state(used=100), _DispatchRuntime()
    graph = _answer_graph(runtime)

    with pytest.raises(LLMInvocationError, match="ABSOLUTE_LLM_LIMIT_EXHAUSTED"):
        if node == "outline":
            graph._outline_answer_node(state)
        else:
            graph._compose_answer_node(state)

    assert runtime.calls == []
    assert state["retry_budget"]["llm_calls_used"] == 100


def test_review_repair_dispatch__cap_is_enforced_at_actual_dispatch() -> None:
    state, runtime = _review_state(exact=False, used=99), _DispatchRuntime(2)

    with pytest.raises(LLMInvocationError, match="ABSOLUTE_LLM_LIMIT_EXHAUSTED"):
        _review_graph(runtime)._inspect_goal_and_evidence_node(state)

    assert len(runtime.calls) == 1
    assert runtime.dispatches == 1
    assert state["retry_budget"]["llm_calls_used"] == 100
