"""Route-local query handoff tests with fake inference and no Provider calls."""

from copy import deepcopy
from typing import Any, cast

import pytest
from tests.support.context_retrieval import request_intent
from tests.support.fakes.llm import FakeStructuredInferencePort

from google_work_agent.application.agents.request_understanding.contracts.request_intent import (
    RequestIntentV3,
)
from google_work_agent.application.agents.request_understanding.validate_intent import (
    validate_intent,
)
from google_work_agent.application.agents.retrieval.build_query import RouteConstraintPolicy
from google_work_agent.application.agents.retrieval.contracts.query_plan import (
    RetrievalV2ValidationError,
)
from google_work_agent.application.agents.retrieval.contracts.query_plan_schema import (
    RETRIEVAL_QUERY_PLAN_V2_OUTPUT_SCHEMA,
    normalize_retrieval_query_plan_candidate,
)
from google_work_agent.application.agents.retrieval.plan_query import (
    RetrievalBudget,
    _validate_initial_user_anchor_preservation,
    followup_retrieval_planner_input,
    initial_retrieval_planner_input,
    plan_query,
)
from google_work_agent.application.agents.retrieval.project_route_constraints import (
    project_route_constraints,
)
from google_work_agent.application.agents.tool_routing.contracts.tool_route_plan import (
    InputToolRouteV1,
)
from google_work_agent.application.prompt_runtime.load_prompt_input_contract import (
    load_prompt_input_contract,
)
from google_work_agent.application.prompt_runtime.prompt_registry import PromptRegistry
from google_work_agent.application.use_cases.run.guard_run_budget import build_default_run_budget
from google_work_agent.ports.llm.output_schema_validation import validate_output_schema


def _route(route_id: str, *work_ids: str, resource: str = "GMAIL_THREAD") -> InputToolRouteV1:
    return cast(
        InputToolRouteV1,
        {
            "route_id": route_id,
            "connector_id": "google_workspace",
            "resource_type": resource,
            "work_unit_ids": list(work_ids),
            "allowed_read_tool_ids": [
                "tasks_list_tasks" if resource == "TASK" else "gmail_search_threads"
            ],
            "required": True,
            "reason_codes": ["REQUESTED_INPUT"],
        },
    )


def _constraint(value: str, work: str, *, field: str = "search_terms") -> dict[str, Any]:
    return {
        "kind": "USER_REQUIREMENT",
        "field": field,
        "value": value,
        "work_unit_ids": [work],
        "provenance": {
            "source": "USER_REQUEST",
            "start_offset": 0,
            "end_offset": len(value),
        },
    }


def _projection(intent: Any, routes: list[InputToolRouteV1], *, followup: bool = False) -> Any:
    arguments = {
        "user_request": "Summarize Alpha mail. Separately list Beta Tasks.",
        "request_intent": intent,
        "input_routes": routes,
        "retrieval_budget": RetrievalBudget(),
        "validated_resource_refs": {"mail": ["gmail_thread:exact-identity"]},
    }
    if followup:
        return followup_retrieval_planner_input(
            **cast(Any, arguments),
            followup={
                "current_round_no": 1,
                "prior_query_attempts": [],
                "unresolved_sufficiency_issues": [],
                "read_result_summaries": [],
            },
        )
    return initial_retrieval_planner_input(**cast(Any, arguments))


def _query(route_id: str, value: str, *, participant: bool = False) -> dict[str, Any]:
    constraint: dict[str, Any] = (
        {
            "kind": "PARTICIPANT",
            "participants": [{"role": "SENDER", "identity": value}],
            "match_mode": "ANY",
        }
        if participant
        else {"kind": "KEYWORD", "terms": [value], "match_mode": "ANY"}
    )
    return {
        "schema_version": 3,
        "route_queries": [
            {
                "route_id": route_id,
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


def _run(prompt_input: Any, routes: list[InputToolRouteV1], outputs: list[object]) -> Any:
    runtime = FakeStructuredInferencePort(outputs=outputs)
    prompt_ref = PromptRegistry().lookup_for_development_smoke("retrieval.plan_query")
    result, budget, invoked = plan_query(
        llm_runtime=runtime,
        prompt_ref=prompt_ref,
        revision_prompt_ref=prompt_ref,
        output_schema=RETRIEVAL_QUERY_PLAN_V2_OUTPUT_SCHEMA,
        prompt_input=prompt_input,
        requested_mode="LOCAL_GPU",
        frozen_routes=routes,
        route_policies={
            route["route_id"]: RouteConstraintPolicy(
                frozenset({"KEYWORD", "PARTICIPANT", "CONCEPT"})
            )
            for route in routes
        },
        retry_budget=build_default_run_budget(),
    )
    assert invoked is True
    return result, budget, runtime


@pytest.mark.parametrize("followup", [False, True])
def test_query_input_preserves_exact_shared_work_binding_and_selected_identity(
    followup: bool,
) -> None:
    routes = [_route("mail", "work-2", "work-1"), _route("task", "work-3", resource="TASK")]
    original = deepcopy(routes)
    intent = {
        "schema_version": 3,
        "constraints": [
            _constraint("Alpha", "work-1"),
            _constraint("Gamma", "work-2"),
            _constraint("Beta", "work-3"),
        ],
    }
    projected = _projection(intent, routes, followup=followup)

    assert projected["input_routes"][0]["work_unit_ids"] == ["work-2", "work-1"]
    assert projected["input_routes"][0]["resource_refs"] == ["gmail_thread:exact-identity"]
    assert projected["input_routes"][1]["work_unit_ids"] == ["work-3"]
    assert projected["required_user_anchors"] == [
        {
            "applies_to": "INITIAL_GMAIL_SEARCH",
            "route_ids": ["mail"],
            "work_unit_ids": ["work-2", "work-1"],
            "keyword_terms": ["Alpha", "Gamma"],
            "participant_identities": [],
        }
    ]
    projected["input_routes"][0]["work_unit_ids"].append("not-authorized")
    assert routes == original


@pytest.mark.parametrize("participant", [False, True])
def test_wrong_work_anchor_is_rejected_then_revised_with_same_route_binding(
    participant: bool,
) -> None:
    first, second = ("a@example.test", "b@example.test") if participant else ("Alpha", "Beta")
    field = "sender_email" if participant else "search_terms"
    routes = [_route("mail", "work-1"), _route("task", "work-2", resource="TASK")]
    intent = {
        "schema_version": 3,
        "constraints": [
            _constraint(first, "work-1", field=field),
            _constraint(second, "work-2", field=field),
        ],
    }
    projected = _projection(intent, routes)
    wrong = _query("mail", second, participant=participant)
    correct = _query("mail", first, participant=participant)
    result, budget, runtime = _run(projected, routes, [wrong, correct])

    assert result == normalize_retrieval_query_plan_candidate(correct)
    assert len(runtime.calls) == 2
    first_call, repair = runtime.calls
    assert first_call["prompt_input"]["input_routes"][0]["work_unit_ids"] == ["work-1"]
    assert repair["prompt_input"]["base_projection"]["input_routes"][0]["work_unit_ids"] == [
        "work-1"
    ]
    assert (
        repair["prompt_input"]["failure_record"]["failure_reason_code"]
        == "QUERY_USER_CONSTRAINT_MISSING"
    )
    assert budget["semantic_revisions_used_by_failure"]
    assert validate_output_schema(wrong, first_call["output_schema"].json_schema)
    assert not validate_output_schema(correct, first_call["output_schema"].json_schema)


def test_shared_read_accepts_either_applicable_anchor_without_extra_query_or_call() -> None:
    route = _route("mail", "work-1", "work-2")
    projected = _projection(
        {
            "schema_version": 3,
            "constraints": [_constraint("Alpha", "work-1"), _constraint("Beta", "work-2")],
        },
        [route],
    )
    candidate = _query("mail", "Beta")
    result, _, runtime = _run(projected, [route], [candidate])

    assert len(runtime.calls) == len(result["route_queries"]) == 1
    assert projected["required_user_anchors"][0]["keyword_terms"] == ["Alpha", "Beta"]


def test_independent_gmail_routes_have_independent_literal_schema_bindings() -> None:
    routes = [_route("first", "work-1"), _route("second", "work-2")]
    projected = _projection(
        {
            "schema_version": 3,
            "constraints": [_constraint("Alpha", "work-1"), _constraint("Beta", "work-2")],
        },
        routes,
    )
    candidate = _query("first", "Alpha")
    candidate["route_queries"].extend(_query("second", "Beta")["route_queries"])
    result, _, runtime = _run(projected, routes, [candidate])

    schema = runtime.calls[0]["output_schema"].json_schema
    assert len(runtime.calls) == 1
    assert len(result["route_queries"]) == 2
    assert not validate_output_schema(candidate, schema)
    assert validate_output_schema(_query("first", "Beta"), schema)
    assert validate_output_schema(_query("second", "Alpha"), schema)
    assert [item["keyword_terms"] for item in projected["required_user_anchors"]] == [
        ["Alpha"],
        ["Beta"],
    ]


def test_repeated_wrong_work_anchor_fails_closed_at_existing_revision_limit() -> None:
    routes = [_route("mail", "work-1")]
    projected = _projection(
        {
            "schema_version": 3,
            "constraints": [_constraint("Alpha", "work-1"), _constraint("Beta", "work-2")],
        },
        routes,
    )
    with pytest.raises(RetrievalV2ValidationError) as caught:
        _run(projected, routes, [_query("mail", "Beta"), _query("mail", "Beta")])
    assert caught.value.reason_code == "QUERY_USER_CONSTRAINT_MISSING"


def test_concept_only_work_is_not_disabled_by_another_work_exact_anchor() -> None:
    routes = [_route("mail", "work-1"), _route("other-mail", "work-2")]
    projected = _projection(
        {
            "schema_version": 3,
            "constraints": [
                _constraint("Alpha", "work-1"),
                _constraint("delays", "work-2", field="business_concepts"),
            ],
        },
        routes,
    )
    _, _, runtime = _run(projected, routes, [_query("mail", "Alpha")])

    shown = {route["route_id"]: route for route in runtime.calls[0]["prompt_input"]["input_routes"]}
    assert "CONCEPT" not in shown["mail"]["supported_constraint_kinds"]
    assert "CONCEPT" in shown["other-mail"]["supported_constraint_kinds"]
    with pytest.raises(RetrievalV2ValidationError, match="concept-only"):
        _validate_initial_user_anchor_preservation(
            cast(Any, normalize_retrieval_query_plan_candidate(_query("other-mail", "Alpha"))),
            prompt_input=projected,
            frozen_routes=routes,
        )


@pytest.mark.parametrize("remove_from", ["constraint", "route", "both"])
def test_v3_missing_binding_never_becomes_implicit_global_scope(remove_from: str) -> None:
    route = _route("mail", "work-1")
    constraint = _constraint("Alpha", "work-1")
    if remove_from in {"route", "both"}:
        cast(dict[str, Any], route).pop("work_unit_ids")
    if remove_from in {"constraint", "both"}:
        constraint.pop("work_unit_ids")
    projected = _projection({"schema_version": 3, "constraints": [constraint]}, [route])

    assert projected["required_user_anchors"][0]["keyword_terms"] == []
    if remove_from in {"route", "both"}:
        assert "work_unit_ids" not in projected["input_routes"][0]


def test_unbound_legacy_direct_input_keeps_anchors_without_inventing_work_ids() -> None:
    route = _route("mail")
    cast(dict[str, Any], route).pop("work_unit_ids")
    constraint = _constraint("Alpha", "work-1")
    constraint.pop("work_unit_ids")
    projected = _projection({"constraints": [constraint]}, [route])

    assert projected["required_user_anchors"][0]["keyword_terms"] == ["Alpha"]
    assert "work_unit_ids" not in projected["required_user_anchors"][0]
    assert "work_unit_ids" not in projected["input_routes"][0]
    assert (
        project_route_constraints(
            {"request_intent": {"requested_work": {}, "constraints": [constraint]}}, route
        )
        == []
    )


def test_followup_can_pivot_without_reimposing_initial_exact_anchor() -> None:
    routes = [_route("mail", "work-1")]
    projected = _projection(
        {"schema_version": 3, "constraints": [_constraint("Alpha", "work-1")]},
        routes,
        followup=True,
    )
    candidate = cast(Any, normalize_retrieval_query_plan_candidate(_query("mail", "NewAlias")))
    assert (
        _validate_initial_user_anchor_preservation(
            candidate, prompt_input=projected, frozen_routes=routes
        )
        is candidate
    )


def test_valid_v3_mail_and_task_intent_reaches_query_without_cross_work_anchor() -> None:
    parts = ["Summarize Alpha mail.", "Separately list Beta Tasks."]
    text = " ".join(parts)
    intent = cast(Any, request_intent())
    intent.update(
        goal=text, analysis_requirement="NONE", requested_resource_hints=["GMAIL_THREAD", "TASK"]
    )
    intent["requested_work"] = {
        "work_units": [
            {
                "unit_id": f"work-{index + 1}",
                "request_provenance": [
                    {
                        "source": "USER_REQUEST",
                        "start_offset": text.index(part),
                        "end_offset": text.index(part) + len(part),
                        "source_text": part,
                    }
                ],
            }
            for index, part in enumerate(parts)
        ],
        "work_relations": [],
    }
    intent["constraints"] = []
    for value, work in [("Alpha", "work-1"), ("Beta", "work-2")]:
        constraint = _constraint(value, work)
        constraint["provenance"].update(
            start_offset=text.index(value), end_offset=text.index(value) + len(value)
        )
        intent["constraints"].append(constraint)
    validated = validate_intent(
        intent, require_meta=True, provenance_sources={"USER_REQUEST": text}
    )
    routes = [_route("mail", "work-1"), _route("task", "work-2", resource="TASK")]
    projected = _projection(validated, routes)

    assert projected["required_user_anchors"][0]["keyword_terms"] == ["Alpha"]
    with pytest.raises(RetrievalV2ValidationError):
        _validate_initial_user_anchor_preservation(
            cast(Any, normalize_retrieval_query_plan_candidate(_query("mail", "Beta"))),
            prompt_input=projected,
            frozen_routes=routes,
        )


def test_query_projection_contract_version_and_draft_activation_are_preserved() -> None:
    contract = load_prompt_input_contract()
    registry = PromptRegistry()
    prompt = registry.lookup_for_development_smoke("retrieval.plan_query")
    projected = _projection(cast(RequestIntentV3, {"constraints": []}), [_route("mail", "work-1")])

    assert contract.entry("retrieval.plan_query").input_schema_version == 6
    assert prompt.input_schema_version == "6"
    contract.validate_projection("retrieval.plan_query", projected)
    assert registry.product_release_ready is False
