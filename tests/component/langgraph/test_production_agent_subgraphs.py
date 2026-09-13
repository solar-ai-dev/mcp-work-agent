from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
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
from google_work_agent.application.agents.tool_routing.bind_registry_candidates import (
    bind_registry_candidates,
)
from google_work_agent.application.agents.tool_routing.contracts.semantic_route_candidate import (
    SemanticRouteCandidate,
)
from google_work_agent.application.agents.tool_routing.finalize_route import finalize_route
from google_work_agent.application.prompt_runtime.prompt_registry import DEVELOPMENT_SMOKE
from google_work_agent.application.tool_registry.load_signed_tool_registry import (
    load_development_tool_registry,
)
from google_work_agent.application.use_cases.run.account_provider_dispatch import (
    provider_dispatch_execution_scope,
)
from google_work_agent.application.use_cases.run.guard_run_budget import (
    build_default_run_budget,
    validate_run_budget_v2,
)
from google_work_agent.ports.connector.connector_read_port import ConnectorReadResultV1, JsonValue
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
        request_reconsideration: bool = False,
        duplicate_found: bool = False,
        searchable_target: bool = False,
        unresolved_calendar_identity: bool = False,
        cross_source_draft: bool = False,
        container_retrieval: bool = False,
        calendar_event_query: bool = False,
    ) -> None:
        self.request_confirmation = request_confirmation
        self.github_retrieval = github_retrieval
        self.work_fact_count = work_fact_count
        self.retrieval_needs_more = retrieval_needs_more
        self.retrieval_followup_changes_query = retrieval_followup_changes_query
        self.request_reconsideration = request_reconsideration
        self.duplicate_found = duplicate_found
        self.searchable_target = searchable_target
        self.unresolved_calendar_identity = unresolved_calendar_identity
        self.cross_source_draft = cross_source_draft
        self.container_retrieval = container_retrieval
        self.calendar_event_query = calendar_event_query
        self.calls: list[str] = []
        self.inputs: dict[str, list[dict[str, object]]] = {}

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
        self.inputs.setdefault(prompt_id, []).append(dict(projection))
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
            if self.cross_source_draft:
                return {
                    "goal": "prepare a draft from existing work facts",
                    "completion_conditions": ["prepare the draft", "do not send it"],
                    "constraints": {
                        "search_terms": ["Project Anchor"],
                        "business_concepts": [],
                        "person": [],
                        "sender": [],
                        "recipient": ["person@example.test"],
                        "subject": [],
                        "period": [],
                        "coverage_requirement": "NOT_COLLECTION",
                        "additional_constraints": [],
                    },
                    "analysis_requirement": "NONE",
                }
            if self.searchable_target:
                return {
                    "goal": "confirm shipment criteria and owner from related mail",
                    "completion_conditions": ["return an evidence-backed answer"],
                    "constraints": {
                        "search_terms": ["Project Anchor"],
                        "business_concepts": ["shipment"],
                        "person": [],
                        "sender": [],
                        "recipient": [],
                        "subject": [],
                        "period": [],
                        "coverage_requirement": "NOT_COLLECTION",
                        "additional_constraints": [],
                    },
                    "analysis_requirement": "NONE",
                }
            if self.unresolved_calendar_identity:
                return {
                    "goal": "confirm the target event time",
                    "completion_conditions": ["return the selected event time"],
                    "constraints": {
                        "search_terms": [],
                        "business_concepts": ["event time"],
                        "person": [],
                        "sender": [],
                        "recipient": [],
                        "subject": [],
                        "period": [],
                        "coverage_requirement": "NOT_COLLECTION",
                        "additional_constraints": [],
                    },
                    "analysis_requirement": "NONE",
                }
            needs_action = self.request_confirmation or has_confirmation
            return {
                "goal": "schedule team sync" if needs_action else "summarize status",
                "completion_conditions": ["return a result"],
                "constraints": {
                    "search_terms": [],
                    "business_concepts": [],
                    "person": [],
                    "sender": [],
                    "recipient": [],
                    "subject": [],
                    "period": [],
                    "coverage_requirement": "NOT_COLLECTION",
                    "additional_constraints": [],
                },
                "analysis_requirement": "NONE",
            }
        if prompt_id == "request_understanding.identify_effect_prohibitions":
            return {
                "effect_prohibitions": [
                    {
                        "effect": candidate["effect"],
                        "prohibition": (
                            "FORBIDDEN"
                            if self.cross_source_draft and candidate["effect"] == "SEND"
                            else "NOT_FORBIDDEN"
                        ),
                    }
                    for candidate in cast(
                        Sequence[Mapping[str, object]], projection["effect_candidates"]
                    )
                ]
            }
        if prompt_id == "request_understanding.identify_source_dependencies":
            if self.cross_source_draft:
                return _source_dependency_decisions(
                    projection,
                    source_types={
                        "TASK": ["work status"],
                        "CALENDAR_EVENT": ["schedule"],
                    },
                )
            if self.searchable_target:
                return _source_dependency_decisions(
                    projection,
                    source_types={"GMAIL_THREAD": ["shipment criteria", "owner"]},
                )
            if self.unresolved_calendar_identity:
                return _source_dependency_decisions(
                    projection,
                    source_types={"CALENDAR_EVENT": ["event_identity", "start"]},
                )
            needs_action = self.request_confirmation or has_confirmation
            return (
                _source_dependency_decisions(projection)
                if needs_action
                else _source_dependency_decisions(
                    projection,
                    source_types={"GITHUB_ISSUE": []} if self.github_retrieval else {},
                )
            )
        if prompt_id == "request_understanding.identify_output_responsibilities":
            needs_action = self.request_confirmation or has_confirmation
            return _output_responsibility_decisions(
                projection,
                output_types=(
                    {"GMAIL_DRAFT": "CREATE"}
                    if self.cross_source_draft
                    else ({"CALENDAR_EVENT": "CREATE"} if needs_action else {})
                ),
            )
        if prompt_id == "request_understanding.identify_source_status":
            return {"statuses": []}
        if prompt_id == "request_understanding.detect_ambiguity":
            if self.unresolved_calendar_identity:
                return {
                    "missing_information_owner": "USER",
                    "missing_fields": ["event_identity"],
                }
            if self.searchable_target:
                first_attempt = self.calls.count(prompt_id) == 1
                return {
                    "missing_information_owner": "USER" if first_attempt else "CONNECTOR",
                    "missing_fields": (
                        ["target_resource"] if first_attempt else ["shipment criteria and owner"]
                    ),
                }
            needs_confirmation = self.request_confirmation and not has_confirmation
            return {
                "missing_information_owner": "USER" if needs_confirmation else "NONE",
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
        if prompt_id == "tool_routing.select_tool_if_needed":
            route = cast(Mapping[str, object], projection["route_candidate"])
            candidates = cast(list[Mapping[str, str]], projection["registered_candidates"])
            selected = next(
                item["tool_id"] for item in candidates if item["tool_id"] == "github_close_issue"
            )
            return {
                "schema_version": 1,
                "route_id": route["route_id"],
                "selected_tool_id": selected,
            }
        if prompt_id == "retrieval.plan_query":
            if self.calendar_event_query:
                route = cast(list[Mapping[str, object]], projection["input_routes"])[0]
                return {
                    "schema_version": 3,
                    "route_queries": [
                        {
                            "route_id": route["route_id"],
                            "operation": "SEARCH",
                            "reason_codes": ["USER_REQUEST"],
                            "search_spec": {
                                "mode": "INITIAL",
                                "constraints": {
                                    "keyword": {
                                        "kind": "KEYWORD",
                                        "terms": ["Atlas"],
                                        "match_mode": "ALL",
                                    },
                                    "concept": {
                                        "kind": "CONCEPT",
                                        "concept": "schedule",
                                        "manifestations": ["인쇄소", "납기"],
                                    },
                                },
                            },
                            "detail_candidate_ref": None,
                        }
                    ],
                }
            if self.container_retrieval:
                routes = cast(list[Mapping[str, object]], projection["input_routes"])
                return {
                    "schema_version": 3,
                    "route_queries": [
                        {
                            "route_id": route["route_id"],
                            "operation": "SEARCH",
                            "reason_codes": ["USER_REQUEST"],
                            "search_spec": {
                                "mode": "INITIAL",
                                "constraints": {
                                    "container_ref": {
                                        "kind": "CONTAINER_REF",
                                        "container_refs": [
                                            cast(list[str], route["container_refs"])[0]
                                        ],
                                    }
                                },
                            },
                            "detail_candidate_ref": None,
                        }
                        for route in routes
                    ],
                }
            current_round_no = projection.get("current_round_no")
            search_spec: dict[str, object] = (
                {
                    "mode": "CHANGED",
                    "constraint_delta": {
                        "upsert_constraints": {
                            ("concept" if self.retrieval_followup_changes_query else "keyword"): (
                                {
                                    "kind": "CONCEPT",
                                    "concept": "new status evidence",
                                    "manifestations": [f"status-{current_round_no}"],
                                }
                                if self.retrieval_followup_changes_query
                                else {
                                    "kind": "KEYWORD",
                                    "terms": ["status"],
                                    "match_mode": "ANY",
                                }
                            ),
                        },
                        "remove_constraint_kinds": [],
                    },
                }
                if current_round_no is not None
                else {
                    "mode": "INITIAL",
                    "constraints": {
                        "keyword": {
                            "kind": "KEYWORD",
                            "terms": ["status"],
                            "match_mode": "ANY",
                        }
                    },
                }
            )
            if self.github_retrieval:
                input_routes = cast(list[Mapping[str, object]], projection["input_routes"])
                assert input_routes[0].get("container_refs") == ["acme/repo"]
                search_spec = {
                    "mode": "INITIAL",
                    "constraints": {
                        "container_ref": {
                            "kind": "CONTAINER_REF",
                            "container_refs": ["acme/repo"],
                        }
                    },
                }
            return {
                "schema_version": 3,
                "route_queries": [
                    {
                        "route_id": "route-1",
                        "operation": "SEARCH",
                        "reason_codes": ["USER_REQUEST"],
                        "search_spec": search_spec,
                        "detail_candidate_ref": None,
                    }
                ],
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
        }:
            return {"relation_candidates": []}
        if prompt_id == "work_analysis.detect_duplicate_conflict_candidates":
            return {"relation_candidates": []}
        if prompt_id == "work_analysis.assess_requested_task_satisfaction":
            if self.duplicate_found:
                facts = cast(list[Mapping[str, object]], projection.get("work_facts", []))
                source_state = cast(Mapping[str, object], projection.get("source_state", {}))
                task_candidates = cast(
                    list[Mapping[str, object]], source_state.get("task_review_candidates", [])
                )
                return {
                    "requested_work_status": "SATISFIED",
                    "requested_work_reason": "The observed Task already satisfies the request",
                    "matched_fact_ids": [str(facts[0]["fact_id"])],
                    "matched_candidate_refs": [str(task_candidates[0]["candidate_ref"])],
                    "evidence_refs": list(cast(list[str], facts[0]["evidence_refs"])),
                }
            return {
                "requested_work_status": "NOT_SATISFIED",
                "requested_work_reason": "Observed tasks do not satisfy the request",
                "matched_fact_ids": [],
                "matched_candidate_refs": [],
                "evidence_refs": [],
            }
        if prompt_id == "work_analysis.assess_action_necessity":
            routes = cast(list[Mapping[str, object]], projection["output_routes"])
            duplicate = cast(
                Mapping[str, object], projection.get("duplicate_conflict_assessment", {})
            )
            return {
                "route_assessments": [
                    {
                        "route_id": str(route["route_id"]),
                        "status": "REQUIRED",
                        "reason": "THE_REQUESTED_EXTERNAL_EFFECT_IS_NOT_YET_SATISFIED",
                        "evidence_refs": list(cast(list[str], duplicate.get("evidence_refs", []))),
                        "candidate_refs": list(
                            cast(list[str], duplicate.get("matched_candidate_refs", []))
                        ),
                    }
                    for route in routes
                ]
            }
        if prompt_id == "work_analysis.assess_information_gaps":
            if self.request_reconsideration:
                return {
                    "disposition": "REQUEST_RECONSIDERATION_REQUIRED",
                    "ambiguities": [],
                    "retrieval_needs": [],
                    "evidence_refs": ["current-evidence"],
                    "reason_codes": ["CURRENT_EVIDENCE_CHANGES_REQUEST_MEANING"],
                }
            return {
                "disposition": "COMPLETE",
                "ambiguities": [],
                "retrieval_needs": [],
                "evidence_refs": [],
            }
        if prompt_id == "work_analysis.assess_operational_risks":
            return {
                "risks": [],
                "evidence_refs": [],
            }
        raise AssertionError(f"unexpected component Prompt: {prompt_id}")


class _ComponentConnectorReadPort:
    def __init__(self, *, include_body: bool = False) -> None:
        self.call_count = 0
        self.include_body = include_body

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
                        "payload": {
                            "subject": "Weekly status",
                            **(
                                {"body": "The current weekly status is ready."}
                                if self.include_body
                                else {}
                            ),
                        },
                    }
                ]
            },
            next_page_token=None,
            total_count=1,
        )


class _CollectionConnectorReadPort:
    def __init__(self, *, item_count: int, has_next_page: bool) -> None:
        self.item_count = item_count
        self.has_next_page = has_next_page
        self.call_count = 0

    def execute_read(self, binding: Any, tool_arguments: dict[str, Any]) -> ConnectorReadResultV1:
        del tool_arguments
        self.call_count += 1
        return ConnectorReadResultV1(
            schema_version=1,
            tool_id=binding.tool_id,
            request_id="component-collection-read-1",
            output={
                "items": [
                    {
                        "resource_type": "gmail_thread",
                        "resource_id": f"thread-{index}",
                        "parent_id": None,
                        "version": "v1",
                        "related_resource_ids": [],
                        "payload": {
                            "subject": "Same title" if index < 2 else f"Status title {index}",
                            "body": "The current status is ready.",
                        },
                    }
                    for index in range(self.item_count)
                ]
            },
            next_page_token="next-page" if self.has_next_page else None,
            total_count=self.item_count + (1 if self.has_next_page else 0),
        )


class _PagedCollectionConnectorReadPort:
    def __init__(self) -> None:
        self.call_count = 0

    def execute_read(self, binding: Any, tool_arguments: dict[str, Any]) -> ConnectorReadResultV1:
        del tool_arguments
        page = self.call_count
        self.call_count += 1
        return ConnectorReadResultV1(
            schema_version=1,
            tool_id=binding.tool_id,
            request_id=f"component-paged-read-{page}",
            output={
                "items": [
                    {
                        "resource_type": "gmail_thread",
                        "resource_id": f"thread-{page}",
                        "parent_id": None,
                        "version": "v1",
                        "related_resource_ids": [],
                        "payload": {
                            "subject": f"Status title {page}",
                            "body": "The current status is ready.",
                        },
                    }
                ]
            },
            next_page_token="next-page" if page == 0 else None,
            total_count=2,
        )


class _ContainerConnectorReadPort:
    def __init__(self, resource_type: str) -> None:
        self.resource_type = resource_type
        self.arguments: list[dict[str, Any]] = []

    def execute_read(self, binding: Any, tool_arguments: dict[str, Any]) -> ConnectorReadResultV1:
        self.arguments.append(dict(tool_arguments))
        resource_type = (
            "task"
            if "task_list_id" in tool_arguments
            else "calendar_event"
            if "calendar_id" in tool_arguments
            else self.resource_type
        )
        container_id = cast(
            str,
            tool_arguments.get("task_list_id") or tool_arguments.get("calendar_id"),
        )
        payload: dict[str, JsonValue] = (
            {"title": f"Task from {container_id}", "status": "needsAction", "due": None}
            if resource_type == "task"
            else {
                "title": f"Event from {container_id}",
                "start": "2026-09-12T09:00:00+09:00",
                "end": "2026-09-12T10:00:00+09:00",
            }
        )
        return ConnectorReadResultV1(
            1,
            binding.tool_id,
            f"container-read-{len(self.arguments)}",
            {
                "items": [
                    {
                        "resource_type": resource_type,
                        "resource_id": f"item-{len(self.arguments)}",
                        "parent_id": container_id,
                        "version": "v1",
                        "related_resource_ids": [],
                        "payload": payload,
                    }
                ]
            },
            None,
            1,
        )


@pytest.mark.parametrize("multiple", [False, True])
def test_retrieval_person__compiled_identity_search__preserves_same_run(multiple: bool) -> None:
    class Reader:
        def __init__(self) -> None:
            self.queries: list[str] = []

        def execute_read(self, binding: Any, arguments: dict[str, Any]) -> ConnectorReadResultV1:
            query = arguments["query"]
            self.queries.append(query)
            identities = [("김하늘 대리", "first@example.test")]
            if multiple:
                identities.append(("김바다 대리", "second@example.test"))
            if "@" in query:
                identities = [item for item in identities if item[1] in query]
            return ConnectorReadResultV1(
                1,
                binding.tool_id,
                "person-fixture",
                {
                    "items": [
                        {
                            "resource_type": "gmail_thread",
                            "resource_id": email,
                            "parent_id": None,
                            "version": "v1",
                            "related_resource_ids": [],
                            "payload": {
                                "subject": "status",
                                "body": "status reviewed",
                                "sender_name": name,
                                "sender_email": email,
                            },
                        }
                        for name, email in identities
                    ],
                },
                None,
                len(identities),
            )

    def confirm(state: Any) -> Any:
        return interrupt(state["user_interrupt"]), None

    reader = Reader()
    state = _state(initial_target="context_retriever")
    state["request_intent"] = cast(
        Any,
        {
            **_intent(),
            "constraints": [{"kind": "PERSON", "field": "person", "value": "김대리"}],
        },
    )
    state["tool_route_plan"] = cast(Any, _answer_route_plan(with_input_route=True))
    retrieval = RetrievalSubgraph(
        now_ms=lambda: 1_000,
        should_stop_for_cancel=lambda _: False,
        timezone_provider=lambda: "Asia/Seoul",
        llm_runtime=_ComponentInferencePort(),
        prompt_manifest_path=None,
        prompt_execution_scope=DEVELOPMENT_SMOKE,
        id_factory=_IdFactory(),
        graph_profile=GraphProfile.SIX_ROLE_BASELINE,
        transition_run=lambda *_: None,
        merge_decision=cast(Any, _merge_decision),
        evidence_store=RunScopedEvidenceStore(),
        connector_reader=reader,
        tool_catalog=load_development_tool_registry(),
        read_result_cache=InMemoryRunRetrievalCache(),
        confirm_inline=confirm,
    ).build()
    wrapper = StateGraph(GraphState)
    wrapper.add_node("retrieval", retrieval)
    wrapper.add_edge(START, "retrieval")
    wrapper.add_edge("retrieval", END)
    graph = wrapper.compile(checkpointer=InMemorySaver())
    config: RunnableConfig = {"configurable": {"thread_id": "person-measurement"}}
    with provider_dispatch_execution_scope():
        result = graph.invoke(state, config)
    chosen = "second@example.test" if multiple else "first@example.test"
    if multiple:
        payload = result["__interrupt__"][0].value
        assert {item["option_id"] for item in payload["options"]} == {
            "first@example.test",
            "second@example.test",
        }
        assert len(reader.queries) == 1
        with provider_dispatch_execution_scope():
            result = graph.invoke(
                Command(
                    resume={
                        "schema_version": 1,
                        "response_kind": "OPTION",
                        "selected_option": chosen,
                        "free_text": None,
                    }
                ),
                config,
            )
    assert graph.get_state(config).next == ()
    assert len(reader.queries) == 2
    assert chosen in reader.queries[1]
    artifact = result["retrieval_result"]
    assert len(artifact["person_candidates"]) == (2 if multiple else 1)
    if multiple:
        assert artifact["selected_person_identities"] == {"김대리": chosen}
    assert all(item["source_segment_ids"] for item in artifact["person_candidates"])


def _state(
    *,
    initial_target: str = "request_understanding",
    selected_resources: tuple[SelectedResourceRef, ...] = (),
    request_text: str = "summarize status",
) -> GraphState:
    request = WorkflowStartRequest(
        run_id="component-run-1",
        conversation_id="component-conversation-1",
        workflow_key="component-thread-1",
        entry_mode="AGENT_SEARCH",
        requested_mode="AUTO",
        request_text=request_text,
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


def _container_read_route_plan(resource_type: str) -> dict[str, object]:
    result = _answer_route_plan()
    result["input_plan"] = {
        "schema_version": 1,
        "meta": {
            "artifact_id": "input-container-1",
            "revision": 1,
            "based_on": [{"artifact_id": "intent-1", "revision": 1}],
        },
        "input_routes": [
            {
                "route_id": "route-1",
                "resource_type": resource_type,
                "connector_id": "google_workspace",
                "allowed_read_tool_ids": [
                    "tasks_list_tasks" if resource_type == "TASK" else "calendar_list_events"
                ],
                "required": True,
                "reason_codes": ["USER_REQUEST"],
            }
        ],
    }
    return result


def _task_and_calendar_read_route_plan() -> dict[str, object]:
    result = _answer_route_plan()
    result["input_plan"] = {
        "schema_version": 1,
        "meta": {
            "artifact_id": "input-container-1",
            "revision": 1,
            "based_on": [{"artifact_id": "intent-1", "revision": 1}],
        },
        "input_routes": [
            {
                "route_id": "task-route",
                "resource_type": "TASK",
                "connector_id": "google_workspace",
                "allowed_read_tool_ids": ["tasks_list_tasks"],
                "required": True,
                "reason_codes": ["USER_REQUEST"],
            },
            {
                "route_id": "calendar-route",
                "resource_type": "CALENDAR_EVENT",
                "connector_id": "google_workspace",
                "allowed_read_tool_ids": ["calendar_list_events"],
                "required": True,
                "reason_codes": ["USER_REQUEST"],
            },
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


def _source_dependency_decisions(
    projection: Mapping[str, object],
    *,
    source_types: Mapping[str, list[str]] | None = None,
) -> dict[str, object]:
    sources = source_types or {}
    decisions: list[dict[str, object]] = []
    candidates = cast(list[Mapping[str, object]], projection["source_candidates"])
    for candidate in candidates:
        resource_type = cast(str, candidate["resource_type"])
        information = sources.get(resource_type)
        if information is not None:
            decisions.append(
                {
                    "resource_type": resource_type,
                    "dependency": "SOURCE_REQUIRED",
                    "required_information": information,
                }
            )
        else:
            decisions.append({"resource_type": resource_type, "dependency": "SOURCE_NOT_REQUIRED"})
    return {"source_dependencies": decisions}


def _output_responsibility_decisions(
    projection: Mapping[str, object],
    *,
    output_types: Mapping[str, str] | None = None,
) -> dict[str, object]:
    outputs = output_types or {}
    candidates = cast(list[Mapping[str, object]], projection["output_candidates"])
    return {
        "output_responsibilities": [
            {
                "resource_type": candidate["resource_type"],
                "effect": outputs[cast(str, candidate["resource_type"])],
            }
            for candidate in candidates
            if candidate["resource_type"] in outputs
        ]
    }


def _confirm_early(_state: object) -> tuple[None, dict[str, object]]:
    return None, {"__target__": "end", "__workflow_control__": {"stage": "PAUSED"}}


def _edge_set(graph: Any) -> set[tuple[str, str]]:
    return {(edge.source, edge.target) for edge in graph.get_graph().edges}


def test_request_understanding__compiled_normal_path__produces_intent() -> None:
    llm = _ComponentInferencePort()
    graph = RequestUnderstandingSubgraph(
        llm_runtime=llm,
        tool_catalog=load_development_tool_registry(),
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
        "request_understanding.identify_effect_prohibitions",
        "request_understanding.identify_source_dependencies",
        "request_understanding.identify_output_responsibilities",
        "request_understanding.identify_source_status",
    ]
    assert ("finalize_intent", "identify_goal") in _edge_set(graph)


def test_request_understanding__compiled_searchable_target__normalizes_false_confirmation() -> None:
    llm = _ComponentInferencePort(searchable_target=True)
    graph = RequestUnderstandingSubgraph(
        llm_runtime=llm,
        tool_catalog=load_development_tool_registry(),
        prompt_manifest_path=None,
        prompt_execution_scope=DEVELOPMENT_SMOKE,
        id_factory=_IdFactory(),
        graph_profile=GraphProfile.SIX_ROLE_BASELINE,
        transition_run=lambda _run_id, _transition: None,
        merge_decision=cast(Any, _merge_decision),
        confirm_inline=_confirm_early,
    ).build()

    with provider_dispatch_execution_scope():
        result = graph.invoke(_state(request_text="Project Anchor shipment status"))

    assert result["request_intent"]["ambiguity"] == {
        "requires_confirmation": False,
        "reason_codes": [],
        "missing_fields": [],
    }
    assert llm.calls.count("request_understanding.detect_ambiguity") == 1
    resolution = cast(
        Mapping[str, object],
        llm.inputs["request_understanding.detect_ambiguity"][0]["resolution_responsibilities"],
    )
    assert resolution["searchable_target_anchor_count"] == 1
    assert resolution["connector_owned_source_count"] == 1


def test_request_understanding__compiled_resource_identity__requests_confirmation() -> None:
    llm = _ComponentInferencePort(unresolved_calendar_identity=True)
    captured_ambiguity: dict[str, object] = {}

    def confirm_inline(
        state: Mapping[str, object],
    ) -> tuple[None, dict[str, object]]:
        captured_ambiguity.update(cast(Mapping[str, object], state["ambiguity_candidate"]))
        return _confirm_early(state)

    graph = RequestUnderstandingSubgraph(
        llm_runtime=llm,
        tool_catalog=load_development_tool_registry(),
        prompt_manifest_path=None,
        prompt_execution_scope=DEVELOPMENT_SMOKE,
        id_factory=_IdFactory(),
        graph_profile=GraphProfile.SIX_ROLE_BASELINE,
        transition_run=lambda _run_id, _transition: None,
        merge_decision=cast(Any, _merge_decision),
        confirm_inline=confirm_inline,
    ).build()

    with provider_dispatch_execution_scope():
        result = graph.invoke(_state(request_text="그 일정 언제야?"))

    assert result["__workflow_control__"] == {"stage": "PAUSED"}
    assert captured_ambiguity == {
        "requires_confirmation": True,
        "reason_codes": ["REQUEST_UNDERSTANDING_NEEDS_CONFIRMATION"],
        "missing_fields": ["event_identity"],
    }
    assert llm.calls.count("request_understanding.detect_ambiguity") == 1


def test_request_understanding__compiled_cross_source_draft__keeps_sources_and_send_ban() -> None:
    llm = _ComponentInferencePort(cross_source_draft=True)
    graph = RequestUnderstandingSubgraph(
        llm_runtime=llm,
        tool_catalog=load_development_tool_registry(),
        prompt_manifest_path=None,
        prompt_execution_scope=DEVELOPMENT_SMOKE,
        id_factory=_IdFactory(),
        graph_profile=GraphProfile.SIX_ROLE_BASELINE,
        transition_run=lambda _run_id, _transition: None,
        merge_decision=cast(Any, _merge_decision),
        confirm_inline=_confirm_early,
    ).build()

    with provider_dispatch_execution_scope():
        result = graph.invoke(_state(request_text="prepare a draft from work and schedule"))

    assert result["request_intent"]["resource_responsibilities"] == {
        "source_reads": [
            {"resource_type": "TASK", "required_information": ["work status"]},
            {
                "resource_type": "CALENDAR_EVENT",
                "required_information": ["schedule"],
            },
        ],
        "outputs": [{"resource_type": "GMAIL_DRAFT", "effect": "CREATE"}],
    }
    source_input = llm.inputs["request_understanding.identify_source_dependencies"][0]
    source_candidates_input = cast(
        list[dict[str, Any]], source_input["source_candidates"]
    )
    source_candidates = {item["resource_type"]: item for item in source_candidates_input}
    assert source_candidates["TASK_LIST"]["owned_fact_kinds"] == [
        "task_list_identity",
        "task_list_title",
    ]
    assert "completion_status" in source_candidates["TASK"]["owned_fact_kinds"]
    assert "start" in source_candidates["CALENDAR_EVENT"]["owned_fact_kinds"]
    assert "start" not in source_candidates["CALENDAR"]["owned_fact_kinds"]
    output_input = llm.inputs["request_understanding.identify_output_responsibilities"][0]
    effect_prohibitions = cast(list[dict[str, Any]], output_input["effect_prohibitions"])
    assert {item["effect"]: item["prohibition"] for item in effect_prohibitions}["SEND"] == (
        "FORBIDDEN"
    )
    source_status_input = llm.inputs["request_understanding.identify_source_status"][0]
    source_reads = cast(list[dict[str, Any]], source_status_input["source_reads"])
    assert [item["resource_type"] for item in source_reads] == [
        "TASK",
        "CALENDAR_EVENT",
    ]
    assert source_status_input["outputs"] == [{"resource_type": "GMAIL_DRAFT", "effect": "CREATE"}]


def test_tool_routing__compiled_normal_path__produces_answer_route() -> None:
    state = _state(initial_target="tool_route")
    intent = _intent()
    intent["requested_effect_hints"] = []
    state["request_intent"] = cast(Any, intent)
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
    assert llm.calls == []
    assert ("finalize_route", "determine_io_resources") in _edge_set(graph)


def test_tool_routing__compiled_cross_source_draft__does_not_add_freebusy() -> None:
    state = _state(
        initial_target="tool_route",
        request_text="Create a draft from existing work and schedule facts",
    )
    state["request_intent"] = cast(
        Any,
        {
            **_intent(),
            "requested_effect_hints": ["CREATE"],
            "requested_resource_hints": ["TASK", "CALENDAR_EVENT", "GMAIL_DRAFT"],
            "resource_responsibilities": {
                "source_reads": [
                    {"resource_type": "TASK", "required_information": ["work status"]},
                    {
                        "resource_type": "CALENDAR_EVENT",
                        "required_information": ["schedule"],
                    },
                ],
                "outputs": [{"resource_type": "GMAIL_DRAFT", "effect": "CREATE"}],
            },
        },
    )
    graph = ToolRoutingSubgraph(
        llm_runtime=_ComponentInferencePort(),
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

    input_resource_types = {
        route["resource_type"] for route in result["tool_route_plan"]["input_plan"]["input_routes"]
    }
    assert input_resource_types == {"TASK", "TASK_LIST", "CALENDAR", "CALENDAR_EVENT"}
    assert (
        result["tool_route_plan"]["output_plan"]["output_routes"][0]["selected_tool_id"]
        == "gmail_create_draft"
    )


def test_tool_routing__compiled_multiple_registry_candidates__preserves_bound_route() -> None:
    state = _state(
        initial_target="tool_route",
        request_text="Close the selected GitHub issue",
    )
    state["request_intent"] = cast(
        Any,
        {
            **_intent(),
            "goal": "close the selected GitHub issue",
            "requested_effect_hints": ["UPDATE"],
            "requested_resource_hints": ["GITHUB_ISSUE"],
            "resource_responsibilities": {
                "source_reads": [],
                "outputs": [{"resource_type": "GITHUB_ISSUE", "effect": "UPDATE"}],
            },
        },
    )
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

    output_route = result["tool_route_plan"]["output_plan"]["output_routes"][0]
    assert output_route["selected_tool_id"] == "github_close_issue"
    assert llm.calls == ["tool_routing.select_tool_if_needed"]
    prompt_input = llm.inputs["tool_routing.select_tool_if_needed"][0]
    route_candidate = cast(Mapping[str, object], prompt_input["route_candidate"])
    assert output_route["route_id"] == route_candidate["route_id"]
    assert prompt_input["registered_candidates"] == [
        {"tool_id": "github_close_issue"},
        {"tool_id": "github_reopen_issue"},
        {"tool_id": "github_update_issue"},
    ]


def test_retrieval__compiled_normal_path__materializes_evidence() -> None:
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
        result = graph.invoke(state)

    assert result["retrieval_result"]["coverage"] == "PARTIAL"
    assert result["retrieval_result"]["missing_information"][0]["reason_codes"] == [
        "NO_SELECTED_EVIDENCE_SUPPORTS_REQUESTED_FACT"
    ]
    assert result["retrieval_result"]["evidence_refs"]

    assert connector.call_count == 1
    binding = next(iter(result["__context_read_bindings__"].values()))
    assert binding["source_fetch_plan"]["query_identity_hash"] == binding["query_identity_hash"]
    sufficiency_input = llm.inputs["retrieval.assess_sufficiency"][0]
    assert sufficiency_input["read_result_summaries"] == [
        {
            "read_result_handle": next(iter(result["__context_read_bindings__"])),
            "route_id": "route-1",
            "query_identity_hash": binding["query_identity_hash"],
            "has_next_page": False,
            "exhausted": True,
            "result_count": 1,
            "page_state_hash": None,
        }
    ]
    assert set(graph.get_graph().nodes) == {
        "__start__",
        "__end__",
        "plan_query",
        "build_query",
        "execute_read",
        "normalize_segments",
        "rag_retrieve",
        "select_evidence",
        "assess_sufficiency",
        "finalize",
    }
    assert all(
        (node, "__end__") in _edge_set(graph)
        for node in (
            "plan_query",
            "build_query",
            "execute_read",
            "normalize_segments",
            "rag_retrieve",
            "select_evidence",
            "assess_sufficiency",
            "finalize",
        )
    )
    assert ("assess_sufficiency", "plan_query") in _edge_set(graph)
    assert ("finalize", "finalize") in _edge_set(graph)


@pytest.mark.parametrize(
    ("resource_type", "container_type", "parent_key", "resource_value"),
    [
        ("TASK", "TASK_LIST", "task_list_id", "task"),
        ("CALENDAR_EVENT", "CALENDAR", "calendar_id", "calendar_event"),
    ],
)
@pytest.mark.parametrize("explicit", [False, True])
def test_retrieval__compiled_container_scope__fans_out_or_honors_explicit_selection(
    resource_type: str,
    container_type: str,
    parent_key: str,
    resource_value: str,
    explicit: bool,
) -> None:
    selected = (
        (
            SelectedResourceRef(
                "selected-container",
                "google_workspace",
                container_type,
                "container-b",
            ),
        )
        if explicit
        else ()
    )
    state = _state(initial_target="context_retriever", selected_resources=selected)
    state["request_intent"] = cast(Any, _intent())
    state["tool_route_plan"] = cast(Any, _container_read_route_plan(resource_type))
    connector = _ContainerConnectorReadPort(resource_value)
    graph = RetrievalSubgraph(
        now_ms=lambda: 1_000,
        should_stop_for_cancel=lambda _run_id: False,
        timezone_provider=lambda: "Asia/Seoul",
        llm_runtime=_ComponentInferencePort(container_retrieval=True),
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
        authorized_tasklist_ids_provider=(
            (lambda: ("container-a", "container-b")) if resource_type == "TASK" else None
        ),
        authorized_calendar_ids_provider=(
            (lambda: ("container-a", "container-b")) if resource_type == "CALENDAR_EVENT" else None
        ),
    ).build()

    with provider_dispatch_execution_scope():
        result = graph.invoke(state)

    assert [arguments[parent_key] for arguments in connector.arguments] == (
        ["container-b"] if explicit else ["container-a", "container-b"]
    )
    assert all(isinstance(arguments[parent_key], str) for arguments in connector.arguments)
    assert result["retrieval_result"]["source_statuses"][0]["status"] == "COMPLETE"


def test_retrieval__compiled_container_scope__allows_current_authorized_45_reads() -> None:
    task_lists = tuple(f"task-list-{index}" for index in range(22))
    calendars = tuple(f"calendar-{index}" for index in range(23))
    state = _state(initial_target="context_retriever")
    state["request_intent"] = cast(Any, _intent())
    state["tool_route_plan"] = cast(Any, _task_and_calendar_read_route_plan())
    connector = _ContainerConnectorReadPort("mixed")
    graph = RetrievalSubgraph(
        now_ms=lambda: 1_000,
        should_stop_for_cancel=lambda _run_id: False,
        timezone_provider=lambda: "Asia/Seoul",
        llm_runtime=_ComponentInferencePort(container_retrieval=True),
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
        authorized_tasklist_ids_provider=lambda: task_lists,
        authorized_calendar_ids_provider=lambda: calendars,
    ).build()

    with provider_dispatch_execution_scope():
        result = graph.invoke(state)

    assert len(connector.arguments) == 45
    assert all("task_list_id" in arguments for arguments in connector.arguments[:22])
    assert {arguments["task_list_id"] for arguments in connector.arguments[:22]} == set(task_lists)
    assert all("calendar_id" in arguments for arguments in connector.arguments[22:])
    assert {arguments["calendar_id"] for arguments in connector.arguments[22:]} == set(calendars)
    assert result["retry_budget"]["source_page_calls_used"] == 45
    assert result["retry_budget"]["max_source_page_calls"] == 50


def test_retrieval__compiled_calendar_event_search__preserves_query_to_connector() -> None:
    state = _state(initial_target="context_retriever")
    state["request_intent"] = cast(Any, _intent())
    state["tool_route_plan"] = cast(Any, _container_read_route_plan("CALENDAR_EVENT"))
    connector = _ContainerConnectorReadPort("calendar_event")
    graph = RetrievalSubgraph(
        now_ms=lambda: 1_000,
        should_stop_for_cancel=lambda _run_id: False,
        timezone_provider=lambda: "Asia/Seoul",
        llm_runtime=_ComponentInferencePort(calendar_event_query=True),
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
        authorized_calendar_ids_provider=lambda: ("calendar-1",),
    ).build()

    with provider_dispatch_execution_scope():
        result = graph.invoke(state)

    assert connector.arguments == [
        {
            "calendar_id": "calendar-1",
            "page_size": 20,
            "single_events": True,
            "order_by": "startTime",
            "query": "납기 인쇄소 Atlas",
        }
    ]
    plan = result["__context_canonical_plans__"]["route-1"]
    assert [constraint["kind"] for constraint in plan["effective_constraints"]] == [
        "CONCEPT",
        "CONTAINER_REF",
        "KEYWORD",
    ]


def test_retrieval__compiled_budget_exhaustion__projects_terminal_partial() -> None:
    state = _state(initial_target="context_retriever")
    intent = _intent()
    intent["requested_resource_hints"] = ["GMAIL_THREAD"]
    state["request_intent"] = cast(Any, intent)
    state["tool_route_plan"] = cast(Any, _answer_route_plan(with_input_route=True))
    state["retry_budget"]["connector_calls_used"] = state["retry_budget"]["max_connector_calls"]
    state["retry_budget"]["source_page_calls_used"] = state["retry_budget"]["max_source_page_calls"]
    connector = _ComponentConnectorReadPort()
    graph = RetrievalSubgraph(
        now_ms=lambda: 1_000,
        should_stop_for_cancel=lambda _run_id: False,
        timezone_provider=lambda: "Asia/Seoul",
        llm_runtime=_ComponentInferencePort(),
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

    assert connector.call_count == 0
    assert result["retrieval_result"]["coverage"] == "PARTIAL"
    source_status = result["retrieval_result"]["source_statuses"][0]
    assert source_status["status"] == "PARTIAL"
    assert source_status["failure_kind"] is None
    assert source_status["checked_read_count"] == 0
    assert source_status["known_scope_count"] == 1
    assert source_status["scope_complete"] is False
    assert source_status["continuation_status"] == "UNKNOWN"
    assert any(
        "REQUIRED_SOURCE_PARTIAL" in item["reason_codes"]
        for item in result["retrieval_result"]["missing_information"]
    )
    assert result["__context_query_attempts__"] == []


def test_retrieval__compiled_budget_stop__halts_remaining_container_fanout() -> None:
    state = _state(initial_target="context_retriever")
    state["request_intent"] = cast(Any, _intent())
    state["tool_route_plan"] = cast(Any, _container_read_route_plan("TASK"))
    state["retry_budget"]["connector_calls_used"] = 49
    state["retry_budget"]["source_page_calls_used"] = 49
    connector = _ContainerConnectorReadPort("task")
    graph = RetrievalSubgraph(
        now_ms=lambda: 1_000,
        should_stop_for_cancel=lambda _run_id: False,
        timezone_provider=lambda: "Asia/Seoul",
        llm_runtime=_ComponentInferencePort(container_retrieval=True),
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
        authorized_tasklist_ids_provider=lambda: ("task-list-a", "task-list-b"),
    ).build()

    with provider_dispatch_execution_scope():
        result = graph.invoke(state)

    assert [item["task_list_id"] for item in connector.arguments] == ["task-list-a"]
    assert len(result["__context_query_attempts__"]) == 1
    source_status = result["retrieval_result"]["source_statuses"][0]
    assert source_status["checked_read_count"] == 1
    assert source_status["known_scope_count"] == 2
    assert source_status["scope_complete"] is False
    assert source_status["observed_resource_count"] == 1


def test_retrieval__compiled_cache_rehydrate__preserves_bounded_segment_selection() -> None:
    task_counts = (2, 2, 1, 0, 2, 0, 2, 0, 1, 1, 2, 1, 1, 1, 1, 1, 1, 1, 1, 0, 1, 3)

    class MultiSourceInference(_ComponentInferencePort):
        def __init__(self) -> None:
            super().__init__(retrieval_needs_more=True)

        def _response(self, prompt_id: str, projection: Mapping[str, object]) -> dict[str, object]:
            if prompt_id == "retrieval.plan_query":
                routes = cast(list[Mapping[str, object]], projection["input_routes"])
                return {
                    "schema_version": 2,
                    "route_queries": [
                        {
                            "route_id": route["route_id"],
                            "operation": "SEARCH",
                            "reason_codes": ["USER_REQUEST"],
                            "search_spec": {
                                "mode": "INITIAL",
                                "constraints": (
                                    [
                                        {
                                            "kind": "CONTAINER_REF",
                                            "container_refs": [
                                                cast(list[str], route["container_refs"])[0]
                                            ],
                                        }
                                    ]
                                    if route.get("container_refs")
                                    else []
                                ),
                            },
                            "detail_candidate_ref": None,
                        }
                        for route in routes
                    ],
                }
            return super()._response(prompt_id, projection)

    class MultiSourceConnector:
        def __init__(self) -> None:
            self.task_read_count = 0
            self.calls: list[str] = []

        def execute_read(
            self, binding: Any, tool_arguments: dict[str, Any]
        ) -> ConnectorReadResultV1:
            del tool_arguments
            self.calls.append(binding.tool_id)
            if binding.tool_id == "tasks_list_tasks":
                read_index = self.task_read_count
                self.task_read_count += 1
                items: list[JsonValue] = [
                    {
                        "resource_type": "task",
                        "resource_id": f"task-{read_index}-{index}",
                        "parent_id": f"task-list-{read_index}",
                        "version": "v1",
                        "related_resource_ids": [],
                        "payload": {
                            "title": f"Task {read_index}-{index}",
                            "status": "needsAction",
                            "due": None,
                            "notes": f"Task note {read_index}-{index}",
                        },
                    }
                    for index in range(task_counts[read_index])
                ]
            elif binding.tool_id == "tasks_list_tasklists":
                items = [
                    {
                        "resource_type": "task_list",
                        "resource_id": f"task-list-0-{index}",
                        "parent_id": None,
                        "version": "v1",
                        "related_resource_ids": [],
                        "payload": {"title": f"Task list {index}"},
                    }
                    for index in range(20)
                ]
            elif binding.tool_id == "calendar_list_calendars":
                items = [
                    {
                        "resource_type": "calendar",
                        "resource_id": f"calendar-0-{index}",
                        "parent_id": None,
                        "version": "v1",
                        "related_resource_ids": [],
                        "payload": {"summary": f"Calendar {index}"},
                    }
                    for index in range(20)
                ]
            else:
                raise AssertionError(f"unexpected tool: {binding.tool_id}")
            return ConnectorReadResultV1(
                1,
                binding.tool_id,
                f"multi-source-read-{len(self.calls)}",
                {"items": items},
                None,
                len(items),
            )

    state = _state(initial_target="context_retriever")
    state["request_intent"] = cast(Any, _intent())
    route_plan = _answer_route_plan()
    cast(Any, route_plan)["input_plan"]["input_routes"] = [
        {
            "route_id": "task-route",
            "resource_type": "TASK",
            "connector_id": "google_workspace",
            "allowed_read_tool_ids": ["tasks_list_tasks"],
            "required": True,
            "reason_codes": ["USER_REQUEST"],
        },
        {
            "route_id": "task-list-route",
            "resource_type": "TASK_LIST",
            "connector_id": "google_workspace",
            "allowed_read_tool_ids": ["tasks_list_tasklists"],
            "required": True,
            "reason_codes": ["RESOURCE_DISCOVERY"],
        },
        {
            "route_id": "calendar-route",
            "resource_type": "CALENDAR",
            "connector_id": "google_workspace",
            "allowed_read_tool_ids": ["calendar_list_calendars"],
            "required": True,
            "reason_codes": ["RESOURCE_DISCOVERY"],
        },
    ]
    state["tool_route_plan"] = cast(Any, route_plan)
    connector = MultiSourceConnector()
    graph = RetrievalSubgraph(
        now_ms=lambda: 1_000,
        should_stop_for_cancel=lambda _run_id: False,
        timezone_provider=lambda: "Asia/Seoul",
        llm_runtime=MultiSourceInference(),
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
        authorized_tasklist_ids_provider=lambda: tuple(f"task-list-{index}" for index in range(22)),
        authorized_calendar_ids_provider=lambda: tuple(f"calendar-{index}" for index in range(20)),
    ).build()

    updates: list[dict[str, object]] = []
    with provider_dispatch_execution_scope():
        for update in graph.stream(state, stream_mode="updates"):
            updates.append(cast(dict[str, object], update))
            if "assess_sufficiency" in update:
                break

    assert connector.calls == [
        *["tasks_list_tasks"] * 22,
        "tasks_list_tasklists",
        "calendar_list_calendars",
    ]
    normalize_update = cast(
        Mapping[str, object],
        next(update["normalize_segments"] for update in updates if "normalize_segments" in update),
    )
    assert len(cast(list[object], normalize_update["__context_read_result_handles__"])) == 24
    assert len(cast(list[object], normalize_update["__context_segment_handles__"])) == 65
    assert len(cast(list[object], normalize_update["segments"])) == 24
    assert any("assess_sufficiency" in update for update in updates)


@pytest.mark.parametrize(
    ("has_next_page", "expected_continuation"),
    [(False, "EXHAUSTED"), (True, "HAS_MORE")],
)
def test_retrieval__compiled_collection_metadata__is_not_limited_by_rag_evidence_caps(
    has_next_page: bool,
    expected_continuation: str,
) -> None:
    state = _state(initial_target="context_retriever")
    state["request_intent"] = cast(Any, _intent())
    state["tool_route_plan"] = cast(Any, _answer_route_plan(with_input_route=True))
    connector = _CollectionConnectorReadPort(item_count=25, has_next_page=has_next_page)
    graph = RetrievalSubgraph(
        now_ms=lambda: 1_000,
        should_stop_for_cancel=lambda _run_id: False,
        timezone_provider=lambda: "Asia/Seoul",
        llm_runtime=_ComponentInferencePort(),
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

    collection = result["retrieval_result"]["collection_results"][0]
    assert connector.call_count == 1
    assert collection["continuation_status"] == expected_continuation
    assert len(collection["items"]) == 25
    assert len(result["retrieval_result"]["source_resource_refs"]) <= 12
    assert [item["title"] for item in collection["items"][:2]] == [
        "Same title",
        "Same title",
    ]


def test_retrieval__compiled_exhaustive_collection__reads_unread_page_before_finalize() -> None:
    state = _state(initial_target="context_retriever")
    intent = _intent()
    intent["constraints"] = [
        {
            "kind": "SCOPE",
            "field": "coverage_requirement",
            "value": "EXHAUSTIVE",
        }
    ]
    state["request_intent"] = cast(Any, intent)
    state["tool_route_plan"] = cast(Any, _answer_route_plan(with_input_route=True))
    connector = _PagedCollectionConnectorReadPort()
    llm = _ComponentInferencePort()
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

    assert connector.call_count == 2
    assert llm.calls.count("retrieval.assess_sufficiency") == 1
    assert result["retrieval_result"]["collection_results"][0]["continuation_status"] == "EXHAUSTED"


@pytest.mark.parametrize(
    "cancel_after, expected_reads, expected_prompts",
    [
        ("retrieval.plan_query", 0, ["retrieval.plan_query"]),
        ("connector", 1, ["retrieval.plan_query"]),
        (
            "retrieval.assess_sufficiency",
            1,
            ["retrieval.plan_query", "retrieval.assess_sufficiency"],
        ),
    ],
)
def test_retrieval_cancellation__requested__returns_to_main_without_external_call(
    cancel_after: str,
    expected_reads: int,
    expected_prompts: list[str],
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
            self,
            binding: Any,
            arguments: dict[str, Any],
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
        now_ms=lambda: 1_000,
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

    assert connector.call_count == expected_reads
    assert llm.calls == expected_prompts
    assert result.get("retrieval_result") is None  # No fabricated successful handoff.
    assert (
        route_after_context_retriever(
            result,
            available_targets=frozenset({"end"}),
            should_stop_for_cancel=lambda _run_id: cancelled,
        )
        == "end"
    )  # Release the invocation for the existing cancellation command owner.


@pytest.mark.parametrize(
    "cancel_after_update, expected_reads, expected_prompts",
    [
        ("build_query", 0, ["retrieval.plan_query"]),
        ("rag_retrieve", 1, ["retrieval.plan_query"]),
        ("select_evidence", 1, ["retrieval.plan_query"]),
    ],
)
def test_retrieval_cancellation__between_scheduled_nodes__prevents_new_io(
    cancel_after_update: str,
    expected_reads: int,
    expected_prompts: list[str],
) -> None:
    cancelled = False
    state = _state(initial_target="context_retriever")
    state["request_intent"] = cast(Any, _intent())
    state["tool_route_plan"] = cast(Any, _answer_route_plan(with_input_route=True))
    llm = _ComponentInferencePort()
    connector = _ComponentConnectorReadPort()
    graph = RetrievalSubgraph(
        should_stop_for_cancel=lambda _run_id: cancelled,
        now_ms=lambda: 1_000,
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
            if prompt_id == "retrieval.plan_query":
                result = super()._response(prompt_id, projection)
                constraints = cast(Any, result)["route_queries"][0]["search_spec"]["constraints"]
                constraints["concept"] = {
                    "kind": "CONCEPT",
                    "concept": "일정",
                    "manifestations": ["회의", "시간변경"],
                }
                constraints["temporal_range"] = {
                    "kind": "TEMPORAL_RANGE",
                    "axis": "EVENT_TIME",
                    "timezone": "Asia/Seoul",
                    "start_local": "2026-08-31T00:00:00",
                    "end_local": "2026-09-07T00:00:00",
                }
                return result
            if prompt_id == "retrieval.select_evidence":
                self.assessed_resources.append(
                    [
                        str(segment["resource_ref"])
                        for segment in cast(list[dict[str, Any]], projection["ranked_segments"])
                    ]
                )
                for segment in cast(list[dict[str, Any]], projection["ranked_segments"]):
                    annotation = segment["temporal_date_candidates"][0]
                    assert annotation["target_index"] == 0
                    assert annotation["date_mentions_truncated"] is date_rich
                    assert len(annotation["date_mentions"]) == (12 if date_rich else 1)
                    assert annotation["date_mentions"][0] == {
                        "source_text": "2026년 9월 3일",
                        "candidate_date": "2026-09-03",
                        "year_explicit": True,
                        "date_intersects_window": True,
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
            items: list[JsonValue] = [
                {
                    "resource_type": "gmail_thread",
                    "resource_id": resource_id,
                    "parent_id": None,
                    "version": "v1",
                    "related_resource_ids": [],
                    "payload": {
                        "subject": f"Status {resource_id}",
                        "body": f"회의 일정은 2026년 9월 3일 {resource_id}"
                        + (
                            " ".join(f"2026년 9월 {day}일" for day in range(1, 22))
                            if date_rich
                            else ""
                        ),
                    },
                }
                for resource_id in ids
            ]
            output: dict[str, JsonValue] = (
                {"item": items[0]} if binding.tool_id == "gmail_get_thread" else {"items": items}
            )
            return ConnectorReadResultV1(
                1, binding.tool_id, "detail-test", output, None, len(items)
            )

    state = _state(initial_target="context_retriever")
    intent = _intent()
    intent["requested_resource_hints"] = ["GMAIL_THREAD"]
    intent["constraints"] = [{"kind": "TIME", "field": "temporal_axis", "value": "EVENT_TIME"}]
    constraints = cast(list[dict[str, object]], intent["constraints"])
    constraints.append({"kind": "DATE", "field": "period", "value": "이번주"})
    constraints.append(
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
    durable_budget = validate_run_budget_v2(dict(state["retry_budget"]))

    def update_run_budget(
        run_id: str,
        update: Callable[[Mapping[str, object]], Mapping[str, object]],
    ) -> Mapping[str, object]:
        nonlocal durable_budget
        assert run_id == state["run_id"]
        durable_budget = validate_run_budget_v2(dict(update(durable_budget)))
        return durable_budget

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
        update_run_budget=update_run_budget,
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
    assert durable_budget["connector_calls_used"] == 4
    assert durable_budget["source_page_calls_used"] == 1
    assert durable_budget["detail_fetches_used"] == 3
    assert result["retry_budget"] == durable_budget
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
    connector = _ComponentConnectorReadPort(include_body=True)
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
    attempts = cast(list[dict[str, Any]], second["__context_query_attempts__"])
    assert all(
        next(
            constraint
            for constraint in attempt["normalized_intent_constraints"]
            if constraint["kind"] == "KEYWORD"
        )["terms"]
        == ["status"]
        for attempt in attempts
    )
    assert next(
        constraint
        for constraint in attempts[1]["normalized_intent_constraints"]
        if constraint["kind"] == "CONCEPT"
    ) == {
        "kind": "CONCEPT",
        "concept": "new status evidence",
        "manifestations": ["status-1"],
    }
    assert len(attempts) == 2


def test_retrieval__route_reconsideration__preserves_inflight_query_facts() -> None:
    class RouteReconsiderationInference(_ComponentInferencePort):
        def _response(
            self, prompt_id: str, projection: Mapping[str, object]
        ) -> dict[str, object]:
            if prompt_id == "retrieval.assess_sufficiency":
                return {
                    "schema_version": 2,
                    "status": "ROUTE_RECONSIDERATION_REQUIRED",
                    "issues": [
                        {
                            "slot": "requested_fact",
                            "issue_type": "MISSING",
                            "required": True,
                            "resolution_source": "ROUTE",
                            "safety_critical": False,
                            "reason_codes": ["NO_SELECTED_EVIDENCE_SUPPORTS_REQUESTED_FACT"],
                        }
                    ],
                }
            return super()._response(prompt_id, projection)

    state = _state(initial_target="context_retriever")
    state["request_intent"] = cast(Any, _intent())
    catalog = load_development_tool_registry()
    semantic = SemanticRouteCandidate(
        ("GMAIL_THREAD",),
        (),
        "ANSWER",
        "REQUIRED",
    )
    first_binding = bind_registry_candidates(
        candidate=semantic,
        tool_catalog=catalog,
        id_factory=lambda: "route-1",
    )
    first_route = finalize_route(
        request_intent=cast(Any, state["request_intent"]),
        binding=first_binding,
        selected_tools={},
        tool_catalog=catalog,
        id_factory=_IdFactory(),
    )["tool_route_plan"]
    assert first_route is not None
    state["tool_route_plan"] = first_route
    llm = RouteReconsiderationInference()
    connector = _CollectionConnectorReadPort(item_count=20, has_next_page=True)
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
        tool_catalog=catalog,
        read_result_cache=cache,
        confirm_inline=cast(Any, _confirm_early),
    ).build()

    with provider_dispatch_execution_scope():
        first = graph.invoke(state)

    assert first["retrieval_result"] is None
    assert first["acquisition_result"]["resource_handles"]
    assert first["__context_current_round_no__"] == 0
    assert first["__context_sufficiency_output__"]["status"] == (
        "ROUTE_RECONSIDERATION_REQUIRED"
    )
    assert len(first["__context_query_attempts__"]) == 1
    first_handle_count = len(first["__context_read_result_handles__"])

    repeated_binding = bind_registry_candidates(
        candidate=semantic,
        tool_catalog=catalog,
        id_factory=lambda: "new-route-id",
    )
    rerouted = finalize_route(
        request_intent=cast(Any, state["request_intent"]),
        binding=repeated_binding,
        selected_tools={},
        tool_catalog=catalog,
        id_factory=_IdFactory(),
        previous_plan=first_route,
    )["tool_route_plan"]
    assert rerouted is not None
    assert rerouted["input_plan"] is first_route["input_plan"]

    with provider_dispatch_execution_scope():
        second = graph.invoke(
            {
                **first,
                "tool_route_plan": rerouted,
                "workflow_signal": None,
            }
        )

    followup = llm.inputs["retrieval.plan_query"][1]
    assert followup["current_round_no"] == 1
    assert len(cast(list[object], followup["prior_query_attempts"])) == 1
    assert len(cast(list[object], followup["read_result_summaries"])) == 1
    read_summary = cast(list[dict[str, object]], followup["read_result_summaries"])[0]
    assert read_summary["has_next_page"] is True
    assert read_summary["query_identity_hash"]
    issues = cast(list[dict[str, object]], followup["unresolved_sufficiency_issues"])
    assert issues[0]["reason_codes"] == ["NO_SELECTED_EVIDENCE_SUPPORTS_REQUESTED_FACT"]
    prior_attempt = cast(list[dict[str, object]], followup["prior_query_attempts"])[0]
    assert prior_attempt["query_attempt_id"]
    assert prior_attempt["normalized_intent_constraints"]
    assert connector.call_count == 2
    assert len(second["__context_query_attempts__"]) == 2
    assert len(second["__context_read_result_handles__"]) == first_handle_count + 1
    assert second["__context_query_attempts__"][1]["operation_kind"] == "SEARCH"


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
    assert llm.calls.count("retrieval.plan_query") == 5


def test_retrieval__plan_query_finalize__skips_stale_builder_plan() -> None:
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
        updates = list(
            graph.stream(
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
                },
                stream_mode="updates",
            )
        )

    visited = [next(iter(update)) for update in updates]
    assert visited == ["plan_query", "finalize"]
    assert connector.call_count == 1


def test_retrieval__new_plan_after_stale_finalize__continues_to_builder_and_read() -> None:
    state = _state(initial_target="context_retriever")
    state["request_intent"] = cast(Any, _intent())
    state["tool_route_plan"] = cast(Any, _answer_route_plan(with_input_route=True))
    llm = _ComponentInferencePort(retrieval_followup_changes_query=True)
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
        updates = list(
            graph.stream(
                {
                    **state,
                    "__context_followup_operation__": "FINALIZE",
                },
                stream_mode="updates",
            )
        )

    visited = [next(iter(update)) for update in updates]
    assert visited[:3] == ["plan_query", "build_query", "execute_read"]
    assert connector.call_count == visited.count("execute_read")
    assert connector.call_count > 0


def test_retrieval__unchanged_local_followup__closes_partial_without_looping() -> None:
    state = _state(initial_target="context_retriever")
    state["request_intent"] = cast(Any, _intent())
    state["tool_route_plan"] = cast(Any, _answer_route_plan(with_input_route=True))
    llm = _ComponentInferencePort(
        retrieval_needs_more=True,
        retrieval_followup_changes_query=False,
    )
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
    assert result["retry_budget"]["additional_retrieval_rounds_used"] == 1
    assert result["__target__"] == "SOLUTION_PLANNING"
    assert connector.call_count == 1
    assert llm.calls.count("retrieval.plan_query") == 3
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


def test_current_evidence__through_compiled_work_analysis__reenters_request_owner() -> None:
    state = _state(initial_target="work_analysis")
    state["request_intent"] = cast(Any, _intent())
    state["tool_route_plan"] = cast(Any, _answer_route_plan())
    retrieval = _retrieval_result()
    retrieval["coverage"] = "SUFFICIENT"
    retrieval["evidence_refs"] = ["current-evidence"]
    state["retrieval_result"] = cast(Any, retrieval)
    evidence_store = RunScopedEvidenceStore()
    evidence_store.put(
        run_id=state["run_id"],
        evidence_drafts=[
            {
                "schema_version": 1,
                "evidence_id": "current-evidence",
                "resource_handle": "gmail_message:current-message",
                "segment_id": "current-segment",
                "kind": "excerpt",
                "excerpt": "The observed source changes the initial request interpretation.",
                "locator": {},
                "reason_codes": ["SUPPORTS"],
            }
        ],
    )
    graph = WorkAnalysisSubgraph(
        llm_runtime=_ComponentInferencePort(request_reconsideration=True),
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

    signal = result["request_reconsideration"]
    assert result["__target__"] == "REQUEST_UNDERSTANDING"
    assert result.get("work_analysis_result") is None
    assert signal["based_on_request_intent"] == {
        "artifact_id": "intent-1",
        "revision": 1,
        "based_on": [],
    }
    assert signal["observations"] == [
        {
            "evidence_ref": "current-evidence",
            "resource_ref": "gmail_message:current-message",
            "excerpt": "The observed source changes the initial request interpretation.",
        }
    ]


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
    retrieval["source_statuses"] = [
        {
            "route_id": "input-task-route",
            "resource_type": "TASK",
            "status": "COMPLETE",
            "evidence_refs": ["task-evidence"],
            "observed_resource_count": 2,
            "failure_kind": None,
        }
    ]
    retrieval["task_review_candidates"] = [
        {
            "candidate_ref": "task:existing-0",
            "route_id": "input-task-route",
            "resource_id": "existing-0",
            "task_list_id": "task-list-1",
            "title": "task-0",
            "status": "needsAction",
            "due": None,
            "source_version_ref": None,
            "notes": None,
            "notes_truncated": False,
        },
        {
            "candidate_ref": "task:existing-1",
            "route_id": "input-task-route",
            "resource_id": "existing-1",
            "task_list_id": "task-list-1",
            "title": "task-1",
            "status": "needsAction",
            "due": None,
            "source_version_ref": None,
            "notes": None,
            "notes_truncated": False,
        },
    ]
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
        "work_analysis.assess_requested_task_satisfaction",
        "work_analysis.assess_action_necessity",
        "work_analysis.assess_information_gaps",
        "work_analysis.assess_operational_risks",
    ]


def test_work_analysis__satisfied_duplicate__does_not_ask_second_llm_to_override() -> None:
    state = _state(initial_target="work_analysis")
    intent = _intent()
    intent["requested_effect_hints"] = ["CREATE"]
    intent["requested_resource_hints"] = ["TASK"]
    state["request_intent"] = cast(Any, intent)
    state["tool_route_plan"] = cast(Any, _task_create_route_plan())
    retrieval = _retrieval_result()
    retrieval["coverage"] = "SUFFICIENT"
    retrieval["evidence_refs"] = ["task-evidence"]
    retrieval["source_statuses"] = [
        {
            "route_id": "input-task-route",
            "resource_type": "TASK",
            "status": "COMPLETE",
            "evidence_refs": ["task-evidence"],
            "observed_resource_count": 1,
            "failure_kind": None,
        }
    ]
    retrieval["task_review_candidates"] = [
        {
            "candidate_ref": "task:existing-1",
            "route_id": "input-task-route",
            "resource_id": "existing-1",
            "task_list_id": "task-list-1",
            "title": "task-0",
            "status": "needsAction",
            "due": None,
            "source_version_ref": None,
            "notes": None,
            "notes_truncated": False,
        }
    ]
    state["retrieval_result"] = cast(Any, retrieval)
    evidence_store = RunScopedEvidenceStore()
    evidence_store.put(
        run_id=state["run_id"],
        evidence_drafts=[
            {
                "schema_version": 1,
                "evidence_id": "task-evidence",
                "resource_handle": "task:existing-1",
                "segment_id": "task-segment",
                "kind": "excerpt",
                "excerpt": "task-0 is an existing task",
                "locator": {},
                "reason_codes": ["POLICY_TASK_DUPLICATE_CHECK"],
            }
        ],
    )

    llm = _ComponentInferencePort(work_fact_count=1, duplicate_found=True)
    work_analysis = WorkAnalysisSubgraph(
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
    wrapper = StateGraph(GraphState)
    wrapper.add_node("work_analysis", work_analysis)
    wrapper.add_edge(START, "work_analysis")
    wrapper.add_edge("work_analysis", END)
    graph = wrapper.compile(checkpointer=InMemorySaver())
    config: RunnableConfig = {"configurable": {"thread_id": "duplicate-override-thread"}}

    with provider_dispatch_execution_scope():
        result = graph.invoke(state, config)

    analysis = result["work_analysis_result"]
    assert analysis["action_necessity"] == "NOT_REQUIRED"
    assert analysis["route_action_necessities"] == [
        {
            "route_id": "output-task-route",
            "status": "NOT_REQUIRED",
            "reason": "REQUESTED_TASK_ALREADY_SATISFIED",
            "evidence_refs": ["task-evidence"],
            "candidate_refs": ["task:existing-1"],
        }
    ]
    assert "work_analysis.assess_action_necessity" not in llm.calls


def test_planning__compiled_normal_path__produces_answer() -> None:
    calls: list[str] = []
    inputs: list[Mapping[str, object]] = []

    def invoke(prompt_id: str, prompt_input: Mapping[str, object]) -> Mapping[str, object]:
        calls.append(prompt_id)
        inputs.append(prompt_input)
        if prompt_id == "planning.outline_answer":
            return {"sections": ["summary"], "evidence_refs": []}
        return {"schema_version": 2, "answer": "done", "evidence_refs": []}

    intent = _intent()
    constraints = cast(list[dict[str, object]], intent["constraints"])
    constraints.append(
        {
            "kind": "SCOPE",
            "field": "coverage_requirement",
            "value": "EXHAUSTIVE",
        }
    )
    graph = PlanningSubgraph(
        dependencies=PlanningRuntimeDependencies(invoke=cast(PlanningSemanticInvoker, invoke))
    ).build()
    result = graph.invoke(
        {
            "user_request": "summarize status",
            "request_intent": intent,
            "tool_route_plan": _answer_route_plan(),
            "work_analysis": {},
            "evidence": [],
            "retrieval_result": {
                **_retrieval_result(),
                "collection_results": [
                    {
                        "route_id": "route-1",
                        "resource_type": "gmail_thread",
                        "continuation_status": "HAS_MORE",
                        "items": [
                            {
                                "resource_ref": "gmail_thread:first",
                                "resource_type": "gmail_thread",
                                "title": "Same title",
                            },
                            {
                                "resource_ref": "gmail_thread:second",
                                "resource_type": "gmail_thread",
                                "title": "Same title",
                            },
                        ],
                    }
                ],
            },
        }
    )

    assert result["planning_disposition"] == "ANSWER"
    assert calls == ["planning.outline_answer", "planning.compose_answer"]
    assert all(
        item["collection_results"]
        == [
            {
                "resource_type": "gmail_thread",
                "continuation_status": "HAS_MORE",
                "items": [
                    {"item_number": 1, "title": "Same title"},
                    {"item_number": 2, "title": "Same title"},
                ],
            }
        ]
        for item in inputs
    )
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
        tool_catalog=load_development_tool_registry(),
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


def test_reconsideration_confirmation__preserves_prior_intent__and_revises_artifact() -> None:
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
        tool_catalog=load_development_tool_registry(),
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
    config: RunnableConfig = {"configurable": {"thread_id": "reconsider-confirm-thread"}}
    state = _state()
    state["request_intent"] = cast(Any, _intent())
    state["request_reconsideration"] = cast(
        Any,
        {
            "kind": "REQUEST_RECONSIDERATION_REQUIRED",
            "reason_codes": ["OBSERVED_SOURCE_CONTRADICTS_INTENT"],
            "based_on_request_intent": {
                "artifact_id": "intent-1",
                "revision": 1,
                "based_on": [],
            },
            "observations": [
                {
                    "evidence_ref": "ev-1",
                    "resource_ref": "gmail_message:message-1",
                    "excerpt": "current observation",
                }
            ],
        },
    )

    with provider_dispatch_execution_scope():
        graph.invoke(state, config)
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

    assert resumed["request_intent"]["meta"] == {
        "artifact_id": "intent-1",
        "revision": 2,
        "based_on": [{"artifact_id": "intent-1", "revision": 1}],
    }


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
            "observed_resource_count": 2,
            "checked_read_count": 1,
            "known_scope_count": 1,
            "scope_complete": True,
            "continuation_status": "EXHAUSTED",
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
