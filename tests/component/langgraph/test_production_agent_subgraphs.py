from __future__ import annotations

from collections.abc import Callable, Mapping
from itertools import count
from typing import Any, cast

import pytest
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt

from google_work_agent.adapters.langgraph.main.state import (
    GraphState,
    WorkflowPhase,
    initial_graph_state,
)
from google_work_agent.adapters.langgraph.main.supervisor import route_supervisor
from google_work_agent.adapters.langgraph.profiles.profile_registry import GraphProfile
from google_work_agent.adapters.langgraph.subgraphs.planning.graph import (
    PlanningRuntimeDependencies,
    PlanningSubgraph,
)
from google_work_agent.adapters.langgraph.subgraphs.planning.routing import (
    route_after_assemble_plan as planning_assemble_routing,
)
from google_work_agent.adapters.langgraph.subgraphs.request_understanding.graph import (
    RequestUnderstandingSubgraph,
)
from google_work_agent.adapters.langgraph.subgraphs.request_understanding.routing import (
    route_after_finalize_intent as request_finalize_routing,
)
from google_work_agent.adapters.langgraph.subgraphs.retrieval.graph import RetrievalSubgraph
from google_work_agent.adapters.langgraph.subgraphs.review.graph import (
    ReviewRuntimeDependencies,
    ReviewSubgraph,
)
from google_work_agent.adapters.langgraph.subgraphs.review.routing.route_after_entry import (
    route_after_entry,
)
from google_work_agent.adapters.langgraph.subgraphs.tool_routing.graph import ToolRoutingSubgraph
from google_work_agent.adapters.langgraph.subgraphs.tool_routing.routing import (
    route_after_validate_route as tool_validation_routing,
)
from google_work_agent.adapters.langgraph.subgraphs.work_analysis.graph import WorkAnalysisSubgraph
from google_work_agent.adapters.langgraph.subgraphs.work_analysis.routing import (
    route_after_assess_information_gaps as work_gap_routing,
)
from google_work_agent.adapters.system.memory.retrieval_evidence_store import (
    RunScopedEvidenceStore,
)
from google_work_agent.adapters.system.memory.run_retrieval_cache import (
    InMemoryRunRetrievalCache,
)
from google_work_agent.application.agents.planning.contracts.planning_semantics import (
    PlanningSemanticInvoker,
)
from google_work_agent.application.agents.review.contracts.review_findings import (
    ReviewSemanticInvoker,
)
from google_work_agent.application.prompt_runtime.prompt_registry import DEVELOPMENT_SMOKE
from google_work_agent.application.tool_registry.load_signed_tool_registry import (
    load_development_tool_registry,
)
from google_work_agent.application.use_cases.run.account_provider_dispatch import (
    provider_dispatch_execution_scope,
)
from google_work_agent.application.use_cases.run.guard_run_budget import build_default_run_budget
from google_work_agent.ports.connector.connector_read_port import ConnectorReadResultV1
from google_work_agent.ports.llm.output_schema_validation import validate_output_schema
from google_work_agent.ports.llm.structured_inference_contracts import (
    OutputSchemaDefinition,
    PromptReference,
)
from google_work_agent.ports.llm.structured_inference_port import StructuredInferenceResultV1
from google_work_agent.ports.system.contracts.confirmation import (
    ConfirmationResponseProjectionV1,
)
from google_work_agent.ports.system.contracts.workflow_execution import (
    SelectedResourceRef,
    WorkflowCorrelationContext,
    WorkflowStartRequest,
)


class _IdFactory:
    def __init__(self) -> None:
        self._values = count()

    def __call__(self) -> str:
        return f"component-id-{next(self._values)}"


class _ComponentInferencePort:
    def __init__(
        self,
        *,
        request_confirmation: bool = False,
        work_fact_count: int = 0,
        retrieval_needs_more: bool = False,
        retrieval_followup_changes_query: bool = True,
        github_retrieval: bool = False,
    ) -> None:
        self.request_confirmation = request_confirmation
        self.github_retrieval = github_retrieval
        self.work_fact_count = work_fact_count
        self.retrieval_needs_more = retrieval_needs_more
        self.retrieval_followup_changes_query = retrieval_followup_changes_query
        self.calls: list[str] = []

    def infer(
        self,
        requested_mode: str,
        prompt_ref: PromptReference,
        input_projection: Mapping[str, object],
        output_schema_ref: OutputSchemaDefinition,
    ) -> StructuredInferenceResultV1:
        del requested_mode
        prompt_id = prompt_ref.prompt_id
        self.calls.append(prompt_id)
        base = input_projection.get("base_projection", input_projection)
        projection = cast(Mapping[str, object], base)
        output = self._response(prompt_id, projection)
        if self.github_retrieval:
            assert not validate_output_schema(output, output_schema_ref.json_schema)
        return StructuredInferenceResultV1(
            schema_version=1,
            structured_output=output,
            provider="component-fake",
            model="component-fake",
            actual_runtime="API_LLM",
            input_tokens=1,
            output_tokens=1,
            latency_ms=1,
            fallback_reason=None,
        )

    def _response(self, prompt_id: str, projection: Mapping[str, object]) -> dict[str, object]:
        has_confirmation = isinstance(projection.get("confirmation_response"), Mapping)
        if prompt_id == "request_understanding.identify_goal":
            return {
                "goal": "schedule team sync" if has_confirmation else "summarize status",
                "completion_conditions": ["return a result"],
                "constraints": [],
                "requested_effect_hints": ["CREATE"] if has_confirmation else [],
                "requested_resource_hints": ["CALENDAR_EVENT"] if has_confirmation else [],
                "analysis_requirement": "NONE",
            }
        if prompt_id == "request_understanding.detect_ambiguity":
            needs_confirmation = self.request_confirmation and not has_confirmation
            return {
                "requires_confirmation": needs_confirmation,
                "missing_information_owner": "USER" if needs_confirmation else "NONE",
                "reason_codes": ["MISSING_TARGET"] if needs_confirmation else [],
                "missing_fields": ["target"] if needs_confirmation else [],
            }
        if prompt_id == "tool_routing.determine_io_resources":
            return {
                "schema_version": 1,
                "input_resource_types": [],
                "output_resource_types": [],
                "output_effects": [],
                "disposition": "NO_TOOL_NEEDED",
            }
        if prompt_id == "retrieval.plan_query":
            current_round_no = projection.get("current_round_no")
            search_spec: dict[str, object] = (
                {
                    "mode": "CHANGED",
                    "constraint_delta": {
                        "upsert_constraints": [
                            {
                                "kind": "KEYWORD",
                                "terms": [
                                    f"status-{current_round_no}"
                                    if self.retrieval_followup_changes_query
                                    else "status"
                                ],
                                "match_mode": "ANY",
                            }
                        ],
                        "remove_constraint_kinds": [],
                    },
                }
                if current_round_no is not None
                else {
                    "mode": "INITIAL",
                    "constraints": [
                        {
                            "kind": "KEYWORD",
                            "terms": ["status"],
                            "match_mode": "ANY",
                        }
                    ],
                }
            )
            if self.github_retrieval:
                input_routes = cast(list[Mapping[str, object]], projection["input_routes"])
                assert input_routes[0].get("container_refs") == ["acme/repo"]
                search_spec = {
                    "mode": "INITIAL",
                    "constraints": [{"kind": "CONTAINER_REF", "container_refs": ["acme/repo"]}],
                }
            return {
                "schema_version": 2,
                "route_queries": [
                    {
                        "route_id": "route-1",
                        "operation": "SEARCH",
                        "reason_codes": ["USER_REQUEST"],
                        "search_spec": search_spec,
                        "detail_candidate_ref": None,
                    }
                ],
                "required_information": ["status"],
                "retrieval_order": ["route-1"],
            }
        if prompt_id == "retrieval.select_evidence":
            ranked = cast(list[Mapping[str, object]], projection.get("ranked_segments", []))
            segment_ids = [str(item["segment_id"]) for item in ranked]
            return {
                "schema_version": 3,
                "segment_assessments": {
                    segment_id: {
                        "role": "SUPPORTS",
                        "relevance_reason": "status evidence",
                    }
                    for segment_id in segment_ids
                },
            }
        if prompt_id == "retrieval.assess_sufficiency":
            if self.retrieval_needs_more:
                return {
                    "schema_version": 2,
                    "status": "NEEDS_MORE_DATA",
                    "issues": [
                        {
                            "slot": "approved_budget",
                            "issue_type": "MISSING",
                            "required": True,
                            "resolution_source": "GOOGLE",
                            "safety_critical": False,
                            "reason_codes": ["APPROVED_BUDGET_NOT_FOUND"],
                        }
                    ],
                }
            return {"schema_version": 2, "status": "SUFFICIENT", "issues": []}
        if prompt_id == "work_analysis.extract_work_facts":
            return {
                "fact_candidates": [
                    {
                        "kind": "TASK",
                        "subject": f"task-{index}",
                        "value": f"task-{index}",
                        "derivation": "EXPLICIT",
                        "evidence_refs": [
                            item["evidence_id"]
                            for item in cast(list[dict[str, object]], projection["evidence"])
                        ],
                    }
                    for index in range(self.work_fact_count)
                ]
            }
        if prompt_id in {
            "work_analysis.resolve_entity_relations",
            "work_analysis.resolve_temporal_dependencies",
            "work_analysis.detect_duplicate_conflict_candidates",
        }:
            return {"relation_candidates": []}
        if prompt_id == "work_analysis.assess_information_gaps":
            return {
                "disposition": "COMPLETE",
                "ambiguities": [],
                "retrieval_needs": [],
                "evidence_refs": [],
            }
        if prompt_id == "work_analysis.assess_operational_risks":
            return {
                "risks": [],
                "action_necessity_candidate": "NOT_REQUIRED",
                "action_necessity_reason": "Answer only",
                "evidence_refs": [],
            }
        raise AssertionError(f"unexpected component Prompt: {prompt_id}")


class _ComponentConnectorReadPort:
    def __init__(self) -> None:
        self.call_count = 0

    def execute_read(self, binding: Any, tool_arguments: dict[str, Any]) -> ConnectorReadResultV1:
        del tool_arguments
        self.call_count += 1
        return ConnectorReadResultV1(
            schema_version=1,
            tool_id=binding.tool_id,
            request_id="component-read-1",
            output={
                "items": [
                    {
                        "resource_type": "gmail_thread",
                        "resource_id": "thread-1",
                        "parent_id": None,
                        "version": "v1",
                        "related_resource_ids": [],
                        "payload": {"subject": "Weekly status"},
                    }
                ]
            },
            next_page_token=None,
            total_count=1,
        )


def _state(
    *,
    initial_target: str = "request_understanding",
    selected_resources: tuple[SelectedResourceRef, ...] = (),
) -> GraphState:
    request = WorkflowStartRequest(
        run_id="component-run-1",
        conversation_id="component-conversation-1",
        workflow_key="component-thread-1",
        entry_mode="AGENT_SEARCH",
        requested_mode="AUTO",
        request_text="summarize status",
        selected_resource_ids=(),
        run_budget=build_default_run_budget(),
        correlation=WorkflowCorrelationContext("component-request-1", None, "1"),
        selected_resources=selected_resources,
    )
    return initial_graph_state(
        request,
        graph_profile=GraphProfile.SIX_ROLE_BASELINE,
        graph_version="component-test",
        initial_target=initial_target,
    )


def _intent() -> dict[str, object]:
    return {
        "schema_version": 2,
        "goal": "summarize status",
        "completion_conditions": ["return a result"],
        "constraints": [],
        "requested_effect_hints": ["READ"],
        "requested_resource_hints": [],
        "analysis_requirement": "NONE",
        "ambiguity": {
            "requires_confirmation": False,
            "reason_codes": [],
            "missing_fields": [],
        },
        "meta": {"artifact_id": "intent-1", "revision": 1, "based_on": []},
    }


def _answer_route_plan(*, with_input_route: bool = False) -> dict[str, object]:
    input_routes: list[dict[str, object]] = []
    if with_input_route:
        input_routes.append(
            {
                "route_id": "route-1",
                "resource_type": "EMAIL",
                "connector_id": "google_workspace",
                "allowed_read_tool_ids": ["gmail_search_threads"],
                "required": True,
                "reason_codes": ["USER_REQUEST"],
            }
        )
    based_on = [{"artifact_id": "intent-1", "revision": 1}]
    return {
        "schema_version": 2,
        "input_plan": {
            "schema_version": 1,
            "meta": {"artifact_id": "input-1", "revision": 1, "based_on": based_on},
            "input_routes": input_routes,
        },
        "output_plan": {
            "schema_version": 1,
            "meta": {"artifact_id": "output-1", "revision": 1, "based_on": based_on},
            "output_mode": "ANSWER",
        },
        "tool_registry_version": "component-test",
    }


def _task_create_route_plan() -> dict[str, object]:
    result = _answer_route_plan()
    result["input_plan"] = {
        "schema_version": 1,
        "meta": {
            "artifact_id": "input-task-1",
            "revision": 1,
            "based_on": [{"artifact_id": "intent-1", "revision": 1}],
        },
        "input_routes": [
            {
                "route_id": "input-task-route",
                "resource_type": "TASK",
                "connector_id": "google_workspace",
                "allowed_read_tool_ids": ["tasks_list_tasks"],
                "required": True,
                "reason_codes": ["POLICY_TASK_DUPLICATE_CHECK"],
            }
        ],
    }
    result["output_plan"] = {
        "schema_version": 1,
        "meta": {
            "artifact_id": "output-task-1",
            "revision": 1,
            "based_on": [{"artifact_id": "intent-1", "revision": 1}],
        },
        "output_mode": "ACTION",
        "output_routes": [
            {
                "route_id": "output-task-route",
                "resource_type": "TASK",
                "connector_id": "google_workspace",
                "effect": "CREATE",
                "selected_tool_id": "tasks_create_task",
                "reason_codes": ["USER_REQUEST"],
            }
        ],
    }
    return result


def _retrieval_result() -> dict[str, object]:
    return {
        "schema_version": 1,
        "meta": {
            "artifact_id": "retrieval-1",
            "revision": 1,
            "based_on": [{"artifact_id": "intent-1", "revision": 1}],
        },
        "coverage": "NO_FETCH_NEEDED",
        "context_bundle_ref": None,
        "evidence_refs": [],
        "selected_segment_ids": [],
        "excluded_segment_ids": [],
        "source_resource_refs": [],
        "source_statuses": [],
        "availability_results": [],
        "missing_information": [],
        "retrieval_rounds": 0,
    }


def _merge_decision(
    state: Mapping[str, object], update: Mapping[str, object], decision: Mapping[str, object]
) -> dict[str, object]:
    decision_state = cast(Mapping[str, object], decision["state_update"])
    return {
        **state,
        **update,
        **decision_state,
        "__target__": cast(str, decision["target"]),
    }


def _confirm_early(_state: object) -> tuple[None, dict[str, object]]:
    return None, {"__target__": "end", "__workflow_control__": {"stage": "PAUSED"}}


def _edge_set(graph: Any) -> set[tuple[str, str]]:
    return {(edge.source, edge.target) for edge in graph.get_graph().edges}


def test_request_understanding__compiled_normal_path__produces_intent() -> None:
    llm = _ComponentInferencePort()
    graph = RequestUnderstandingSubgraph(
        llm_runtime=llm,
        prompt_manifest_path=None,
        prompt_execution_scope=DEVELOPMENT_SMOKE,
        id_factory=_IdFactory(),
        graph_profile=GraphProfile.SIX_ROLE_BASELINE,
        transition_run=lambda _run_id, _transition: None,
        merge_decision=cast(Any, _merge_decision),
        confirm_inline=_confirm_early,
    ).build()

    with provider_dispatch_execution_scope():
        result = graph.invoke(_state())

    assert result["request_intent"]["goal"] == "summarize status"
    assert llm.calls == [
        "request_understanding.identify_goal",
        "request_understanding.detect_ambiguity",
    ]
    assert ("finalize_intent", "identify_goal") in _edge_set(graph)


def test_tool_routing__compiled_normal_path__produces_answer_route() -> None:
    state = _state(initial_target="tool_route")
    state["request_intent"] = cast(Any, _intent())
    llm = _ComponentInferencePort()
    graph = ToolRoutingSubgraph(
        llm_runtime=llm,
        tool_catalog=load_development_tool_registry(),
        prompt_manifest_path=None,
        prompt_execution_scope=DEVELOPMENT_SMOKE,
        graph_profile=GraphProfile.SIX_ROLE_BASELINE,
        merge_decision=cast(Any, _merge_decision),
        confirm_inline=cast(Any, _confirm_early),
        id_factory=_IdFactory(),
    ).build()

    with provider_dispatch_execution_scope():
        result = graph.invoke(state)

    assert result["tool_route_plan"]["output_plan"]["output_mode"] == "ANSWER"
    assert llm.calls == ["tool_routing.determine_io_resources"]
    assert ("finalize_route", "determine_io_resources") in _edge_set(graph)


def test_retrieval__compiled_normal_path__materializes_evidence() -> None:
    state = _state(initial_target="context_retriever")
    state["request_intent"] = cast(Any, _intent())
    state["tool_route_plan"] = cast(Any, _answer_route_plan(with_input_route=True))
    llm = _ComponentInferencePort()
    connector = _ComponentConnectorReadPort()
    graph = RetrievalSubgraph(
        now_ms=lambda: 1_000,
        should_stop_for_cancel=lambda _run_id: False,
        timezone_provider=lambda: "Asia/Seoul",
        llm_runtime=llm,
        prompt_manifest_path=None,
        prompt_execution_scope=DEVELOPMENT_SMOKE,
        id_factory=_IdFactory(),
        graph_profile=GraphProfile.SIX_ROLE_BASELINE,
        transition_run=lambda _run_id, _transition: None,
        merge_decision=cast(Any, _merge_decision),
        evidence_store=RunScopedEvidenceStore(),
        connector_reader=connector,
        tool_catalog=load_development_tool_registry(),
        read_result_cache=InMemoryRunRetrievalCache(),
        confirm_inline=cast(Any, _confirm_early),
    ).build()

    with provider_dispatch_execution_scope():
        result = graph.invoke(state)

    assert result["retrieval_result"]["coverage"] == "SUFFICIENT"
    assert result["retrieval_result"]["evidence_refs"]
    assert connector.call_count == 1
    assert set(graph.get_graph().nodes) == {
        "__start__", "__end__", "plan_query", "build_query", "execute_read",
        "normalize_segments", "rag_retrieve", "select_evidence", "assess_sufficiency", "finalize",
    }
    assert all((node, "__end__") in _edge_set(graph) for node in (
        "plan_query", "build_query", "execute_read", "normalize_segments", "rag_retrieve",
        "select_evidence", "assess_sufficiency", "finalize",
    ))
    assert ("assess_sufficiency", "plan_query") in _edge_set(graph)
    assert ("finalize", "finalize") in _edge_set(graph)


@pytest.mark.parametrize("cancel_after, expected_reads, expected_prompts", [
    ("retrieval.plan_query", 0, ["retrieval.plan_query"]),
    ("connector", 1, ["retrieval.plan_query"]),
    ("retrieval.select_evidence", 1, ["retrieval.plan_query", "retrieval.select_evidence"]),
    ("retrieval.assess_sufficiency", 1, ["retrieval.plan_query", "retrieval.select_evidence",
                                        "retrieval.assess_sufficiency"]),
])
def test_retrieval_cancellation_returns_to_main_without_another_external_call(
    cancel_after: str, expected_reads: int, expected_prompts: list[str],
) -> None:
    from google_work_agent.adapters.langgraph.main.routing.route_after_context_retriever import (
        route_after_context_retriever,
    )

    cancelled = False

    class CancelAfterInference(_ComponentInferencePort):
        def _response(self, prompt_id: str, projection: Mapping[str, object]) -> dict[str, object]:
            nonlocal cancelled
            result = super()._response(prompt_id, projection)
            if prompt_id == cancel_after:
                cancelled = True
            return result

    class CancelAfterRead(_ComponentConnectorReadPort):
        def execute_read(
            self, binding: Any, arguments: Mapping[str, object],
        ) -> ConnectorReadResultV1:
            nonlocal cancelled
            result = super().execute_read(binding, arguments)
            if cancel_after == "connector":
                cancelled = True
            return result

    state = _state(initial_target="context_retriever")
    state["request_intent"] = cast(Any, _intent())
    state["tool_route_plan"] = cast(Any, _answer_route_plan(with_input_route=True))
    llm = CancelAfterInference()
    connector = CancelAfterRead()
    graph = RetrievalSubgraph(
        should_stop_for_cancel=lambda _run_id: cancelled,
        now_ms=lambda: 1_000, timezone_provider=lambda: "Asia/Seoul",
        llm_runtime=llm, prompt_manifest_path=None, prompt_execution_scope=DEVELOPMENT_SMOKE,
        id_factory=_IdFactory(), graph_profile=GraphProfile.SIX_ROLE_BASELINE,
        transition_run=lambda _run_id, _transition: None,
        merge_decision=cast(Any, _merge_decision), evidence_store=RunScopedEvidenceStore(),
        connector_reader=connector, tool_catalog=load_development_tool_registry(),
        read_result_cache=InMemoryRunRetrievalCache(), confirm_inline=cast(Any, _confirm_early),
    ).build()
    with provider_dispatch_execution_scope():
        result = graph.invoke(state)

    assert connector.call_count == expected_reads
    assert llm.calls == expected_prompts
    assert result.get("retrieval_result") is None  # No fabricated successful handoff.
    assert route_after_context_retriever(
        result, available_targets=frozenset({"end"}),
        should_stop_for_cancel=lambda _run_id: cancelled,
    ) == "end"  # Release the invocation for the existing cancellation command owner.


@pytest.mark.parametrize("cancel_after_update, expected_reads, expected_prompts", [
    ("build_query", 0, ["retrieval.plan_query"]),
    ("rag_retrieve", 1, ["retrieval.plan_query"]),
    ("select_evidence", 1, ["retrieval.plan_query", "retrieval.select_evidence"]),
])
def test_retrieval_cancellation_between_scheduled_nodes_prevents_new_io(
    cancel_after_update: str, expected_reads: int, expected_prompts: list[str],
) -> None:
    cancelled = False
    state = _state(initial_target="context_retriever")
    state["request_intent"] = cast(Any, _intent())
    state["tool_route_plan"] = cast(Any, _answer_route_plan(with_input_route=True))
    llm = _ComponentInferencePort()
    connector = _ComponentConnectorReadPort()
    graph = RetrievalSubgraph(
        should_stop_for_cancel=lambda _run_id: cancelled,
        now_ms=lambda: 1_000, timezone_provider=lambda: "Asia/Seoul",
        llm_runtime=llm, prompt_manifest_path=None, prompt_execution_scope=DEVELOPMENT_SMOKE,
        id_factory=_IdFactory(), graph_profile=GraphProfile.SIX_ROLE_BASELINE,
        transition_run=lambda _run_id, _transition: None,
        merge_decision=cast(Any, _merge_decision), evidence_store=RunScopedEvidenceStore(),
        connector_reader=connector, tool_catalog=load_development_tool_registry(),
        read_result_cache=InMemoryRunRetrievalCache(), confirm_inline=cast(Any, _confirm_early),
    ).build()
    updates = []
    with provider_dispatch_execution_scope():
        for update in graph.stream(state, stream_mode="updates"):
            updates.append(update)
            if cancel_after_update in update:
                cancelled = True
    assert cancelled
    assert connector.call_count == expected_reads
    assert llm.calls == expected_prompts
    assert not any("finalize" in update for update in updates)


@pytest.mark.parametrize("date_rich", [False, True])
def test_retrieval__three_details__preserve_one_search_round(date_rich: bool) -> None:
    from datetime import datetime

    run_start = int(datetime.fromisoformat("2026-09-06T23:59:55+09:00").timestamp() * 1000)

    class TemporalInference(_ComponentInferencePort):
        def __init__(self) -> None:
            super().__init__()
            self.assessed_resources: list[list[str]] = []

        def _response(self, prompt_id: str, projection: Mapping[str, object]) -> dict[str, object]:
            if prompt_id == "retrieval.select_evidence":
                self.assessed_resources.append([
                    str(segment["resource_ref"])
                    for segment in cast(list[dict[str, Any]], projection["ranked_segments"])
                ])
                for segment in cast(list[dict[str, Any]], projection["ranked_segments"]):
                    annotation = segment["temporal_date_candidates"][0]
                    assert annotation["target_index"] == 0
                    assert annotation["date_mentions_truncated"] is date_rich
                    assert len(annotation["date_mentions"]) == (12 if date_rich else 1)
                    assert annotation["date_mentions"][0] == {
                        "source_text": "2026년 9월 3일", "candidate_date": "2026-09-03",
                        "year_explicit": True, "date_intersects_window": True,
                    }
            if prompt_id in {"retrieval.select_evidence", "retrieval.assess_sufficiency"}:
                assert projection["temporal_constraints"] == [
                    {
                        "kind": "TEMPORAL_RANGE",
                        "axis": "EVENT_TIME",
                        "timezone": "Asia/Seoul",
                        "start_local": "2026-08-31T00:00:00",
                        "end_local": "2026-09-07T00:00:00",
                    }
                ]
            return super()._response(prompt_id, projection)

    class DetailConnector:
        def __init__(self) -> None:
            self.calls: list[tuple[str, dict[str, Any]]] = []

        def execute_read(self, binding: Any, arguments: dict[str, Any]) -> ConnectorReadResultV1:
            self.calls.append((binding.tool_id, dict(arguments)))
            ids = (
                [arguments["thread_id"]]
                if binding.tool_id == "gmail_get_thread"
                else ["one", "two", "three"]
            )
            items = [
                {
                    "resource_type": "gmail_thread",
                    "resource_id": resource_id,
                    "parent_id": None,
                    "version": "v1",
                    "related_resource_ids": [],
                    "payload": {
                        "subject": f"Status {resource_id}",
                        "body": f"회의 일정은 2026년 9월 3일 {resource_id}" + (
                            " ".join(f"2026년 9월 {day}일" for day in range(1, 22))
                            if date_rich else ""
                        ),
                    },
                }
                for resource_id in ids
            ]
            output = (
                {"item": items[0]} if binding.tool_id == "gmail_get_thread" else {"items": items}
            )
            return ConnectorReadResultV1(
                1, binding.tool_id, "detail-test", output, None, len(items)
            )

    state = _state(initial_target="context_retriever")
    intent = _intent()
    intent["requested_resource_hints"] = ["GMAIL_THREAD"]
    intent["constraints"] = [{"kind": "TIME", "field": "temporal_axis", "value": "EVENT_TIME"}]
    intent["constraints"].append({"kind": "DATE", "field": "period", "value": "이번주"})
    intent["constraints"].append(
        {"kind": "USER_REQUIREMENT", "field": "business_concepts", "value": ["일정"]}
    )
    state["retry_budget"]["started_at_ms"] = run_start
    state["request_intent"] = cast(Any, intent)
    routes = _answer_route_plan(with_input_route=True)
    cast(Any, routes)["input_plan"]["input_routes"][0]["allowed_read_tool_ids"].append(
        "gmail_get_thread"
    )
    cast(Any, routes)["input_plan"]["input_routes"][0]["resource_type"] = "GMAIL_THREAD"
    state["tool_route_plan"] = cast(Any, routes)
    connector = DetailConnector()
    inference = TemporalInference()
    graph = RetrievalSubgraph(
        now_ms=lambda: run_start + 10_000,
        should_stop_for_cancel=lambda _run_id: False,
        timezone_provider=lambda: "Asia/Seoul",
        llm_runtime=inference,
        prompt_manifest_path=None,
        prompt_execution_scope=DEVELOPMENT_SMOKE,
        id_factory=_IdFactory(),
        graph_profile=GraphProfile.SIX_ROLE_BASELINE,
        transition_run=lambda _run_id, _transition: None,
        merge_decision=cast(Any, _merge_decision),
        evidence_store=RunScopedEvidenceStore(),
        connector_reader=connector,
        tool_catalog=load_development_tool_registry(),
        read_result_cache=InMemoryRunRetrievalCache(),
        confirm_inline=cast(Any, _confirm_early),
    ).build()
    with provider_dispatch_execution_scope():
        result = graph.invoke(state, config={"recursion_limit": 100})
    assert len(inference.assessed_resources[0]) == 3
    assert [len(resources) for resources in inference.assessed_resources[1:]] == [1, 1, 1]
    assert set(inference.assessed_resources[0]) == {
        resources[0] for resources in inference.assessed_resources[1:]
    }
    assert result["retrieval_result"]["coverage"] == "SUFFICIENT"
    assert result["retrieval_result"]["retrieval_rounds"] == 1
    assert [tool for tool, _ in connector.calls] == [
        "gmail_search_threads",
        *["gmail_get_thread"] * 3,
    ]
    assert {args["thread_id"] for tool, args in connector.calls if tool == "gmail_get_thread"} == {
        "one",
        "two",
        "three",
    }
    assert result["retry_budget"]["detail_fetches_used"] == 3
    assert result["retry_budget"]["source_page_calls_used"] == 1
    assert result["retry_budget"]["additional_retrieval_rounds_used"] == 0
    assert {attempt["round_no"] for attempt in result["__context_query_attempts__"]} == {0}
    assert result["retrieval_result"]["temporal_constraints"] == [
        {
            "kind": "TEMPORAL_RANGE",
            "axis": "EVENT_TIME",
            "timezone": "Asia/Seoul",
            "start_local": "2026-08-31T00:00:00",
            "end_local": "2026-09-07T00:00:00",
        }
    ]


def test_retrieval__main_back_edge__extends_checkpointed_prior_query() -> None:
    state = _state(initial_target="context_retriever")
    state["request_intent"] = cast(Any, _intent())
    state["tool_route_plan"] = cast(Any, _answer_route_plan(with_input_route=True))
    llm = _ComponentInferencePort()
    connector = _ComponentConnectorReadPort()
    cache = InMemoryRunRetrievalCache()
    graph = RetrievalSubgraph(
        now_ms=lambda: 1_000,
        should_stop_for_cancel=lambda _run_id: False,
        timezone_provider=lambda: "Asia/Seoul",
        llm_runtime=llm,
        prompt_manifest_path=None,
        prompt_execution_scope=DEVELOPMENT_SMOKE,
        id_factory=_IdFactory(),
        graph_profile=GraphProfile.SIX_ROLE_BASELINE,
        transition_run=lambda _run_id, _transition: None,
        merge_decision=cast(Any, _merge_decision),
        evidence_store=RunScopedEvidenceStore(),
        connector_reader=connector,
        tool_catalog=load_development_tool_registry(),
        read_result_cache=cache,
        confirm_inline=cast(Any, _confirm_early),
    ).build()

    with provider_dispatch_execution_scope():
        first = graph.invoke(state)
        second = graph.invoke(
            {
                **first,
                "workflow_signal": {
                    "kind": "RETRIEVAL_REQUIRED",
                    "reason_codes": ["EVIDENCE_GAP"],
                    "needs": [
                        {
                            "required_information": "new status evidence",
                            "reason_codes": ["EVIDENCE_GAP"],
                        }
                    ],
                },
            }
        )

    assert second["retrieval_result"]["meta"]["revision"] == 2
    assert second["retrieval_result"]["retrieval_rounds"] == 2
    assert connector.call_count == 2
    assert llm.calls.count("retrieval.plan_query") == 2
    assert cast(Any, second["__context_query_attempts__"])[0]["normalized_intent_constraints"][0][
        "terms"
    ] == ["status"]
    assert cast(Any, second["__context_query_attempts__"])[1]["normalized_intent_constraints"][0][
        "terms"
    ] == ["status-1"]
    assert len(second["__context_query_attempts__"]) == 2


def test_retrieval__unchanged_main_back_edge__closes_partial_without_a_second_read() -> None:
    state = _state(initial_target="context_retriever")
    state["request_intent"] = cast(Any, _intent())
    state["tool_route_plan"] = cast(Any, _answer_route_plan(with_input_route=True))
    llm = _ComponentInferencePort(retrieval_followup_changes_query=False)
    connector = _ComponentConnectorReadPort()
    graph = RetrievalSubgraph(
        now_ms=lambda: 1_000,
        should_stop_for_cancel=lambda _run_id: False,
        timezone_provider=lambda: "Asia/Seoul",
        llm_runtime=llm,
        prompt_manifest_path=None,
        prompt_execution_scope=DEVELOPMENT_SMOKE,
        id_factory=_IdFactory(),
        graph_profile=GraphProfile.SIX_ROLE_BASELINE,
        transition_run=lambda _run_id, _transition: None,
        merge_decision=cast(Any, _merge_decision),
        evidence_store=RunScopedEvidenceStore(),
        connector_reader=connector,
        tool_catalog=load_development_tool_registry(),
        read_result_cache=InMemoryRunRetrievalCache(),
        confirm_inline=cast(Any, _confirm_early),
    ).build()

    with provider_dispatch_execution_scope():
        first = graph.invoke(state)
        second = graph.invoke(
            {
                **first,
                "workflow_signal": {
                    "kind": "RETRIEVAL_REQUIRED",
                    "reason_codes": ["EVIDENCE_GAP"],
                    "needs": [
                        {
                            "required_information": "new status evidence",
                            "reason_codes": ["EVIDENCE_GAP"],
                        }
                    ],
                },
            }
        )

    assert second["retrieval_result"]["coverage"] == "PARTIAL"
    assert second["retrieval_result"]["meta"]["revision"] == 2
    assert second["retrieval_result"]["retrieval_rounds"] == 1
    assert second["__target__"] == "SOLUTION_PLANNING"
    assert connector.call_count == 1
    assert llm.calls.count("retrieval.plan_query") == 2


def test_retrieval__unchanged_local_followup__closes_partial_without_looping() -> None:
    state = _state(initial_target="context_retriever")
    state["request_intent"] = cast(Any, _intent())
    state["tool_route_plan"] = cast(Any, _answer_route_plan(with_input_route=True))
    llm = _ComponentInferencePort(retrieval_needs_more=True)
    connector = _ComponentConnectorReadPort()
    graph = RetrievalSubgraph(
        now_ms=lambda: 1_000,
        should_stop_for_cancel=lambda _run_id: False,
        timezone_provider=lambda: "Asia/Seoul",
        llm_runtime=llm,
        prompt_manifest_path=None,
        prompt_execution_scope=DEVELOPMENT_SMOKE,
        id_factory=_IdFactory(),
        graph_profile=GraphProfile.SIX_ROLE_BASELINE,
        transition_run=lambda _run_id, _transition: None,
        merge_decision=cast(Any, _merge_decision),
        evidence_store=RunScopedEvidenceStore(),
        connector_reader=connector,
        tool_catalog=load_development_tool_registry(),
        read_result_cache=InMemoryRunRetrievalCache(),
        confirm_inline=cast(Any, _confirm_early),
    ).build()

    with provider_dispatch_execution_scope():
        result = graph.invoke(state)

    assert result["retrieval_result"]["coverage"] == "PARTIAL"
    assert result["retrieval_result"]["retrieval_rounds"] == 1
    assert result["retry_budget"]["additional_retrieval_rounds_used"] == 0
    assert result["__target__"] == "SOLUTION_PLANNING"
    assert connector.call_count == 1
    assert llm.calls.count("retrieval.plan_query") == 1
    assert llm.calls.count("retrieval.assess_sufficiency") == 1


def test_work_analysis__compiled_normal_path__produces_analysis() -> None:
    state = _state(initial_target="work_analysis")
    state["request_intent"] = cast(Any, _intent())
    state["tool_route_plan"] = cast(Any, _answer_route_plan())
    state["retrieval_result"] = cast(Any, _retrieval_result())
    llm = _ComponentInferencePort()
    graph = WorkAnalysisSubgraph(
        llm_runtime=llm,
        prompt_manifest_path=None,
        prompt_execution_scope=DEVELOPMENT_SMOKE,
        id_factory=_IdFactory(),
        graph_profile=GraphProfile.SIX_ROLE_BASELINE,
        transition_run=lambda _run_id, _transition: None,
        merge_decision=cast(Any, _merge_decision),
        evidence_store=RunScopedEvidenceStore(),
        confirm_inline=cast(Any, _confirm_early),
    ).build()

    with provider_dispatch_execution_scope():
        result = graph.invoke(state)

    assert result["work_analysis_result"]["schema_version"] == 2
    assert result["__target__"] == "SOLUTION_PLANNING"
    assert ("extract_work_facts", "resolve_temporal_dependencies") in _edge_set(graph)
    assert ("finalize", "assess_operational_risks") in _edge_set(graph)


def test_work_analysis__policy_only__skips_unrelated_relation_llms() -> None:
    state = _state(initial_target="work_analysis")
    intent = _intent()
    intent["requested_effect_hints"] = ["CREATE"]
    intent["requested_resource_hints"] = ["TASK"]
    state["request_intent"] = cast(Any, intent)
    state["tool_route_plan"] = cast(Any, _task_create_route_plan())
    retrieval = _retrieval_result()
    retrieval["coverage"] = "SUFFICIENT"
    retrieval["evidence_refs"] = ["task-evidence"]
    state["retrieval_result"] = cast(Any, retrieval)
    evidence_store = RunScopedEvidenceStore()
    evidence_store.put(
        run_id=state["run_id"],
        evidence_drafts=[
            {
                "schema_version": 1,
                "evidence_id": "task-evidence",
                "resource_handle": "task:existing",
                "segment_id": "task-segment",
                "kind": "excerpt",
                "excerpt": "task-0 and task-1 are existing tasks",
                "locator": {},
                "reason_codes": ["POLICY_TASK_DUPLICATE_CHECK"],
            }
        ],
    )
    llm = _ComponentInferencePort(work_fact_count=2)
    graph = WorkAnalysisSubgraph(
        llm_runtime=llm,
        prompt_manifest_path=None,
        prompt_execution_scope=DEVELOPMENT_SMOKE,
        id_factory=_IdFactory(),
        graph_profile=GraphProfile.SIX_ROLE_BASELINE,
        transition_run=lambda _run_id, _transition: None,
        merge_decision=cast(Any, _merge_decision),
        evidence_store=evidence_store,
        confirm_inline=cast(Any, _confirm_early),
    ).build()

    with provider_dispatch_execution_scope():
        result = graph.invoke(state)

    assert result["work_analysis_result"]["schema_version"] == 2
    assert llm.calls == [
        "work_analysis.extract_work_facts",
        "work_analysis.detect_duplicate_conflict_candidates",
        "work_analysis.assess_information_gaps",
        "work_analysis.assess_operational_risks",
    ]


def test_planning__compiled_normal_path__produces_answer() -> None:
    calls: list[str] = []

    def invoke(prompt_id: str, _prompt_input: Mapping[str, object]) -> Mapping[str, object]:
        calls.append(prompt_id)
        if prompt_id == "planning.outline_answer":
            return {"sections": ["summary"], "evidence_refs": []}
        return {"schema_version": 2, "answer": "done", "evidence_refs": []}

    graph = PlanningSubgraph(
        dependencies=PlanningRuntimeDependencies(invoke=cast(PlanningSemanticInvoker, invoke))
    ).build()
    result = graph.invoke(
        {
            "user_request": "summarize status",
            "request_intent": _intent(),
            "tool_route_plan": _answer_route_plan(),
            "work_analysis": {},
            "evidence": [],
        }
    )

    assert result["planning_disposition"] == "ANSWER"
    assert calls == ["planning.outline_answer", "planning.compose_answer"]
    assert ("compose_answer", "outline_answer") in _edge_set(graph)


def test_review__compiled_normal_path__passes_review() -> None:
    calls: list[str] = []

    def invoke(prompt_id: str, _prompt_input: Mapping[str, object]) -> Mapping[str, object]:
        calls.append(prompt_id)
        return {"schema_version": 1, "dimension": prompt_id, "findings": []}

    graph = ReviewSubgraph(
        dependencies=ReviewRuntimeDependencies(invoke=cast(ReviewSemanticInvoker, invoke))
    ).build()
    result = graph.invoke(
        {
            "review_phase": "INITIAL",
            "request_intent": _intent(),
            "tool_route_plan": _answer_route_plan(),
            "planning_result": {"answer": "done"},
            "work_analysis": {},
            "evidence": [],
            "policy_summary": {},
            "review_artifact_id": "review-1",
            "review_revision": 1,
            "review_based_on": [],
        }
    )

    assert result["review_result"]["status"] == "PASS"
    assert calls == ["review.inspect_goal_and_evidence"]
    assert ("recheck", "aggregate_findings") in _edge_set(graph)


def test_request_confirmation__interrupts_and_resumes__same_owner() -> None:
    llm = _ComponentInferencePort(request_confirmation=True)

    def confirm_inline(
        state: Mapping[str, object],
    ) -> tuple[ConfirmationResponseProjectionV1, None]:
        user_interrupt = cast(Mapping[str, object], state["user_interrupt"])
        resume = interrupt(
            {
                "semantic_owner_id": "REQUEST_UNDERSTANDING",
                "origin_target": user_interrupt["origin_target"],
            }
        )
        return cast(ConfirmationResponseProjectionV1, resume["confirmation_response"]), None

    request_graph = RequestUnderstandingSubgraph(
        llm_runtime=llm,
        prompt_manifest_path=None,
        prompt_execution_scope=DEVELOPMENT_SMOKE,
        id_factory=_IdFactory(),
        graph_profile=GraphProfile.SIX_ROLE_BASELINE,
        transition_run=lambda _run_id, _transition: None,
        merge_decision=cast(Any, _merge_decision),
        confirm_inline=confirm_inline,
    ).build()
    wrapper = StateGraph(GraphState)
    wrapper.add_node("request_understanding", request_graph)
    wrapper.add_edge(START, "request_understanding")
    wrapper.add_edge("request_understanding", END)
    graph = wrapper.compile(checkpointer=InMemorySaver())
    config: RunnableConfig = {"configurable": {"thread_id": "component-confirmation-thread"}}

    with provider_dispatch_execution_scope():
        interrupted = graph.invoke(_state(), config)

    assert interrupted["__interrupt__"][0].value == {
        "semantic_owner_id": "REQUEST_UNDERSTANDING",
        "origin_target": "request.detect_ambiguity",
    }
    assert graph.get_state(config).next == ("request_understanding",)

    with provider_dispatch_execution_scope():
        resumed = graph.invoke(
            Command(
                resume={
                    "confirmation_response": {
                        "schema_version": 1,
                        "response_kind": "FREE_TEXT",
                        "selected_option": None,
                        "free_text": "team sync tomorrow",
                    }
                }
            ),
            config,
        )

    assert resumed["request_intent"]["goal"] == "schedule team sync"
    assert graph.get_state(config).next == ()
    assert llm.calls.count("request_understanding.identify_goal") == 2


@pytest.mark.parametrize(
    ("router", "state"),
    [
        (request_finalize_routing.route_after_finalize_intent, {}),
        (tool_validation_routing.route_after_validate_route, {}),
        (work_gap_routing.route_after_assess_information_gaps, {}),
        (planning_assemble_routing.route_after_assemble_plan, {}),
        (route_after_entry, {"review_phase": "UNKNOWN"}),
    ],
)
def test_agent_router__unknown_disposition__raises(
    router: Callable[[Any], str], state: dict[str, object]
) -> None:
    with pytest.raises(ValueError):
        router(state)


@pytest.mark.parametrize(
    ("phase", "result"),
    [
        (WorkflowPhase.REQUEST_ANALYSIS, {"result": "UNKNOWN"}),
        (WorkflowPhase.PLAN_REVIEW, {"status": "UNKNOWN"}),
    ],
)
def test_supervisor__unknown_agent_disposition__raises(
    phase: WorkflowPhase, result: dict[str, object]
) -> None:
    state = _state()
    if phase is WorkflowPhase.PLAN_REVIEW:
        state["request_intent"] = cast(Any, _intent())
        state["tool_route_plan"] = cast(Any, _answer_route_plan())
        state["planning_result"] = cast(
            Any,
            {
                "meta": {
                    "artifact_id": "plan-1",
                    "revision": 1,
                    "based_on": [{"artifact_id": "output-1", "revision": 1}],
                },
                "answer": "answer",
            },
        )
    with pytest.raises(ValueError):
        route_supervisor(phase=phase, state=state, result=result)


def test_supervisor__unknown_tool_disposition__routes_recovery() -> None:
    state = _state()
    state["request_intent"] = cast(Any, _intent())
    decision = route_supervisor(
        phase=WorkflowPhase.TOOL_ROUTING,
        state=state,
        result={"disposition": "UNKNOWN"},
    )

    assert decision["target"] == "RECOVERY"
    assert decision["reason_code"] == "TOOL_ROUTE_CONTRACT_VIOLATION"


def test_supervisor__unknown_retrieval_disposition__blocks_instead_of_normal_route() -> None:
    state = _state()
    state["request_intent"] = cast(Any, _intent())
    state["tool_route_plan"] = cast(Any, _answer_route_plan(with_input_route=True))
    decision = route_supervisor(
        phase=WorkflowPhase.CONTEXT_RETRIEVAL,
        state=state,
        result={"disposition": "UNKNOWN", "typed_result": None},
    )

    assert decision["target"] == "FINALIZE"
    finalize_intent = decision["state_update"]["finalize_intent"]
    assert finalize_intent is not None
    assert finalize_intent["intent"] == "BLOCKED"
    assert finalize_intent["reason_code"] == "CONTEXT_BLOCKED"


class _ReadBoundaryReached(RuntimeError):
    pass


class _StoppingGitHubReadPort:
    def __init__(self) -> None:
        self.arguments: dict[str, Any] | None = None
        self.call_count = 0

    def execute_read(self, binding: Any, tool_arguments: dict[str, Any]) -> ConnectorReadResultV1:
        self.call_count += 1
        assert binding.tool_id == "github_list_issues"
        self.arguments = tool_arguments
        raise _ReadBoundaryReached


class _ComponentGitHubConnectorReadPort:
    def __init__(self) -> None:
        self.arguments: dict[str, Any] | None = None
        self.call_count = 0

    def execute_read(self, binding: Any, tool_arguments: dict[str, Any]) -> ConnectorReadResultV1:
        self.call_count += 1
        assert binding.tool_id == "github_list_issues"
        self.arguments = dict(tool_arguments)
        return ConnectorReadResultV1(
            schema_version=1,
            tool_id=binding.tool_id,
            request_id="component-github-read-1",
            output={
                "items": [
                    {
                        "resource_type": "github_issue",
                        "resource_id": "acme/repo#7",
                        "parent_id": "acme/repo",
                        "version": "2026-09-01T00:00:00Z",
                        "related_resource_ids": ["acme/repo"],
                        "payload": {
                            "repository": "acme/repo",
                            "issue_number": 7,
                            "title": "Status issue seven",
                            "description": "First status update",
                            "state": "OPEN",
                        },
                    },
                    {
                        "resource_type": "github_issue",
                        "resource_id": "acme/repo#8",
                        "parent_id": "acme/repo",
                        "version": "2026-09-02T00:00:00Z",
                        "related_resource_ids": ["acme/repo"],
                        "payload": {
                            "repository": "acme/repo",
                            "issue_number": 8,
                            "title": "Status issue eight",
                            "description": "Second status update",
                            "state": "OPEN",
                        },
                    },
                ]
            },
            next_page_token=None,
            total_count=2,
        )


def _github_intent(*, explicit_repository: bool) -> dict[str, object]:
    intent = _intent()
    if explicit_repository:
        intent["constraints"] = [
            {
                "kind": "RESOURCE",
                "field": "repository",
                "value": "acme/repo",
                "provenance": {
                    "source": "USER_REQUEST",
                    "start_offset": 0,
                    "end_offset": 9,
                },
            }
        ]
    return intent


def _github_route_plan() -> dict[str, object]:
    plan = _answer_route_plan()
    input_plan = cast(dict[str, object], plan["input_plan"])
    input_plan["input_routes"] = [
        {
            "route_id": "route-1",
            "resource_type": "GITHUB_ISSUE",
            "connector_id": "github",
            "allowed_read_tool_ids": ["github_list_issues"],
            "required": True,
            "reason_codes": ["USER_REQUEST"],
        }
    ]
    return plan


@pytest.mark.parametrize("authority_source", ["explicit", "selected"])
def test_retrieval__github_repository_authority__reaches_connector_read(
    authority_source: str,
) -> None:
    selected_resources = (
        (
            SelectedResourceRef(
                resource_ref_id="github_issue:acme/repo#7",
                connector_id="github",
                resource_type="github_issue",
                resource_id="acme/repo#7",
                parent_resource_id="acme/repo",
            ),
        )
        if authority_source == "selected"
        else ()
    )
    state = _state(
        initial_target="context_retriever",
        selected_resources=selected_resources,
    )
    state["request_intent"] = cast(
        Any, _github_intent(explicit_repository=authority_source == "explicit")
    )
    state["tool_route_plan"] = cast(Any, _github_route_plan())
    connector = _ComponentGitHubConnectorReadPort()
    graph = RetrievalSubgraph(
        now_ms=lambda: 1_000,
        should_stop_for_cancel=lambda _run_id: False,
        timezone_provider=lambda: "Asia/Seoul",
        llm_runtime=_ComponentInferencePort(github_retrieval=True),
        prompt_manifest_path=None,
        prompt_execution_scope=DEVELOPMENT_SMOKE,
        id_factory=_IdFactory(),
        graph_profile=GraphProfile.SIX_ROLE_BASELINE,
        transition_run=lambda _run_id, _transition: None,
        merge_decision=cast(Any, _merge_decision),
        evidence_store=RunScopedEvidenceStore(),
        connector_reader=connector,
        tool_catalog=load_development_tool_registry(),
        read_result_cache=InMemoryRunRetrievalCache(),
        confirm_inline=cast(Any, _confirm_early),
    ).build()

    with provider_dispatch_execution_scope():
        result = graph.invoke(state)

    assert connector.arguments == {"repository": "acme/repo", "state": "ALL"}
    assert connector.call_count == 1
    assert result["retrieval_result"]["coverage"] == "SUFFICIENT"
    assert set(result["retrieval_result"]["source_resource_refs"]) == {
        "github_issue:acme/repo#7",
        "github_issue:acme/repo#8",
    }
    assert result["retrieval_result"]["source_statuses"] == [
        {
            "route_id": "route-1",
            "resource_type": "github_issue",
            "status": "COMPLETE",
            "evidence_refs": result["retrieval_result"]["evidence_refs"],
            "failure_kind": None,
        }
    ]


@pytest.mark.parametrize("authority_case", ["missing", "conflict", "unvalidated"])
def test_retrieval__invalid_repository_authority__stops_before_connector_read(
    authority_case: str,
) -> None:
    explicit_repository = authority_case != "missing"
    intent = _github_intent(explicit_repository=explicit_repository)
    selected_resources: tuple[SelectedResourceRef, ...] = ()
    if authority_case == "conflict":
        selected_resources = (
            SelectedResourceRef(
                resource_ref_id="github_issue:other/repo#7",
                connector_id="github",
                resource_type="github_issue",
                resource_id="other/repo#7",
                parent_resource_id="other/repo",
            ),
        )
    elif authority_case == "unvalidated":
        constraints = cast(list[dict[str, object]], intent["constraints"])
        constraints[0].pop("provenance")
    state = _state(
        initial_target="context_retriever",
        selected_resources=selected_resources,
    )
    state["request_intent"] = cast(Any, intent)
    state["tool_route_plan"] = cast(Any, _github_route_plan())
    connector = _StoppingGitHubReadPort()
    graph = RetrievalSubgraph(
        now_ms=lambda: 1_000,
        should_stop_for_cancel=lambda _run_id: False,
        timezone_provider=lambda: "Asia/Seoul",
        llm_runtime=_ComponentInferencePort(github_retrieval=True),
        prompt_manifest_path=None,
        prompt_execution_scope=DEVELOPMENT_SMOKE,
        id_factory=_IdFactory(),
        graph_profile=GraphProfile.SIX_ROLE_BASELINE,
        transition_run=lambda _run_id, _transition: None,
        merge_decision=cast(Any, _merge_decision),
        evidence_store=RunScopedEvidenceStore(),
        connector_reader=connector,
        tool_catalog=load_development_tool_registry(),
        read_result_cache=InMemoryRunRetrievalCache(),
        confirm_inline=cast(Any, _confirm_early),
    ).build()

    with provider_dispatch_execution_scope(), pytest.raises(ValueError):
        graph.invoke(state)

    assert connector.call_count == 0
