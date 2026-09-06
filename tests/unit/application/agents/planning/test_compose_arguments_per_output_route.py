from collections.abc import Mapping
from typing import cast

import pytest

from google_work_agent.application.agents.planning.compose_arguments_per_output_route import (
    compose_arguments_per_output_route,
    tool_argument_candidate_output_schema,
)
from google_work_agent.application.agents.planning.contracts.planning_semantics import (
    PlanningSemanticInvoker,
)
from google_work_agent.application.agents.planning.contracts.planning_tool_schema import (
    planning_tool_argument_schema,
)
from google_work_agent.application.agents.planning.resolve_default_container import (
    BoundSelectedToolSchemaV1,
    PlanningArgumentBindingError,
    resolve_default_container,
)
from google_work_agent.application.agents.request_understanding.contracts.request_intent import (
    RequestIntentV2,
)
from google_work_agent.ports.llm.output_schema_validation import validate_output_schema

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


@pytest.mark.parametrize(
    "tool", ["github_update_issue", "github_close_issue", "github_reopen_issue"]
)
@pytest.mark.parametrize("binding", ["exact", "no_selection", "wrong_selection", "wrong_evidence"])
def test_github_arguments__selected_identity_binding__preserves_only_exact_target_evidence(
    tool, binding
):
    route = {
        **ROUTE,
        "connector_id": "github",
        "resource_type": "GITHUB_ISSUE",
        "effect": "UPDATE",
        "selected_tool_id": tool,
    }
    bound = cast(
        BoundSelectedToolSchemaV1,
        {
            **route,
            "schema_version": 1,
            "argument_schema": planning_tool_argument_schema(tool),
            "immutable_arguments": {"repository": "owner/repo"},
        },
    )
    arguments = {"repository": "owner/repo", "issue_number": 7}
    if tool == "github_update_issue":
        arguments["title"] = "New title"
    target = "owner/repo#8" if binding == "wrong_selection" else "owner/repo#7"
    evidence_handle = (
        "github_issue:owner/repo#8" if binding == "wrong_evidence" else "github_issue:owner/repo#7"
    )
    intent = {
        "constraints": []
        if binding == "no_selection"
        else [
            {"kind": "RESOURCE", "field": "selected_resource_id", "value": [target]},
        ]
    }
    result = compose_arguments_per_output_route(
        [route],
        objectives=[OBJECTIVE],
        bound_tool_schemas=[bound],
        request_intent=intent,
        evidence=[
            {"evidence_id": "user", "origin_type": "USER_MESSAGE"},
            {"evidence_id": "target", "resource_handle": evidence_handle},
        ],
        invoke=lambda *_: {
            "schema_version": 1,
            "route_id": "r1",
            "arguments": arguments,
            "evidence_refs": ["user"],
        },
    )[0]
    assert result["arguments"] == arguments
    assert result["evidence_refs"] == (["user", "target"] if binding == "exact" else ["user"])


@pytest.mark.parametrize("patch", [{"notes": ""}, {"due": None}, {"due": "2026-09-08"}])
def test_compose_modification__explicit_changes__preserve_partial_shape(
    patch: dict[str, object],
) -> None:
    bound = cast(
        BoundSelectedToolSchemaV1,
        {
            **ROUTE,
            "schema_version": 1,
            "immutable_arguments": {},
            "argument_schema": planning_tool_argument_schema(
                "tasks_create_task", modification=True
            ),
        },
    )
    modification = {
        "request": "명시한 필드만 수정",
        "current_arguments": {
            "task_list_id": "list-1",
            "payload": {"title": "그대로 유지", "notes": "기존 메모"},
        },
        "reference_time": "2026-09-06T00:00:00Z",
        "timezone": "Asia/Seoul",
    }

    def invoke(_prompt_id: str, value: Mapping[str, object]) -> Mapping[str, object]:
        assert value["modification"] == modification
        result = {
            "schema_version": 1,
            "route_id": "r1",
            "arguments": {"payload": patch},
            "evidence_refs": [],
        }
        assert (
            validate_output_schema(result, tool_argument_candidate_output_schema(value).json_schema)
            == []
        )
        return result

    result = compose_arguments_per_output_route(
        [ROUTE],
        objectives=[OBJECTIVE],  # type: ignore[list-item]
        bound_tool_schemas=[bound],
        modification=modification,
        invoke=invoke,
    )
    assert result[0]["arguments"] == {"payload": patch}
    assert "title" not in result[0]["arguments"]["payload"]  # type: ignore[operator]


@pytest.mark.parametrize(
    "patch",
    [{"task_list_id": "other"}, {"status": "completed"}, {"due": "2026-02-30"}, {"notes": None}],
)
def test_compose_modification__unsupported_or_invalid_fields__rejects(
    patch: dict[str, object],
) -> None:
    schema = planning_tool_argument_schema("tasks_create_task", modification=True)
    bound = cast(
        BoundSelectedToolSchemaV1,
        {**ROUTE, "schema_version": 1, "argument_schema": schema, "immutable_arguments": {}},
    )
    with pytest.raises(PlanningArgumentBindingError):
        compose_arguments_per_output_route(
            [ROUTE],
            objectives=[OBJECTIVE],  # type: ignore[list-item]
            bound_tool_schemas=[bound],
            modification={"request": "수정"},
            invoke=lambda *_: {
                "schema_version": 1,
                "route_id": "r1",
                "arguments": {"payload": patch},
                "evidence_refs": [],
            },
        )


@pytest.mark.parametrize("invalid_field", ["description", "route", "container", "evidence"])
def test_inference_schema__rejects_invalid_arguments__inside_repair_boundary(
    invalid_field: str,
) -> None:
    bound = resolve_default_container(
        route=ROUTE,  # type: ignore[arg-type]
        selected_tool_schema=planning_tool_argument_schema("tasks_create_task"),
        explicit_container_id="list-1",
    )
    schema = tool_argument_candidate_output_schema(
        {
            "output_route": ROUTE,
            "tool_schema": bound["argument_schema"],
            "evidence": [{"evidence_ref": "e1"}],
        }
    )
    payload = {"title": "Report", "notes": "Review", "scheduled_date": "2026-09-07"}
    arguments: dict[str, object] = {"task_list_id": "list-1", "payload": payload}
    candidate: dict[str, object] = {
        "schema_version": 1,
        "route_id": "r1",
        "arguments": arguments,
        "evidence_refs": ["e1"],
    }
    assert validate_output_schema(candidate, schema.json_schema) == []
    if invalid_field == "description":
        payload["description"] = payload.pop("notes")
    elif invalid_field == "route":
        candidate["route_id"] = "other-route"
    elif invalid_field == "container":
        arguments["task_list_id"] = "other-list"
    else:
        candidate["evidence_refs"] = ["unavailable"]
    assert validate_output_schema(candidate, schema.json_schema)


def test_argument_prompt__receives_only_selected__bound_tool_schema() -> None:
    bound = resolve_default_container(
        route=ROUTE,  # type: ignore[arg-type]
        selected_tool_schema=planning_tool_argument_schema("tasks_create_task"),
        explicit_container_id="list-1",
    )

    def invoke(_prompt_id: str, prompt_input: Mapping[str, object]) -> Mapping[str, object]:
        assert set(prompt_input) == {"output_route", "action_objective", "tool_schema", "evidence"}
        assert prompt_input["tool_schema"]["properties"]["task_list_id"]["const"] == "list-1"  # type: ignore[index]
        candidate = {
            "schema_version": 1,
            "route_id": "r1",
            "arguments": {"payload": {"title": "Report"}},
            "evidence_refs": ["e1"],
        }
        schema = tool_argument_candidate_output_schema(prompt_input)
        assert validate_output_schema(candidate, schema.json_schema) == []
        return candidate

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


@pytest.mark.parametrize("description", [None, "검증 결과 공유"])
def test_exact_calendar_create__preserves_all_constraints__in_arguments(
    description: str | None,
) -> None:
    route = {
        "route_id": "calendar-route",
        "resource_type": "CALENDAR_EVENT",
        "connector_id": "google_workspace",
        "effect": "CREATE",
        "selected_tool_id": "calendar_create_event",
        "reason_codes": [],
    }
    bound = resolve_default_container(
        route=route,  # type: ignore[arg-type]
        selected_tool_schema=planning_tool_argument_schema("calendar_create_event"),
        explicit_container_id="primary",
    )
    objective = {
        "schema_version": 1,
        "route_id": "calendar-route",
        "objective": "Create the requested event",
        "target_semantics": "CALENDAR_EVENT",
        "scope_constraints": [],
        "evidence_refs": ["user-message-1"],
    }
    request_intent = {
        "ambiguity": {"requires_confirmation": False},
        "constraints": [
            {"kind": "RESOURCE", "field": "title", "value": "[GWA OPT] Calendar 42"},
            {"kind": "DATE", "field": "date", "value": "2026-09-08"},
            {"kind": "TIME", "field": "start_time", "value": "15:00"},
            {"kind": "TIME", "field": "end_time", "value": "15:30"},
            {"kind": "TIME", "field": "timezone", "value": "Asia/Seoul"},
        ],
    }

    expected_payload = {
        "title": "[GWA OPT] Calendar 42",
        "start": "2026-09-08T15:00:00+09:00",
        "end": "2026-09-08T15:30:00+09:00",
    }
    calls: list[str] = []
    if description is not None:
        cast(list[dict[str, str]], request_intent["constraints"]).append(
            {"kind": "RESOURCE", "field": "description", "value": description}
        )
        expected_payload["description"] = description

    def invoke(prompt_id: str, prompt_input: Mapping[str, object]) -> Mapping[str, object]:
        assert description is not None, "exact supported constraints need no inference"
        assert prompt_input["request_intent"] == request_intent
        calls.append(prompt_id)
        return {
            "schema_version": 1,
            "route_id": "calendar-route",
            "arguments": {"payload": expected_payload},
            "evidence_refs": ["user-message-1"],
        }

    result = compose_arguments_per_output_route(
        [route],
        objectives=[objective],  # type: ignore[list-item]
        bound_tool_schemas=[bound],
        request_intent=request_intent,
        evidence=[
            {
                "evidence_id": "user-message-1",
                "origin_type": "USER_MESSAGE",
                "kind": "USER_REQUEST",
            }
        ],
        invoke=invoke,
    )
    assert len(calls) == (1 if description is not None else 0)
    assert result == (
        {
            "schema_version": 1,
            "route_id": "calendar-route",
            "arguments": {
                "calendar_id": "primary",
                "payload": expected_payload,
            },
            "evidence_refs": ["user-message-1"],
        },
    )


def test_exact_task_create__materializes_arguments__without_llm() -> None:
    bound = resolve_default_container(
        route=ROUTE,  # type: ignore[arg-type]
        selected_tool_schema=planning_tool_argument_schema("tasks_create_task"),
        explicit_container_id="@default",
    )
    request_intent = {
        "ambiguity": {"requires_confirmation": False},
        "constraints": [{"kind": "RESOURCE", "field": "title", "value": "Submit report"}],
    }

    result = compose_arguments_per_output_route(
        [ROUTE],
        objectives=[OBJECTIVE],  # type: ignore[list-item]
        bound_tool_schemas=[bound],
        request_intent=request_intent,
        evidence=[{"evidence_ref": "e1"}],
        invoke=lambda *_: (_ for _ in ()).throw(AssertionError("LLM must be skipped")),
    )

    assert result[0]["arguments"] == {
        "task_list_id": "@default",
        "payload": {"title": "Submit report"},
    }


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

    def invoke(_prompt_id: str, prompt_input: Mapping[str, object]) -> Mapping[str, object]:
        candidate = {
            "schema_version": 1,
            "route_id": "r1",
            "arguments": business_arguments,
            "evidence_refs": ["e1"],
        }
        schema = tool_argument_candidate_output_schema(prompt_input)
        assert validate_output_schema(candidate, schema.json_schema) == []
        return candidate

    result = compose_arguments_per_output_route(
        [route],
        objectives=[_github_objective()],  # type: ignore[list-item]
        bound_tool_schemas=[bound],
        evidence=[{"evidence_ref": "e1"}],
        invoke=invoke,
    )

    assert result[0]["arguments"]["repository"] == "acme/repo"


@pytest.mark.parametrize("include_repository", [False, True])
def test_github_update_schema__missing_change__is_rejected(include_repository: bool) -> None:
    route = _github_route("github_update_issue", "UPDATE")
    bound = resolve_default_container(
        route=route,  # type: ignore[arg-type]
        selected_tool_schema=planning_tool_argument_schema("github_update_issue"),
        request_intent=_github_intent("acme/repo"),
    )
    schema = tool_argument_candidate_output_schema(
        {
            "output_route": route,
            "tool_schema": bound["argument_schema"],
            "evidence": [],
        }
    )
    arguments: dict[str, object] = {"issue_number": 7}
    if include_repository:
        arguments["repository"] = "acme/repo"
    candidate = {
        "schema_version": 1,
        "route_id": "r1",
        "arguments": arguments,
        "evidence_refs": [],
    }
    assert validate_output_schema(candidate, schema.json_schema)


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
