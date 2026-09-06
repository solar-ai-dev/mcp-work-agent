from typing import cast

from tests.support.context_retrieval import (
    _acquisition_result,
    _intent,
    _selection_output,
    _sufficiency_output,
    _tool_route_plan,
)

from google_work_agent.application.agents.retrieval.contracts.retrieval_result import (
    AcquisitionResultV1,
    EvidenceDraftV1,
    RetrievalResultV1,
)
from google_work_agent.application.agents.retrieval.finalize_retrieval import (
    finalize_retrieval,
)


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
        "availability_results",
        "missing_information",
        "retrieval_rounds",
        "temporal_constraints",
        "person_candidates",
        "selected_person_identities",
        "unresolved_event_dates",
    }


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
            "failure_kind": None,
        }
    ]
    assert result["source_resource_refs"] == ["github_issue:acme/repo#7"]
    assert all(status["resource_type"] != "ISSUE" for status in result["source_statuses"])


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
