from collections.abc import Mapping
from pathlib import Path
from typing import Any, Literal, cast

import pytest
from tests.support.fakes.llm import FakeStructuredInferencePort

from google_work_agent.application.agents.request_understanding.contracts.request_intent import (
    RequestIntentV2,
)
from google_work_agent.application.agents.retrieval.build_query import (
    RouteConstraintPolicy,
    build_query,
)
from google_work_agent.application.agents.retrieval.contracts.query_attempt import (
    QueryAttemptV1,
)
from google_work_agent.application.agents.retrieval.contracts.query_plan import (
    RetrievalV2ValidationError,
    SourceFetchPlanV1,
)
from google_work_agent.application.agents.retrieval.contracts.query_plan_schema import (
    RETRIEVAL_QUERY_PLAN_V2_OUTPUT_SCHEMA,
)
from google_work_agent.application.agents.retrieval.plan_query import (
    RetrievalBudget,
    has_retrieval_followup_path,
    initial_retrieval_planner_input,
    plan_query,
)
from google_work_agent.application.agents.tool_routing.contracts.tool_route_plan import (
    InputToolRouteV1,
    ToolRoutePlanV2,
)
from google_work_agent.application.use_cases.run.guard_run_budget import build_default_run_budget
from google_work_agent.ports.llm.output_schema_validation import validate_output_schema
from google_work_agent.ports.llm.structured_inference_contracts import (
    OutputSchemaDefinition,
    PromptReference,
)
from google_work_agent.ports.llm.structured_inference_port import StructuredInferenceResultV1


def _tool_route_plan(*, allowed_read_tool_ids: list[str]) -> ToolRoutePlanV2:
    return cast(
        ToolRoutePlanV2,
        {
            "schema_version": 2,
            "input_plan": {
                "schema_version": 1,
                "meta": {},
                "input_routes": [
                    {
                        "route_id": "route-1",
                        "resource_type": "GMAIL_THREAD",
                        "connector_id": "google_workspace",
                        "allowed_read_tool_ids": allowed_read_tool_ids,
                        "required": True,
                        "reason_codes": ["USER_REQUEST"],
                    }
                ],
            },
            "output_plan": {
                "schema_version": 1,
                "meta": {},
                "output_mode": "ANSWER",
            },
            "tool_registry_version": "test",
        },
    )


def _task_calendar_followup_context() -> tuple[
    list[InputToolRouteV1],
    dict[str, RouteConstraintPolicy],
    dict[str, list[str]],
    dict[str, SourceFetchPlanV1],
]:
    routes = cast(
        list[InputToolRouteV1],
        [
            {
                "route_id": "tasks",
                "resource_type": "TASK",
                "connector_id": "google_workspace",
                "allowed_read_tool_ids": ["tasks_list_tasks"],
                "required": True,
                "reason_codes": ["USER_REQUEST"],
            },
            {
                "route_id": "calendar-events",
                "resource_type": "CALENDAR_EVENT",
                "connector_id": "google_workspace",
                "allowed_read_tool_ids": ["calendar_list_events"],
                "required": True,
                "reason_codes": ["USER_REQUEST"],
            },
        ],
    )
    policies = {
        "tasks": RouteConstraintPolicy(
            frozenset({"CONTAINER_REF", "STATUS_SCOPE"}),
            frozenset({"CONTAINER_REF"}),
        ),
        "calendar-events": RouteConstraintPolicy(
            frozenset({"CONTAINER_REF", "KEYWORD"}),
            frozenset({"CONTAINER_REF"}),
        ),
    }
    container_refs = {
        "tasks": ["task-list:authorized"],
        "calendar-events": ["calendar:authorized"],
    }
    prior_plans = {
        plan["route_id"]: plan
        for plan in build_query(
            {
                "schema_version": 2,
                "route_queries": [
                    {
                        "route_id": "tasks",
                        "operation": "SEARCH",
                        "reason_codes": ["USER_REQUEST"],
                        "search_spec": {
                            "mode": "INITIAL",
                            "constraints": [
                                {
                                    "kind": "CONTAINER_REF",
                                    "container_refs": container_refs["tasks"],
                                },
                                {"kind": "STATUS_SCOPE", "values": ["ANY"]},
                            ],
                        },
                        "detail_candidate_ref": None,
                    },
                    {
                        "route_id": "calendar-events",
                        "operation": "SEARCH",
                        "reason_codes": ["USER_REQUEST"],
                        "search_spec": {
                            "mode": "INITIAL",
                            "constraints": [
                                {
                                    "kind": "CONTAINER_REF",
                                    "container_refs": container_refs["calendar-events"],
                                },
                                {
                                    "kind": "KEYWORD",
                                    "terms": ["schedule"],
                                    "match_mode": "ANY",
                                },
                            ],
                        },
                        "detail_candidate_ref": None,
                    },
                ],
            },
            frozen_routes=routes,
            route_policies=policies,
            validated_container_refs=container_refs,
        )
    }
    return routes, policies, container_refs, prior_plans


def _retrieval_prompt_ref() -> PromptReference:
    return PromptReference(
        prompt_bundle_version="test",
        prompt_id="retrieval.plan_query",
        prompt_version="1",
        content_hash="hash",
        agent_role="retrieval",
        subgraph_name="retrieval",
        node_name="plan_query",
        node_state="INITIAL",
        purpose="plan_query",
        input_schema_version="v2",
        output_schema_version="v2",
    )


def test_initial_retrieval_planner_input__includes_current_run__user_request() -> None:
    route = cast(
        InputToolRouteV1,
        _tool_route_plan(allowed_read_tool_ids=["gmail_search_threads"])["input_plan"][
            "input_routes"
        ][0],
    )

    prompt_input = initial_retrieval_planner_input(
        user_request="Atlas final shipment date",
        request_intent=cast(
            RequestIntentV2,
            {
                "constraints": [
                    {
                        "kind": "USER_REQUIREMENT",
                        "field": "search_terms",
                        "value": "Atlas",
                        "provenance": {"source": "USER_REQUEST"},
                    },
                    {
                        "kind": "USER_REQUIREMENT",
                        "field": "business_concepts",
                        "value": ["최종 출고일"],
                        "provenance": {"source": "USER_REQUEST"},
                    },
                    {
                        "kind": "USER_REQUIREMENT",
                        "field": "search_terms",
                        "value": "invented-anchor",
                        "provenance": {"source": "SYSTEM"},
                    },
                ]
            },
        ),
        input_routes=[route],
        retrieval_budget=RetrievalBudget(),
    )

    assert prompt_input["user_request"] == "Atlas final shipment date"
    assert prompt_input["required_user_anchors"] == {
        "applies_to": "INITIAL_GMAIL_SEARCH",
        "route_ids": [route["route_id"]],
        "keyword_terms": ["Atlas"],
        "participant_identities": [],
    }


def test_plan_query__gmail_unfiltered_candidate__does_not_force_semantic_revision() -> None:
    route = cast(
        InputToolRouteV1,
        {
            "route_id": "route-1",
            "resource_type": "GMAIL_THREAD",
            "connector_id": "google_workspace",
            "allowed_read_tool_ids": ["gmail_search_threads"],
            "required": True,
            "reason_codes": ["USER_REQUEST"],
        },
    )
    provider_candidate = {
        "schema_version": 3,
        "route_queries": [
            {
                "route_id": "route-1",
                "operation": "SEARCH",
                "reason_codes": ["USER_REQUEST"],
                "search_spec": {
                    "mode": "INITIAL",
                    "constraints": {},
                },
                "detail_candidate_ref": None,
            }
        ],
    }
    runtime = FakeStructuredInferencePort(outputs=[provider_candidate])
    prompt_ref = PromptReference(
        prompt_bundle_version="test",
        prompt_id="retrieval.plan_query",
        prompt_version="1",
        content_hash="hash",
        agent_role="retrieval",
        subgraph_name="retrieval",
        node_name="plan_query",
        node_state="INITIAL",
        purpose="plan_query",
        input_schema_version="v2",
        output_schema_version="v2",
    )

    result, budget, llm_invoked = plan_query(
        llm_runtime=runtime,
        prompt_ref=prompt_ref,
        revision_prompt_ref=prompt_ref,
        output_schema=RETRIEVAL_QUERY_PLAN_V2_OUTPUT_SCHEMA,
        prompt_input={
            "request_intent": {"constraints": []},
            "input_routes": [route],
        },
        requested_mode="LOCAL_GPU",
        frozen_routes=[route],
        route_policies={"route-1": RouteConstraintPolicy(frozenset({"CONCEPT", "STATUS_SCOPE"}))},
        retry_budget=build_default_run_budget(),
    )

    assert result == {
        "schema_version": 2,
        "route_queries": [
            {
                "route_id": "route-1",
                "operation": "SEARCH",
                "reason_codes": ["USER_REQUEST"],
                "search_spec": {"mode": "INITIAL", "constraints": []},
                "detail_candidate_ref": None,
            }
        ],
    }
    assert llm_invoked is True
    assert len(runtime.calls) == 1
    assert runtime.calls[0]["output_schema"].schema_version == ("retrieval-query-plan-candidate-v3")
    assert budget["semantic_revisions_used_by_failure"] == {}


def _provenance_constraint(
    *, kind: str, field: str, value: str
) -> dict[str, object]:
    return {
        "kind": kind,
        "field": field,
        "value": value,
        "provenance": {
            "source": "USER_REQUEST",
            "start_offset": 0,
            "end_offset": len(value),
        },
    }


def _gmail_initial_candidate(*constraints: dict[str, object]) -> dict[str, object]:
    return {
        "schema_version": 2,
        "route_queries": [
            {
                "route_id": "route-1",
                "operation": "SEARCH",
                "reason_codes": ["USER_REQUEST"],
                "search_spec": {
                    "mode": "INITIAL",
                    "constraints": list(constraints),
                },
                "detail_candidate_ref": None,
            }
        ],
    }


def _run_gmail_initial_plan(
    *,
    constraints: list[dict[str, object]],
    outputs: list[object],
) -> tuple[dict[str, object], dict[str, object], FakeStructuredInferencePort]:
    route = cast(
        InputToolRouteV1,
        {
            "route_id": "route-1",
            "resource_type": "GMAIL_THREAD",
            "connector_id": "google_workspace",
            "allowed_read_tool_ids": ["gmail_search_threads"],
            "required": True,
            "reason_codes": ["USER_REQUEST"],
        },
    )
    runtime = FakeStructuredInferencePort(outputs=outputs)
    result, budget, _ = plan_query(
        llm_runtime=runtime,
        prompt_ref=_retrieval_prompt_ref(),
        revision_prompt_ref=_retrieval_prompt_ref(),
        output_schema=RETRIEVAL_QUERY_PLAN_V2_OUTPUT_SCHEMA,
        prompt_input={
            "request_intent": {"constraints": constraints},
            "input_routes": [route],
        },
        requested_mode="LOCAL_GPU",
        frozen_routes=[route],
        route_policies={
            "route-1": RouteConstraintPolicy(
                frozenset({"KEYWORD", "CONCEPT", "PARTICIPANT"})
            )
        },
        retry_budget=build_default_run_budget(),
    )
    return cast(dict[str, object], result), cast(dict[str, object], budget), runtime


@pytest.mark.parametrize(
    ("intent_constraint", "query_constraint"),
    [
        (
            _provenance_constraint(
                kind="USER_REQUIREMENT",
                field="search_terms",
                value="Lumen 마이그레이션 승인 메일",
            ),
            {"kind": "KEYWORD", "terms": ["Lumen"], "match_mode": "PHRASE"},
        ),
        (
            _provenance_constraint(
                kind="RESOURCE", field="subject", value="Atlas 납품 확정"
            ),
            {
                "kind": "KEYWORD",
                "terms": ["Atlas 납품 확정"],
                "match_mode": "PHRASE",
            },
        ),
        (
            _provenance_constraint(kind="PERSON", field="person", value="수민"),
            {"kind": "KEYWORD", "terms": ["수민"], "match_mode": "PHRASE"},
        ),
        (
            _provenance_constraint(
                kind="EMAIL", field="sender_email", value="sumin@example.com"
            ),
            {
                "kind": "PARTICIPANT",
                "participants": [{"role": "SENDER", "identity": "sumin@example.com"}],
                "match_mode": "ALL",
            },
        ),
    ],
)
def test_plan_query__explicit_user_anchor__is_preserved(
    intent_constraint: dict[str, object], query_constraint: dict[str, object]
) -> None:
    candidate = _gmail_initial_candidate(query_constraint)

    result, budget, runtime = _run_gmail_initial_plan(
        constraints=[intent_constraint],
        outputs=[candidate],
    )

    assert result == candidate
    assert budget["semantic_revisions_used_by_failure"] == {}
    assert len(runtime.calls) == 1


def test_plan_query__anchor_and_planner_manifestations__are_both_allowed() -> None:
    intent_constraints: list[dict[str, object]] = [
        _provenance_constraint(
            kind="USER_REQUIREMENT",
            field="search_terms",
            value="Lumen 마이그레이션 승인 메일",
        ),
        {
            "kind": "USER_REQUIREMENT",
            "field": "business_concepts",
            "value": "데이터 이전 시작 시간",
        },
    ]
    candidate = _gmail_initial_candidate(
        {"kind": "KEYWORD", "terms": ["Lumen"], "match_mode": "PHRASE"},
        {
            "kind": "CONCEPT",
            "concept": "데이터 이전 시작 시간",
            "manifestations": ["시작 예정 시간", "이전 시작일"],
        },
    )

    result, budget, _ = _run_gmail_initial_plan(
        constraints=intent_constraints,
        outputs=[candidate],
    )

    assert result == candidate
    assert budget["semantic_revisions_used_by_failure"] == {}


def test_plan_query__omitted_user_anchor__uses_existing_semantic_revision() -> None:
    intent_constraints: list[dict[str, object]] = [
        _provenance_constraint(
            kind="USER_REQUIREMENT",
            field="search_terms",
            value="Lumen 마이그레이션 승인 메일",
        ),
        {
            "kind": "USER_REQUIREMENT",
            "field": "business_concepts",
            "value": "데이터 이전 시작 시간",
        },
    ]
    omitted = _gmail_initial_candidate(
        {
            "kind": "CONCEPT",
            "concept": "데이터 이전 시작 시간",
            "manifestations": ["시작 예정 시간", "이전 시작일"],
        }
    )
    revised = _gmail_initial_candidate(
        {"kind": "KEYWORD", "terms": ["Lumen"], "match_mode": "PHRASE"}
    )

    result, budget, runtime = _run_gmail_initial_plan(
        constraints=intent_constraints,
        outputs=[omitted, revised],
    )

    assert result == revised
    assert sum(cast(dict[str, int], budget["semantic_revisions_used_by_failure"]).values()) == 1
    revision_input = cast(dict[str, object], runtime.calls[1]["prompt_input"])
    assert revision_input["candidate_output"] == omitted
    failure = cast(dict[str, object], revision_input["failure_record"])
    assert failure["failure_reason_code"] == "QUERY_USER_CONSTRAINT_MISSING"


def test_plan_query__concept_only__cannot_invent_exact_keyword_anchor() -> None:
    constraints: list[dict[str, object]] = [
        {
            "kind": "USER_REQUIREMENT",
            "field": "business_concepts",
            "value": "업무 일정",
        }
    ]
    invented = _gmail_initial_candidate(
        {"kind": "KEYWORD", "terms": ["Atlas"], "match_mode": "PHRASE"}
    )
    concept = _gmail_initial_candidate(
        {
            "kind": "CONCEPT",
            "concept": "업무 일정",
            "manifestations": ["일정"],
        }
    )

    result, budget, runtime = _run_gmail_initial_plan(
        constraints=constraints,
        outputs=[invented, concept],
    )

    assert result == concept
    assert sum(cast(dict[str, int], budget["semantic_revisions_used_by_failure"]).values()) == 1
    assert cast(dict[str, object], runtime.calls[1]["prompt_input"])[
        "candidate_output"
    ] == invented


def test_plan_query__multiple_user_anchors__does_not_force_all_match_mode() -> None:
    constraints = [
        _provenance_constraint(
            kind="USER_REQUIREMENT", field="search_terms", value=value
        )
        for value in ("Atlas", "Lumen")
    ]
    candidate = _gmail_initial_candidate(
        {
            "kind": "KEYWORD",
            "terms": ["Atlas", "Lumen"],
            "match_mode": "ANY",
        }
    )

    result, budget, _ = _run_gmail_initial_plan(
        constraints=constraints,
        outputs=[candidate],
    )

    assert result == candidate
    assert budget["semantic_revisions_used_by_failure"] == {}


def test_retrieval_followup_path__exhausted_selected_read__rejects() -> None:
    assert not has_retrieval_followup_path(
        request_intent=cast(RequestIntentV2, {"constraints": []}),
        tool_route_plan=_tool_route_plan(allowed_read_tool_ids=["gmail_get_thread"]),
        route_policies={"route-1": RouteConstraintPolicy(frozenset({"KEYWORD"}))},
        unresolved_sufficiency_issues=[],
        read_result_summaries=[],
        query_attempts=[],
    )


def test_retrieval_followup_path__lexical_anchor_or_unread_page__distinguishes() -> None:
    assert not has_retrieval_followup_path(
        request_intent=cast(RequestIntentV2, {"constraints": []}),
        tool_route_plan=_tool_route_plan(
            allowed_read_tool_ids=["gmail_search_threads", "gmail_get_thread"]
        ),
        route_policies={"route-1": RouteConstraintPolicy(frozenset({"KEYWORD"}))},
        unresolved_sufficiency_issues=[{"required": True, "resolution_source": "GOOGLE"}],
        read_result_summaries=[{"route_id": "route-1", "has_next_page": False, "result_count": 0}],
        query_attempts=[
            cast(
                QueryAttemptV1,
                {
                    "route_id": "route-1",
                    "operation_kind": "SEARCH",
                    "round_no": 0,
                    "normalized_intent_constraints": [
                        {
                            "kind": "KEYWORD",
                            "terms": ["회의 관련 메일"],
                            "match_mode": "PHRASE",
                        }
                    ],
                },
            )
        ],
    )
    assert has_retrieval_followup_path(
        request_intent=cast(RequestIntentV2, {"constraints": []}),
        tool_route_plan=_tool_route_plan(allowed_read_tool_ids=["gmail_get_thread"]),
        route_policies={"route-1": RouteConstraintPolicy(frozenset({"KEYWORD"}))},
        unresolved_sufficiency_issues=[{"required": True, "resolution_source": "GOOGLE"}],
        read_result_summaries=[{"route_id": "route-1", "has_next_page": True, "exhausted": False}],
        query_attempts=[],
    )


def test_retrieval_followup_path__selected_detail__does_not_expand_to_search() -> None:
    assert not has_retrieval_followup_path(
        request_intent=cast(RequestIntentV2, {"constraints": []}),
        tool_route_plan=_tool_route_plan(
            allowed_read_tool_ids=["gmail_search_threads", "gmail_get_thread"]
        ),
        route_policies={"route-1": RouteConstraintPolicy(frozenset({"KEYWORD"}))},
        unresolved_sufficiency_issues=[],
        read_result_summaries=[],
        query_attempts=[
            cast(
                QueryAttemptV1,
                {"route_id": "route-1", "operation_kind": "DETAIL_FETCH"},
            )
        ],
    )


def test_retrieval_followup_path__exhausted_identity_search__rejects() -> None:
    assert not has_retrieval_followup_path(
        request_intent=cast(RequestIntentV2, {"constraints": []}),
        tool_route_plan=_tool_route_plan(allowed_read_tool_ids=["tasks_list_tasks"]),
        route_policies={
            "route-1": RouteConstraintPolicy(
                frozenset({"CONTAINER_REF"}), frozenset({"CONTAINER_REF"})
            )
        },
        unresolved_sufficiency_issues=[],
        read_result_summaries=[{"has_next_page": False, "exhausted": True}],
        query_attempts=[cast(QueryAttemptV1, {"route_id": "route-1", "operation_kind": "SEARCH"})],
    )


@pytest.mark.parametrize(
    ("constraints", "search_attempt_count", "expected"),
    [
        ([{"kind": "RESOURCE", "field": "subject", "value": "정확한 제목"}], 1, True),
        ([], 2, True),
        ([], 3, False),
    ],
)
def test_retrieval_followup__with_format_change__preserves_progress_budget(
    constraints: list[dict[str, str]], search_attempt_count: int, expected: bool
) -> None:
    attempts = [
        cast(
            QueryAttemptV1,
            {
                "route_id": "route-1",
                "round_no": index,
                "operation_kind": "SEARCH",
                "stop_reason": "COMPLETE",
                "normalized_intent_constraints": [
                    {
                        "kind": "KEYWORD",
                        "terms": ["회의 관련 메일"],
                        "match_mode": "PHRASE",
                    }
                ],
            },
        )
        for index in range(search_attempt_count)
    ]

    assert (
        has_retrieval_followup_path(
            request_intent=cast(RequestIntentV2, {"constraints": constraints}),
            tool_route_plan=_tool_route_plan(
                allowed_read_tool_ids=["gmail_search_threads", "gmail_get_thread"]
            ),
            route_policies={"route-1": RouteConstraintPolicy(frozenset({"KEYWORD"}))},
            unresolved_sufficiency_issues=[{"required": True, "resolution_source": "GOOGLE"}],
            read_result_summaries=[{"route_id": "route-1", "result_count": 0, "exhausted": True}],
            query_attempts=attempts,
        )
        is expected
    )


def test_plan_query_is__the_only_product_prompt__owner_in_retrieval_core() -> None:
    owner = (
        Path(__file__).resolve().parents[5] / "src/google_work_agent/application/agents/retrieval"
    )
    plan_source = (owner / "plan_query.py").read_text(encoding="utf-8")
    assert "StructuredInferencePort" in plan_source
    assert "PromptReference" in plan_source
    for operation in (
        "build_query.py",
        "execute_read.py",
        "normalize_segments.py",
        "resolve_availability.py",
        "rag_retrieve_rerank.py",
    ):
        source = (owner / operation).read_text(encoding="utf-8")
        assert "PromptReference" not in source
        assert "StructuredInferencePort" not in source


def test_selected_exact_resource__materializes_detail_fetch__without_llm() -> None:
    runtime = FakeStructuredInferencePort(outputs=[])
    prompt_ref = PromptReference(
        prompt_bundle_version="test",
        prompt_id="retrieval.plan_query",
        prompt_version="1",
        content_hash="hash",
        agent_role="retrieval",
        subgraph_name="retrieval",
        node_name="plan_query",
        node_state="INITIAL",
        purpose="plan_query",
        input_schema_version="v2",
        output_schema_version="v2",
    )
    frozen_routes = [
        {
            "route_id": "route-1",
            "resource_type": "GMAIL_THREAD",
            "connector_id": "google_workspace",
            "allowed_read_tool_ids": ["gmail_get_thread"],
            "required": True,
            "reason_codes": ["RESOURCE_SELECTED"],
        }
    ]

    result, _, llm_invoked = plan_query(
        llm_runtime=runtime,
        prompt_ref=prompt_ref,
        revision_prompt_ref=prompt_ref,
        output_schema=RETRIEVAL_QUERY_PLAN_V2_OUTPUT_SCHEMA,
        prompt_input={"request_intent": {}, "input_routes": frozen_routes},
        requested_mode="LOCAL_GPU",
        frozen_routes=cast(list[InputToolRouteV1], frozen_routes),
        route_policies={"route-1": RouteConstraintPolicy(frozenset({"RESOURCE_REF"}))},
        retry_budget=build_default_run_budget(),
        validated_resource_refs={"route-1": ["gmail_thread:thread-42"]},
    )

    assert llm_invoked is False
    assert runtime.calls == []
    assert result["route_queries"] == [
        {
            "route_id": "route-1",
            "operation": "DETAIL_FETCH",
            "reason_codes": ["RESOURCE_SELECTED"],
            "search_spec": None,
            "detail_candidate_ref": "gmail_thread:thread-42",
        }
    ]


def test_selected_calendar_event__materializes_detail_fetch__without_search_container() -> None:
    runtime = FakeStructuredInferencePort(outputs=[])
    prompt_ref = PromptReference(
        prompt_bundle_version="test",
        prompt_id="retrieval.plan_query",
        prompt_version="1",
        content_hash="hash",
        agent_role="retrieval",
        subgraph_name="retrieval",
        node_name="plan_query",
        node_state="INITIAL",
        purpose="plan_query",
        input_schema_version="v2",
        output_schema_version="v2",
    )
    frozen_routes = [
        {
            "route_id": "event-detail",
            "resource_type": "CALENDAR_EVENT",
            "connector_id": "google_workspace",
            "allowed_read_tool_ids": ["calendar_get_event", "calendar_list_events"],
            "required": True,
            "reason_codes": ["RESOURCE_SELECTED"],
        }
    ]

    result, _, llm_invoked = plan_query(
        llm_runtime=runtime,
        prompt_ref=prompt_ref,
        revision_prompt_ref=prompt_ref,
        output_schema=RETRIEVAL_QUERY_PLAN_V2_OUTPUT_SCHEMA,
        prompt_input={
            "request_intent": {
                "constraints": [
                    {
                        "kind": "USER_REQUIREMENT",
                        "field": "search_terms",
                        "value": "confirmed target label",
                        "provenance": {"source": "CONFIRMATION_RESPONSE"},
                    }
                ]
            },
            "input_routes": frozen_routes,
        },
        requested_mode="LOCAL_GPU",
        frozen_routes=cast(list[InputToolRouteV1], frozen_routes),
        route_policies={
            "event-detail": RouteConstraintPolicy(
                frozenset({"TEMPORAL_RANGE", "CONTAINER_REF"}),
                frozenset({"CONTAINER_REF"}),
            )
        },
        retry_budget=build_default_run_budget(),
        validated_resource_refs={"event-detail": ["calendar_event:event-42"]},
    )

    assert llm_invoked is False
    assert runtime.calls == []
    assert result["route_queries"] == [
        {
            "route_id": "event-detail",
            "operation": "DETAIL_FETCH",
            "reason_codes": ["RESOURCE_SELECTED"],
            "search_spec": None,
            "detail_candidate_ref": "calendar_event:event-42",
        }
    ]


def test_calendar_search__without_container_authority__rejects_plan() -> None:
    runtime = FakeStructuredInferencePort(outputs=[])
    prompt_ref = PromptReference(
        prompt_bundle_version="test",
        prompt_id="retrieval.plan_query",
        prompt_version="1",
        content_hash="hash",
        agent_role="retrieval",
        subgraph_name="retrieval",
        node_name="plan_query",
        node_state="INITIAL",
        purpose="plan_query",
        input_schema_version="v2",
        output_schema_version="v2",
    )
    frozen_routes = cast(
        list[InputToolRouteV1],
        [
            {
                "route_id": "event-search",
                "resource_type": "CALENDAR_EVENT",
                "connector_id": "google_workspace",
                "allowed_read_tool_ids": ["calendar_list_events"],
                "required": True,
                "reason_codes": ["USER_REQUEST"],
            }
        ],
    )

    with pytest.raises(
        RetrievalV2ValidationError, match="requires validated container scope"
    ) as caught:
        plan_query(
            llm_runtime=runtime,
            prompt_ref=prompt_ref,
            revision_prompt_ref=prompt_ref,
            output_schema=RETRIEVAL_QUERY_PLAN_V2_OUTPUT_SCHEMA,
            prompt_input={"request_intent": {}, "input_routes": frozen_routes},
            requested_mode="LOCAL_GPU",
            frozen_routes=frozen_routes,
            route_policies={
                "event-search": RouteConstraintPolicy(
                    frozenset({"TEMPORAL_RANGE", "CONTAINER_REF"}),
                    frozenset({"CONTAINER_REF"}),
                )
            },
            retry_budget=build_default_run_budget(),
        )

    assert runtime.calls == []
    assert caught.value.reason_code == "RETRIEVAL_ROUTE_SCOPE_VIOLATION"
    assert caught.value.validation_stage == "QUERY_PLAN_VALIDATOR"
    assert caught.value.affected_field_paths == ("$.validated_container_refs",)


def test_explicit_resource_id__materializes_detail_fetch__without_llm() -> None:
    runtime = FakeStructuredInferencePort(outputs=[])
    prompt_ref = PromptReference(
        prompt_bundle_version="test",
        prompt_id="retrieval.plan_query",
        prompt_version="1",
        content_hash="hash",
        agent_role="retrieval",
        subgraph_name="retrieval",
        node_name="plan_query",
        node_state="INITIAL",
        purpose="plan_query",
        input_schema_version="v2",
        output_schema_version="v2",
    )
    frozen_routes = [
        {
            "route_id": "route-draft",
            "resource_type": "GMAIL_DRAFT",
            "connector_id": "google_workspace",
            "allowed_read_tool_ids": ["gmail_get_draft"],
            "required": True,
            "reason_codes": ["EXPLICIT_RESOURCE_ID"],
        }
    ]

    result, _, llm_invoked = plan_query(
        llm_runtime=runtime,
        prompt_ref=prompt_ref,
        revision_prompt_ref=prompt_ref,
        output_schema=RETRIEVAL_QUERY_PLAN_V2_OUTPUT_SCHEMA,
        prompt_input={"request_intent": {}, "input_routes": frozen_routes},
        requested_mode="LOCAL_GPU",
        frozen_routes=cast(list[InputToolRouteV1], frozen_routes),
        route_policies={"route-draft": RouteConstraintPolicy(frozenset({"RESOURCE_REF"}))},
        retry_budget=build_default_run_budget(),
        validated_resource_refs={"route-draft": ["gmail_draft:r976635311795334843"]},
    )

    assert llm_invoked is False
    assert runtime.calls == []
    assert result["route_queries"] == [
        {
            "route_id": "route-draft",
            "operation": "DETAIL_FETCH",
            "reason_codes": ["EXPLICIT_RESOURCE_ID"],
            "search_spec": None,
            "detail_candidate_ref": "gmail_draft:r976635311795334843",
        }
    ]


def test_draft_update__searches_only_user_bound_source_title__without_llm() -> None:
    runtime = FakeStructuredInferencePort(outputs=[])
    prompt_ref = PromptReference(
        prompt_bundle_version="test",
        prompt_id="retrieval.plan_query",
        prompt_version="1",
        content_hash="hash",
        agent_role="retrieval",
        subgraph_name="retrieval",
        node_name="plan_query",
        node_state="INITIAL",
        purpose="plan_query",
        input_schema_version="v2",
        output_schema_version="v2",
    )
    route = cast(
        InputToolRouteV1,
        {
            "route_id": "route-draft",
            "resource_type": "GMAIL_DRAFT",
            "connector_id": "google_workspace",
            "allowed_read_tool_ids": ["gmail_search_drafts", "gmail_get_draft"],
            "required": True,
            "reason_codes": ["USER_REQUEST"],
        },
    )
    intent = {
        "goal": "초안 끝에 새 문장을 추가한다.",
        "completion_conditions": ["8월 21일 입고 준비를 확인 중입니다.를 추가한다."],
        "constraints": [
            {
                "kind": "USER_REQUIREMENT",
                "field": "search_terms",
                "value": "Quartz 납품 회신 검토",
                "provenance": {
                    "source": "USER_REQUEST",
                    "start_offset": 8,
                    "end_offset": 22,
                },
            },
            {
                "kind": "USER_REQUIREMENT",
                "field": "business_concepts",
                "value": ["8월 21일", "입고 준비"],
            },
        ],
        "requested_effect_hints": ["READ", "UPDATE"],
        "requested_resource_hints": ["GMAIL_DRAFT"],
    }

    result, _, llm_invoked = plan_query(
        llm_runtime=runtime,
        prompt_ref=prompt_ref,
        revision_prompt_ref=prompt_ref,
        output_schema=RETRIEVAL_QUERY_PLAN_V2_OUTPUT_SCHEMA,
        prompt_input={"request_intent": intent, "input_routes": [route]},
        requested_mode="LOCAL_GPU",
        frozen_routes=[route],
        route_policies={
            "route-draft": RouteConstraintPolicy(
                frozenset({"KEYWORD", "STATUS_SCOPE"}),
                frozenset({"STATUS_SCOPE"}),
            )
        },
        retry_budget=build_default_run_budget(),
    )

    assert llm_invoked is False
    assert runtime.calls == []
    assert result["route_queries"] == [
        {
            "route_id": "route-draft",
            "operation": "SEARCH",
            "reason_codes": ["EXACT_DRAFT_SOURCE_LOOKUP"],
            "search_spec": {
                "mode": "INITIAL",
                "constraints": [
                    {
                        "kind": "KEYWORD",
                        "terms": ["Quartz 납품 회신 검토"],
                        "match_mode": "PHRASE",
                    },
                    {"kind": "STATUS_SCOPE", "values": ["DRAFT"]},
                ],
            },
            "detail_candidate_ref": None,
        }
    ]


def test_plan_query__with_exhaustive_gmail_subject_collection__uses_request_prefix() -> None:
    runtime = FakeStructuredInferencePort(outputs=[])
    prompt_ref = PromptReference(
        prompt_bundle_version="test",
        prompt_id="retrieval.plan_query",
        prompt_version="1",
        content_hash="hash",
        agent_role="retrieval",
        subgraph_name="retrieval",
        node_name="plan_query",
        node_state="INITIAL",
        purpose="plan_query",
        input_schema_version="v2",
        output_schema_version="v2",
    )
    route = cast(
        InputToolRouteV1,
        {
            "route_id": "route-gmail",
            "resource_type": "GMAIL_THREAD",
            "connector_id": "google_workspace",
            "allowed_read_tool_ids": ["gmail_search_threads", "gmail_get_thread"],
            "required": True,
            "reason_codes": ["USER_REQUEST"],
        },
    )
    intent = cast(
        RequestIntentV2,
        {
            "goal": "Orion rollout planning email titles",
            "completion_conditions": ["return every title"],
            "constraints": [
                {
                    "kind": "USER_REQUIREMENT",
                    "field": "search_terms",
                    "value": "Orion rollout planning",
                    "provenance": {
                        "source": "USER_REQUEST",
                        "start_offset": 0,
                        "end_offset": 22,
                    },
                },
                {"kind": "SCOPE", "field": "coverage_requirement", "value": "EXHAUSTIVE"},
            ],
            "requested_effect_hints": ["READ"],
            "requested_resource_hints": ["GMAIL_THREAD"],
            "analysis_requirement": "NONE",
            "resource_responsibilities": {
                "source_reads": [
                    {
                        "resource_type": "GMAIL_THREAD",
                        "required_information": ["thread_identity", "subject"],
                    }
                ],
                "outputs": [],
            },
        },
    )

    result, _, llm_invoked = plan_query(
        llm_runtime=runtime,
        prompt_ref=prompt_ref,
        revision_prompt_ref=prompt_ref,
        output_schema=RETRIEVAL_QUERY_PLAN_V2_OUTPUT_SCHEMA,
        prompt_input={"request_intent": intent, "input_routes": [route]},
        requested_mode="LOCAL_GPU",
        frozen_routes=[route],
        route_policies={"route-gmail": RouteConstraintPolicy(frozenset({"KEYWORD"}))},
        retry_budget=build_default_run_budget(),
    )

    assert llm_invoked is False
    assert runtime.calls == []
    assert result["route_queries"] == [
        {
            "route_id": "route-gmail",
            "operation": "SEARCH",
            "reason_codes": ["EXHAUSTIVE_METADATA_COLLECTION_SEARCH"],
            "search_spec": {
                "mode": "INITIAL",
                "constraints": [
                    {"kind": "KEYWORD", "terms": ["Orion", "rollout"], "match_mode": "ALL"}
                ],
            },
            "detail_candidate_ref": None,
        }
    ]


def test_followup_with_ranked_candidate__materializes_detail_fetch__without_llm() -> None:
    runtime = FakeStructuredInferencePort(outputs=[])
    prompt_ref = PromptReference(
        prompt_bundle_version="test",
        prompt_id="retrieval.plan_query",
        prompt_version="1",
        content_hash="hash",
        agent_role="retrieval",
        subgraph_name="retrieval",
        node_name="plan_query",
        node_state="INITIAL",
        purpose="plan_query",
        input_schema_version="v2",
        output_schema_version="v2",
    )
    frozen_routes = [
        {
            "route_id": "route-1",
            "resource_type": "GMAIL_THREAD",
            "connector_id": "google_workspace",
            "allowed_read_tool_ids": ["gmail_search_threads", "gmail_get_thread"],
            "required": True,
            "reason_codes": ["USER_REQUEST"],
        }
    ]

    result, _, llm_invoked = plan_query(
        llm_runtime=runtime,
        prompt_ref=prompt_ref,
        revision_prompt_ref=prompt_ref,
        output_schema=RETRIEVAL_QUERY_PLAN_V2_OUTPUT_SCHEMA,
        prompt_input={
            "current_round_no": 0,
            "unresolved_sufficiency_issues": [
                {
                    "required": True,
                    "resolution_source": "GOOGLE",
                    "reason_codes": ["INCOMPLETE"],
                }
            ],
        },
        requested_mode="LOCAL_GPU",
        frozen_routes=cast(list[InputToolRouteV1], frozen_routes),
        route_policies={"route-1": RouteConstraintPolicy(frozenset({"KEYWORD"}))},
        retry_budget=build_default_run_budget(),
        detail_candidate_refs=[
            "gmail_thread:already-read",
            "gmail_thread:next-candidate",
        ],
        attempted_detail_candidate_refs=["gmail_thread:already-read"],
    )

    assert llm_invoked is False
    assert runtime.calls == []
    assert result["route_queries"] == [
        {
            "route_id": "route-1",
            "operation": "DETAIL_FETCH",
            "reason_codes": ["CANDIDATE_DETAIL_REQUIRED"],
            "search_spec": None,
            "detail_candidate_ref": "gmail_thread:next-candidate",
        }
    ]


@pytest.mark.parametrize(
    ("coverage_requirement", "expected_operation"),
    [(None, "DETAIL_FETCH"), ("EXHAUSTIVE", "NEXT_PAGE")],
    ids=["normal-fact-detail-first", "exhaustive-page-first"],
)
def test_plan_query__page_and_detail_candidate__uses_coverage_aware_priority(
    coverage_requirement: str | None,
    expected_operation: Literal["DETAIL_FETCH", "NEXT_PAGE"],
) -> None:
    runtime = FakeStructuredInferencePort(outputs=[])
    route = cast(
        InputToolRouteV1,
        {
            "route_id": "route-1",
            "resource_type": "GMAIL_THREAD",
            "connector_id": "google_workspace",
            "allowed_read_tool_ids": ["gmail_search_threads", "gmail_get_thread"],
            "required": True,
            "reason_codes": ["USER_REQUEST"],
        },
    )
    policy = {"route-1": RouteConstraintPolicy(frozenset({"KEYWORD"}))}
    prior = build_query(
        {
            "schema_version": 2,
            "route_queries": [
                {
                    "route_id": "route-1",
                    "operation": "SEARCH",
                    "reason_codes": ["USER_REQUEST"],
                    "search_spec": {
                        "mode": "INITIAL",
                        "constraints": [
                            {"kind": "KEYWORD", "terms": ["Juniper"], "match_mode": "ALL"}
                        ],
                    },
                    "detail_candidate_ref": None,
                }
            ],
        },
        frozen_routes=[route],
        route_policies=policy,
    )[0]
    read_summaries = [
        {
            "route_id": "route-1",
            "query_identity_hash": prior["query_identity_hash"],
            "read_result_handle": "page-1",
            "result_count": 20,
            "has_next_page": True,
            "exhausted": False,
        }
    ]

    result, _, llm_invoked = plan_query(
        llm_runtime=runtime,
        prompt_ref=_retrieval_prompt_ref(),
        revision_prompt_ref=_retrieval_prompt_ref(),
        output_schema=RETRIEVAL_QUERY_PLAN_V2_OUTPUT_SCHEMA,
        prompt_input={
            "request_intent": cast(
                RequestIntentV2,
                {
                    "constraints": (
                        []
                        if coverage_requirement is None
                        else [
                            {
                                "kind": "SCOPE",
                                "field": "coverage_requirement",
                                "value": coverage_requirement,
                            }
                        ]
                    ),
                },
            ),
            "current_round_no": 1,
            "unresolved_sufficiency_issues": [
                {
                    "required": True,
                    "resolution_source": "GOOGLE",
                    "route_id": "route-1",
                    "reason_codes": ["CANDIDATE_DETAIL_REQUIRED"],
                },
                {
                    "required": True,
                    "resolution_source": "GOOGLE",
                    "route_id": "route-1",
                    "reason_codes": ["COLLECTION_PAGE_REMAINS"],
                },
            ],
            "read_result_summaries": read_summaries,
        },
        requested_mode="LOCAL_GPU",
        frozen_routes=[route],
        route_policies=policy,
        retry_budget=build_default_run_budget(),
        detail_candidate_refs=["gmail_thread:candidate"],
        prior_plans={"route-1": prior},
        read_result_summaries=read_summaries,
    )

    assert llm_invoked is False
    assert runtime.calls == []
    assert result["route_queries"] == [
        {
            "route_id": "route-1",
            "operation": expected_operation,
            "reason_codes": [
                "CANDIDATE_DETAIL_REQUIRED"
                if expected_operation == "DETAIL_FETCH"
                else "UNREAD_PAGE_AVAILABLE"
            ],
            "search_spec": None,
            "detail_candidate_ref": (
                "gmail_thread:candidate" if expected_operation == "DETAIL_FETCH" else None
            ),
        }
    ]


def test_confirmed_target__during_query_planning__preserves_phrase_anchor_and_container() -> None:
    runtime = FakeStructuredInferencePort(outputs=[])
    frozen_routes = cast(
        list[InputToolRouteV1],
        [
            {
                "route_id": "event-search",
                "resource_type": "CALENDAR_EVENT",
                "connector_id": "google_workspace",
                "allowed_read_tool_ids": ["calendar_list_events"],
                "required": True,
                "reason_codes": ["REQUESTED_INPUT"],
            },
            {
                "route_id": "calendar-discovery",
                "resource_type": "CALENDAR",
                "connector_id": "google_workspace",
                "allowed_read_tool_ids": ["calendar_list_calendars"],
                "required": True,
                "reason_codes": ["RETRIEVAL_CALENDAR_DISCOVERY"],
            },
        ],
    )
    policies = {
        "event-search": RouteConstraintPolicy(
            frozenset({"KEYWORD", "CONTAINER_REF"}),
            frozenset({"CONTAINER_REF"}),
        ),
        "calendar-discovery": RouteConstraintPolicy(frozenset({"CONTAINER_REF"})),
    }

    result, _, llm_invoked = plan_query(
        llm_runtime=runtime,
        prompt_ref=_retrieval_prompt_ref(),
        revision_prompt_ref=_retrieval_prompt_ref(),
        output_schema=RETRIEVAL_QUERY_PLAN_V2_OUTPUT_SCHEMA,
        prompt_input={
            "request_intent": {
                "constraints": [
                    {
                        "kind": "USER_REQUIREMENT",
                        "field": "search_terms",
                        "value": "confirmed target label",
                        "provenance": {
                            "source": "CONFIRMATION_RESPONSE",
                            "start_offset": 0,
                            "end_offset": 22,
                            "source_text": "confirmed target label",
                        },
                    }
                ]
            },
            "input_routes": frozen_routes,
        },
        requested_mode="LOCAL_GPU",
        frozen_routes=frozen_routes,
        route_policies=policies,
        retry_budget=build_default_run_budget(),
        validated_container_refs={"event-search": ["calendar:authorized"]},
    )

    assert llm_invoked is False
    assert runtime.calls == []
    assert result["route_queries"] == [
        {
            "route_id": "event-search",
            "operation": "SEARCH",
            "reason_codes": ["CONFIRMED_TARGET_DISCOVERY"],
            "search_spec": {
                "mode": "INITIAL",
                "constraints": [
                    {
                        "kind": "KEYWORD",
                        "terms": ["confirmed target label"],
                        "match_mode": "PHRASE",
                    },
                    {
                        "kind": "CONTAINER_REF",
                        "container_refs": ["calendar:authorized"],
                    },
                ],
            },
            "detail_candidate_ref": None,
        }
    ]


def test_retrieval_followup__no_required_google_issue__keeps_query_planning_llm() -> None:
    output = {
        "schema_version": 2,
        "route_queries": [
            {
                "route_id": "route-1",
                "operation": "NEXT_PAGE",
                "reason_codes": ["MORE_RESULTS_AVAILABLE"],
                "search_spec": None,
                "detail_candidate_ref": None,
            }
        ],
    }
    runtime = FakeStructuredInferencePort(outputs=[output])
    prompt_ref = PromptReference(
        prompt_bundle_version="test",
        prompt_id="retrieval.plan_query",
        prompt_version="1",
        content_hash="hash",
        agent_role="retrieval",
        subgraph_name="retrieval",
        node_name="plan_query",
        node_state="INITIAL",
        purpose="plan_query",
        input_schema_version="v2",
        output_schema_version="v2",
    )
    frozen_routes = [
        {
            "route_id": "route-1",
            "resource_type": "GMAIL_THREAD",
            "connector_id": "google_workspace",
            "allowed_read_tool_ids": ["gmail_search_threads", "gmail_get_thread"],
            "required": True,
            "reason_codes": ["USER_REQUEST"],
        }
    ]
    route = cast(InputToolRouteV1, frozen_routes[0])
    policy = {"route-1": RouteConstraintPolicy(frozenset({"KEYWORD"}))}
    prior = build_query(
        {
            "schema_version": 2,
            "route_queries": [
                {
                    "route_id": "route-1",
                    "operation": "SEARCH",
                    "reason_codes": ["USER_REQUEST"],
                    "search_spec": {
                        "mode": "INITIAL",
                        "constraints": [
                            {"kind": "KEYWORD", "terms": ["Quartz"], "match_mode": "PHRASE"}
                        ],
                    },
                    "detail_candidate_ref": None,
                }
            ],
        },
        frozen_routes=[route],
        route_policies=policy,
    )[0]
    read_summaries = [
        {
            "route_id": "route-1",
            "query_identity_hash": prior["query_identity_hash"],
            "read_result_handle": "page-1",
            "has_next_page": True,
            "exhausted": False,
        }
    ]

    _, _, llm_invoked = plan_query(
        llm_runtime=runtime,
        prompt_ref=prompt_ref,
        revision_prompt_ref=prompt_ref,
        output_schema=RETRIEVAL_QUERY_PLAN_V2_OUTPUT_SCHEMA,
        prompt_input={
            "current_round_no": 0,
            "unresolved_sufficiency_issues": [],
            "read_result_summaries": read_summaries,
        },
        requested_mode="LOCAL_GPU",
        frozen_routes=cast(list[InputToolRouteV1], frozen_routes),
        route_policies=policy,
        retry_budget=build_default_run_budget(),
        detail_candidate_refs=["gmail_thread:candidate"],
        prior_plans={"route-1": prior},
        read_result_summaries=read_summaries,
    )

    assert llm_invoked is True
    assert len(runtime.calls) == 1


def test_plan_query__required_followup_routes__revises_omitting_candidate() -> None:
    routes, policies, container_refs, prior_plans = _task_calendar_followup_context()
    task_summary = {
        "route_id": "tasks",
        "query_identity_hash": prior_plans["tasks"]["query_identity_hash"],
        "read_result_handle": "tasks-page-1",
        "result_count": 20,
        "has_next_page": True,
        "exhausted": False,
    }
    revised = {
        "schema_version": 2,
        "route_queries": [
            {
                "route_id": "tasks",
                "operation": "NEXT_PAGE",
                "reason_codes": ["UNREAD_PAGE_AVAILABLE"],
                "search_spec": None,
                "detail_candidate_ref": None,
            },
            {
                "route_id": "calendar-events",
                "operation": "SEARCH",
                "reason_codes": ["INSUFFICIENT_EVIDENCE"],
                "search_spec": {
                    "mode": "CHANGED",
                    "constraint_delta": {
                        "upsert_constraints": [
                            {
                                "kind": "KEYWORD",
                                "terms": ["delivery schedule"],
                                "match_mode": "ANY",
                            }
                        ],
                        "remove_constraint_kinds": [],
                    },
                },
                "detail_candidate_ref": None,
            },
        ],
    }
    runtime = FakeStructuredInferencePort(outputs=[revised])

    result, budget, llm_invoked = plan_query(
        llm_runtime=runtime,
        prompt_ref=_retrieval_prompt_ref(),
        revision_prompt_ref=_retrieval_prompt_ref(),
        output_schema=RETRIEVAL_QUERY_PLAN_V2_OUTPUT_SCHEMA,
        prompt_input={
            "request_intent": {"constraints": []},
            "input_routes": routes,
            "current_round_no": 1,
            "prior_query_attempts": [],
            "unresolved_sufficiency_issues": [
                {
                    "required": True,
                    "resolution_source": "GOOGLE",
                    "route_id": "tasks",
                },
                {
                    "required": True,
                    "resolution_source": "GOOGLE",
                    "route_id": "calendar-events",
                },
            ],
            "read_result_summaries": [task_summary],
        },
        requested_mode="LOCAL_GPU",
        frozen_routes=routes,
        route_policies=policies,
        retry_budget=build_default_run_budget(),
        validated_container_refs=container_refs,
        prior_plans=prior_plans,
        read_result_summaries=[task_summary],
    )

    assert [query["route_id"] for query in result["route_queries"]] == [
        "tasks",
        "calendar-events",
    ]
    assert llm_invoked is True
    assert len(runtime.calls) == 1
    assert sum(budget["semantic_revisions_used_by_failure"].values()) == 1
    revision_input = cast(dict[str, object], runtime.calls[0]["prompt_input"])
    failure_record = cast(dict[str, object], revision_input["failure_record"])
    assert failure_record["failure_reason_code"] == "RETRIEVAL_QUERY_PLAN_SEMANTIC_INVALID"
    assert failure_record["affected_field_paths"] == ["$.route_queries"]
    omitted_candidate = cast(dict[str, object], revision_input["candidate_output"])
    omitted_queries = cast(list[dict[str, object]], omitted_candidate["route_queries"])
    assert [query["route_id"] for query in omitted_queries] == ["tasks"]


def test_plan_query__llm_candidate_omitting_required_route__uses_semantic_revision() -> None:
    routes, policies, container_refs, prior_plans = _task_calendar_followup_context()
    task_query = {
        "route_id": "tasks",
        "operation": "SEARCH",
        "reason_codes": ["INSUFFICIENT_EVIDENCE"],
        "search_spec": {
            "mode": "CHANGED",
            "constraint_delta": {
                "upsert_constraints": [
                    {"kind": "STATUS_SCOPE", "values": ["COMPLETED"]}
                ],
                "remove_constraint_kinds": [],
            },
        },
        "detail_candidate_ref": None,
    }
    initial = {"schema_version": 2, "route_queries": [task_query]}
    revised = {
        "schema_version": 2,
        "route_queries": [
            task_query,
            {
                "route_id": "calendar-events",
                "operation": "SEARCH",
                "reason_codes": ["INSUFFICIENT_EVIDENCE"],
                "search_spec": {
                    "mode": "CHANGED",
                    "constraint_delta": {
                        "upsert_constraints": [
                            {
                                "kind": "KEYWORD",
                                "terms": ["delivery schedule"],
                                "match_mode": "ANY",
                            }
                        ],
                        "remove_constraint_kinds": [],
                    },
                },
                "detail_candidate_ref": None,
            },
        ],
    }
    runtime = FakeStructuredInferencePort(outputs=[initial, revised])

    result, budget, llm_invoked = plan_query(
        llm_runtime=runtime,
        prompt_ref=_retrieval_prompt_ref(),
        revision_prompt_ref=_retrieval_prompt_ref(),
        output_schema=RETRIEVAL_QUERY_PLAN_V2_OUTPUT_SCHEMA,
        prompt_input={
            "request_intent": {"constraints": []},
            "input_routes": routes,
            "current_round_no": 1,
            "prior_query_attempts": [],
            "unresolved_sufficiency_issues": [
                {
                    "required": True,
                    "resolution_source": "GOOGLE",
                    "route_id": route_id,
                }
                for route_id in ("tasks", "calendar-events")
            ],
            "read_result_summaries": [],
        },
        requested_mode="LOCAL_GPU",
        frozen_routes=routes,
        route_policies=policies,
        retry_budget=build_default_run_budget(),
        validated_container_refs=container_refs,
        prior_plans=prior_plans,
        read_result_summaries=[],
    )

    assert [query["route_id"] for query in result["route_queries"]] == [
        "tasks",
        "calendar-events",
    ]
    assert llm_invoked is True
    assert len(runtime.calls) == 2
    assert sum(budget["semantic_revisions_used_by_failure"].values()) == 1
    revision_input = cast(dict[str, object], runtime.calls[1]["prompt_input"])
    assert revision_input["candidate_output"] == initial
    failure_record = cast(dict[str, object], revision_input["failure_record"])
    assert failure_record["affected_field_paths"] == ["$.route_queries"]


@pytest.mark.parametrize("required_route_id", ["tasks", "calendar-events"])
def test_plan_query__single_unresolved_route__does_not_force_resolved_route(
    required_route_id: str,
) -> None:
    routes, policies, container_refs, prior_plans = _task_calendar_followup_context()
    summary = {
        "route_id": required_route_id,
        "query_identity_hash": prior_plans[required_route_id]["query_identity_hash"],
        "read_result_handle": f"{required_route_id}-page-1",
        "result_count": 20,
        "has_next_page": True,
        "exhausted": False,
    }
    runtime = FakeStructuredInferencePort(outputs=[])

    result, _, llm_invoked = plan_query(
        llm_runtime=runtime,
        prompt_ref=_retrieval_prompt_ref(),
        revision_prompt_ref=_retrieval_prompt_ref(),
        output_schema=RETRIEVAL_QUERY_PLAN_V2_OUTPUT_SCHEMA,
        prompt_input={
            "request_intent": {"constraints": []},
            "input_routes": routes,
            "current_round_no": 1,
            "prior_query_attempts": [],
            "unresolved_sufficiency_issues": [
                {
                    "required": True,
                    "resolution_source": "GOOGLE",
                    "route_id": required_route_id,
                }
            ],
            "read_result_summaries": [summary],
        },
        requested_mode="LOCAL_GPU",
        frozen_routes=routes,
        route_policies=policies,
        retry_budget=build_default_run_budget(),
        validated_container_refs=container_refs,
        prior_plans=prior_plans,
        read_result_summaries=[summary],
    )

    assert [query["route_id"] for query in result["route_queries"]] == [required_route_id]
    assert llm_invoked is False
    assert runtime.calls == []


def test_plan_query__optional_followup_issue__does_not_force_route() -> None:
    routes, policies, container_refs, prior_plans = _task_calendar_followup_context()
    task_summary = {
        "route_id": "tasks",
        "query_identity_hash": prior_plans["tasks"]["query_identity_hash"],
        "read_result_handle": "tasks-page-1",
        "result_count": 20,
        "has_next_page": True,
        "exhausted": False,
    }
    runtime = FakeStructuredInferencePort(outputs=[])

    result, _, llm_invoked = plan_query(
        llm_runtime=runtime,
        prompt_ref=_retrieval_prompt_ref(),
        revision_prompt_ref=_retrieval_prompt_ref(),
        output_schema=RETRIEVAL_QUERY_PLAN_V2_OUTPUT_SCHEMA,
        prompt_input={
            "request_intent": {"constraints": []},
            "input_routes": routes,
            "current_round_no": 1,
            "prior_query_attempts": [],
            "unresolved_sufficiency_issues": [
                {
                    "required": True,
                    "resolution_source": "GOOGLE",
                    "route_id": "tasks",
                },
                {
                    "required": False,
                    "resolution_source": "GOOGLE",
                    "route_id": "calendar-events",
                },
            ],
            "read_result_summaries": [task_summary],
        },
        requested_mode="LOCAL_GPU",
        frozen_routes=routes,
        route_policies=policies,
        retry_budget=build_default_run_budget(),
        validated_container_refs=container_refs,
        prior_plans=prior_plans,
        read_result_summaries=[task_summary],
    )

    assert [query["route_id"] for query in result["route_queries"]] == ["tasks"]
    assert llm_invoked is False
    assert runtime.calls == []


def test_gmail_followup__can_add_concept__without_replacing_protected_keyword() -> None:
    output = {
        "schema_version": 2,
        "route_queries": [
            {
                "route_id": "route-1",
                "operation": "SEARCH",
                "reason_codes": ["INSUFFICIENT_EVIDENCE"],
                "search_spec": {
                    "mode": "CHANGED",
                    "constraint_delta": {
                        "upsert_constraints": [
                            {
                                "kind": "CONCEPT",
                                "concept": "delivery schedule",
                                "manifestations": ["납품 일정"],
                            }
                        ],
                        "remove_constraint_kinds": [],
                    },
                },
                "detail_candidate_ref": None,
            }
        ],
    }
    runtime = FakeStructuredInferencePort(outputs=[output])
    prompt_ref = PromptReference(
        prompt_bundle_version="test",
        prompt_id="retrieval.plan_query",
        prompt_version="1",
        content_hash="hash",
        agent_role="retrieval",
        subgraph_name="retrieval",
        node_name="plan_query",
        node_state="INITIAL",
        purpose="plan_query",
        input_schema_version="v2",
        output_schema_version="v2",
    )
    frozen_routes = [
        {
            "route_id": "route-1",
            "resource_type": "GMAIL_THREAD",
            "connector_id": "google_workspace",
            "allowed_read_tool_ids": ["gmail_search_threads", "gmail_get_thread"],
            "required": True,
            "reason_codes": ["USER_REQUEST"],
        }
    ]
    prior_keyword = {
        "kind": "KEYWORD",
        "terms": ["Quartz"],
        "match_mode": "PHRASE",
    }
    route = cast(InputToolRouteV1, frozen_routes[0])
    policies = {"route-1": RouteConstraintPolicy(frozenset({"KEYWORD", "CONCEPT"}))}
    prior = build_query(
        {
            "schema_version": 2,
            "route_queries": [
                {
                    "route_id": "route-1",
                    "operation": "SEARCH",
                    "reason_codes": ["USER_REQUEST"],
                    "search_spec": {"mode": "INITIAL", "constraints": [prior_keyword]},
                    "detail_candidate_ref": None,
                }
            ],
        },
        frozen_routes=[route],
        route_policies=policies,
    )[0]

    result, _, llm_invoked = plan_query(
        llm_runtime=runtime,
        prompt_ref=prompt_ref,
        revision_prompt_ref=prompt_ref,
        output_schema=RETRIEVAL_QUERY_PLAN_V2_OUTPUT_SCHEMA,
        prompt_input={
            "request_intent": {
                "constraints": [{"kind": "RESOURCE", "field": "title", "value": "Quartz"}]
            },
            "input_routes": frozen_routes,
            "current_round_no": 1,
            "prior_query_attempts": [
                {
                    "route_id": "route-1",
                    "operation_kind": "SEARCH",
                    "round_no": 0,
                    "normalized_intent_constraints": [prior_keyword],
                }
            ],
            "unresolved_sufficiency_issues": [{"required": True, "resolution_source": "GOOGLE"}],
            "read_result_summaries": [],
        },
        requested_mode="LOCAL_GPU",
        frozen_routes=cast(list[InputToolRouteV1], frozen_routes),
        route_policies=policies,
        retry_budget=build_default_run_budget(),
        prior_plans={"route-1": prior},
    )

    assert llm_invoked is True
    assert result == output
    projected_input = cast(dict[str, object], runtime.calls[0]["prompt_input"])
    projected_routes = cast(list[dict[str, object]], projected_input["input_routes"])
    assert projected_routes[0]["supported_constraint_kinds"] == ["CONCEPT", "KEYWORD"]


def test_plan_query__unverified_participant__uses_one_semantic_revision() -> None:
    route = cast(
        InputToolRouteV1,
        {
            "route_id": "route-1",
            "resource_type": "GMAIL_THREAD",
            "connector_id": "google_workspace",
            "allowed_read_tool_ids": ["gmail_search_threads"],
            "required": True,
            "reason_codes": ["USER_REQUEST"],
        },
    )
    prior_keyword = {
        "kind": "KEYWORD",
        "terms": ["Nimbus"],
        "match_mode": "PHRASE",
    }
    policies = {"route-1": RouteConstraintPolicy(frozenset({"KEYWORD", "CONCEPT", "PARTICIPANT"}))}
    prior = build_query(
        {
            "schema_version": 2,
            "route_queries": [
                {
                    "route_id": "route-1",
                    "operation": "SEARCH",
                    "reason_codes": ["USER_REQUEST"],
                    "search_spec": {"mode": "INITIAL", "constraints": [prior_keyword]},
                    "detail_candidate_ref": None,
                }
            ],
        },
        frozen_routes=[route],
        route_policies=policies,
    )[0]
    invalid = {
        "schema_version": 2,
        "route_queries": [
            {
                "route_id": "route-1",
                "operation": "SEARCH",
                "reason_codes": ["MISSING_DATE"],
                "search_spec": {
                    "mode": "CHANGED",
                    "constraint_delta": {
                        "upsert_constraints": [
                            {
                                "kind": "PARTICIPANT",
                                "participants": [
                                    {"role": "ANY", "identity": "invented@example.com"}
                                ],
                                "match_mode": "ALL",
                            }
                        ],
                        "remove_constraint_kinds": [],
                    },
                },
                "detail_candidate_ref": None,
            }
        ],
    }
    revised = {
        "schema_version": 2,
        "route_queries": [
            {
                "route_id": "route-1",
                "operation": "SEARCH",
                "reason_codes": ["MISSING_DATE"],
                "search_spec": {
                    "mode": "CHANGED",
                    "constraint_delta": {
                        "upsert_constraints": [
                            {"kind": "CONCEPT", "concept": "출시", "manifestations": ["공개"]}
                        ],
                        "remove_constraint_kinds": [],
                    },
                },
                "detail_candidate_ref": None,
            }
        ],
    }
    runtime = FakeStructuredInferencePort(outputs=[invalid, revised])
    prompt_ref = PromptReference(
        prompt_bundle_version="test",
        prompt_id="retrieval.plan_query",
        prompt_version="1",
        content_hash="hash",
        agent_role="retrieval",
        subgraph_name="retrieval",
        node_name="plan_query",
        node_state="INITIAL",
        purpose="plan_query",
        input_schema_version="v2",
        output_schema_version="v2",
    )

    result, budget, invoked = plan_query(
        llm_runtime=runtime,
        prompt_ref=prompt_ref,
        revision_prompt_ref=prompt_ref,
        output_schema=RETRIEVAL_QUERY_PLAN_V2_OUTPUT_SCHEMA,
        prompt_input={
            "request_intent": {"constraints": []},
            "input_routes": [route],
            "current_round_no": 1,
            "prior_query_attempts": [],
            "unresolved_sufficiency_issues": [],
            "read_result_summaries": [],
        },
        requested_mode="LOCAL_GPU",
        frozen_routes=[route],
        route_policies=policies,
        retry_budget=build_default_run_budget(),
        prior_plans={"route-1": prior},
    )

    assert invoked is True
    assert result == revised
    assert len(runtime.calls) == 2
    assert sum(budget["semantic_revisions_used_by_failure"].values()) == 1


@pytest.mark.parametrize("terms", [["회의 관련 메일"], ["프로젝트", "일정"]])
def test_query_expansion__lexical_anchor_only__does_not_relax_with_dictionary(
    terms: list[str],
) -> None:
    from google_work_agent.application.agents.retrieval.plan_query_expansion import (
        plan_query_expansion,
    )

    assert (
        plan_query_expansion(
            prompt_input={
                "current_round_no": 0,
                "request_intent": {"constraints": []},
                "prior_query_attempts": [
                    {
                        "route_id": "route-1",
                        "operation_kind": "SEARCH",
                        "stop_reason": "COMPLETE",
                        "normalized_intent_constraints": [
                            {"kind": "KEYWORD", "terms": terms, "match_mode": "ALL"},
                        ],
                    }
                ],
                "unresolved_sufficiency_issues": [
                    {"required": True, "resolution_source": "GOOGLE"}
                ],
                "read_result_summaries": [
                    {"route_id": "route-1", "result_count": 0, "exhausted": True},
                ],
            },
            frozen_routes=_tool_route_plan(
                allowed_read_tool_ids=["gmail_search_threads", "gmail_get_thread"],
            )["input_plan"]["input_routes"],
        )
        is None
    )


def test_general_search__with_semantic_choice__keeps_query_planning_llm() -> None:
    output = {
        "schema_version": 2,
        "route_queries": [
            {
                "route_id": "route-1",
                "operation": "SEARCH",
                "reason_codes": ["USER_REQUEST"],
                "search_spec": {
                    "mode": "INITIAL",
                    "constraints": [{"kind": "KEYWORD", "terms": ["budget"], "match_mode": "ANY"}],
                },
                "detail_candidate_ref": None,
            }
        ],
    }
    runtime = FakeStructuredInferencePort(outputs=[output])
    prompt_ref = PromptReference(
        prompt_bundle_version="test",
        prompt_id="retrieval.plan_query",
        prompt_version="1",
        content_hash="hash",
        agent_role="retrieval",
        subgraph_name="retrieval",
        node_name="plan_query",
        node_state="INITIAL",
        purpose="plan_query",
        input_schema_version="v2",
        output_schema_version="v2",
    )
    frozen_routes = [
        {
            "route_id": "route-1",
            "resource_type": "GMAIL_THREAD",
            "connector_id": "google_workspace",
            "allowed_read_tool_ids": ["gmail_search_threads", "gmail_get_thread"],
            "required": True,
            "reason_codes": ["USER_REQUEST"],
        }
    ]

    result, _, llm_invoked = plan_query(
        llm_runtime=runtime,
        prompt_ref=prompt_ref,
        revision_prompt_ref=prompt_ref,
        output_schema=RETRIEVAL_QUERY_PLAN_V2_OUTPUT_SCHEMA,
        prompt_input={"request_intent": {}, "input_routes": frozen_routes},
        requested_mode="LOCAL_GPU",
        frozen_routes=cast(list[InputToolRouteV1], frozen_routes),
        route_policies={"route-1": RouteConstraintPolicy(frozenset({"KEYWORD"}))},
        retry_budget=build_default_run_budget(),
    )

    assert llm_invoked is True
    assert len(runtime.calls) == 1
    assert result == output
    projected_input = cast(dict[str, object], runtime.calls[0]["prompt_input"])
    projected_routes = cast(list[dict[str, object]], projected_input["input_routes"])
    assert projected_routes[0]["supported_constraint_kinds"] == ["KEYWORD"]
    assert projected_routes[0]["required_constraint_kinds"] == []
    assert projected_routes[0]["allowed_operations"] == ["SEARCH"]


def test_query_planner__with_get_only_route__searches_supported_route() -> None:
    output = {
        "schema_version": 2,
        "route_queries": [
            {
                "route_id": "thread-search",
                "operation": "SEARCH",
                "reason_codes": ["USER_REQUEST"],
                "search_spec": {
                    "mode": "INITIAL",
                    "constraints": [{"kind": "KEYWORD", "terms": ["Quartz"], "match_mode": "ANY"}],
                },
                "detail_candidate_ref": None,
            }
        ],
    }
    runtime = FakeStructuredInferencePort(outputs=[output])
    prompt_ref = PromptReference(
        "test",
        "retrieval.plan_query",
        "1",
        "hash",
        "retrieval",
        "retrieval",
        "plan_query",
        "INITIAL",
        "plan_query",
        "v2",
        "v2",
    )
    frozen_routes = cast(
        list[InputToolRouteV1],
        [
            {
                "route_id": "message-detail",
                "resource_type": "GMAIL_MESSAGE",
                "connector_id": "google_workspace",
                "allowed_read_tool_ids": ["gmail_get_message"],
                "required": True,
                "reason_codes": ["USER_REQUEST"],
            },
            {
                "route_id": "thread-search",
                "resource_type": "GMAIL_THREAD",
                "connector_id": "google_workspace",
                "allowed_read_tool_ids": ["gmail_search_threads", "gmail_get_thread"],
                "required": True,
                "reason_codes": ["USER_REQUEST"],
            },
        ],
    )

    result, _, _ = plan_query(
        llm_runtime=runtime,
        prompt_ref=prompt_ref,
        revision_prompt_ref=prompt_ref,
        output_schema=RETRIEVAL_QUERY_PLAN_V2_OUTPUT_SCHEMA,
        prompt_input={"request_intent": {}, "input_routes": frozen_routes},
        requested_mode="LOCAL_GPU",
        frozen_routes=frozen_routes,
        route_policies={
            route["route_id"]: RouteConstraintPolicy(frozenset({"KEYWORD"}))
            for route in frozen_routes
        },
        retry_budget=build_default_run_budget(),
    )

    assert result == output
    call = runtime.calls[0]
    projected_routes = {
        route["route_id"]: route
        for route in cast(list[dict[str, object]], call["prompt_input"]["input_routes"])
    }
    assert projected_routes["message-detail"]["allowed_operations"] == []
    assert projected_routes["thread-search"]["allowed_operations"] == ["SEARCH"]
    schema = cast(OutputSchemaDefinition, call["output_schema"])
    invalid = {
        **output,
        "route_queries": [{**output["route_queries"][0], "route_id": "message-detail"}],
    }
    assert validate_output_schema(invalid, schema.json_schema)


def test_query_planner__with_only_unbound_get_route__fails_before_llm_schema() -> None:
    runtime = FakeStructuredInferencePort(outputs=[])
    prompt_ref = PromptReference(
        "test",
        "retrieval.plan_query",
        "1",
        "hash",
        "retrieval",
        "retrieval",
        "plan_query",
        "INITIAL",
        "plan_query",
        "v2",
        "v2",
    )
    frozen_routes = cast(
        list[InputToolRouteV1],
        [
            {
                "route_id": "message-detail",
                "resource_type": "GMAIL_MESSAGE",
                "connector_id": "google_workspace",
                "allowed_read_tool_ids": ["gmail_get_message"],
                "required": True,
                "reason_codes": ["USER_REQUEST"],
            }
        ],
    )

    with pytest.raises(RetrievalV2ValidationError, match="no executable retrieval operation"):
        plan_query(
            llm_runtime=runtime,
            prompt_ref=prompt_ref,
            revision_prompt_ref=prompt_ref,
            output_schema=RETRIEVAL_QUERY_PLAN_V2_OUTPUT_SCHEMA,
            prompt_input={"request_intent": {}, "input_routes": frozen_routes},
            requested_mode="LOCAL_GPU",
            frozen_routes=frozen_routes,
            route_policies={"message-detail": RouteConstraintPolicy(frozenset({"KEYWORD"}))},
            retry_budget=build_default_run_budget(),
        )

    assert runtime.calls == []


def test_initial_query__invalid_next_page__repairs_before_materialization() -> None:
    invalid_initial = {
        "schema_version": 2,
        "route_queries": [
            {
                "route_id": "route-1",
                "operation": "NEXT_PAGE",
                "reason_codes": ["USER_REQUEST"],
                "search_spec": None,
                "detail_candidate_ref": None,
            }
        ],
    }
    repaired = {
        "schema_version": 2,
        "route_queries": [
            {
                "route_id": "route-1",
                "operation": "SEARCH",
                "reason_codes": ["USER_REQUEST"],
                "search_spec": {
                    "mode": "INITIAL",
                    "constraints": [{"kind": "STATUS_SCOPE", "values": ["INCOMPLETE"]}],
                },
                "detail_candidate_ref": None,
            }
        ],
    }
    runtime = FakeStructuredInferencePort(outputs=[invalid_initial, repaired])
    prompt_ref = PromptReference(
        prompt_bundle_version="test",
        prompt_id="retrieval.plan_query",
        prompt_version="1",
        content_hash="hash",
        agent_role="retrieval",
        subgraph_name="retrieval",
        node_name="plan_query",
        node_state="INITIAL",
        purpose="plan_query",
        input_schema_version="v2",
        output_schema_version="v2",
    )
    frozen_routes = [
        {
            "route_id": "route-1",
            "resource_type": "TASK",
            "connector_id": "google_workspace",
            "allowed_read_tool_ids": ["tasks_list_tasks"],
            "required": True,
            "reason_codes": ["USER_REQUEST"],
        }
    ]

    result, budget, llm_invoked = plan_query(
        llm_runtime=runtime,
        prompt_ref=prompt_ref,
        revision_prompt_ref=prompt_ref,
        output_schema=RETRIEVAL_QUERY_PLAN_V2_OUTPUT_SCHEMA,
        prompt_input={"request_intent": {}, "input_routes": frozen_routes},
        requested_mode="LOCAL_GPU",
        frozen_routes=cast(list[InputToolRouteV1], frozen_routes),
        route_policies={"route-1": RouteConstraintPolicy(frozenset({"STATUS_SCOPE"}))},
        retry_budget=build_default_run_budget(),
    )

    assert llm_invoked is True
    assert result == repaired
    assert len(runtime.calls) == 2
    assert sum(budget["semantic_revisions_used_by_failure"].values()) == 1
    repair_input = cast(dict[str, object], runtime.calls[1]["prompt_input"])
    failure_record = cast(dict[str, object], repair_input["failure_record"])
    assert failure_record["failure_reason_code"] == "QUERY_OPERATION_FIELD_MISMATCH"
    assert failure_record["affected_field_paths"] == ["$.route_queries[].operation"]


def test_revised_query_validation_error__after_schema_revision__retains_diagnostics() -> None:
    invalid = {
        "schema_version": 2,
        "route_queries": [
            {
                "route_id": "route-1",
                "operation": "SEARCH",
                "reason_codes": ["USER_REQUEST"],
                "search_spec": {
                    "mode": "INITIAL",
                    "constraints": [
                        {"kind": "KEYWORD", "terms": ["first"], "match_mode": "ANY"},
                        {"kind": "KEYWORD", "terms": ["second"], "match_mode": "ANY"},
                    ],
                },
                "detail_candidate_ref": None,
            }
        ],
    }
    runtime = FakeStructuredInferencePort(outputs=[invalid, invalid])
    prompt_ref = PromptReference(
        prompt_bundle_version="test",
        prompt_id="retrieval.plan_query",
        prompt_version="1",
        content_hash="hash",
        agent_role="retrieval",
        subgraph_name="retrieval",
        node_name="plan_query",
        node_state="INITIAL",
        purpose="plan_query",
        input_schema_version="v2",
        output_schema_version="v2",
    )
    frozen_routes = cast(
        list[InputToolRouteV1],
        [
            {
                "route_id": "route-1",
                "resource_type": "GMAIL_THREAD",
                "connector_id": "google_workspace",
                "allowed_read_tool_ids": ["gmail_search_threads"],
                "required": True,
                "reason_codes": ["USER_REQUEST"],
            }
        ],
    )

    with pytest.raises(RetrievalV2ValidationError) as caught:
        plan_query(
            llm_runtime=runtime,
            prompt_ref=prompt_ref,
            revision_prompt_ref=prompt_ref,
            output_schema=RETRIEVAL_QUERY_PLAN_V2_OUTPUT_SCHEMA,
            prompt_input={"request_intent": {}, "input_routes": frozen_routes},
            requested_mode="LOCAL_GPU",
            frozen_routes=frozen_routes,
            route_policies={"route-1": RouteConstraintPolicy(frozenset({"KEYWORD"}))},
            retry_budget=build_default_run_budget(),
        )

    assert len(runtime.calls) == 2
    assert caught.value.validation_stage == "QUERY_PLAN_VALIDATOR"
    assert caught.value.affected_field_paths == ("$.route_queries[].search_spec.constraints",)


def test_calendar_route__projects_existing__route_constraint_policy() -> None:
    output = {
        "schema_version": 2,
        "route_queries": [
            {
                "route_id": "calendar-read",
                "operation": "SEARCH",
                "reason_codes": ["POLICY_PRECONDITION"],
                "search_spec": {
                    "mode": "INITIAL",
                    "constraints": [
                        {
                            "kind": "TEMPORAL_RANGE",
                            "axis": "EVENT_TIME",
                            "start_local": "2026-09-05T15:00:00",
                            "end_local": "2026-09-05T15:30:00",
                            "timezone": "Asia/Seoul",
                        }
                    ],
                },
                "detail_candidate_ref": None,
            }
        ],
    }
    runtime = FakeStructuredInferencePort(outputs=[output])
    prompt_ref = PromptReference(
        prompt_bundle_version="test",
        prompt_id="retrieval.plan_query",
        prompt_version="1",
        content_hash="hash",
        agent_role="retrieval",
        subgraph_name="retrieval",
        node_name="plan_query",
        node_state="INITIAL",
        purpose="plan_query",
        input_schema_version="v2",
        output_schema_version="v2",
    )
    frozen_routes = [
        {
            "route_id": "calendar-read",
            "resource_type": "CALENDAR_EVENT",
            "connector_id": "google_workspace",
            "allowed_read_tool_ids": ["calendar_list_events"],
            "required": True,
            "reason_codes": ["POLICY_PRECONDITION"],
        }
    ]

    result, _, llm_invoked = plan_query(
        llm_runtime=runtime,
        prompt_ref=prompt_ref,
        revision_prompt_ref=prompt_ref,
        output_schema=RETRIEVAL_QUERY_PLAN_V2_OUTPUT_SCHEMA,
        prompt_input={"request_intent": {}, "input_routes": frozen_routes, "retrieval_budget": {}},
        requested_mode="LOCAL_GPU",
        frozen_routes=cast(list[InputToolRouteV1], frozen_routes),
        route_policies={
            "calendar-read": RouteConstraintPolicy(frozenset({"TEMPORAL_RANGE", "CONTAINER_REF"}))
        },
        retry_budget=build_default_run_budget(),
        validated_container_refs={"calendar-read": ["primary"]},
    )

    assert llm_invoked is True
    assert result == output
    projected_input = cast(dict[str, object], runtime.calls[0]["prompt_input"])
    projected_routes = cast(list[dict[str, object]], projected_input["input_routes"])
    assert projected_routes[0]["supported_constraint_kinds"] == [
        "CONTAINER_REF",
        "TEMPORAL_RANGE",
    ]
    assert projected_routes[0]["required_constraint_kinds"] == []


def test_plan_query__freebusy_without_temporal_range__uses_semantic_revision() -> None:
    missing_temporal = {
        "schema_version": 2,
        "route_queries": [
            {
                "route_id": "calendar-availability",
                "operation": "FREEBUSY",
                "reason_codes": ["USER_REQUEST"],
                "search_spec": {
                    "mode": "INITIAL",
                    "constraints": [
                        {
                            "kind": "CONTAINER_REF",
                            "container_refs": ["calendar-1"],
                        }
                    ],
                },
                "detail_candidate_ref": None,
            }
        ],
    }
    repaired = {
        "schema_version": 2,
        "route_queries": [
            {
                "route_id": "calendar-availability",
                "operation": "FREEBUSY",
                "reason_codes": ["USER_REQUEST"],
                "search_spec": {
                    "mode": "INITIAL",
                    "constraints": [
                        {
                            "kind": "CONTAINER_REF",
                            "container_refs": ["calendar-1"],
                        },
                        {
                            "kind": "TEMPORAL_RANGE",
                            "axis": "AVAILABILITY_WINDOW",
                            "start_local": "2026-09-15T09:00:00",
                            "end_local": "2026-09-15T18:00:00",
                            "timezone": "Asia/Seoul",
                        }
                    ],
                },
                "detail_candidate_ref": None,
            }
        ],
    }
    runtime = FakeStructuredInferencePort(outputs=[missing_temporal, repaired])
    route = cast(
        InputToolRouteV1,
        {
            "route_id": "calendar-availability",
            "resource_type": "CALENDAR_FREEBUSY",
            "connector_id": "google_workspace",
            "allowed_read_tool_ids": ["calendar_query_freebusy"],
            "required": True,
            "reason_codes": ["USER_REQUEST"],
        },
    )

    result, budget, llm_invoked = plan_query(
        llm_runtime=runtime,
        prompt_ref=_retrieval_prompt_ref(),
        revision_prompt_ref=_retrieval_prompt_ref(),
        output_schema=RETRIEVAL_QUERY_PLAN_V2_OUTPUT_SCHEMA,
        prompt_input={"request_intent": {"constraints": []}, "input_routes": [route]},
        requested_mode="LOCAL_GPU",
        frozen_routes=[route],
        route_policies={
            "calendar-availability": RouteConstraintPolicy(
                frozenset({"CONTAINER_REF", "TEMPORAL_RANGE"}),
                frozenset({"CONTAINER_REF"}),
            )
        },
        retry_budget=build_default_run_budget(),
        validated_container_refs={"calendar-availability": ["calendar-1"]},
    )

    assert llm_invoked is True
    assert len(runtime.calls) == 2
    assert sum(budget["semantic_revisions_used_by_failure"].values()) == 1
    search_spec = result["route_queries"][0]["search_spec"]
    assert search_spec is not None
    assert search_spec["mode"] == "INITIAL"
    assert {constraint["kind"] for constraint in search_spec["constraints"]} == {
        "CONTAINER_REF",
        "TEMPORAL_RANGE",
    }


def test_exact_calendar_create_precondition__materializes_all_policy_reads__without_llm() -> None:
    runtime = FakeStructuredInferencePort(outputs=[])
    prompt_ref = PromptReference(
        prompt_bundle_version="test",
        prompt_id="retrieval.plan_query",
        prompt_version="1",
        content_hash="hash",
        agent_role="retrieval",
        subgraph_name="retrieval",
        node_name="plan_query",
        node_state="INITIAL",
        purpose="plan_query",
        input_schema_version="v2",
        output_schema_version="v2",
    )
    frozen_routes = [
        {
            "route_id": "calendar-list",
            "resource_type": "CALENDAR",
            "connector_id": "google_workspace",
            "allowed_read_tool_ids": ["calendar_list_calendars"],
            "required": True,
            "reason_codes": ["POLICY_CALENDAR_CONFLICT_CHECK"],
        },
        {
            "route_id": "event-list",
            "resource_type": "CALENDAR_EVENT",
            "connector_id": "google_workspace",
            "allowed_read_tool_ids": ["calendar_list_events"],
            "required": True,
            "reason_codes": ["POLICY_CALENDAR_CONFLICT_CHECK"],
        },
        {
            "route_id": "freebusy",
            "resource_type": "CALENDAR_FREEBUSY",
            "connector_id": "google_workspace",
            "allowed_read_tool_ids": ["calendar_query_freebusy"],
            "required": True,
            "reason_codes": ["POLICY_CALENDAR_CONFLICT_CHECK"],
        },
    ]
    typed_routes = cast(list[InputToolRouteV1], frozen_routes)
    policies: dict[str, RouteConstraintPolicy] = {
        route["route_id"]: RouteConstraintPolicy(
            frozenset({"TEMPORAL_RANGE", "CONTAINER_REF"}),
            frozenset({"CONTAINER_REF"}) if route["resource_type"] != "CALENDAR" else frozenset(),
        )
        for route in typed_routes
    }
    container_refs: dict[str, list[str]] = {
        route["route_id"]: ["primary"] for route in typed_routes
    }

    result, _, llm_invoked = plan_query(
        llm_runtime=runtime,
        prompt_ref=prompt_ref,
        revision_prompt_ref=prompt_ref,
        output_schema=RETRIEVAL_QUERY_PLAN_V2_OUTPUT_SCHEMA,
        prompt_input={
            "request_intent": {
                "requested_effect_hints": ["READ", "CREATE"],
                "requested_resource_hints": ["CALENDAR", "CALENDAR_EVENT"],
                "constraints": [
                    {"kind": "DATE", "field": "date", "value": "2026-09-05"},
                    {
                        "kind": "TIME",
                        "field": "start_time",
                        "value": "15:00",
                    },
                    {
                        "kind": "TIME",
                        "field": "end_time",
                        "value": "15:30",
                    },
                ],
            },
            "input_routes": frozen_routes,
        },
        requested_mode="LOCAL_GPU",
        frozen_routes=typed_routes,
        route_policies=policies,
        retry_budget=build_default_run_budget(),
        validated_container_refs=container_refs,
        timezone="Asia/Seoul",
    )

    assert llm_invoked is False
    assert runtime.calls == []
    assert [item["route_id"] for item in result["route_queries"]] == [
        "calendar-list",
        "event-list",
        "freebusy",
    ]
    assert [item["operation"] for item in result["route_queries"]] == [
        "SEARCH",
        "SEARCH",
        "FREEBUSY",
    ]
    for route_query in result["route_queries"]:
        search_spec = route_query["search_spec"]
        assert search_spec is not None
        assert search_spec["mode"] == "INITIAL"
        constraints = search_spec["constraints"]
        assert constraints[0] == {
            "kind": "CONTAINER_REF",
            "container_refs": ["primary"],
        }
        temporal = constraints[1]
        assert temporal["kind"] == "TEMPORAL_RANGE"
        assert temporal["start_local"] == "2026-09-05T15:00:00"
        assert temporal["end_local"] == "2026-09-05T15:30:00"
        assert temporal["timezone"] == "Asia/Seoul"


def test_task_calendar_draft_sources__use_calendar_specific_anchor__without_llm() -> None:
    runtime = FakeStructuredInferencePort(outputs=[])
    routes = cast(
        list[InputToolRouteV1],
        [
            {
                "route_id": "events",
                "resource_type": "CALENDAR_EVENT",
                "connector_id": "google_workspace",
                "allowed_read_tool_ids": ["calendar_list_events"],
                "required": True,
                "reason_codes": ["REQUESTED_INPUT"],
            },
            {
                "route_id": "tasks",
                "resource_type": "TASK",
                "connector_id": "google_workspace",
                "allowed_read_tool_ids": ["tasks_list_tasks"],
                "required": True,
                "reason_codes": ["REQUESTED_INPUT"],
            },
            {
                "route_id": "calendars",
                "resource_type": "CALENDAR",
                "connector_id": "google_workspace",
                "allowed_read_tool_ids": ["calendar_list_calendars"],
                "required": True,
                "reason_codes": ["RETRIEVAL_CALENDAR_DISCOVERY"],
            },
            {
                "route_id": "task-lists",
                "resource_type": "TASK_LIST",
                "connector_id": "google_workspace",
                "allowed_read_tool_ids": ["tasks_list_tasklists"],
                "required": True,
                "reason_codes": ["RETRIEVAL_TASK_LIST_DISCOVERY"],
            },
        ],
    )
    policies = {
        route["route_id"]: RouteConstraintPolicy(
            frozenset(
                {"CONTAINER_REF", "KEYWORD"}
                if route["resource_type"] == "CALENDAR_EVENT"
                else {"CONTAINER_REF"}
            ),
            frozenset({"CONTAINER_REF"})
            if route["resource_type"] in {"TASK", "CALENDAR_EVENT"}
            else frozenset(),
        )
        for route in routes
    }
    containers = {
        "events": ["calendar:primary"],
        "tasks": ["task-list:primary"],
        "calendars": ["calendar:primary"],
        "task-lists": ["task-list:primary"],
    }

    result, _, llm_invoked = plan_query(
        llm_runtime=runtime,
        prompt_ref=_retrieval_prompt_ref(),
        revision_prompt_ref=_retrieval_prompt_ref(),
        output_schema=RETRIEVAL_QUERY_PLAN_V2_OUTPUT_SCHEMA,
        prompt_input={
            "request_intent": {
                "requested_effect_hints": ["READ", "CREATE"],
                "requested_resource_hints": ["TASK", "CALENDAR_EVENT", "GMAIL_DRAFT"],
                "constraints": [
                    {
                        "kind": "USER_REQUIREMENT",
                        "field": "search_terms",
                        "value": "Orion",
                        "provenance": {"source": "USER_REQUEST", "start_offset": 0},
                    },
                    {
                        "kind": "USER_REQUIREMENT",
                        "field": "search_terms",
                        "value": "제작사 일정 일정",
                        "provenance": {"source": "USER_REQUEST", "start_offset": 11},
                    },
                ],
                "resource_responsibilities": {
                    "source_reads": [
                        {"resource_type": "TASK", "required_information": ["title"]},
                        {
                            "resource_type": "CALENDAR_EVENT",
                            "required_information": ["title", "start"],
                        },
                    ],
                    "outputs": [{"resource_type": "GMAIL_DRAFT", "effect": "CREATE"}],
                },
            },
            "input_routes": routes,
        },
        requested_mode="LOCAL_GPU",
        frozen_routes=routes,
        route_policies=policies,
        retry_budget=build_default_run_budget(),
        validated_container_refs=containers,
    )

    assert llm_invoked is False
    assert runtime.calls == []
    assert [query["route_id"] for query in result["route_queries"]] == [
        "events",
        "tasks",
        "calendars",
        "task-lists",
    ]
    event_spec = result["route_queries"][0]["search_spec"]
    assert event_spec is not None
    event_spec_mapping = cast(Mapping[str, object], event_spec)
    assert event_spec_mapping["constraints"] == [
        {"kind": "KEYWORD", "terms": ["제작사"], "match_mode": "PHRASE"},
        {"kind": "CONTAINER_REF", "container_refs": ["calendar:primary"]},
    ]
    for query in result["route_queries"][1:]:
        assert query["search_spec"] == {
            "mode": "INITIAL",
            "constraints": [
                {
                    "kind": "CONTAINER_REF",
                    "container_refs": containers[query["route_id"]],
                }
            ],
        }


@pytest.mark.parametrize(
    ("requested_effects", "requested_resources"),
    [
        (["CREATE"], ["TASK"]),
        (["READ", "CREATE"], ["TASK_LIST", "TASK"]),
    ],
)
def test_exact_task_create_precondition__materializes_duplicate_reads__without_llm(
    requested_effects: list[str], requested_resources: list[str]
) -> None:
    runtime = FakeStructuredInferencePort(outputs=[])
    prompt_ref = PromptReference(
        prompt_bundle_version="test",
        prompt_id="retrieval.plan_query",
        prompt_version="1",
        content_hash="hash",
        agent_role="retrieval",
        subgraph_name="retrieval",
        node_name="plan_query",
        node_state="INITIAL",
        purpose="plan_query",
        input_schema_version="v2",
        output_schema_version="v2",
    )
    frozen_routes = [
        {
            "route_id": "tasks",
            "resource_type": "TASK",
            "connector_id": "google_workspace",
            "allowed_read_tool_ids": ["tasks_list_tasks"],
            "required": True,
            "reason_codes": ["POLICY_TASK_DUPLICATE_CHECK"],
        },
        {
            "route_id": "task-lists",
            "resource_type": "TASK_LIST",
            "connector_id": "google_workspace",
            "allowed_read_tool_ids": ["tasks_list_tasklists"],
            "required": True,
            "reason_codes": ["POLICY_TASK_DUPLICATE_CHECK"],
        },
    ]
    typed_routes = cast(list[InputToolRouteV1], frozen_routes)
    policies: dict[str, RouteConstraintPolicy] = {
        route["route_id"]: RouteConstraintPolicy(
            frozenset({"CONTAINER_REF"}),
            frozenset({"CONTAINER_REF"}) if route["resource_type"] == "TASK" else frozenset(),
        )
        for route in typed_routes
    }
    container_refs: dict[str, list[str]] = {
        route["route_id"]: ["@default"] for route in typed_routes
    }

    result, _, llm_invoked = plan_query(
        llm_runtime=runtime,
        prompt_ref=prompt_ref,
        revision_prompt_ref=prompt_ref,
        output_schema=RETRIEVAL_QUERY_PLAN_V2_OUTPUT_SCHEMA,
        prompt_input={
            "request_intent": {
                "requested_effect_hints": requested_effects,
                "requested_resource_hints": requested_resources,
                "constraints": [
                    {
                        "kind": "RESOURCE",
                        "field": "title",
                        "value": "Submit report",
                    },
                    {"kind": "RESOURCE", "field": "notes", "value": "Attach evidence"},
                    {"kind": "DATE", "field": "scheduled_date", "value": "2026-09-11"},
                ],
            },
            "input_routes": frozen_routes,
        },
        requested_mode="LOCAL_GPU",
        frozen_routes=typed_routes,
        route_policies=policies,
        retry_budget=build_default_run_budget(),
        validated_container_refs=container_refs,
    )

    assert llm_invoked is False
    assert runtime.calls == []
    assert [item["route_id"] for item in result["route_queries"]] == ["tasks", "task-lists"]
    assert [item["operation"] for item in result["route_queries"]] == [
        "SEARCH",
        "SEARCH",
    ]
    for route_query in result["route_queries"]:
        assert route_query["search_spec"] == {
            "mode": "INITIAL",
            "constraints": [{"kind": "CONTAINER_REF", "container_refs": ["@default"]}],
        }


def test_exact_task_create_precondition__extra_source_route__uses_semantic_planner() -> None:
    runtime = FakeStructuredInferencePort(outputs=[RuntimeError("semantic query path reached")])
    prompt_ref = PromptReference(
        prompt_bundle_version="test",
        prompt_id="retrieval.plan_query",
        prompt_version="1",
        content_hash="hash",
        agent_role="retrieval",
        subgraph_name="retrieval",
        node_name="plan_query",
        node_state="INITIAL",
        purpose="plan_query",
        input_schema_version="v2",
        output_schema_version="v2",
    )
    frozen_routes = cast(
        list[InputToolRouteV1],
        [
            {
                "route_id": "tasks",
                "resource_type": "TASK",
                "connector_id": "google_workspace",
                "allowed_read_tool_ids": ["tasks_list_tasks"],
                "required": True,
                "reason_codes": ["POLICY_TASK_DUPLICATE_CHECK"],
            },
            {
                "route_id": "task-lists",
                "resource_type": "TASK_LIST",
                "connector_id": "google_workspace",
                "allowed_read_tool_ids": ["tasks_list_tasklists"],
                "required": True,
                "reason_codes": ["POLICY_TASK_DUPLICATE_CHECK"],
            },
            {
                "route_id": "source-mail",
                "resource_type": "GMAIL_THREAD",
                "connector_id": "google_workspace",
                "allowed_read_tool_ids": ["gmail_search_threads", "gmail_get_thread"],
                "required": True,
                "reason_codes": ["USER_REQUEST"],
            },
        ],
    )

    with pytest.raises(RuntimeError, match="semantic query path reached"):
        plan_query(
            llm_runtime=runtime,
            prompt_ref=prompt_ref,
            revision_prompt_ref=prompt_ref,
            output_schema=RETRIEVAL_QUERY_PLAN_V2_OUTPUT_SCHEMA,
            prompt_input={
                "request_intent": {
                    "requested_effect_hints": ["READ", "CREATE"],
                    "requested_resource_hints": ["GMAIL_THREAD", "TASK_LIST", "TASK"],
                    "constraints": [
                        {"kind": "RESOURCE", "field": "title", "value": "Submit report"}
                    ],
                },
                "input_routes": frozen_routes,
            },
            requested_mode="LOCAL_GPU",
            frozen_routes=frozen_routes,
            route_policies={
                "tasks": RouteConstraintPolicy(frozenset({"CONTAINER_REF"})),
                "task-lists": RouteConstraintPolicy(frozenset({"CONTAINER_REF"})),
                "source-mail": RouteConstraintPolicy(frozenset({"KEYWORD"})),
            },
            retry_budget=build_default_run_budget(),
            validated_container_refs={"tasks": ["@default"], "task-lists": ["@default"]},
        )

    assert len(runtime.calls) == 1


@pytest.mark.parametrize(
    ("constraints", "container_refs"),
    [
        ([], {"tasks": ["@default"], "task-lists": ["@default"]}),
        (
            [
                {"kind": "RESOURCE", "field": "title", "value": "Submit report"},
                {"kind": "RESOURCE", "field": "title", "value": "Second title"},
            ],
            {"tasks": ["@default"], "task-lists": ["@default"]},
        ),
        (
            [{"kind": "RESOURCE", "field": "title", "value": "Submit report"}],
            {"task-lists": ["@default"]},
        ),
    ],
)
def test_exact_task_create_precondition__invalid_title_or_missing_container__uses_semantic_planner(
    constraints: list[dict[str, object]],
    container_refs: dict[str, list[str]],
) -> None:
    runtime = FakeStructuredInferencePort(outputs=[RuntimeError("semantic query path reached")])
    prompt_ref = PromptReference(
        prompt_bundle_version="test",
        prompt_id="retrieval.plan_query",
        prompt_version="1",
        content_hash="hash",
        agent_role="retrieval",
        subgraph_name="retrieval",
        node_name="plan_query",
        node_state="INITIAL",
        purpose="plan_query",
        input_schema_version="v2",
        output_schema_version="v2",
    )
    frozen_routes = cast(
        list[InputToolRouteV1],
        [
            {
                "route_id": "tasks",
                "resource_type": "TASK",
                "connector_id": "google_workspace",
                "allowed_read_tool_ids": ["tasks_list_tasks"],
                "required": True,
                "reason_codes": ["POLICY_TASK_DUPLICATE_CHECK"],
            },
            {
                "route_id": "task-lists",
                "resource_type": "TASK_LIST",
                "connector_id": "google_workspace",
                "allowed_read_tool_ids": ["tasks_list_tasklists"],
                "required": True,
                "reason_codes": ["POLICY_TASK_DUPLICATE_CHECK"],
            },
        ],
    )

    with pytest.raises(RuntimeError, match="semantic query path reached"):
        plan_query(
            llm_runtime=runtime,
            prompt_ref=prompt_ref,
            revision_prompt_ref=prompt_ref,
            output_schema=RETRIEVAL_QUERY_PLAN_V2_OUTPUT_SCHEMA,
            prompt_input={
                "request_intent": {
                    "requested_effect_hints": ["CREATE"],
                    "requested_resource_hints": ["TASK"],
                    "constraints": constraints,
                },
                "input_routes": frozen_routes,
            },
            requested_mode="LOCAL_GPU",
            frozen_routes=frozen_routes,
            route_policies={
                "tasks": RouteConstraintPolicy(frozenset({"CONTAINER_REF"})),
                "task-lists": RouteConstraintPolicy(frozenset({"CONTAINER_REF"})),
            },
            retry_budget=build_default_run_budget(),
            validated_container_refs=container_refs,
        )

    assert len(runtime.calls) == 1


def test_calendar_route__without_validated_container__does_not_offer_container_ref() -> None:
    runtime = FakeStructuredInferencePort(
        outputs=[
            {
                "schema_version": 2,
                "route_queries": [
                    {
                        "route_id": "calendar-read",
                        "operation": "SEARCH",
                        "reason_codes": ["POLICY_PRECONDITION"],
                        "search_spec": {
                            "mode": "INITIAL",
                            "constraints": [
                                {
                                    "kind": "TEMPORAL_RANGE",
                                    "axis": "EVENT_TIME",
                                    "start_local": "2026-09-05T15:00:00",
                                    "end_local": "2026-09-05T15:30:00",
                                    "timezone": "Asia/Seoul",
                                }
                            ],
                        },
                        "detail_candidate_ref": None,
                    }
                ],
            }
        ]
    )
    prompt_ref = PromptReference(
        prompt_bundle_version="test",
        prompt_id="retrieval.plan_query",
        prompt_version="1",
        content_hash="hash",
        agent_role="retrieval",
        subgraph_name="retrieval",
        node_name="plan_query",
        node_state="INITIAL",
        purpose="plan_query",
        input_schema_version="v2",
        output_schema_version="v2",
    )
    frozen_routes = [
        {
            "route_id": "calendar-read",
            "resource_type": "CALENDAR_EVENT",
            "connector_id": "google_workspace",
            "allowed_read_tool_ids": ["calendar_list_events"],
            "required": True,
            "reason_codes": ["POLICY_PRECONDITION"],
        }
    ]

    plan_query(
        llm_runtime=runtime,
        prompt_ref=prompt_ref,
        revision_prompt_ref=prompt_ref,
        output_schema=RETRIEVAL_QUERY_PLAN_V2_OUTPUT_SCHEMA,
        prompt_input={"request_intent": {}, "input_routes": frozen_routes},
        requested_mode="LOCAL_GPU",
        frozen_routes=cast(list[InputToolRouteV1], frozen_routes),
        route_policies={
            "calendar-read": RouteConstraintPolicy(frozenset({"TEMPORAL_RANGE", "CONTAINER_REF"}))
        },
        retry_budget=build_default_run_budget(),
    )

    projected_input = cast(dict[str, object], runtime.calls[0]["prompt_input"])
    projected_routes = cast(list[dict[str, object]], projected_input["input_routes"])
    assert projected_routes[0]["supported_constraint_kinds"] == ["TEMPORAL_RANGE"]


def test_general_gmail_search__with_sender_and_subject__passes_values_to_planner() -> None:
    output = {
        "schema_version": 2,
        "route_queries": [
            {
                "route_id": "route-1",
                "operation": "SEARCH",
                "reason_codes": ["USER_REQUEST"],
                "search_spec": {
                    "mode": "INITIAL",
                    "constraints": [
                        {
                            "kind": "PARTICIPANT",
                            "participants": [{"role": "SENDER", "identity": "sender@example.com"}],
                            "match_mode": "ALL",
                        },
                        {"kind": "KEYWORD", "terms": ["회신부탁"], "match_mode": "PHRASE"},
                    ],
                },
                "detail_candidate_ref": None,
            }
        ],
    }
    runtime = FakeStructuredInferencePort(outputs=[output])
    prompt_ref = PromptReference(
        prompt_bundle_version="test",
        prompt_id="retrieval.plan_query",
        prompt_version="1",
        content_hash="hash",
        agent_role="retrieval",
        subgraph_name="retrieval",
        node_name="plan_query",
        node_state="INITIAL",
        purpose="plan_query",
        input_schema_version="v2",
        output_schema_version="v2",
    )
    frozen_routes = [
        {
            "route_id": "route-1",
            "resource_type": "GMAIL_THREAD",
            "connector_id": "google_workspace",
            "allowed_read_tool_ids": ["gmail_search_threads", "gmail_get_thread"],
            "required": True,
            "reason_codes": ["USER_REQUEST"],
        }
    ]
    prompt_input: dict[str, object] = {
        "request_intent": {
            "constraints": [
                {
                    "kind": "SCOPE",
                    "field": "search_criteria_sender",
                    "value": "sender@example.com",
                },
                {"kind": "SCOPE", "field": "search_criteria_subject", "value": "회신부탁"},
            ]
        },
        "input_routes": frozen_routes,
    }

    result, _, llm_invoked = plan_query(
        llm_runtime=runtime,
        prompt_ref=prompt_ref,
        revision_prompt_ref=prompt_ref,
        output_schema=RETRIEVAL_QUERY_PLAN_V2_OUTPUT_SCHEMA,
        prompt_input=prompt_input,
        requested_mode="LOCAL_GPU",
        frozen_routes=cast(list[InputToolRouteV1], frozen_routes),
        route_policies={"route-1": RouteConstraintPolicy(frozenset({"PARTICIPANT", "KEYWORD"}))},
        retry_budget=build_default_run_budget(),
    )

    assert llm_invoked is True
    constraints = result["route_queries"][0]["search_spec"]
    assert constraints is not None
    assert constraints["mode"] == "INITIAL"
    assert constraints["constraints"] == [
        {
            "kind": "PARTICIPANT",
            "participants": [{"role": "SENDER", "identity": "sender@example.com"}],
            "match_mode": "ALL",
        },
        {"kind": "KEYWORD", "terms": ["회신부탁"], "match_mode": "PHRASE"},
    ]


def test_general_gmail_search__with_relation_constraint__preserves_count_semantics() -> None:
    output = {
        "schema_version": 2,
        "route_queries": [
            {
                "route_id": "route-1",
                "operation": "SEARCH",
                "reason_codes": ["USER_REQUEST"],
                "search_spec": {
                    "mode": "INITIAL",
                    "constraints": [
                        {
                            "kind": "KEYWORD",
                            "terms": ["대리", "프로젝트", "일정"],
                            "match_mode": "ANY",
                        }
                    ],
                },
                "detail_candidate_ref": None,
            }
        ],
    }
    runtime = FakeStructuredInferencePort(outputs=[output])
    prompt_ref = PromptReference(
        prompt_bundle_version="test",
        prompt_id="retrieval.plan_query",
        prompt_version="1",
        content_hash="hash",
        agent_role="retrieval",
        subgraph_name="retrieval",
        node_name="plan_query",
        node_state="INITIAL",
        purpose="plan_query",
        input_schema_version="v2",
        output_schema_version="v2",
    )
    frozen_routes = [
        {
            "route_id": "route-1",
            "resource_type": "GMAIL_THREAD",
            "connector_id": "google_workspace",
            "allowed_read_tool_ids": ["gmail_search_threads", "gmail_get_thread"],
            "required": True,
            "reason_codes": ["USER_REQUEST"],
        }
    ]
    prompt_input: dict[str, object] = {
        "request_intent": {
            "constraints": [
                {"kind": "RESOURCE", "field": "subject", "value": "project_schedule"},
                {"kind": "PERSON", "field": "person", "value": ["김대리"]},
                {
                    "kind": "USER_REQUIREMENT",
                    "field": "original_search_request",
                    "value": ["김대리와 이야기한 프로젝트 일정 메일을 찾아봐"],
                },
                {
                    "kind": "USER_REQUIREMENT",
                    "field": "search_terms",
                    "value": ["프로젝트", "일정"],
                },
            ]
        },
        "input_routes": frozen_routes,
    }

    result, _, llm_invoked = plan_query(
        llm_runtime=runtime,
        prompt_ref=prompt_ref,
        revision_prompt_ref=prompt_ref,
        output_schema=RETRIEVAL_QUERY_PLAN_V2_OUTPUT_SCHEMA,
        prompt_input=prompt_input,
        requested_mode="LOCAL_GPU",
        frozen_routes=cast(list[InputToolRouteV1], frozen_routes),
        route_policies={"route-1": RouteConstraintPolicy(frozenset({"PARTICIPANT", "KEYWORD"}))},
        retry_budget=build_default_run_budget(),
    )

    assert llm_invoked is True
    search_spec = result["route_queries"][0]["search_spec"]
    assert search_spec is not None
    assert search_spec["mode"] == "INITIAL"
    assert search_spec["constraints"] == [
        {"kind": "KEYWORD", "terms": ["대리", "프로젝트", "일정"], "match_mode": "ANY"},
    ]


def test_general_gmail_search__last_week__uses_schema_bound_temporal_value() -> None:
    output: dict[str, Any] = {
        "schema_version": 3,
        "route_queries": [
            {
                "route_id": "route-1",
                "operation": "SEARCH",
                "reason_codes": ["USER_REQUEST"],
                "search_spec": {
                    "mode": "INITIAL",
                    "constraints": {
                        "keyword": {
                            "kind": "KEYWORD",
                            "terms": ["프로젝트", "일정"],
                            "match_mode": "ANY",
                        },
                        "temporal_range": {
                            "kind": "TEMPORAL_RANGE",
                            "axis": "MESSAGE_TIME",
                            "start_local": "2026-08-24T00:00:00",
                            "end_local": "2026-08-31T00:00:00",
                            "timezone": "Asia/Seoul",
                        },
                    },
                },
                "detail_candidate_ref": None,
            }
        ],
    }
    runtime = FakeStructuredInferencePort(outputs=[output])
    prompt_ref = PromptReference(
        prompt_bundle_version="test",
        prompt_id="retrieval.plan_query",
        prompt_version="1",
        content_hash="hash",
        agent_role="retrieval",
        subgraph_name="retrieval",
        node_name="plan_query",
        node_state="INITIAL",
        purpose="plan_query",
        input_schema_version="v2",
        output_schema_version="v2",
    )
    frozen_routes = [
        {
            "route_id": "route-1",
            "resource_type": "GMAIL_THREAD",
            "connector_id": "google_workspace",
            "allowed_read_tool_ids": ["gmail_search_threads", "gmail_get_thread"],
            "required": True,
            "reason_codes": ["USER_REQUEST"],
        }
    ]

    result, _, _ = plan_query(
        llm_runtime=runtime,
        prompt_ref=prompt_ref,
        revision_prompt_ref=prompt_ref,
        output_schema=RETRIEVAL_QUERY_PLAN_V2_OUTPUT_SCHEMA,
        prompt_input={
            "request_intent": {
                "constraints": [
                    {"kind": "DATE", "field": "period", "value": ["지난주"]},
                    {"kind": "TIME", "field": "temporal_axis", "value": "MESSAGE_TIME"},
                    {
                        "kind": "USER_REQUIREMENT",
                        "field": "search_terms",
                        "value": ["프로젝트", "일정"],
                    },
                ]
            },
            "input_routes": frozen_routes,
        },
        requested_mode="LOCAL_GPU",
        frozen_routes=cast(list[InputToolRouteV1], frozen_routes),
        route_policies={"route-1": RouteConstraintPolicy(frozenset({"KEYWORD", "TEMPORAL_RANGE"}))},
        retry_budget=build_default_run_budget(),
        now_ms=1_788_560_100_000,
        timezone="Asia/Seoul",
    )

    search_spec = result["route_queries"][0]["search_spec"]
    assert search_spec is not None
    assert search_spec["mode"] == "INITIAL"
    assert search_spec["constraints"] == [
        {
            "kind": "TEMPORAL_RANGE",
            "axis": "MESSAGE_TIME",
            "start_local": "2026-08-24T00:00:00",
            "end_local": "2026-08-31T00:00:00",
            "timezone": "Asia/Seoul",
        },
        {"kind": "KEYWORD", "terms": ["프로젝트", "일정"], "match_mode": "ANY"},
    ]
    dispatched_schema = cast(OutputSchemaDefinition, runtime.calls[0]["output_schema"])
    assert validate_output_schema(output, dispatched_schema.json_schema) == []
    output["route_queries"][0]["search_spec"]["constraints"]["temporal_range"]["start_local"] = (
        "2025-08-24T00:00:00"
    )
    assert validate_output_schema(output, dispatched_schema.json_schema)


def test_selected_exact_resource__invalid_route_binding__fails_without_llm_fallback() -> None:
    runtime = FakeStructuredInferencePort(outputs=[])
    prompt_ref = PromptReference(
        prompt_bundle_version="test",
        prompt_id="retrieval.plan_query",
        prompt_version="1",
        content_hash="hash",
        agent_role="retrieval",
        subgraph_name="retrieval",
        node_name="plan_query",
        node_state="INITIAL",
        purpose="plan_query",
        input_schema_version="v2",
        output_schema_version="v2",
    )
    frozen_routes = [
        {
            "route_id": "route-1",
            "resource_type": "GMAIL_THREAD",
            "connector_id": "google_workspace",
            "allowed_read_tool_ids": ["gmail_get_thread"],
            "required": True,
            "reason_codes": ["RESOURCE_SELECTED"],
        }
    ]

    with pytest.raises(RetrievalV2ValidationError, match="does not match"):
        plan_query(
            llm_runtime=runtime,
            prompt_ref=prompt_ref,
            revision_prompt_ref=prompt_ref,
            output_schema=RETRIEVAL_QUERY_PLAN_V2_OUTPUT_SCHEMA,
            prompt_input={"request_intent": {}, "input_routes": frozen_routes},
            requested_mode="LOCAL_GPU",
            frozen_routes=cast(list[InputToolRouteV1], frozen_routes),
            route_policies={"route-1": RouteConstraintPolicy(frozenset({"RESOURCE_REF"}))},
            retry_budget=build_default_run_budget(),
            validated_resource_refs={"route-1": ["task:wrong-scope"]},
        )

    assert runtime.calls == []


class _OmittingRepositoryInference:
    def infer(
        self,
        requested_mode: Literal["AUTO", "LOCAL_GPU", "API_LLM"],
        prompt_ref: PromptReference,
        input_projection: Mapping[str, object],
        output_schema_ref: OutputSchemaDefinition,
    ) -> StructuredInferenceResultV1:
        del requested_mode, prompt_ref, input_projection, output_schema_ref
        return StructuredInferenceResultV1(
            schema_version=1,
            structured_output={
                "schema_version": 2,
                "route_queries": [
                    {
                        "route_id": "route-1",
                        "operation": "SEARCH",
                        "reason_codes": ["USER_REQUEST"],
                        "search_spec": {"mode": "INITIAL", "constraints": []},
                        "detail_candidate_ref": None,
                    }
                ],
            },
            provider="fake",
            model="fake",
            actual_runtime="API_LLM",
            input_tokens=1,
            output_tokens=1,
            latency_ms=1,
            fallback_reason=None,
        )


def test_plan_query__validated_required_repository__binds_before_semantic_validation() -> None:
    prompt = PromptReference(
        prompt_bundle_version="test",
        prompt_id="retrieval.plan_query",
        prompt_version="1",
        content_hash="hash",
        agent_role="retrieval",
        subgraph_name="retrieval",
        node_name="plan_query",
        node_state="ACTIVE",
        purpose="test",
        input_schema_version="1",
        output_schema_version="2",
    )
    schema = RETRIEVAL_QUERY_PLAN_V2_OUTPUT_SCHEMA
    route: InputToolRouteV1 = {
        "route_id": "route-1",
        "connector_id": "github",
        "resource_type": "GITHUB_ISSUE",
        "allowed_read_tool_ids": ["github_list_issues"],
        "required": True,
        "reason_codes": ["USER_REQUEST"],
    }

    result, _, used_llm = plan_query(
        llm_runtime=_OmittingRepositoryInference(),
        prompt_ref=prompt,
        revision_prompt_ref=prompt,
        output_schema=schema,
        prompt_input={},
        requested_mode="AUTO",
        frozen_routes=[route],
        route_policies={
            "route-1": RouteConstraintPolicy(
                supported_kinds=frozenset({"CONTAINER_REF", "STATUS_SCOPE"}),
                required_kinds=frozenset({"CONTAINER_REF"}),
            )
        },
        retry_budget=build_default_run_budget(),
        validated_container_refs={"route-1": ["acme/repo"]},
    )

    assert used_llm is True
    assert result["route_queries"][0]["search_spec"] == {
        "mode": "INITIAL",
        "constraints": [{"kind": "CONTAINER_REF", "container_refs": ["acme/repo"]}],
    }
