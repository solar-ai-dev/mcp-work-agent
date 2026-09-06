"""Gmail semantic preservation across production query and evidence boundaries."""

from datetime import datetime
from typing import cast
from zoneinfo import ZoneInfo

import pytest
from tests.support.fakes.llm import FakeStructuredInferencePort

from google_work_agent.adapters.langgraph.subgraphs.retrieval.projections import (
    execute_read_projection,
)
from google_work_agent.application.agents.request_understanding import (
    preserve_explicit_search_anchors,
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
from google_work_agent.application.agents.retrieval.normalize_segments import SourceSegment
from google_work_agent.application.agents.retrieval.plan_query import plan_query
from google_work_agent.application.agents.retrieval.preserve_gmail_search_semantics import (
    gmail_planner_constraint_kinds,
    preserve_gmail_search_semantics,
    validate_requested_concepts,
)
from google_work_agent.application.agents.retrieval.rag_retrieve_rerank import rag_retrieve_rerank
from google_work_agent.application.agents.tool_routing.contracts.tool_route_plan import (
    InputToolRouteV1,
)
from google_work_agent.application.use_cases.run.guard_run_budget import build_default_run_budget
from google_work_agent.ports.llm.output_schema_validation import validate_output_schema
from google_work_agent.ports.llm.structured_inference_contracts import (
    OutputSchemaDefinition,
    PromptReference,
)

ROUTE: InputToolRouteV1 = {
    "route_id": "gmail", "resource_type": "GMAIL_THREAD", "connector_id": "google_workspace",
    "allowed_read_tool_ids": ["gmail_search_threads", "gmail_get_thread"],
    "required": True, "reason_codes": ["USER_REQUEST"],
}
POLICIES = {"gmail": RouteConstraintPolicy(frozenset({"KEYWORD", "CONCEPT"}))}


def test_gmail_constraint_kinds__requested_status_scope__remains_available() -> None:
    kinds = gmail_planner_constraint_kinds({"request_intent": {"constraints": [
        {"kind": "SCOPE", "field": "status", "value": "DRAFT"},
    ]}})
    assert kinds is not None and "STATUS_SCOPE" in kinds


def test_gmail_status__unrelated_or_changed_status__cannot_restrict_search() -> None:
    assert "STATUS_SCOPE" not in gmail_planner_constraint_kinds({"request_intent": {
        "constraints": [{"kind": "SCOPE", "field": "status", "value": "OPEN"}],
    }})
    planned = preserve_gmail_search_semantics(
        _plan([{"kind": "STATUS_SCOPE", "values": ["SENT"]}]), frozen_routes=[ROUTE],
        now_ms=None, timezone=None, prompt_input={"request_intent": {"constraints": [
            {"kind": "SCOPE", "field": "status", "value": "DRAFT"},
        ]}},
    )
    fetch = build_query(planned, frozen_routes=[ROUTE], route_policies={
        "gmail": RouteConstraintPolicy(frozenset({"STATUS_SCOPE"})),
    })[0]
    assert fetch["effective_constraints"] == [{"kind": "STATUS_SCOPE", "values": ["DRAFT"]}]


def test_query_planner__unstructured_request_constraint__retains_bounded_discovery() -> None:
    intent = {"constraints": [
        {"kind": "USER_REQUIREMENT", "field": "original_search_request",
         "value": ["메일에서 ORB-17 물품이 언제 나가는지 확인해줘"]},
    ]}
    kinds = gmail_planner_constraint_kinds({"request_intent": intent})
    assert kinds is not None and "KEYWORD" in kinds
    assert not {"TEMPORAL_RANGE", "STATUS_SCOPE", "CONCEPT"} & kinds
    reference = PromptReference(
        prompt_bundle_version="test", prompt_id="retrieval.plan_query", prompt_version="1",
        content_hash="test", agent_role="retrieval", subgraph_name="retrieval",
        node_name="plan_query", node_state="INITIAL", purpose="plan_query",
        input_schema_version="2", output_schema_version="2",
    )
    runtime = FakeStructuredInferencePort(outputs=[_plan([
        {"kind": "KEYWORD", "terms": ["ORB-17"], "match_mode": "PHRASE"},
    ])])
    planned, _, _ = plan_query(
        llm_runtime=runtime, prompt_ref=reference, revision_prompt_ref=reference,
        output_schema=RETRIEVAL_QUERY_PLAN_V2_OUTPUT_SCHEMA,
        prompt_input={"request_intent": intent, "input_routes": [ROUTE]},
        requested_mode="LOCAL_GPU", frozen_routes=[ROUTE], route_policies=POLICIES,
        retry_budget=build_default_run_budget(),
    )
    fetch = build_query(planned, frozen_routes=[ROUTE], route_policies=POLICIES)[0]
    _, arguments = execute_read_projection.project_connector_call(fetch, route=ROUTE, page_size=20)
    assert arguments["query"] == '"ORB-17"'


def test_gmail_constraints__scope_search_terms__preserves_original_anchor() -> None:
    kinds = gmail_planner_constraint_kinds({"request_intent": {"constraints": [
        {"kind": "SCOPE", "field": "search_terms", "value": ["ORB-17"]},
    ]}})
    assert kinds is not None and "KEYWORD" in kinds
    preserved = preserve_gmail_search_semantics(
        _plan([]), frozen_routes=[ROUTE], now_ms=None, timezone=None,
        prompt_input={"request_intent": {"constraints": [
            {"kind": "SCOPE", "field": "search_terms", "value": ["ORB-17"]},
        ]}},
    )
    fetch = build_query(preserved, frozen_routes=[ROUTE], route_policies=POLICIES)[0]
    _, arguments = execute_read_projection.project_connector_call(fetch, route=ROUTE, page_size=20)
    assert arguments["query"] == '"ORB-17"'


@pytest.mark.parametrize("start,end,valid", [
    (None, None, False), ("2026-09-01", None, True),
    (None, "2026-09-08", True), ("2026-09-01", "2026-09-08", True),
])
def test_temporal_schema__missing_both_boundaries__matches_domain_validation(start, end, valid):
    candidate = _plan([{
        "kind": "TEMPORAL_RANGE", "axis": "MESSAGE_TIME", "start_local": start,
        "end_local": end, "timezone": "Asia/Seoul",
    }])
    errors = validate_output_schema(candidate, RETRIEVAL_QUERY_PLAN_V2_OUTPUT_SCHEMA.json_schema)
    assert (not errors) is valid


def test_gmail_constraints__empty_values__do_not_authorize_temporal_or_status_filters() -> None:
    intent = preserve_explicit_search_anchors.preserve_explicit_search_anchors(
        {
            "goal": "메일 조회", "completion_conditions": ["자료 확인"], "constraints": [
                {"kind": "DATE", "field": "period", "value": ""},
                {"kind": "SCOPE", "field": "status", "value": [" "]},
                {"kind": "USER_REQUIREMENT", "field": "search_terms", "value": ["ORB-17"]},
            ], "requested_resource_hints": ["GMAIL_THREAD"],
            "requested_effect_hints": ["READ"], "analysis_requirement": "NONE",
        }, request_text="메일에서 ORB-17을 찾아줘", entry_mode="AGENT_SEARCH",
    )
    kinds = gmail_planner_constraint_kinds({"request_intent": intent})
    assert kinds is not None and "KEYWORD" in kinds
    assert not {"TEMPORAL_RANGE", "STATUS_SCOPE"} & kinds


def _concept() -> dict[str, object]:
    return {
        "kind": "CONCEPT",
        "concept": "일정",
        "manifestations": ["체육대회", "박람회", "시간변경"],
    }


def test_mail_request__period_only__reaches_provider_without_schedule_filter() -> None:
    request = "9월 첫째주에 온 메일 찾아줘."
    intent = preserve_explicit_search_anchors.preserve_explicit_search_anchors(
        {
            "goal": request, "completion_conditions": ["메일 조회"], "constraints": [
                {"kind": "DATE", "field": "period", "value": ["9월 첫째주"]},
                {"kind": "TIME", "field": "temporal_axis", "value": ["MESSAGE_TIME"]},
            ],
            "requested_resource_hints": ["GMAIL_THREAD"], "requested_effect_hints": ["READ"],
            "analysis_requirement": "NONE",
        }, request_text=request, entry_mode="AGENT_SEARCH",
    )
    planned = preserve_gmail_search_semantics(
        _plan([_concept(),
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
def test_schedule_concept__project_anchor_or_exact_subject__preserves_scope(
    exact_subject: bool,
) -> None:
    request = (
        "제목이 'KAN-93 일정'인 메일 찾아줘"
        if exact_subject else "KAN-93 일정 얘기한 메일 찾아줘"
    )
    candidate = preserve_explicit_search_anchors.preserve_explicit_search_anchors(
        {
            "goal": request, "completion_conditions": ["관련 메일 확인"], "constraints": [
                {"kind": "USER_REQUIREMENT", "field": "search_terms", "value": ["KAN-93"]},
                {"kind": "USER_REQUIREMENT", "field": "business_concepts", "value": ["일정"]},
            ],
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
        _concept(),
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
        inference_schema = cast(OutputSchemaDefinition, runtime.calls[0]["output_schema"])
        assert validate_output_schema(_plan([_concept()]), inference_schema.json_schema) == []
        assert validate_output_schema(_plan([
            _concept(), {"kind": "KEYWORD", "terms": ["invented"], "match_mode": "ALL"},
        ]), inference_schema.json_schema)
        assert arguments["query"] == (
            '{"박람회" "시간변경" "체육대회"} "KAN-93"'
        )
        concept = next(item for item in fetch["effective_constraints"] if item["kind"] == "CONCEPT")
        assert concept["concept"] == "일정"
        assert set(concept["manifestations"]) == {
            "박람회", "체육대회", "시간변경",
        }


@pytest.mark.parametrize("concept,terms,valid", [
    ("납품", ["출하"], True), ("정산", ["차액"], True),
    ("납품", ["납품"], True), ("요청에 없는 업무", ["자료"], False),
])
def test_compound_concepts__planner_hypothesis__keeps_user_owned_concept(concept, terms, valid):
    intent = {"constraints": [
        {"kind": "USER_REQUIREMENT", "field": "business_concepts", "value": ["납품", "정산"]},
        {"kind": "USER_REQUIREMENT", "field": "search_terms", "value": ["ORB-17"]},
    ]}
    candidate = _plan([{"kind": "CONCEPT", "concept": concept, "manifestations": terms}])
    if valid:
        validate_requested_concepts(candidate, {"request_intent": intent}, [ROUTE])
    else:
        with pytest.raises(RetrievalV2ValidationError):
            validate_requested_concepts(candidate, {"request_intent": intent}, [ROUTE])
    assert intent["constraints"][0]["value"] == ["납품", "정산"]
    assert intent["constraints"][1]["value"] == ["ORB-17"]


def test_concept_revision__specific_failure_and_raw_candidate__rebinds_exact_anchor(
) -> None:
    initial_constraints: list[object] = []
    reason = "QUERY_USER_CONSTRAINT_MISSING"
    initial = _plan(initial_constraints)
    runtime = FakeStructuredInferencePort(outputs=[initial, _plan([_concept()])])
    reference = PromptReference(
        prompt_bundle_version="test", prompt_id="retrieval.plan_query", prompt_version="1",
        content_hash="test", agent_role="retrieval", subgraph_name="retrieval",
        node_name="plan_query", node_state="INITIAL", purpose="plan_query",
        input_schema_version="2", output_schema_version="2",
    )
    intent = {"constraints": [
        {"kind": "USER_REQUIREMENT", "field": "business_concepts", "value": ["일정"]},
        {"kind": "USER_REQUIREMENT", "field": "search_terms", "value": ["ORB-17"]},
    ]}
    planned, budget, _ = plan_query(
        llm_runtime=runtime, prompt_ref=reference, revision_prompt_ref=reference,
        output_schema=RETRIEVAL_QUERY_PLAN_V2_OUTPUT_SCHEMA,
        prompt_input={"request_intent": intent, "input_routes": [ROUTE]},
        requested_mode="LOCAL_GPU", frozen_routes=[ROUTE], route_policies=POLICIES,
        retry_budget=build_default_run_budget(),
    )
    repair_input = runtime.calls[1]["prompt_input"]
    assert repair_input["failure_record"]["failure_reason_code"] == reason
    assert repair_input["candidate_output"] == initial
    assert initial["route_queries"][0]["search_spec"]["constraints"] == initial_constraints
    assert sum(budget["semantic_revisions_used_by_failure"].values()) == 1
    fetch = build_query(planned, frozen_routes=[ROUTE], route_policies=POLICIES)[0]
    _, arguments = execute_read_projection.project_connector_call(fetch, route=ROUTE, page_size=20)
    assert arguments["query"] == '{"박람회" "시간변경" "체육대회"} "ORB-17"'


@pytest.mark.parametrize("manifestations", [
    [], ["회의", "회의"], [str(index) for index in range(13)], ["from:someone@example.com"],
    ['회의" OR is:unread'], ["회의\n방문"],
])
def test_concept_schema_builder__unbounded_or_provider_syntax__rejects(
    manifestations: list[str],
) -> None:
    candidate = _plan([{"kind": "CONCEPT", "concept": "일정", "manifestations": manifestations}])
    assert validate_output_schema(candidate, RETRIEVAL_QUERY_PLAN_V2_OUTPUT_SCHEMA.json_schema)
    with pytest.raises(RetrievalV2ValidationError):
        build_query(candidate, frozen_routes=[ROUTE], route_policies=POLICIES)


def test_concept_search__concept_only__bounds_query_and_preserves_changed_identity() -> None:
    concept = _concept()
    assert concept is not None
    candidate = _plan([concept])
    initial = build_query(candidate, frozen_routes=[ROUTE], route_policies=POLICIES)[0]
    reversed_plan = _plan([
        {**concept, "manifestations": list(reversed(cast(list[str], concept["manifestations"])))},
    ])
    reordered = build_query(reversed_plan, frozen_routes=[ROUTE], route_policies=POLICIES)[0]
    assert initial["query_identity_hash"] == reordered["query_identity_hash"]
    _, arguments = execute_read_projection.project_connector_call(
        initial, route=ROUTE, page_size=20,
    )
    assert arguments["query"]
    assert "after:" not in str(arguments["query"])


def test_concept_ranking__matching_concept__remains_candidate_not_event_fact() -> None:
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
        _plan([_concept()]), frozen_routes=[ROUTE], route_policies=POLICIES,
    )
    ranked = rag_retrieve_rerank(segments, request_intent=intent, source_plans=plans, top_k=3)
    assert [item["segment_id"] for item in ranked] == ["s2", "s3", "s1"]
    assert ranked[0]["reason_codes"] == ["CONCEPT_MANIFESTATION_MATCH"]
    assert ranked[1]["reason_codes"] == ["CONCEPT_MANIFESTATION_MATCH"]
    assert ranked[2]["reason_codes"] == []
