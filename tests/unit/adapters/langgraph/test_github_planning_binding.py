from __future__ import annotations

from collections.abc import Mapping
from typing import Any, cast

import pytest

from google_work_agent.adapters.langgraph.subgraphs.planning.nodes import (
    compose_arguments_per_output_route_node as arguments_node,
)
from google_work_agent.application.agents.planning.contracts.planning_semantics import (
    PlanningSemanticInvoker,
)
from google_work_agent.application.agents.planning.resolve_default_container import (
    PlanningArgumentBindingError,
)
from google_work_agent.application.agents.request_understanding.contracts.request_intent import (
    RequestIntentV2,
)
from google_work_agent.application.use_cases.run.guard_run_budget import build_default_run_budget
from google_work_agent.ports.system.contracts.workflow_execution import (
    SelectedResourceRef,
    WorkflowCorrelationContext,
    WorkflowStartRequest,
)


@pytest.mark.parametrize("authority_source", ["explicit", "selected"])
def test_github_planning_node__validated_repository__binds_before_argument_writer(
    authority_source: str,
) -> None:
    repository = "acme/repo"
    selected = (_selected_issue(repository),) if authority_source == "selected" else ()
    intent = _intent(repository if authority_source == "explicit" else None)
    calls: list[Mapping[str, object]] = []

    def invoke(_prompt_id: str, prompt_input: Mapping[str, object]) -> Mapping[str, object]:
        calls.append(prompt_input)
        assert prompt_input["tool_schema"]["properties"]["repository"]["const"] == repository  # type: ignore[index]
        return {
            "schema_version": 1,
            "route_id": "route-1",
            "arguments": {"title": "Bug"},
            "evidence_refs": ["e1"],
        }

    result = arguments_node.compose_arguments_per_output_route_node(
        _state(intent=intent, selected=selected),
        invoke=cast(PlanningSemanticInvoker, invoke),
    )

    assert len(calls) == 1
    assert result["argument_candidates"][0]["arguments"]["repository"] == repository  # type: ignore[index]


def test_github_planning_node__missing_or_conflicting_authority__skips_writer() -> None:
    calls = 0

    def invoke(*_args: object) -> Mapping[str, object]:
        nonlocal calls
        calls += 1
        return {}

    with pytest.raises(PlanningArgumentBindingError, match="repository is required"):
        arguments_node.compose_arguments_per_output_route_node(
            _state(intent=_intent(None), selected=()),
            invoke=cast(PlanningSemanticInvoker, invoke),
        )
    with pytest.raises(PlanningArgumentBindingError, match="conflict"):
        arguments_node.compose_arguments_per_output_route_node(
            _state(
                intent=_intent("owner-a/repo"),
                selected=(_selected_issue("owner-b/repo"),),
            ),
            invoke=cast(PlanningSemanticInvoker, invoke),
        )

    assert calls == 0


def _state(
    *,
    intent: RequestIntentV2,
    selected: tuple[SelectedResourceRef, ...],
) -> dict[str, object]:
    route = {
        "route_id": "route-1",
        "resource_type": "GITHUB_ISSUE",
        "connector_id": "github",
        "effect": "CREATE",
        "selected_tool_id": "github_create_issue",
        "reason_codes": ["USER_REQUEST"],
    }
    return {
        "__request__": WorkflowStartRequest(
            run_id="run-1",
            conversation_id="conversation-1",
            workflow_key="thread-1",
            entry_mode="RESOURCE_SELECTED" if selected else "AGENT_SEARCH",
            requested_mode="AUTO",
            request_text="Create an issue",
            selected_resource_ids=tuple(item.resource_id for item in selected),
            run_budget=cast(dict[str, Any], build_default_run_budget()),
            correlation=WorkflowCorrelationContext("request-1", "command-1", "v1"),
            selected_resources=selected,
        ),
        "request_intent": intent,
        "output_plan": {"output_mode": "ACTION", "output_routes": [route]},
        "action_objective_candidates": [
            {
                "schema_version": 1,
                "route_id": "route-1",
                "objective": "Create issue",
                "target_semantics": "GITHUB_ISSUE",
                "scope_constraints": ["repository-bound"],
                "evidence_refs": ["e1"],
            }
        ],
        "evidence": [{"evidence_ref": "e1"}],
    }


def _intent(repository: str | None) -> RequestIntentV2:
    constraints: list[dict[str, object]] = []
    if repository is not None:
        constraints.append(
            {
                "kind": "RESOURCE",
                "field": "repository",
                "value": repository,
                "provenance": {
                    "source": "USER_REQUEST",
                    "start_offset": 0,
                    "end_offset": len(repository),
                },
            }
        )
    return cast(
        RequestIntentV2,
        {
            "schema_version": 2,
            "meta": {"artifact_id": "intent-1", "revision": 1, "based_on": []},
            "goal": "Create issue",
            "completion_conditions": ["Issue created"],
            "constraints": constraints,
            "requested_effect_hints": ["CREATE"],
            "requested_resource_hints": ["GITHUB_ISSUE"],
            "analysis_requirement": "NONE",
            "ambiguity": {
                "requires_confirmation": False,
                "reason_codes": [],
                "missing_fields": [],
            },
        },
    )


def _selected_issue(repository: str) -> SelectedResourceRef:
    return SelectedResourceRef(
        resource_ref_id="ref-1",
        connector_id="github",
        resource_type="github_issue",
        resource_id=f"{repository}#7",
        parent_resource_id=repository,
    )
