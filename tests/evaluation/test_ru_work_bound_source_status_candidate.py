"""Inactive status-contract component gate; fake semantics, no model/Provider calls."""

from __future__ import annotations

from copy import deepcopy
from itertools import count
from typing import Any, cast

import pytest
from scripts.ru_work_bound_source_status_candidate import (
    build_work_bound_source_status_schema,
    identify_work_bound_source_status,
    normalize_work_bound_source_statuses,
    project_preserved_work_bound_statuses,
)
from tests.support.fakes.llm import FakeStructuredInferencePort

from google_work_agent.adapters.langgraph.main.state import initial_graph_state
from google_work_agent.adapters.langgraph.profiles.profile_registry import GraphProfile
from google_work_agent.adapters.langgraph.subgraphs.retrieval.projections import (
    execute_read_projection,
)
from google_work_agent.adapters.langgraph.subgraphs.tool_routing.graph import ToolRoutingSubgraph
from google_work_agent.application.agents.planning.project_request_intent_for_work_units import (
    project_request_intent_for_work_units,
)
from google_work_agent.application.agents.request_understanding.contracts.request_intent import (
    RequestedWorkDefinitionV1,
    RequestGoalCandidateV1,
    RequestGoalSemanticValidationError,
    ResourceResponsibilitiesV1,
)
from google_work_agent.application.agents.request_understanding.finalize_intent import (
    finalize_intent,
)
from google_work_agent.application.agents.request_understanding.identify_source_status import (
    build_identify_source_status_output_schema,
)
from google_work_agent.application.agents.retrieval.build_query import (
    RouteConstraintPolicy,
    build_query,
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
from google_work_agent.ports.llm.structured_inference_contracts import PromptReference
from google_work_agent.ports.system.contracts.workflow_execution import (
    WorkflowCorrelationContext,
    WorkflowStartRequest,
)

_SPANS = ("Summarize incomplete Tasks.", "Separately list completed Tasks.")
_REQUEST = " ".join(_SPANS)
_PROMPT = PromptReference(
    prompt_bundle_version="inactive-status-candidate",
    prompt_id="request_understanding.identify_source_status",
    prompt_version="candidate",
    content_hash="no-live-prompt-activation",
    agent_role="request_understanding",
    subgraph_name="request_understanding",
    node_name="identify_goal",
    node_state="INITIAL",
    purpose="identify_source_status",
    input_schema_version="2",
    output_schema_version="3",
)


def _work() -> RequestedWorkDefinitionV1:
    return {
        "work_units": [
            {
                "unit_id": f"work-{index + 1}",
                "request_provenance": [
                    {
                        "source": "USER_REQUEST",
                        "start_offset": _REQUEST.index(span),
                        "end_offset": _REQUEST.index(span) + len(span),
                        "source_text": span,
                    }
                ],
            }
            for index, span in enumerate(_SPANS)
        ],
        "work_relations": [],
    }


def _responsibilities() -> ResourceResponsibilitiesV1:
    return {
        "source_reads": [
            {
                "resource_type": "TASK",
                "required_information": ["title", "status"],
                "target_scope": "CRITERIA",
                "work_unit_ids": [f"work-{index}"],
            }
            for index in (1, 2)
        ],
        "outputs": [],
    }


def _status(value: str = "INCOMPLETE", refs: list[str] | None = None) -> dict[str, Any]:
    return {
        "value": value,
        "source_resource_type": "TASK",
        "source": "USER_REQUEST",
        "source_text": "incomplete Tasks" if value == "INCOMPLETE" else "completed Tasks",
        "work_unit_ids": ["work-1"] if refs is None else refs,
    }


def _normalize(output: object, **kwargs: Any) -> Any:
    return normalize_work_bound_source_statuses(
        output,
        responsibilities=kwargs.get("responsibilities", _responsibilities()),
        requested_work=_work(),
        provenance_sources=kwargs.get("provenance_sources", {"USER_REQUEST": _REQUEST}),
    )


def _candidate(constraints: list[Any]) -> RequestGoalCandidateV1:
    responsibilities = _responsibilities()
    return cast(
        RequestGoalCandidateV1,
        {
            "goal": _REQUEST,
            "completion_conditions": list(_SPANS),
            "constraints": constraints
            + [
                {
                    "kind": "USER_REQUIREMENT",
                    "field": "required_information",
                    "value": source["required_information"],
                    "work_unit_ids": source["work_unit_ids"],
                }
                for source in responsibilities["source_reads"]
            ],
            "requested_effect_hints": ["READ"],
            "requested_resource_hints": ["TASK"],
            "resource_responsibilities": responsibilities,
            "analysis_requirement": "NONE",
            "effect_prohibitions": [{"effect": "CREATE", "work_unit_ids": ["work-1", "work-2"]}],
            "requested_work": _work(),
        },
    )


def test_schema_supports_distinct_and_shared_status_without_changing_product_schema() -> None:
    old = build_identify_source_status_output_schema(_responsibilities())
    old_snapshot = deepcopy(old.json_schema)
    new = build_work_bound_source_status_schema(_responsibilities(), _work())
    statuses = [_status(), _status("COMPLETED", ["work-2"])]
    assert validate_output_schema({"statuses": statuses}, new.json_schema) == []
    assert (
        validate_output_schema({"statuses": [_status(refs=["work-1", "work-2"])]}, new.json_schema)
        == []
    )
    assert new.json_schema["properties"]["statuses"]["maxItems"] == 4  # type: ignore[index]
    assert validate_output_schema(
        {
            "statuses": [
                {k: v for k, v in item.items() if k != "work_unit_ids"} for item in statuses
            ]
        },
        old.json_schema,
    ) == ["$.statuses must contain at most 1 items"]
    assert old.json_schema == old_snapshot
    assert (
        build_identify_source_status_output_schema(_responsibilities()).json_schema == old_snapshot
    )


@pytest.mark.parametrize("refs", [[], ["unknown"], ["work-1", "work-1"]])
def test_invalid_work_refs_are_rejected_without_default_union(refs: list[str]) -> None:
    with pytest.raises(ValueError, match="work-bound status candidate is invalid"):
        _normalize({"statuses": [_status(refs=refs)]})


def test_resource_work_membership_is_closed_not_just_known_work_ids() -> None:
    responsibilities = _responsibilities()
    responsibilities["source_reads"][1]["resource_type"] = "CALENDAR_EVENT"
    with pytest.raises(ValueError, match="work-bound status candidate is invalid"):
        _normalize({"statuses": [_status(refs=["work-2"])]}, responsibilities=responsibilities)
    event = {
        **_status(refs=["work-2"]),
        "value": "CANCELLED",
        "source_resource_type": "CALENDAR_EVENT",
        "source_text": "cancelled events",
    }
    normalized = _normalize(
        {"statuses": [event]},
        responsibilities=responsibilities,
        provenance_sources={"USER_REQUEST": "cancelled events"},
    )
    assert normalized[0]["value"] == "CANCELLED"
    assert normalized[0]["work_unit_ids"] == ["work-2"]
    with pytest.raises(ValueError, match="work-bound status candidate is invalid"):
        _normalize(
            {"statuses": [{**event, "source_resource_type": "TASK", "work_unit_ids": ["work-1"]}]}
        )


@pytest.mark.parametrize("source", ["USER_REQUEST", "CONFIRMATION_RESPONSE"])
def test_exact_provenance_is_required_and_not_inferred(source: str) -> None:
    status = {**_status(), "source": source}
    with pytest.raises(RequestGoalSemanticValidationError) as error:
        _normalize({"statuses": [status]}, provenance_sources={source: "unrelated request"})
    assert error.value.reason_code == "REQUEST_STATUS_PROVENANCE_MISMATCH"
    result = _normalize({"statuses": [status]}, provenance_sources={source: "incomplete Tasks"})
    assert result[0]["provenance"]["source"] == source
    assert result[0]["provenance"]["source_text"] == "incomplete Tasks"
    assert result[0]["work_unit_ids"] == ["work-1"]


def test_empty_status_does_not_invent_any_scope() -> None:
    assert _normalize({"statuses": []}, provenance_sources=None) == []
    with pytest.raises(ValueError):
        _normalize({"statuses": [{**_status(), "value": "ANY"}]})


def test_one_work_can_accept_multiple_existing_states_without_forcing_decomposition() -> None:
    result = _normalize({"statuses": [_status(), _status("COMPLETED", ["work-1"])]})
    assert [item["value"] for item in result] == ["INCOMPLETE", "COMPLETED"]
    assert all(item["work_unit_ids"] == ["work-1"] for item in result)


def test_binding_identity_includes_work_set_but_ignores_ref_order() -> None:
    # The owner can bind the same literal to different already-confirmed work.
    result = _normalize({"statuses": [_status(), _status(refs=["work-2"])]})
    assert [item["work_unit_ids"] for item in result] == [["work-1"], ["work-2"]]
    with pytest.raises(ValueError, match="duplicated"):
        _normalize(
            {
                "statuses": [
                    _status(refs=["work-1", "work-2"]),
                    _status(refs=["work-2", "work-1"]),
                ]
            }
        )


@pytest.mark.parametrize("revision", [False, True])
def test_existing_single_call_carries_work_and_preserves_selected_identity(revision: bool) -> None:
    output = {"statuses": [_status(), _status("COMPLETED", ["work-2"])]}
    runtime = FakeStructuredInferencePort(outputs=[output], validate_schema=True)
    selected = [
        {"resource_type": "task", "resource_id": "stable-task", "connector_id": "google_workspace"}
    ]
    prompt_input = {
        "user_request": _REQUEST,
        "selected_resource_refs": selected,
        "requested_work": _work(),
    }
    before = deepcopy(prompt_input)
    result = identify_work_bound_source_status(
        llm_runtime=runtime,
        requested_mode="LOCAL_GPU",
        prompt_ref=_PROMPT,
        prompt_input=prompt_input,
        goal_candidate={"goal": _REQUEST},
        responsibilities=_responsibilities(),
        candidate_output={"statuses": []} if revision else None,
        failure_record={"failure_reason_code": "TEST_STRUCTURAL_FAILURE"} if revision else None,
    )
    assert result == output
    assert len(runtime.calls) == 1
    recorded = runtime.calls[0]["prompt_input"]
    base = cast(dict[str, Any], recorded["base_projection"] if revision else recorded)
    assert base["requested_work"] == _work()
    assert base["selected_resource_refs"] == selected
    assert base["source_reads"] == _responsibilities()["source_reads"]
    assert prompt_input == before
    assert runtime.calls[0]["output_schema"].schema_version == "request-source-status-v3"


def test_simple_selected_work_keeps_identity_and_does_not_force_status() -> None:
    request = "Tell me the current status of the selected Task."
    work: RequestedWorkDefinitionV1 = {
        "work_units": [
            {
                "unit_id": "work-1",
                "request_provenance": [
                    {
                        "source": "USER_REQUEST",
                        "start_offset": 0,
                        "end_offset": len(request),
                        "source_text": request,
                    }
                ],
            }
        ],
        "work_relations": [],
    }
    responsibilities = _responsibilities()
    responsibilities["source_reads"] = responsibilities["source_reads"][:1]
    responsibilities["source_reads"][0]["target_scope"] = "SINGULAR"
    selected = [
        {
            "resource_type": "task",
            "resource_id": "stable-task",
            "connector_id": "google_workspace",
            "parent_resource_id": "stable-list",
        }
    ]
    runtime = FakeStructuredInferencePort(outputs=[{"statuses": []}], validate_schema=True)
    result = identify_work_bound_source_status(
        llm_runtime=runtime,
        requested_mode="LOCAL_GPU",
        prompt_ref=_PROMPT,
        prompt_input={
            "user_request": request,
            "selected_resource_refs": selected,
            "requested_work": work,
        },
        goal_candidate={"goal": request},
        responsibilities=responsibilities,
    )
    assert result == {"statuses": []}
    assert len(runtime.calls) == 1
    projection = runtime.calls[0]["prompt_input"]
    assert projection["selected_resource_refs"] == selected
    assert projection["source_reads"] == responsibilities["source_reads"]
    assert projection["requested_work"] == work


def test_requested_work_proof_is_checked_before_any_fake_inference() -> None:
    work = _work()
    work["work_units"][0]["request_provenance"][0]["source_text"] = "not in request"
    runtime = FakeStructuredInferencePort(outputs=[])
    with pytest.raises(ValueError, match="not source-bound"):
        identify_work_bound_source_status(
            llm_runtime=runtime,
            requested_mode="LOCAL_GPU",
            prompt_ref=_PROMPT,
            prompt_input={
                "user_request": _REQUEST,
                "selected_resource_refs": [],
                "requested_work": work,
            },
            goal_candidate={"goal": _REQUEST},
            responsibilities=_responsibilities(),
        )
    assert runtime.calls == []


def test_intrinsic_only_source_retains_zero_call_path() -> None:
    responsibilities = _responsibilities()
    for source in responsibilities["source_reads"]:
        source["resource_type"] = "GMAIL_DRAFT"
    runtime = FakeStructuredInferencePort(outputs=[])
    assert identify_work_bound_source_status(
        llm_runtime=runtime,
        requested_mode="LOCAL_GPU",
        prompt_ref=_PROMPT,
        prompt_input={
            "user_request": _REQUEST,
            "selected_resource_refs": [],
            "requested_work": _work(),
        },
        goal_candidate={"goal": _REQUEST},
        responsibilities=responsibilities,
    ) == {"statuses": []}
    assert runtime.calls == []


def test_confirmation_preserves_existing_binding_and_rejects_missing_legacy_binding() -> None:
    normalized = _normalize({"statuses": [_status(), _status("COMPLETED", ["work-2"])]})
    candidate = _candidate(normalized)
    preserved = project_preserved_work_bound_statuses(candidate)
    assert _normalize(preserved) == normalized
    assert candidate["constraints"][:2] == normalized
    malformed = deepcopy(candidate)
    del malformed["constraints"][0]["work_unit_ids"]  # type: ignore[misc]
    with pytest.raises(ValueError, match="non-empty list"):
        project_preserved_work_bound_statuses(malformed)


def test_connected_status_binding_keeps_planning_scope_and_one_shared_task_read() -> None:
    statuses = _normalize({"statuses": [_status(), _status("COMPLETED", ["work-2"])]})
    intent = finalize_intent(
        _candidate(statuses),
        {"requires_confirmation": False, "reason_codes": [], "missing_fields": []},
        artifact_id="candidate-status-intent",
        user_request=_REQUEST,
    )
    assert intent["schema_version"] == 3
    for unit, expected in (("work-1", "INCOMPLETE"), ("work-2", "COMPLETED")):
        local = project_request_intent_for_work_units(intent, work_unit_ids=[unit])
        assert [c["value"] for c in local["constraints"] if c["field"] == "status"] == [expected]
        assert local["effect_prohibitions"] == [{"effect": "CREATE", "work_unit_ids": [unit]}]
        assert local["resource_responsibilities"]["outputs"] == []

    request = WorkflowStartRequest(
        run_id="status-component",
        conversation_id="status-component",
        workflow_key="test",
        entry_mode="CHAT",
        requested_mode="LOCAL_GPU",
        request_text=_REQUEST,
        selected_resource_ids=(),
        selected_resources=(),
        correlation=WorkflowCorrelationContext("test", "test", "test"),
        run_budget=build_default_run_budget(started_at_ms=1000),
    )
    runtime = FakeStructuredInferencePort(outputs=[])
    sequence = count()
    graph = ToolRoutingSubgraph(
        llm_runtime=runtime,
        tool_catalog=load_development_tool_registry(),
        prompt_manifest_path=None,
        prompt_execution_scope=DEVELOPMENT_SMOKE,
        graph_profile=GraphProfile.SIX_ROLE_BASELINE,
        merge_decision=lambda state, update, decision: {
            **state,
            **update,
            **decision["state_update"],
        },
        confirm_inline=lambda _state: pytest.fail(
            "complete typed input must not require confirmation"
        ),
        id_factory=lambda: f"status-route-{next(sequence)}",
    ).build()
    state = initial_graph_state(
        request,
        graph_profile=GraphProfile.SIX_ROLE_BASELINE,
        graph_version="component-test",
        initial_target="tool_routing",
    )
    state["request_intent"] = intent
    with provider_dispatch_execution_scope():
        routed = graph.invoke(state)
    routes = routed["tool_route_plan"]["input_plan"]["input_routes"]
    tasks = [route for route in routes if route["resource_type"] == "TASK"]
    assert len(tasks) == 1
    route = tasks[0]
    assert route["work_unit_ids"] == ["work-1", "work-2"]
    assert runtime.calls == []
    route_id = route["route_id"]
    # Explicit union-query fixture tests deterministic consumption, not Query LLM judgment.
    plan = {
        "schema_version": 2,
        "route_queries": [
            {
                "route_id": route_id,
                "operation": "SEARCH",
                "reason_codes": ["USER_REQUEST"],
                "detail_candidate_ref": None,
                "search_spec": {
                    "mode": "INITIAL",
                    "constraints": [
                        {"kind": "STATUS_SCOPE", "values": ["INCOMPLETE", "COMPLETED"]},
                        {"kind": "CONTAINER_REF", "container_refs": ["task-list"]},
                    ],
                },
            }
        ],
    }
    fetches = build_query(
        plan,
        frozen_routes=tasks,
        route_policies={
            route_id: RouteConstraintPolicy(frozenset({"STATUS_SCOPE", "CONTAINER_REF"}))
        },
        validated_container_refs={route_id: ["task-list"]},
    )
    assert len(fetches) == 1
    tool, arguments = execute_read_projection.project_connector_call(
        fetches[0], route=route, page_size=20
    )
    assert tool == "tasks_list_tasks"
    assert arguments["show_completed"] is True
    assert arguments["task_list_id"] == "task-list"
