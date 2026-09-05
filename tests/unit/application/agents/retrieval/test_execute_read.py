from hashlib import sha256
from typing import cast

import pytest

from google_work_agent.adapters.system.memory.run_retrieval_cache import InMemoryRunRetrievalCache
from google_work_agent.application.agents.retrieval.build_query import (
    QueryUnchangedAfterFailureError,
    build_query_attempt,
)
from google_work_agent.application.agents.retrieval.contracts.query_plan import SourceFetchPlanV1
from google_work_agent.application.agents.retrieval.execute_read import (
    RetrievalReadBindingError,
    execute_read,
)
from google_work_agent.application.use_cases.run.consume_retrieval_read_budget import (
    RetrievalReadBudgetExceeded,
)
from google_work_agent.application.use_cases.run.guard_run_budget import build_default_run_budget
from google_work_agent.ports.connector.connector_read_port import (
    ConnectorReadResultV1,
    JsonValue,
)
from google_work_agent.ports.connector.contracts.validated_connector_tool_binding import (
    ValidatedConnectorToolBindingV1,
)
from google_work_agent.ports.system.run_retrieval_cache_port import RunRetrievalCacheEntryV1


class _Reader:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def execute_read(
        self,
        binding: ValidatedConnectorToolBindingV1,
        tool_arguments: dict[str, JsonValue],
    ) -> ConnectorReadResultV1:
        del binding
        self.calls.append(dict(tool_arguments))
        return ConnectorReadResultV1(1, "gmail_search_threads", "req", {}, None, 0)


def _plan() -> SourceFetchPlanV1:
    return cast(
        SourceFetchPlanV1,
        {
            "schema_version": 1,
            "route_id": "r1",
            "connector_id": "google_workspace",
            "resource_type": "GMAIL_THREAD",
            "operation_kind": "NEXT_PAGE",
            "effective_constraints": [],
            "query_identity_hash": "q" * 64,
            "prior_read_result_handle": "prior",
            "detail_candidate_ref": None,
        },
    )


def _binding() -> ValidatedConnectorToolBindingV1:
    return ValidatedConnectorToolBindingV1(
        1,
        "google_workspace",
        "GMAIL_THREAD",
        "gmail_search_threads",
        "READ",
        "in:v1",
        "out:v1",
        "a" * 64,
    )


@pytest.mark.parametrize(
    "run_id,route_id,query_hash",
    [("other", "r1", "q" * 64), ("run", "r2", "q" * 64), ("run", "r1", "x" * 64)],
)
def test_invalid_continuation__binding_prevents__provider_call(
    run_id: str, route_id: str, query_hash: str
) -> None:
    cache = InMemoryRunRetrievalCache()
    cache.put_read_result(
        RunRetrievalCacheEntryV1(
            1,
            "prior",
            run_id,
            route_id,
            query_hash,
            ConnectorReadResultV1(1, "gmail_search_threads", "old", {}, "opaque", 1),
            False,
        )
    )
    reader = _Reader()

    with pytest.raises(RetrievalReadBindingError):
        execute_read(
            plan=_plan(),
            run_id="run",
            binding=_binding(),
            tool_arguments={"query": "bounded"},
            connector_reader=reader,
            read_result_cache=cache,
            read_result_handle="new",
            run_budget=build_default_run_budget(),
            now_ms=0,
            prior_query_attempts=[],
        )

    assert reader.calls == []


@pytest.mark.parametrize("detail_used,expected_calls", [(0, 1), (12, 0)])
def test_detail_dispatch__charges_only_detail_dimension_and_honors_limit(
    detail_used: int, expected_calls: int
) -> None:
    plan = {**_plan(), "operation_kind": "DETAIL_FETCH", "detail_candidate_ref": "gmail_thread:t"}
    reader = _Reader()
    budget = build_default_run_budget()
    budget["detail_fetches_used"] = detail_used
    arguments = dict(
        plan=plan,
        run_id="run",
        binding=_binding(),
        tool_arguments={"thread_id": "t"},
        connector_reader=reader,
        read_result_cache=InMemoryRunRetrievalCache(),
        read_result_handle="detail",
        run_budget=budget,
        now_ms=0,
        prior_query_attempts=[],
    )
    if expected_calls:
        execute_read(**arguments)
    else:
        with pytest.raises(RetrievalReadBudgetExceeded, match="DETAIL_FETCH_LIMIT"):
            execute_read(**arguments)
    assert len(reader.calls) == expected_calls
    assert budget["detail_fetches_used"] == detail_used + expected_calls
    assert budget["connector_calls_used"] == expected_calls
    assert budget["source_page_calls_used"] == 0
    assert budget["additional_retrieval_rounds_used"] == 0


def test_exhausted_continuation__does_not__restart_provider_read() -> None:
    cache = InMemoryRunRetrievalCache()
    cache.put_read_result(
        RunRetrievalCacheEntryV1(
            1,
            "prior",
            "run",
            "r1",
            "q" * 64,
            ConnectorReadResultV1(1, "gmail_search_threads", "old", {}, None, 1),
            True,
        )
    )
    reader = _Reader()

    result = execute_read(
        plan=_plan(),
        run_id="run",
        binding=_binding(),
        tool_arguments={"query": "bounded"},
        connector_reader=reader,
        read_result_cache=cache,
        read_result_handle="new",
        run_budget=build_default_run_budget(),
        now_ms=0,
        prior_query_attempts=[],
    )

    assert result.status == "EXHAUSTED"
    assert not result.provider_called
    assert reader.calls == []


@pytest.mark.parametrize("operation", ["SEARCH", "DETAIL_FETCH", "NEXT_PAGE"])
def test_repeated_read__blocked_before_provider_and_budget_charge(operation: str) -> None:
    plan = cast(SourceFetchPlanV1, {**_plan(), "operation_kind": operation})
    args = {"query": "bounded"} if operation != "DETAIL_FETCH" else {"thread_id": "t1"}
    attempt = build_query_attempt(
        query_attempt_id="a1", run_id="run", plan=plan, round_no=0, attempt_no=0,
        tool_id="gmail_search_threads", canonical_arguments=args,
        previous_query_hash=None, page_state_hash=sha256(b"opaque").hexdigest(),
        candidate_count=1, stop_reason="COMPLETE",
        prior_query_attempts=[], change_reason_code="USER_REQUEST",
    )
    # A -> B -> A is not merely an immediate-repeat check.
    different = {**attempt, "query_spec": {**attempt["query_spec"],
                 "canonical_arguments": {"query": "different"}}, "page_state_hash": "other"}
    prior = [attempt, different]
    if operation == "NEXT_PAGE":
        prior.append({**attempt, "attempt_no": 2})
    cache = InMemoryRunRetrievalCache()
    cache.put_read_result(RunRetrievalCacheEntryV1(
        1, "prior", "run", "r1", "q" * 64,
        ConnectorReadResultV1(1, "gmail_search_threads", "old", {}, "opaque", 1), False,
    ))
    reader = _Reader()
    budget = build_default_run_budget()
    with pytest.raises(QueryUnchangedAfterFailureError):
        execute_read(
            plan=plan, run_id="run", binding=_binding(), tool_arguments=args,
            connector_reader=reader, read_result_cache=cache, read_result_handle="new",
            run_budget=budget, now_ms=0, prior_query_attempts=prior,
        )
    assert reader.calls == []
    assert budget["connector_calls_used"] == 0
    assert budget["detail_fetches_used"] == 0
    assert budget["source_page_calls_used"] == 0


def test_first_unread_page__is_not_mistaken_for_repeat() -> None:
    plan = _plan()
    cache = InMemoryRunRetrievalCache()
    cache.put_read_result(RunRetrievalCacheEntryV1(
        1, "prior", "run", "r1", "q" * 64,
        ConnectorReadResultV1(1, "gmail_search_threads", "old", {}, "opaque", 1), False,
    ))
    attempt = build_query_attempt(
        query_attempt_id="a1", run_id="run", plan={**plan, "operation_kind": "SEARCH"},
        round_no=0, attempt_no=0, tool_id="gmail_search_threads",
        canonical_arguments={"query": "bounded"}, previous_query_hash=None,
        page_state_hash=sha256(b"opaque").hexdigest(), candidate_count=1, stop_reason="COMPLETE",
        prior_query_attempts=[], change_reason_code="USER_REQUEST",
    )
    reader = _Reader()
    result = execute_read(
        plan=plan, run_id="run", binding=_binding(), tool_arguments={"query": "bounded"},
        connector_reader=reader, read_result_cache=cache, read_result_handle="new",
        run_budget=build_default_run_budget(), now_ms=0, prior_query_attempts=[attempt],
    )
    assert result.provider_called
    assert reader.calls == [{"query": "bounded", "page_token": "opaque"}]
