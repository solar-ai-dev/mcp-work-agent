"""Actual policy/Registry route binding with synthetic acquisition, no external I/O."""

from __future__ import annotations

from collections import deque
from copy import deepcopy
from itertools import count
from typing import Any, cast

import pytest
from tests.support.context_retrieval import (
    SUFFICIENCY_PROMPT_REF,
    FakeLLMRuntime,
    acquisition_result,
    llm_result,
    request_intent,
    run_budget,
    sufficiency_result_fixture,
    tool_route_plan,
)

from google_work_agent.application.agents.retrieval.assess_sufficiency import (
    _is_policy_only_acquisition_route,
    assess_sufficiency,
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
from google_work_agent.application.agents.tool_routing.select_tool_if_needed import (
    select_tool_if_needed,
)
from google_work_agent.application.tool_registry.load_signed_tool_registry import (
    load_development_tool_registry,
)
from google_work_agent.domain.action.model import EffectType


def _connected_fixture(resource: str, *, business_read: bool = False) -> tuple[Any, Any, Any]:
    intent = request_intent()
    intent.update(
        goal="제공한 제목과 시간으로 새 항목을 준비한다.",
        completion_conditions=["정확한 승인 전 Preview"],
        constraints=[
            {"kind": "RESOURCE", "field": "title", "value": "검토", "work_unit_ids": ["work-1"]},
            {
                "kind": "TIME",
                "field": "start",
                "value": "2026-10-01T15:00:00+09:00",
                "work_unit_ids": ["work-1"],
            },
            {
                "kind": "TIME",
                "field": "end",
                "value": "2026-10-01T16:00:00+09:00",
                "work_unit_ids": ["work-1"],
            },
        ],
        requested_effect_hints=["READ", "CREATE"] if business_read else ["CREATE"],
        requested_resource_hints=[resource],
        analysis_requirement="NONE",
        resource_responsibilities={
            "source_reads": [
                {
                    "resource_type": resource,
                    "required_information": ["기존 내용"],
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
    direct = (resource,) if business_read else ()
    semantic = SemanticRouteCandidate(
        input_resource_types=direct,
        output_pairs=((resource, EffectType.CREATE),),
        output_mode="ACTION",
        analysis_requirement="NONE",
        input_reason_codes=tuple((name, "REQUESTED_INPUT") for name in direct),
        input_work_unit_bindings=tuple((name, ("work-1",)) for name in direct),
        output_work_unit_bindings=((resource, EffectType.CREATE, ("work-1",)),),
    )
    policy = resolve_policy_preconditions(request_intent=intent, candidate=semantic)
    assert policy.workflow_signal is None
    ids = count()
    bound = bind_registry_candidates(
        candidate=policy.candidate,
        tool_catalog=load_development_tool_registry(),
        id_factory=lambda: f"route-{next(ids)}",
    )
    plan = tool_route_plan(bound.input_routes)
    output = bound.output_candidates[0]
    runtime = FakeLLMRuntime(deque())
    selected, _ = select_tool_if_needed(
        llm_runtime=runtime,
        route_id=output.route_id,
        connector_id=output.connector_id,
        resource_type=output.resource_type,
        effect=output.effect,
        eligible_tool_ids=output.eligible_tool_ids,
        request=cast(Any, None),
        retry_budget=run_budget(used=0),
    )
    assert runtime.calls == []
    plan["output_plan"] = cast(
        Any,
        {
            **plan["output_plan"],
            "output_mode": "ACTION",
            "output_routes": [
                {
                    "route_id": output.route_id,
                    "resource_type": output.resource_type,
                    "connector_id": output.connector_id,
                    "effect": output.effect,
                    "selected_tool_id": selected,
                    "reason_codes": ["REGISTRY_SINGLE_CANDIDATE"],
                    "work_unit_ids": list(output.work_unit_ids),
                }
            ],
        },
    )
    acquisition = acquisition_result()
    acquisition["resource_handles"] = []
    acquisition["source_summaries"] = [
        cast(
            Any,
            {
                "schema_version": 1,
                "route_id": route["route_id"],
                "source": "TASKS" if resource == "TASK" else "CALENDAR",
                "status": "COMPLETE",
                "required": True,
                "resource_count": 0,
                "resource_handles": [],
                "resources": [],
                "scope_complete": True,
                "continuation_status": "EXHAUSTED",
            },
        )
        for route in bound.input_routes
    ]
    return intent, plan, acquisition


def _assess(intent: Any, plan: Any, acquisition: Any) -> Any:
    runtime = FakeLLMRuntime(deque([llm_result(sufficiency_result_fixture("SUFFICIENT"))]))
    return assess_sufficiency(
        llm_runtime=runtime,
        prompt_ref=SUFFICIENCY_PROMPT_REF,
        requested_mode="LOCAL_GPU",
        request_intent=intent,
        tool_route_plan=plan,
        acquisition_result=acquisition,
        evidence_drafts=[],
        retry_budget=run_budget(used=0),
    )


@pytest.mark.parametrize("resource", ["CALENDAR_EVENT", "TASK"])
def test_complete_empty_policy_lookup_after_actual_dependency_binding_is_not_missing_evidence(
    resource: str,
) -> None:
    intent, plan, acquisition = _connected_fixture(resource)
    assert intent["resource_responsibilities"]["source_reads"] == []
    assert any(len(route["reason_codes"]) > 1 for route in plan["input_plan"]["input_routes"])
    assert _assess(intent, plan, acquisition) == {
        "schema_version": 2,
        "status": "SUFFICIENT",
        "issues": [],
    }


@pytest.mark.parametrize("resource", ["CALENDAR_EVENT", "TASK"])
@pytest.mark.parametrize("policy_reason_only", [False, True])
def test_explicit_business_source_empty_stays_required_even_if_policy_overwrote_reason(
    resource: str,
    policy_reason_only: bool,
) -> None:
    intent, plan, acquisition = _connected_fixture(resource, business_read=True)
    if policy_reason_only:
        for route in plan["input_plan"]["input_routes"]:
            route["reason_codes"] = [x for x in route["reason_codes"] if x.startswith("POLICY_")]
    result = _assess(intent, plan, acquisition)
    assert result["status"] != "SUFFICIENT"
    direct_route = next(
        x for x in plan["input_plan"]["input_routes"] if x["resource_type"] == resource
    )
    assert any(
        issue.get("route_id") == direct_route["route_id"]
        and "REQUIRED_SOURCE_RETURNED_NO_RESOURCES" in issue["reason_codes"]
        for issue in result["issues"]
    )


@pytest.mark.parametrize(
    "change", ["FAILED", "PARTIAL", "NOT_ATTEMPTED", "UNKNOWN_REASON", "LEGACY"]
)
def test_incomplete_or_unproven_mixed_policy_lookup_remains_fail_closed(change: str) -> None:
    intent, plan, acquisition = _connected_fixture("CALENDAR_EVENT")
    before = deepcopy(plan)
    if change == "UNKNOWN_REASON":
        plan["input_plan"]["input_routes"][0]["reason_codes"].append("UNRECOGNIZED_ROLE")
    elif change == "LEGACY":
        intent.pop("resource_responsibilities")
    elif change == "NOT_ATTEMPTED":
        acquisition["source_summaries"].pop(0)
    else:
        acquisition["source_summaries"][0]["status"] = change
    result = _assess(intent, plan, acquisition)
    assert result["status"] != "SUFFICIENT"
    assert any(issue["required"] for issue in result["issues"])
    if change != "UNKNOWN_REASON":
        assert plan == before


@pytest.mark.parametrize("work_binding", [["work-1"], ["work-2"], []])
def test_business_source_classification_uses_route_local_work_binding(
    work_binding: list[str],
) -> None:
    intent, plan, _ = _connected_fixture("CALENDAR_EVENT", business_read=True)
    route = next(
        x for x in plan["input_plan"]["input_routes"] if x["resource_type"] == "CALENDAR_EVENT"
    )
    route["work_unit_ids"] = work_binding
    assert _is_policy_only_acquisition_route(route, request_intent=intent) is (
        work_binding == ["work-2"]
    )


def test_failed_policy_acquisition_retains_safety_critical_policy_issue() -> None:
    intent, plan, acquisition = _connected_fixture("CALENDAR_EVENT")
    acquisition["source_summaries"][0]["status"] = "FAILED"
    result = _assess(intent, plan, acquisition)
    issue = next(x for x in result["issues"] if "REQUIRED_SOURCE_FAILED" in x["reason_codes"])
    assert issue["safety_critical"] is True
    assert issue["resolution_source"] == "POLICY"
