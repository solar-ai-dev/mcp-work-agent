"""Canonical Request Understanding owner-local LangGraph."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any, cast

from langgraph.graph import END, START, StateGraph

from google_work_agent.adapters.langgraph.agent_kernel import merge_trace_context
from google_work_agent.adapters.langgraph.main.confirmation_projection import (
    build_user_interrupt_v1,
)
from google_work_agent.adapters.langgraph.main.state import (
    GraphState,
    GraphStateUpdateV1,
    WorkflowPhase,
    request_from_run_input_state,
)
from google_work_agent.adapters.langgraph.main.supervisor import route_supervisor
from google_work_agent.adapters.langgraph.main.supervisor_decision import SupervisorDecisionV1
from google_work_agent.adapters.langgraph.main.supervisor_terminal_projection import (
    finalize_supervisor_result,
)
from google_work_agent.adapters.langgraph.profiles.profile_registry import GraphProfile
from google_work_agent.adapters.langgraph.subgraphs.request_understanding.state import (
    RequestUnderstandingInputState,
    RequestUnderstandingParentOutputState,
    RequestUnderstandingStateV2,
)
from google_work_agent.application.agents.request_understanding.identify_resource_roles import (
    build_resource_role_candidates,
)
from google_work_agent.application.agents.request_understanding.identify_temporal_scope import (
    needs_temporal_scope,
)
from google_work_agent.application.prompt_runtime.prompt_registry import (
    PRODUCT_RELEASE,
    PromptExecutionScope,
    default_prompt_manifest_path,
    load_prompt_reference,
)
from google_work_agent.application.tool_registry.signed_tool_registry import SignedToolRegistry
from google_work_agent.application.use_cases.connection.check_connector_prerequisites import (
    CheckConnectorPrerequisitesHandler,
)
from google_work_agent.ports.llm.structured_inference_port import StructuredInferencePort
from google_work_agent.ports.system.contracts.confirmation import (
    ConfirmationResponseProjectionV1,
    UserInterruptV1,
)

from .nodes.detect_ambiguity_node import (
    detect_ambiguity_node,
)
from .nodes.finalize_intent_node import (
    finalize_intent_node,
)
from .nodes.identify_goal_node import (
    identify_goal_node,
)
from .nodes.identify_temporal_scope_node import identify_temporal_scope_node
from .projections.request_confirmation_projection import (
    build_request_clarification_question,
)
from .routing.route_after_detect_ambiguity import (
    route_after_detect_ambiguity,
)
from .routing.route_after_finalize_intent import (
    route_after_finalize_intent,
)
from .routing.route_after_identify_goal import (
    route_after_identify_goal,
)
from .routing.route_after_identify_temporal_scope import (
    route_after_identify_temporal_scope,
)

MergeDecision = Callable[[Any, GraphStateUpdateV1, SupervisorDecisionV1], Any]
TransitionRun = Callable[[str, str], None]
ConfirmInline = Callable[
    [RequestUnderstandingStateV2],
    tuple[ConfirmationResponseProjectionV1 | None, dict[str, object] | None],
]


class RequestUnderstandingSubgraph:
    """Compile the owner-local Request Understanding operations."""

    def __init__(
        self,
        *,
        llm_runtime: StructuredInferencePort,
        tool_catalog: SignedToolRegistry,
        prompt_manifest_path: Path | None,
        prompt_execution_scope: PromptExecutionScope = PRODUCT_RELEASE,
        id_factory: Callable[[], str],
        graph_profile: GraphProfile,
        transition_run: TransitionRun,
        merge_decision: MergeDecision,
        confirm_inline: ConfirmInline,
        connector_prerequisites: CheckConnectorPrerequisitesHandler | None = None,
    ) -> None:
        self._llm_runtime = llm_runtime
        self._resource_role_candidates = build_resource_role_candidates(tool_catalog)
        manifest_path = prompt_manifest_path or default_prompt_manifest_path()
        self._identify_goal_prompt_ref = load_prompt_reference(
            "request_understanding.identify_goal",
            manifest_path,
            execution_scope=prompt_execution_scope,
        )
        self._identify_resource_responsibilities_prompt_ref = load_prompt_reference(
            "request_understanding.identify_resource_responsibilities",
            manifest_path,
            execution_scope=prompt_execution_scope,
        )
        self._identify_effect_prohibitions_prompt_ref = load_prompt_reference(
            "request_understanding.identify_effect_prohibitions",
            manifest_path,
            execution_scope=prompt_execution_scope,
        )
        self._identify_source_status_prompt_ref = load_prompt_reference(
            "request_understanding.identify_source_status",
            manifest_path,
            execution_scope=prompt_execution_scope,
        )
        self._identify_temporal_scope_prompt_ref = load_prompt_reference(
            "request_understanding.identify_temporal_scope",
            manifest_path,
            execution_scope=prompt_execution_scope,
        )
        self._detect_ambiguity_prompt_ref = load_prompt_reference(
            "request_understanding.detect_ambiguity",
            manifest_path,
            execution_scope=prompt_execution_scope,
        )
        self._id_factory = id_factory
        self._graph_profile = graph_profile
        self._transition_run = transition_run
        self._merge_decision = merge_decision
        self._confirm_inline = confirm_inline
        self._connector_prerequisites = connector_prerequisites

    def build(self) -> Any:
        graph = StateGraph(
            RequestUnderstandingStateV2,
            input_schema=RequestUnderstandingInputState,
            output_schema=RequestUnderstandingParentOutputState,
        )
        graph.add_node("identify_goal", self._identify_goal_node)
        graph.add_node("identify_temporal_scope", self._identify_temporal_scope_node)
        graph.add_node("detect_ambiguity", self._detect_ambiguity_node)
        graph.add_node("finalize_intent", self._finalize_intent_node)
        graph.add_edge(START, "identify_goal")
        graph.add_conditional_edges(
            "identify_goal",
            route_after_identify_goal,
            {"identify_temporal_scope": "identify_temporal_scope"},
        )
        graph.add_conditional_edges(
            "identify_temporal_scope",
            route_after_identify_temporal_scope,
            {"detect_ambiguity": "detect_ambiguity"},
        )
        graph.add_conditional_edges(
            "detect_ambiguity",
            route_after_detect_ambiguity,
            {"finalize_intent": "finalize_intent"},
        )
        graph.add_conditional_edges(
            "finalize_intent",
            route_after_finalize_intent,
            {"identify_goal": "identify_goal", "end": END},
        )
        return graph.compile(name="request_understanding_subgraph")

    def _identify_goal_node(
        self, state: RequestUnderstandingStateV2
    ) -> RequestUnderstandingStateV2:
        request = request_from_run_input_state(cast(Any, state))
        invocation_id = self._invocation_id(state)
        is_first_node = invocation_id is None
        if is_first_node:
            self._transition_run(request.run_id, "start_analysis")
            invocation_id = self._id_factory()
        if request.entry_mode not in {"AGENT_SEARCH", "RESOURCE_SELECTED"}:
            raise ValueError(f"unsupported request entry mode: {request.entry_mode}")
        current_run_fields = cast(
            RequestUnderstandingStateV2,
            {
                "request_text": request.request_text,
                "entry_mode": request.entry_mode,
                "selected_resource_refs": list(request.selected_resources),
            },
        )
        working_state = cast(RequestUnderstandingStateV2, {**state, **current_run_fields})
        patch = identify_goal_node(
            working_state,
            llm_runtime=self._llm_runtime,
            prompt_ref=self._identify_goal_prompt_ref,
            effect_prohibition_prompt_ref=self._identify_effect_prohibitions_prompt_ref,
            responsibility_prompt_ref=self._identify_resource_responsibilities_prompt_ref,
            source_status_prompt_ref=self._identify_source_status_prompt_ref,
            resource_role_candidates=self._resource_role_candidates,
        )
        calls_used = max(
            0,
            patch["retry_budget"]["llm_calls_used"] - state["retry_budget"]["llm_calls_used"],
        )
        return {
            **current_run_fields,
            **patch,
            "workflow_phase": WorkflowPhase.REQUEST_ANALYSIS.value,
            "trace_context": self._trace(
                working_state,
                node_name="identify_goal",
                llm_call_id=f"{request.run_id}:request.identify_goal",
                prompt_ref=self._identify_goal_prompt_ref,
                additional_prompt_refs=(
                    self._identify_effect_prohibitions_prompt_ref,
                    self._identify_resource_responsibilities_prompt_ref,
                    self._identify_source_status_prompt_ref,
                ),
                llm_call_increment=calls_used,
                invocation_id=invocation_id,
                agent_invocation_increment=1 if is_first_node else 0,
            ),
        }

    def _identify_temporal_scope_node(
        self, state: RequestUnderstandingStateV2
    ) -> RequestUnderstandingStateV2:
        candidate = state.get("goal_candidate")
        if candidate is None:
            raise ValueError("request-understanding goal candidate is required")
        invokes_llm = needs_temporal_scope(candidate)
        patch = identify_temporal_scope_node(
            state,
            llm_runtime=self._llm_runtime,
            prompt_ref=self._identify_temporal_scope_prompt_ref,
        )
        return {
            **patch,
            "trace_context": self._trace(
                state,
                node_name="identify_temporal_scope",
                llm_call_id=(
                    f"{request_from_run_input_state(cast(Any, state)).run_id}:"
                    "request.identify_temporal_scope"
                    if invokes_llm
                    else None
                ),
                prompt_ref=self._identify_temporal_scope_prompt_ref if invokes_llm else None,
                llm_call_increment=int(invokes_llm),
                invocation_id=self._invocation_id(state),
            ),
        }

    def _detect_ambiguity_node(
        self, state: RequestUnderstandingStateV2
    ) -> RequestUnderstandingStateV2:
        request = request_from_run_input_state(cast(Any, state))
        patch = detect_ambiguity_node(
            state,
            connector_prerequisites=self._connector_prerequisites,
            llm_runtime=self._llm_runtime,
            prompt_ref=self._detect_ambiguity_prompt_ref,
        )
        working_state = cast(RequestUnderstandingStateV2, {**state, **patch})
        result: RequestUnderstandingStateV2 = {
            **patch,
            "trace_context": self._trace(
                state,
                node_name="detect_ambiguity",
                llm_call_id=None
                if patch.get("prerequisite_message")
                else f"{request.run_id}:request.detect_ambiguity",
                prompt_ref=None
                if patch.get("prerequisite_message")
                else self._detect_ambiguity_prompt_ref,
                llm_call_increment=0 if patch.get("prerequisite_message") else 1,
            ),
        }
        ambiguity = working_state.get("ambiguity_candidate")
        if (
            not patch.get("prerequisite_message")
            and ambiguity is not None
            and ambiguity["requires_confirmation"]
        ):
            result.update(self._confirmation_signal(working_state))
        return result

    def _confirmation_signal(
        self, state: RequestUnderstandingStateV2
    ) -> RequestUnderstandingStateV2:
        ambiguity = state.get("ambiguity_candidate")
        candidate = state.get("goal_candidate")
        if ambiguity is None or candidate is None:
            raise ValueError("request-understanding ambiguity is required")
        request = request_from_run_input_state(cast(Any, state))
        question = build_request_clarification_question(
            request_text=request.request_text,
            ambiguity=ambiguity,
            goal_candidate=candidate,
        )
        interrupt_id = self._id_factory()
        prompt_context = dict(cast(dict[str, object], state.get("prompt_context", {})))
        prompt_context.pop("confirmation_response", None)
        prompt_context["confirmation_interrupt"] = {
            "schema_version": 1,
            "interrupt_id": interrupt_id,
            "semantic_owner_id": "REQUEST_UNDERSTANDING",
            "origin_target": question["origin_target"],
        }
        return {
            "workflow_phase": WorkflowPhase.WAITING_CONFIRMATION.value,
            "user_interrupt": cast(
                UserInterruptV1,
                {
                    **build_user_interrupt_v1(question),
                    "interrupt_id": interrupt_id,
                },
            ),
            "prompt_context": prompt_context,
        }

    def _finalize_intent_node(
        self, state: RequestUnderstandingStateV2
    ) -> RequestUnderstandingStateV2:
        if state.get("prerequisite_message"):
            decision = finalize_supervisor_result(
                state=cast(GraphState, state),
                intent="COMPLETED",
                result_kind="PARTIAL",
                reason_code="CONNECTOR_PREREQUISITE_UNMET",
                prerequisite_message=state["prerequisite_message"],
            )
            return cast(
                RequestUnderstandingStateV2,
                self._merge_decision(
                    state,
                    {},
                    decision,
                ),
            )
        ambiguity = state.get("ambiguity_candidate")
        if ambiguity is None:
            raise ValueError("request-understanding ambiguity result is required")
        if ambiguity["requires_confirmation"]:
            confirmation_response, early_return_patch = self._confirm_inline(state)
            trace_context = self._trace(state, node_name="finalize_intent")
            if early_return_patch is not None:
                return cast(
                    RequestUnderstandingStateV2,
                    {
                        **early_return_patch,
                        "user_interrupt": None,
                        "trace_context": trace_context,
                    },
                )
            if confirmation_response is None:
                raise ValueError("request-understanding confirmation response is required")
            prompt_context = dict(cast(dict[str, object], state.get("prompt_context", {})))
            prompt_context["confirmation_response"] = dict(confirmation_response)
            prompt_context.pop("confirmation_interrupt", None)
            return {
                "final_intent": None,
                "user_interrupt": None,
                "prompt_context": prompt_context,
                "trace_context": trace_context,
            }

        patch = finalize_intent_node(state, id_factory=self._id_factory)
        intent = patch["request_intent"]
        output = {
            "schema_version": 1,
            "result": "COMPLETE",
            "request_intent": intent,
            "clarification": None,
            "failure": None,
            "validator_codes": [],
        }
        decision = route_supervisor(
            phase=WorkflowPhase.REQUEST_ANALYSIS,
            state=cast(GraphState, state),
            result=output,
        )
        request = request_from_run_input_state(cast(Any, state))
        update: GraphStateUpdateV1 = {
            "request_intent": intent,
            "workflow_phase": WorkflowPhase.REQUEST_ANALYSIS.value,
            "prompt_context": {
                "entry_mode": request.entry_mode,
                "selected_resource_ids": list(request.selected_resource_ids),
            },
            "trace_context": {
                "request_understanding_result": "COMPLETE",
                "validator_codes": [],
            },
        }
        traced_state = cast(
            RequestUnderstandingStateV2,
            {
                **state,
                **patch,
                "trace_context": self._trace(state, node_name="finalize_intent"),
            },
        )
        merged = self._merge_decision(traced_state, update, decision)
        merged["final_intent"] = intent
        return cast(RequestUnderstandingStateV2, merged)

    def _trace(
        self,
        state: RequestUnderstandingStateV2,
        *,
        node_name: str,
        llm_call_id: str | None = None,
        prompt_ref: Any = None,
        additional_prompt_refs: tuple[Any, ...] = (),
        llm_call_increment: int = 0,
        invocation_id: str | None = None,
        agent_invocation_increment: int = 0,
    ) -> dict[str, object]:
        resolved_invocation_id = invocation_id or self._invocation_id(state)
        if resolved_invocation_id is None:
            raise ValueError("request-understanding invocation id is required")
        return merge_trace_context(
            state,
            graph_profile=self._graph_profile.value,
            agent_subgraph_id="request_understanding",
            agent_role="request_understanding",
            agent_invocation_id=resolved_invocation_id,
            subgraph_namespace="request_understanding",
            node_name=node_name,
            llm_call_id=llm_call_id,
            prompt_ref=prompt_ref,
            additional_prompt_refs=additional_prompt_refs,
            agent_invocation_increment=agent_invocation_increment,
            llm_call_increment=llm_call_increment,
        )

    @staticmethod
    def _invocation_id(state: RequestUnderstandingStateV2) -> str | None:
        trace_context = state.get("trace_context", {})
        raw_log = trace_context.get("agent_node_log", [])
        if not isinstance(raw_log, list):
            return None
        for item in reversed(raw_log):
            if not isinstance(item, Mapping):
                continue
            if item.get("agent_subgraph_id") != "request_understanding":
                continue
            invocation_id = item.get("agent_invocation_id")
            if isinstance(invocation_id, str) and invocation_id:
                return invocation_id
        return None


__all__ = ["RequestUnderstandingSubgraph"]
