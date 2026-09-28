"""Planning preflight and trace consume the route's actual owner boundary."""

from collections.abc import Iterator, Mapping
from copy import deepcopy
from itertools import count
from typing import Any, Literal, cast

import pytest

from google_work_agent.adapters.langgraph.profiles.profile_registry import GraphProfile
from google_work_agent.adapters.langgraph.subgraphs.planning.graph import PlanningSubgraph
from google_work_agent.adapters.langgraph.subgraphs.planning.state import PlanningLocalState
from google_work_agent.adapters.system.memory.retrieval_evidence_store import RunScopedEvidenceStore
from google_work_agent.application.prompt_runtime.prompt_registry import DEVELOPMENT_SMOKE
from google_work_agent.application.use_cases.run.account_provider_dispatch import (
    account_provider_dispatch,
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
    def __init__(
        self, *, dispatches_per_infer: int = 1, payload: dict[str, object] | None = None
    ) -> None:
        self.calls: list[Mapping[str, object]] = []
        self.dispatches_per_infer = dispatches_per_infer
        self.payload = payload or {"title": "Second composed"}

    def infer(
        self,
        requested_mode: Literal["AUTO", "LOCAL_GPU", "API_LLM"],
        prompt_ref: PromptReference,
        input_projection: Mapping[str, object],
        output_schema_ref: OutputSchemaDefinition,
    ) -> StructuredInferenceResultV1:
        # Exercise the same ledger boundary as FIRST, repair and fallback.
        # No Provider is instantiated or called.
        for _ in range(self.dispatches_per_infer):
            account_provider_dispatch()
        self.calls.append(deepcopy(dict(input_projection)))
        if prompt_ref.prompt_id.endswith("draft_action_objective_per_output_route"):
            output = {
                "schema_version": 1,
                "objective": "Prepare the second independent task",
                "scope_constraints": [],
                "evidence_refs": [],
            }
        else:
            output = {
                "schema_version": 1,
                "route_id": cast(dict[str, object], input_projection["output_route"])["route_id"],
                "arguments": {"payload": dict(self.payload)},
                "evidence_refs": [],
            }
        return StructuredInferenceResultV1(1, output, "fake", "fake", "LOCAL_GPU", 0, 0, 0, None)


@pytest.fixture(autouse=True)
def _dispatch_scope() -> Iterator[None]:
    with provider_dispatch_execution_scope():
        yield


def _state(*, second_title: bool, used: int = 0) -> PlanningLocalState:
    titles = [("work-1", "First"), *([("work-2", "Second")] if second_title else [])]
    routes = [
        {
            "route_id": f"route-{number}",
            "work_unit_ids": [f"work-{number}"],
            "connector_id": "google_workspace",
            "resource_type": "TASK",
            "effect": "CREATE",
            "selected_tool_id": "tasks_create_task",
        }
        for number in (1, 2)
    ]
    request = (
        "Create a task named First and a task named Second."
        if second_title
        else "Create a task named First and another task with a suitable title."
    )
    budget = build_default_run_budget()
    budget["llm_calls_used"] = used
    return cast(
        PlanningLocalState,
        {
            "run_id": "run-planning",
            "user_request": request,
            "request_intent": {
                "schema_version": 3,
                "goal": request,
                "completion_conditions": ["Two independent Task previews."],
                "constraints": [
                    {"kind": "RESOURCE", "field": "title", "value": title, "work_unit_ids": [work]}
                    for work, title in titles
                ],
                "requested_effect_hints": ["CREATE"],
                "requested_resource_hints": ["TASK"],
                "resource_responsibilities": {
                    "source_reads": [],
                    "outputs": [
                        {
                            "resource_type": "TASK",
                            "effect": "CREATE",
                            "work_unit_ids": [f"work-{i}"],
                        }
                        for i in (1, 2)
                    ],
                },
                "effect_prohibitions": [],
                "requested_work": {
                    "work_units": [
                        {
                            "unit_id": f"work-{i}",
                            "request_provenance": [
                                {
                                    "source": "USER_REQUEST",
                                    "source_text": request,
                                    "start_offset": 0,
                                    "end_offset": len(request),
                                }
                            ],
                        }
                        for i in (1, 2)
                    ],
                    "work_relations": [],
                },
                "ambiguity": {"requires_confirmation": False},
            },
            "output_plan": {"output_mode": "ACTION", "output_routes": routes},
            "evidence": [],
            "retry_budget": budget,
            "trace_context": {},
            "action_objective_candidates": [
                {
                    "schema_version": 1,
                    "route_id": route["route_id"],
                    "objective": "Create the independent Task",
                    "target_semantics": "TASK",
                    "scope_constraints": [],
                    "evidence_refs": [],
                }
                for route in routes
            ],
            "__request__": WorkflowStartRequest(
                "run-planning",
                "conversation",
                "workflow",
                "AGENT_SEARCH",
                "LOCAL_GPU",
                request,
                (),
                WorkflowCorrelationContext("req", None, "v1"),
                budget,
            ),
        },
    )


def _graph(runtime: _DispatchRuntime, **overrides: Any) -> PlanningSubgraph:
    identifiers = count(1)
    options: dict[str, Any] = {
        "llm_runtime": runtime,
        "prompt_execution_scope": DEVELOPMENT_SMOKE,
        "graph_profile": GraphProfile.SIX_ROLE_BASELINE,
        "id_factory": lambda: f"id-{next(identifiers)}",
        "default_tasklist_id_provider": lambda: "tasklist",
        **overrides,
    }
    return PlanningSubgraph(**options)


def _run(node: str, state: PlanningLocalState, runtime: _DispatchRuntime) -> PlanningLocalState:
    graph = _graph(runtime)
    if node == "objective":
        return graph._draft_action_objective_node(state)
    return graph._compose_arguments_node(state)


@pytest.mark.parametrize("node", ["objective", "arguments"])
@pytest.mark.parametrize("used", [0, 99, 100])
def test_two_route_exact_titles__zero_calls_even_at_cap__no_lazy_prompt_keyerror(
    node: str, used: int
) -> None:
    state, runtime = _state(second_title=True, used=used), _DispatchRuntime()

    result = _run(node, state, runtime)

    assert runtime.calls == []
    assert result["retry_budget"]["llm_calls_used"] == used
    assert result["trace_context"]["llm_call_count"] == 0
    assert result["trace_context"]["prompt_refs"] == []
    if node == "arguments":
        assert [
            item["arguments"]["payload"]["title"] for item in result["argument_candidates"]
        ] == ["First", "Second"]


@pytest.mark.parametrize("node", ["objective", "arguments"])
@pytest.mark.parametrize("dispatches", [1, 2])
def test_other_work_without_exact_title__one_infer__actual_dispatches_counted(
    node: str, dispatches: int
) -> None:
    state = _state(second_title=False, used=3)
    runtime = _DispatchRuntime(dispatches_per_infer=dispatches)
    before = deepcopy(state["request_intent"])

    result = _run(node, state, runtime)

    assert len(runtime.calls) == 1
    assert result["retry_budget"]["llm_calls_used"] == 3 + dispatches
    assert result["trace_context"]["llm_call_count"] == dispatches
    observed = cast(dict[str, Any], runtime.calls[0])
    assert observed["output_route"]["work_unit_ids"] == ["work-2"]
    assert observed["request_intent"]["constraints"] == []
    assert state["request_intent"] == before
    if node == "objective":
        assert observed["user_request"] == state["user_request"]
    else:
        assert (
            result["argument_candidates"][1]["arguments"]["payload"]["title"] == "Second composed"
        )


@pytest.mark.parametrize("node", ["objective", "arguments"])
def test_required_call_at_cap__still_denied_before_inference(node: str) -> None:
    runtime = _DispatchRuntime()
    with pytest.raises(LLMInvocationError, match="ABSOLUTE_LLM_LIMIT_EXHAUSTED"):
        _run(node, _state(second_title=False, used=100), runtime)
    assert runtime.calls == []


@pytest.mark.parametrize("node", ["objective", "arguments"])
def test_work_bound_evidence__only_needed_route_calls__does_not_leak_other_refs(node: str) -> None:
    state = _state(second_title=False)
    state["evidence"] = [{"evidence_id": "e-first"}, {"evidence_id": "e-second"}]
    state["retrieval_result"] = cast(
        Any,
        {
            "evidence_by_work_unit": [
                {"work_unit_id": "work-1", "evidence_refs": ["e-first"]},
                {"work_unit_id": "work-2", "evidence_refs": ["e-second"]},
            ]
        },
    )
    runtime = _DispatchRuntime()

    result = _run(node, state, runtime)

    assert len(runtime.calls) == 1
    assert runtime.calls[0]["evidence"] == [{"evidence_id": "e-second"}]
    assert result["trace_context"]["llm_call_count"] == 1


def test_warmed_objective_prompt_cache__new_deterministic_run__no_unused_prompt_ref() -> None:
    runtime = _DispatchRuntime()
    graph = _graph(runtime)
    with provider_dispatch_execution_scope():
        first = graph._draft_action_objective_node(_state(second_title=False))
    assert first["__planning_agent_local__"]["prompt_ref"] is not None

    with provider_dispatch_execution_scope():
        result = graph._draft_action_objective_node(_state(second_title=True))

    assert len(runtime.calls) == 1
    assert result["trace_context"]["llm_call_count"] == 0
    assert result["__planning_agent_local__"]["prompt_ref"] is None


def test_missing_container__all_schema_binding_precedes_inference__zero_dispatch() -> None:
    state = _state(second_title=False)
    runtime = _DispatchRuntime()
    graph = _graph(runtime, default_tasklist_id_provider=None)

    result = graph._compose_arguments_node(state)

    assert runtime.calls == []
    assert result["final_result"]["disposition"] == "NEEDS_CONFIRMATION"
    assert state["retry_budget"]["llm_calls_used"] == 0
    assert not result.get("trace_context", {}).get("llm_call_count", 0)


def test_satisfied_draft__production_answer_return__keeps_actual_dispatch_usage() -> None:
    state = _state(second_title=False)
    intent = cast(dict[str, Any], state["request_intent"])
    intent["constraints"] = []
    intent["requested_work"]["work_units"] = intent["requested_work"]["work_units"][:1]
    intent["resource_responsibilities"] = {
        "source_reads": [{"resource_type": "GMAIL_DRAFT", "work_unit_ids": ["work-1"]}],
        "outputs": [
            {"resource_type": "GMAIL_DRAFT", "effect": "UPDATE", "work_unit_ids": ["work-1"]}
        ],
    }
    state["output_plan"]["output_routes"] = [
        {
            "route_id": "route-1",
            "work_unit_ids": ["work-1"],
            "connector_id": "google_workspace",
            "resource_type": "GMAIL_DRAFT",
            "effect": "UPDATE",
            "selected_tool_id": "gmail_update_draft",
        }
    ]
    state["action_objective_candidates"] = [
        {
            "schema_version": 1,
            "route_id": "route-1",
            "objective": "Preserve requested body",
            "target_semantics": "GMAIL_DRAFT",
            "scope_constraints": [],
            "evidence_refs": ["e-draft"],
        }
    ]
    state["evidence"] = [
        {
            "evidence_id": "e-draft",
            "resource_handle": "gmail_draft:d1",
            "locator": {"source_version_ref": "version-1"},
        }
    ]
    store = RunScopedEvidenceStore()
    store.put_resource_snapshot(
        run_id=state["run_id"],
        resource_handle="gmail_draft:d1",
        source_version_ref="version-1",
        snapshot={
            "to": ["recipient@example.com"],
            "cc": [],
            "bcc": [],
            "subject": "Current draft",
            "body": "Already present",
            "thread_id": None,
            "in_reply_to": None,
            "references": None,
            "attachments": [],
        },
    )
    runtime = _DispatchRuntime(dispatches_per_infer=2, payload={"body": "Already present"})
    graph = _graph(
        runtime,
        evidence_store=store,
        merge_decision=lambda original, update, decision: {**original, **update},
    )

    result = graph._compose_arguments_node(state)

    assert len(runtime.calls) == 1
    assert result["planning_disposition"] == "ANSWER"
    assert result["final_result"]["evidence_refs"] == ["e-draft"]
    assert result["retry_budget"]["llm_calls_used"] == 2
    assert result["trace_context"]["llm_call_count"] == 2
    assert "__planning_action_seeds__" not in result
