"""Actual failed-READ projection through compiled Planning, without Provider/model.

Sufficiency is a fixed typed input. The fake composer verifies the handoff only;
its response is not evidence of semantic model success.
"""

from collections.abc import Mapping
from copy import deepcopy
from typing import cast

import pytest
from tests.component.langgraph import test_production_agent_subgraphs as support

from google_work_agent.adapters.langgraph.subgraphs.planning.graph import (
    PlanningRuntimeDependencies,
    PlanningSubgraph,
)
from google_work_agent.adapters.langgraph.subgraphs.retrieval.projections import (
    execute_read_projection,
)
from google_work_agent.adapters.system.memory.retrieval_evidence_store import RunScopedEvidenceStore
from google_work_agent.application.agents.request_understanding.contracts import (
    request_goal_candidate_schema,
)
from google_work_agent.application.agents.request_understanding.contracts.request_intent import (
    RequestIntentV3,
    ResourceResponsibilitiesV1,
)
from google_work_agent.application.agents.request_understanding.validate_intent import (
    validate_intent,
)
from google_work_agent.application.agents.retrieval.contracts.query_plan import SourceFetchPlanV1
from google_work_agent.application.agents.retrieval.finalize_retrieval import finalize_retrieval
from google_work_agent.application.agents.tool_routing.contracts.tool_route_plan import (
    ToolRoutePlanV2,
)
from google_work_agent.ports.connector.connector_read_port import ConnectorReadResultV1


@pytest.mark.parametrize("failure_code", ["NOT_FOUND", "PERMISSION_DENIED", None])
def test_read_outcome__through_compiled_answer__keeps_failure_distinct_from_empty(
    failure_code: str | None,
) -> None:
    request = "현재 할 일의 상태와 예정일을 알려줘."
    intent = support._intent()
    intent.update(
        goal=request,
        requested_resource_hints=["TASK"],
        resource_responsibilities={
            "source_reads": [
                {
                    "resource_type": "TASK",
                    "required_information": ["status", "due"],
                    "target_scope": "CRITERIA",
                    "work_unit_ids": ["work-1"],
                }
            ],
            "outputs": [],
        },
        requested_work={
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
    )
    intent["constraints"] = request_goal_candidate_schema.derive_source_information_constraints(
        cast(ResourceResponsibilitiesV1, intent["resource_responsibilities"])
    )
    validate_intent(intent, require_meta=True, provenance_sources={"USER_REQUEST": request})
    route_plan = support._task_and_calendar_read_route_plan()
    input_plan = cast(dict[str, object], route_plan["input_plan"])
    routes = cast(list[dict[str, object]], input_plan["input_routes"])
    input_plan["input_routes"] = [route for route in routes if route["resource_type"] == "TASK"]
    fetch_plan = cast(
        SourceFetchPlanV1,
        {
            "route_id": "task-route",
            "connector_id": "google_workspace",
            "resource_type": "TASK",
            "query_identity_hash": "a" * 64,
        },
    )
    empty_read = ConnectorReadResultV1(
        1, "tasks_list_tasks", "component-read", {"items": []}, None, 0
    )
    acquisition = execute_read_projection.project_acquisition_result(
        [(fetch_plan, empty_read)] if failure_code is None else [],
        remaining_budget={},
        failed_reads=[] if failure_code is None else [(fetch_plan, failure_code, True)],
    )
    retrieval = finalize_retrieval(
        artifact_id="retrieval-read-outcome",
        request_intent=cast(RequestIntentV3, intent),
        tool_route_plan=cast(ToolRoutePlanV2, route_plan),
        acquisition_result=acquisition,
        selection_result={
            "schema_version": 2,
            "selected_segment_ids": [],
            "evidence_drafts": [],
            "excluded_segment_ids": [],
        },
        evidence_drafts=[],
        sufficiency_result={
            "schema_version": 2,
            "status": "SUFFICIENT" if failure_code is None else "PARTIAL",
            "issues": [],
        },
        current_round_no=0,
    )
    status = retrieval["source_statuses"][0]
    assert status["checked_read_count"] == 1
    assert status["observed_resource_count"] == 0
    assert status["work_unit_ids"] == ["work-1"]
    assert status["resource_type"] == "task"
    assert retrieval["evidence_refs"] == []
    original = deepcopy((intent, acquisition, retrieval))
    calls: list[tuple[str, dict[str, object]]] = []

    def invoke(prompt_id: str, prompt_input: Mapping[str, object]) -> Mapping[str, object]:
        assert failure_code is not None, "confirmed complete empty READ needs no model"
        calls.append((prompt_id, deepcopy(dict(prompt_input))))
        return {
            "schema_version": 2,
            "answer": "자료 조회가 실패하여 현재 할 일의 상태와 예정일을 확인할 수 없습니다.",
            "evidence_refs": [],
        }

    graph = PlanningSubgraph(
        dependencies=PlanningRuntimeDependencies(invoke=invoke),
        evidence_store=RunScopedEvidenceStore(),
    ).build()
    result = graph.invoke(
        {
            "run_id": "read-outcome-run",
            "user_request": request,
            "request_intent": intent,
            "tool_route_plan": route_plan,
            "retrieval_result": retrieval,
        }
    )
    assert result["planning_disposition"] == "ANSWER"
    assert result["final_result"]["evidence_refs"] == []
    assert (intent, acquisition, retrieval) == original
    answer = result["final_result"]["answer"]
    if failure_code is None:
        assert calls == []
        assert status["status"] == "COMPLETE" and status["failure_kind"] is None
        assert status["scope_complete"] is True
        assert "접근 가능한 전체 범위를 확인했지만 관련 항목을 찾지 못했습니다." in answer
    else:
        assert status["status"] == "FAILED"
        assert status["failure_kind"] == (
            "NOT_FOUND" if failure_code == "NOT_FOUND" else "SCOPE"
        )
        assert status["scope_complete"] is False
        assert status["continuation_status"] == "UNKNOWN"
        assert [prompt_id for prompt_id, _ in calls] == ["planning.compose_answer"]
        projection = calls[0][1]
        assert projection["user_request"] == request
        assert projection["evidence"] == []
        assert projection["source_statuses"] == [status]
        assert projection["coverage"] == "PARTIAL"
        assert "일부 자료를 읽지 못했습니다. 검색 결과가 없다는 뜻은 아닙니다." in answer
        assert "찾지 못했습니다" not in answer
        assert "조회 범위 1개를 확인" not in answer
