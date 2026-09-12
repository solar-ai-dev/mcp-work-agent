from typing import cast

from tests.support.context_retrieval import (
    _acquisition_result,
    _intent,
    _selection_output,
    _sufficiency_output,
    _tool_route_plan,
)

from google_work_agent.application.agents.retrieval.contracts.query_attempt import QueryAttemptV1
from google_work_agent.application.agents.retrieval.contracts.retrieval_result import (
    AcquisitionResultV1,
    EvidenceDraftV1,
    RetrievalResultV1,
)
from google_work_agent.application.agents.retrieval.finalize_retrieval import (
    finalize_retrieval,
)


def test_finalize_retrieval__unresolved_event_year__cannot_report_sufficient_coverage() -> None:
    result = finalize_retrieval(
        artifact_id="retrieval-yearless",
        request_intent=_intent(),
        tool_route_plan=_tool_route_plan(),
        acquisition_result=_acquisition_result(),
        selection_result=_selection_output(["segment-1"]),
        evidence_drafts=[
            {
                "schema_version": 1,
                "evidence_id": "e1",
                "resource_handle": "gmail_thread:thread-kim",
                "segment_id": "segment-1",
                "kind": "excerpt",
                "excerpt": "연수는 9월 4일입니다.",
                "locator": {},
                "reason_codes": ["SUPPORTS"],
            }
        ],
        sufficiency_result=_sufficiency_output("SUFFICIENT"),
        current_round_no=1,
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
    assert result["unresolved_event_dates"] == [{"evidence_id": "e1", "source_text": "9월 4일"}]
    assert result["coverage"] == "PARTIAL"
    assert result["evidence_refs"] == ["e1"]


def test_finalize_retrieval__preserves_full_contract__and_revision_lineage() -> None:
    prior = cast(
        RetrievalResultV1,
        {
            "schema_version": 1,
            "meta": {"artifact_id": "retrieval-1", "revision": 2, "based_on": []},
            "coverage": "PARTIAL",
            "context_bundle_ref": None,
            "evidence_refs": [],
            "selected_segment_ids": [],
            "excluded_segment_ids": ["segment-old"],
            "source_resource_refs": [],
            "source_statuses": [],
            "availability_results": [],
            "missing_information": [],
            "retrieval_rounds": 1,
        },
    )
    selection = _selection_output(["segment-1"])
    selection["excluded_segment_ids"] = ["segment-model"]
    result = finalize_retrieval(
        artifact_id="unused-new-id",
        request_intent=_intent(),
        tool_route_plan=_tool_route_plan(),
        acquisition_result=_acquisition_result(),
        selection_result=selection,
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
        sufficiency_result=_sufficiency_output("SUFFICIENT"),
        current_round_no=2,
        availability_results=[
            {
                "start": "2026-08-31T09:00:00+09:00",
                "end": "2026-08-31T10:00:00+09:00",
                "timezone": "Asia/Seoul",
                "derived_from_resource_refs": [],
            }
        ],
        exclusion_obligation_segment_ids=["segment-user"],
        prior_result=prior,
    )

    assert result["meta"]["artifact_id"] == "retrieval-1"
    assert result["meta"]["revision"] == 3
    assert {tuple(item.values()) for item in result["meta"]["based_on"]} >= {("retrieval-1", 2)}
    assert result["excluded_segment_ids"] == [
        "segment-old",
        "segment-model",
        "segment-user",
    ]
    assert result["availability_results"]
    assert set(result) == {
        "schema_version",
        "meta",
        "coverage",
        "context_bundle_ref",
        "evidence_refs",
        "selected_segment_ids",
        "excluded_segment_ids",
        "source_resource_refs",
        "source_statuses",
        "collection_results",
        "availability_results",
        "missing_information",
        "retrieval_rounds",
        "temporal_constraints",
        "person_candidates",
        "selected_person_identities",
        "unresolved_event_dates",
        "task_review_candidates",
    }


def test_finalize_retrieval__after_active_result_invalidation__continues_durable_head() -> None:
    result = finalize_retrieval(
        artifact_id="unused-new-id",
        request_intent=_intent(),
        tool_route_plan=_tool_route_plan(),
        acquisition_result=_acquisition_result(),
        selection_result={
            "schema_version": 2,
            "evidence_drafts": [],
            "selected_segment_ids": [],
            "excluded_segment_ids": [],
        },
        evidence_drafts=[],
        sufficiency_result=_sufficiency_output("SUFFICIENT"),
        current_round_no=0,
        prior_artifact_ref={"artifact_id": "retrieval-head", "revision": 4},
    )

    assert result["meta"]["artifact_id"] == "retrieval-head"
    assert result["meta"]["revision"] == 5
    assert {"artifact_id": "retrieval-head", "revision": 4} in result["meta"]["based_on"]


def test_finalize_retrieval__with_github_issue__preserves_exact_resource_type() -> None:
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
    acquisition = cast(
        AcquisitionResultV1,
        {
            "schema_version": 1,
            "status": "COMPLETE",
            "resource_handles": [
                "github_issue:acme/repo#7",
                "github_issue:acme/repo#8",
            ],
            "source_summaries": [
                {
                    "route_id": "route-github",
                    "source": "GITHUB",
                    "status": "COMPLETE",
                    "resource_handles": [
                        "github_issue:acme/repo#7",
                        "github_issue:acme/repo#8",
                    ],
                    "resources": [
                        {
                            "resource_type": "github_issue",
                            "resource_id": "acme/repo#7",
                        },
                        {
                            "resource_type": "github_issue",
                            "resource_id": "acme/repo#8",
                        },
                    ],
                }
            ],
            "missing_slots": [],
            "remaining_budget": {},
        },
    )
    selection = _selection_output(["segment-7"])
    evidence = cast(
        EvidenceDraftV1,
        {
            "schema_version": 1,
            "evidence_id": "evidence-segment-7",
            "resource_handle": "github_issue:acme/repo#7",
            "segment_id": "segment-7",
            "kind": "excerpt",
            "excerpt": "Issue seven",
            "locator": {},
            "reason_codes": ["SUPPORTS"],
        },
    )

    result = finalize_retrieval(
        artifact_id="retrieval-github",
        request_intent=_intent(),
        tool_route_plan=route_plan,
        acquisition_result=acquisition,
        selection_result=selection,
        evidence_drafts=[evidence],
        sufficiency_result=_sufficiency_output("SUFFICIENT"),
        current_round_no=0,
    )

    assert result["source_statuses"] == [
        {
            "route_id": "route-github",
            "resource_type": "github_issue",
            "status": "COMPLETE",
            "evidence_refs": ["evidence-segment-7"],
            "observed_resource_count": 2,
            "checked_read_count": 0,
            "known_scope_count": 0,
            "scope_complete": False,
            "continuation_status": "UNKNOWN",
            "failure_kind": None,
        }
    ]
    assert result["source_resource_refs"] == ["github_issue:acme/repo#7"]
    assert all(status["resource_type"] != "ISSUE" for status in result["source_statuses"])


def test_finalize_retrieval__preserves_collection_metadata_beyond_evidence_budget() -> None:
    resources = [
        {
            "resource_handle": f"gmail_thread:thread-{index}",
            "resource_type": "gmail_thread",
            "resource_id": f"thread-{index}",
            "payload": {"subject": "Same title" if index < 2 else f"Title {index}"},
        }
        for index in range(25)
    ]
    acquisition = cast(
        AcquisitionResultV1,
        {
            "schema_version": 1,
            "status": "COMPLETE",
            "resource_handles": [item["resource_handle"] for item in resources],
            "source_summaries": [
                {
                    "route_id": "route-gmail",
                    "source": "GMAIL",
                    "status": "COMPLETE",
                    "resource_handles": [item["resource_handle"] for item in resources],
                    "resources": resources,
                }
            ],
            "missing_slots": [],
            "remaining_budget": {"pages": 2},
        },
    )
    evidence = cast(
        EvidenceDraftV1,
        {
            "schema_version": 1,
            "evidence_id": "evidence-first",
            "resource_handle": "gmail_thread:thread-0",
            "segment_id": "segment-first",
            "kind": "excerpt",
            "excerpt": "Same title",
            "locator": {},
            "reason_codes": ["CONTEXT"],
        },
    )

    result = finalize_retrieval(
        artifact_id="retrieval-collection",
        request_intent=_intent(),
        tool_route_plan=_tool_route_plan(),
        acquisition_result=acquisition,
        selection_result=_selection_output(["segment-first"]),
        evidence_drafts=[evidence],
        sufficiency_result=_sufficiency_output("SUFFICIENT"),
        current_round_no=0,
        read_result_summaries=[
            {
                "route_id": "route-gmail",
                "has_next_page": False,
                "exhausted": True,
            }
        ],
    )

    collection = result["collection_results"][0]
    assert collection["continuation_status"] == "EXHAUSTED"
    assert len(collection["items"]) == 25
    assert collection["items"][:2] == [
        {
            "resource_ref": "gmail_thread:thread-0",
            "resource_type": "gmail_thread",
            "title": "Same title",
        },
        {
            "resource_ref": "gmail_thread:thread-1",
            "resource_type": "gmail_thread",
            "title": "Same title",
        },
    ]
    assert result["source_resource_refs"] == ["gmail_thread:thread-0"]


def test_finalize_retrieval__reports_unfinished_collection_page_without_forcing_coverage() -> None:
    acquisition = _acquisition_result()
    acquisition["remaining_budget"]["pages"] = 0
    acquisition["source_summaries"][0]["route_id"] = "route-gmail"
    acquisition["source_summaries"][0]["resources"] = [
        {
            "resource_handle": "gmail_thread:thread-kim",
            "resource_type": "gmail_thread",
            "resource_id": "thread-kim",
            "payload": {"subject": "Current status"},
        }
    ]

    result = finalize_retrieval(
        artifact_id="retrieval-has-more",
        request_intent=_intent(),
        tool_route_plan=_tool_route_plan(),
        acquisition_result=acquisition,
        selection_result={
            "schema_version": 2,
            "evidence_drafts": [],
            "selected_segment_ids": [],
            "excluded_segment_ids": [],
        },
        evidence_drafts=[],
        sufficiency_result=_sufficiency_output("SUFFICIENT"),
        current_round_no=0,
        read_result_summaries=[
            {
                "route_id": "route-gmail",
                "has_next_page": True,
                "exhausted": False,
            }
        ],
    )

    assert result["coverage"] == "SUFFICIENT"
    assert result["collection_results"][0]["continuation_status"] == "HAS_MORE"


def test_finalize_retrieval__preserves_bounded_scope_counts_and_incomplete_coverage() -> None:
    acquisition = _acquisition_result()
    acquisition["status"] = "PARTIAL"
    acquisition["source_summaries"][0].update(
        route_id="route-gmail",
        checked_read_count=2,
        known_scope_count=2,
        scope_complete=True,
        continuation_status="EXHAUSTED",
    )
    acquisition["source_summaries"].append(
        {
            "schema_version": 1,
            "route_id": "route-gmail",
            "source": "GMAIL",
            "connector_id": "google_workspace",
            "status": "PARTIAL",
            "required": True,
            "error_code": None,
            "termination_kind": "BUDGET_STOPPED",
            "budget_reason_code": "CONNECTOR_LIMIT",
            "resource_count": 0,
            "resource_handles": [],
            "resources": [],
            "checked_read_count": 0,
            "known_scope_count": 3,
            "scope_complete": False,
            "continuation_status": "UNKNOWN",
        }
    )

    result = finalize_retrieval(
        artifact_id="retrieval-partial-scope",
        request_intent=_intent(),
        tool_route_plan=_tool_route_plan(),
        acquisition_result=acquisition,
        selection_result={
            "schema_version": 2,
            "evidence_drafts": [],
            "selected_segment_ids": [],
            "excluded_segment_ids": [],
        },
        evidence_drafts=[],
        sufficiency_result=_sufficiency_output("PARTIAL"),
        current_round_no=0,
        read_result_summaries=[
            {"route_id": "route-gmail", "has_next_page": False, "exhausted": True}
        ],
    )

    source = result["source_statuses"][0]
    assert source["status"] == "PARTIAL"
    assert source["checked_read_count"] == 2
    assert source["known_scope_count"] == 5
    assert source["observed_resource_count"] == 1
    assert source["scope_complete"] is False
    assert source["continuation_status"] == "UNKNOWN"
    assert result["collection_results"][0]["continuation_status"] == "UNKNOWN"


def test_finalize_retrieval__with_google_resources__retains_exact_resource_types() -> None:
    for route_type, source, exact_type in (
        ("GMAIL_THREAD", "GMAIL", "gmail_thread"),
        ("TASK", "TASKS", "task"),
        ("CALENDAR_EVENT", "CALENDAR", "calendar_event"),
    ):
        route_plan = _tool_route_plan(
            [
                {
                    "route_id": "route-google",
                    "resource_type": route_type,
                    "connector_id": "google_workspace",
                    "allowed_read_tool_ids": ["read"],
                    "required": True,
                    "reason_codes": [],
                }
            ]
        )
        acquisition = _acquisition_result()
        summary = acquisition["source_summaries"][0]
        summary["route_id"] = "route-google"
        summary["source"] = source
        summary["resources"] = [{"resource_type": exact_type}]

        result = finalize_retrieval(
            artifact_id="retrieval-google",
            request_intent=_intent(),
            tool_route_plan=route_plan,
            acquisition_result=acquisition,
            selection_result={
                "schema_version": 2,
                "selected_segment_ids": [],
                "evidence_drafts": [],
                "excluded_segment_ids": [],
            },
            evidence_drafts=[],
            sufficiency_result=_sufficiency_output("SUFFICIENT"),
            current_round_no=0,
        )

        assert result["source_statuses"][0]["resource_type"] == exact_type


def test_finalize_retrieval__complete_empty_read__is_observed_sufficient_coverage() -> None:
    acquisition = _acquisition_result()
    acquisition["status"] = "COMPLETE"
    acquisition["resource_handles"] = []
    acquisition["source_summaries"][0]["status"] = "COMPLETE"
    acquisition["source_summaries"][0]["resource_handles"] = []
    acquisition["source_summaries"][0]["resources"] = []

    result = finalize_retrieval(
        artifact_id="retrieval-empty",
        request_intent=_intent(),
        tool_route_plan=_tool_route_plan(),
        acquisition_result=acquisition,
        selection_result={
            "schema_version": 2,
            "evidence_drafts": [],
            "selected_segment_ids": [],
            "excluded_segment_ids": [],
        },
        evidence_drafts=[],
        sufficiency_result=_sufficiency_output("SUFFICIENT"),
        current_round_no=0,
    )

    assert result["coverage"] == "SUFFICIENT"


def test_finalize_retrieval__no_fetch_needed__requires_not_attempted_sources() -> None:
    acquisition = _acquisition_result()
    acquisition["status"] = "NOT_ATTEMPTED"
    acquisition["resource_handles"] = []
    acquisition["source_summaries"][0]["status"] = "NOT_ATTEMPTED"
    acquisition["source_summaries"][0]["resource_handles"] = []
    acquisition["source_summaries"][0]["resources"] = []

    result = finalize_retrieval(
        artifact_id="retrieval-not-attempted",
        request_intent=_intent(),
        tool_route_plan=_tool_route_plan(),
        acquisition_result=acquisition,
        selection_result={
            "schema_version": 2,
            "evidence_drafts": [],
            "selected_segment_ids": [],
            "excluded_segment_ids": [],
        },
        evidence_drafts=[],
        sufficiency_result=_sufficiency_output("SUFFICIENT"),
        current_round_no=0,
    )

    assert result["coverage"] == "NO_FETCH_NEEDED"
