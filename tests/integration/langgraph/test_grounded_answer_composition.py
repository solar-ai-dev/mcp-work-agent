"""Execute the production Planning graph with only semantic inference faked."""

from __future__ import annotations

import json
from collections.abc import Mapping
from copy import deepcopy
from typing import cast

import pytest
from tests.support.graph_path_recorder import GraphPathRecorder

from google_work_agent.adapters.langgraph.subgraphs.planning.graph import (
    PlanningRuntimeDependencies,
    PlanningSubgraph,
)
from google_work_agent.application.agents.planning.contracts.planning_semantics import (
    PlanningSemanticInvoker,
)
from google_work_agent.application.prompt_runtime.load_prompt_input_contract import (
    load_prompt_input_contract,
)


@pytest.mark.parametrize("case", ["person", "event", "partial", "uncertain", "failure", "selected"])
def test_grounded_answer__production_graph__composes_instead_of_dumping_source(case: str) -> None:
    evidence = [
        {
            "evidence_id": "e1",
            "segment_id": "s1",
            "resource_handle": "gmail_message:m1",
            "excerpt": "Message ID: m1\nReceived: 2026-08-26T09:00:00+09:00\n연수는 9월 4일입니다.",
        }
    ]
    retrieval: dict[str, object] = {"coverage": "SUFFICIENT"}
    if case in {"person", "selected"}:
        retrieval["person_candidates"] = [
            {
                "mention": "김대리",
                "identity": "person@example.test",
                "source_segment_ids": ["s1"],
            }
        ]
    if case == "selected":
        retrieval["selected_person_identities"] = {"김대리": "person@example.test"}
        person_candidates = cast(list[dict[str, object]], retrieval["person_candidates"])
        person_candidates.append(
            {
                "mention": "김대리",
                "identity": "other@example.test",
                "source_segment_ids": ["s2"],
            }
        )
        evidence.append({"evidence_id": "e2", "segment_id": "s2", "excerpt": "다른 사람의 메일"})
    if case in {"event", "uncertain"}:
        retrieval["temporal_constraints"] = [
            {
                "kind": "TEMPORAL_RANGE",
                "axis": "EVENT_TIME",
                "timezone": "Asia/Seoul",
                "start_local": "2026-09-01T00:00:00",
                "end_local": "2026-09-08T00:00:00",
            }
        ]
    if case == "uncertain":
        retrieval["unresolved_event_dates"] = [{"evidence_id": "e1", "source_text": "9월 4일"}]
        retrieval["missing_information"] = [{"code": "person_identity", "description": "미확정"}]
    if case == "failure":
        retrieval["source_statuses"] = [
            {
                "route_id": "r1",
                "resource_type": "GMAIL_MESSAGE",
                "status": "FAILED",
                "failure_kind": "TIMEOUT",
                "evidence_refs": [],
            }
        ]
    if case in {"partial", "uncertain", "failure"}:
        retrieval["coverage"] = "PARTIAL"
    original_evidence = deepcopy(evidence)
    original_retrieval = deepcopy(retrieval)
    calls: list[str] = []

    def invoke(prompt_id: str, projection: Mapping[str, object]) -> Mapping[str, object]:
        load_prompt_input_contract().validate_projection(prompt_id, projection)
        calls.append(prompt_id)
        if prompt_id == "planning.outline_answer":
            return {
                "sections": ["자료"],
                "evidence_refs": [item["evidence_id"] for item in evidence],
            }
        assert prompt_id == "planning.compose_answer"
        assert projection["coverage"] == retrieval["coverage"]
        if case == "selected":
            assert projection["evidence"] == [evidence[0]]
            assert (
                projection["selected_person_identities"] == retrieval["selected_person_identities"]
            )
        return {
            "schema_version": 2,
            "answer": "연수 안내에는 9월 4일로 적혀 있습니다.",
            "evidence_refs": ["e1"],
        }

    recorder = GraphPathRecorder()
    graph = PlanningSubgraph(
        dependencies=PlanningRuntimeDependencies(invoke=cast(PlanningSemanticInvoker, invoke)),
    ).build()
    result = graph.invoke(
        {
            "user_request": "관련 자료에서 연수 날짜를 알려줘",
            "request_intent": {
                "goal": "연수 확인",
                "requested_effect_hints": ["READ"],
                "analysis_requirement": "NONE",
            },
            "tool_route_plan": {"output_plan": {"output_mode": "ANSWER", "output_routes": []}},
            "evidence": evidence,
            "retrieval_result": retrieval,
        },
        config={"callbacks": [recorder]},
    )
    nodes = [event["node"] for event in recorder.path]
    assert nodes == ["__start__", "outline_answer", "compose_answer"]
    assert calls == ["planning.outline_answer", "planning.compose_answer"]
    final = result["final_result"]
    assert final["schema_version"] == 2
    assert final["evidence_refs"] == ["e1"]
    assert "연수 안내에는 9월 4일" in final["answer"]
    assert "Message ID" not in final["answer"]
    assert "Received:" not in final["answer"]
    assert "2026년 9월 4일" not in final["answer"]
    assert "확인한 자료 원문" not in final["answer"]
    if retrieval["coverage"] == "PARTIAL":
        assert "부분 결과" in final["answer"]
    if case == "uncertain":
        assert "연도가 확정되지 않아" in final["answer"]
        assert "신원이 확정되지 않았습니다" in final["answer"]
    if case == "failure":
        assert "검색 결과가 없다는 뜻은 아닙니다" in final["answer"]
    assert evidence == original_evidence
    assert retrieval == original_retrieval
    print(
        json.dumps(
            {"case": case, "nodes": nodes, "prompts": calls, "final": final}, ensure_ascii=False
        )
    )
