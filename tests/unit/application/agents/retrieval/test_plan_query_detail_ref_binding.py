"""Actual planner/revision/materializer connection; fake LLM, no provider execution."""

from copy import deepcopy
from typing import Any, cast

from tests.support.fakes.llm import FakeStructuredInferencePort

from google_work_agent.application.agents.request_understanding.contracts.request_intent import (
    RequestIntentV3,
)
from google_work_agent.application.agents.retrieval.build_query import (
    RouteConstraintPolicy,
    build_query,
)
from google_work_agent.application.agents.retrieval.contracts.query_plan_schema import (
    RETRIEVAL_QUERY_PLAN_V2_OUTPUT_SCHEMA,
)
from google_work_agent.application.agents.retrieval.plan_query import (
    RetrievalBudget,
    initial_retrieval_planner_input,
    plan_query,
)
from google_work_agent.application.agents.tool_routing.contracts.tool_route_plan import (
    InputToolRouteV1,
)
from google_work_agent.application.use_cases.run.guard_run_budget import build_default_run_budget
from google_work_agent.ports.llm.output_schema_validation import validate_output_schema
from google_work_agent.ports.llm.structured_inference_contracts import PromptReference


def _detail(ref: str) -> dict[str, Any]:
    return {
        "schema_version": 3,
        "route_queries": [
            {
                "route_id": "tasks",
                "operation": "DETAIL_FETCH",
                "reason_codes": ["REQUESTED_INPUT"],
                "search_spec": None,
                "detail_candidate_ref": ref,
            }
        ],
    }


def _context(*, selected: bool) -> dict[str, Any]:
    routes = cast(
        list[InputToolRouteV1],
        [
            {
                "route_id": "tasks",
                "resource_type": "TASK",
                "connector_id": "google_workspace",
                "allowed_read_tool_ids": ["tasks_list_tasks", "tasks_get_task"],
                "required": True,
                "reason_codes": ["REQUESTED_INPUT"],
                "work_unit_ids": ["work-1"],
            },
            {
                "route_id": "lists",
                "resource_type": "TASK_LIST",
                "connector_id": "google_workspace",
                "allowed_read_tool_ids": ["tasks_list_tasklists"],
                "required": True,
                "reason_codes": ["CONTAINER_DISCOVERY"],
                "work_unit_ids": ["work-1"],
            },
        ],
    )
    refs = {"tasks": ["task:selected"]} if selected else {}
    parents = {"tasks": ["task_list:parent"], "lists": ["task_list:parent"]}
    request = "선택한 작업을 확인해줘." if selected else "작업 목록을 확인해줘."
    intent = cast(
        RequestIntentV3,
        {
            "schema_version": 3,
            "goal": request,
            "completion_conditions": ["요청한 작업 정보를 답한다."],
            "requested_effect_hints": ["READ"],
            "requested_resource_hints": ["TASK"],
            "analysis_requirement": "NONE",
            "effect_prohibitions": [],
            "constraints": [],
            "ambiguity": {"requires_confirmation": False, "reason_codes": [], "missing_fields": []},
            "requested_work": {
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
            },
            "resource_responsibilities": {
                "source_reads": [
                    {
                        "resource_type": "TASK",
                        "required_information": ["title"],
                        "target_scope": "SINGULAR" if selected else "CRITERIA",
                        "work_unit_ids": ["work-1"],
                    }
                ],
                "outputs": [],
            },
            "meta": {"artifact_id": "intent-1", "revision": 1, "based_on": []},
        },
    )
    return {
        "frozen_routes": routes,
        "route_policies": {
            route["route_id"]: RouteConstraintPolicy(frozenset({"CONTAINER_REF"}))
            for route in routes
        },
        "validated_resource_refs": refs,
        "validated_container_refs": parents,
        "prompt_input": initial_retrieval_planner_input(
            user_request=request,
            request_intent=intent,
            input_routes=routes,
            retrieval_budget=RetrievalBudget(),
            validated_resource_refs=refs,
            validated_container_refs=parents,
        ),
    }


def _plan(runtime: FakeStructuredInferencePort, context: dict[str, Any]) -> tuple[Any, Any, bool]:
    ref = PromptReference(
        "test",
        "retrieval.plan_query",
        "1",
        "hash",
        "retrieval",
        "retrieval",
        "plan_query",
        "INITIAL",
        "plan_query",
        "v2",
        "v2",
    )
    return plan_query(
        llm_runtime=runtime,
        prompt_ref=ref,
        revision_prompt_ref=ref,
        output_schema=RETRIEVAL_QUERY_PLAN_V2_OUTPUT_SCHEMA,
        requested_mode="LOCAL_GPU",
        retry_budget=build_default_run_budget(),
        **context,
    )


def test_planner_first_and_revision_share_exact_ref_schema_and_preserve_materialized_identity() -> (
    None
):
    context = _context(selected=True)
    before = deepcopy(context)
    invalid, valid = _detail("selected"), _detail("task:selected")
    runtime = FakeStructuredInferencePort(outputs=[invalid, valid], validate_schema=False)

    result, budget, invoked = _plan(runtime, context)

    assert invoked is True and len(runtime.calls) == 2
    assert sum(budget["semantic_revisions_used_by_failure"].values()) == 1
    assert context == before
    assert invalid["route_queries"][0]["detail_candidate_ref"] == "selected"
    revision = runtime.calls[1]["prompt_input"]
    assert revision["candidate_output"] == invalid
    failure = cast(dict[str, object], revision["failure_record"])
    assert failure["failure_reason_code"] == "RETRIEVAL_ROUTE_SCOPE_VIOLATION"
    assert failure["affected_field_paths"] == ["$.route_queries[].detail_candidate_ref"]
    assert revision["base_projection"] == runtime.calls[0]["prompt_input"]
    task_input = next(
        route
        for route in cast(list[dict[str, object]], runtime.calls[0]["prompt_input"]["input_routes"])
        if route["route_id"] == "tasks"
    )
    assert task_input["resource_refs"] == ["task:selected"]
    assert task_input["container_refs"] == ["task_list:parent"]
    for call in runtime.calls:
        schema = call["output_schema"].json_schema
        assert validate_output_schema(invalid, schema)
        assert validate_output_schema(valid, schema) == []
    assert runtime.calls[0]["output_schema"] == runtime.calls[1]["output_schema"]
    fetches = build_query(
        result, **{key: value for key, value in context.items() if key != "prompt_input"}
    )
    assert len(fetches) == 1
    assert fetches[0]["operation_kind"] == "DETAIL_FETCH"
    assert fetches[0]["detail_candidate_ref"] == "task:selected"
    assert fetches[0]["resource_type"] == "TASK"


def test_same_planner_without_exact_or_acquired_ref_removes_detail_fetch() -> None:
    context = _context(selected=False)
    output = {
        "schema_version": 3,
        "route_queries": [
            {
                "route_id": "tasks",
                "operation": "SEARCH",
                "reason_codes": ["REQUESTED_INPUT"],
                "detail_candidate_ref": None,
                "search_spec": {
                    "mode": "INITIAL",
                    "constraints": {
                        "container_ref": {
                            "kind": "CONTAINER_REF",
                            "container_refs": ["task_list:parent"],
                        },
                    },
                },
            }
        ],
    }
    runtime = FakeStructuredInferencePort(outputs=[output], validate_schema=False)

    result, budget, invoked = _plan(runtime, context)

    assert invoked is True and len(runtime.calls) == 1
    assert budget["semantic_revisions_used_by_failure"] == {}
    call = runtime.calls[0]
    task_input = next(
        route
        for route in cast(list[dict[str, object]], call["prompt_input"]["input_routes"])
        if route["route_id"] == "tasks"
    )
    assert task_input["allowed_operations"] == ["SEARCH"]
    assert "resource_refs" not in task_input
    assert validate_output_schema(output, call["output_schema"].json_schema) == []
    assert validate_output_schema(_detail("task:selected"), call["output_schema"].json_schema)
    fetches = build_query(
        result, **{key: value for key, value in context.items() if key != "prompt_input"}
    )
    assert len(fetches) == 1 and fetches[0]["operation_kind"] == "SEARCH"
    assert fetches[0]["detail_candidate_ref"] is None
    assert fetches[0]["effective_constraints"] == [
        {"kind": "CONTAINER_REF", "container_refs": ["task_list:parent"]},
    ]
