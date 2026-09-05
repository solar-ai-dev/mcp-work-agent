"""Semantic concept discovery across the production query and evidence boundaries."""

from datetime import datetime
from typing import cast
from zoneinfo import ZoneInfo

import pytest
from tests.support.fakes.llm import FakeStructuredInferencePort

from google_work_agent.adapters.langgraph.subgraphs.retrieval.projections import (
    execute_read_projection,
)
from google_work_agent.application.agents.request_understanding import (
    preserve_vague_read_semantics,
)
from google_work_agent.application.agents.request_understanding.contracts.request_intent import (
    RequestIntentV2,
)
from google_work_agent.application.agents.retrieval.build_query import (
    RouteConstraintPolicy,
    build_query,
)
from google_work_agent.application.agents.retrieval.contracts.query_plan import (
    RetrievalV2ValidationError,
)
from google_work_agent.application.agents.retrieval.contracts.query_plan_schema import (
    RETRIEVAL_QUERY_PLAN_V2_OUTPUT_SCHEMA,
)
from google_work_agent.application.agents.retrieval.expand_business_concept import (
    expand_business_concept,
)
from google_work_agent.application.agents.retrieval.normalize_segments import SourceSegment
from google_work_agent.application.agents.retrieval.plan_query import plan_query
from google_work_agent.application.agents.retrieval.preserve_gmail_search_semantics import (
    preserve_gmail_search_semantics,
)
from google_work_agent.application.agents.retrieval.rag_retrieve_rerank import rag_retrieve_rerank
from google_work_agent.application.agents.tool_routing.contracts.tool_route_plan import (
    InputToolRouteV1,
)
from google_work_agent.application.use_cases.run.guard_run_budget import build_default_run_budget
from google_work_agent.ports.llm.output_schema_validation import validate_output_schema
from google_work_agent.ports.llm.structured_inference_contracts import PromptReference

ROUTE: InputToolRouteV1 = {
    "route_id": "gmail", "resource_type": "GMAIL_THREAD", "connector_id": "google_workspace",
    "allowed_read_tool_ids": ["gmail_search_threads", "gmail_get_thread"],
    "required": True, "reason_codes": ["USER_REQUEST"],
}
POLICIES = {"gmail": RouteConstraintPolicy(frozenset({"KEYWORD", "CONCEPT"}))}


def test_period_only_mail_request_reaches_provider_without_invented_schedule_filter() -> None:
    request = "9월 첫째주에 온 메일 찾아줘."
    intent = preserve_vague_read_semantics.preserve_vague_read_semantics(
        {
            "goal": request, "completion_conditions": ["메일 조회"], "constraints": [
                {"kind": "USER_REQUIREMENT", "field": "business_concepts", "value": ["일정"]},
            ],
            "requested_resource_hints": ["GMAIL_THREAD"], "requested_effect_hints": ["READ"],
            "analysis_requirement": "NONE",
        }, request_text=request, entry_mode="AGENT_SEARCH",
    )
    planned = preserve_gmail_search_semantics(
        _plan([expand_business_concept("일정"),
               {"kind": "KEYWORD", "terms": ["회의"], "match_mode": "PHRASE"}]),
        prompt_input={"request_intent": intent}, frozen_routes=[ROUTE],
        now_ms=int(datetime(2026, 9, 6, tzinfo=ZoneInfo("Asia/Seoul")).timestamp() * 1000),
        timezone="Asia/Seoul",
    )
    fetch = build_query(
        planned, frozen_routes=[ROUTE], route_policies={
            "gmail": RouteConstraintPolicy(frozenset({"KEYWORD", "CONCEPT", "TEMPORAL_RANGE"})),
        },
    )[0]
    _, arguments = execute_read_projection.project_connector_call(fetch, route=ROUTE, page_size=20)
    assert arguments["query"] == "after:1788188400 before:1788793200"
    assert [item["kind"] for item in fetch["effective_constraints"]] == ["TEMPORAL_RANGE"]


def _plan(constraints: list[object]) -> dict[str, object]:
    return {
        "schema_version": 2,
        "route_queries": [{
            "route_id": "gmail", "operation": "SEARCH", "reason_codes": ["USER_REQUEST"],
            "search_spec": {"mode": "INITIAL", "constraints": constraints},
            "detail_candidate_ref": None,
        }],
        "required_information": ["관련 메일의 실제 업무 내용"], "retrieval_order": ["gmail"],
    }


@pytest.mark.parametrize("exact_subject", [False, True])
def test_schedule_concept_keeps_project_anchor_but_never_broadens_an_exact_subject(
    exact_subject: bool,
) -> None:
    request = (
        "제목이 'KAN-93 일정'인 메일 찾아줘"
        if exact_subject else "KAN-93 일정 얘기한 메일 찾아줘"
    )
    candidate = preserve_vague_read_semantics.preserve_vague_read_semantics(
        {
            "goal": request, "completion_conditions": ["관련 메일 확인"], "constraints": [],
            "requested_resource_hints": ["GMAIL_THREAD"], "requested_effect_hints": ["READ"],
            "analysis_requirement": "NONE",
        },
        request_text=request, entry_mode="AGENT_SEARCH",
    )
    reference = PromptReference(
        prompt_bundle_version="test", prompt_id="retrieval.plan_query", prompt_version="1",
        content_hash="test", agent_role="retrieval", subgraph_name="retrieval",
        node_name="plan_query", node_state="INITIAL", purpose="plan_query",
        input_schema_version="2", output_schema_version="2",
    )
    # A literal model keyword must not AND away the requested concept alternatives.
    runtime = FakeStructuredInferencePort(outputs=[_plan([
        {"kind": "KEYWORD", "terms": ["일정"], "match_mode": "PHRASE"},
    ])])
    planned, _, invoked = plan_query(
        llm_runtime=runtime, prompt_ref=reference, revision_prompt_ref=reference,
        output_schema=RETRIEVAL_QUERY_PLAN_V2_OUTPUT_SCHEMA,
        prompt_input={"request_intent": candidate, "input_routes": [ROUTE]},
        requested_mode="LOCAL_GPU", frozen_routes=[ROUTE], route_policies=POLICIES,
        retry_budget=build_default_run_budget(),
    )
    assert invoked
    assert validate_output_schema(planned, RETRIEVAL_QUERY_PLAN_V2_OUTPUT_SCHEMA.json_schema) == []
    fetch = build_query(planned, frozen_routes=[ROUTE], route_policies=POLICIES)[0]
    tool, arguments = execute_read_projection.project_connector_call(
        fetch, route=ROUTE, page_size=20,
    )
    assert tool == "gmail_search_threads"
    if exact_subject:
        assert arguments["query"] == '"KAN-93 일정"'
        assert not any(item["kind"] == "CONCEPT" for item in fetch["effective_constraints"])
    else:
        assert arguments["query"] == (
            '{"개최" "교육" "박람회" "방문" "시간변경" "일정" "참석" '
            '"체육대회" "출장" "행사" "회의"} "KAN-93"'
        )
        concept = next(item for item in fetch["effective_constraints"] if item["kind"] == "CONCEPT")
        assert concept["concept"] == "일정"
        assert set(concept["manifestations"]) == {
            "일정", "회의", "행사", "박람회", "체육대회", "교육",
            "출장", "방문", "참석", "개최", "시간변경",
        }


@pytest.mark.parametrize("manifestations", [
    [], ["회의", "회의"], [str(index) for index in range(13)], ["from:someone@example.com"],
    ['회의" OR is:unread'], ["회의\n방문"],
])
def test_concept_schema_and_builder_reject_unbounded_or_provider_syntax(
    manifestations: list[str],
) -> None:
    candidate = _plan([{"kind": "CONCEPT", "concept": "일정", "manifestations": manifestations}])
    assert validate_output_schema(candidate, RETRIEVAL_QUERY_PLAN_V2_OUTPUT_SCHEMA.json_schema)
    with pytest.raises(RetrievalV2ValidationError):
        build_query(candidate, frozen_routes=[ROUTE], route_policies=POLICIES)


def test_concept_only_search_is_bounded_and_new_query_identity_preserves_changes() -> None:
    concept = expand_business_concept("일정")
    assert concept is not None
    candidate = _plan([concept])
    initial = build_query(candidate, frozen_routes=[ROUTE], route_policies=POLICIES)[0]
    reversed_plan = _plan([
        {**concept, "manifestations": list(reversed(concept["manifestations"]))},
    ])
    reordered = build_query(reversed_plan, frozen_routes=[ROUTE], route_policies=POLICIES)[0]
    assert initial["query_identity_hash"] == reordered["query_identity_hash"]
    _, arguments = execute_read_projection.project_connector_call(
        initial, route=ROUTE, page_size=20,
    )
    assert arguments["query"]
    assert "after:" not in str(arguments["query"])
    assert expand_business_concept("invented ontology") is None


def test_concept_ranking_is_a_candidate_signal_not_an_event_fact() -> None:
    intent = cast(RequestIntentV2, {
        "goal": "관련 자료를 찾아줘", "constraints": [
            {"kind": "USER_REQUIREMENT", "field": "business_concepts", "value": ["일정"]},
        ],
    })
    segments = [
        SourceSegment("s1", "h1", "GMAIL", "gmail_message", "m1", None, None, {}, "쇼핑 쿠폰"),
        SourceSegment(
            "s2", "h2", "GMAIL", "gmail_message", "m2", None, None, {}, "9월 3일 체육대회",
        ),
        SourceSegment(
            "s3", "h3", "GMAIL", "gmail_message", "m3", None, None, {}, "박람회 참석 안내",
        ),
    ]
    plans = build_query(
        _plan([expand_business_concept("일정")]), frozen_routes=[ROUTE], route_policies=POLICIES,
    )
    ranked = rag_retrieve_rerank(segments, request_intent=intent, source_plans=plans, top_k=3)
    assert [item["segment_id"] for item in ranked] == ["s2", "s3", "s1"]
    assert ranked[0]["reason_codes"] == ["CONCEPT_MANIFESTATION_MATCH"]
    assert ranked[1]["reason_codes"] == ["CONCEPT_MANIFESTATION_MATCH"]
    assert ranked[2]["reason_codes"] == []
