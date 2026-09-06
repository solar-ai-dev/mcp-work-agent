"""Synthetic evidence: production semantic contracts across the two Connector families."""

from dataclasses import replace
from typing import Any, cast

import pytest
from tests.support.context_retrieval import (
    SUFFICIENCY_PROMPT_REF,
    _acquisition_result,
    _intent,
    _tool_route_plan,
)
from tests.support.fakes.llm import FakeStructuredInferencePort

from google_work_agent.adapters.langgraph.subgraphs.retrieval.projections import (
    execute_read_projection,
)
from google_work_agent.adapters.system.memory.run_retrieval_cache import InMemoryRunRetrievalCache
from google_work_agent.application.agents.retrieval.assess_sufficiency import (
    assess_sufficiency,
    source_statuses_prompt_projection,
)
from google_work_agent.application.agents.retrieval.build_query import (
    RouteConstraintPolicy,
    build_query,
)
from google_work_agent.application.agents.retrieval.contracts.query_plan import (
    RetrievalQueryPlanV2,
    RetrievalV2ValidationError,
)
from google_work_agent.application.agents.retrieval.contracts.query_plan_schema import (
    RETRIEVAL_QUERY_PLAN_V2_OUTPUT_SCHEMA,
)
from google_work_agent.application.agents.retrieval.execute_read import execute_read
from google_work_agent.application.agents.retrieval.plan_candidate_detail import (
    plan_candidate_detail,
)
from google_work_agent.application.agents.retrieval.plan_query import plan_query
from google_work_agent.application.agents.retrieval.plan_query_expansion import (
    plan_query_expansion,
)
from google_work_agent.application.agents.tool_routing.contracts.tool_route_plan import (
    InputToolRouteV1,
)
from google_work_agent.application.tool_registry.load_signed_tool_registry import (
    load_signed_tool_registry,
)
from google_work_agent.application.use_cases.run.guard_run_budget import build_default_run_budget
from google_work_agent.ports.connector.connector_read_port import ConnectorReadResultV1

GITHUB: InputToolRouteV1 = {
    "route_id": "github", "connector_id": "github", "resource_type": "GITHUB_ISSUE",
    "allowed_read_tool_ids": ["github_list_issues", "github_get_issue"],
    "required": True, "reason_codes": ["USER_REQUEST"],
}
GOOGLE: InputToolRouteV1 = {
    "route_id": "gmail", "connector_id": "google_workspace", "resource_type": "GMAIL_THREAD",
    "allowed_read_tool_ids": ["gmail_search_threads", "gmail_get_thread"],
    "required": True, "reason_codes": ["USER_REQUEST"],
}
POLICY = RouteConstraintPolicy(
    supported_kinds=frozenset({"CONTAINER_REF", "STATUS_SCOPE"}),
    required_kinds=frozenset({"CONTAINER_REF"}),
)


def _query(status: str) -> RetrievalQueryPlanV2:
    return cast(RetrievalQueryPlanV2, {
        "schema_version": 2, "required_information": ["issues"], "retrieval_order": ["github"],
        "route_queries": [{
            "route_id": "github", "operation": "SEARCH", "reason_codes": ["USER_REQUEST"],
            "search_spec": {"mode": "INITIAL", "constraints": [
                {"kind": "CONTAINER_REF", "container_refs": ["acme/repo"]},
                {"kind": "STATUS_SCOPE", "values": [status]},
            ]}, "detail_candidate_ref": None,
        }],
    })


@pytest.mark.parametrize("status", ["OPEN", "CLOSED"])
def test_github_status__real_schema_and_planner__reaches_connector(
    status: str,
) -> None:
    runtime = FakeStructuredInferencePort(outputs=[_query(status)], validate_schema=True)
    plan, _, invoked = plan_query(
        llm_runtime=runtime,
        prompt_ref=replace(SUFFICIENCY_PROMPT_REF, prompt_id="retrieval.plan_query"),
        revision_prompt_ref=SUFFICIENCY_PROMPT_REF,
        output_schema=RETRIEVAL_QUERY_PLAN_V2_OUTPUT_SCHEMA,
        prompt_input={"input_routes": [GITHUB]}, requested_mode="LOCAL_GPU",
        frozen_routes=[GITHUB], route_policies={"github": POLICY},
        retry_budget=build_default_run_budget(), validated_container_refs={"github": ["acme/repo"]},
    )
    fetch = build_query(
        plan, frozen_routes=[GITHUB], route_policies={"github": POLICY},
        validated_container_refs={"github": ["acme/repo"]},
    )[0]
    tool, arguments = execute_read_projection.project_connector_call(
        fetch, route=GITHUB, page_size=20
    )
    assert invoked and len(runtime.calls) == 1
    assert (tool, arguments) == ("github_list_issues", {"repository": "acme/repo", "state": status})


@pytest.mark.parametrize("status", ["COMPLETED", "INCOMPLETE", "DRAFT", "CONFIRMED"])
def test_google_status__github_query__fails_closed(status: str) -> None:
    with pytest.raises(RetrievalV2ValidationError):
        build_query(
            _query(status), frozen_routes=[GITHUB], route_policies={"github": POLICY},
            validated_container_refs={"github": ["acme/repo"]},
        )


def _followup() -> dict[str, object]:
    return {
        "current_round_no": 1,
        "unresolved_sufficiency_issues": [{
            "slot": "issue body", "route_id": "github", "issue_type": "MISSING",
            "required": True, "resolution_source": "CONNECTOR", "safety_critical": False,
            "reason_codes": ["MISSING_BODY"],
        }],
        "read_result_summaries": [
            {"route_id": route["route_id"], "has_next_page": True, "exhausted": False}
            for route in (GOOGLE, GITHUB)
        ],
    }


def test_connector_followup__page_and_detail__select_only_deficient_route() -> None:
    prompt = _followup()
    page = plan_query_expansion(prompt_input=prompt, frozen_routes=[GOOGLE, GITHUB])
    detail = plan_candidate_detail(
        prompt_input=prompt, frozen_routes=[GOOGLE, GITHUB],
        detail_candidate_refs=["gmail_thread:known", "github_issue:acme/repo#7"],
    )
    assert page is not None and detail is not None
    assert page["retrieval_order"] == detail["retrieval_order"] == ["github"]
    assert page["route_queries"][0]["operation"] == "NEXT_PAGE"
    assert detail["route_queries"][0]["detail_candidate_ref"] == "github_issue:acme/repo#7"
    assert plan_candidate_detail(
        prompt_input=prompt, frozen_routes=[GOOGLE, GITHUB],
        detail_candidate_refs=["github_issue:acme/repo#7"],
        attempted_detail_candidate_refs=["github_issue:acme/repo#7"],
    ) is None


@pytest.mark.parametrize("write,expected", [(False, "PARTIAL"), (True, "BLOCKED")])
def test_failed_github_route__successful_google_evidence__preserves_gap(
    write: bool, expected: str,
) -> None:
    intent = _intent()
    intent["analysis_requirement"] = "NONE"
    intent["constraints"] = []
    intent["requested_resource_hints"] = ["GMAIL_THREAD", "GITHUB_ISSUE"]
    intent["requested_effect_hints"] = ["READ", "CREATE"] if write else ["READ"]
    acquisition = _acquisition_result()
    acquisition["source_summaries"][0]["route_id"] = "gmail"
    acquisition["source_summaries"].append({
        "source": "GITHUB", "connector_id": "github", "route_id": "github",
        "status": "FAILED", "resource_count": 0, "resource_handles": [],
    })
    budget = build_default_run_budget()
    budget["additional_retrieval_rounds_used"] = 2
    result = assess_sufficiency(
        llm_runtime=FakeStructuredInferencePort(
            outputs=[{"schema_version": 2, "status": "SUFFICIENT", "issues": []}],
            validate_schema=True,
        ),
        prompt_ref=SUFFICIENCY_PROMPT_REF, requested_mode="LOCAL_GPU", request_intent=intent,
        tool_route_plan=_tool_route_plan([GOOGLE, GITHUB]), acquisition_result=acquisition,
        evidence_drafts=[{
            "schema_version": 1, "evidence_id": "e1", "resource_handle": "gmail_thread:thread-kim",
            "segment_id": "s1", "kind": "excerpt", "excerpt": "confirmed source fact",
            "locator": {}, "reason_codes": ["SUPPORTS"],
        }], retry_budget=budget,
    )
    assert result["status"] == expected
    assert [(issue["route_id"], issue["resolution_source"]) for issue in result["issues"]] == [
        ("github", "CONNECTOR"),
    ]


def test_same_connector_routes__source_statuses__remain_independent() -> None:
    second = {**GITHUB, "route_id": "github-second"}
    acquisition = _acquisition_result()
    acquisition["source_summaries"] = [{
        "source": "GITHUB", "connector_id": "github", "route_id": "github", "status": "COMPLETE",
    }]
    statuses = source_statuses_prompt_projection(
        tool_route_plan=_tool_route_plan([GITHUB, second]), acquisition_result=acquisition,
    )
    assert [item["status"] for item in statuses] == ["COMPLETE", "NOT_ATTEMPTED"]


class _PagedReader:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def execute_read(self, binding: Any, arguments: dict[str, Any]) -> ConnectorReadResultV1:
        self.calls.append(arguments)
        return ConnectorReadResultV1(
            schema_version=1, tool_id=binding.tool_id, request_id=f"r{len(self.calls)}",
            output={"items": []}, next_page_token="opaque" if len(self.calls) == 1 else None,
            total_count=0,
        )


def test_github_pagination__exhaustion__counts_only_real_calls() -> None:
    fetch = build_query(
        _query("OPEN"), frozen_routes=[GITHUB], route_policies={"github": POLICY},
        validated_container_refs={"github": ["acme/repo"]},
    )[0]
    reader, cache, budget = _PagedReader(), InMemoryRunRetrievalCache(), build_default_run_budget()
    binding = load_signed_tool_registry().bind_required("github", "github_list_issues", "READ")
    args = {"repository": "acme/repo", "state": "OPEN"}
    def invoke(plan: Any, handle: str) -> Any:
        return execute_read(
            plan=plan, run_id="run-1", binding=binding, tool_arguments=args,
            connector_reader=reader, read_result_cache=cache, read_result_handle=handle,
            run_budget=budget, now_ms=1000, prior_query_attempts=[],
        )
    assert invoke(fetch, "first").provider_called
    page = {**fetch, "operation_kind": "NEXT_PAGE", "prior_read_result_handle": "first"}
    assert invoke(page, "second").provider_called
    exhausted = {**page, "prior_read_result_handle": "second"}
    assert not invoke(exhausted, "third").provider_called
    assert len(reader.calls) == 2
    assert budget["connector_calls_used"] == budget["source_page_calls_used"] == 2
    assert reader.calls[1]["page_token"] == "opaque"
