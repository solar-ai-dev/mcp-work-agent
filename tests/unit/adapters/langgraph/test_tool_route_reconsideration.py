"""Actual selection handoff with fake inference; not a semantic-model quality test."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from hashlib import sha256
from itertools import count
from pathlib import Path
from typing import Any, cast

import pytest
from tests.integration.langgraph.test_work_binding_connected_consumers import (
    _inputs,
    _merge,
    _unexpected_confirmation,
)
from tests.unit.adapters.langgraph.test_tool_selection_capability import _RecordingSelectionLLM
from tests.unit.application.agents.tool_routing.test_select_tool_if_needed import (
    RecordingLLMRuntime,
    _prompt_ref,
)

from google_work_agent.adapters.langgraph.main.state import initial_graph_state
from google_work_agent.adapters.langgraph.profiles.profile_registry import GraphProfile
from google_work_agent.adapters.langgraph.subgraphs.tool_routing.graph import ToolRoutingSubgraph
from google_work_agent.adapters.langgraph.subgraphs.tool_routing.nodes import (
    select_tool_if_needed_node as selection_node,
)
from google_work_agent.application.agents.tool_routing.contracts.route_binding_candidate import (
    BoundOutputRouteCandidateV1,
)
from google_work_agent.application.agents.tool_routing.select_tool_if_needed import (
    select_tool_if_needed,
)
from google_work_agent.application.agents.tool_routing.selection_reconsideration import (
    capture_selection_reconsideration,
    project_selection_reconsideration,
)
from google_work_agent.application.agents.tool_routing.validate_route import (
    ToolRouteValidationError,
)
from google_work_agent.application.prompt_runtime.prompt_registry import DEVELOPMENT_SMOKE
from google_work_agent.application.tool_registry.load_signed_tool_registry import (
    load_development_tool_registry,
)
from google_work_agent.application.use_cases.run.account_provider_dispatch import (
    provider_dispatch_execution_scope,
)


def _fixture() -> tuple[Any, Any, Any, Any]:
    request, intent = _inputs(action=True)
    parts = (
        "Update issue 10 from the selected mail.",
        "Update issue 20 separately from the selected mail.",
    )
    text = " ".join(parts)
    request = replace(request, request_text=text)
    intent["goal"] = text
    intent["completion_conditions"] = list(parts)
    intent["constraints"] = intent["constraints"][:1]
    for unit, part in zip(intent["requested_work"]["work_units"], parts, strict=True):
        unit["request_provenance"] = [
            {
                "source": "USER_REQUEST",
                "start_offset": text.index(part),
                "end_offset": text.index(part) + len(part),
                "source_text": part,
            }
        ]
    intent["requested_resource_hints"] = ["GMAIL_THREAD", "GITHUB_ISSUE"]
    intent["requested_effect_hints"] = ["READ", "UPDATE"]
    intent["resource_responsibilities"]["outputs"] = [
        {"resource_type": "GITHUB_ISSUE", "effect": "UPDATE", "work_unit_ids": [unit]}
        for unit in ("work-1", "work-2")
    ]
    # Fixed typed input; this gate evaluates handoff, not RU decomposition.
    sequence = count()
    llm = _RecordingSelectionLLM()
    graph = ToolRoutingSubgraph(
        llm_runtime=llm,
        tool_catalog=load_development_tool_registry(),
        prompt_manifest_path=None,
        prompt_execution_scope=DEVELOPMENT_SMOKE,
        graph_profile=GraphProfile.SIX_ROLE_BASELINE,
        merge_decision=_merge,
        confirm_inline=_unexpected_confirmation,
        id_factory=lambda: f"route-review-{next(sequence)}",
    ).build()
    state = initial_graph_state(
        request,
        graph_profile=GraphProfile.SIX_ROLE_BASELINE,
        graph_version="review-handoff-test",
        initial_target="tool_routing",
    )
    state["request_intent"] = intent
    return graph, state, intent, llm


def _review(plan: Any, *, affected: list[str] | None = None) -> Any:
    return {
        "schema_version": 2,
        "meta": {
            "artifact_id": "review-current",
            "revision": 1,
            "based_on": [{"artifact_id": "planning-current", "revision": 1}],
        },
        "status": "ROUTE_RECONSIDERATION",
        "route_issues": [
            {
                "code": "TOOL_OPERATION_MISMATCH",
                "description": "The selected tool cannot express the requested operation.",
                "affected_route_ids": affected
                if affected is not None
                else [plan["output_plan"]["output_routes"][1]["route_id"]],
            }
        ],
    }


def _capture(intent: Any, plan: Any, review: Any) -> Any:
    return capture_selection_reconsideration(
        request_intent=intent,
        previous_route_plan=plan,
        review=review,
        workflow_signal={"kind": "ROUTE_RECONSIDERATION_REQUIRED", "reason_codes": ["review"]},
    )


def _candidates(plan: Any) -> list[BoundOutputRouteCandidateV1]:
    return [
        BoundOutputRouteCandidateV1(
            route_id=f"new-{index}",
            connector_id=route["connector_id"],
            resource_type=route["resource_type"],
            effect=route["effect"],
            eligible_tool_ids=("github_close_issue", "github_update_issue"),
            work_unit_ids=tuple(route["work_unit_ids"]),
        )
        for index, route in enumerate(plan["output_plan"]["output_routes"])
    ]


def test_compiled_reconsideration_preserves_route_issues_and_shared_capability() -> None:
    graph, state, intent, llm = _fixture()
    before = deepcopy(intent)
    with provider_dispatch_execution_scope():
        initial = graph.invoke(state)
    prior = initial["tool_route_plan"]
    assert len(llm.calls) == 1
    initial_wire = deepcopy(llm.calls[0])
    assert set(initial_wire) == {"user_request", "route_candidate", "registered_candidates"}
    review = _review(prior)
    review_before = deepcopy(review)
    with provider_dispatch_execution_scope():
        revised = graph.invoke(
            {
                **state,
                "tool_route_plan": prior,
                "plan_review": review,
                "workflow_signal": {
                    "kind": "ROUTE_RECONSIDERATION_REQUIRED",
                    "reason_codes": ["review"],
                },
            }
        )
    assert len(llm.calls) == 2  # one selection for two routes, on each invocation
    feedback = cast(Any, llm.calls[1]["reconsideration"])
    current = revised["tool_route_plan"]["output_plan"]["output_routes"]
    assert [item["route_id"] for item in feedback["routes"]] == [r["route_id"] for r in current]
    assert [item["previous_route_id"] for item in feedback["routes"]] == [
        r["route_id"] for r in prior["output_plan"]["output_routes"]
    ]
    assert [item["work_unit_ids"] for item in feedback["routes"]] == [["work-1"], ["work-2"]]
    assert feedback["routes"][0]["issues"] == []
    assert feedback["routes"][1]["issues"] == review["route_issues"]
    assert review == review_before
    assert revised["request_intent"] == intent == before
    reads = revised["tool_route_plan"]["input_plan"]["input_routes"]
    assert len(reads) == 1 and reads[0]["work_unit_ids"] == ["work-1", "work-2"]
    assert len(current) == 2


@pytest.mark.parametrize("change", ["route_id", "intent_revision", "ambiguous_binding"])
def test_unknown_or_ambiguous_reconsideration_binding_fails_closed(change: str) -> None:
    graph, state, intent, _ = _fixture()
    with provider_dispatch_execution_scope():
        plan = graph.invoke(state)["tool_route_plan"]
    review = _review(plan)
    if change == "route_id":
        review["route_issues"][0]["affected_route_ids"] = ["stale-route"]
    elif change == "intent_revision":
        intent["meta"]["revision"] += 1
    else:
        plan["output_plan"]["output_routes"][1]["work_unit_ids"] = ["work-1"]
    with pytest.raises(ToolRouteValidationError):
        context = _capture(intent, plan, review)
        project_selection_reconsideration(context=context, candidates=_candidates(plan))


def test_input_only_issue_does_not_change_output_selection_context() -> None:
    graph, state, intent, _ = _fixture()
    with provider_dispatch_execution_scope():
        plan = graph.invoke(state)["tool_route_plan"]
    review = _review(plan, affected=[plan["input_plan"]["input_routes"][0]["route_id"]])
    assert (
        project_selection_reconsideration(
            context=_capture(intent, plan, review), candidates=_candidates(plan)
        )
        is None
    )


def test_initial_and_non_route_review_do_not_leak_stale_feedback() -> None:
    graph, state, intent, _ = _fixture()
    with provider_dispatch_execution_scope():
        plan = graph.invoke(state)["tool_route_plan"]
    review = _review(plan)
    assert (
        capture_selection_reconsideration(
            request_intent=intent,
            previous_route_plan=plan,
            review=review,
            workflow_signal=None,
        )
        is None
    )
    review = {**review, "status": "PASS"}
    assert _capture(intent, plan, review) is None


def test_request_semantic_error_is_context_not_permission_to_rewrite_intent() -> None:
    graph, state, intent, _ = _fixture()
    with provider_dispatch_execution_scope():
        prior = graph.invoke(state)["tool_route_plan"]
    review = _review(prior, affected=[])
    review["route_issues"][0]["description"] = "The request was READ, not UPDATE."
    before = deepcopy(intent)
    with provider_dispatch_execution_scope():
        after = graph.invoke(
            {
                **state,
                "tool_route_plan": prior,
                "plan_review": review,
                "workflow_signal": {"kind": "ROUTE_RECONSIDERATION_REQUIRED", "reason_codes": []},
            }
        )
    assert intent == after["request_intent"] == before
    assert [
        route["effect"] for route in after["tool_route_plan"]["output_plan"]["output_routes"]
    ] == ["UPDATE", "UPDATE"]


def test_initial_selection_prompt_source_is_byte_identical() -> None:
    source = Path("src/google_work_agent/application/prompt_runtime/sources/") / (
        "tool_routing.select_tool_if_needed.md"
    )
    assert sha256(source.read_bytes()).hexdigest() == (
        "cd482c0ef2acd6343bd6ad347218e5ece52343c903ace855fe9b0602ccee7154"
    )


def test_single_candidate_feedback_does_not_add_call_or_change_output_semantics() -> None:
    graph, state, intent, _ = _fixture()
    with provider_dispatch_execution_scope():
        plan = graph.invoke(state)["tool_route_plan"]
    candidates = [
        replace(candidate, eligible_tool_ids=("github_update_issue",))
        for candidate in _candidates(plan)
    ]
    llm = _RecordingSelectionLLM()
    context = _capture(intent, plan, _review(plan))
    with provider_dispatch_execution_scope():
        result = selection_node.select_tool_if_needed_node(
            {**state, "registry_candidates": candidates, "selection_reconsideration": context},
            llm_runtime=llm,
            prompt_ref=None,
        )
    assert llm.calls == []
    assert len(result["bound_output_routes"]) == 2
    assert [route["work_unit_ids"] for route in result["bound_output_routes"]] == [
        ["work-1"],
        ["work-2"],
    ]
    assert all(route["effect"] == "UPDATE" for route in result["bound_output_routes"])


def test_bounded_selection_repair_preserves_reconsideration_exactly() -> None:
    graph, state, intent, _ = _fixture()
    with provider_dispatch_execution_scope():
        plan = graph.invoke(state)["tool_route_plan"]
    candidates = _candidates(plan)
    feedback = project_selection_reconsideration(
        context=_capture(intent, plan, _review(plan)),
        candidates=candidates,
    )
    candidate = candidates[0]
    llm = RecordingLLMRuntime(
        outputs=[
            {"schema_version": 1, "route_id": candidate.route_id, "selected_tool_id": "unknown"},
            {
                "schema_version": 1,
                "route_id": candidate.route_id,
                "selected_tool_id": candidate.eligible_tool_ids[0],
            },
        ]
    )
    with provider_dispatch_execution_scope():
        selected, _ = select_tool_if_needed(
            llm_runtime=llm,
            route_id=candidate.route_id,
            connector_id=candidate.connector_id,
            resource_type=candidate.resource_type,
            effect=candidate.effect,
            eligible_tool_ids=candidate.eligible_tool_ids,
            request=state["__request__"],
            retry_budget=state["retry_budget"],
            prompt_ref=_prompt_ref(),
            reconsideration=feedback,
        )
    assert selected == candidate.eligible_tool_ids[0]
    assert len(llm.calls) == 2
    assert llm.calls[0]["prompt_input"]["reconsideration"] == feedback
    assert llm.calls[1]["prompt_input"]["base_projection"] == llm.calls[0]["prompt_input"]
