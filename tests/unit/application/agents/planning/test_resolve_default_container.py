from __future__ import annotations

from typing import cast

import pytest

from google_work_agent.application.agents.planning.contracts.planning_tool_schema import (
    planning_tool_argument_schema,
)
from google_work_agent.application.agents.planning.resolve_default_container import (
    RequiredContainerUnresolvedError,
    resolve_default_container,
)
from google_work_agent.application.agents.request_understanding.contracts.request_intent import (
    RequestIntentV2,
)


def _route() -> dict[str, object]:
    return {
        "route_id": "r1",
        "resource_type": "TASK",
        "connector_id": "google_workspace",
        "effect": "CREATE",
        "selected_tool_id": "tasks_create_task",
        "reason_codes": [],
    }


def test_explicit_container__wins_and__is_const_bound() -> None:
    result = resolve_default_container(
        route=_route(),  # type: ignore[arg-type]
        selected_tool_schema=planning_tool_argument_schema("tasks_create_task"),
        explicit_container_id="explicit",
        default_tasklist_id_provider=lambda: "default",
    )
    assert result["immutable_arguments"] == {"task_list_id": "explicit"}
    assert result["argument_schema"]["properties"]["task_list_id"]["const"] == "explicit"  # type: ignore[index]


def test_required_container__without_source__fails_before_prompt() -> None:
    with pytest.raises(RequiredContainerUnresolvedError):
        resolve_default_container(
            route=_route(),  # type: ignore[arg-type]
            selected_tool_schema=planning_tool_argument_schema("tasks_create_task"),
        )


@pytest.mark.parametrize(
    "tool_id",
    [
        "github_create_issue",
        "github_update_issue",
        "github_close_issue",
        "github_reopen_issue",
    ],
)
def test_github_repository__existing_resolver__const_binds(tool_id: str) -> None:
    result = resolve_default_container(
        route=_github_route(tool_id),  # type: ignore[arg-type]
        selected_tool_schema=planning_tool_argument_schema(tool_id),
        request_intent=_intent("acme/repo"),
    )

    assert result["immutable_arguments"] == {"repository": "acme/repo"}
    assert result["argument_schema"]["properties"]["repository"]["const"] == "acme/repo"  # type: ignore[index]


def test_github_repository__google_defaults__are_not_used() -> None:
    with pytest.raises(RequiredContainerUnresolvedError, match="repository"):
        resolve_default_container(
            route=_github_route("github_create_issue"),  # type: ignore[arg-type]
            selected_tool_schema=planning_tool_argument_schema("github_create_issue"),
            request_intent=_intent(None),
            default_tasklist_id_provider=lambda: "task-default",
            default_calendar_id_provider=lambda: "calendar-default",
        )


def _github_route(tool_id: str) -> dict[str, object]:
    return {
        "route_id": "github-route",
        "resource_type": "GITHUB_ISSUE",
        "connector_id": "github",
        "effect": "CREATE" if tool_id == "github_create_issue" else "UPDATE",
        "selected_tool_id": tool_id,
        "reason_codes": [],
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
            "goal": "Mutate issue",
            "completion_conditions": ["Issue mutated"],
            "constraints": constraints,
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
