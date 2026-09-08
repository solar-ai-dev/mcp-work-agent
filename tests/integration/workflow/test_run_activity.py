"""Observe real LangGraph task identities across interrupt/resume and a back-edge."""

import sqlite3
from pathlib import Path
from typing import Any, TypedDict
from unittest.mock import Mock

from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt

from google_work_agent.adapters.langgraph.activity_callback import RunActivityCallback
from google_work_agent.application.use_cases.trace_event.record_run_activity import (
    RecordRunActivityHandler,
)


class ActivityGraphState(TypedDict):
    run_id: str
    round: int


def test_graph_activity__records_completed_semantic_fact__before_agent_end() -> None:
    emit = Mock()
    callback = RunActivityCallback(
        RecordRunActivityHandler(emit_trace=emit, now_ms=lambda: 1, service_instance_id="test")
    )
    subgraph = StateGraph(ActivityGraphState)
    subgraph.add_node(
        "identify_goal",
        lambda state: {
            "round": state["round"] + 1,
            "goal_candidate": {"goal": "분기 보고서를 정리한다"},
        },
    )
    subgraph.add_edge(START, "identify_goal")
    subgraph.add_edge("identify_goal", END)
    graph = StateGraph(ActivityGraphState)
    graph.add_node("request_understanding", subgraph.compile())
    graph.add_edge(START, "request_understanding")
    graph.add_edge("request_understanding", END)

    graph.compile().invoke({"run_id": "r", "round": 0}, config={"callbacks": [callback]})

    observed = [call.args[0].attributes for call in emit.call_args_list]
    assert [item["state"] for item in observed] == [
        "RUNNING",
        "RUNNING",
        "RECORDED",
    ]
    assert len({item["execution_id"] for item in observed}) == 1
    assert [item["detail_updates"][0]["state"] for item in observed if item["detail_updates"]] == [
        "RECORDED",
    ]
    assert [item["detail_updates"][0]["label"] for item in observed if item["detail_updates"]] == [
        "요청 업무",
    ]
    assert [item["detail_updates"][0]["value"] for item in observed if item["detail_updates"]] == [
        "분기 보고서를 정리한다",
    ]


def test_graph_activity__preserves_parent_identity__across_restart_and_resume(
    tmp_path: Path,
) -> None:
    emit = Mock()

    def determine_io_resources(state: ActivityGraphState) -> dict[str, int]:
        interrupt("continue")
        return {"round": state["round"] + 1}

    def build(connection: sqlite3.Connection) -> tuple[Any, RunActivityCallback]:
        callback = RunActivityCallback(
            RecordRunActivityHandler(
                emit_trace=emit,
                now_ms=lambda: 1,
                service_instance_id="test",
            )
        )
        subgraph = StateGraph(ActivityGraphState)
        subgraph.add_node("determine_io_resources", determine_io_resources)
        subgraph.add_edge(START, "determine_io_resources")
        subgraph.add_edge("determine_io_resources", END)
        graph = StateGraph(ActivityGraphState)
        graph.add_node("tool_route", subgraph.compile())
        graph.add_edge(START, "tool_route")
        graph.add_edge("tool_route", END)
        return graph.compile(checkpointer=SqliteSaver(connection)), callback

    config: RunnableConfig = {"configurable": {"thread_id": "r"}}
    checkpoint_path = tmp_path / "activity-checkpoint.db"
    with sqlite3.connect(checkpoint_path, check_same_thread=False) as connection:
        compiled, callback = build(connection)
        config["callbacks"] = [callback]
        compiled.invoke({"run_id": "r", "round": 0}, config=config)
    with sqlite3.connect(checkpoint_path, check_same_thread=False) as connection:
        restarted, callback = build(connection)
        config["callbacks"] = [callback]
        restarted.invoke(Command(resume="yes"), config=config)

    observed = [call.args[0].attributes for call in emit.call_args_list]
    assert [item["state"] for item in observed] == [
        "RUNNING",
        "WAITING",
        "RUNNING",
        "RECORDED",
    ]
    assert all(item["detail_updates"] == [] for item in observed)
    assert len({item["execution_id"] for item in observed}) == 1


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
    config: RunnableConfig = {"configurable": {"thread_id": "r"}, "callbacks": [callback]}
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
    assert old_plan["실행안 1 · 예정일"] == "2026-09-11"
    assert approval["승인 예정일"] == "2026-09-08"
    assert approval["승인 대상 Task List"] == "task-list-e2e"
    assert verified["기대 예정일"] == verified["재조회 예정일"] == "2026-09-08"
    assert measurement["stale_approval_status"] == 409
