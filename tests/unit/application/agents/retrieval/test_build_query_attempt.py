"""Query-attempt materialization scenarios owned by retrieval.build_query."""

from google_work_agent.application.agents.retrieval.build_query import (
    build_query_attempt,
    followup_planner_projection,
)


def test_query_attempt__uses_bounded_query__and_page_identities() -> None:
    attempt = build_query_attempt(
        query_attempt_id="attempt-1",
        run_id="run-1",
        round_no=0,
        attempt_no=0,
        plan={
            "schema_version": 1,
            "route_id": "route-1",
            "connector_id": "google_workspace",
            "resource_type": "GMAIL_THREAD",
            "operation_kind": "SEARCH",
            "effective_constraints": [
                {"kind": "KEYWORD", "terms": ["roadmap"], "match_mode": "ANY"}
            ],
            "query_identity_hash": "query-hash",
            "prior_read_result_handle": None,
            "detail_candidate_ref": None,
        },
        tool_id="gmail_search_threads",
        canonical_arguments={"query": "roadmap", "page_size": 10},
        previous_query_hash=None,
        page_state_hash="page-hash",
        candidate_count=2,
        stop_reason="READ_COMPLETE",
        prior_query_attempts=[],
        change_reason_code="USER_REQUEST",
    )

    assert attempt["operation_kind"] == "SEARCH"
    assert attempt["round_no"] == 0
    assert attempt["query_spec"]["canonical_arguments"]["query"] == "roadmap"
    assert "page_token" not in attempt
    assert "next_page_token" not in attempt
    assert attempt["added_constraints"] == ["KEYWORD"]
    assert attempt["change_reason_code"] == "USER_REQUEST"

    changed = build_query_attempt(
        query_attempt_id="attempt-2", run_id="run-1", round_no=1, attempt_no=1,
        plan={
            "schema_version": 1, "route_id": "route-1", "connector_id": "google_workspace",
            "resource_type": "GMAIL_THREAD", "operation_kind": "SEARCH",
            "effective_constraints": [
                {"kind": "KEYWORD", "terms": ["roadmap", "conference"], "match_mode": "ANY"},
            ], "query_identity_hash": "changed", "prior_read_result_handle": "previous-read",
            "detail_candidate_ref": None,
        }, tool_id="gmail_search_threads",
        canonical_arguments={"query": "{roadmap conference}", "page_size": 10},
        previous_query_hash="query-hash", page_state_hash=None,
        candidate_count=1, stop_reason="COMPLETE", prior_query_attempts=[attempt],
        change_reason_code="QUERY_RELAXED_AFTER_NO_RESULTS",
    )
    assert changed["added_constraints"] == ["KEYWORD"]
    assert changed["removed_constraints"] == ["KEYWORD"]
    assert changed["previous_query_hash"] == "query-hash"
    assert changed["change_reason_code"] == "QUERY_RELAXED_AFTER_NO_RESULTS"

    projection = followup_planner_projection(
        current_round_no=1, prior_query_attempts=[attempt, changed],
        unresolved_sufficiency_issues=[{"required": True, "description": "missing event date"}],
        read_result_summaries=[{"route_id": "route-1", "result_count": 1}],
    )
    for original, projected in zip(
        [attempt, changed], projection["prior_query_attempts"], strict=True,
    ):
        assert "query_spec" in original
        assert "query_spec" not in projected
        assert (projected["normalized_intent_constraints"]
                == original["normalized_intent_constraints"])
        assert projected["candidate_count"] == original["candidate_count"]
        assert projected["stop_reason"] == original["stop_reason"]
