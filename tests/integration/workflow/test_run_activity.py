"""Observe real LangGraph task identities across interrupt/resume and a back-edge."""

from pathlib import Path
from typing import TypedDict
from unittest.mock import Mock

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt

from google_work_agent.adapters.langgraph.activity_callback import RunActivityCallback
from google_work_agent.application.use_cases.trace_event.record_run_activity import (
    RecordRunActivityHandler,
)


class ActivityGraphState(TypedDict):
    run_id: str
    round: int


def test_graph_activity__preserves_task_identity__through_resume_and_back_edge() -> None:
    emit = Mock()
    callback = RunActivityCallback(
        RecordRunActivityHandler(emit_trace=emit, now_ms=lambda: 1, service_instance_id="test")
    )

    def retrieve(state: ActivityGraphState) -> dict[str, int]:
        interrupt("continue")
        return {"round": state["round"] + 1}

    builder = StateGraph(ActivityGraphState)
    builder.add_node("context_retriever", retrieve)
    builder.add_edge(START, "context_retriever")
    builder.add_conditional_edges(
        "context_retriever", lambda state: END if state["round"] == 2 else "context_retriever"
    )
    graph = builder.compile(checkpointer=InMemorySaver())
    config = {"configurable": {"thread_id": "r"}, "callbacks": [callback]}
    graph.invoke({"run_id": "r", "round": 0}, config=config)
    before = [call.args[0].attributes for call in emit.call_args_list]
    assert [item["state"] for item in before] == ["RUNNING", "WAITING"]
    assert len({item["execution_id"] for item in before}) == 1
    graph.invoke(Command(resume="yes"), config=config)
    graph.invoke(Command(resume="yes"), config=config)
    after = [call.args[0].attributes for call in emit.call_args_list]
    ids = list(dict.fromkeys(item["execution_id"] for item in after))
    assert len(ids) == 2
    assert [item["state"] for item in after if item["execution_id"] == ids[0]] == [
        "RUNNING",
        "WAITING",
        "RUNNING",
        "RECORDED",
    ]
    assert graph.get_state(config).values["round"] == 2


def test_graph_activity__does_not_break_execution__when_trace_is_unavailable() -> None:
    record = Mock(side_effect=RuntimeError("unavailable"))
    builder = StateGraph(ActivityGraphState)
    builder.add_node("planning", lambda state: {"round": 1})
    builder.add_edge(START, "planning")
    builder.add_edge("planning", END)
    result = builder.compile().invoke(
        {"run_id": "r", "round": 0}, config={"callbacks": [RunActivityCallback(record)]}
    )
    assert result["round"] == 1


def test_product_graph_activity__retains_old_plan__after_modify_and_verified_write(
    tmp_path: Path,
) -> None:
    from scripts.measure_tasks_write import measure

    measurement = measure("modify", tmp_path)
    assert measurement["measurement_status"] == "PASS"
    assert measurement["writes_before_approval"] == 0
    rows = measurement["final"]["activity"]["rows"]
    roles = [row["role"] for row in rows]
    assert roles == [
        "요청 분석",
        "자료 경로 선택",
        "자료 검색",
        "업무 분석",
        "계획 생성",
        "계획 검토",
        "승인 대기",
        "계획 검토",
        "승인 대기",
        "사용자 승인",
        "승인된 작업 실행",
        "결과 검증",
    ]
    assert len({row["execution_id"] for row in rows}) == len(rows)
    assert [row["sequence"] for row in rows] == list(range(1, len(rows) + 1))
    assert all(row["state"] == "RECORDED" for row in rows)
    old_plan = {item["label"]: item["value"] for item in rows[4]["details"]}
    approval = {item["label"]: item["value"] for item in rows[-3]["details"]}
    verified = {item["label"]: item["value"] for item in rows[-1]["details"]}
    assert old_plan["예정일"] == "2026-09-11"
    assert approval["승인 예정일"] == "2026-09-08"
    assert verified["기대 예정일"] == verified["재조회 예정일"] == "2026-09-08"
    assert measurement["stale_approval_status"] == 409
