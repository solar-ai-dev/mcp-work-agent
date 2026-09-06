"""Activity uses validated output fields, not a second inference path."""

from unittest.mock import Mock

from google_work_agent.application.use_cases.trace_event.record_run_activity import (
    RecordRunActivityCommand,
    RecordRunActivityHandler,
)


def test_record_activity__selects_plan_fields__without_raw_body_or_authority() -> None:
    emit = Mock()
    handler = RecordRunActivityHandler(
        emit_trace=emit, now_ms=lambda: 1, service_instance_id="test"
    )
    handler(
        RecordRunActivityCommand(
            "run",
            "planning:task",
            "planning",
            "END",
            {
                "planning_result": {
                    "meta": {"revision": 2},
                    "actions": [
                        {
                            "arguments": {
                                "task_list_id": "list",
                                "payload": {
                                    "title": "새 계획",
                                    "scheduled_date": "2026-09-10",
                                    "notes": "PRIVATE BODY",
                                    "access_token": "SECRET",
                                },
                            }
                        }
                    ],
                },
                "raw_prompt": "PRIVATE PROMPT",
                "execution_summary": {"success": True},
            },
        )
    )
    command = emit.call_args.args[0]
    values = [item["value"] for item in command.attributes["details"]]
    assert "새 계획" in values and "2026-09-10" in values
    assert "PRIVATE" not in str(command.attributes) and "SECRET" not in str(command.attributes)
    assert command.attributes["state"] == "RECORDED"
    assert "성공" not in command.attributes["label"]
    assert emit.call_count == 1


def test_record_activity__distinguishes_partial__without_debug_counts() -> None:
    emit = Mock()
    handler = RecordRunActivityHandler(
        emit_trace=emit, now_ms=lambda: 1, service_instance_id="test"
    )
    handler(
        RecordRunActivityCommand(
            "run",
            "retrieval:task",
            "context_retriever",
            "END",
            {
                "retrieval_result": {
                    "meta": {"revision": 1},
                    "coverage": "PARTIAL",
                    "evidence_refs": ["e1"],
                    "source_resource_refs": ["s1"],
                    "source_statuses": [{"status": "FAILED", "failure_kind": "TIMEOUT"}],
                },
                "__context_query_attempts__": [
                    {"operation_kind": "SEARCH", "candidate_count": 4},
                    {"operation_kind": "DETAIL_FETCH", "candidate_count": 1},
                    {"operation_kind": "DETAIL_FETCH", "candidate_count": None},
                ],
            },
        )
    )
    attrs = emit.call_args.args[0].attributes
    assert attrs["state"] == "PARTIAL"
    details = {item["label"]: item["value"] for item in attrs["details"]}
    assert details["조회 범위"] == "후보의 상세 내용을 확인했습니다."
    assert "결과 revision" not in details
    assert "선택 근거 수" not in details
    assert "검색 반환 후보 합계" not in str(details)
    assert "취소" not in str(attrs)


def test_record_activity__records_observed_step__before_parent_completion() -> None:
    emit = Mock()
    handler = RecordRunActivityHandler(
        emit_trace=emit, now_ms=lambda: 7, service_instance_id="test"
    )
    handler(
        RecordRunActivityCommand(
            "run",
            "retrieval:task",
            "context_retriever",
            "STEP_START",
            {},
            detail=("execute_read", "자료 조회", "자료를 확인 중입니다."),
        )
    )
    attrs = emit.call_args.args[0].attributes
    assert attrs["state"] == "RUNNING"
    assert attrs["details"] == []
    assert attrs["detail_updates"] == [
        {
            "fact_id": attrs["detail_updates"][0]["fact_id"],
            "state": "RUNNING",
            "label": "자료 조회",
            "value": "자료를 확인 중입니다.",
            "occurred_at_ms": 7,
        }
    ]
    assert len(attrs["detail_updates"][0]["fact_id"]) == 64


def test_record_activity__ignores_unvalidated_and_unknown__artifacts() -> None:
    emit = Mock()
    handler = RecordRunActivityHandler(
        emit_trace=emit, now_ms=lambda: 1, service_instance_id="test"
    )
    handler(
        RecordRunActivityCommand(
            "run",
            "planning:task",
            "planning",
            "END",
            {
                "planning_result": {"answer": "UNVALIDATED"},
            },
        )
    )
    attrs = emit.call_args.args[0].attributes
    assert attrs["details"] == []
    assert attrs["state"] == "RECORDED"
    assert "업무 결과는 Run 상태에서 별도로 확인합니다" in attrs["label"]
    handler(RecordRunActivityCommand("run", "tool:task", "provider_tool", "END", {}))
    assert emit.call_count == 1
