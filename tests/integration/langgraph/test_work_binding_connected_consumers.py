"""Typed binding integration; fake semantics/Connector, not model-quality evidence.

Tool Routing and Planning are compiled Product subgraphs. Retrieval uses its real
query/read/finalization operations; selection and acquisition are explicit fixtures.
"""

from __future__ import annotations

from copy import deepcopy
from itertools import count
from typing import Any, cast

import pytest
from tests.support.context_retrieval import (
    SUFFICIENCY_PROMPT_REF,
    acquisition_result,
    request_intent,
    selection_output,
    sufficiency_result_fixture,
)
from tests.support.fakes.llm import FakeStructuredInferencePort

from google_work_agent.adapters.langgraph.main.state import initial_graph_state
from google_work_agent.adapters.langgraph.profiles.profile_registry import GraphProfile
from google_work_agent.adapters.langgraph.subgraphs.planning.graph import (
    PlanningRuntimeDependencies,
    PlanningSubgraph,
)
from google_work_agent.adapters.langgraph.subgraphs.retrieval.projections import (
    execute_read_projection,
)
from google_work_agent.adapters.langgraph.subgraphs.tool_routing.graph import ToolRoutingSubgraph
from google_work_agent.adapters.system.memory.run_retrieval_cache import InMemoryRunRetrievalCache
from google_work_agent.application.agents.retrieval.build_query import (
    RouteConstraintPolicy,
    build_query,
)
from google_work_agent.application.agents.retrieval.contracts.query_plan_schema import (
    RETRIEVAL_QUERY_PLAN_V2_OUTPUT_SCHEMA,
)
from google_work_agent.application.agents.retrieval.execute_read import execute_read
from google_work_agent.application.agents.retrieval.finalize_retrieval import finalize_retrieval
from google_work_agent.application.agents.retrieval.plan_query import plan_query
from google_work_agent.application.prompt_runtime.prompt_registry import DEVELOPMENT_SMOKE
from google_work_agent.application.tool_registry.load_signed_tool_registry import (
    load_development_tool_registry,
)
from google_work_agent.application.use_cases.run.account_provider_dispatch import (
    provider_dispatch_execution_scope,
)
from google_work_agent.application.use_cases.run.guard_run_budget import build_default_run_budget
from google_work_agent.ports.connector.connector_read_port import ConnectorReadResultV1
from google_work_agent.ports.system.contracts.workflow_execution import (
    SelectedResourceRef,
    WorkflowCorrelationContext,
    WorkflowStartRequest,
)


def _merge(state: Any, update: Any, decision: Any) -> Any:
    return {**state, **update, **decision["state_update"], "__target__": decision["target"]}


def _unexpected_confirmation(_state: Any) -> Any:
    raise AssertionError("complete typed test input must not require confirmation")


class _Reader:
    def __init__(self) -> None:
        self.calls: list[Any] = []
        self.body = "The shared project deadline is Friday."

    def execute_read(self, binding: Any, arguments: Any) -> ConnectorReadResultV1:
        assert binding.effect == "READ"
        self.calls.append((binding.tool_id, deepcopy(arguments)))
        return ConnectorReadResultV1(
            1,
            binding.tool_id,
            "test-read",
            {"item": {"resource_id": "thread-kim", "body": self.body}},
            None,
            1,
        )


def _inputs(action: bool) -> tuple[Any, Any]:
    parts = (
        (
            "Prepare a draft for first@example.test from the selected mail.",
            "Prepare a separate draft for second@example.test from the selected mail.",
        )
        if action
        else (
            "Summarize the selected mail.",
            "List the deadline information in the selected mail.",
        )
    )
    text = " ".join(parts)
    request = WorkflowStartRequest(
        run_id="binding-test",
        conversation_id="test",
        workflow_key="test",
        entry_mode="RESOURCE_SELECTED",
        requested_mode="LOCAL_GPU",
        request_text=text,
        selected_resource_ids=("thread-kim",),
        selected_resources=(
            SelectedResourceRef("selected-1", "google_workspace", "gmail_thread", "thread-kim"),
        ),
        correlation=WorkflowCorrelationContext("test", "test", "v1"),
        run_budget=build_default_run_budget(started_at_ms=1000),
    )
    intent = cast(Any, deepcopy(request_intent()))
    intent.update(
        goal=text,
        analysis_requirement="NONE",
        requested_effect_hints=["READ", "CREATE"] if action else ["READ"],
    )
    intent["requested_resource_hints"] = (
        ["GMAIL_THREAD", "GMAIL_DRAFT"] if action else ["GMAIL_THREAD"]
    )
    intent["requested_work"] = {
        "work_units": [
            {
                "unit_id": unit,
                "request_provenance": [
                    {
                        "source": "USER_REQUEST",
                        "start_offset": text.index(part),
                        "end_offset": text.index(part) + len(part),
                        "source_text": part,
                    }
                ],
            }
            for unit, part in zip(("work-1", "work-2"), parts, strict=True)
        ],
        "work_relations": [],
    }
    intent["constraints"] = [
        {
            "kind": "SCOPE",
            "field": "required_sources",
            "value": "EMAIL",
            "work_unit_ids": ["work-1", "work-2"],
        },
        *[
            {
                "kind": "PERSON",
                "field": "recipient",
                "value": address,
                "work_unit_ids": [unit],
            }
            for unit, address in (
                ("work-1", "first@example.test"),
                ("work-2", "second@example.test"),
            )
            if action
        ],
    ]
    intent["resource_responsibilities"] = {
        "source_reads": [
            {
                "resource_type": "GMAIL_THREAD",
                "required_information": ["message_history"],
                "target_scope": "SINGULAR",
                "work_unit_ids": [unit],
            }
            for unit in ("work-1", "work-2")
        ],
        "outputs": [
            {"resource_type": "GMAIL_DRAFT", "effect": "CREATE", "work_unit_ids": [unit]}
            for unit in ("work-1", "work-2")
        ]
        if action
        else [],
    }
    return request, intent


@pytest.mark.parametrize("action", [False, True], ids=["shared-answer", "independent-drafts"])
def test_work_bindings_reach_read_and_compiled_planning_without_duplicate_dispatch(
    action: bool,
) -> None:
    request, intent = _inputs(action)
    registry = load_development_tool_registry()
    llm = FakeStructuredInferencePort(outputs=[])
    sequence = count()
    route_graph = ToolRoutingSubgraph(
        llm_runtime=llm,
        tool_catalog=registry,
        prompt_manifest_path=None,
        prompt_execution_scope=DEVELOPMENT_SMOKE,
        graph_profile=GraphProfile.SIX_ROLE_BASELINE,
        merge_decision=_merge,
        confirm_inline=_unexpected_confirmation,
        id_factory=lambda: f"route-artifact-{next(sequence)}",
    ).build()
    state = initial_graph_state(
        request,
        graph_profile=GraphProfile.SIX_ROLE_BASELINE,
        graph_version="binding-test",
        initial_target="tool_routing",
    )
    state["request_intent"] = intent
    with provider_dispatch_execution_scope():
        routed = route_graph.invoke(state)
    route_plan = routed["tool_route_plan"]
    routes = route_plan["input_plan"]["input_routes"]
    assert len(routes) == 1
    assert routes[0]["work_unit_ids"] == ["work-1", "work-2"]
    assert not llm.calls
    route_id = routes[0]["route_id"]
    policy = {route_id: RouteConstraintPolicy(frozenset({"RESOURCE_REF"}))}
    references = {route_id: ["gmail_thread:thread-kim"]}
    if action:
        llm.outputs.append(
            {
                "schema_version": 3,
                "route_queries": [
                    {
                        "route_id": route_id,
                        "operation": "DETAIL_FETCH",
                        "reason_codes": ["RESOURCE_SELECTED"],
                        "search_spec": None,
                        "detail_candidate_ref": "gmail_thread:thread-kim",
                    }
                ],
            }
        )
    query, budget, invoked = plan_query(
        llm_runtime=llm,
        prompt_ref=SUFFICIENCY_PROMPT_REF,
        revision_prompt_ref=SUFFICIENCY_PROMPT_REF,
        output_schema=RETRIEVAL_QUERY_PLAN_V2_OUTPUT_SCHEMA,
        prompt_input={"request_intent": intent, "input_routes": routes},
        requested_mode="LOCAL_GPU",
        frozen_routes=routes,
        route_policies=policy,
        retry_budget=request.run_budget,
        validated_resource_refs=references,
    )
    assert invoked is action
    fetches = build_query(
        query, frozen_routes=routes, route_policies=policy, validated_resource_refs=references
    )
    assert len(fetches) == 1
    reader = _Reader()
    cache = InMemoryRunRetrievalCache()
    tool, arguments = execute_read_projection.project_connector_call(
        fetches[0],
        route=routes[0],
        page_size=20,
        detail_resource={
            "resource_type": "gmail_thread",
            "resource_id": "thread-kim",
            "parent_id": None,
        },
    )
    read = execute_read(
        plan=fetches[0],
        run_id=request.run_id,
        binding=registry.bind_required("google_workspace", tool, "READ"),
        tool_arguments=cast(Any, arguments),
        connector_reader=reader,
        read_result_cache=cache,
        read_result_handle="read-1",
        run_budget=budget,
        now_ms=1000,
        prior_query_attempts=[],
    )
    assert read.provider_called
    assert reader.calls == [("gmail_get_thread", {"thread_id": "thread-kim"})]
    evidence = [
        {
            "schema_version": 1,
            "evidence_id": "e-shared",
            "resource_handle": "gmail_thread:thread-kim",
            "segment_id": "segment-1",
            "kind": "excerpt",
            "excerpt": reader.body,
            "locator": {},
            "reason_codes": ["SUPPORTS"],
        }
    ]
    retrieval = finalize_retrieval(
        artifact_id="retrieval-shared",
        request_intent=intent,
        tool_route_plan=route_plan,
        acquisition_result=acquisition_result(),
        selection_result=selection_output(["segment-1"]),
        evidence_drafts=cast(Any, evidence),
        sufficiency_result=sufficiency_result_fixture("SUFFICIENT"),
        current_round_no=0,
    )
    expected_binding = [
        {"work_unit_id": unit, "evidence_refs": ["e-shared"]} for unit in ("work-1", "work-2")
    ]
    assert retrieval["evidence_by_work_unit"] == expected_binding
    assert retrieval["evidence_refs"] == ["e-shared"]
    planning_calls: list[Any] = []

    def invoke(prompt_id: str, prompt_input: Any) -> Any:
        projection = prompt_input
        planning_calls.append((prompt_id, deepcopy(projection)))
        if not action:
            assert prompt_id == "planning.compose_answer"
            assert projection["evidence_by_work_unit"] == expected_binding
            assert len(projection["evidence"]) == 1
            return {
                "schema_version": 2,
                "answer": "The shared deadline is Friday.",
                "evidence_refs": ["e-shared"],
            }
        route = projection["output_route"]
        units = route["work_unit_ids"]
        assert len(units) == 1
        constraints = projection["request_intent"]["constraints"]
        recipients = [item["value"] for item in constraints if item["field"] == "recipient"]
        expected = "first@example.test" if units == ["work-1"] else "second@example.test"
        assert recipients == [expected]
        assert len(projection["evidence"]) == 1
        if prompt_id == "planning.draft_action_objective_per_output_route":
            return {
                "schema_version": 1,
                "objective": "Prepare this independent draft",
                "scope_constraints": [],
                "evidence_refs": ["e-shared"],
            }
        assert prompt_id == "planning.compose_arguments_per_output_route"
        return {
            "schema_version": 1,
            "route_id": route["route_id"],
            "arguments": {
                "payload": {"to": [expected], "subject": "Deadline", "body": reader.body}
            },
            "evidence_refs": ["e-shared"],
        }

    planning = PlanningSubgraph(dependencies=PlanningRuntimeDependencies(invoke=invoke)).build()
    planned = planning.invoke(
        {
            "user_request": request.request_text,
            "request_intent": intent,
            "tool_route_plan": route_plan,
            "retrieval_result": retrieval,
            "evidence": evidence,
        }
    )
    if action:
        outputs = route_plan["output_plan"]["output_routes"]
        assert len(outputs) == 2
        assert outputs[0]["route_id"] != outputs[1]["route_id"]
        assert [item["work_unit_ids"] for item in outputs] == [["work-1"], ["work-2"]]
        actions = planned["final_result"]["actions"]
        assert len(actions) == 2
        assert [item["arguments"]["payload"]["to"] for item in actions] == [
            ["first@example.test"],
            ["second@example.test"],
        ]
        assert len(planning_calls) == 4
    else:
        assert planned["planning_disposition"] == "ANSWER"
        assert len(planning_calls) == 1
    assert len(reader.calls) == 1
