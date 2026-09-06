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


def test_record_activity__distinguishes_partial__and_query_counts() -> None:
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
    assert details["선택 근거 수"] == "1"
    assert details["현재까지 검색 반환 후보 합계 (중복 포함)"] == "4"
    assert details["현재까지 완료한 상세 조회 수"] == "1"
    assert "취소" not in str(attrs)


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
    assert emit.call_args.args[0].attributes["details"] == []
    handler(RecordRunActivityCommand("run", "tool:task", "provider_tool", "END", {}))
    assert emit.call_count == 1
