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
                    "schema_version": 2,
                    "meta": {"artifact_id": "plan", "revision": 2, "based_on": []},
                    "actions": [
                        {
                            "arguments": {
                                "task_list_id": "list",
                                "payload": {
                                    "title": "새 계획",
                                    "scheduled_date": "2026-09-10",
                                    "status": "needsAction",
                                    "location": "회의실 A",
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
    assert {"새 계획", "2026-09-10", "needsAction", "회의실 A"} <= set(values)
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
                    "schema_version": 1,
                    "meta": {"artifact_id": "retrieval", "revision": 1, "based_on": []},
                    "coverage": "PARTIAL",
                    "evidence_refs": ["e1"],
                    "source_resource_refs": ["s1"],
                    "source_statuses": [{"status": "FAILED", "failure_kind": "TIMEOUT"}],
                    "missing_information": [],
                },
                "__context_query_attempts__": [
                    {"operation_kind": "SEARCH", "candidate_count": 4},
                    {
                        "operation_kind": "DETAIL_FETCH",
                        "candidate_count": 1,
                        "stop_reason": "COMPLETE",
                    },
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


def test_record_activity__completed_semantic_step__uses_observed_value() -> None:
    emit = Mock()
    handler = RecordRunActivityHandler(
        emit_trace=emit, now_ms=lambda: 7, service_instance_id="test"
    )
    handler(
        RecordRunActivityCommand(
            "run",
            "retrieval:task",
            "request_understanding",
            "STEP_END",
            {"goal_candidate": {"goal": "분기 보고서를 정리한다"}},
            detail=("identify_goal", "요청 목적", "요청 목적을 확인했습니다."),
        )
    )
    attrs = emit.call_args.args[0].attributes
    assert attrs["state"] == "RUNNING"
    assert attrs["details"] == []
    assert attrs["detail_updates"] == [
        {
            "fact_id": attrs["detail_updates"][0]["fact_id"],
            "state": "RECORDED",
            "label": "요청 업무",
            "value": "분기 보고서를 정리한다",
            "occurred_at_ms": 7,
        }
    ]
    assert len(attrs["detail_updates"][0]["fact_id"]) == 64


def test_record_activity__no_op_ambiguity_step__emits_no_child_fact() -> None:
    emit = Mock()
    handler = RecordRunActivityHandler(
        emit_trace=emit, now_ms=lambda: 7, service_instance_id="test"
    )

    handler(
        RecordRunActivityCommand(
            "run",
            "request:task",
            "request_understanding",
            "STEP_END",
            {
                "ambiguity_candidate": {
                    "requires_confirmation": False,
                    "reason_codes": [],
                    "missing_fields": [],
                }
            },
            detail=("detect_ambiguity", "필요한 사용자 결정", "확인했습니다."),
        )
    )

    assert emit.call_count == 0


def test_record_activity__query_rejection__preserves_specific_safe_cause() -> None:
    emit = Mock()
    handler = RecordRunActivityHandler(
        emit_trace=emit, now_ms=lambda: 7, service_instance_id="test"
    )

    handler(
        RecordRunActivityCommand(
            "run",
            "retrieval:task",
            "context_retriever",
            "STEP_END",
            {
                "__context_agent_local__": {
                    "failure_record": {
                        "reason_code": "QUERY_USER_CONSTRAINT_MISSING",
                        "diagnostic": "CHANGED SEARCH changes protected STATUS_SCOPE anchor",
                    }
                }
            },
            detail=("build_query", "검색 조건 검증", "검색 조건의 연속성을 확인했습니다."),
        )
    )

    update = emit.call_args.args[0].attributes["detail_updates"][0]
    assert update["label"] == "검색 변경 거절 원인"
    assert "QUERY_USER_CONSTRAINT_MISSING" in update["value"]
    assert "STATUS_SCOPE" in update["value"]


def test_record_activity__request_and_route_artifacts__preserve_values_and_roles() -> None:
    emit = Mock()
    handler = RecordRunActivityHandler(
        emit_trace=emit, now_ms=lambda: 1, service_instance_id="test"
    )
    meta = {"artifact_id": "a", "revision": 1, "based_on": []}
    handler(
        RecordRunActivityCommand(
            "run",
            "stage:task",
            "stage_one",
            "END",
            {
                "request_intent": {
                    "schema_version": 2,
                    "meta": meta,
                    "goal": "고객에게 검토 메일을 보낸다",
                    "completion_conditions": ["검토 메일 전송 준비"],
                    "requested_effect_hints": ["READ", "SEND"],
                    "requested_resource_hints": ["GMAIL_MESSAGE"],
                    "constraints": [
                        {
                            "kind": "EMAIL",
                            "field": "recipient",
                            "value": "bonggyulim0728@gmail.com",
                            "provenance": {"source": "USER_REQUEST"},
                        }
                    ],
                    "ambiguity": {
                        "requires_confirmation": False,
                        "reason_codes": [],
                        "missing_fields": [],
                    },
                },
                "tool_route_plan": {
                    "schema_version": 2,
                    "tool_registry_version": "test",
                    "input_plan": {
                        "schema_version": 1,
                        "meta": meta,
                        "input_routes": [
                            {"connector_id": "google_workspace", "resource_type": "GMAIL_MESSAGE"}
                        ],
                    },
                    "output_plan": {
                        "schema_version": 1,
                        "meta": meta,
                        "output_mode": "ACTION",
                        "output_routes": [
                            {
                                "connector_id": "google_workspace",
                                "resource_type": "GMAIL_MESSAGE",
                                "effect": "SEND",
                            }
                        ],
                    },
                },
            },
        )
    )

    details = emit.call_args.args[0].attributes["details"]
    assert {item["value"] for item in details} >= {
        "고객에게 검토 메일을 보낸다",
        "bonggyulim0728@gmail.com",
        "Google Workspace · Gmail Message",
        "Google Workspace · Gmail Message · 전송",
    }
    assert any(item["label"] == "사용자 요청 · 받는 사람" for item in details)


def test_record_activity__retrieval_outcomes__do_not_conflate_no_fetch_zero_and_failure() -> None:
    emit = Mock()
    handler = RecordRunActivityHandler(
        emit_trace=emit, now_ms=lambda: 1, service_instance_id="test"
    )
    base = {
        "schema_version": 1,
        "meta": {"artifact_id": "r", "revision": 1, "based_on": []},
        "evidence_refs": [],
        "source_resource_refs": [],
        "missing_information": [],
    }
    for namespace, retrieval in (
        (
            "no-fetch",
            {**base, "coverage": "NO_FETCH_NEEDED", "source_statuses": []},
        ),
        (
            "zero",
            {
                **base,
                "coverage": "PARTIAL",
                "source_statuses": [{"status": "COMPLETE", "failure_kind": None}],
            },
        ),
        (
            "failed",
            {
                **base,
                "coverage": "PARTIAL",
                "source_statuses": [{"status": "FAILED", "failure_kind": "TIMEOUT"}],
            },
        ),
    ):
        handler(
            RecordRunActivityCommand(
                "run",
                namespace,
                "context_retriever",
                "END",
                {"retrieval_result": retrieval},
            )
        )

    values = [
        [item["value"] for item in call.args[0].attributes["details"]]
        for call in emit.call_args_list
    ]
    assert values[0] == ["이 요청에는 업무 자료 조회가 필요하지 않았습니다."]
    assert values[1] == ["허용된 조회 범위에서 조건에 맞는 자료가 없었습니다."]
    assert values[2] == ["조회 시간 초과"]


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
                "planning_result": {
                    "schema_version": 2,
                    "meta": {"artifact_id": "invalid", "revision": 1, "based_on": []},
                    "answer": "UNVALIDATED",
                },
            },
        )
    )
    attrs = emit.call_args.args[0].attributes
    assert attrs["details"] == []
    assert attrs["state"] == "RECORDED"
    assert "업무 결과는 Run 상태에서 별도로 확인합니다" in attrs["label"]
    handler(RecordRunActivityCommand("run", "tool:task", "provider_tool", "END", {}))
    assert emit.call_count == 1
