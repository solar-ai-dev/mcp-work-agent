from collections import deque
from copy import deepcopy
from dataclasses import replace
from typing import Literal, cast

import pytest
from tests.support.context_retrieval import (
    SUFFICIENCY_PROMPT_REF,
    FakeLLMRuntime,
    _acquisition_result,
    _intent,
    _llm_result,
    _run_budget,
    _sufficiency_output,
    _tool_route_plan,
)

from google_work_agent.adapters.langgraph.subgraphs.retrieval.nodes.assess_sufficiency_node import (
    assess_sufficiency_node,
)
from google_work_agent.application.agents.retrieval.assess_sufficiency import (
    assess_sufficiency,
    authorize_retrieval_followup,
    deterministic_sufficiency,
    missing_information_projection,
)
from google_work_agent.application.agents.retrieval.contracts.query_attempt import QueryAttemptV1
from google_work_agent.application.agents.retrieval.contracts.retrieval_result import (
    AcquisitionResultV1,
    EvidenceDraftV1,
    SufficiencyResultV2,
)
from google_work_agent.application.agents.tool_routing.contracts.tool_route_plan import (
    ActionOutputPlanV1,
)
from google_work_agent.ports.llm.structured_inference_contracts import OutputSchemaDefinition


def test_search_candidate__unread_metadata__requires_detail_without_llm_guess() -> None:
    intent = _intent()
    intent["analysis_requirement"] = "NONE"
    intent["constraints"] = []
    runtime = FakeLLMRuntime(deque())
    route_plan = _tool_route_plan()
    route = route_plan["input_plan"]["input_routes"][0]
    route["resource_type"] = "GMAIL_THREAD"
    route["allowed_read_tool_ids"] = ["gmail_search_threads", "gmail_get_thread"]
    result = assess_sufficiency(
        llm_runtime=runtime,
        prompt_ref=SUFFICIENCY_PROMPT_REF,
        requested_mode="LOCAL_GPU",
        request_intent=intent,
        tool_route_plan=route_plan,
        acquisition_result=_acquisition_result(),
        retry_budget=_run_budget(used=0),
        evidence_drafts=[
            {
                "schema_version": 1,
                "evidence_id": "e1",
                "resource_handle": "gmail_thread:thread-kim",
                "segment_id": "s1",
                "kind": "excerpt",
                "excerpt": "unclear title",
                "locator": {"is_metadata_only": True},
                "reason_codes": ["CONTEXT"],
            }
        ],
    )
    assert result["status"] == "NEEDS_MORE_DATA"
    assert result["issues"][0]["reason_codes"] == ["CANDIDATE_DETAIL_REQUIRED"]
    assert runtime.calls == []


def test_existing_gmail_thread_reply__search_candidate__requires_detail_without_llm() -> None:
    intent = _intent()
    intent["analysis_requirement"] = "NONE"
    intent["constraints"] = []
    intent["requested_effect_hints"] = ["READ", "SEND"]
    intent["requested_resource_hints"] = ["GMAIL_THREAD", "GMAIL_MESSAGE"]
    route_plan = _tool_route_plan(
        [
            {
                "route_id": "route-gmail",
                "resource_type": "GMAIL_THREAD",
                "connector_id": "google_workspace",
                "allowed_read_tool_ids": ["gmail_search_threads", "gmail_get_thread"],
                "required": True,
                "reason_codes": ["REQUESTED_INPUT"],
            }
        ]
    )
    route_plan["output_plan"] = {
        "schema_version": 1,
        "meta": {"artifact_id": "route-out-1", "revision": 1, "based_on": []},
        "output_mode": "ACTION",
        "output_routes": [
            {
                "route_id": "route-send",
                "resource_type": "GMAIL_MESSAGE",
                "connector_id": "google_workspace",
                "effect": "SEND",
                "selected_tool_id": "gmail_send",
                "reason_codes": ["REGISTRY_SINGLE_CANDIDATE"],
            }
        ],
    }

    result = deterministic_sufficiency(
        request_intent=intent,
        tool_route_plan=route_plan,
        acquisition_result=_acquisition_result(),
        evidence_drafts=[],
        retry_budget=_run_budget(used=0),
    )

    assert result is not None
    assert result["status"] == "NEEDS_MORE_DATA"
    assert result["issues"][0]["reason_codes"] == ["CANDIDATE_DETAIL_REQUIRED"]


def test_existing_gmail_thread_reply__detailed_identity__is_sufficient_without_llm() -> None:
    intent = _intent()
    intent["analysis_requirement"] = "NONE"
    intent["constraints"] = []
    intent["requested_effect_hints"] = ["READ", "SEND"]
    intent["requested_resource_hints"] = ["GMAIL_THREAD", "GMAIL_MESSAGE"]
    route_plan = _tool_route_plan(
        [
            {
                "route_id": "route-gmail",
                "resource_type": "GMAIL_THREAD",
                "connector_id": "google_workspace",
                "allowed_read_tool_ids": ["gmail_search_threads", "gmail_get_thread"],
                "required": True,
                "reason_codes": ["REQUESTED_INPUT"],
            }
        ]
    )
    route_plan["output_plan"] = {
        "schema_version": 1,
        "meta": {"artifact_id": "route-out-1", "revision": 1, "based_on": []},
        "output_mode": "ACTION",
        "output_routes": [
            {
                "route_id": "route-send",
                "resource_type": "GMAIL_MESSAGE",
                "connector_id": "google_workspace",
                "effect": "SEND",
                "selected_tool_id": "gmail_send",
                "reason_codes": ["REGISTRY_SINGLE_CANDIDATE"],
            }
        ],
    }
    runtime = FakeLLMRuntime()
    result = assess_sufficiency(
        llm_runtime=runtime,
        prompt_ref=SUFFICIENCY_PROMPT_REF,
        requested_mode="LOCAL_GPU",
        request_intent=intent,
        tool_route_plan=route_plan,
        acquisition_result=_acquisition_result(),
        evidence_drafts=[
            {
                "schema_version": 1,
                "evidence_id": "evidence-thread-kim",
                "resource_handle": "gmail_thread:thread-kim",
                "segment_id": "segment-thread-kim",
                "kind": "excerpt",
                "excerpt": "From: Kim\nSubject: Project\nPlease reply next week.",
                "locator": {
                    "thread_id": "thread-kim",
                    "rfc822_message_id": "<message-kim@example.test>",
                    "received_at": "2026-09-07T12:00:00+09:00",
                },
                "reason_codes": ["SUPPORTS"],
            }
        ],
        retry_budget=_run_budget(used=0),
        query_attempts=[
            cast(
                QueryAttemptV1,
                {
                    "schema_version": 1,
                    "query_attempt_id": "attempt-detail-1",
                    "run_id": "run-1",
                    "route_id": "route-gmail",
                    "round_no": 1,
                    "attempt_no": 2,
                    "resource_type": "GMAIL_THREAD",
                    "connector_id": "google_workspace",
                    "operation_kind": "DETAIL_FETCH",
                    "normalized_intent_constraints": [],
                    "query_spec": {
                        "tool_id": "gmail_get_thread",
                        "tool_schema_version": "1",
                        "canonical_arguments": {"thread_id": "thread-kim"},
                    },
                    "previous_query_hash": None,
                    "page_state_hash": None,
                    "added_constraints": [],
                    "removed_constraints": [],
                    "change_reason_code": "DETAIL_REQUIRED",
                    "candidate_count": 1,
                    "top_score": None,
                    "score_margin": None,
                    "confidence_band": "HIGH",
                    "retrieval_config_version": "1",
                    "score_config_version": "1",
                    "threshold_config_version": "1",
                    "stop_reason": "DETAIL_COMPLETE",
                },
            )
        ],
    )

    assert result == {"schema_version": 2, "status": "SUFFICIENT", "issues": []}
    assert runtime.calls == []


@pytest.mark.parametrize(
    "has_next,exhausted,used,expected",
    [
        (True, False, 0, "NEEDS_MORE_DATA"),
        (True, False, 2, "PARTIAL"),
        (True, True, 0, "SUFFICIENT"),
        (False, False, 0, "SUFFICIENT"),
    ],
)
def test_sufficiency_node__unread_page__requires_bounded_coverage(
    has_next: bool,
    exhausted: bool,
    used: int,
    expected: str,
) -> None:
    runtime = FakeLLMRuntime(deque([_llm_result(_sufficiency_output("SUFFICIENT"))]))
    intent = _intent()
    intent["analysis_requirement"] = "NONE"
    intent["constraints"] = []
    result = cast(
        SufficiencyResultV2,
        assess_sufficiency_node(
            {
                "request_intent": intent,
                "evidence_selection": {
                    "schema_version": 2,
                    "evidence_drafts": [],
                    "selected_segment_ids": [],
                    "excluded_segment_ids": [],
                },
            },
            llm_runtime=runtime,
            prompt_ref=SUFFICIENCY_PROMPT_REF,
            requested_mode="LOCAL_GPU",
            tool_route_plan=_tool_route_plan(),
            acquisition_result=_acquisition_result(),
            retry_budget=_run_budget(used=used),
            evidence_drafts=[
                {
                    "schema_version": 1,
                    "evidence_id": "e1",
                    "resource_handle": "gmail_thread:thread-kim",
                    "segment_id": "s1",
                    "kind": "excerpt",
                    "excerpt": "현재 확인한 한 개의 자료",
                    "locator": {},
                    "reason_codes": ["SUPPORTS"],
                }
            ],
            read_result_summaries=[
                {
                    "route_id": "route-gmail",
                    "has_next_page": has_next,
                    "exhausted": exhausted,
                }
            ],
        )["sufficiency"],
    )
    assert result["status"] == expected
    if has_next and not exhausted:
        assert result["issues"][0]["reason_codes"] == ["UNREAD_PAGE_AVAILABLE"]


def test_event_year_uncertainty__cannot_be_promoted_by__generic_continue_guard() -> None:
    intent = _intent()
    intent["analysis_requirement"] = "NONE"
    intent["constraints"] = []
    runtime = FakeLLMRuntime(deque([_llm_result(_sufficiency_output("SUFFICIENT"))]))
    result = assess_sufficiency(
        llm_runtime=runtime,
        prompt_ref=SUFFICIENCY_PROMPT_REF,
        requested_mode="LOCAL_GPU",
        request_intent=intent,
        tool_route_plan=_tool_route_plan(),
        acquisition_result=_acquisition_result(),
        retry_budget=_run_budget(used=0),
        evidence_drafts=[
            {
                "schema_version": 1,
                "evidence_id": "e1",
                "resource_handle": "gmail_thread:thread-kim",
                "segment_id": "s1",
                "kind": "excerpt",
                "excerpt": "연수는 9월 4일입니다.",
                "locator": {},
                "reason_codes": ["SUPPORTS"],
            }
        ],
        query_attempts=[
            cast(
                QueryAttemptV1,
                {
                    "route_id": "route-gmail",
                    "resource_type": "GMAIL_THREAD",
                    "operation_kind": "SEARCH",
                    "normalized_intent_constraints": [
                        {
                            "kind": "TEMPORAL_RANGE",
                            "axis": "EVENT_TIME",
                            "timezone": "Asia/Seoul",
                            "start_local": "2026-09-01T00:00:00",
                            "end_local": "2026-09-08T00:00:00",
                        }
                    ],
                },
            )
        ],
    )
    assert result["status"] == "PARTIAL"
    assert result["issues"][0]["reason_codes"] == ["EVENT_YEAR_UNCONFIRMED"]


@pytest.mark.parametrize("code", ["NOT_FOUND", "PERMISSION_DENIED"])
@pytest.mark.parametrize(("effect", "expected"), [("READ", "PARTIAL"), ("CREATE", "BLOCKED")])
def test_sufficiency_node__target_access_failure__stops_without_search_or_write(
    code: str,
    effect: Literal["READ", "CREATE", "UPDATE", "SEND", "DELETE"],
    expected: str,
) -> None:
    runtime = FakeLLMRuntime(deque())
    budget = _run_budget(used=0)
    original_budget = deepcopy(budget)
    acquisition = _acquisition_result()
    acquisition["status"] = "FAILED"
    acquisition["resource_handles"] = []
    acquisition["source_summaries"] = [
        {
            "route_id": "route-github",
            "connector_id": "github",
            "source": "GITHUB",
            "status": "FAILED",
            "error_code": code,
            "resource_count": 0,
            "resource_handles": [],
        }
    ]
    result = cast(
        SufficiencyResultV2,
        assess_sufficiency_node(
            {
                "request_intent": {**_intent(), "requested_effect_hints": [effect]},
                "evidence_selection": {
                    "schema_version": 2,
                    "evidence_drafts": [],
                    "selected_segment_ids": [],
                    "excluded_segment_ids": [],
                },
            },
            llm_runtime=runtime,
            prompt_ref=SUFFICIENCY_PROMPT_REF,
            requested_mode="AUTO",
            tool_route_plan=_tool_route_plan(
                [
                    {
                        "route_id": "route-github",
                        "connector_id": "github",
                        "resource_type": "GITHUB_ISSUE",
                        "allowed_read_tool_ids": ["github_list_issues"],
                        "required": True,
                        "reason_codes": [],
                    }
                ]
            ),
            acquisition_result=acquisition,
            evidence_drafts=[],
            retry_budget=budget,
        )["sufficiency"],
    )
    assert result["status"] == expected
    assert result["issues"][0]["route_id"] == "route-github"
    assert "SOURCE_" + code in result["issues"][0]["reason_codes"]
    assert runtime.calls == []
    assert budget == original_budget


def test_assess_sufficiency__emits_a__typed_bounded_disposition() -> None:
    runtime = FakeLLMRuntime(deque([_llm_result(_sufficiency_output("SUFFICIENT"))]))
    result = assess_sufficiency(
        llm_runtime=runtime,
        prompt_ref=replace(SUFFICIENCY_PROMPT_REF, prompt_id="retrieval.assess_sufficiency"),
        requested_mode="AUTO",
        request_intent=_intent(),
        tool_route_plan=_tool_route_plan(),
        acquisition_result=_acquisition_result(),
        evidence_drafts=[
            {
                "schema_version": 1,
                "evidence_id": "evidence-segment-1",
                "resource_handle": "gmail_thread:thread-kim",
                "segment_id": "segment-1",
                "kind": "excerpt",
                "excerpt": "Project Alpha update",
                "locator": {"sender_name": "Kim", "sender_email": "kim@example.test"},
                "reason_codes": ["SUPPORTS"],
            }
        ],
        retry_budget=_run_budget(used=0),
    )

    assert result["status"] == "SUFFICIENT"
    prompt_input = cast(dict[str, object], runtime.calls[0]["prompt_input"])
    assert "confirmation_response" not in prompt_input
    assert set(prompt_input) == {
        "request_intent",
        "selected_evidence",
        "source_statuses",
        "budget_state",
        "temporal_constraints",
    }


def test_retrieval_followup__reentry__charges_one_additional_round() -> None:
    result, budget, should_retrieve_more = authorize_retrieval_followup(
        _sufficiency_output("NEEDS_MORE_DATA"),
        request_intent=_intent(),
        retry_budget=_run_budget(used=0),
        evidence_supported_partial_possible=True,
        can_acquire_new_information=True,
    )

    assert result["status"] == "NEEDS_MORE_DATA"
    assert budget["additional_retrieval_rounds_used"] == 1
    assert should_retrieve_more is True


def test_retrieval_followup__exhausted_read_with_evidence__normalizes_to_partial() -> None:
    result, budget, should_retrieve_more = authorize_retrieval_followup(
        _sufficiency_output("NEEDS_MORE_DATA"),
        request_intent=_intent(),
        retry_budget=_run_budget(used=2),
        evidence_supported_partial_possible=True,
        can_acquire_new_information=True,
    )

    assert result["status"] == "PARTIAL"
    assert budget["additional_retrieval_rounds_used"] == 2
    assert should_retrieve_more is False


def test_retrieval_followup__selected_direct_read_without_new_path__closes() -> None:
    result, budget, should_retrieve_more = authorize_retrieval_followup(
        _sufficiency_output("NEEDS_MORE_DATA"),
        request_intent=_intent(),
        retry_budget=_run_budget(used=0),
        evidence_supported_partial_possible=True,
        can_acquire_new_information=False,
    )

    assert result["status"] == "PARTIAL"
    assert budget["additional_retrieval_rounds_used"] == 0
    assert should_retrieve_more is False


def test_retrieval_followup__empty_read__closes_without_confirmation() -> None:
    result, budget, should_retrieve_more = authorize_retrieval_followup(
        _sufficiency_output("NEEDS_MORE_DATA"),
        request_intent=_intent(),
        retry_budget=_run_budget(used=1),
        evidence_supported_partial_possible=False,
        can_acquire_new_information=False,
    )

    assert result["status"] == "PARTIAL"
    assert budget["additional_retrieval_rounds_used"] == 1
    assert should_retrieve_more is False


def test_assess_sufficiency__complete_selected_gmail_read__skips_llm() -> None:
    runtime = FakeLLMRuntime()
    intent = _intent()
    intent["analysis_requirement"] = "NONE"
    route_plan = _tool_route_plan(
        [
            {
                "route_id": "route-gmail",
                "resource_type": "GMAIL_THREAD",
                "connector_id": "google_workspace",
                "allowed_read_tool_ids": ["gmail_get_thread"],
                "required": True,
                "reason_codes": ["RESOURCE_SELECTED"],
            }
        ]
    )

    result = assess_sufficiency(
        llm_runtime=runtime,
        prompt_ref=SUFFICIENCY_PROMPT_REF,
        requested_mode="LOCAL_GPU",
        request_intent=intent,
        tool_route_plan=route_plan,
        acquisition_result=_acquisition_result(),
        evidence_drafts=[
            {
                "schema_version": 1,
                "evidence_id": "evidence-segment-1",
                "resource_handle": "gmail_thread:thread-kim",
                "segment_id": "segment-1",
                "kind": "excerpt",
                "excerpt": "From: Kim\nSubject: Project\nPlease reply next week.",
                "locator": {},
                "reason_codes": ["SUPPORTS"],
            }
        ],
        retry_budget=_run_budget(used=0),
    )

    assert result == {"schema_version": 2, "status": "SUFFICIENT", "issues": []}
    assert runtime.calls == []


@pytest.mark.parametrize("resource", ["TASK", "CALENDAR_EVENT"])
@pytest.mark.parametrize("incomplete", [None, "failed_route", "missing_route", "source_request"])
def test_assess_sufficiency__only_complete_create_policy_reads__skip_llm(
    resource: str,
    incomplete: str | None,
) -> None:
    runtime = FakeLLMRuntime(deque([_llm_result(_sufficiency_output("SUFFICIENT"))]))
    intent = _intent()
    intent["requested_effect_hints"] = ["CREATE"]
    intent["requested_resource_hints"] = [resource]
    intent["analysis_requirement"] = "NONE"
    routes = [
        {
            "route_id": "calendar-route",
            "resource_type": "CALENDAR",
            "connector_id": "google_workspace",
            "allowed_read_tool_ids": ["calendar_list_calendars"],
            "required": True,
            "reason_codes": ["POLICY_CALENDAR_CONFLICT_CHECK"],
        },
        {
            "route_id": "events-route",
            "resource_type": "CALENDAR_EVENT",
            "connector_id": "google_workspace",
            "allowed_read_tool_ids": ["calendar_list_events"],
            "required": True,
            "reason_codes": ["POLICY_CALENDAR_CONFLICT_CHECK"],
        },
        {
            "route_id": "freebusy-route",
            "resource_type": "CALENDAR_FREEBUSY",
            "connector_id": "google_workspace",
            "allowed_read_tool_ids": ["calendar_query_freebusy"],
            "required": True,
            "reason_codes": ["POLICY_CALENDAR_CONFLICT_CHECK"],
        },
    ]
    if resource == "TASK":
        routes = [
            {
                "route_id": "task-route",
                "resource_type": "TASK",
                "connector_id": "google_workspace",
                "allowed_read_tool_ids": ["tasks_list_tasks"],
                "required": True,
                "reason_codes": ["POLICY_TASK_DUPLICATE_CHECK"],
            },
            {
                "route_id": "list-route",
                "resource_type": "TASK_LIST",
                "connector_id": "google_workspace",
                "allowed_read_tool_ids": ["tasks_list_tasklists"],
                "required": True,
                "reason_codes": ["POLICY_TASK_DUPLICATE_CHECK"],
            },
        ]
    route_plan = _tool_route_plan(routes)
    route_plan["output_plan"] = {
        "schema_version": 1,
        "meta": {"artifact_id": "route-out-1", "revision": 1, "based_on": []},
        "output_mode": "ACTION",
        "output_routes": [
            {
                "route_id": "create-route",
                "resource_type": resource,
                "connector_id": "google_workspace",
                "effect": "CREATE",
                "selected_tool_id": (
                    "tasks_create_task" if resource == "TASK" else "calendar_create_event"
                ),
                "reason_codes": ["REGISTRY_SINGLE_CANDIDATE"],
            }
        ],
    }
    acquisition = _acquisition_result()
    acquisition["resource_handles"] = ["calendar:primary", "calendar_freebusy:primary:hash"]
    acquisition["source_summaries"] = [
        {
            "route_id": route["route_id"],
            "source": "TASKS" if resource == "TASK" else "CALENDAR",
            "status": "COMPLETE",
            "required": True,
            "resource_count": 0 if route["resource_type"] == "CALENDAR_EVENT" else 1,
            "resource_handles": [],
            "resources": [],
        }
        for route in routes
    ]

    if incomplete == "failed_route":
        acquisition["source_summaries"][0]["status"] = "FAILED"
    elif incomplete == "missing_route":
        acquisition["source_summaries"].pop()
    elif incomplete == "source_request":
        route_plan["input_plan"]["input_routes"][0]["reason_codes"] = ["USER_REQUESTED"]

    result = assess_sufficiency(
        llm_runtime=runtime,
        prompt_ref=SUFFICIENCY_PROMPT_REF,
        requested_mode="LOCAL_GPU",
        request_intent=intent,
        tool_route_plan=route_plan,
        acquisition_result=acquisition,
        evidence_drafts=[],
        retry_budget=_run_budget(used=0),
    )

    if incomplete is None:
        assert result == {"schema_version": 2, "status": "SUFFICIENT", "issues": []}
        assert runtime.calls == []
    else:
        assert result["status"] != "SUFFICIENT"
        assert len(runtime.calls) == 1


def test_assess_sufficiency__rejects_required_lookup__without_evidence() -> None:
    runtime = FakeLLMRuntime(deque([_llm_result(_sufficiency_output("SUFFICIENT"))]))
    acquisition = _acquisition_result()

    result = assess_sufficiency(
        llm_runtime=runtime,
        prompt_ref=SUFFICIENCY_PROMPT_REF,
        requested_mode="LOCAL_GPU",
        request_intent=_intent(),
        tool_route_plan=_tool_route_plan(),
        acquisition_result=acquisition,
        evidence_drafts=[],
        retry_budget=_run_budget(used=0),
    )

    assert result["status"] == "NEEDS_MORE_DATA"
    assert result["issues"][-1]["reason_codes"] == ["REQUIRED_SOURCE_HAS_NO_RELEVANT_EVIDENCE"]


@pytest.mark.parametrize("failed", [False, True])
def test_empty_acquisition__failure_or_zero_results__keeps_reason_without_model(
    failed: bool,
) -> None:
    acquisition = _acquisition_result()
    acquisition["source_summaries"][0].update(
        status="FAILED" if failed else "COMPLETE",
        resource_count=0,
        resource_handles=[],
    )
    if failed:
        acquisition["source_summaries"][0]["error_code"] = "PERMISSION_DENIED"
    runtime = FakeLLMRuntime(deque())
    result = assess_sufficiency(
        llm_runtime=runtime,
        prompt_ref=SUFFICIENCY_PROMPT_REF,
        requested_mode="LOCAL_GPU",
        request_intent=_intent(),
        tool_route_plan=_tool_route_plan(),
        acquisition_result=acquisition,
        evidence_drafts=[],
        retry_budget=_run_budget(used=0),
    )
    reasons = {code for issue in result["issues"] for code in issue["reason_codes"]}
    expected_reason = (
        "SOURCE_PERMISSION_DENIED" if failed else "REQUIRED_SOURCE_RETURNED_NO_RESOURCES"
    )
    assert expected_reason in reasons
    assert ("REQUIRED_SOURCE_RETURNED_NO_RESOURCES" in reasons) is not failed
    assert runtime.calls == []


@pytest.mark.parametrize("mail_count", [0, 1])
def test_mail_to_task__empty_mail__does_not_substitute_task_policy_evidence(
    mail_count: int,
) -> None:
    runtime = FakeLLMRuntime(deque([_llm_result(_sufficiency_output("SUFFICIENT"))]))
    acquisition = _acquisition_result()
    acquisition["source_summaries"][0]["resource_count"] = mail_count
    acquisition["source_summaries"][0]["resource_handles"] = []
    acquisition["resource_handles"] = ["task:existing"]
    intent = _intent()
    intent["requested_effect_hints"] = ["READ", "CREATE"]
    result = assess_sufficiency(
        llm_runtime=runtime,
        prompt_ref=SUFFICIENCY_PROMPT_REF,
        requested_mode="LOCAL_GPU",
        request_intent=intent,
        tool_route_plan=_tool_route_plan(),
        acquisition_result=acquisition,
        evidence_drafts=[
            {
                "schema_version": 1,
                "evidence_id": "e-task",
                "resource_handle": "task:existing",
                "segment_id": "s-task",
                "kind": "excerpt",
                "excerpt": "기존 태스크",
                "locator": {},
                "reason_codes": ["SUPPORTS"],
            }
        ],
        retry_budget=_run_budget(used=0),
    )
    assert result["status"] == "NEEDS_MORE_DATA"
    assert result["issues"][-1]["reason_codes"] == [
        "REQUIRED_SOURCE_RETURNED_NO_RESOURCES"
        if mail_count == 0
        else "REQUIRED_SOURCE_HAS_NO_RELEVANT_EVIDENCE"
    ]


@pytest.mark.parametrize(
    "analysis,axis,used,person,concept",
    [
        ("REQUIRED", "MESSAGE_TIME", 0, False, False),
        ("NONE", "EVENT_TIME", 0, False, False),
        ("NONE", "EVENT_TIME", 2, False, False),
        ("NONE", "MESSAGE_TIME", 0, True, False),
        ("NONE", "MESSAGE_TIME", 0, False, True),
    ],
)
def test_assess_sufficiency__analysis_request__requires_each_selected_thread_detail(
    analysis: Literal["NONE", "REQUIRED"],
    axis: str,
    used: int,
    person: bool,
    concept: bool,
) -> None:
    runtime = FakeLLMRuntime(deque([_llm_result(_sufficiency_output("SUFFICIENT"))]))
    intent = _intent()
    intent["analysis_requirement"] = analysis
    intent["constraints"] = [{"kind": "TIME", "field": "temporal_axis", "value": axis}]
    if person:
        intent["constraints"].append({"kind": "PERSON", "field": "person", "value": "김대리"})
    if concept:
        intent["constraints"].append(
            {"kind": "USER_REQUIREMENT", "field": "business_concepts", "value": ["일정"]}
        )
    intent["requested_effect_hints"] = ["READ"]
    intent["requested_resource_hints"] = ["GMAIL_THREAD"]
    route_plan = _tool_route_plan(
        [
            {
                "route_id": "route-gmail",
                "resource_type": "GMAIL_THREAD",
                "connector_id": "google_workspace",
                "allowed_read_tool_ids": ["gmail_search_threads", "gmail_get_thread"],
                "required": True,
                "reason_codes": ["REGISTRY_SINGLE_CANDIDATE"],
            }
        ]
    )
    evidence: list[EvidenceDraftV1] = [
        {
            "schema_version": 1,
            "evidence_id": f"evidence-{name}",
            "resource_handle": f"gmail_thread:{name}",
            "segment_id": f"segment-{name}",
            "kind": "excerpt",
            "excerpt": f"KAN-93 {name}",
            "locator": {"sender_name": "Kim", "sender_email": "kim@example.test"},
            "reason_codes": ["SUPPORTS"],
        }
        for name in ("first", "second")
    ]
    acquisition = _acquisition_result()
    acquisition["source_summaries"][0]["resource_handles"] = [
        item["resource_handle"] for item in evidence
    ]

    result = assess_sufficiency(
        llm_runtime=runtime,
        prompt_ref=SUFFICIENCY_PROMPT_REF,
        requested_mode="LOCAL_GPU",
        request_intent=intent,
        tool_route_plan=route_plan,
        acquisition_result=acquisition,
        evidence_drafts=evidence,
        retry_budget=_run_budget(used=used),
        attempted_detail_candidate_refs=["gmail_thread:first"],
    )

    assert result["status"] == "NEEDS_MORE_DATA"
    assert result["issues"][-1]["reason_codes"] == ["CANDIDATE_DETAIL_REQUIRED"]


@pytest.mark.parametrize("detail_used,allowed", [(0, True), (12, False)])
def test_detail_followup__hydration_only__does_not_charge_search_rounds(
    detail_used: int, allowed: bool
) -> None:
    budget = _run_budget(used=2)
    budget["detail_fetches_used"] = detail_used
    result, updated, followup = authorize_retrieval_followup(
        _sufficiency_output("NEEDS_MORE_DATA"),
        request_intent=_intent(),
        retry_budget=budget,
        evidence_supported_partial_possible=True,
        can_acquire_new_information=True,
        detail_fetch_count=1,
    )
    assert followup is allowed
    assert updated == budget
    assert result["status"] == ("NEEDS_MORE_DATA" if allowed else "PARTIAL")


def test_assess_sufficiency__safety_critical_gap__blocks_before_candidate_detail() -> None:
    blocked_google_gap = {
        "schema_version": 2,
        "status": "BLOCKED",
        "issues": [
            {
                "slot": "latest_decision",
                "issue_type": "MISSING",
                "required": True,
                "resolution_source": "GOOGLE",
                "safety_critical": True,
                "reason_codes": ["CONTENT_NOT_EXPOSED"],
            }
        ],
    }
    runtime = FakeLLMRuntime(deque([_llm_result(blocked_google_gap)]))
    intent = _intent()
    intent["analysis_requirement"] = "REQUIRED"
    intent["requested_effect_hints"] = ["READ"]
    intent["requested_resource_hints"] = ["GMAIL_THREAD"]
    route_plan = _tool_route_plan(
        [
            {
                "route_id": "route-gmail",
                "resource_type": "GMAIL_THREAD",
                "connector_id": "google_workspace",
                "allowed_read_tool_ids": ["gmail_search_threads", "gmail_get_thread"],
                "required": True,
                "reason_codes": ["REGISTRY_SINGLE_CANDIDATE"],
            }
        ]
    )

    result = assess_sufficiency(
        llm_runtime=runtime,
        prompt_ref=SUFFICIENCY_PROMPT_REF,
        requested_mode="LOCAL_GPU",
        request_intent=intent,
        tool_route_plan=route_plan,
        acquisition_result=_acquisition_result(),
        evidence_drafts=[
            {
                "schema_version": 1,
                "evidence_id": "evidence-first",
                "resource_handle": "gmail_thread:first",
                "segment_id": "segment-first",
                "kind": "excerpt",
                "excerpt": "KAN-93 metadata",
                "locator": {},
                "reason_codes": ["SUPPORTS"],
            }
        ],
        retry_budget=_run_budget(used=0),
    )

    assert result["status"] == "BLOCKED"
    assert result["issues"][0]["safety_critical"] is True
    assert result["issues"][-1]["reason_codes"] == ["CANDIDATE_DETAIL_REQUIRED"]


def test_assess_sufficiency__all_candidate_details_acquired__accepts_analysis() -> None:
    runtime = FakeLLMRuntime(deque([_llm_result(_sufficiency_output("SUFFICIENT"))]))
    intent = _intent()
    intent["analysis_requirement"] = "REQUIRED"
    intent["requested_effect_hints"] = ["READ"]
    intent["requested_resource_hints"] = ["GMAIL_THREAD"]
    route_plan = _tool_route_plan(
        [
            {
                "route_id": "route-gmail",
                "resource_type": "GMAIL_THREAD",
                "connector_id": "google_workspace",
                "allowed_read_tool_ids": ["gmail_search_threads", "gmail_get_thread"],
                "required": True,
                "reason_codes": ["REGISTRY_SINGLE_CANDIDATE"],
            }
        ]
    )
    evidence: list[EvidenceDraftV1] = [
        {
            "schema_version": 1,
            "evidence_id": f"evidence-{name}",
            "resource_handle": f"gmail_thread:{name}",
            "segment_id": f"segment-{name}",
            "kind": "excerpt",
            "excerpt": f"KAN-93 {name}",
            "locator": {"sender_name": "Kim", "sender_email": "kim@example.test"},
            "reason_codes": ["SUPPORTS"],
        }
        for name in ("first", "second")
    ]

    acquisition = _acquisition_result()
    acquisition["source_summaries"][0]["resource_handles"] = [
        item["resource_handle"] for item in evidence
    ]
    result = assess_sufficiency(
        llm_runtime=runtime,
        prompt_ref=SUFFICIENCY_PROMPT_REF,
        requested_mode="LOCAL_GPU",
        request_intent=intent,
        tool_route_plan=route_plan,
        acquisition_result=acquisition,
        evidence_drafts=evidence,
        retry_budget=_run_budget(used=0),
        attempted_detail_candidate_refs=["gmail_thread:first", "gmail_thread:second"],
    )

    assert result == {"schema_version": 2, "status": "SUFFICIENT", "issues": []}


def test_assess_sufficiency__read_only_connector_gap__cannot_become_user_confirmation() -> None:
    runtime = FakeLLMRuntime(deque([_llm_result(_sufficiency_output("NEEDS_CONFIRMATION"))]))
    acquisition = _acquisition_result()
    acquisition["resource_handles"] = []
    acquisition["source_summaries"][0]["resource_count"] = 0
    acquisition["source_summaries"][0]["resource_handles"] = []

    result = assess_sufficiency(
        llm_runtime=runtime,
        prompt_ref=SUFFICIENCY_PROMPT_REF,
        requested_mode="LOCAL_GPU",
        request_intent=_intent(),
        tool_route_plan=_tool_route_plan(),
        acquisition_result=acquisition,
        evidence_drafts=[],
        retry_budget=_run_budget(used=0),
    )

    assert result["status"] == "NEEDS_MORE_DATA"
    assert {issue["resolution_source"] for issue in result["issues"]} == {"GOOGLE"}


def test_assess_sufficiency__new_candidate_conflict__remains_a_user_choice() -> None:
    conflict = {
        "schema_version": 2,
        "status": "NEEDS_CONFIRMATION",
        "issues": [
            {
                "slot": "matching_resource",
                "issue_type": "CONFLICT",
                "required": True,
                "resolution_source": "USER",
                "safety_critical": False,
                "reason_codes": ["MULTIPLE_MATCHING_RESOURCES"],
            }
        ],
    }
    runtime = FakeLLMRuntime(deque([_llm_result(conflict)]))

    result = assess_sufficiency(
        llm_runtime=runtime,
        prompt_ref=SUFFICIENCY_PROMPT_REF,
        requested_mode="LOCAL_GPU",
        request_intent=_intent(),
        tool_route_plan=_tool_route_plan(),
        acquisition_result=_acquisition_result(),
        evidence_drafts=[
            {
                "schema_version": 1,
                "evidence_id": "e1",
                "resource_handle": "gmail_thread:one",
                "segment_id": "s1",
                "kind": "excerpt",
                "excerpt": "candidate one",
                "locator": {},
                "reason_codes": ["CONTEXT"],
            }
        ],
        retry_budget=_run_budget(used=0),
        attempted_detail_candidate_refs=["gmail_thread:one"],
    )

    assert result["status"] == "NEEDS_CONFIRMATION"
    assert result["issues"][0]["resolution_source"] == "USER"


def test_observed_person_candidates__introduce_user_choice__after_clear_request() -> None:
    intent = _intent()
    intent["ambiguity"] = {
        "requires_confirmation": False,
        "missing_fields": [],
        "ambiguous_fields": [],
    }
    candidates = [
        {
            "mention": "김대리",
            "identity": identity,
            "display_names": [display],
            "source_segment_ids": [segment],
        }
        for identity, display, segment in (
            ("first@example.test", "김민수", "segment-1"),
            ("second@example.test", "김민지", "segment-2"),
        )
    ]

    result = deterministic_sufficiency(
        request_intent=intent,
        tool_route_plan=_tool_route_plan(),
        acquisition_result=_acquisition_result(),
        evidence_drafts=[],
        retry_budget=_run_budget(used=0),
        person_candidates=candidates,
    )

    assert result is not None
    assert result["status"] == "NEEDS_CONFIRMATION"
    assert result["issues"][0]["reason_codes"] == ["PERSON_IDENTITY_AMBIGUOUS"]


def test_github_issue_insufficiency__with_frozen_route__uses_connector() -> None:
    issue = {
        "slot": "issue details",
        "issue_type": "MISSING",
        "required": True,
        "resolution_source": "CONNECTOR",
        "safety_critical": False,
        "reason_codes": ["DETAIL_REQUIRED"],
    }
    runtime = FakeLLMRuntime(
        deque([_llm_result({"schema_version": 2, "status": "NEEDS_MORE_DATA", "issues": [issue]})])
    )
    route_plan = _tool_route_plan(
        [
            {
                "route_id": "route-github",
                "resource_type": "GITHUB_ISSUE",
                "connector_id": "github",
                "allowed_read_tool_ids": ["github_list_issues"],
                "required": True,
                "reason_codes": ["USER_REQUEST"],
            }
        ]
    )
    original_route_plan = deepcopy(route_plan)
    acquisition = cast(
        AcquisitionResultV1,
        {
            "schema_version": 1,
            "status": "COMPLETE",
            "resource_handles": ["github_issue:acme/repo#7"],
            "source_summaries": [
                {
                    "route_id": "route-github",
                    "source": "GITHUB",
                    "status": "COMPLETE",
                    "resource_handles": ["github_issue:acme/repo#7"],
                    "resources": [],
                }
            ],
            "missing_slots": [],
            "remaining_budget": {},
        },
    )

    result = assess_sufficiency(
        llm_runtime=runtime,
        prompt_ref=SUFFICIENCY_PROMPT_REF,
        requested_mode="AUTO",
        request_intent=_intent(),
        tool_route_plan=route_plan,
        acquisition_result=acquisition,
        evidence_drafts=[],
        retry_budget=_run_budget(used=0),
    )

    prompt_input = cast(dict[str, object], runtime.calls[0]["prompt_input"])
    source_statuses = cast(list[dict[str, object]], prompt_input["source_statuses"])
    output_schema = cast(OutputSchemaDefinition, runtime.calls[0]["output_schema"])
    schema_properties = cast(dict[str, object], output_schema.json_schema["properties"])
    issues_schema = cast(dict[str, object], schema_properties["issues"])
    issue_schema = cast(dict[str, object], issues_schema["items"])
    issue_properties = cast(dict[str, object], issue_schema["properties"])
    resolution_schema = cast(dict[str, object], issue_properties["resolution_source"])
    resolution_enum = cast(list[str], resolution_schema["enum"])
    assert result["status"] == "NEEDS_MORE_DATA"
    assert result["issues"][0]["resolution_source"] == "CONNECTOR"
    assert source_statuses == [
        {
            "route_id": "route-github",
            "resource_type": "ISSUE",
            "status": "COMPLETE",
            "failure_kind": None,
        }
    ]
    assert "CONNECTOR" in resolution_enum
    assert "GOOGLE" not in resolution_enum
    assert route_plan == original_route_plan
    projected = missing_information_projection(result["issues"])[0]
    assert projected["required_for"] == "RETRIEVAL"
    assert projected["reason_codes"] == result["issues"][0]["reason_codes"]


def test_google_insufficiency__with_existing_source__retains_google() -> None:
    runtime = FakeLLMRuntime(deque([_llm_result(_sufficiency_output("NEEDS_MORE_DATA"))]))

    result = assess_sufficiency(
        llm_runtime=runtime,
        prompt_ref=SUFFICIENCY_PROMPT_REF,
        requested_mode="AUTO",
        request_intent=_intent(),
        tool_route_plan=_tool_route_plan(),
        acquisition_result=_acquisition_result(),
        evidence_drafts=[],
        retry_budget=_run_budget(used=0),
    )

    assert result["status"] == "NEEDS_MORE_DATA"
    assert result["issues"][0]["resolution_source"] == "GOOGLE"
    output_schema = cast(OutputSchemaDefinition, runtime.calls[0]["output_schema"])
    schema_properties = cast(dict[str, object], output_schema.json_schema["properties"])
    issues_schema = cast(dict[str, object], schema_properties["issues"])
    issue_schema = cast(dict[str, object], issues_schema["items"])
    issue_properties = cast(dict[str, object], issue_schema["properties"])
    resolution_schema = cast(dict[str, object], issue_properties["resolution_source"])
    resolution_enum = cast(list[str], resolution_schema["enum"])
    assert "GOOGLE" in resolution_enum
    assert "CONNECTOR" not in resolution_enum


@pytest.mark.parametrize(
    "tool", ["github_update_issue", "github_close_issue", "github_reopen_issue"]
)
@pytest.mark.parametrize(
    "gap",
    [
        None,
        "no_evidence",
        "wrong_issue",
        "partial",
        "ambiguous",
        "analysis",
        "other_source",
        "other_output",
        "missing_slot",
    ],
)
def test_selected_resource_mutation__complete_target_read__does_not_require_future_values(
    tool: str, gap: str | None
) -> None:
    intent = _intent()
    intent["analysis_requirement"] = "NONE"
    intent["requested_effect_hints"] = ["UPDATE"]
    intent["constraints"] = [
        {"kind": "RESOURCE", "field": "selected_resource_id", "value": ["owner/repo#7"]}
    ]
    route = {
        "route_id": "route-github",
        "resource_type": "GITHUB_ISSUE",
        "connector_id": "github",
        "allowed_read_tool_ids": ["github_get_issue"],
        "required": True,
        "reason_codes": ["RESOURCE_SELECTED"],
    }
    plan = _tool_route_plan([route])
    plan["output_plan"] = {
        "schema_version": 1,
        "meta": plan["input_plan"]["meta"],
        "output_mode": "ACTION",
        "output_routes": [
            {
                "route_id": "out-github",
                "resource_type": "GITHUB_ISSUE",
                "connector_id": "github",
                "effect": "UPDATE",
                "selected_tool_id": tool,
                "reason_codes": [],
            }
        ],
    }
    acquisition = _acquisition_result()
    acquisition["resource_handles"] = ["github_issue:owner/repo#7"]
    acquisition["source_summaries"] = [
        {
            "route_id": "route-github",
            "connector_id": "github",
            "source": "GITHUB",
            "status": "COMPLETE",
            "resource_handles": ["github_issue:owner/repo#7"],
            "resource_count": 1,
        }
    ]
    evidence: list[EvidenceDraftV1] = [
        {
            "schema_version": 1,
            "evidence_id": "e1",
            "resource_handle": "github_issue:owner/repo#7",
            "segment_id": "s1",
            "kind": "excerpt",
            "excerpt": "Current title, body and open state",
            "locator": {},
            "reason_codes": ["SUPPORTS"],
        }
    ]
    if gap == "no_evidence":
        evidence.clear()
    elif gap == "wrong_issue":
        evidence[0]["resource_handle"] = "github_issue:owner/repo#8"
    elif gap == "partial":
        acquisition["status"] = "PARTIAL"
    elif gap == "ambiguous":
        intent["ambiguity"]["requires_confirmation"] = True
    elif gap == "analysis":
        intent["analysis_requirement"] = "REQUIRED"
    elif gap == "other_source":
        plan["input_plan"]["input_routes"].append(
            {**plan["input_plan"]["input_routes"][0], "route_id": "other"}
        )
    elif gap == "other_output":
        action_output = cast(ActionOutputPlanV1, plan["output_plan"])
        action_output["output_routes"].append(
            {**action_output["output_routes"][0], "route_id": "other"}
        )
    elif gap == "missing_slot":
        acquisition["missing_slots"] = ["target"]
    result = deterministic_sufficiency(
        request_intent=intent,
        tool_route_plan=plan,
        acquisition_result=acquisition,
        evidence_drafts=evidence,
        retry_budget=_run_budget(used=0),
    )
    if gap is not None:
        assert result is None
    else:
        assert result == {"schema_version": 2, "status": "SUFFICIENT", "issues": []}


@pytest.mark.parametrize(
    ("resource_type", "effect", "identity", "handle", "tool"),
    [
        ("TASK", "UPDATE", "task-1", "task:task-1", "tasks_update_task"),
        (
            "CALENDAR_EVENT",
            "UPDATE",
            "event-1",
            "calendar_event:event-1",
            "calendar_update_event",
        ),
        (
            "CALENDAR_EVENT",
            "DELETE",
            "event-1",
            "calendar_event:event-1",
            "calendar_delete_event",
        ),
    ],
)
def test_selected_google_resource_action__complete_detail_read__is_sufficient(
    resource_type: str,
    effect: Literal["UPDATE", "DELETE"],
    identity: str,
    handle: str,
    tool: str,
) -> None:
    intent = _intent()
    intent["analysis_requirement"] = "NONE"
    intent["requested_effect_hints"] = ["READ", effect]
    intent["constraints"] = [
        {"kind": "RESOURCE", "field": "selected_resource_id", "value": [identity]}
    ]
    route = {
        "route_id": "route-selected",
        "resource_type": resource_type,
        "connector_id": "google_workspace",
        "allowed_read_tool_ids": ["selected_detail_tool"],
        "required": True,
        "reason_codes": ["RESOURCE_SELECTED"],
    }
    plan = _tool_route_plan([route])
    plan["output_plan"] = {
        "schema_version": 1,
        "meta": plan["input_plan"]["meta"],
        "output_mode": "ACTION",
        "output_routes": [
            {
                "route_id": "out-selected",
                "resource_type": resource_type,
                "connector_id": "google_workspace",
                "effect": effect,
                "selected_tool_id": tool,
                "reason_codes": [],
            }
        ],
    }
    acquisition = _acquisition_result()
    acquisition["resource_handles"] = [handle]
    acquisition["source_summaries"] = [
        {
            "route_id": "route-selected",
            "connector_id": "google_workspace",
            "source": "TASKS" if resource_type == "TASK" else "CALENDAR",
            "status": "COMPLETE",
            "resource_handles": [handle],
            "resource_count": 1,
        }
    ]
    evidence = [
        cast(
            EvidenceDraftV1,
            {
                "schema_version": 1,
                "evidence_id": "e1",
                "resource_handle": handle,
                "segment_id": "s1",
                "kind": "excerpt",
                "excerpt": "current provider detail",
                "locator": {},
                "reason_codes": ["SUPPORTS"],
            },
        )
    ]

    result = deterministic_sufficiency(
        request_intent=intent,
        tool_route_plan=plan,
        acquisition_result=acquisition,
        evidence_drafts=evidence,
        retry_budget=_run_budget(used=0),
    )

    assert result == {"schema_version": 2, "status": "SUFFICIENT", "issues": []}
