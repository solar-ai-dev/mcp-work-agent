from collections.abc import Mapping
from typing import cast

import pytest

from google_work_agent.application.agents.planning.compose_arguments_per_output_route import (
    compose_arguments_per_output_route,
)
from google_work_agent.application.agents.planning.contracts.planning_semantics import (
    PlanningSemanticInvoker,
)
from google_work_agent.application.agents.planning.contracts.planning_tool_schema import (
    planning_tool_argument_schema,
)
from google_work_agent.application.agents.planning.resolve_default_container import (
    PlanningArgumentBindingError,
    resolve_default_container,
)
from google_work_agent.application.agents.request_understanding.contracts.request_intent import (
    RequestIntentV2,
)

ROUTE = {
    "route_id": "r1",
    "resource_type": "TASK",
    "connector_id": "google_workspace",
    "effect": "CREATE",
    "selected_tool_id": "tasks_create_task",
    "reason_codes": [],
}
OBJECTIVE = {
    "schema_version": 1,
    "route_id": "r1",
    "objective": "Create task",
    "target_semantics": "TASK",
    "scope_constraints": ["create only"],
    "evidence_refs": ["e1"],
}


def test_argument_prompt__receives_only_selected__bound_tool_schema() -> None:
    bound = resolve_default_container(
        route=ROUTE,  # type: ignore[arg-type]
        selected_tool_schema=planning_tool_argument_schema("tasks_create_task"),
        explicit_container_id="list-1",
    )

    def invoke(_prompt_id: str, prompt_input: Mapping[str, object]) -> Mapping[str, object]:
        assert set(prompt_input) == {"output_route", "action_objective", "tool_schema", "evidence"}
        assert prompt_input["tool_schema"]["properties"]["task_list_id"]["const"] == "list-1"  # type: ignore[index]
        return {
            "schema_version": 1,
            "route_id": "r1",
            "arguments": {"payload": {"title": "Report"}},
            "evidence_refs": ["e1"],
        }

    result = compose_arguments_per_output_route(
        [ROUTE],
        objectives=[OBJECTIVE],  # type: ignore[list-item]
        bound_tool_schemas=[bound],
        evidence=[{"evidence_ref": "e1"}],
        invoke=cast(PlanningSemanticInvoker, invoke),
    )
    assert result[0]["arguments"]["task_list_id"] == "list-1"


def test_argument_candidate__cannot_override__bound_container() -> None:
    bound = resolve_default_container(
        route=ROUTE,  # type: ignore[arg-type]
        selected_tool_schema=planning_tool_argument_schema("tasks_create_task"),
        explicit_container_id="list-1",
    )
    with pytest.raises(PlanningArgumentBindingError, match="immutable"):
        compose_arguments_per_output_route(
            [ROUTE],
            objectives=[OBJECTIVE],  # type: ignore[list-item]
            bound_tool_schemas=[bound],
            evidence=[{"evidence_ref": "e1"}],
            invoke=lambda *_: {
                "schema_version": 1,
                "route_id": "r1",
                "arguments": {"task_list_id": "other", "payload": {"title": "Report"}},
                "evidence_refs": ["e1"],
            },
        )


@pytest.mark.parametrize(
    ("tool_id", "effect", "business_arguments"),
    [
        ("github_create_issue", "CREATE", {"title": "Bug"}),
        ("github_update_issue", "UPDATE", {"issue_number": 7, "title": "Fixed"}),
        ("github_close_issue", "UPDATE", {"issue_number": 7}),
        ("github_reopen_issue", "UPDATE", {"issue_number": 7}),
    ],
)
def test_github_argument_omission__immutable_repository__is_injected(
    tool_id: str,
    effect: str,
    business_arguments: dict[str, object],
) -> None:
    route = _github_route(tool_id, effect)
    bound = resolve_default_container(
        route=route,  # type: ignore[arg-type]
        selected_tool_schema=planning_tool_argument_schema(tool_id),
        request_intent=_github_intent("acme/repo"),
    )

    result = compose_arguments_per_output_route(
        [route],
        objectives=[_github_objective()],  # type: ignore[list-item]
        bound_tool_schemas=[bound],
        evidence=[{"evidence_ref": "e1"}],
        invoke=lambda *_: {
            "schema_version": 1,
            "route_id": "r1",
            "arguments": business_arguments,
            "evidence_refs": ["e1"],
        },
    )

    assert result[0]["arguments"]["repository"] == "acme/repo"


def test_github_argument_match__same_repository__is_accepted() -> None:
    route = _github_route("github_create_issue", "CREATE")
    bound = resolve_default_container(
        route=route,  # type: ignore[arg-type]
        selected_tool_schema=planning_tool_argument_schema("github_create_issue"),
        request_intent=_github_intent("acme/repo"),
    )

    result = compose_arguments_per_output_route(
        [route],
        objectives=[_github_objective()],  # type: ignore[list-item]
        bound_tool_schemas=[bound],
        evidence=[{"evidence_ref": "e1"}],
        invoke=lambda *_: {
            "schema_version": 1,
            "route_id": "r1",
            "arguments": {"repository": "acme/repo", "title": "Bug"},
            "evidence_refs": ["e1"],
        },
    )

    assert result[0]["arguments"]["repository"] == "acme/repo"


@pytest.mark.parametrize(
    ("tool_id", "effect", "business_arguments"),
    [
        ("github_create_issue", "CREATE", {"title": "Bug"}),
        ("github_update_issue", "UPDATE", {"issue_number": 7, "title": "Fixed"}),
        ("github_close_issue", "UPDATE", {"issue_number": 7}),
        ("github_reopen_issue", "UPDATE", {"issue_number": 7}),
    ],
)
def test_github_argument_conflict_or_repair__immutable_repository__cannot_change(
    tool_id: str,
    effect: str,
    business_arguments: dict[str, object],
) -> None:
    route = _github_route(tool_id, effect)
    bound = resolve_default_container(
        route=route,  # type: ignore[arg-type]
        selected_tool_schema=planning_tool_argument_schema(tool_id),
        request_intent=_github_intent("owner-a/repo"),
    )

    with pytest.raises(PlanningArgumentBindingError, match="immutable repository"):
        compose_arguments_per_output_route(
            [route],
            objectives=[_github_objective()],  # type: ignore[list-item]
            bound_tool_schemas=[bound],
            evidence=[{"evidence_ref": "e1"}],
            invoke=lambda *_: {
                "schema_version": 1,
                "route_id": "r1",
                "arguments": {**business_arguments, "repository": "owner-b/repo"},
                "evidence_refs": ["e1"],
            },
        )


def test_bound_repository__frozen_resource_identity__cannot_change() -> None:
    route = _github_route("github_create_issue", "CREATE")
    bound = resolve_default_container(
        route=route,  # type: ignore[arg-type]
        selected_tool_schema=planning_tool_argument_schema("github_create_issue"),
        request_intent=_github_intent("acme/repo"),
    )
    bound["resource_type"] = "TASK"

    with pytest.raises(ValueError, match="frozen route identity"):
        compose_arguments_per_output_route(
            [route],
            objectives=[_github_objective()],  # type: ignore[list-item]
            bound_tool_schemas=[bound],
            evidence=[{"evidence_ref": "e1"}],
            invoke=lambda *_: {},
        )


def _github_route(tool_id: str, effect: str) -> dict[str, object]:
    return {
        "route_id": "r1",
        "resource_type": "GITHUB_ISSUE",
        "connector_id": "github",
        "effect": effect,
        "selected_tool_id": tool_id,
        "reason_codes": [],
    }


def _github_objective() -> dict[str, object]:
    return {
        "schema_version": 1,
        "route_id": "r1",
        "objective": "Mutate issue",
        "target_semantics": "GITHUB_ISSUE",
        "scope_constraints": ["repository-bound"],
        "evidence_refs": ["e1"],
    }


def _github_intent(repository: str) -> RequestIntentV2:
    return cast(
        RequestIntentV2,
        {
            "schema_version": 2,
            "meta": {"artifact_id": "intent-1", "revision": 1, "based_on": []},
            "goal": "Mutate issue",
            "completion_conditions": ["Issue mutated"],
            "constraints": [
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
            ],
            "requested_effect_hints": ["UPDATE"],
            "requested_resource_hints": ["GITHUB_ISSUE"],
            "analysis_requirement": "NONE",
            "ambiguity": {
                "requires_confirmation": False,
                "reason_codes": [],
                "missing_fields": [],
            },
        },
    )
