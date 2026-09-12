from typing import cast

import pytest

from google_work_agent.adapters.langgraph.subgraphs.retrieval.projections import (
    retrieval_continuation_projection,
)
from google_work_agent.application.agents.retrieval.contracts.query_attempt import (
    QueryAttemptV1,
)
from google_work_agent.application.agents.retrieval.contracts.query_plan import (
    SourceFetchPlanV1,
)


def test_restore_retrieval_continuation__prior_query__preserves_bounds() -> None:
    plan = cast(
        SourceFetchPlanV1,
        {
            "schema_version": 1,
            "route_id": "route-1",
            "connector_id": "google_workspace",
            "resource_type": "EMAIL",
            "operation_kind": "SEARCH",
            "effective_constraints": [
                {"kind": "KEYWORD", "terms": ["status"], "match_mode": "ANY"}
            ],
            "query_identity_hash": "a" * 64,
            "prior_read_result_handle": None,
            "detail_candidate_ref": None,
        },
    )
    attempt = cast(QueryAttemptV1, {"route_id": "route-1"})

    result = retrieval_continuation_projection.restore_retrieval_continuation(
        {
            "__context_canonical_plans__": {"route-1": plan},
            "__context_query_attempts__": [attempt],
            "__context_read_result_handles__": ["read-1"],
            "__context_read_bindings__": {
                "read-1": {
                    "route_id": "route-1",
                    "query_identity_hash": "a" * 64,
                }
            },
            "__context_segment_handles__": ["email:1"],
        },
        has_prior_result=True,
    )

    assert result["canonical_plans"] == {"route-1": plan}
    assert result["query_attempts"] == [attempt]
    assert result["read_result_handles"] == ["read-1"]


def test_cached_read_binding__changed_route_plan__resolves_exact_executed_plan() -> None:
    executed = cast(
        SourceFetchPlanV1,
        {
            "schema_version": 1,
            "route_id": "route-1",
            "connector_id": "google_workspace",
            "resource_type": "EMAIL",
            "operation_kind": "SEARCH",
            "effective_constraints": [
                {"kind": "KEYWORD", "terms": ["first"], "match_mode": "PHRASE"}
            ],
            "query_identity_hash": "a" * 64,
            "prior_read_result_handle": None,
            "detail_candidate_ref": None,
        },
    )
    latest = cast(
        SourceFetchPlanV1,
        {
            **executed,
            "effective_constraints": [
                {"kind": "KEYWORD", "terms": ["latest"], "match_mode": "PHRASE"}
            ],
            "query_identity_hash": "b" * 64,
        },
    )

    binding = retrieval_continuation_projection.bind_read_result_plan(executed)
    resolved = retrieval_continuation_projection.resolve_read_result_plan(
        binding,
        available_plans=[latest],
    )

    assert resolved == executed
    assert resolved is not executed


def test_old_cached_read_binding__changed_route_plan__requires_exact_query_identity() -> None:
    latest = cast(
        SourceFetchPlanV1,
        {
            "schema_version": 1,
            "route_id": "route-1",
            "connector_id": "google_workspace",
            "resource_type": "EMAIL",
            "operation_kind": "SEARCH",
            "effective_constraints": [],
            "query_identity_hash": "b" * 64,
            "prior_read_result_handle": None,
            "detail_candidate_ref": None,
        },
    )

    with pytest.raises(ValueError, match="executed query"):
        retrieval_continuation_projection.resolve_read_result_plan(
            {"route_id": "route-1", "query_identity_hash": "a" * 64},
            available_plans=[latest],
        )


def test_restore_retrieval_continuation__old_checkpoint__uses_fresh_read() -> None:
    assert retrieval_continuation_projection.restore_retrieval_continuation(
        {}, has_prior_result=True
    ) == {
        "canonical_plans": {},
        "query_attempts": [],
        "read_result_handles": [],
        "read_bindings": {},
        "segment_handles": [],
    }


def test_restore_retrieval_continuation__new_run__does_not_inherit_stale_fields() -> None:
    assert retrieval_continuation_projection.restore_retrieval_continuation(
        {
            "__context_canonical_plans__": {"stale": {"route_id": "stale"}},
            "__context_query_attempts__": [{"route_id": "stale"}],
            "__context_read_result_handles__": ["stale-read"],
            "__context_read_bindings__": {"stale-read": {"route_id": "stale"}},
            "__context_segment_handles__": ["stale-segment"],
        },
        has_prior_result=False,
    ) == {
        "canonical_plans": {},
        "query_attempts": [],
        "read_result_handles": [],
        "read_bindings": {},
        "segment_handles": [],
    }


def test_restore_retrieval_continuation__partial_checkpoint__rejects() -> None:
    with pytest.raises(ValueError, match="incomplete"):
        retrieval_continuation_projection.restore_retrieval_continuation(
            {"__context_canonical_plans__": {}},
            has_prior_result=True,
        )
