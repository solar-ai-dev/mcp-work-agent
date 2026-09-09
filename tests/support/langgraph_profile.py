"""Inputs shared by exact graph-profile architecture tests."""

from collections.abc import Callable
from typing import Any

from google_work_agent.adapters.langgraph.main.graph import (
    GraphNodeBindings,
    MainControlNodeBindings,
)
from google_work_agent.adapters.langgraph.main.state import GraphState


def profile_build_arguments() -> tuple[
    GraphNodeBindings,
    MainControlNodeBindings,
    Callable[[str], bool],
    Any,
    set[str],
]:
    def node(state: GraphState) -> dict[str, object]:
        del state
        return {}

    bindings = GraphNodeBindings(
        request_understanding=node,
        tool_route=node,
        context_retriever=node,
        work_analysis=node,
        planning=node,
        review=node,
        single_workflow=node,
        waiting_approval=node,
        stage_one=node,
        stage_two=node,
        stage_three=node,
    )
    controls = MainControlNodeBindings(
        initialize=node,
        retrieval_entry=node,
        planning_entry=node,
        review_entry=node,
        domain_validation=node,
        preflight=node,
        domain_reconcile=node,
        action_execution=node,
        verification=node,
        recovery=node,
        cancel_resolution=node,
        response_synthesis=node,
        terminal_commit=node,
        finalize=node,
    )
    return (
        bindings,
        controls,
        lambda _run_id: False,
        None,
        {
            "REQUEST_UNDERSTANDING",
            "TOOL_ROUTE",
            "RETRIEVAL",
            "WORK_ANALYSIS",
            "PLANNING",
            "REVIEW",
        },
    )
