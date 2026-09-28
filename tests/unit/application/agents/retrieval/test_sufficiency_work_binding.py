"""Sufficiency must consume frozen route ownership, not reconstruct it from prose."""

from collections import deque
from copy import deepcopy
from typing import Any, cast

import pytest
from tests.support.context_retrieval import (
    SUFFICIENCY_PROMPT_REF,
    FakeLLMRuntime,
    acquisition_result,
    llm_result,
    request_intent,
    run_budget,
    sufficiency_result_fixture,
    tool_route_plan,
)

from google_work_agent.application.agents.request_understanding.validate_intent import (
    validate_intent,
)
from google_work_agent.application.agents.retrieval.assess_sufficiency import (
    assess_sufficiency,
    source_statuses_prompt_projection,
)


def test_sufficiency_input_preserves_frozen_shared_read_work_binding() -> None:
    spans = [
        "Summarize the first email body.",
        "Summarize the second email body.",
        "Summarize the task notes.",
    ]
    request = " ".join(spans)
    intent = request_intent()
    intent.update(
        goal=request,
        completion_conditions=spans,
        constraints=[
            {
                "kind": "USER_REQUIREMENT",
                "field": "required_information",
                "value": [information],
                "work_unit_ids": units,
            }
            for information, units in (("body", ["work-1", "work-2"]), ("notes", ["work-3"]))
        ],
        requested_resource_hints=["GMAIL_THREAD", "TASK"],
        requested_work={
            "work_units": [
                {
                    "unit_id": f"work-{index}",
                    "request_provenance": [
                        {
                            "source": "USER_REQUEST",
                            "start_offset": request.index(span),
                            "end_offset": request.index(span) + len(span),
                            "source_text": span,
                        }
                    ],
                }
                for index, span in enumerate(spans, 1)
            ],
            "work_relations": [],
        },
        resource_responsibilities={
            "source_reads": [
                {
                    "resource_type": resource,
                    "required_information": [information],
                    "target_scope": "CRITERIA",
                    "work_unit_ids": units,
                }
                for resource, information, units in (
                    ("GMAIL_THREAD", "body", ["work-1", "work-2"]),
                    ("TASK", "notes", ["work-3"]),
                )
            ],
            "outputs": [],
        },
    )
    intent = validate_intent(
        intent, require_meta=True, provenance_sources={"USER_REQUEST": request}
    )
    routes = tool_route_plan(
        [
            {
                "route_id": route_id,
                "resource_type": resource,
                "connector_id": "google_workspace",
                "allowed_read_tool_ids": [tool],
                "required": True,
                "reason_codes": ["REQUESTED_INPUT"],
                "work_unit_ids": units,
            }
            for route_id, resource, tool, units in (
                ("mail-route", "GMAIL_THREAD", "gmail_get_thread", ["work-1", "work-2"]),
                ("task-route", "TASK", "tasks_get_task", ["work-3"]),
            )
        ]
    )
    acquisition = acquisition_result()
    acquisition["source_summaries"][0]["route_id"] = "mail-route"
    evidence = [
        {
            "schema_version": 1,
            "evidence_id": "mail-evidence",
            "resource_handle": "gmail_thread:thread-kim",
            "segment_id": "mail-segment",
            "kind": "excerpt",
            "excerpt": "The acquired email contains a project update.",
            "locator": {"is_metadata_only": False},
            "reason_codes": ["SUPPORTS"],
        }
    ]
    before = deepcopy((intent, routes, acquisition, evidence))
    runtime = FakeLLMRuntime(deque([llm_result(sufficiency_result_fixture("NEEDS_MORE_DATA"))]))

    assess_sufficiency(
        llm_runtime=runtime,
        prompt_ref=SUFFICIENCY_PROMPT_REF,
        requested_mode="LOCAL_GPU",
        request_intent=intent,
        tool_route_plan=routes,
        acquisition_result=acquisition,
        evidence_drafts=cast(Any, evidence),
        retry_budget=run_budget(used=0),
    )

    assert len(runtime.calls) == 1
    assert (intent, routes, acquisition, evidence) == before
    projection = cast(dict[str, Any], runtime.calls[0]["prompt_input"])
    assert projection["request_intent"] == intent
    assert len(projection["selected_evidence"]) == 1
    assert {
        item["route_id"]: item.get("work_unit_ids") for item in projection["source_statuses"]
    } == {"mail-route": ["work-1", "work-2"], "task-route": ["work-3"]}


@pytest.mark.parametrize(
    ("acquired_status", "expected_status"),
    [
        ("COMPLETE", "COMPLETE"),
        ("PARTIAL", "PARTIAL"),
        ("FAILED", "FAILED"),
        (None, "NOT_ATTEMPTED"),
    ],
)
def test_source_status_keeps_binding_independent_of_acquisition_success(
    acquired_status: str | None, expected_status: str
) -> None:
    routes = tool_route_plan()
    route = routes["input_plan"]["input_routes"][0]
    route["work_unit_ids"] = ["work-1", "work-2"]
    acquisition = acquisition_result()
    if acquired_status is None:
        acquisition["source_summaries"] = []
    else:
        acquisition["source_summaries"][0]["status"] = acquired_status
    projection = source_statuses_prompt_projection(
        tool_route_plan=routes,
        acquisition_result=acquisition,
        known_work_unit_ids=["work-1", "work-2"],
    )
    assert len(projection) == 1
    assert projection[0]["route_id"] == route["route_id"]
    assert projection[0]["work_unit_ids"] == ["work-1", "work-2"]
    assert projection[0]["status"] == expected_status
    cast(list[str], projection[0]["work_unit_ids"]).append("local-only")
    assert route["work_unit_ids"] == ["work-1", "work-2"]


def test_legacy_unbound_route_does_not_invent_work_membership() -> None:
    routes = tool_route_plan()
    cast(dict[str, object], routes["input_plan"]["input_routes"][0]).pop("work_unit_ids")
    projection = source_statuses_prompt_projection(
        tool_route_plan=routes,
        acquisition_result=acquisition_result(),
    )
    assert len(projection) == 1
    assert "work_unit_ids" not in projection[0]


@pytest.mark.parametrize("routes", [None, tool_route_plan([])])
def test_no_input_route_has_no_invented_status_or_work_binding(routes: Any) -> None:
    assert (
        source_statuses_prompt_projection(
            tool_route_plan=routes,
            acquisition_result=acquisition_result(),
            known_work_unit_ids=["work-1"],
        )
        == []
    )


def test_unknown_route_work_id_is_rejected_before_sufficiency_llm_call() -> None:
    routes = tool_route_plan()
    routes["input_plan"]["input_routes"][0]["work_unit_ids"] = ["unknown-work"]
    runtime = FakeLLMRuntime(deque())
    with pytest.raises(ValueError, match="unknown WorkUnit"):
        assess_sufficiency(
            llm_runtime=runtime,
            prompt_ref=SUFFICIENCY_PROMPT_REF,
            requested_mode="LOCAL_GPU",
            request_intent=request_intent(),
            tool_route_plan=routes,
            acquisition_result=acquisition_result(),
            evidence_drafts=[],
            retry_budget=run_budget(used=0),
        )
    assert runtime.calls == []


@pytest.mark.parametrize("work_ids", [[], ["work-1", "work-1"], [""], "work-1"])
def test_invalid_work_binding_is_not_normalized_into_an_invented_valid_set(work_ids: Any) -> None:
    routes = tool_route_plan()
    routes["input_plan"]["input_routes"][0]["work_unit_ids"] = work_ids
    with pytest.raises(ValueError, match="unique non-empty WorkUnit"):
        source_statuses_prompt_projection(
            tool_route_plan=routes,
            acquisition_result=acquisition_result(),
            known_work_unit_ids=["work-1"],
        )
