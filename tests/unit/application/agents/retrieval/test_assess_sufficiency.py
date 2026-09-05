from collections import deque
from copy import deepcopy
from dataclasses import replace
from typing import cast

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

from google_work_agent.application.agents.retrieval.assess_sufficiency import (
    SUFFICIENCY_OUTPUT_SCHEMA,
    assess_sufficiency,
    missing_information_projection,
)
from google_work_agent.application.agents.retrieval.contracts.retrieval_result import (
    AcquisitionResultV1,
)


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
                "locator": {},
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
    }


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
    schema_properties = cast(dict[str, object], SUFFICIENCY_OUTPUT_SCHEMA.json_schema["properties"])
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
    assert route_plan == original_route_plan
    assert missing_information_projection(result["issues"])[0]["required_for"] == "RETRIEVAL"


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
