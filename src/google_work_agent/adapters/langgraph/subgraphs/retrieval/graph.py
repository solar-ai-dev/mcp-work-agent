"""Canonical Retrieval LangGraph subgraph."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from functools import partial
from hashlib import sha256
from pathlib import Path
from typing import Any, cast

from langchain_core.runnables import RunnableLambda
from langgraph.graph import END, START, StateGraph

from google_work_agent.adapters.langgraph.agent_kernel import (
    build_agent_local_state,
    consume_llm_call_budget,
    ensure_llm_call_budget,
    merge_trace_context,
)
from google_work_agent.adapters.langgraph.main.confirmation_projection import (
    build_user_interrupt_v1,
)
from google_work_agent.adapters.langgraph.main.state import (
    CONTEXT_AGENT_LOCAL_KEY,
    CONTEXT_CANONICAL_PLANS_KEY,
    CONTEXT_CURRENT_ROUND_NO_KEY,
    CONTEXT_DETAIL_CANDIDATES_KEY,
    CONTEXT_FOLLOWUP_OPERATION_KEY,
    CONTEXT_FOLLOWUP_PLANNER_INPUT_KEY,
    CONTEXT_NEXT_PAGE_HANDLES_KEY,
    CONTEXT_QUERY_ATTEMPTS_KEY,
    CONTEXT_RAG_CANDIDATES_KEY,
    CONTEXT_READ_BINDINGS_KEY,
    CONTEXT_READ_RESULT_HANDLES_KEY,
    CONTEXT_ROUND_PREADVANCED_KEY,
    CONTEXT_SEGMENT_HANDLES_KEY,
    CONTEXT_SELECTION_OUTPUT_KEY,
    CONTEXT_SUFFICIENCY_OUTPUT_KEY,
    GraphState,
    GraphStateUpdateV1,
    WorkflowPhase,
    _require_state_value,
    request_from_state,
)
from google_work_agent.adapters.langgraph.main.supervisor import (
    RetrievalRouteResultV1,
    route_supervisor,
)
from google_work_agent.adapters.langgraph.main.supervisor_decision import SupervisorDecisionV1
from google_work_agent.adapters.langgraph.profiles.profile_registry import GraphProfile
from google_work_agent.adapters.langgraph.subgraph_state import (
    AgentLocalStateV1,
)
from google_work_agent.adapters.langgraph.subgraphs.retrieval.nodes.assess_sufficiency_node import (
    assess_sufficiency_node,
)
from google_work_agent.adapters.langgraph.subgraphs.retrieval.nodes.build_query_node import (
    build_query_node,
)
from google_work_agent.adapters.langgraph.subgraphs.retrieval.nodes.execute_read_node import (
    execute_read_node,
)
from google_work_agent.adapters.langgraph.subgraphs.retrieval.nodes.finalize_retrieval_node import (
    finalize_retrieval_node,
)
from google_work_agent.adapters.langgraph.subgraphs.retrieval.nodes.normalize_segments_node import (
    normalize_segments_node,
)
from google_work_agent.adapters.langgraph.subgraphs.retrieval.nodes.plan_query_node import (
    plan_query_node,
)
from google_work_agent.adapters.langgraph.subgraphs.retrieval.nodes.select_evidence_node import (
    select_evidence_node,
)
from google_work_agent.adapters.langgraph.subgraphs.retrieval.state import (
    ContextRetrievalInputState,
    ContextRetrievalLocalState,
    ReadResultBindingV1,
    RetrievalState,
)
from google_work_agent.adapters.system.memory.retrieval_evidence_store import (
    RunScopedEvidenceStore,
    resolve_evidence_projection,
)
from google_work_agent.application.agents.request_understanding.contracts import (
    request_understanding_output,
)
from google_work_agent.application.agents.request_understanding.contracts.request_intent import (
    RequestIntentV2,
    StateArtifactRefV1,
    validated_repository_authority,
)
from google_work_agent.application.agents.retrieval.assess_sufficiency import (
    authorize_retrieval_followup,
    deterministic_sufficiency,
)
from google_work_agent.application.agents.retrieval.authorize_evidence_reassessment import (
    authorize_evidence_reassessment,
)
from google_work_agent.application.agents.retrieval.bind_exact_resource_refs import (
    ExactResourceBindingsV1,
    bind_exact_resource_refs,
)
from google_work_agent.application.agents.retrieval.build_query import (
    QueryUnchangedAfterFailureError,
    RouteConstraintPolicy,
    build_query_attempt,
    followup_planner_projection,
)
from google_work_agent.application.agents.retrieval.contracts.query_attempt import QueryAttemptV1
from google_work_agent.application.agents.retrieval.contracts.query_plan import (
    RetrievalConstraintKindV1,
    RetrievalQueryPlanV2,
    RetrievalV2ValidationError,
    SourceFetchPlanV1,
)
from google_work_agent.application.agents.retrieval.contracts.query_plan_schema import (
    RETRIEVAL_QUERY_PLAN_V2_OUTPUT_SCHEMA,
)
from google_work_agent.application.agents.retrieval.contracts.retrieval_result import (
    AcquisitionResultV1,
    PersonCandidateV1,
    RetrievalResultV1,
    SufficiencyIssueV2,
    SufficiencyResultV2,
)
from google_work_agent.application.agents.retrieval.execute_read import RetrievalReadBindingError
from google_work_agent.application.agents.retrieval.finalize_retrieval import (
    advance_current_round_no,
    initialize_current_round_no,
)
from google_work_agent.application.agents.retrieval.match_person_mention import (
    project_person_candidates,
    resolve_supported_person_identities,
)
from google_work_agent.application.agents.retrieval.plan_candidate_detail import (
    plan_candidate_detail,
)
from google_work_agent.application.agents.retrieval.plan_query import (
    DEFAULT_RETRIEVAL_BUDGET,
    deterministic_query_plan,
    followup_retrieval_planner_input,
    has_retrieval_followup_path,
    initial_retrieval_planner_input,
)
from google_work_agent.application.agents.retrieval.project_attempted_detail_refs import (
    project_attempted_detail_refs,
)
from google_work_agent.application.agents.retrieval.project_detail_candidate_refs import (
    project_detail_candidate_refs,
)
from google_work_agent.application.agents.retrieval.project_gmail_draft_source_snapshots import (
    project_gmail_draft_source_snapshots,
)
from google_work_agent.application.agents.retrieval.project_task_review_candidates import (
    project_task_review_candidates,
)
from google_work_agent.application.agents.retrieval.resolve_availability import (
    AvailableIntervalV1,
    BusyIntervalV1,
    resolve_availability,
)
from google_work_agent.application.agents.retrieval.retain_unchanged_evidence import (
    preferred_detail_evidence_ids,
)
from google_work_agent.application.agents.retrieval.select_evidence import (
    materialize_evidence_drafts,
)
from google_work_agent.application.agents.tool_routing.bind_registry_candidates import (
    coarse_resource_category,
)
from google_work_agent.application.agents.tool_routing.contracts.tool_route_plan import (
    InputToolRouteV1,
    ToolRoutePlanV2,
)
from google_work_agent.application.prompt_runtime.prompt_registry import (
    PRODUCT_RELEASE,
    PromptExecutionScope,
    default_prompt_manifest_path,
    load_prompt_reference,
)
from google_work_agent.application.tool_registry.signed_tool_registry import SignedToolRegistry
from google_work_agent.application.use_cases.resource.get_repository_access import (
    GetRepositoryAccessHandler,
)
from google_work_agent.application.use_cases.run.guard_run_budget import (
    BudgetDecision,
    RunBudgetV2,
    approve_additional_acquisition,
    approve_planning_revision,
)
from google_work_agent.ports.connector.connector_read_port import ConnectorReadPort
from google_work_agent.ports.llm.structured_inference_port import StructuredInferencePort
from google_work_agent.ports.system.contracts.confirmation import (
    ConfirmationResponseProjectionV1,
)
from google_work_agent.ports.system.contracts.observability import ObservabilityContext
from google_work_agent.ports.system.contracts.retrieval_head import RetrievalHeadV1
from google_work_agent.ports.system.contracts.workflow_signal import (
    RetrievalNeedV1,
    RetrievalRequiredV1,
)
from google_work_agent.ports.system.run_retrieval_cache_port import RunRetrievalCachePort

from .nodes.rag_retrieve_rerank_node import (
    rag_retrieve_rerank_node,
)
from .projections.execute_read_projection import (
    find_detail_resource,
    project_acquisition_result,
    project_connector_call,
    sanitize_acquisition_result,
)
from .projections.retrieval_continuation_projection import (
    bind_read_result_plan,
    read_result_binding_matches_plan,
    resolve_read_result_plan,
    restore_prior_evidence_selection,
    restore_retrieval_continuation,
)
from .routing.route_after_assess_sufficiency import (
    route_after_assess_sufficiency,
)
from .routing.route_after_build_query import (
    followup_operation_marker,
    route_after_build_query,
)
from .routing.route_after_execute_read import (
    route_after_execute_read,
)
from .routing.route_after_finalize_retrieval import (
    route_after_finalize_retrieval,
)
from .routing.route_after_normalize_segments import (
    route_after_normalize_segments,
)
from .routing.route_after_plan_query import (
    route_after_plan_query,
)
from .routing.route_after_rag_retrieve_rerank import (
    route_after_rag_retrieve_rerank,
)
from .routing.route_after_retrieval_boundary import route_after_retrieval_boundary
from .routing.route_after_select_evidence import (
    route_after_select_evidence,
)

MergeDecision = Callable[[Any, GraphStateUpdateV1, SupervisorDecisionV1], Any]
ConfirmInline = Callable[
    [ContextRetrievalLocalState],
    tuple[ConfirmationResponseProjectionV1 | None, dict[str, object] | None],
]


def _resolve_availability_from_reads(
    *,
    acquisition_result: AcquisitionResultV1,
    canonical_plans: Mapping[str, SourceFetchPlanV1],
) -> list[AvailableIntervalV1]:
    """Project FreeBusy reads into provider-neutral availability Local State."""
    freebusy_resources = [
        (str(summary.get("route_id", "")), resource)
        for summary in acquisition_result["source_summaries"]
        for resource in cast(list[dict[str, object]], summary.get("resources", []))
        if resource.get("resource_type") == "calendar_freebusy"
    ]
    if not freebusy_resources:
        return []
    results: list[AvailableIntervalV1] = []
    for route_id, resource in freebusy_resources:
        plan = canonical_plans.get(route_id)
        if plan is None:
            raise ValueError("FreeBusy result has no canonical source plan")
        timezones = {
            str(constraint["timezone"])
            for constraint in plan["effective_constraints"]
            if constraint["kind"] == "TEMPORAL_RANGE"
        }
        if len(timezones) != 1:
            raise ValueError("FreeBusy availability requires one frozen calendar timezone")
        timezone = next(iter(timezones))
        handle = resource.get("resource_handle")
        payload = resource.get("payload")
        if not isinstance(handle, str) or not isinstance(payload, Mapping):
            raise ValueError("FreeBusy resource projection is invalid")
        window_start = payload.get("time_min")
        window_end = payload.get("time_max")
        raw_intervals = payload.get("busy_intervals", [])
        if (
            not isinstance(window_start, str)
            or not isinstance(window_end, str)
            or not isinstance(raw_intervals, list)
        ):
            raise ValueError("FreeBusy interval projection is invalid")
        busy_intervals: list[BusyIntervalV1] = []
        for interval in raw_intervals:
            if not isinstance(interval, Mapping):
                raise ValueError("FreeBusy busy interval must be an object")
            start = interval.get("start")
            end = interval.get("end")
            if not isinstance(start, str) or not isinstance(end, str):
                raise ValueError("FreeBusy busy interval boundaries are invalid")
            busy_intervals.append({"start": start, "end": end, "resource_ref": handle})
        results.extend(
            resolve_availability(
                window_start=window_start,
                window_end=window_end,
                timezone=timezone,
                busy_intervals=busy_intervals,
            )
        )
    return results


def _runtime_route_constraint_policies(
    routes: list[InputToolRouteV1],
) -> dict[str, RouteConstraintPolicy]:
    """Current read executor capability projection, kept outside planner authority.

    The current Google read port supports only the listed deterministic query
    constraints. Unsupported semantic kinds fail closed before dispatch.
    """
    supported_by_resource = {
        "EMAIL": frozenset(
            {
                "TEMPORAL_RANGE",
                "PARTICIPANT",
                "KEYWORD",
                "CONCEPT",
                "RESOURCE_REF",
                "CONTAINER_REF",
                "STATUS_SCOPE",
            }
        ),
        "TASK": frozenset({"CONTAINER_REF"}),
        "ISSUE": frozenset({"CONTAINER_REF", "STATUS_SCOPE"}),
        "CALENDAR": frozenset({"TEMPORAL_RANGE", "CONTAINER_REF"}),
    }
    return {
        route["route_id"]: RouteConstraintPolicy(
            supported_kinds=cast(
                frozenset[RetrievalConstraintKindV1],
                supported_by_resource[coarse_resource_category(route["resource_type"])],
            ),
            required_kinds=(
                frozenset({"CONTAINER_REF"})
                if route["resource_type"] in {"TASK", "CALENDAR_EVENT", "CALENDAR_FREEBUSY"}
                or (
                    route["connector_id"] == "github"
                    and route["resource_type"] == "GITHUB_ISSUE"
                    and "github_list_issues" in route["allowed_read_tool_ids"]
                )
                else frozenset()
            ),
        )
        for route in routes
        if coarse_resource_category(route["resource_type"]) in supported_by_resource
    }


def _retrieval_trace_context(
    state: ContextRetrievalLocalState, node_id: str
) -> ObservabilityContext:
    request = request_from_state(state)
    return ObservabilityContext(
        request_id=request.correlation.request_id,
        command_id=request.correlation.command_id,
        conversation_id=request.conversation_id,
        run_id=request.run_id,
        langgraph_thread_id=request.workflow_key,
        llm_call_id=f"{request.run_id}:{node_id}",
    )


def _authorize_context_adjustment_budget(
    state: Mapping[str, object],
) -> RunBudgetV2:
    """Charge the user-requested fresh Retrieval and downstream replanning once."""

    current = cast(RunBudgetV2, state["retry_budget"])
    control = state.get("__workflow_control__")
    if not isinstance(control, Mapping) or control.get("kind") != "CONTEXT_ADJUSTMENT":
        return current
    revision = approve_planning_revision(current)
    if revision["decision"] == BudgetDecision.DENY.value:
        return current
    acquisition = approve_additional_acquisition(revision["run_budget"])
    return (
        current
        if acquisition["decision"] == BudgetDecision.DENY.value
        else acquisition["run_budget"]
    )


class RetrievalSubgraph:
    """Build and execute the canonical Retrieval runtime."""

    def __init__(
        self,
        *,
        llm_runtime: StructuredInferencePort,
        prompt_manifest_path: Path | None,
        prompt_execution_scope: PromptExecutionScope = PRODUCT_RELEASE,
        id_factory: Callable[[], str],
        graph_profile: GraphProfile,
        transition_run: Callable[[str, str], None],
        should_stop_for_cancel: Callable[[str], bool],
        merge_decision: MergeDecision,
        evidence_store: RunScopedEvidenceStore,
        connector_reader: ConnectorReadPort,
        tool_catalog: SignedToolRegistry,
        read_result_cache: RunRetrievalCachePort,
        confirm_inline: ConfirmInline,
        now_ms: Callable[[], int],
        timezone_provider: Callable[[], str],
        default_tasklist_id_provider: Callable[[], str | None] | None = None,
        default_calendar_id_provider: Callable[[], str | None] | None = None,
        repository_access: GetRepositoryAccessHandler | None = None,
        load_retrieval_head: Callable[[str], RetrievalHeadV1 | None] | None = None,
        update_run_budget: Callable[
            [str, Callable[[Mapping[str, object]], Mapping[str, object]]],
            Mapping[str, object],
        ]
        | None = None,
    ) -> None:
        self._llm_runtime = llm_runtime
        manifest_path = prompt_manifest_path or default_prompt_manifest_path()
        self._plan_query_prompt_ref = load_prompt_reference(
            "retrieval.plan_query", manifest_path, execution_scope=prompt_execution_scope
        )
        self._select_prompt_ref = load_prompt_reference(
            "retrieval.select_evidence", manifest_path, execution_scope=prompt_execution_scope
        )
        self._sufficiency_prompt_ref = load_prompt_reference(
            "retrieval.assess_sufficiency",
            manifest_path,
            execution_scope=prompt_execution_scope,
        )
        self._id_factory = id_factory
        self._graph_profile = graph_profile
        self._transition_run = transition_run
        self._should_stop_for_cancel = should_stop_for_cancel
        self._merge_decision = merge_decision
        self._evidence_store = evidence_store
        self._connector_reader = connector_reader
        self._repository_access = repository_access
        self._load_retrieval_head = load_retrieval_head
        self._update_run_budget = update_run_budget
        self._tool_catalog = tool_catalog
        self._read_result_cache = read_result_cache
        self._confirm_inline = confirm_inline
        self._now_ms = now_ms
        self._timezone_provider = timezone_provider
        # Pre-Prompt Runtime Closure: TASK routes' only supported semantic
        # constraint kind is CONTAINER_REF (_runtime_route_constraint_policies
        # below), but nothing ever populated validated_container_refs for the
        # planner call, so a TASK-resource plan_query could never validate.
        # Reuses the existing per-account Settings default_tasklist_id
        # concept (already the authoritative resource handler access layer's
        # own _resolve_task_list_id falls back to) rather than adding a new
        # discovery Port/authority. When unset, TASK routes keep today's
        # existing (pre-existing, unrelated to this change) behavior.
        self._default_tasklist_id_provider = default_tasklist_id_provider
        self._default_calendar_id_provider = default_calendar_id_provider

    def build(self) -> Any:
        graph = StateGraph(
            ContextRetrievalLocalState,
            input_schema=ContextRetrievalInputState,
            output_schema=GraphState,
        )
        graph.add_node("plan_query", self._cancellable_node(self._plan_query_node))
        graph.add_node("build_query", self._cancellable_node(self._build_query_node))
        graph.add_node("execute_read", self._cancellable_node(self._execute_read_node))
        graph.add_node("normalize_segments", self._cancellable_node(self._normalize_segments_node))
        graph.add_node("rag_retrieve", self._cancellable_node(self._rag_retrieve_node))
        graph.add_node("select_evidence", self._cancellable_node(self._select_evidence_node))
        graph.add_node("assess_sufficiency", self._cancellable_node(self._assess_sufficiency_node))
        graph.add_node("finalize", self._cancellable_node(self._finalize_node))
        graph.add_edge(START, "plan_query")
        boundaries = (
            ("plan_query", route_after_plan_query, ("build_query", "finalize")),
            ("build_query", route_after_build_query, ("execute_read", "finalize")),
            ("execute_read", route_after_execute_read, ("normalize_segments",)),
            ("normalize_segments", route_after_normalize_segments, ("rag_retrieve",)),
            ("rag_retrieve", route_after_rag_retrieve_rerank, ("select_evidence",)),
            ("select_evidence", route_after_select_evidence, ("assess_sufficiency",)),
            (
                "assess_sufficiency",
                route_after_assess_sufficiency,
                ("select_evidence", "plan_query", "finalize"),
            ),
            ("finalize", route_after_finalize_retrieval, ("finalize", "plan_query")),
        )
        for name, router, successors in boundaries:
            graph.add_conditional_edges(
                name,
                partial(
                    route_after_retrieval_boundary,
                    normal_route=router,
                    should_stop_for_cancel=self._should_stop_for_cancel,
                ),
                {**{target: target for target in successors}, "end": END},
            )
        return graph.compile(name="retrieval_subgraph")

    def _cancellable_node(
        self,
        step: Callable[[ContextRetrievalLocalState], ContextRetrievalLocalState],
    ) -> RunnableLambda[ContextRetrievalLocalState, ContextRetrievalLocalState]:
        def invoke(state: ContextRetrievalLocalState) -> ContextRetrievalLocalState:
            # Cancellation can arrive after edge evaluation, while the next
            # checkpoint/node is being scheduled. Recheck before starting work.
            if self._should_stop_for_cancel(state["run_id"]):
                return state
            return step(state)

        return RunnableLambda(invoke)

    def _initialize_state(self, state: ContextRetrievalLocalState) -> ContextRetrievalLocalState:
        request = request_from_state(state)
        self._transition_run(request.run_id, "begin_retrieval")
        invocation_id = self._id_factory()
        tool_route_plan = _require_state_value(state.get("tool_route_plan"), "tool_route_plan")
        current_round_no = initialize_current_round_no(
            prior_result=state.get("retrieval_result"),
            tool_route_plan=tool_route_plan,
        )
        continuation = restore_retrieval_continuation(
            state,
            has_prior_result=current_round_no > 0,
        )
        local_state = build_agent_local_state(
            agent_role="context_retriever",
            invocation_id=invocation_id,
            node_state="INITIALIZED",
            input_projection={
                "request_intent": _require_state_value(state["request_intent"], "request_intent"),
                "has_prior_acquisition": state.get("acquisition_result") is not None,
            },
            prompt_ref=self._select_prompt_ref,
        )
        retry_budget = _authorize_context_adjustment_budget(state)
        prior_result = state.get("retrieval_result")
        serialized_read_bindings: dict[str, dict[str, object]] = {
            handle: dict(binding) for handle, binding in continuation["read_bindings"].items()
        }
        next_state: ContextRetrievalLocalState = {
            **state,
            "retry_budget": retry_budget,
            "selected_person_identities": state.get(
                "selected_person_identities",
                {} if prior_result is None else prior_result.get("selected_person_identities", {}),
            ),
            "input_route_ref": cast(
                StateArtifactRefV1, dict(tool_route_plan["input_plan"]["meta"])
            ),
            "input_routes": list(tool_route_plan["input_plan"]["input_routes"]),
            "query_plan": None,
            "query_attempts": list(continuation["query_attempts"]),
            "source_statuses": [],
            "read_result_handles": list(continuation["read_result_handles"]),
            "segment_handles": list(continuation["segment_handles"]),
            "availability_results": [],
            "rag_candidates": [],
            "evidence_selection": None,
            "sufficiency": None,
            "final_result": None,
            CONTEXT_AGENT_LOCAL_KEY: local_state,
            CONTEXT_CURRENT_ROUND_NO_KEY: current_round_no,
            CONTEXT_READ_RESULT_HANDLES_KEY: list(continuation["read_result_handles"]),
            CONTEXT_READ_BINDINGS_KEY: serialized_read_bindings,
            CONTEXT_SEGMENT_HANDLES_KEY: list(continuation["segment_handles"]),
            CONTEXT_QUERY_ATTEMPTS_KEY: list(continuation["query_attempts"]),
            CONTEXT_CANONICAL_PLANS_KEY: dict(continuation["canonical_plans"]),
            CONTEXT_ROUND_PREADVANCED_KEY: current_round_no > 0,
            "trace_context": merge_trace_context(
                state,
                graph_profile=self._graph_profile.value,
                agent_subgraph_id="context_retriever",
                agent_role="context_retriever",
                agent_invocation_id=invocation_id,
                subgraph_namespace="context",
                node_name="init",
                prompt_ref=self._select_prompt_ref,
                agent_invocation_increment=1,
            ),
        }
        # Q2-HANDOFF: WorkAnalysis/Review's RetrievalRequiredV1 re-entry --
        # the signal is consumed and cleared right here, and (only when a
        # prior read already exists to extend) turned into a genuine new
        # follow-up round via the same plan_followup machinery Retrieval's
        # own local loop uses. RetrievalRequiredV1 is never produced inside
        # this subgraph -- only Supervisor constructs it.
        retrieval_required = _retrieval_required_signal(state.get("workflow_signal"))
        pending_need = _pending_retrieval_need(state.get("pending_user_retrieval_need"))
        if retrieval_required is not None or pending_need is not None:
            next_state["workflow_signal"] = None
            needs = (
                retrieval_required["needs"]
                if retrieval_required is not None
                else [cast(RetrievalNeedV1, pending_need)]
            )
            if continuation["canonical_plans"]:
                sufficiency: SufficiencyResultV2 = {
                    "schema_version": 2,
                    "status": "NEEDS_MORE_DATA",
                    "issues": _needs_as_sufficiency_issues(needs, state["tool_route_plan"]),
                }
                prior_result = cast(RetrievalResultV1, state.get("retrieval_result"))
                if prior_result is None:
                    raise ValueError("retrieval continuation requires its prior result")
                evidence_drafts = resolve_evidence_projection(
                    store=self._evidence_store,
                    run_id=state["run_id"],
                    retrieval_result=prior_result,
                )
                selection = restore_prior_evidence_selection(
                    prior_result=prior_result,
                    evidence_drafts=evidence_drafts,
                )
                next_state[CONTEXT_SUFFICIENCY_OUTPUT_KEY] = sufficiency
                next_state["sufficiency"] = sufficiency
                next_state[CONTEXT_SELECTION_OUTPUT_KEY] = selection
                next_state["evidence_selection"] = selection
                next_state["evidence_drafts"] = evidence_drafts
                next_state["availability_results"] = cast(
                    list[AvailableIntervalV1],
                    list(prior_result["availability_results"]),
                )
                next_state[CONTEXT_FOLLOWUP_PLANNER_INPUT_KEY] = followup_planner_projection(
                    current_round_no=current_round_no,
                    prior_query_attempts=list(continuation["query_attempts"]),
                    unresolved_sufficiency_issues=sufficiency["issues"],
                    read_result_summaries=self._bounded_read_result_summaries(next_state),
                )
        return next_state

    def _select_evidence_node(
        self, state: ContextRetrievalLocalState
    ) -> ContextRetrievalLocalState:
        request = request_from_state(state)
        local_state = cast(AgentLocalStateV1, state[CONTEXT_AGENT_LOCAL_KEY])
        request_intent = _require_state_value(state["request_intent"], "request_intent")
        segments = self._normalized_segments(state)
        rag_candidates = _require_state_value(
            state.get(CONTEXT_RAG_CANDIDATES_KEY), "rag candidates"
        )
        calls_before = state["retry_budget"]["llm_calls_used"]
        ensure_llm_call_budget(state)
        patch = select_evidence_node(
            cast(
                RetrievalState,
                {
                    "request_intent": request_intent,
                    "rag_candidates": rag_candidates,
                    "query_attempts": state.get(CONTEXT_QUERY_ATTEMPTS_KEY, []),
                    "evidence_selection": state.get("evidence_selection"),
                    "exclusion_obligation_segment_ids": state.get(
                        "exclusion_obligation_segment_ids", []
                    ),
                    "evidence_reassessment_issues": state.get(
                        "__context_evidence_reassessment_issues__", []
                    )
                    or [],
                },
            ),
            llm_runtime=self._llm_runtime,
            prompt_ref=self._select_prompt_ref,
            revision_prompt_ref=self._select_prompt_ref,
            source_fetch_plans=[
                state[CONTEXT_CANONICAL_PLANS_KEY][query["route_id"]]
                for query in _require_state_value(state["query_plan"], "query_plan")[
                    "route_queries"
                ]
            ],
            requested_mode=request.requested_mode,
            segments=cast(list[Any], segments),
            retry_budget=cast(RunBudgetV2, state["retry_budget"]),
        )
        selection = cast(Any, patch["evidence_selection"])
        revised_retry_budget = consume_llm_call_budget(
            {**state, "retry_budget": cast(RunBudgetV2, patch["retry_budget"])}
        )
        calls_used = revised_retry_budget["llm_calls_used"] - calls_before
        updated_local = dict(local_state)
        updated_local["node_state"] = "SELECT_EVIDENCE_COMPLETE"
        updated_local["typed_result"] = cast(dict[str, object], selection)
        selected_state = cast(
            ContextRetrievalLocalState,
            {
                **state,
                CONTEXT_AGENT_LOCAL_KEY: cast(AgentLocalStateV1, updated_local),
                CONTEXT_RAG_CANDIDATES_KEY: rag_candidates,
                CONTEXT_SELECTION_OUTPUT_KEY: selection,
                "rag_candidates": rag_candidates,
                "evidence_selection": selection,
                "__context_evidence_reassessment_issues__": None,
                "retry_budget": revised_retry_budget,
                "trace_context": merge_trace_context(
                    state,
                    graph_profile=self._graph_profile.value,
                    agent_subgraph_id="context_retriever",
                    agent_role="context_retriever",
                    agent_invocation_id=local_state["invocation_id"],
                    subgraph_namespace="context",
                    node_name="select_evidence",
                    llm_call_id=(
                        f"{request.run_id}:retrieval.select_evidence" if calls_used else None
                    ),
                    prompt_ref=self._select_prompt_ref if calls_used else None,
                    llm_call_increment=calls_used,
                ),
            },
        )
        return self._materialize_evidence(selected_state)

    def _normalize_segments_node(
        self, state: ContextRetrievalLocalState
    ) -> ContextRetrievalLocalState:
        working_state = self._ephemeral_raw_state(state)
        acquisition_result = _require_state_value(
            working_state["acquisition_result"], "acquisition_result"
        )
        for observation in project_gmail_draft_source_snapshots(acquisition_result):
            self._evidence_store.put_resource_snapshot(
                run_id=state["run_id"],
                resource_handle=observation["resource_handle"],
                source_version_ref=observation["source_version_ref"],
                snapshot=observation["snapshot"],
            )
        patch = normalize_segments_node(
            cast(
                Any,
                {
                    "operation_inputs": {
                        "normalize_segments": {
                            "acquisition_result": acquisition_result,
                            "preferred_segment_ids": preferred_detail_evidence_ids(
                                state.get("evidence_selection"),
                                [
                                    state[CONTEXT_CANONICAL_PLANS_KEY][query["route_id"]]
                                    for query in _require_state_value(
                                        state["query_plan"], "query_plan"
                                    )["route_queries"]
                                ],
                            ),
                        }
                    }
                },
            )
        )
        segments = cast(list[Any], patch["normalized_segments"])
        return cast(
            ContextRetrievalLocalState,
            {
                **state,
                "acquisition_result": sanitize_acquisition_result(acquisition_result),
                "segments": [segment.segment_id for segment in segments],
                "segment_handles": list(state.get(CONTEXT_SEGMENT_HANDLES_KEY, [])),
                "availability_results": _resolve_availability_from_reads(
                    acquisition_result=acquisition_result,
                    canonical_plans=state.get(CONTEXT_CANONICAL_PLANS_KEY, {}),
                ),
            },
        )

    def _normalized_segments(self, state: ContextRetrievalLocalState) -> list[Any]:
        working_state = self._ephemeral_raw_state(state)
        acquisition_result = _require_state_value(
            working_state["acquisition_result"], "acquisition_result"
        )
        patch = normalize_segments_node(
            cast(
                Any,
                {
                    "operation_inputs": {
                        "normalize_segments": {
                            "acquisition_result": acquisition_result,
                            "preferred_segment_ids": list(state.get("segments", [])),
                        }
                    }
                },
            )
        )
        segments = cast(list[Any], patch["normalized_segments"])
        expected_ids = state.get("segments")
        actual_ids = [segment.segment_id for segment in segments]
        if expected_ids is not None and actual_ids != expected_ids:
            raise ValueError("stable segment identity changed within one retrieval round")
        return segments

    def _ephemeral_raw_state(self, state: ContextRetrievalLocalState) -> ContextRetrievalLocalState:
        handles = cast(list[str], state.get(CONTEXT_READ_RESULT_HANDLES_KEY, []))
        bindings = cast(Mapping[str, object], state.get(CONTEXT_READ_BINDINGS_KEY, {}))
        if not handles:
            return state
        results = self._resolve_cached_results(state, bindings=bindings, handles=handles)
        plans = self._plans_for_cached_results(
            state,
            plans=list(state.get(CONTEXT_CANONICAL_PLANS_KEY, {}).values()),
            bindings=bindings,
            handles=handles,
        )
        safe = cast(AcquisitionResultV1, state.get("acquisition_result"))
        hydrated = project_acquisition_result(
            list(zip(plans, results, strict=True)),
            remaining_budget=dict(safe["remaining_budget"]),
            prior_result=safe,
        )
        return cast(
            ContextRetrievalLocalState,
            {**state, "acquisition_result": hydrated},
        )

    def _rag_retrieve_node(self, state: ContextRetrievalLocalState) -> ContextRetrievalLocalState:
        request_intent = _require_state_value(state["request_intent"], "request_intent")
        segments = self._normalized_segments(state)
        patch = rag_retrieve_rerank_node(
            cast(
                Any,
                {
                    "operation_inputs": {
                        "rag_retrieve_rerank": {
                            "segments": cast(list[Any], segments),
                            "request_intent": request_intent,
                            "source_plans": list(state[CONTEXT_CANONICAL_PLANS_KEY].values()),
                            "top_k": 24,
                        }
                    }
                },
            )
        )
        candidates = cast(list[Any], patch["rag_candidates"])
        return {
            **state,
            "ranked_segments": candidates,
            "rag_candidates": candidates,
            CONTEXT_RAG_CANDIDATES_KEY: candidates,
        }

    def _materialize_evidence(
        self, state: ContextRetrievalLocalState
    ) -> ContextRetrievalLocalState:
        local_state = cast(AgentLocalStateV1, state[CONTEXT_AGENT_LOCAL_KEY])
        selection = state[CONTEXT_SELECTION_OUTPUT_KEY]
        evidence_drafts = materialize_evidence_drafts(
            selection,
            segments=cast(list[Any], self._normalized_segments(state)),
        )
        updated_local = dict(local_state)
        updated_local["node_state"] = "SELECTION_VALIDATED"
        updated_local["typed_result"] = cast(dict[str, object], selection)
        prior_result = state.get("retrieval_result")
        prior_candidates = [] if prior_result is None else prior_result.get("person_candidates", [])
        person_candidates = project_person_candidates(
            _require_state_value(state["request_intent"], "request_intent"),
            evidence_drafts,
            state.get("person_candidates", prior_candidates),
            state.get("exclusion_obligation_segment_ids", []),
            source_segments=self._normalized_segments(state),
        )
        return {
            **state,
            CONTEXT_AGENT_LOCAL_KEY: cast(AgentLocalStateV1, updated_local),
            "evidence_drafts": evidence_drafts,
            "person_candidates": person_candidates,
            "selected_person_identities": resolve_supported_person_identities(
                person_candidates,
                evidence_drafts,
                state.get(
                    "selected_person_identities",
                    {}
                    if prior_result is None
                    else prior_result.get("selected_person_identities", {}),
                ),
            ),
            "trace_context": merge_trace_context(
                state,
                graph_profile=self._graph_profile.value,
                agent_subgraph_id="context_retriever",
                agent_role="context_retriever",
                agent_invocation_id=local_state["invocation_id"],
                subgraph_namespace="context",
                node_name="select_evidence",
            ),
        }

    def _run_sufficiency_attempt(
        self,
        state: ContextRetrievalLocalState,
        *,
        confirmation_response: ConfirmationResponseProjectionV1 | None,
    ) -> tuple[SufficiencyResultV2, dict[str, object], RunBudgetV2]:
        """One ``retrieval.assess_sufficiency`` LLM call. Safe to call again
        for a later confirmation round -- ``select_evidence``/
        deterministic evidence materialization already completed before any
        pause, so ``evidence_drafts`` here is always the same already-frozen
        selection, never re-derived or re-fetched.
        """
        deterministic = deterministic_sufficiency(
            request_intent=_require_state_value(state["request_intent"], "request_intent"),
            tool_route_plan=state.get("tool_route_plan"),
            acquisition_result=_require_state_value(
                state["acquisition_result"], "acquisition_result"
            ),
            evidence_drafts=state["evidence_drafts"],
            retry_budget=cast(RunBudgetV2, state["retry_budget"]),
            confirmation_response=confirmation_response,
            person_candidates=state.get("person_candidates", []),
            selected_person_identities=state.get("selected_person_identities"),
            query_attempts=state.get(CONTEXT_QUERY_ATTEMPTS_KEY, []),
        )
        if deterministic is not None:
            return (
                deterministic,
                {"structured_output_attempts": 0},
                cast(RunBudgetV2, state["retry_budget"]),
            )
        ensure_llm_call_budget(state)
        patch = assess_sufficiency_node(
            cast(
                RetrievalState,
                {
                    "request_intent": _require_state_value(
                        state["request_intent"], "request_intent"
                    ),
                    "evidence_selection": state[CONTEXT_SELECTION_OUTPUT_KEY],
                    "query_attempts": state.get(CONTEXT_QUERY_ATTEMPTS_KEY, []),
                },
            ),
            llm_runtime=self._llm_runtime,
            prompt_ref=self._sufficiency_prompt_ref,
            requested_mode=request_from_state(state).requested_mode,
            tool_route_plan=state.get("tool_route_plan"),
            acquisition_result=_require_state_value(
                state["acquisition_result"], "acquisition_result"
            ),
            evidence_drafts=state["evidence_drafts"],
            retry_budget=cast(RunBudgetV2, state["retry_budget"]),
            confirmation_response=confirmation_response,
            attempted_detail_candidate_refs=self._attempted_detail_candidate_refs(state),
            read_result_summaries=self._bounded_read_result_summaries(state),
        )
        sufficiency_result = cast(SufficiencyResultV2, patch["sufficiency"])
        llm_provider_result: dict[str, object] = {"structured_output_attempts": 1}
        retry_budget = consume_llm_call_budget(state)
        return sufficiency_result, llm_provider_result, retry_budget

    def _assess_sufficiency_node(
        self, state: ContextRetrievalLocalState
    ) -> ContextRetrievalLocalState:
        local_state = cast(AgentLocalStateV1, state[CONTEXT_AGENT_LOCAL_KEY])
        sufficiency_result, llm_provider_result, retry_budget = self._run_sufficiency_attempt(
            state, confirmation_response=None
        )
        tool_route_plan = _require_state_value(state["tool_route_plan"], "tool_route_plan")
        detail_followup = plan_candidate_detail(
            prompt_input={
                "current_round_no": state[CONTEXT_CURRENT_ROUND_NO_KEY],
                "unresolved_sufficiency_issues": sufficiency_result["issues"],
            },
            frozen_routes=tool_route_plan["input_plan"]["input_routes"],
            detail_candidate_refs=project_detail_candidate_refs(
                evidence_drafts=state.get("evidence_drafts", []),
                acquisition_result=state.get("acquisition_result"),
            ),
            attempted_detail_candidate_refs=self._attempted_detail_candidate_refs(state),
        )
        sufficiency_result, retry_budget, should_plan_followup = authorize_retrieval_followup(
            sufficiency_result,
            request_intent=_require_state_value(state["request_intent"], "request_intent"),
            retry_budget=retry_budget,
            evidence_supported_partial_possible=bool(state["evidence_drafts"]),
            detail_fetch_count=len(detail_followup["route_queries"]) if detail_followup else 0,
            can_acquire_new_information=any(
                item["slot"] == "person_identity_search" for item in sufficiency_result["issues"]
            )
            or has_retrieval_followup_path(
                request_intent=_require_state_value(state["request_intent"], "request_intent"),
                tool_route_plan=tool_route_plan,
                route_policies=_runtime_route_constraint_policies(
                    tool_route_plan["input_plan"]["input_routes"]
                ),
                unresolved_sufficiency_issues=cast(
                    list[Mapping[str, object]], sufficiency_result["issues"]
                ),
                read_result_summaries=self._bounded_read_result_summaries(state),
                query_attempts=cast(
                    list[QueryAttemptV1], state.get(CONTEXT_QUERY_ATTEMPTS_KEY, [])
                ),
                detail_candidate_refs=project_detail_candidate_refs(
                    evidence_drafts=state.get("evidence_drafts", []),
                    acquisition_result=state.get("acquisition_result"),
                ),
                attempted_detail_candidate_refs=self._attempted_detail_candidate_refs(state),
            ),
        )
        reassessment_issues, retry_budget = authorize_evidence_reassessment(
            sufficiency=sufficiency_result,
            selection=state[CONTEXT_SELECTION_OUTPUT_KEY],
            candidates=state.get(CONTEXT_RAG_CANDIDATES_KEY, []),
            segments=self._normalized_segments(state),
            retry_budget=retry_budget,
            can_acquire_new_information=should_plan_followup,
        )
        updated_local = dict(local_state)
        updated_local["node_state"] = "SUFFICIENCY_COMPLETE"
        updated_local["typed_result"] = cast(dict[str, object], sufficiency_result)
        next_state: ContextRetrievalLocalState = {
            **state,
            CONTEXT_AGENT_LOCAL_KEY: cast(AgentLocalStateV1, updated_local),
            CONTEXT_SUFFICIENCY_OUTPUT_KEY: sufficiency_result,
            "sufficiency": sufficiency_result,
            "llm_provider_result": llm_provider_result,
            "retry_budget": retry_budget,
            "__context_evidence_reassessment_issues__": reassessment_issues or None,
            "trace_context": merge_trace_context(
                state,
                graph_profile=self._graph_profile.value,
                agent_subgraph_id="context_retriever",
                agent_role="context_retriever",
                agent_invocation_id=local_state["invocation_id"],
                subgraph_namespace="context",
                node_name="assess_sufficiency",
                llm_call_id=(
                    f"{request_from_state(state).run_id}:retrieval.assess_sufficiency"
                    if llm_provider_result.get("structured_output_attempts", 0)
                    else None
                ),
                prompt_ref=(
                    self._sufficiency_prompt_ref
                    if llm_provider_result.get("structured_output_attempts", 0)
                    else None
                ),
                llm_call_increment=cast(
                    int, llm_provider_result.get("structured_output_attempts", 0)
                ),
            ),
        }
        if should_plan_followup:
            next_state[CONTEXT_FOLLOWUP_PLANNER_INPUT_KEY] = followup_planner_projection(
                current_round_no=state[CONTEXT_CURRENT_ROUND_NO_KEY],
                prior_query_attempts=list(state.get(CONTEXT_QUERY_ATTEMPTS_KEY, [])),
                unresolved_sufficiency_issues=cast(
                    list[dict[str, object]], list(sufficiency_result["issues"])
                ),
                read_result_summaries=self._bounded_read_result_summaries(state),
            )
        elif sufficiency_result["status"] == "NEEDS_CONFIRMATION":
            # Materialized here -- not in finalize -- because this node never
            # replays on resume (it completes and commits before any pause),
            # so interrupt_id is generated exactly once and stays stable
            # across finalize's node-replay.
            request_intent = _require_state_value(state["request_intent"], "request_intent")
            user_interrupt, confirmation_interrupt = self._materialize_confirmation_interrupt(
                result=sufficiency_result,
                request_intent=request_intent,
                person_candidates=state.get("person_candidates", []),
                selected_person_identities=state.get("selected_person_identities", {}),
            )
            next_state["workflow_phase"] = WorkflowPhase.WAITING_CONFIRMATION.value
            next_state["user_interrupt"] = cast(Any, user_interrupt)
            next_state["prompt_context"] = {
                **cast(dict[str, object], state.get("prompt_context", {})),
                "confirmation_interrupt": confirmation_interrupt,
            }
        return next_state

    def _validated_container_refs(
        self,
        state: ContextRetrievalLocalState,
        frozen_routes: list[InputToolRouteV1],
    ) -> dict[str, list[str]]:
        """Resolve existing validated container authorities per frozen route.

        Google defaults retain their existing behavior. GitHub routes consume
        only current-Run RequestIntent/SelectedResourceRef authority.
        """
        tasklist_id = (
            None
            if self._default_tasklist_id_provider is None
            else self._default_tasklist_id_provider()
        )
        calendar_id = (
            None
            if self._default_calendar_id_provider is None
            else self._default_calendar_id_provider()
        )
        result: dict[str, list[str]] = {}
        for route in frozen_routes:
            category = coarse_resource_category(route["resource_type"])
            if category == "TASK" and tasklist_id:
                result[route["route_id"]] = [tasklist_id]
            elif category == "CALENDAR" and calendar_id:
                result[route["route_id"]] = [calendar_id]
        github_routes = [
            route
            for route in frozen_routes
            if route["connector_id"] == "github"
            and route["resource_type"].upper() == "GITHUB_ISSUE"
        ]
        if github_routes:
            request_intent = cast(
                RequestIntentV2,
                _require_state_value(state.get("request_intent"), "request intent"),
            )
            repository = validated_repository_authority(
                request_intent,
                selected_resources=request_from_state(state).selected_resources,
            )
            if repository is not None:
                for route in github_routes:
                    result[route["route_id"]] = [repository]
        return result

    @staticmethod
    def _exact_resource_bindings(
        state: ContextRetrievalLocalState,
        frozen_routes: list[InputToolRouteV1],
    ) -> ExactResourceBindingsV1:
        request_intent = cast(
            RequestIntentV2,
            _require_state_value(state.get("request_intent"), "request intent"),
        )
        return bind_exact_resource_refs(
            request_intent=request_intent,
            frozen_routes=frozen_routes,
            selected_resources=request_from_state(state).selected_resources,
        )

    @staticmethod
    def _bound_detail_resource(
        state: ContextRetrievalLocalState,
        *,
        resource_type: str,
        resource_ref: str,
    ) -> Mapping[str, object] | None:
        tool_route_plan = _require_state_value(state.get("tool_route_plan"), "tool_route_plan")
        bindings = RetrievalSubgraph._exact_resource_bindings(
            state,
            tool_route_plan["input_plan"]["input_routes"],
        )
        identity = bindings["identities_by_ref"].get(resource_ref)
        if identity is None or identity["resource_type"].upper() != resource_type.upper():
            return None
        return identity

    def _plan_query_node(self, state: ContextRetrievalLocalState) -> ContextRetrievalLocalState:
        if CONTEXT_AGENT_LOCAL_KEY not in state:
            state = self._initialize_state(state)
        tool_route_plan = _require_state_value(state.get("tool_route_plan"), "tool_route_plan")
        frozen_routes = tool_route_plan["input_plan"]["input_routes"]
        route_policies = _runtime_route_constraint_policies(frozen_routes)
        exact_resource_bindings = self._exact_resource_bindings(state, frozen_routes)
        validated_resource_refs = exact_resource_bindings["refs_by_route"]
        validated_container_refs = self._validated_container_refs(state, frozen_routes)
        followup = state.get(CONTEXT_FOLLOWUP_PLANNER_INPUT_KEY)
        detail_candidate_refs = project_detail_candidate_refs(
            evidence_drafts=state.get("evidence_drafts", []),
            acquisition_result=state.get("acquisition_result"),
        )
        attempted_detail_candidate_refs = self._attempted_detail_candidate_refs(state)
        prior_canonical = state.get(CONTEXT_CANONICAL_PLANS_KEY, {})
        prior_read_result_handles = self._prior_read_result_handles(state, prior_canonical)
        read_result_summaries = self._bounded_read_result_summaries(state)
        prompt_input = (
            initial_retrieval_planner_input(
                request_intent=_require_state_value(state["request_intent"], "request_intent"),
                input_routes=frozen_routes,
                retrieval_budget=DEFAULT_RETRIEVAL_BUDGET,
                validated_resource_refs=validated_resource_refs,
                validated_container_refs=validated_container_refs,
            )
            if followup is None
            else followup_retrieval_planner_input(
                request_intent=_require_state_value(state["request_intent"], "request_intent"),
                input_routes=frozen_routes,
                retrieval_budget=DEFAULT_RETRIEVAL_BUDGET,
                followup=followup,
                validated_resource_refs=validated_resource_refs,
                validated_container_refs=validated_container_refs,
            )
        )
        deterministic_plan = deterministic_query_plan(
            prompt_input=prompt_input,
            frozen_routes=frozen_routes,
            route_policies=route_policies,
            validated_resource_refs=validated_resource_refs,
            validated_container_refs=validated_container_refs,
            timezone=self._timezone_provider(),
            detail_candidate_refs=detail_candidate_refs,
            attempted_detail_candidate_refs=attempted_detail_candidate_refs,
            person_candidates=state.get("person_candidates", []),
            selected_person_identities=state.get("selected_person_identities"),
        )
        if deterministic_plan is None:
            ensure_llm_call_budget(state)
        try:
            patch = plan_query_node(
                cast(
                    Any,
                    {
                        "operation_inputs": {
                            "plan_query": {
                                "llm_runtime": self._llm_runtime,
                                "prompt_ref": self._plan_query_prompt_ref,
                                "revision_prompt_ref": self._plan_query_prompt_ref,
                                "output_schema": RETRIEVAL_QUERY_PLAN_V2_OUTPUT_SCHEMA,
                                "prompt_input": prompt_input,
                                "requested_mode": request_from_state(state).requested_mode,
                                "frozen_routes": frozen_routes,
                                "route_policies": route_policies,
                                "retry_budget": cast(RunBudgetV2, state["retry_budget"]),
                                "validated_resource_refs": validated_resource_refs,
                                "validated_container_refs": validated_container_refs,
                                "detail_candidate_refs": detail_candidate_refs,
                                "attempted_detail_candidate_refs": attempted_detail_candidate_refs,
                                "now_ms": state["retry_budget"]["started_at_ms"],
                                "timezone": self._timezone_provider(),
                                "person_candidates": state.get("person_candidates", []),
                                "selected_person_identities": state.get(
                                    "selected_person_identities"
                                ),
                                "prior_plans": prior_canonical,
                                "prior_read_result_handles": prior_read_result_handles,
                                "read_result_summaries": read_result_summaries,
                            }
                        }
                    },
                )
            )
        except QueryUnchangedAfterFailureError as error:
            if followup is None:
                raise
            return self._close_unmaterializable_followup(state, validation_error=error)
        query_plan = cast(RetrievalQueryPlanV2, patch["query_plan"])
        revised_retry_budget = cast(RunBudgetV2, patch["retry_budget"])
        llm_invoked = deterministic_plan is None
        result: ContextRetrievalLocalState = {
            **state,
            "query_plan": query_plan,
            "retry_budget": (
                consume_llm_call_budget({**state, "retry_budget": revised_retry_budget})
                if llm_invoked
                else revised_retry_budget
            ),
        }
        result.pop(CONTEXT_FOLLOWUP_OPERATION_KEY, None)
        return result

    @staticmethod
    def _attempted_detail_candidate_refs(state: ContextRetrievalLocalState) -> list[str]:
        return project_attempted_detail_refs(
            cast(list[QueryAttemptV1], state.get(CONTEXT_QUERY_ATTEMPTS_KEY, []))
        )

    @staticmethod
    def _prior_read_result_handles(
        state: ContextRetrievalLocalState,
        prior_canonical: Mapping[str, SourceFetchPlanV1],
    ) -> dict[str, str]:
        bindings = cast(Mapping[str, ReadResultBindingV1], state.get(CONTEXT_READ_BINDINGS_KEY, {}))
        result: dict[str, str] = {}
        handles = cast(list[str], state.get(CONTEXT_READ_RESULT_HANDLES_KEY, list(bindings)))
        for handle in reversed(handles):
            binding = bindings.get(handle)
            if not isinstance(binding, Mapping):
                raise RetrievalReadBindingError("read-result binding is malformed")
            route_id = binding.get("route_id")
            query_hash = binding.get("query_identity_hash")
            plan = prior_canonical.get(route_id) if isinstance(route_id, str) else None
            if (
                plan is not None
                and isinstance(query_hash, str)
                and read_result_binding_matches_plan(binding, plan)
                and route_id not in result
            ):
                result[route_id] = handle
        return result

    def _execute_read_node(self, state: ContextRetrievalLocalState) -> ContextRetrievalLocalState:
        round_no = (
            state[CONTEXT_CURRENT_ROUND_NO_KEY]
            if state.get(CONTEXT_ROUND_PREADVANCED_KEY) is True
            else advance_current_round_no(
                current_round_no=state[CONTEXT_CURRENT_ROUND_NO_KEY],
                is_followup=state.get(CONTEXT_FOLLOWUP_OPERATION_KEY)
                in {"SEARCH", "NEXT_PAGE", "READ"},
            )
        )
        plans = cast(
            list[SourceFetchPlanV1],
            [
                state[CONTEXT_CANONICAL_PLANS_KEY][query["route_id"]]
                for query in _require_state_value(state.get("query_plan"), "query_plan")[
                    "route_queries"
                ]
            ],
        )
        route_plan = _require_state_value(state.get("tool_route_plan"), "tool_route_plan")
        routes = {route["route_id"]: route for route in route_plan["input_plan"]["input_routes"]}
        bindings = dict(cast(Mapping[str, object], state.get(CONTEXT_READ_BINDINGS_KEY, {})))
        new_handles: list[str] = []
        failed_reads: list[tuple[SourceFetchPlanV1, str]] = []
        page_calls = 0
        attempts = list(cast(list[QueryAttemptV1], state.get(CONTEXT_QUERY_ATTEMPTS_KEY, [])))
        for plan in plans:
            if self._should_stop_for_cancel(state["run_id"]):
                break
            route = routes.get(plan["route_id"])
            if route is None:
                raise RetrievalReadBindingError("retrieval plan route is not frozen")
            detail_resource = None
            candidate_ref = plan["detail_candidate_ref"]
            if candidate_ref is not None:
                route_handles = [
                    handle
                    for handle in state.get(CONTEXT_READ_RESULT_HANDLES_KEY, [])
                    if isinstance(bindings.get(handle), Mapping)
                    and cast(Mapping[str, object], bindings[handle]).get("route_id")
                    == plan["route_id"]
                ]
                prior_results = self._resolve_cached_results(
                    state,
                    bindings=bindings,
                    handles=route_handles,
                )
                detail_resource = find_detail_resource(candidate_ref, prior_results)
                if detail_resource is None:
                    detail_resource = self._bound_detail_resource(
                        state,
                        resource_type=plan["resource_type"],
                        resource_ref=candidate_ref,
                    )
                if detail_resource is None:
                    raise RetrievalReadBindingError(
                        "DETAIL_FETCH candidate is neither cache-bound nor current-Run selected"
                    )
            resource_refs = [
                ref
                for constraint in plan["effective_constraints"]
                if constraint["kind"] == "RESOURCE_REF"
                for ref in constraint["resource_refs"]
            ]
            if resource_refs:
                if len(resource_refs) != 1:
                    raise RetrievalReadBindingError(
                        "direct selected-resource read requires exactly one resource ref"
                    )
                detail_resource = self._bound_detail_resource(
                    state,
                    resource_type=plan["resource_type"],
                    resource_ref=resource_refs[0],
                )
                if detail_resource is None:
                    raise RetrievalReadBindingError("selected resource is not current-Run bound")
            tool_id, arguments = project_connector_call(
                plan,
                route=route,
                page_size=DEFAULT_RETRIEVAL_BUDGET.max_page_size,
                detail_resource=detail_resource,
            )
            binding = self._tool_catalog.bind_required(plan["connector_id"], tool_id, "READ")
            read_handle = self._id_factory()
            patch = execute_read_node(
                cast(
                    Any,
                    {
                        "operation_inputs": {
                            "execute_read": {
                                "plan": plan,
                                "run_id": state["run_id"],
                                "binding": binding,
                                "tool_arguments": arguments,
                                "connector_reader": self._connector_reader,
                                "read_result_cache": self._read_result_cache,
                                "read_result_handle": read_handle,
                                "run_budget": state["retry_budget"],
                                "now_ms": self._now_ms(),
                                "prior_query_attempts": attempts,
                                "repository_access": self._repository_access,
                                "request_intent": state["request_intent"],
                                "selected_resources": request_from_state(state).selected_resources,
                                "durable_budget_accountant": (
                                    None
                                    if self._update_run_budget is None
                                    else lambda update: self._update_run_budget(
                                        state["run_id"], update
                                    )
                                ),
                            }
                        }
                    },
                )
            )
            execution = cast(Any, patch["read_execution"])
            if execution.status == "FAILED":
                failed_reads.append((plan, execution.failure_code))
            if execution.provider_called and plan["operation_kind"] != "DETAIL_FETCH":
                page_calls += 1
            effective_handle = execution.read_result_handle
            if execution.status == "COMPLETE":
                bindings[effective_handle] = bind_read_result_plan(plan)
                new_handles.append(effective_handle)
            token = None
            resolution = self._read_result_cache.resolve_read_result(
                effective_handle,
                state["run_id"],
                plan["route_id"],
                plan["query_identity_hash"],
            )
            if resolution.entry is not None:
                token = resolution.entry.read_result.next_page_token
            attempts.append(
                build_query_attempt(
                    query_attempt_id=self._id_factory(),
                    run_id=state["run_id"],
                    plan=plan,
                    round_no=round_no,
                    attempt_no=len(attempts),
                    tool_id=tool_id,
                    canonical_arguments=arguments,
                    previous_query_hash=(
                        None
                        if plan["prior_read_result_handle"] is None
                        else cast(Mapping[str, str], bindings[plan["prior_read_result_handle"]])[
                            "query_identity_hash"
                        ]
                    ),
                    page_state_hash=(None if token is None else sha256(token.encode()).hexdigest()),
                    candidate_count=execution.candidate_count,
                    stop_reason=execution.status,
                    prior_query_attempts=attempts,
                    change_reason_code=next(
                        query["reason_codes"][0]
                        for query in _require_state_value(state.get("query_plan"), "query_plan")[
                            "route_queries"
                        ]
                        if query["route_id"] == plan["route_id"]
                    ),
                )
            )
        all_handles = [
            *cast(list[str], state.get(CONTEXT_READ_RESULT_HANDLES_KEY, [])),
            *new_handles,
        ]
        raw_results = self._resolve_cached_results(
            state,
            bindings=bindings,
            handles=all_handles,
        )
        plan_by_binding = self._plans_for_cached_results(
            state, plans=plans, bindings=bindings, handles=all_handles
        )
        acquisition = project_acquisition_result(
            list(zip(plan_by_binding, raw_results, strict=True)),
            remaining_budget=self._remaining_retrieval_budget(state, page_calls),
            failed_reads=failed_reads,
            prior_result=state.get("acquisition_result"),
        )
        safe_acquisition = self._bounded_acquisition(acquisition)
        return cast(
            ContextRetrievalLocalState,
            {
                **state,
                "acquisition_result": safe_acquisition,
                CONTEXT_CURRENT_ROUND_NO_KEY: round_no,
                CONTEXT_READ_RESULT_HANDLES_KEY: all_handles,
                CONTEXT_SEGMENT_HANDLES_KEY: list(acquisition["resource_handles"]),
                CONTEXT_QUERY_ATTEMPTS_KEY: attempts,
                CONTEXT_READ_BINDINGS_KEY: bindings,
                CONTEXT_ROUND_PREADVANCED_KEY: False,
                "read_result_handles": all_handles,
                "segment_handles": list(acquisition["resource_handles"]),
                "query_attempts": attempts,
                "task_review_candidates": project_task_review_candidates(acquisition),
            },
        )

    def _resolve_cached_results(
        self,
        state: ContextRetrievalLocalState,
        *,
        bindings: Mapping[str, object],
        handles: list[str] | None = None,
    ) -> list[Any]:
        resolved = []
        for handle in (
            cast(list[str], state.get(CONTEXT_READ_RESULT_HANDLES_KEY, []))
            if handles is None
            else handles
        ):
            raw = bindings.get(handle)
            if not isinstance(raw, Mapping):
                raise RetrievalReadBindingError("read-result handle has no local binding")
            route_id = raw.get("route_id")
            query_hash = raw.get("query_identity_hash")
            if not isinstance(route_id, str) or not isinstance(query_hash, str):
                raise RetrievalReadBindingError("read-result binding is malformed")
            resolution = self._read_result_cache.resolve_read_result(
                handle, state["run_id"], route_id, query_hash
            )
            if resolution.status not in {"FOUND", "EXHAUSTED"} or resolution.entry is None:
                raise RetrievalReadBindingError(
                    f"invalid retrieval cache dependency: {resolution.status}"
                )
            resolved.append(resolution.entry.read_result)
        return resolved

    @staticmethod
    def _plans_for_cached_results(
        state: ContextRetrievalLocalState,
        *,
        plans: list[SourceFetchPlanV1],
        bindings: Mapping[str, object],
        handles: list[str],
    ) -> list[SourceFetchPlanV1]:
        prior = cast(
            Mapping[str, SourceFetchPlanV1],
            state.get(CONTEXT_CANONICAL_PLANS_KEY, {}),
        )
        available_plans = [*plans, *prior.values()]
        result = []
        for handle in handles:
            raw = bindings.get(handle)
            if not isinstance(raw, Mapping):
                raise RetrievalReadBindingError("read-result binding is malformed")
            try:
                result.append(resolve_read_result_plan(raw, available_plans=available_plans))
            except ValueError as error:
                raise RetrievalReadBindingError(str(error)) from error
        return result

    @staticmethod
    def _bounded_acquisition(result: AcquisitionResultV1) -> AcquisitionResultV1:
        return {
            **result,
            "source_summaries": [
                {key: value for key, value in summary.items() if key != "resources"}
                for summary in result["source_summaries"]
            ],
        }

    @staticmethod
    def _remaining_retrieval_budget(
        state: ContextRetrievalLocalState, provider_calls: int
    ) -> dict[str, int]:
        prior = state.get("acquisition_result")
        remaining = (
            DEFAULT_RETRIEVAL_BUDGET.as_remaining()
            if not isinstance(prior, Mapping)
            else dict(cast(Mapping[str, int], prior.get("remaining_budget", {})))
        )
        remaining["pages"] = max(0, remaining.get("pages", 0) - provider_calls)
        return remaining

    def _build_query_node(self, state: ContextRetrievalLocalState) -> ContextRetrievalLocalState:
        tool_route_plan = _require_state_value(state.get("tool_route_plan"), "tool_route_plan")
        frozen_routes = tool_route_plan["input_plan"]["input_routes"]
        route_policies = _runtime_route_constraint_policies(frozen_routes)
        exact_resource_bindings = self._exact_resource_bindings(state, frozen_routes)
        validated_resource_refs = exact_resource_bindings["refs_by_route"]
        validated_container_refs = self._validated_container_refs(state, frozen_routes)
        query_plan = _require_state_value(state.get("query_plan"), "query plan")
        detail_candidate_refs = state.get(CONTEXT_SEGMENT_HANDLES_KEY, [])
        prior_canonical = state.get(CONTEXT_CANONICAL_PLANS_KEY, {})
        if not prior_canonical:
            patch = build_query_node(
                cast(
                    Any,
                    {
                        "operation_inputs": {
                            "build_query": {
                                "plan": query_plan,
                                "frozen_routes": frozen_routes,
                                "route_policies": route_policies,
                                "validated_resource_refs": validated_resource_refs,
                                "validated_container_refs": validated_container_refs,
                                "detail_candidate_refs": detail_candidate_refs,
                            }
                        }
                    },
                )
            )
            canonical_plans = cast(list[SourceFetchPlanV1], patch["source_fetch_plans"])
            return {
                **state,
                CONTEXT_CANONICAL_PLANS_KEY: {plan["route_id"]: plan for plan in canonical_plans},
            }
        handles = self._prior_read_result_handles(state, prior_canonical)
        try:
            patch = build_query_node(
                cast(
                    Any,
                    {
                        "operation_inputs": {
                            "build_query": {
                                "plan": query_plan,
                                "frozen_routes": frozen_routes,
                                "route_policies": route_policies,
                                "prior_plans": prior_canonical,
                                "person_candidates": state.get("person_candidates", []),
                                "selected_person_identities": state.get(
                                    "selected_person_identities"
                                ),
                                "prior_read_result_handles": handles,
                                "read_result_summaries": self._bounded_read_result_summaries(state),
                                "validated_resource_refs": validated_resource_refs,
                                "validated_container_refs": validated_container_refs,
                                "detail_candidate_refs": detail_candidate_refs,
                            }
                        }
                    },
                )
            )
            canonical_plans = cast(list[SourceFetchPlanV1], patch["source_fetch_plans"])
        except QueryUnchangedAfterFailureError as error:
            return self._close_unmaterializable_followup(
                state,
                validation_error=error,
            )
        operations = {plan["operation_kind"] for plan in canonical_plans}
        if not operations:
            raise RetrievalV2ValidationError(
                "materialized retrieval plan contains no executable operation",
                reason_code="QUERY_OPERATION_UNAVAILABLE",
            )
        operation_marker = followup_operation_marker(operations)
        result: ContextRetrievalLocalState = {
            **state,
            CONTEXT_CANONICAL_PLANS_KEY: {
                **prior_canonical,
                **{plan["route_id"]: plan for plan in canonical_plans},
            },
            CONTEXT_FOLLOWUP_OPERATION_KEY: operation_marker,
        }
        next_page_plans = [
            plan for plan in canonical_plans if plan["operation_kind"] == "NEXT_PAGE"
        ]
        if next_page_plans:
            result[CONTEXT_NEXT_PAGE_HANDLES_KEY] = {
                plan["route_id"]: cast(str, plan["prior_read_result_handle"])
                for plan in next_page_plans
            }
        detail_plans = [
            plan for plan in canonical_plans if plan["operation_kind"] == "DETAIL_FETCH"
        ]
        if detail_plans:
            result[CONTEXT_DETAIL_CANDIDATES_KEY] = {
                plan["route_id"]: cast(str, plan["detail_candidate_ref"]) for plan in detail_plans
            }
        return result

    def _close_unmaterializable_followup(
        self,
        state: ContextRetrievalLocalState,
        *,
        validation_error: RetrievalV2ValidationError | None = None,
    ) -> ContextRetrievalLocalState:
        """Close a planned follow-up that cannot produce a distinct read."""

        working_state = self._ephemeral_raw_state(state)
        sufficiency, retry_budget, _ = authorize_retrieval_followup(
            cast(SufficiencyResultV2, working_state[CONTEXT_SUFFICIENCY_OUTPUT_KEY]),
            request_intent=_require_state_value(working_state["request_intent"], "request_intent"),
            retry_budget=cast(RunBudgetV2, working_state["retry_budget"]),
            evidence_supported_partial_possible=bool(working_state["evidence_drafts"]),
            can_acquire_new_information=False,
        )
        current_round_no = working_state[CONTEXT_CURRENT_ROUND_NO_KEY]
        if working_state.get(CONTEXT_ROUND_PREADVANCED_KEY) is True:
            current_round_no = max(0, current_round_no - 1)
        local_state = cast(AgentLocalStateV1, working_state[CONTEXT_AGENT_LOCAL_KEY])
        updated_local = dict(local_state)
        if validation_error is not None:
            updated_local["node_state"] = "QUERY_BUILD_REJECTED"
            updated_local["candidate_output"] = cast(
                dict[str, object], working_state.get("query_plan")
            )
            updated_local["failure_record"] = {
                "schema_version": 1,
                "reason_code": validation_error.reason_code,
                "diagnostic": str(validation_error),
                "retryable": False,
            }
        return {
            **working_state,
            CONTEXT_AGENT_LOCAL_KEY: cast(AgentLocalStateV1, updated_local),
            CONTEXT_SUFFICIENCY_OUTPUT_KEY: sufficiency,
            "sufficiency": sufficiency,
            "retry_budget": retry_budget,
            CONTEXT_CURRENT_ROUND_NO_KEY: current_round_no,
            CONTEXT_FOLLOWUP_OPERATION_KEY: "FINALIZE",
        }

    @staticmethod
    def _route_after_followup_plan(state: ContextRetrievalLocalState) -> str:
        operation = state.get(CONTEXT_FOLLOWUP_OPERATION_KEY)
        if operation == "NEXT_PAGE":
            return "execute_next_page"
        if operation == "SEARCH":
            return "execute_followup_search"
        if operation == "DETAIL_FETCH":
            return "execute_detail"
        return "finalize"

    def _materialize_confirmation_interrupt(
        self,
        *,
        result: SufficiencyResultV2,
        request_intent: RequestIntentV2,
        person_candidates: Sequence[PersonCandidateV1] = (),
        selected_person_identities: Mapping[str, str] | None = None,
    ) -> tuple[dict[str, object], dict[str, object]]:
        """Build one round's ``(user_interrupt, confirmation_interrupt metadata)``.

        Safe to call with ``self._id_factory()``-backed identifiers only from
        an invocation that has not itself called ``interrupt()`` yet: true
        for ``assess_sufficiency`` (round 1, never replays) and for a
        *freshly self-looped* ``finalize`` invocation about to materialize
        round N+1 and return (not yet resumed, so not yet replayed either).
        ``origin_target`` stays ``retrieval.assess_sufficiency`` -- the
        already-allowlisted (``CONFIRMATION_ORIGIN_TARGETS``) value this
        question always had, even though ``interrupt()`` itself now lives in
        ``finalize``; Tool Route's own ``tool_route.finalize`` shows this
        origin_target/interrupt-owning-node split is already an accepted
        convention, not a new one.
        """
        issue = next(
            (item for item in result["issues"] if item["resolution_source"] == "USER"),
            None,
        )
        slot = "required information" if issue is None else issue["slot"]
        reason_code = (
            "RETRIEVAL_NEEDS_CONFIRMATION"
            if issue is None or not issue["reason_codes"]
            else issue["reason_codes"][0]
        )
        question: request_understanding_output.ClarificationQuestionV1 = {
            "schema_version": 1,
            "origin_target": "retrieval.assess_sufficiency",
            "question": f"‘{request_intent['goal']}’을 위한 조회 조건을 확정하지 못했습니다. "
            "대상이나 기간 중 원하는 조건을 알려주세요. 아직 외부 변경은 실행하지 않았습니다.",
            "affected_field_paths": [slot],
            "reason_code": reason_code,
            "known_context_summary": request_intent["goal"],
            "options": [],
        }
        if reason_code == "PERSON_IDENTITY_AMBIGUOUS":
            for mention in dict.fromkeys(item["mention"] for item in person_candidates):
                candidates = [item for item in person_candidates if item["mention"] == mention]
                if len(candidates) < 2 or (selected_person_identities or {}).get(mention) in {
                    item["identity"] for item in candidates
                }:
                    continue
                question["question"] = (
                    f"‘{mention}’에 해당할 수 있는 사람이 여러 명입니다. 누구를 찾으시나요?"
                )
                question["options"] = [
                    {
                        "option_id": item["identity"],
                        "label": f"{' / '.join(item['display_names'])} ({item['identity']})",
                    }
                    for item in candidates
                ]
                break
        interrupt_id = self._id_factory()
        user_interrupt = {
            **build_user_interrupt_v1(question),
            "interrupt_id": interrupt_id,
        }
        confirmation_interrupt = {
            "schema_version": 1,
            "interrupt_id": interrupt_id,
            "semantic_owner_id": "RETRIEVAL",
            "origin_target": question["origin_target"],
        }
        return user_interrupt, confirmation_interrupt

    def _finalize_node(self, state: ContextRetrievalLocalState) -> ContextRetrievalLocalState:
        result = cast(SufficiencyResultV2, state[CONTEXT_SUFFICIENCY_OUTPUT_KEY])

        if result["status"] == "NEEDS_CONFIRMATION" and isinstance(
            state.get("user_interrupt"), Mapping
        ):
            state, result = self._resolve_confirmation_inline(state)
            if result is None:
                # RequestConfirmation not applied / ResumeConfirmation
                # conflict -- the confirm_inline callback already built the
                # correct end-of-run state patch. Never loop back from here.
                return cast(
                    ContextRetrievalLocalState,
                    {**state, "__context_retrieval_retry_confirmation__": False},
                )
            if result["status"] == "NEEDS_CONFIRMATION":
                # Still ambiguous after this round's answer. Do NOT call
                # interrupt() again inside this already-resumed task -- see
                # module docstring / Tool Route's established rationale.
                # Materialize the next round's payload (self._id_factory()
                # is safe here: this "finalize" invocation has not itself
                # paused yet) and cleanly return so the self-loop
                # conditional edge re-enters "finalize" as a fresh, separate
                # task for that round.
                request_intent = _require_state_value(state["request_intent"], "request_intent")
                user_interrupt, confirmation_interrupt = self._materialize_confirmation_interrupt(
                    result=result,
                    request_intent=request_intent,
                    person_candidates=state.get("person_candidates", []),
                    selected_person_identities=state.get("selected_person_identities", {}),
                )
                prompt_context = dict(cast(dict[str, object], state.get("prompt_context", {})))
                prompt_context["confirmation_interrupt"] = confirmation_interrupt
                return cast(
                    ContextRetrievalLocalState,
                    {
                        **state,
                        "workflow_phase": WorkflowPhase.WAITING_CONFIRMATION.value,
                        "user_interrupt": cast(Any, user_interrupt),
                        "prompt_context": prompt_context,
                        "__context_retrieval_retry_confirmation__": True,
                    },
                )

        if result["status"] == "NEEDS_MORE_DATA":
            return self._assess_sufficiency_node(state)
        return self._finalize_resolved(state, result=result)

    def _resolve_confirmation_inline(
        self, state: ContextRetrievalLocalState
    ) -> tuple[ContextRetrievalLocalState, Any]:
        """Pause via a real nested-subgraph ``interrupt()``, then resolve the
        bounded ``ConfirmationResponseProjectionV1`` with exactly one more
        ``retrieval.assess_sufficiency`` call -- not by re-entering
        ``select_evidence`` or re-reading any
        provider data. Returns ``(state, None)`` when the caller must return
        ``state`` immediately (not-applied/conflict end state); otherwise
        ``(updated_state, resolved_result)``.

        This whole method's body replays from the top on resume (LangGraph's
        standard node-replay semantics for the node containing
        ``interrupt()``) -- every value it depends on before the interrupt
        call is either read unchanged from state (set once by
        ``assess_sufficiency``, a node that itself never replays) or is
        itself the idempotency-guarded, side-effect-free core in
        ``confirm_inline``.
        """
        confirmation_response, early_return_patch = self._confirm_inline(state)
        if early_return_patch is not None:
            return cast(ContextRetrievalLocalState, {**state, **early_return_patch}), None
        assert confirmation_response is not None

        candidates = state.get("person_candidates", [])
        selection = confirmation_response.get("selected_option") or confirmation_response.get(
            "free_text"
        )
        current_interrupt = state.get("user_interrupt")
        offered = (
            set()
            if current_interrupt is None
            else {item["option_id"] for item in current_interrupt["options"]}
        )
        if selection in offered:
            selected = dict(state.get("selected_person_identities", {}))
            for item in candidates:
                if item["identity"] == selection:
                    selected[item["mention"]] = item["identity"]
            state = {**state, "selected_person_identities": selected}

        sufficiency_result, llm_provider_result, retry_budget = self._run_sufficiency_attempt(
            state, confirmation_response=confirmation_response
        )

        prompt_context = dict(cast(dict[str, object], state.get("prompt_context", {})))
        prompt_context.pop("confirmation_interrupt", None)

        updated_state = cast(
            ContextRetrievalLocalState,
            {
                **state,
                CONTEXT_SUFFICIENCY_OUTPUT_KEY: sufficiency_result,
                "llm_provider_result": llm_provider_result,
                "retry_budget": retry_budget,
                "user_interrupt": None,
                "prompt_context": prompt_context,
            },
        )
        return updated_state, sufficiency_result

    def _finalize_resolved(
        self, state: ContextRetrievalLocalState, *, result: SufficiencyResultV2
    ) -> ContextRetrievalLocalState:
        local_state = cast(AgentLocalStateV1, state[CONTEXT_AGENT_LOCAL_KEY])
        selection = state[CONTEXT_SELECTION_OUTPUT_KEY]
        sufficiency = state[CONTEXT_SUFFICIENCY_OUTPUT_KEY]
        # Q2-HANDOFF: RetrievalResultV1 is only materialized for a disposition
        # a Parent may actually consume (SUFFICIENT/PARTIAL). Unfinished
        # candidates (NEEDS_MORE_DATA/NEEDS_CONFIRMATION/
        # ROUTE_RECONSIDERATION_REQUIRED/BLOCKED) are never forced into it --
        # Supervisor routes those purely on `disposition` below.
        retrieval_result = None
        if state.get("tool_route_plan") is not None and result["status"] in {
            "SUFFICIENT",
            "PARTIAL",
        }:
            prior_result = state.get("retrieval_result")
            prior_artifact_ref: StateArtifactRefV1 | None = None
            if prior_result is None and self._load_retrieval_head is not None:
                head = self._load_retrieval_head(state["run_id"])
                if head is not None:
                    prior_artifact_ref = {
                        "artifact_id": head.retrieval_artifact_id,
                        "revision": head.retrieval_revision,
                    }
            patch = finalize_retrieval_node(
                cast(
                    RetrievalState,
                    {
                        "request_intent": _require_state_value(
                            state["request_intent"], "request_intent"
                        ),
                        "evidence_selection": selection,
                        "sufficiency": sufficiency,
                        "availability_results": state.get("availability_results", []),
                        "query_attempts": state.get(CONTEXT_QUERY_ATTEMPTS_KEY, []),
                        "person_candidates": state.get("person_candidates", []),
                        "selected_person_identities": state.get("selected_person_identities", {}),
                        "exclusion_obligation_segment_ids": state.get(
                            "exclusion_obligation_segment_ids", []
                        ),
                    },
                ),
                artifact_id=self._id_factory(),
                tool_route_plan=_require_state_value(state["tool_route_plan"], "tool_route_plan"),
                acquisition_result=_require_state_value(
                    state["acquisition_result"], "acquisition_result"
                ),
                evidence_drafts=state["evidence_drafts"],
                current_round_no=state[CONTEXT_CURRENT_ROUND_NO_KEY],
                prior_result=prior_result,
                prior_artifact_ref=prior_artifact_ref,
                task_review_candidates=list(state.get("task_review_candidates", [])),
            )
            retrieval_result = cast(Any, patch["final_result"])
        self._evidence_store.put(run_id=state["run_id"], evidence_drafts=state["evidence_drafts"])
        retrieval_return: RetrievalRouteResultV1 = {
            "disposition": cast(str, result["status"]),
            "typed_result": retrieval_result,
        }
        decision = route_supervisor(
            phase=WorkflowPhase.CONTEXT_RETRIEVAL,
            state=cast(GraphState, state),
            result=retrieval_return,
        )
        updated_local = dict(local_state)
        updated_local["node_state"] = "FINALIZED"
        updated_local["typed_result"] = cast(dict[str, object], result)
        updated_local["disposition"] = {
            "schema_version": 1,
            "status": cast(str, result["status"]),
            "next_target": cast(str, decision["target"]),
            "reason_code": cast(str | None, decision.get("reason_code")),
        }
        merged = self._merge_decision(
            {
                **state,
                CONTEXT_AGENT_LOCAL_KEY: cast(AgentLocalStateV1, updated_local),
                "trace_context": merge_trace_context(
                    state,
                    graph_profile=self._graph_profile.value,
                    agent_subgraph_id="context_retriever",
                    agent_role="context_retriever",
                    agent_invocation_id=local_state["invocation_id"],
                    subgraph_namespace="context",
                    node_name="finalize",
                ),
                "__context_retrieval_retry_confirmation__": False,
            },
            {"workflow_phase": WorkflowPhase.CONTEXT_RETRIEVAL.value},
            decision,
        )
        if retrieval_result is not None:
            merged["retrieval_result"] = retrieval_result
            merged["acquisition_result"] = sanitize_acquisition_result(
                _require_state_value(state["acquisition_result"], "acquisition_result")
            )
            merged["pending_user_retrieval_need"] = None
            merged["exclusion_obligation_segment_ids"] = []
        merged.pop(CONTEXT_AGENT_LOCAL_KEY, None)
        merged.pop(CONTEXT_RAG_CANDIDATES_KEY, None)
        merged.pop(CONTEXT_SELECTION_OUTPUT_KEY, None)
        merged.pop(CONTEXT_SUFFICIENCY_OUTPUT_KEY, None)
        merged.pop(CONTEXT_CURRENT_ROUND_NO_KEY, None)
        merged.pop(CONTEXT_ROUND_PREADVANCED_KEY, None)
        # Keep bounded read identities until terminal cleanup so a Main
        # Analysis/Review back-edge can extend the exact prior query.
        merged.pop(CONTEXT_FOLLOWUP_PLANNER_INPUT_KEY, None)
        merged.pop(CONTEXT_FOLLOWUP_OPERATION_KEY, None)
        merged.pop(CONTEXT_NEXT_PAGE_HANDLES_KEY, None)
        merged.pop(CONTEXT_DETAIL_CANDIDATES_KEY, None)
        merged.pop("query_plan", None)
        merged.pop("query_attempts", None)
        merged.pop("source_statuses", None)
        merged.pop("read_result_handles", None)
        merged.pop("segment_handles", None)
        merged.pop("rag_candidates", None)
        merged.pop("evidence_selection", None)
        merged.pop("sufficiency", None)
        merged.pop("final_result", None)
        merged.pop("input_route_ref", None)
        merged.pop("input_routes", None)
        merged.pop("segments", None)
        merged.pop("ranked_segments", None)
        merged.pop("availability_results", None)
        merged.pop("evidence_drafts", None)
        merged.pop("llm_provider_result", None)
        merged.pop("__context_evidence_reassessment_issues__", None)
        merged.pop("source_fetch_plans", None)
        return cast(ContextRetrievalLocalState, merged)

    def _bounded_read_result_summaries(
        self, state: ContextRetrievalLocalState
    ) -> list[dict[str, object]]:
        summaries: dict[tuple[str, str], dict[str, object]] = {}
        bindings = cast(Mapping[str, object], state.get(CONTEXT_READ_BINDINGS_KEY, {}))
        for handle in cast(list[str], state.get(CONTEXT_READ_RESULT_HANDLES_KEY, [])):
            raw = bindings.get(handle)
            if not isinstance(raw, Mapping):
                continue
            route_id = raw.get("route_id")
            query_hash = raw.get("query_identity_hash")
            if not isinstance(route_id, str) or not isinstance(query_hash, str):
                continue
            resolution = self._read_result_cache.resolve_read_result(
                handle, state["run_id"], route_id, query_hash
            )
            if resolution.entry is None:
                continue
            token = resolution.entry.read_result.next_page_token
            output = resolution.entry.read_result.output
            raw_items = output.get("items", [])
            count = len(raw_items) if isinstance(raw_items, list) else 1 if "item" in output else 0
            summaries[(route_id, query_hash)] = {
                "read_result_handle": handle,
                "route_id": route_id,
                "query_identity_hash": query_hash,
                "has_next_page": token is not None,
                "exhausted": resolution.status == "EXHAUSTED",
                "result_count": count,
                "page_state_hash": None if token is None else sha256(token.encode()).hexdigest(),
            }
        return list(summaries.values())


def _retrieval_required_signal(signal: object) -> RetrievalRequiredV1 | None:
    if isinstance(signal, dict) and signal.get("kind") == "RETRIEVAL_REQUIRED":
        return cast(RetrievalRequiredV1, signal)
    return None


def _pending_retrieval_need(value: object) -> RetrievalNeedV1 | None:
    if not isinstance(value, Mapping):
        return None
    required_information = value.get("required_information")
    reason_codes = value.get("reason_codes")
    if not isinstance(required_information, str) or not required_information:
        raise ValueError("pending Retrieval need requires bounded required_information")
    if not isinstance(reason_codes, list) or not all(
        isinstance(item, str) and item for item in reason_codes
    ):
        raise ValueError("pending Retrieval need requires reason_codes")
    return {
        "required_information": required_information,
        "reason_codes": list(reason_codes),
    }


def _needs_as_sufficiency_issues(
    needs: list[RetrievalNeedV1],
    tool_route_plan: ToolRoutePlanV2 | None,
) -> list[SufficiencyIssueV2]:
    """Project an incoming WorkAnalysis/Review need into the same bounded,
    Retrieval-local ``unresolved_sufficiency_issues`` shape the internal
    local loop already feeds ``retrieval.plan_query`` with (SufficiencyIssue,
    docs/05-context-retrieval.md SS19.1) -- reusing the existing follow-up
    channel rather than adding a second, differently-shaped planner input."""
    routes = [] if tool_route_plan is None else tool_route_plan["input_plan"]["input_routes"]
    issues: list[SufficiencyIssueV2] = [
        {
            "slot": need["required_information"],
            "issue_type": "MISSING",
            "required": True,
            "resolution_source": "ROUTE"
            if len(routes) != 1
            else "GOOGLE"
            if routes[0]["connector_id"] == "google_workspace"
            else "CONNECTOR",
            "safety_critical": False,
            "reason_codes": list(need["reason_codes"]),
        }
        for need in needs
    ]
    if len(routes) == 1:
        for issue in issues:
            issue["route_id"] = routes[0]["route_id"]
    return issues
