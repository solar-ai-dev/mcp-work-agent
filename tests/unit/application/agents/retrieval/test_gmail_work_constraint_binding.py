"""Gmail query hypotheses consume only constraints owned by their frozen WorkUnits."""

from copy import deepcopy
from typing import Any, cast

import pytest
from tests.support.fakes.llm import FakeStructuredInferencePort

from google_work_agent.application.agents.retrieval.build_query import RouteConstraintPolicy
from google_work_agent.application.agents.retrieval.contracts.query_plan_schema import (
    RETRIEVAL_QUERY_PLAN_V2_OUTPUT_SCHEMA,
)
from google_work_agent.application.agents.retrieval.plan_query import plan_query
from google_work_agent.application.agents.retrieval.resolve_gmail_planner_constraint_kinds import (
    resolve_gmail_planner_constraint_kinds,
)
from google_work_agent.application.agents.retrieval.resolve_requested_gmail_concepts import (
    resolve_requested_gmail_concepts,
)
from google_work_agent.application.agents.tool_routing.contracts.tool_route_plan import (
    InputToolRouteV1,
)
from google_work_agent.application.prompt_runtime.prompt_registry import PromptRegistry
from google_work_agent.application.use_cases.run.guard_run_budget import build_default_run_budget
from google_work_agent.ports.llm.output_schema_validation import validate_output_schema


def _route(*work_ids: str, selected: bool = False) -> InputToolRouteV1:
    return cast(
        InputToolRouteV1,
        {
            "route_id": "mail",
            "resource_type": "GMAIL_THREAD",
            "connector_id": "google_workspace",
            "allowed_read_tool_ids": ["gmail_get_thread" if selected else "gmail_search_threads"],
            "required": True,
            "reason_codes": ["RESOURCE_SELECTED" if selected else "REQUESTED_INPUT"],
            "work_unit_ids": list(work_ids),
        },
    )


def _input() -> dict[str, Any]:
    return {
        "request_intent": {
            "schema_version": 3,
            "constraints": [
                {
                    "kind": "USER_REQUIREMENT",
                    "field": "business_concepts",
                    "value": "alpha",
                    "work_unit_ids": ["work-mail"],
                },
                {
                    "kind": "USER_REQUIREMENT",
                    "field": "business_concepts",
                    "value": "beta",
                    "work_unit_ids": ["work-other"],
                },
                {
                    "kind": "SCOPE",
                    "field": "status",
                    "value": "DRAFT",
                    "work_unit_ids": ["work-other"],
                },
                {
                    "kind": "TIME",
                    "field": "temporal_axis",
                    "value": "EVENT_TIME",
                    "work_unit_ids": ["work-other"],
                },
            ],
        }
    }


@pytest.mark.parametrize("work_id,expected", [("work-mail", {"alpha"}), ("work-other", {"beta"})])
def test_business_concepts_are_bound_in_both_directions(work_id: str, expected: set[str]) -> None:
    prompt = _input()
    original = deepcopy(prompt)
    assert resolve_requested_gmail_concepts(prompt, [_route(work_id)]) == {"mail": expected}
    assert prompt == original


def test_shared_read_keeps_union_of_its_consumers_without_other_work() -> None:
    prompt = _input()
    prompt["request_intent"]["constraints"].append(
        {
            "kind": "USER_REQUIREMENT",
            "field": "business_concepts",
            "value": "unrelated",
            "work_unit_ids": ["work-third"],
        }
    )
    route = _route("work-mail", "work-other")
    assert resolve_requested_gmail_concepts(prompt, [route]) == {"mail": {"alpha", "beta"}}
    assert {"CONCEPT", "KEYWORD", "STATUS_SCOPE", "TEMPORAL_RANGE"}.issubset(
        resolve_gmail_planner_constraint_kinds(prompt, route=route) or set()
    )


def test_other_work_status_and_temporal_axis_do_not_enable_mail_filters() -> None:
    prompt = _input()
    own = resolve_gmail_planner_constraint_kinds(prompt, route=_route("work-mail"))
    other = resolve_gmail_planner_constraint_kinds(prompt, route=_route("work-other"))
    assert own is not None and {"CONCEPT", "KEYWORD"}.issubset(own)
    assert own.isdisjoint({"STATUS_SCOPE", "TEMPORAL_RANGE"})
    assert other is not None and {"STATUS_SCOPE", "TEMPORAL_RANGE"}.issubset(other)


@pytest.mark.parametrize("missing", ["route", "constraint", "both", "unrelated"])
def test_unbound_v3_does_not_recover_other_work_meaning_as_global(missing: str) -> None:
    prompt = _input()
    route = _route("work-mail" if missing != "unrelated" else "work-third")
    if missing in {"route", "both"}:
        cast(dict[str, Any], route).pop("work_unit_ids")
    if missing in {"constraint", "both"}:
        for constraint in prompt["request_intent"]["constraints"]:
            constraint.pop("work_unit_ids")
    assert resolve_requested_gmail_concepts(prompt, [route]) == {}
    kinds = resolve_gmail_planner_constraint_kinds(prompt, route=route)
    assert kinds is not None and "KEYWORD" in kinds
    assert kinds.isdisjoint({"CONCEPT", "STATUS_SCOPE", "TEMPORAL_RANGE"})


def test_selected_detail_does_not_create_search_concept_or_extra_llm_call() -> None:
    prompt = _input()
    route = _route("work-mail", selected=True)
    assert resolve_requested_gmail_concepts(prompt, [route]) == {}
    runtime = FakeStructuredInferencePort(outputs=[])
    ref = PromptRegistry().lookup_for_development_smoke("retrieval.plan_query")
    result, _, invoked = plan_query(
        llm_runtime=runtime,
        prompt_ref=ref,
        revision_prompt_ref=ref,
        output_schema=RETRIEVAL_QUERY_PLAN_V2_OUTPUT_SCHEMA,
        prompt_input=prompt,
        requested_mode="LOCAL_GPU",
        frozen_routes=[route],
        route_policies={"mail": RouteConstraintPolicy(frozenset({"RESOURCE_REF"}))},
        retry_budget=build_default_run_budget(),
        validated_resource_refs={"mail": ["gmail_thread:exact"]},
    )
    assert invoked is False and runtime.calls == []
    assert result["route_queries"][0]["detail_candidate_ref"] == "gmail_thread:exact"


def _query(constraint: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": 3,
        "route_queries": [
            {
                "route_id": "mail",
                "operation": "SEARCH",
                "reason_codes": ["USER_REQUEST"],
                "search_spec": {
                    "mode": "INITIAL",
                    "constraints": {constraint["kind"].lower(): constraint},
                },
                "detail_candidate_ref": None,
            }
        ],
    }


def test_actual_planner_schema_accepts_own_concept_but_rejects_foreign_meaning() -> None:
    route = _route("work-mail")
    prompt = _input()
    prompt["input_routes"] = [route]
    valid = _query({"kind": "CONCEPT", "concept": "alpha", "manifestations": ["alpha"]})
    runtime = FakeStructuredInferencePort(outputs=[valid], validate_schema=True)
    ref = PromptRegistry().lookup_for_development_smoke("retrieval.plan_query")
    result, _, invoked = plan_query(
        llm_runtime=runtime,
        prompt_ref=ref,
        revision_prompt_ref=ref,
        output_schema=RETRIEVAL_QUERY_PLAN_V2_OUTPUT_SCHEMA,
        prompt_input=prompt,
        requested_mode="LOCAL_GPU",
        frozen_routes=[route],
        route_policies={
            "mail": RouteConstraintPolicy(
                frozenset(
                    {
                        "CONCEPT",
                        "KEYWORD",
                        "TEMPORAL_RANGE",
                        "STATUS_SCOPE",
                        "PARTICIPANT",
                    }
                )
            )
        },
        retry_budget=build_default_run_budget(),
    )
    assert invoked is True and len(runtime.calls) == 1
    assert result["route_queries"][0]["search_spec"]["constraints"][0]["concept"] == "alpha"
    schema = runtime.calls[0]["output_schema"].json_schema
    assert validate_output_schema(valid, schema) == []
    for foreign in [
        {"kind": "CONCEPT", "concept": "beta", "manifestations": ["beta"]},
        {"kind": "STATUS_SCOPE", "values": ["DRAFT"]},
        {
            "kind": "TEMPORAL_RANGE",
            "axis": "MESSAGE_TIME",
            "start_local": "2026-10-01T00:00:00",
            "end_local": "2026-10-02T00:00:00",
            "timezone": "Asia/Seoul",
        },
    ]:
        assert validate_output_schema(_query(foreign), schema)
