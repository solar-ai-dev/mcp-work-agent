from hashlib import sha256
from typing import cast

import pytest

from google_work_agent.application.agents.retrieval.build_query import (
    QueryUnchangedAfterFailureError,
)
from google_work_agent.application.agents.retrieval.contracts.query_attempt import QueryAttemptV1
from google_work_agent.application.agents.retrieval.contracts.query_plan import SourceFetchPlanV1
from google_work_agent.application.agents.retrieval.guard_retrieval_read_repeat import (
    guard_retrieval_read_repeat,
)


def test_guard_retrieval_read_repeat__new_lowering__preserves_semantic_repeat_guard() -> None:
    constraints = [{"kind": "KEYWORD", "terms": ["exact"], "match_mode": "ALL"}]
    attempt = cast(QueryAttemptV1, {
        "run_id": "run", "connector_id": "google_workspace",
        "operation_kind": "SEARCH", "stop_reason": "COMPLETE",
        "normalized_intent_constraints": constraints,
        "query_spec": {"tool_id": "gmail_search_threads", "canonical_arguments": {
            "query": "exact", "page_size": 20,
        }},
    })
    with pytest.raises(QueryUnchangedAfterFailureError):
        guard_retrieval_read_repeat(
            plan=cast(SourceFetchPlanV1, {
                "connector_id": "google_workspace", "operation_kind": "SEARCH",
                "effective_constraints": constraints,
            }), run_id="run", tool_id="gmail_search_threads",
            canonical_arguments={"query": '"exact"', "page_size": 20},
            continuation=None, prior_query_attempts=[attempt],
        )


@pytest.mark.parametrize("previous_run,blocked", [("run-1", True), ("run-2", False)])
def test_guard_retrieval_read_repeat__same_query__blocks_only_current_run(
    previous_run: str, blocked: bool,
) -> None:
    attempt = cast(QueryAttemptV1, {
        "run_id": previous_run, "connector_id": "google_workspace",
        "operation_kind": "SEARCH", "stop_reason": "FAILED",
        "query_spec": {"tool_id": "gmail_search_threads", "canonical_arguments": {"q": "x"}},
    })
    def invoke() -> None:
        guard_retrieval_read_repeat(
            plan=cast(SourceFetchPlanV1, {
                "connector_id": "google_workspace", "operation_kind": "SEARCH",
            }), run_id="run-1", tool_id="gmail_search_threads",
            canonical_arguments={"q": "x"}, continuation=None, prior_query_attempts=[attempt],
        )
    if blocked:
        with pytest.raises(QueryUnchangedAfterFailureError):
            invoke()
    else:
        invoke()


@pytest.mark.parametrize("occurrences,blocked", [(1, False), (2, True)])
def test_guard_retrieval_read_repeat__returned_page_token__allows_once(
    occurrences: int, blocked: bool,
) -> None:
    attempt = cast(QueryAttemptV1, {
        "run_id": "run-1", "connector_id": "google_workspace",
        "operation_kind": "NEXT_PAGE", "stop_reason": "HAS_MORE",
        "query_spec": {"tool_id": "gmail_search_threads", "canonical_arguments": {"q": "x"}},
        "page_state_hash": sha256(b"cursor").hexdigest(),
    })
    def invoke() -> None:
        guard_retrieval_read_repeat(
            plan=cast(SourceFetchPlanV1, {
                "connector_id": "google_workspace", "operation_kind": "NEXT_PAGE",
            }), run_id="run-1", tool_id="gmail_search_threads", canonical_arguments={"q": "x"},
            continuation="cursor", prior_query_attempts=[attempt] * occurrences,
        )
    if blocked:
        with pytest.raises(QueryUnchangedAfterFailureError):
            invoke()
    else:
        invoke()
