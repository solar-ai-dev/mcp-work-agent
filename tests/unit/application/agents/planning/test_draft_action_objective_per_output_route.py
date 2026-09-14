from collections.abc import Mapping
from typing import Any, cast

import pytest

from google_work_agent.application.agents.planning.draft_action_objective_per_output_route import (
    action_objective_candidate_output_schema,
    draft_action_objective_per_output_route,
    requires_objective_inference,
)


def test_action_objective_schema__binds_current_evidence__identities() -> None:
    schema = cast(
        dict[str, Any],
        action_objective_candidate_output_schema(
        {
            "output_route": {
                "resource_type": "TASK",
                "effect": "CREATE",
                "selected_tool_id": "tasks_create_task",
            },
            "evidence": [
                {"evidence_ref": "evidence-2"},
                {"evidence_id": "evidence-1"},
            ],
        }
        ).json_schema,
    )

    evidence_refs = schema["properties"]["evidence_refs"]
    assert evidence_refs["uniqueItems"] is True
    assert evidence_refs["items"]["enum"] == ["evidence-1", "evidence-2"]


def test_action_objective_schema__requires_empty_refs__without_evidence() -> None:
    schema = cast(
        dict[str, Any],
        action_objective_candidate_output_schema(
        {
            "output_route": {
                "resource_type": "TASK",
                "effect": "CREATE",
                "selected_tool_id": "tasks_create_task",
            },
            "evidence": [],
        }
        ).json_schema,
    )

    assert schema["properties"]["evidence_refs"]["maxItems"] == 0


def test_exact_github_create__reuses_validated_goal__without_fabricated_evidence() -> None:
    route = {
        "route_id": "r",
        "resource_type": "GITHUB_ISSUE",
        "effect": "CREATE",
        "selected_tool_id": "github_create_issue",
    }
    intent: dict[str, object] = {
        "goal": "Create requested Issue",
        "requested_resource_hints": ["GITHUB_ISSUE"],
        "requested_effect_hints": ["CREATE"],
        "ambiguity": {"requires_confirmation": False},
        "constraints": [{"field": "repository", "value": "acme/repo"}],
    }
    assert not requires_objective_inference(route, request_intent=intent)
    result = draft_action_objective_per_output_route(
        [route],
        user_request="create issue",
        request_intent=intent,
        work_analysis=None,
        evidence=[],
        invoke=lambda *_: (_ for _ in ()).throw(AssertionError("LLM must be skipped")),
    )
    assert result[0]["objective"] == intent["goal"]
    assert result[0]["evidence_refs"] == []
    assert result[0]["scope_constraints"] == ["repository: acme/repo"]
    assert requires_objective_inference(
        route,
        request_intent={**intent, "requested_resource_hints": ["GMAIL_THREAD", "GITHUB_ISSUE"]},
    )


def test_objective_prompt_is__route_bounded_and__receives_no_tool_schema() -> None:
    def invoke(prompt_id: str, prompt_input: Mapping[str, object]) -> Mapping[str, object]:
        assert prompt_id == "planning.draft_action_objective_per_output_route"
        assert "tool_schema" not in prompt_input
        assert "work_analysis" not in prompt_input
        route = prompt_input["output_route"]
        assert isinstance(route, Mapping)
        return {
            "schema_version": 1,
            "objective": "Create the requested task",
            "scope_constraints": ["create only"],
            "evidence_refs": ["e1"],
        }

    result = draft_action_objective_per_output_route(
        [
            {
                "route_id": "r1",
                "resource_type": "TASK",
                "effect": "CREATE",
                "selected_tool_id": "tasks_create_task",
            }
        ],
        user_request="Create a task",
        request_intent={"goal": "create task"},
        work_analysis=None,
        evidence=[{"evidence_ref": "e1"}],
        invoke=invoke,
    )
    assert result[0]["route_id"] == "r1"
    assert result[0]["target_semantics"] == "TASK"


def test_action_objective__with_spaced_literal__restores_exact_value() -> None:
    exact_sentence = "8월 21일 입고 준비를 확인 중입니다."
    result = draft_action_objective_per_output_route(
        [
            {
                "route_id": "draft-update",
                "resource_type": "GMAIL_DRAFT",
                "effect": "UPDATE",
                "selected_tool_id": "gmail_update_draft",
            }
        ],
        user_request=f"초안 끝에 “{exact_sentence}”만 추가해줘.",
        request_intent={"goal": "초안 수정"},
        work_analysis=None,
        evidence=[],
        invoke=lambda *_: {
            "schema_version": 1,
            "objective": "초안 끝에 '8 월 21 일 입고 준비를 확인 중입니다.'만 추가",
            "scope_constraints": ["'8 월 21 일 입고 준비를 확인 중입니다.'를 한 번만 추가"],
            "evidence_refs": [],
        },
    )

    assert exact_sentence in result[0]["objective"]
    assert exact_sentence in result[0]["scope_constraints"][0]


@pytest.mark.parametrize("target_semantics", ["GMAIL_MESSAGE", "GMAIL_THREAD_REPLY"])
def test_gmail_send_objective__when_planned__requires_explicit_typed_relation(
    target_semantics: str,
) -> None:
    route = {
        "route_id": "gmail-send",
        "resource_type": "GMAIL_MESSAGE",
        "effect": "SEND",
        "selected_tool_id": "gmail_send",
    }

    result = draft_action_objective_per_output_route(
        [route],
        user_request="send a message",
        request_intent={"goal": "send a message"},
        work_analysis=None,
        evidence=[],
        invoke=lambda *_: {
            "schema_version": 1,
            "objective": "Send the requested message",
            "target_semantics": target_semantics,
            "scope_constraints": [],
            "evidence_refs": [],
        },
    )

    assert result[0]["target_semantics"] == target_semantics


def test_non_gmail_objective__with_model_owned_target_semantics__is_rejected() -> None:
    with pytest.raises(ValueError, match="non-owned route fields"):
        draft_action_objective_per_output_route(
            [
                {
                    "route_id": "task",
                    "resource_type": "TASK",
                    "effect": "UPDATE",
                    "selected_tool_id": "tasks_update_task",
                }
            ],
            user_request="update a task",
            request_intent={"goal": "update a task"},
            work_analysis=None,
            evidence=[],
            invoke=lambda *_: {
                "schema_version": 1,
                "objective": "Update the task",
                "target_semantics": "GMAIL_THREAD_REPLY",
                "scope_constraints": [],
                "evidence_refs": [],
            },
        )


def test_exact_calendar_create__materializes_objective__without_llm() -> None:
    result = draft_action_objective_per_output_route(
        [
            {
                "route_id": "calendar-route",
                "resource_type": "CALENDAR_EVENT",
                "effect": "CREATE",
                "selected_tool_id": "calendar_create_event",
            }
        ],
        user_request="create an event",
        request_intent={
            "requested_resource_hints": ["CALENDAR_EVENT"],
            "requested_effect_hints": ["CREATE"],
            "ambiguity": {"requires_confirmation": False},
            "constraints": [
                {"kind": "RESOURCE", "field": "title", "value": "[GWA OPT] Calendar 42"},
                {"kind": "DATE", "field": "date", "value": "2026-09-08"},
                {"kind": "TIME", "field": "start_time", "value": "15:00"},
                {"kind": "TIME", "field": "end_time", "value": "15:30"},
                {"kind": "TIME", "field": "timezone", "value": "Asia/Seoul"},
            ],
        },
        work_analysis=None,
        evidence=[
            {
                "evidence_id": "user-message-1",
                "origin_type": "USER_MESSAGE",
                "kind": "USER_REQUEST",
            }
        ],
        invoke=lambda *_: (_ for _ in ()).throw(AssertionError("LLM must be skipped")),
    )

    assert result[0]["route_id"] == "calendar-route"
    assert result[0]["target_semantics"] == "CALENDAR_EVENT"
    assert "title: [GWA OPT] Calendar 42" in result[0]["scope_constraints"]
    assert result[0]["evidence_refs"] == ["user-message-1"]


def test_exact_task_create__materializes_objective__without_llm() -> None:
    result = draft_action_objective_per_output_route(
        [
            {
                "route_id": "task-route",
                "resource_type": "TASK",
                "effect": "CREATE",
                "selected_tool_id": "tasks_create_task",
            }
        ],
        user_request="create a task",
        request_intent={
            "requested_resource_hints": ["TASK"],
            "requested_effect_hints": ["CREATE"],
            "ambiguity": {"requires_confirmation": False},
            "constraints": [
                {"kind": "RESOURCE", "field": "title", "value": "Submit report"},
                {"kind": "RESOURCE", "field": "notes", "value": "Attach evidence"},
                {"kind": "DATE", "field": "scheduled_date", "value": "2026-09-11"},
            ],
        },
        work_analysis=None,
        evidence=[{"evidence_id": "user-message-1"}],
        invoke=lambda *_: (_ for _ in ()).throw(AssertionError("LLM must be skipped")),
    )

    assert result[0]["target_semantics"] == "TASK"
    assert result[0]["scope_constraints"] == [
        "title: Submit report",
        "notes: Attach evidence",
        "scheduled_date: 2026-09-11",
    ]
    assert result[0]["evidence_refs"] == ["user-message-1"]


def test_source_derived_task_create__with_evidence__uses_semantic_objective_inference() -> None:
    route = {
        "route_id": "task-route",
        "resource_type": "TASK",
        "effect": "CREATE",
        "selected_tool_id": "tasks_create_task",
    }
    request_intent = {
        "requested_resource_hints": ["GMAIL_THREAD", "TASK"],
        "requested_effect_hints": ["READ", "CREATE"],
        "ambiguity": {"requires_confirmation": False},
        "constraints": [
            {"kind": "RESOURCE", "field": "title", "value": "Submit report"},
            {
                "kind": "USER_REQUIREMENT",
                "field": "required_information",
                "value": ["메일의 최신 변경 내용을 메모에 반영"],
            },
        ],
    }
    calls: list[str] = []

    def invoke(prompt_id: str, prompt_input: Mapping[str, object]) -> Mapping[str, object]:
        calls.append(prompt_id)
        assert prompt_input["request_intent"] == request_intent
        return {
            "schema_version": 1,
            "objective": "Create a task using the retrieved mail facts",
            "scope_constraints": [
                "title: Submit report",
                "notes: include the latest change from evidence",
            ],
            "evidence_refs": ["mail-1"],
        }

    result = draft_action_objective_per_output_route(
        [route],
        user_request="read the mail and create a task",
        request_intent=request_intent,
        work_analysis=None,
        evidence=[{"evidence_ref": "mail-1", "origin_type": "CONNECTOR_READ"}],
        invoke=invoke,
    )

    assert calls == ["planning.draft_action_objective_per_output_route"]
    assert result[0]["evidence_refs"] == ["mail-1"]


def test_draft_action_objective_per_output_route__with_task_calendar_sources__returns_objective(
) -> None:
    route = {
        "route_id": "draft-route",
        "resource_type": "GMAIL_DRAFT",
        "effect": "CREATE",
        "selected_tool_id": "gmail_create_draft",
    }
    intent = {
        "ambiguity": {"requires_confirmation": False},
        "resource_responsibilities": {
            "source_reads": [
                {"resource_type": "TASK", "required_information": ["title"]},
                {"resource_type": "CALENDAR_EVENT", "required_information": ["start"]},
            ],
            "outputs": [{"resource_type": "GMAIL_DRAFT", "effect": "CREATE"}],
        },
    }

    result = draft_action_objective_per_output_route(
        [route],
        user_request="Create a grounded draft",
        request_intent=intent,
        work_analysis=None,
        evidence=[{"evidence_id": "task"}, {"evidence_id": "event"}],
        invoke=lambda *_: (_ for _ in ()).throw(AssertionError("LLM must be skipped")),
    )

    assert result[0]["target_semantics"] == "GMAIL_DRAFT"
    assert result[0]["scope_constraints"] == ["CREATE_DRAFT_ONLY", "DO_NOT_SEND"]
    assert result[0]["evidence_refs"] == ["task", "event"]
    assert not requires_objective_inference(route, request_intent=intent)


def test_calendar_create_objective__avoids_repeating__semantic_field_alias_work() -> None:
    result = draft_action_objective_per_output_route(
        [
            {
                "route_id": "calendar-route",
                "resource_type": "CALENDAR_EVENT",
                "effect": "CREATE",
                "selected_tool_id": "calendar_create_event",
            }
        ],
        user_request="create an event",
        request_intent={
            "requested_resource_hints": ["CALENDAR_EVENT"],
            "requested_effect_hints": ["CREATE"],
            "ambiguity": {"requires_confirmation": False},
            "constraints": [
                {"kind": "RESOURCE", "field": "calendar_id", "value": "Project"},
                {"kind": "DATE", "field": "event_start_datetime", "value": "2026-09-11T15:00"},
                {"kind": "DATE", "field": "event_end_datetime", "value": "2026-09-11T15:30"},
                {"kind": "TIME", "field": "timezone", "value": "Asia/Seoul"},
            ],
        },
        work_analysis=None,
        evidence=[],
        invoke=lambda *_: (_ for _ in ()).throw(AssertionError("LLM must be skipped")),
    )

    assert result[0]["target_semantics"] == "CALENDAR_EVENT"
    assert "calendar_id: Project" in result[0]["scope_constraints"]
