"""Inactive Source candidate component gates; no model or Provider execution."""

from __future__ import annotations

from copy import deepcopy
from itertools import count
from typing import Any, cast

import pytest
from scripts.ru_source_requirements_candidate import (
    build_source_requirements_output_schema,
    merge_source_requirements_candidate,
    validate_source_requirements_candidate,
)
from tests.support.fakes.llm import FakeStructuredInferencePort

from google_work_agent.adapters.langgraph.main.state import initial_graph_state
from google_work_agent.adapters.langgraph.profiles.profile_registry import GraphProfile
from google_work_agent.adapters.langgraph.subgraphs.tool_routing.graph import ToolRoutingSubgraph
from google_work_agent.application.agents.planning.project_request_intent_for_work_units import (
    project_request_intent_for_work_units,
)
from google_work_agent.application.agents.request_understanding import (
    identify_source_dependencies as source_ops,
)
from google_work_agent.application.agents.request_understanding import (
    merge_resource_responsibilities as merge_ops,
)
from google_work_agent.application.agents.request_understanding.contracts import (
    request_goal_candidate_schema as goal_schema,
)
from google_work_agent.application.agents.request_understanding.finalize_intent import (
    finalize_intent,
)
from google_work_agent.application.prompt_runtime.prompt_registry import DEVELOPMENT_SMOKE
from google_work_agent.application.tool_registry.load_signed_tool_registry import (
    load_development_tool_registry,
)
from google_work_agent.application.use_cases.run.account_provider_dispatch import (
    provider_dispatch_execution_scope,
)
from google_work_agent.application.use_cases.run.guard_run_budget import build_default_run_budget
from google_work_agent.ports.llm.output_schema_validation import validate_output_schema
from google_work_agent.ports.system.contracts.workflow_execution import (
    WorkflowCorrelationContext,
    WorkflowStartRequest,
)

_CATALOG = load_development_tool_registry()
_SOURCE_CANDIDATES = source_ops.build_source_dependency_candidates(_CATALOG)
_UNITS = ("work-1", "work-2")


def _requirement(facts: list[str], scope: str, *units: str) -> dict[str, Any]:
    return {"required_information": facts, "target_scope": scope, "work_unit_ids": list(units)}


def _candidate(*requirements: dict[str, Any]) -> dict[str, Any]:
    return {
        "source_dependencies": [
            {
                "resource_type": item["resource_type"],
                "dependency": "SOURCE_REQUIRED",
                "requirements": deepcopy(list(requirements)),
            }
            if item["resource_type"] == "GMAIL_THREAD" and requirements
            else {"resource_type": item["resource_type"], "dependency": "SOURCE_NOT_REQUIRED"}
            for item in _SOURCE_CANDIDATES
        ]
    }


def _merge(candidate: object, *, action: bool = False, require_source: bool = False) -> Any:
    return merge_source_requirements_candidate(
        source_decisions=candidate,
        source_candidates=_SOURCE_CANDIDATES,
        work_unit_ids=_UNITS,
        output_decisions={
            "output_responsibilities": [
                {"resource_type": "GMAIL_DRAFT", "effect": "CREATE", "work_unit_ids": [unit]}
                for unit in _UNITS
            ]
            if action
            else []
        },
        output_candidates=({"resource_type": "GMAIL_DRAFT", "allowed_output_effects": ["CREATE"]},),
        require_at_least_one_source=require_source,
    )


def _intent(responsibilities: Any, *, action: bool) -> tuple[str, Any]:
    parts = (
        (
            "Prepare a draft summarizing the Alpha mail body.",
            "Prepare a separate draft listing subject lines of Beta mail.",
        )
        if action
        else ("Summarize the Alpha mail body.", "List subject lines of Beta mail.")
    )
    text = " ".join(parts)
    requested_work = {
        "work_units": [
            {
                "unit_id": unit,
                "request_provenance": [
                    {
                        "source": "USER_REQUEST",
                        "start_offset": text.index(part),
                        "end_offset": text.index(part) + len(part),
                        "source_text": part,
                    }
                ],
            }
            for unit, part in zip(_UNITS, parts, strict=True)
        ],
        "work_relations": [],
    }
    constraints: dict[str, Any] = {
        field: []
        for field in (
            "search_terms",
            "business_concepts",
            "person",
            "sender",
            "recipient",
            "subject",
            "period",
            "additional_constraints",
        )
    }
    constraints["search_terms"] = [
        {"value": value, "work_unit_ids": [unit]}
        for value, unit in zip(("Alpha", "Beta"), _UNITS, strict=True)
    ]
    constraints["coverage_requirement"] = {"value": "NOT_COLLECTION", "work_unit_ids": list(_UNITS)}
    goal = goal_schema.validate_request_goal_candidate(
        {
            "goal": text,
            "completion_conditions": list(parts),
            "constraints": constraints,
            "analysis_requirement": "NONE",
        },
        resource_responsibilities=responsibilities,
        effect_prohibitions={"effect_prohibitions": []},
        requested_work=requested_work,
        work_unit_ids=_UNITS,
        schema=goal_schema.identify_goal_output_schema(_UNITS),
    )
    return text, finalize_intent(
        goal,
        {"requires_confirmation": False, "reason_codes": [], "missing_fields": []},
        artifact_id="requirements-candidate",
        user_request=text,
    )


def _merge_state(state: Any, update: Any, decision: Any) -> Any:
    return {**state, **update, **decision["state_update"], "__target__": decision["target"]}


def _unexpected_confirmation(_state: Any) -> Any:
    raise AssertionError("complete component input unexpectedly requested confirmation")


@pytest.mark.parametrize("action", [False, True], ids=["answer", "independent-drafts"])
def test_disjoint_requirements_reach_compiled_shared_route_and_planning_without_cross_product(
    action: bool,
) -> None:
    requirements = [
        _requirement(["message_history"], "SINGULAR", "work-1"),
        _requirement(["subject"], "CRITERIA", "work-2"),
    ]
    candidate = _candidate(*requirements)
    original = deepcopy(candidate)
    responsibilities = _merge(candidate, action=action)
    text, intent = _intent(responsibilities, action=action)
    request = WorkflowStartRequest(
        run_id="requirements-test",
        conversation_id="requirements-test",
        workflow_key="requirements-test",
        entry_mode="GENERAL",
        requested_mode="LOCAL_GPU",
        request_text=text,
        selected_resource_ids=(),
        selected_resources=(),
        correlation=WorkflowCorrelationContext("test", "test", "v1"),
        run_budget=build_default_run_budget(started_at_ms=1000),
    )
    llm = FakeStructuredInferencePort(outputs=[])
    sequence = count()
    graph = ToolRoutingSubgraph(
        llm_runtime=llm,
        tool_catalog=_CATALOG,
        prompt_manifest_path=None,
        prompt_execution_scope=DEVELOPMENT_SMOKE,
        graph_profile=GraphProfile.SIX_ROLE_BASELINE,
        merge_decision=_merge_state,
        confirm_inline=_unexpected_confirmation,
        id_factory=lambda: f"requirement-route-{next(sequence)}",
    ).build()
    state = initial_graph_state(
        request,
        graph_profile=GraphProfile.SIX_ROLE_BASELINE,
        graph_version="requirements-component",
        initial_target="tool_routing",
    )
    state["request_intent"] = intent
    with provider_dispatch_execution_scope():
        routed = graph.invoke(state)
    route_plan = routed["tool_route_plan"]
    routes = route_plan["input_plan"]["input_routes"]

    assert len(routes) == 1
    assert routes[0]["resource_type"] == "GMAIL_THREAD"
    assert routes[0]["work_unit_ids"] == list(_UNITS)
    assert "gmail_search_threads" in routes[0]["allowed_read_tool_ids"]
    assert llm.calls == []
    if action:
        assert len(route_plan["output_plan"]["output_routes"]) == 2
    for unit, expected in zip(_UNITS, requirements, strict=True):
        projected = project_request_intent_for_work_units(intent, work_unit_ids=[unit])
        assert projected["resource_responsibilities"]["source_reads"] == [
            {"resource_type": "GMAIL_THREAD", **expected}
        ]
        information = [
            item for item in projected["constraints"] if item["field"] == "required_information"
        ]
        assert [item["value"] for item in information] == [expected["required_information"]]
        assert [item["work_unit_ids"] for item in information] == [[unit]]
        assert len(projected["resource_responsibilities"]["outputs"]) == int(action)
    assert candidate == original


def test_current_flat_schema_rejects_disjoint_source_shape_candidate_can_express() -> None:
    requirements = [
        _requirement(["message_history"], "SINGULAR", "work-1"),
        _requirement(["subject"], "CRITERIA", "work-2"),
    ]
    candidate = _candidate(*requirements)
    flat = {
        "source_dependencies": [
            *[
                item
                for item in candidate["source_dependencies"]
                if item["dependency"] == "SOURCE_NOT_REQUIRED"
            ],
            *[
                {"resource_type": "GMAIL_THREAD", "dependency": "SOURCE_REQUIRED", **item}
                for item in requirements
            ],
        ]
    }
    product = source_ops.build_source_dependency_output_schema(
        _SOURCE_CANDIDATES, work_unit_ids=_UNITS
    )
    candidate_schema = build_source_requirements_output_schema(
        _SOURCE_CANDIDATES, work_unit_ids=_UNITS
    )
    assert validate_output_schema(flat, product.json_schema)
    assert not validate_output_schema(candidate, candidate_schema.json_schema)


@pytest.mark.parametrize("required", [False, True])
def test_simple_source_and_not_required_match_existing_product_merge(required: bool) -> None:
    item = _requirement(["subject"], "CRITERIA", "work-1")
    nested = _candidate(item) if required else _candidate()
    flat = {
        "source_dependencies": [
            {"resource_type": row["resource_type"], "dependency": row["dependency"], **item}
            if row["dependency"] == "SOURCE_REQUIRED"
            else row
            for row in nested["source_dependencies"]
        ]
    }
    expected = merge_ops.merge_resource_responsibilities(
        source_decisions=cast(Any, flat),
        source_candidates=_SOURCE_CANDIDATES,
        output_decisions={"output_responsibilities": []},
        output_candidates=(),
    )
    assert _merge(nested) == expected


def test_shared_and_local_information_groups_remain_independent() -> None:
    requirements = [
        _requirement(["common context"], "CRITERIA", *_UNITS),
        _requirement(["sender"], "CRITERIA", "work-1"),
        _requirement(["subject"], "CRITERIA", "work-2"),
    ]
    _, intent = _intent(_merge(_candidate(*requirements)), action=False)
    for unit, fact in (("work-1", "sender"), ("work-2", "subject")):
        local = project_request_intent_for_work_units(intent, work_unit_ids=[unit])
        assert [
            item["value"]
            for item in local["constraints"]
            if item["field"] == "required_information"
        ] == [["common context"], [fact]]


@pytest.mark.parametrize(
    "mutation",
    [
        "duplicate-resource",
        "duplicate-requirement",
        "invalid-work",
        "empty-work",
        "duplicate-work",
        "empty-requirements",
        "not-required-payload",
        "unknown-resource",
        "missing-resource",
        "empty-fact",
        "contradictory-scope",
    ],
)
def test_invalid_candidate_preserves_existing_closed_binding_and_scope_guards(
    mutation: str,
) -> None:
    candidate = _candidate(_requirement(["subject"], "SINGULAR", "work-1"))
    items = candidate["source_dependencies"]
    required = next(item for item in items if item["dependency"] == "SOURCE_REQUIRED")
    requirement = required["requirements"][0]
    if mutation == "duplicate-resource":
        items.append(deepcopy(required))
    elif mutation == "duplicate-requirement":
        required["requirements"].append(deepcopy(requirement))
    elif mutation == "invalid-work":
        requirement["work_unit_ids"] = ["unknown"]
    elif mutation == "empty-work":
        requirement["work_unit_ids"] = []
    elif mutation == "duplicate-work":
        requirement["work_unit_ids"] = ["work-1", "work-1"]
    elif mutation == "empty-requirements":
        required["requirements"] = []
    elif mutation == "not-required-payload":
        required["dependency"] = "SOURCE_NOT_REQUIRED"
    elif mutation == "unknown-resource":
        required["resource_type"] = "UNKNOWN"
    elif mutation == "missing-resource":
        items.remove(required)
    elif mutation == "empty-fact":
        requirement["required_information"] = [" []{} "]
    elif mutation == "contradictory-scope":
        required["requirements"].append({**deepcopy(requirement), "target_scope": "CRITERIA"})
    with pytest.raises(ValueError):
        _merge(candidate)


def test_required_source_condition_still_rejects_all_not_required() -> None:
    with pytest.raises(ValueError):
        _merge(_candidate(), require_source=True)


def test_candidate_reuses_exact_set_and_work_contract_without_mutating_product_schema() -> None:
    product = source_ops.build_source_dependency_output_schema(
        _SOURCE_CANDIDATES, work_unit_ids=_UNITS
    )
    original = deepcopy(product.json_schema)
    candidate = build_source_requirements_output_schema(_SOURCE_CANDIDATES, work_unit_ids=_UNITS)
    product_array = cast(Any, product.json_schema)["properties"]["source_dependencies"]
    candidate_array = cast(Any, candidate.json_schema)["properties"]["source_dependencies"]
    for field in ("minItems", "maxItems", "uniqueItems", "allOf"):
        assert candidate_array[field] == product_array[field]
    assert candidate_array["items"]["oneOf"][0] == product_array["items"]["oneOf"][0]
    current_properties = product_array["items"]["oneOf"][1]["properties"]
    candidate_properties = candidate_array["items"]["oneOf"][1]["properties"]["requirements"][
        "items"
    ]["properties"]
    for field in ("required_information", "target_scope", "work_unit_ids"):
        assert candidate_properties[field] == current_properties[field]
    assert product.json_schema == original
    value = _candidate(_requirement(["subject"], "CRITERIA", *_UNITS))
    before = deepcopy(value)
    validated = validate_source_requirements_candidate(
        value, source_candidates=_SOURCE_CANDIDATES, work_unit_ids=_UNITS
    )
    validated["source_dependencies"].clear()
    assert value == before
