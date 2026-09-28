"""Source0 admission hands the original request to actual Planning consumers.

This is a compiled component boundary test, not a semantic model evaluation.
The external-mail case deliberately preserves an upstream Source omission: its
fake response is NOT a business PASS. No Connector or model runtime is created.
"""

from __future__ import annotations

import socket
from collections.abc import Mapping
from copy import deepcopy
from typing import Any, cast

import pytest
from tests.component.langgraph import test_production_agent_subgraphs as support

from google_work_agent.adapters.langgraph.main.state import GraphState, request_from_state
from google_work_agent.adapters.langgraph.main.supervisor_decision import SupervisorTarget
from google_work_agent.adapters.langgraph.main.supervisor_intake_rules import (
    route_frozen_tool_plan,
)
from google_work_agent.adapters.langgraph.subgraphs.planning.graph import (
    PlanningRuntimeDependencies,
    PlanningSubgraph,
)
from google_work_agent.application.agents.tool_routing.contracts.tool_route_plan import (
    ToolRouteDisposition,
    ToolRoutePlanV2,
)


@pytest.mark.parametrize(
    "request_text",
    [
        "아래 메모를 요약해줘. 메모: Cedar 승인 요청은 보류이며 추가 자료를 기다린다.",
        "내 메일에서 Cedar 승인 요청을 찾아 요약해줘.",
    ],
    ids=["provided-memo-source-free", "external-mail-source-omission-unresolved"],
)
def test_source_free_route_preserves_original_input_into_compiled_answer(
    request_text: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    network_attempts: list[object] = []

    def deny_network(*args: object, **_kwargs: object) -> None:
        network_attempts.append(args)
        raise AssertionError("this component must not contact a model or Provider")

    monkeypatch.setattr(socket, "create_connection", deny_network)
    monkeypatch.setattr(socket.socket, "connect", deny_network)
    state = support._state(request_text=request_text)
    intent = support._intent()
    intent["requested_work"] = {
        "work_units": [
            {
                "unit_id": "work-1",
                "request_provenance": [
                    {
                        "source": "USER_REQUEST",
                        "start_offset": 0,
                        "end_offset": len(request_text),
                        "source_text": request_text,
                    }
                ],
            }
        ],
        "work_relations": [],
    }
    state["request_intent"] = cast(Any, intent)
    before = deepcopy(state)
    plan = cast(ToolRoutePlanV2, support._answer_route_plan())
    decision = route_frozen_tool_plan(
        state=state,
        plan=plan,
        disposition=ToolRouteDisposition.NO_TOOL_NEEDED,
    )
    assert decision["target"] == SupervisorTarget.SOLUTION_PLANNING.value
    assert "retrieval_result" not in decision["state_update"]
    assert plan["input_plan"]["input_routes"] == []
    assert plan["output_plan"]["output_mode"] == "ANSWER"

    captured: list[tuple[str, dict[str, object]]] = []
    fake_answer = "연결 검사 전용 응답입니다. 업무 의미 판정은 수행하지 않았습니다."

    def invoke(prompt_id: str, prompt_input: Mapping[str, object]) -> Mapping[str, object]:
        captured.append((prompt_id, deepcopy(dict(prompt_input))))
        return {"schema_version": 2, "answer": fake_answer, "evidence_refs": []}

    graph = PlanningSubgraph(
        dependencies=PlanningRuntimeDependencies(invoke=invoke),
    ).build()
    result = graph.invoke({**state, **decision["state_update"]})
    assert state == before
    assert request_from_state(cast(GraphState, result)).request_text == request_text
    assert [slot for slot, _ in captured] == ["planning.compose_answer"]
    projection = captured[0][1]
    assert set(projection) == {
        "user_request",
        "request_intent",
        "evidence",
        "answer_outline",
        "temporal_constraints",
    }
    assert projection["user_request"] == request_text
    assert projection["request_intent"] == intent
    assert projection["evidence"] == []
    assert projection["answer_outline"] == {"sections": [request_text], "evidence_refs": []}
    assert projection["temporal_constraints"] == []
    assert not {"coverage", "source_statuses", "collection_results"} & projection.keys()
    assert result.get("retrieval_result") is None
    assert result["final_result"] == {
        "schema_version": 2,
        "answer": fake_answer,
        "evidence_refs": [],
    }
    assert network_attempts == []
