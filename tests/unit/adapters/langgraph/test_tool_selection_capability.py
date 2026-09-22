from __future__ import annotations

from collections.abc import Mapping
from typing import Literal, cast

from google_work_agent.adapters.langgraph.subgraphs.tool_routing.nodes import (
    select_tool_if_needed_node,
)
from google_work_agent.adapters.langgraph.subgraphs.tool_routing.state import ToolRouteStateV1
from google_work_agent.application.agents.tool_routing.contracts.route_binding_candidate import (
    BoundOutputRouteCandidateV1,
)
from google_work_agent.application.use_cases.run.account_provider_dispatch import (
    provider_dispatch_execution_scope,
)
from google_work_agent.application.use_cases.run.guard_run_budget import build_default_run_budget
from google_work_agent.ports.llm.structured_inference_contracts import (
    OutputSchemaDefinition,
    PromptReference,
)
from google_work_agent.ports.llm.structured_inference_port import StructuredInferenceResultV1
from google_work_agent.ports.system.contracts.workflow_execution import (
    WorkflowCorrelationContext,
    WorkflowStartRequest,
)


class _RecordingSelectionLLM:
    def __init__(self) -> None:
        self.calls: list[Mapping[str, object]] = []
        self.input_tokens = 0
        self.output_tokens = 0
        self.latency_ms = 0

    def infer(
        self,
        requested_mode: Literal["AUTO", "LOCAL_GPU", "API_LLM"],
        prompt_ref: PromptReference,
        input_projection: Mapping[str, object],
        output_schema_ref: OutputSchemaDefinition,
    ) -> StructuredInferenceResultV1:
        del requested_mode, prompt_ref, output_schema_ref
        self.calls.append(input_projection)
        self.input_tokens += 12
        self.output_tokens += 4
        self.latency_ms += 25
        candidate = cast(Mapping[str, str], input_projection["route_candidate"])
        tools = cast(list[Mapping[str, str]], input_projection["registered_candidates"])
        return StructuredInferenceResultV1(
            schema_version=1,
            structured_output={
                "schema_version": 1,
                "route_id": candidate["route_id"],
                "selected_tool_id": tools[0]["tool_id"],
            },
            provider="fake",
            model="fake",
            actual_runtime="API_LLM",
            input_tokens=12,
            output_tokens=4,
            latency_ms=25,
            fallback_reason=None,
        )


def _candidate(
    route_id: str,
    work_unit_id: str,
    *,
    connector_id: str = "github",
    resource_type: str = "GITHUB_ISSUE",
    effect: Literal["CREATE", "UPDATE"] = "UPDATE",
    eligible_tool_ids: tuple[str, ...] = ("github_close_issue", "github_update_issue"),
) -> BoundOutputRouteCandidateV1:
    return BoundOutputRouteCandidateV1(
        route_id=route_id,
        connector_id=connector_id,
        resource_type=resource_type,
        effect=effect,
        eligible_tool_ids=eligible_tool_ids,
        work_unit_ids=(work_unit_id,),
    )


def _select(
    candidates: list[BoundOutputRouteCandidateV1],
) -> tuple[ToolRouteStateV1, _RecordingSelectionLLM]:
    llm = _RecordingSelectionLLM()
    request = WorkflowStartRequest(
        run_id="run-1",
        conversation_id="conversation-1",
        workflow_key="thread-1",
        entry_mode="AGENT_SEARCH",
        requested_mode="AUTO",
        request_text="perform the requested independent work",
        selected_resource_ids=(),
        run_budget=build_default_run_budget(),
        correlation=WorkflowCorrelationContext("request-1", "command-1", "v1"),
    )
    state = cast(
        ToolRouteStateV1,
        {
            "__request__": request,
            "registry_candidates": candidates,
            "retry_budget": build_default_run_budget(),
        },
    )
    prompt_ref = PromptReference(
        prompt_bundle_version="test",
        prompt_id="tool_routing.select_tool_if_needed",
        prompt_version="1",
        content_hash="test",
        agent_role="tool_routing",
        subgraph_name="tool_routing",
        node_name="select_tool_if_needed",
        node_state="INITIAL",
        purpose="select_tool_if_needed",
        input_schema_version="v1",
        output_schema_version="v1",
    )
    with provider_dispatch_execution_scope():
        result = select_tool_if_needed_node.select_tool_if_needed_node(
            state, llm_runtime=llm, prompt_ref=prompt_ref
        )
    return result, llm


def test_identical_registry_capability_selects_once_and_fans_out_route_identity() -> None:
    result, llm = _select([_candidate("route-1", "work-1"), _candidate("route-2", "work-2")])
    routes = result["bound_output_routes"]
    assert [route["route_id"] for route in routes] == ["route-1", "route-2"]
    assert [route["work_unit_ids"] for route in routes] == [["work-1"], ["work-2"]]
    assert [route["selected_tool_id"] for route in routes] == ["github_close_issue"] * 2
    assert len(llm.calls) == 1
    assert (llm.input_tokens, llm.output_tokens, llm.latency_ms) == (12, 4, 25)


def test_single_candidate_is_deterministic_across_independent_routes() -> None:
    result, llm = _select(
        [
            _candidate("route-1", "work-1", eligible_tool_ids=("github_create_issue",)),
            _candidate("route-2", "work-2", eligible_tool_ids=("github_create_issue",)),
        ]
    )
    assert len(result["bound_output_routes"]) == 2
    assert all(
        route["reason_codes"] == ["REGISTRY_SINGLE_CANDIDATE"]
        for route in result["bound_output_routes"]
    )
    assert not llm.calls


def test_distinct_registry_capabilities_select_independently() -> None:
    result, llm = _select(
        [
            _candidate("route-1", "work-1"),
            _candidate(
                "route-2", "work-2", resource_type="GMAIL_DRAFT",
                connector_id="google_workspace",
                eligible_tool_ids=("gmail_update_draft", "gmail_replace_draft"),
            ),
        ]
    )
    assert len(result["bound_output_routes"]) == 2
    assert [route["selected_tool_id"] for route in result["bound_output_routes"]] == [
        "github_close_issue", "gmail_update_draft"
    ]
    assert len(llm.calls) == 2
    assert (llm.input_tokens, llm.output_tokens, llm.latency_ms) == (24, 8, 50)


def test_different_eligible_sets_do_not_share_selection_even_for_same_resource_effect() -> None:
    _, llm = _select(
        [
            _candidate("route-1", "work-1"),
            _candidate(
                "route-2", "work-2",
                eligible_tool_ids=("github_update_issue", "github_reopen_issue"),
            ),
        ]
    )
    assert len(llm.calls) == 2
