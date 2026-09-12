from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import asdict, replace
from hashlib import sha256
from typing import cast

import pytest

from google_work_agent.adapters.langgraph.subgraphs.retrieval.nodes.execute_read_node import (
    execute_read_node,
)
from google_work_agent.adapters.langgraph.subgraphs.retrieval.projections import (
    execute_read_projection,
)
from google_work_agent.adapters.system.memory.run_retrieval_cache import InMemoryRunRetrievalCache
from google_work_agent.application.agents.request_understanding.contracts.request_intent import (
    RequestIntentV2,
)
from google_work_agent.application.agents.retrieval.build_query import (
    QueryUnchangedAfterFailureError,
    build_query_attempt,
)
from google_work_agent.application.agents.retrieval.contracts.query_attempt import QueryAttemptV1
from google_work_agent.application.agents.retrieval.contracts.query_plan import SourceFetchPlanV1
from google_work_agent.application.agents.retrieval.execute_read import (
    RetrievalReadBindingError,
    RetrievalReadExecutionV1,
    execute_read,
)
from google_work_agent.application.use_cases.resource.get_repository_access import (
    GetRepositoryAccessHandler,
    GetRepositoryAccessQuery,
)
from google_work_agent.application.use_cases.run.guard_run_budget import (
    build_default_run_budget,
    validate_run_budget_v2,
)
from google_work_agent.ports.connector.connector_failure import (
    ConnectorFailureCode,
    ConnectorOperationFailure,
)
from google_work_agent.ports.connector.connector_read_port import (
    ConnectorReadResultV1,
    JsonValue,
)
from google_work_agent.ports.connector.contracts.validated_connector_tool_binding import (
    ValidatedConnectorToolBindingV1,
)
from google_work_agent.ports.system.run_retrieval_cache_port import RunRetrievalCacheEntryV1
from google_work_agent.ports.system.settings_port import GitHubRepositoryDefaultV1


@pytest.mark.parametrize(
    ("output", "total", "count"),
    [
        ({"items": [{"resource_id": "a"}, {"resource_id": "b"}]}, None, 2),
        ({"items": [{"resource_id": "a"}]}, 1000, 1),
        ({"items": []}, 1000, 0),
        ({"item": {"resource_id": "a"}}, None, 1),
        ({}, 1000, None),
    ],
)
def test_query_attempt_count__provider_estimate__uses_bounded_acquired_resources(
    output: dict[str, JsonValue],
    total: int | None,
    count: int | None,
) -> None:
    class Reader:
        def execute_read(
            self,
            binding: ValidatedConnectorToolBindingV1,
            tool_arguments: dict[str, JsonValue],
        ) -> ConnectorReadResultV1:
            return ConnectorReadResultV1(1, binding.tool_id, "req", output, None, total)

    plan: SourceFetchPlanV1 = {**_plan(), "operation_kind": "SEARCH"}
    execution = execute_read(
        plan=plan,
        run_id="run",
        binding=_binding(),
        tool_arguments={"query": "bounded"},
        connector_reader=Reader(),
        read_result_cache=InMemoryRunRetrievalCache(),
        read_result_handle="new",
        run_budget=build_default_run_budget(),
        now_ms=0,
        prior_query_attempts=[],
    )
    assert execution.candidate_count == count
    attempt = build_query_attempt(
        query_attempt_id="attempt",
        run_id="run",
        plan=plan,
        round_no=0,
        attempt_no=0,
        tool_id=_binding().tool_id,
        canonical_arguments={"query": "bounded"},
        previous_query_hash=None,
        page_state_hash=None,
        candidate_count=execution.candidate_count,
        stop_reason=execution.status,
        prior_query_attempts=[],
        change_reason_code="USER_REQUEST",
    )
    assert attempt["candidate_count"] == count


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


def test_execute_read__with_durable_accountant__commits_budget_before_connector_dispatch() -> None:
    durable_budget = build_default_run_budget()
    graph_budget = build_default_run_budget()

    def account(
        update: Callable[[Mapping[str, object]], Mapping[str, object]],
    ) -> Mapping[str, object]:
        nonlocal durable_budget
        durable_budget = validate_run_budget_v2(dict(update(durable_budget)))
        return durable_budget

    class Reader:
        def execute_read(
            self,
            binding: ValidatedConnectorToolBindingV1,
            tool_arguments: dict[str, JsonValue],
        ) -> ConnectorReadResultV1:
            del binding, tool_arguments
            assert durable_budget["connector_calls_used"] == 1
            assert durable_budget["source_page_calls_used"] == 1
            return ConnectorReadResultV1(
                1, "gmail_search_threads", "req", {"items": []}, None, 0
            )

    result = execute_read(
        plan={**_plan(), "operation_kind": "SEARCH"},
        run_id="run",
        binding=_binding(),
        tool_arguments={"query": "bounded"},
        connector_reader=Reader(),
        read_result_cache=InMemoryRunRetrievalCache(),
        read_result_handle="read",
        run_budget=graph_budget,
        now_ms=0,
        prior_query_attempts=[],
        durable_budget_accountant=account,
    )

    assert result.status == "COMPLETE"
    assert graph_budget == durable_budget


def test_github_default__lost_access__prevents_issue_read() -> None:
    reader = _Reader()
    intent = cast(
        RequestIntentV2,
        {
            "constraints": [],
            "ambiguity": {"requires_confirmation": False},
            "repository_default": asdict(
                GitHubRepositoryDefaultV1("example/project", 1, "github:2")
            ),
        },
    )
    access_calls: list[GetRepositoryAccessQuery] = []

    class DeniedRepositoryAccess(GetRepositoryAccessHandler):
        def __call__(
            self,
            query: GetRepositoryAccessQuery,
            *,
            before_page: Callable[[], None] | None = None,
        ) -> GitHubRepositoryDefaultV1:
            access_calls.append(query)
            if before_page is not None:
                before_page()
            raise ConnectorOperationFailure(
                ConnectorFailureCode.PERMISSION_DENIED, "ACCESS_REMOVED"
            )

    budget = build_default_run_budget()
    execution = execute_read(
        plan={
            **_plan(),
            "connector_id": "github",
            "resource_type": "GITHUB_ISSUE",
            "operation_kind": "SEARCH",
            "prior_read_result_handle": None,
        },
        run_id="run",
        binding=replace(
            _binding(),
            connector_id="github",
            resource_type="GITHUB_ISSUE",
            tool_id="github_list_issues",
        ),
        tool_arguments={"repository": "example/project", "state": "open"},
        connector_reader=reader,
        read_result_cache=InMemoryRunRetrievalCache(),
        read_result_handle="read",
        run_budget=budget,
        now_ms=0,
        prior_query_attempts=[],
        request_intent=intent,
        repository_access=object.__new__(DeniedRepositoryAccess),
    )
    assert execution.status == "FAILED"
    assert execution.failure_code == "PERMISSION_DENIED"
    assert execution.provider_called is False
    assert execution.candidate_count is None
    assert len(access_calls) == 1
    assert reader.calls == []
    assert budget["connector_calls_used"] == 1


@pytest.mark.parametrize(
    "code",
    [ConnectorFailureCode.NOT_FOUND, ConnectorFailureCode.PERMISSION_DENIED],
)
def test_execute_read_node__target_failure__preserves_typed_output_and_traceback(
    code: ConnectorFailureCode,
) -> None:
    @contextmanager
    def boundary() -> Iterator[None]:
        yield

    failure = ConnectorOperationFailure(code, "PROVIDER_FAILURE")

    class Reader:
        def execute_read(
            self,
            binding: ValidatedConnectorToolBindingV1,
            tool_arguments: dict[str, JsonValue],
        ) -> ConnectorReadResultV1:
            del binding, tool_arguments
            with boundary():
                raise failure

    cache = InMemoryRunRetrievalCache()
    budget = build_default_run_budget()
    result = cast(
        RetrievalReadExecutionV1,
        execute_read_node(
            {
                "operation_inputs": {
                    "execute_read": {
                        "plan": {**_plan(), "operation_kind": "SEARCH"},
                        "run_id": "run",
                        "binding": _binding(),
                        "tool_arguments": {"query": "bounded"},
                        "connector_reader": Reader(),
                        "read_result_cache": cache,
                        "read_result_handle": "failed",
                        "run_budget": budget,
                        "now_ms": 0,
                        "prior_query_attempts": [],
                    }
                }
            }
        )["read_execution"],
    )
    assert result.status == "FAILED"
    assert result.failure_code == code.value
    assert result.candidate_count is None
    assert result.provider_called is True
    assert budget["connector_calls_used"] == 1
    assert failure.__traceback__ is not None
    cached = cache.resolve_read_result("failed", "run", "r1", _plan()["query_identity_hash"])
    assert cached.entry is None


def test_execute_read_node__credential_failure__retains_existing_exception_contract() -> None:
    failure = ConnectorOperationFailure(ConnectorFailureCode.AUTH_REQUIRED, "AUTH_EXPIRED")

    class Reader:
        def execute_read(
            self,
            binding: ValidatedConnectorToolBindingV1,
            tool_arguments: dict[str, JsonValue],
        ) -> ConnectorReadResultV1:
            del binding, tool_arguments
            raise failure

    with pytest.raises(ConnectorOperationFailure) as raised:
        execute_read_node(
            {
                "operation_inputs": {
                    "execute_read": {
                        "plan": {**_plan(), "operation_kind": "SEARCH"},
                        "run_id": "run",
                        "binding": _binding(),
                        "tool_arguments": {"query": "bounded"},
                        "connector_reader": Reader(),
                        "read_result_cache": InMemoryRunRetrievalCache(),
                        "read_result_handle": "failed",
                        "run_budget": build_default_run_budget(),
                        "now_ms": 0,
                        "prior_query_attempts": [],
                    }
                }
            }
        )
    assert raised.value is failure


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
def test_detail_dispatch__detail_dimension__charges_only_detail_and_honors_limit(
    detail_used: int, expected_calls: int
) -> None:
    plan: SourceFetchPlanV1 = {
        **_plan(),
        "operation_kind": "DETAIL_FETCH",
        "detail_candidate_ref": "gmail_thread:t",
    }
    reader = _Reader()
    budget = build_default_run_budget()
    budget["detail_fetches_used"] = detail_used
    arguments = execute_read_projection.ExecuteReadInput(
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
        outcome = execute_read(**arguments)
        assert outcome.status == "BUDGET_STOPPED"
        assert outcome.failure_code is None
        assert outcome.stop_reason == "DETAIL_FETCH_LIMIT"
        assert outcome.provider_called is False
        assert outcome.candidate_count is None
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
def test_repeated_read__same_query__blocks_before_provider_and_budget_charge(
    operation: str,
) -> None:
    plan = cast(SourceFetchPlanV1, {**_plan(), "operation_kind": operation})
    args: dict[str, JsonValue] = (
        {"query": "bounded"} if operation != "DETAIL_FETCH" else {"thread_id": "t1"}
    )
    attempt = build_query_attempt(
        query_attempt_id="a1",
        run_id="run",
        plan=plan,
        round_no=0,
        attempt_no=0,
        tool_id="gmail_search_threads",
        canonical_arguments=args,
        previous_query_hash=None,
        page_state_hash=sha256(b"opaque").hexdigest(),
        candidate_count=1,
        stop_reason="COMPLETE",
        prior_query_attempts=[],
        change_reason_code="USER_REQUEST",
    )
    # A -> B -> A is not merely an immediate-repeat check.
    different: QueryAttemptV1 = {
        **attempt,
        "query_spec": {**attempt["query_spec"], "canonical_arguments": {"query": "different"}},
        "page_state_hash": "other",
    }
    prior = [attempt, different]
    if operation == "NEXT_PAGE":
        prior.append({**attempt, "attempt_no": 2})
    cache = InMemoryRunRetrievalCache()
    cache.put_read_result(
        RunRetrievalCacheEntryV1(
            1,
            "prior",
            "run",
            "r1",
            "q" * 64,
            ConnectorReadResultV1(1, "gmail_search_threads", "old", {}, "opaque", 1),
            False,
        )
    )
    reader = _Reader()
    budget = build_default_run_budget()
    with pytest.raises(QueryUnchangedAfterFailureError):
        execute_read(
            plan=plan,
            run_id="run",
            binding=_binding(),
            tool_arguments=args,
            connector_reader=reader,
            read_result_cache=cache,
            read_result_handle="new",
            run_budget=budget,
            now_ms=0,
            prior_query_attempts=prior,
        )
    assert reader.calls == []
    assert budget["connector_calls_used"] == 0
    assert budget["detail_fetches_used"] == 0
    assert budget["source_page_calls_used"] == 0


def test_next_page__first_unread_page__does_not_treat_as_repeat() -> None:
    plan = _plan()
    cache = InMemoryRunRetrievalCache()
    cache.put_read_result(
        RunRetrievalCacheEntryV1(
            1,
            "prior",
            "run",
            "r1",
            "q" * 64,
            ConnectorReadResultV1(1, "gmail_search_threads", "old", {}, "opaque", 1),
            False,
        )
    )
    attempt = build_query_attempt(
        query_attempt_id="a1",
        run_id="run",
        plan={**plan, "operation_kind": "SEARCH"},
        round_no=0,
        attempt_no=0,
        tool_id="gmail_search_threads",
        canonical_arguments={"query": "bounded"},
        previous_query_hash=None,
        page_state_hash=sha256(b"opaque").hexdigest(),
        candidate_count=1,
        stop_reason="COMPLETE",
        prior_query_attempts=[],
        change_reason_code="USER_REQUEST",
    )
    reader = _Reader()
    result = execute_read(
        plan=plan,
        run_id="run",
        binding=_binding(),
        tool_arguments={"query": "bounded"},
        connector_reader=reader,
        read_result_cache=cache,
        read_result_handle="new",
        run_budget=build_default_run_budget(),
        now_ms=0,
        prior_query_attempts=[attempt],
    )
    assert result.provider_called
    assert reader.calls == [{"query": "bounded", "page_token": "opaque"}]
    consumed = cast(
        QueryAttemptV1,
        {**attempt, "operation_kind": "NEXT_PAGE", "page_state_hash": None},
    )
    with pytest.raises(QueryUnchangedAfterFailureError):
        execute_read(
            plan=plan,
            run_id="run",
            binding=_binding(),
            tool_arguments={"query": "bounded"},
            connector_reader=reader,
            read_result_cache=cache,
            read_result_handle="repeated",
            run_budget=build_default_run_budget(),
            now_ms=0,
            prior_query_attempts=[attempt, consumed],
        )
    assert len(reader.calls) == 1
