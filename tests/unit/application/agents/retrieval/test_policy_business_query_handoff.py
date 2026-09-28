"""Policy pre-reads must not replace a separately requested business acquisition."""

from itertools import count
from typing import Any

import pytest
from tests.support.context_retrieval import request_intent
from tests.support.fakes.llm import FakeStructuredInferencePort

from google_work_agent.adapters.langgraph.subgraphs.retrieval.graph import (
    _runtime_route_constraint_policies,
)
from google_work_agent.application.agents.retrieval.contracts.query_plan_schema import (
    RETRIEVAL_QUERY_PLAN_V2_OUTPUT_SCHEMA,
)
from google_work_agent.application.agents.retrieval.plan_query import (
    deterministic_initial_query_plan,
    plan_query,
)
from google_work_agent.application.agents.tool_routing.bind_registry_candidates import (
    bind_registry_candidates,
)
from google_work_agent.application.agents.tool_routing.contracts.semantic_route_candidate import (
    SemanticRouteCandidate,
)
from google_work_agent.application.agents.tool_routing.resolve_policy_preconditions import (
    resolve_policy_preconditions,
)
from google_work_agent.application.tool_registry.load_signed_tool_registry import (
    load_development_tool_registry,
)
from google_work_agent.application.use_cases.run.guard_run_budget import build_default_run_budget
from google_work_agent.domain.action.model import EffectType
from google_work_agent.ports.llm.structured_inference_contracts import PromptReference


def _bound_policy_request(resource: str, *, business_read: bool) -> dict[str, Any]:
    intent = request_intent()
    intent.update(
        requested_effect_hints=["READ", "CREATE"] if business_read else ["CREATE"],
        requested_resource_hints=[resource],
        constraints=[
            {"kind": "RESOURCE", "field": "title", "value": "new item"},
            {"kind": "DATE", "field": "date", "value": "2026-10-01"},
            {"kind": "TIME", "field": "start_time", "value": "15:00"},
            {"kind": "TIME", "field": "end_time", "value": "16:00"},
        ],
        resource_responsibilities={
            "source_reads": [
                {
                    "resource_type": resource,
                    "required_information": ["existing content"],
                    "target_scope": "CRITERIA",
                    "work_unit_ids": ["work-1"],
                }
            ]
            if business_read
            else [],
            "outputs": [
                {"resource_type": resource, "effect": "CREATE", "work_unit_ids": ["work-1"]}
            ],
        },
    )
    candidate = SemanticRouteCandidate(
        input_resource_types=(resource,) if business_read else (),
        output_pairs=((resource, EffectType.CREATE),),
        output_mode="ACTION",
        analysis_requirement="NONE",
        input_reason_codes=((resource, "REQUESTED_INPUT"),) if business_read else (),
        input_work_unit_bindings=((resource, ("work-1",)),) if business_read else (),
        output_work_unit_bindings=((resource, EffectType.CREATE, ("work-1",)),),
    )
    policy = resolve_policy_preconditions(request_intent=intent, candidate=candidate)
    assert policy.workflow_signal is None
    ids = count()
    bound = bind_registry_candidates(
        candidate=policy.candidate,
        tool_catalog=load_development_tool_registry(),
        id_factory=lambda: f"route-{next(ids)}",
    )
    routes = list(bound.input_routes)
    return {
        "prompt_input": {"request_intent": intent, "input_routes": routes},
        "frozen_routes": routes,
        "route_policies": _runtime_route_constraint_policies(routes),
        "validated_resource_refs": None,
        "validated_container_refs": {
            route["route_id"]: ["calendar:primary" if resource == "CALENDAR_EVENT" else "@default"]
            for route in routes
        },
        "timezone": "Asia/Seoul",
    }


@pytest.mark.parametrize("resource", ["CALENDAR_EVENT", "TASK"])
def test_business_source_is_not_swallowed_by_policy_only_initial_plan(resource: str) -> None:
    arguments = _bound_policy_request(resource, business_read=True)
    direct = next(r for r in arguments["frozen_routes"] if r["resource_type"] == resource)
    # The upstream policy merge currently overwrites REQUESTED_INPUT. Typed Source
    # responsibility remains authoritative even when the explanatory reason is gone.
    assert "REQUESTED_INPUT" not in direct["reason_codes"]
    assert deterministic_initial_query_plan(**arguments) is None


@pytest.mark.parametrize("resource", ["CALENDAR_EVENT", "TASK"])
@pytest.mark.parametrize("identity_authority", ["validated_ref", "route_reason"])
def test_exact_source_identity_is_not_replaced_by_a_broad_policy_lookup(
    resource: str, identity_authority: str
) -> None:
    arguments = _bound_policy_request(resource, business_read=False)
    direct = next(r for r in arguments["frozen_routes"] if r["resource_type"] == resource)
    if identity_authority == "validated_ref":
        arguments["validated_resource_refs"] = {
            direct["route_id"]: [f"{resource.lower()}:existing-item"]
        }
    else:
        direct["reason_codes"].append("RESOURCE_SELECTED")
    assert deterministic_initial_query_plan(**arguments) is None


@pytest.mark.parametrize("resource", ["CALENDAR_EVENT", "TASK"])
def test_business_identity_is_passed_to_existing_planner_instead_of_policy_shortcut(
    resource: str,
) -> None:
    arguments = _bound_policy_request(resource, business_read=False)
    candidate = deterministic_initial_query_plan(**arguments)
    assert candidate is not None
    intent = arguments["prompt_input"]["request_intent"]
    intent["resource_responsibilities"]["source_reads"] = [
        {
            "resource_type": resource,
            "required_information": ["existing content"],
            "target_scope": "SELECTED",
            "work_unit_ids": ["work-1"],
        }
    ]
    direct = next(r for r in arguments["frozen_routes"] if r["resource_type"] == resource)
    reference = f"{resource.lower()}:existing-item"
    arguments["validated_resource_refs"] = {direct["route_id"]: [reference]}
    for query in candidate["route_queries"]:
        if query["route_id"] == direct["route_id"]:
            query.update(
                operation="DETAIL_FETCH",
                reason_codes=["RESOURCE_SELECTED"],
                search_spec=None,
                detail_candidate_ref=reference,
            )
    runtime = FakeStructuredInferencePort(outputs=[candidate])
    result, _, invoked = plan_query(
        llm_runtime=runtime,
        prompt_ref=_prompt(),
        revision_prompt_ref=_prompt(),
        output_schema=RETRIEVAL_QUERY_PLAN_V2_OUTPUT_SCHEMA,
        requested_mode="LOCAL_GPU",
        retry_budget=build_default_run_budget(),
        **arguments,
    )
    assert invoked is True
    assert len(runtime.calls) == 1
    source_query = next(q for q in result["route_queries"] if q["route_id"] == direct["route_id"])
    assert source_query["operation"] == "DETAIL_FETCH"
    assert source_query["detail_candidate_ref"] == reference


def test_source_of_another_work_does_not_change_policy_only_current_work() -> None:
    arguments = _bound_policy_request("TASK", business_read=True)
    source = arguments["prompt_input"]["request_intent"]["resource_responsibilities"][
        "source_reads"
    ][0]
    source["work_unit_ids"] = ["other-work"]
    assert deterministic_initial_query_plan(**arguments) is not None


def _prompt() -> PromptReference:
    return PromptReference(
        prompt_bundle_version="test",
        prompt_id="retrieval.plan_query",
        prompt_version="1",
        content_hash="synthetic",
        agent_role="retrieval",
        subgraph_name="retrieval",
        node_name="plan_query",
        node_state="INITIAL",
        purpose="plan_query",
        input_schema_version="v2",
        output_schema_version="v2",
    )


@pytest.mark.parametrize("resource", ["CALENDAR_EVENT", "TASK"])
def test_pure_policy_initial_plan_remains_deterministic_with_no_llm(resource: str) -> None:
    arguments = _bound_policy_request(resource, business_read=False)
    runtime = FakeStructuredInferencePort(outputs=[])
    result, _, llm_invoked = plan_query(
        llm_runtime=runtime,
        prompt_ref=_prompt(),
        revision_prompt_ref=_prompt(),
        output_schema=RETRIEVAL_QUERY_PLAN_V2_OUTPUT_SCHEMA,
        requested_mode="LOCAL_GPU",
        retry_budget=build_default_run_budget(),
        **arguments,
    )
    assert llm_invoked is False
    assert runtime.calls == []
    assert len(result["route_queries"]) == len(arguments["frozen_routes"])
    assert all(
        q["reason_codes"]
        == [
            "POLICY_CALENDAR_CONFLICT_CHECK"
            if resource == "CALENDAR_EVENT"
            else "POLICY_TASK_DUPLICATE_CHECK"
        ]
        for q in result["route_queries"]
    )
