"""Reject repeated provider reads using the current Run's validated attempts."""

from collections.abc import Mapping, Sequence
from hashlib import sha256

from google_work_agent.application.agents.retrieval.build_query import (
    QueryUnchangedAfterFailureError,
)
from google_work_agent.application.agents.retrieval.contracts.query_attempt import QueryAttemptV1
from google_work_agent.application.agents.retrieval.contracts.query_plan import SourceFetchPlanV1
from google_work_agent.ports.connector.connector_read_port import JsonValue


def guard_retrieval_read_repeat(
    *,
    plan: SourceFetchPlanV1,
    run_id: str,
    tool_id: str,
    canonical_arguments: Mapping[str, JsonValue],
    continuation: str | None,
    prior_query_attempts: Sequence[QueryAttemptV1],
) -> None:
    matching = [
        attempt for attempt in prior_query_attempts
        if attempt["run_id"] == run_id
        and attempt["connector_id"] == plan["connector_id"]
        and attempt["query_spec"]["tool_id"] == tool_id
        and (attempt["query_spec"]["canonical_arguments"] == canonical_arguments
             or (attempt["operation_kind"] in {"SEARCH", "NEXT_PAGE"}
                 and plan["operation_kind"] in {"SEARCH", "NEXT_PAGE"}
                 and attempt["normalized_intent_constraints"] == plan["effective_constraints"]))
        and attempt["stop_reason"] != "EXHAUSTED"
    ]
    if plan["operation_kind"] != "NEXT_PAGE":
        if any(attempt["operation_kind"] != "NEXT_PAGE" for attempt in matching):
            raise QueryUnchangedAfterFailureError("QUERY_UNCHANGED_AFTER_FAILURE")
        return
    # page_state_hash is the returned next token, never the raw continuation.
    # The first occurrence authorizes its next page. A repeated occurrence
    # means that page was already consumed (including A -> B -> A token cycles).
    if continuation is not None:
        token_hash = sha256(continuation.encode()).hexdigest()
        if sum(attempt["page_state_hash"] == token_hash for attempt in matching) > 1:
            raise QueryUnchangedAfterFailureError("QUERY_UNCHANGED_AFTER_FAILURE")
