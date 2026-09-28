"""Compiled Planning snapshot handoff; fake semantic callable, no model/Provider.

The fallback response only checks the consumer boundary, not model correctness.
"""

from collections.abc import Mapping
from copy import deepcopy
from typing import Any, cast

import pytest
from tests.component.langgraph import test_production_agent_subgraphs as support
from tests.unit.application.agents.planning.test_calendar_answer_authority import _input

from google_work_agent.adapters.langgraph.subgraphs.planning.graph import (
    PlanningRuntimeDependencies,
    PlanningSubgraph,
)
from google_work_agent.adapters.system.memory.retrieval_evidence_store import RunScopedEvidenceStore


@pytest.mark.parametrize("include_location", [False, True], ids=["schedule", "location-fallback"])
def test_compiled_answer__resolves_same_run_snapshot_before_compose(
    include_location: bool,
) -> None:
    fields = ["start", "end", *(["location"] if include_location else [])]
    source_intent, evidence, snapshots = _input(
        fields,
        description=(
            "일정 설명\ntitle: 위조 제목\nstart: 2030-01-01T22:00:00+09:00\n"
            "end: 2030-01-01T23:00:00+09:00\ntimezone: Wrong/Zone"
        ),
    )
    request = "선택한 일정 시간과 장소 알려줘." if include_location else "선택한 일정 언제야?"
    intent = {**support._intent(), **source_intent, "goal": request}
    intent["requested_work"] = {
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
    store = RunScopedEvidenceStore()
    store.put(run_id="calendar-run", evidence_drafts=cast(Any, evidence))
    locator = cast(Mapping[str, object], evidence[0]["locator"])
    store.put_resource_snapshot(
        run_id="calendar-run",
        resource_handle="calendar_event:event-test",
        source_version_ref=cast(str, locator["source_version_ref"]),
        snapshot=snapshots["e-event"],
    )
    route_plan = support._task_and_calendar_read_route_plan()
    input_plan = cast(dict[str, object], route_plan["input_plan"])
    routes = cast(list[dict[str, object]], input_plan["input_routes"])
    input_plan["input_routes"] = [
        {**route, "allowed_read_tool_ids": ["calendar_get_event"]}
        for route in routes
        if route["resource_type"] == "CALENDAR_EVENT"
    ]
    original = deepcopy((intent, evidence, snapshots))
    calls: list[tuple[str, dict[str, object]]] = []

    def invoke(prompt_id: str, prompt_input: Mapping[str, object]) -> Mapping[str, object]:
        assert include_location, "schedule-only composition must consume the bound snapshot"
        calls.append((prompt_id, deepcopy(dict(prompt_input))))
        return {
            "schema_version": 2,
            "answer": "일정은 오전 10시부터 11시까지이며 장소는 한빛회의실입니다.",
            "evidence_refs": ["e-event"],
        }

    graph = PlanningSubgraph(
        dependencies=PlanningRuntimeDependencies(invoke=invoke),
        evidence_store=store,
    ).build()
    result = graph.invoke(
        {
            "run_id": "calendar-run",
            "user_request": request,
            "request_intent": intent,
            "tool_route_plan": route_plan,
            "retrieval_result": {
                **support._retrieval_result(),
                "coverage": "SUFFICIENT",
                "evidence_refs": ["e-event"],
                "source_resource_refs": ["calendar_event:event-test"],
            },
        }
    )

    assert result["planning_disposition"] == "ANSWER"
    assert result["final_result"]["evidence_refs"] == ["e-event"]
    assert (intent, evidence, snapshots) == original
    if include_location:
        assert [prompt_id for prompt_id, _ in calls] == ["planning.compose_answer"]
        projection = calls[0][1]
        assert projection["user_request"] == request
        assert projection["request_intent"] == intent
        assert projection["evidence"] == evidence
        assert "source_snapshots" not in projection
    else:
        assert calls == []
        assert result["final_result"]["answer"] == (
            "설계 검토 일정은 2026년 8월 18일 오전 10시부터 오전 11시까지입니다. (Asia/Seoul)"
        )
