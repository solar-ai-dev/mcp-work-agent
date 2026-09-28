"""Deterministic lookup must not intersect independent shared-READ targets."""

from copy import deepcopy
from typing import Any, cast

import pytest
from tests.support.context_retrieval import request_intent
from tests.support.fakes.llm import FakeStructuredInferencePort

from google_work_agent.application.agents.request_understanding.validate_intent import (
    validate_intent,
)
from google_work_agent.application.agents.retrieval.build_query import RouteConstraintPolicy
from google_work_agent.application.agents.retrieval.contracts.query_plan_schema import (
    RETRIEVAL_QUERY_PLAN_V2_OUTPUT_SCHEMA,
)
from google_work_agent.application.agents.retrieval.plan_query import (
    deterministic_initial_query_plan,
    plan_query,
)
from google_work_agent.application.agents.tool_routing.contracts.tool_route_plan import (
    InputToolRouteV1,
)
from google_work_agent.application.prompt_runtime.prompt_registry import PromptRegistry
from google_work_agent.application.use_cases.run.guard_run_budget import build_default_run_budget


def _arguments(kind: str, terms: tuple[str | None, ...]) -> dict[str, Any]:
    resource = {
        "metadata": "GMAIL_THREAD",
        "draft": "GMAIL_DRAFT",
        "confirmation": "CALENDAR_EVENT",
    }[kind]
    tool = {
        "metadata": "gmail_search_threads",
        "draft": "gmail_search_drafts",
        "confirmation": "calendar_list_events",
    }[kind]
    spans = [
        (
            f"Edit {term or 'existing'} draft with text edit-{index}."
            if kind == "draft"
            else f"List every {term or 'existing'} item for result {index}."
        )
        for index, term in enumerate(terms, 1)
    ]
    request = " ".join(spans)
    response = " ".join(term for term in terms if term is not None)
    units = [
        {
            "unit_id": f"work-{index}",
            "request_provenance": [
                {
                    "source": "USER_REQUEST",
                    "start_offset": request.index(span),
                    "end_offset": request.index(span) + len(span),
                    "source_text": span,
                }
            ],
        }
        for index, span in enumerate(spans, 1)
    ]
    ids = [unit["unit_id"] for unit in units]
    source = "CONFIRMATION_RESPONSE" if kind == "confirmation" else "USER_REQUEST"
    proof = response if kind == "confirmation" else request
    constraints = [
        {
            "kind": "USER_REQUIREMENT",
            "field": "search_terms",
            "value": term,
            "work_unit_ids": [unit],
            "provenance": {
                "source": source,
                "start_offset": proof.index(term),
                "end_offset": proof.index(term) + len(term),
            },
        }
        for term, unit in zip(terms, ids, strict=True)
        if term is not None
    ]
    constraints.extend(
        {
            "kind": "USER_REQUIREMENT",
            "field": "required_information",
            "value": ["subject" if kind == "metadata" else "body"],
            "work_unit_ids": [unit],
        }
        for unit in ids
    )
    if kind == "metadata":
        constraints.append(
            {
                "kind": "SCOPE",
                "field": "coverage_requirement",
                "value": "EXHAUSTIVE",
                "work_unit_ids": ids,
            }
        )
    intent = request_intent()
    intent.update(
        goal=request,
        completion_conditions=spans,
        constraints=constraints,
        analysis_requirement="NONE",
        requested_resource_hints=[resource],
        requested_effect_hints=["READ", "UPDATE"] if kind == "draft" else ["READ"],
        requested_work={"work_units": units, "work_relations": []},
        resource_responsibilities={
            "source_reads": [
                {
                    "resource_type": resource,
                    "required_information": ["subject" if kind == "metadata" else "body"],
                    "target_scope": "CRITERIA",
                    "work_unit_ids": [unit],
                }
                for unit in ids
            ],
            "outputs": [
                {"resource_type": resource, "effect": "UPDATE", "work_unit_ids": [unit]}
                for unit in ids
            ]
            if kind == "draft"
            else [],
        },
    )
    validated = validate_intent(
        intent,
        require_meta=True,
        provenance_sources={"USER_REQUEST": request, "CONFIRMATION_RESPONSE": response},
    )
    route = cast(
        InputToolRouteV1,
        {
            "route_id": "shared-read",
            "resource_type": resource,
            "connector_id": "google_workspace",
            "allowed_read_tool_ids": [tool],
            "required": True,
            "reason_codes": ["REQUESTED_INPUT"],
            "work_unit_ids": ids,
        },
    )
    return {
        "prompt_input": {
            "user_request": request,
            "request_intent": validated,
            "input_routes": [route],
        },
        "frozen_routes": [route],
        "route_policies": {
            "shared-read": RouteConstraintPolicy(frozenset({"KEYWORD", "STATUS_SCOPE"}))
        },
        "validated_resource_refs": None,
        "validated_container_refs": None,
    }


def _invoke(arguments: dict[str, Any], outputs: list[object]) -> tuple[Any, bool, Any]:
    runtime = FakeStructuredInferencePort(outputs=outputs, validate_schema=True)
    prompt = PromptRegistry().lookup_for_development_smoke("retrieval.plan_query")
    result, _, invoked = plan_query(
        llm_runtime=runtime,
        prompt_ref=prompt,
        revision_prompt_ref=prompt,
        output_schema=RETRIEVAL_QUERY_PLAN_V2_OUTPUT_SCHEMA,
        requested_mode="LOCAL_GPU",
        retry_budget=build_default_run_budget(),
        **arguments,
    )
    return result, invoked, runtime


@pytest.mark.parametrize("kind", ["metadata", "draft", "confirmation"])
@pytest.mark.parametrize("terms", [("Alpha", "Beta"), ("Alpha", None), (None, "Alpha")])
def test_different_or_partially_bound_work_lookups_return_to_existing_planner(
    kind: str, terms: tuple[str | None, ...]
) -> None:
    arguments = _arguments(kind, terms)
    before = deepcopy(arguments)
    assert deterministic_initial_query_plan(**arguments) is None
    assert arguments == before


@pytest.mark.parametrize("kind", ["metadata", "draft", "confirmation"])
@pytest.mark.parametrize("terms", [("Alpha",), ("Alpha", "Alpha")])
def test_single_or_identical_shared_lookup_keeps_zero_llm_and_one_route(
    kind: str, terms: tuple[str | None, ...]
) -> None:
    arguments = _arguments(kind, terms)
    result, invoked, runtime = _invoke(arguments, [])
    assert invoked is False and runtime.calls == []
    assert len(result["route_queries"]) == 1
    keyword = result["route_queries"][0]["search_spec"]["constraints"][0]
    assert keyword["terms"] == ["Alpha"]
    assert keyword["match_mode"] == ("ALL" if kind == "metadata" else "PHRASE")
    assert arguments["frozen_routes"][0]["work_unit_ids"] == [
        f"work-{index}" for index in range(1, len(terms) + 1)
    ]


@pytest.mark.parametrize("kind", ["metadata", "draft", "confirmation"])
def test_other_work_literal_does_not_contaminate_current_route(kind: str) -> None:
    arguments = _arguments(kind, ("Alpha", "Beta"))
    arguments["frozen_routes"][0]["work_unit_ids"] = ["work-1"]
    result, invoked, runtime = _invoke(arguments, [])
    assert invoked is False and runtime.calls == []
    assert result["route_queries"][0]["search_spec"]["constraints"][0]["terms"] == ["Alpha"]


@pytest.mark.parametrize("kind", ["metadata", "draft", "confirmation"])
def test_different_information_or_output_edit_does_not_disable_identical_lookup(kind: str) -> None:
    arguments = _arguments(kind, ("Alpha", "Alpha"))
    intent = arguments["prompt_input"]["request_intent"]
    information = {
        "metadata": ("subject", "timestamps"),
        "draft": ("body", "subject"),
        "confirmation": ("title", "description"),
    }[kind]
    required = [item for item in intent["constraints"] if item["field"] == "required_information"]
    for constraint, source, field in zip(
        required, intent["resource_responsibilities"]["source_reads"], information, strict=True
    ):
        constraint["value"] = [field]
        source["required_information"] = [field]
    if kind == "draft":
        request = arguments["prompt_input"]["user_request"]
        for index in (1, 2):
            literal = f"edit-{index}"
            intent["constraints"].append(
                {
                    "kind": "USER_REQUIREMENT",
                    "field": "description",
                    "value": literal,
                    "work_unit_ids": [f"work-{index}"],
                    "provenance": {
                        "source": "USER_REQUEST",
                        "start_offset": request.index(literal),
                        "end_offset": request.index(literal) + len(literal),
                    },
                }
            )
    arguments["prompt_input"]["request_intent"] = validate_intent(
        intent,
        require_meta=True,
        provenance_sources={
            "USER_REQUEST": arguments["prompt_input"]["user_request"],
            "CONFIRMATION_RESPONSE": "Alpha Alpha",
        },
    )
    result, invoked, runtime = _invoke(arguments, [])
    assert result and invoked is False and runtime.calls == []


@pytest.mark.parametrize("kind", ["metadata", "draft", "confirmation"])
def test_one_constraint_shared_by_both_work_units_keeps_zero_llm(kind: str) -> None:
    arguments = _arguments(kind, ("Alpha", "Alpha"))
    constraints = arguments["prompt_input"]["request_intent"]["constraints"]
    constraints[0]["work_unit_ids"] = ["work-1", "work-2"]
    constraints.pop(1)
    result, invoked, runtime = _invoke(arguments, [])
    assert result and invoked is False and runtime.calls == []


@pytest.mark.parametrize("kind", ["metadata", "draft", "confirmation"])
def test_no_anchor_and_followup_never_use_initial_lookup_shortcuts(kind: str) -> None:
    assert deterministic_initial_query_plan(**_arguments(kind, (None, None))) is None
    followup = _arguments(kind, ("Alpha", "Alpha"))
    followup["prompt_input"]["current_round_no"] = 1
    assert deterministic_initial_query_plan(**followup) is None


@pytest.mark.parametrize("kind", ["metadata", "draft", "confirmation"])
def test_legacy_unbound_lookup_is_preserved_but_v3_missing_binding_is_not_global(kind: str) -> None:
    arguments = _arguments(kind, ("Alpha",))
    intent = arguments["prompt_input"]["request_intent"]
    arguments["frozen_routes"][0].pop("work_unit_ids")
    for constraint in intent["constraints"]:
        constraint.pop("work_unit_ids")
    assert deterministic_initial_query_plan(**arguments) is None
    intent.pop("schema_version")
    intent.pop("requested_work")
    assert deterministic_initial_query_plan(**arguments) is not None


def test_metadata_shared_first_prefix_is_not_equality_of_full_lookup_meaning() -> None:
    arguments = _arguments("metadata", ("Common prefix Alpha", "Common prefix Beta"))
    assert deterministic_initial_query_plan(**arguments) is None


def test_shared_distinct_metadata_lookups_reach_one_existing_planner_call() -> None:
    arguments = _arguments("metadata", ("Alpha", "Beta"))
    candidate = {
        "schema_version": 3,
        "route_queries": [
            {
                "route_id": "shared-read",
                "operation": "SEARCH",
                "reason_codes": ["USER_REQUEST"],
                "search_spec": {
                    "mode": "INITIAL",
                    "constraints": {
                        "keyword": {
                            "kind": "KEYWORD",
                            "terms": ["Alpha", "Beta"],
                            "match_mode": "ANY",
                        }
                    },
                },
                "detail_candidate_ref": None,
            }
        ],
    }
    result, invoked, runtime = _invoke(arguments, [candidate])
    assert invoked is True and len(runtime.calls) == 1
    assert len(result["route_queries"]) == 1
    assert result["route_queries"][0]["search_spec"]["constraints"][0]["match_mode"] == "ANY"
    assert runtime.calls[0]["prompt_input"]["input_routes"][0]["work_unit_ids"] == [
        "work-1",
        "work-2",
    ]
