"""Stored projection paging, immutable execution details and audit precedence."""

from json import dumps
from unittest.mock import Mock

from google_work_agent.application.use_cases.run.project_run_activity import (
    ProjectRunActivityHandler,
)
from google_work_agent.ports.persistence.audit_event_repository import PersistedAuditEventRecord
from google_work_agent.ports.persistence.trace_event_repository import PersistedTraceEventRecord


def test_activity__restores_all_pages__without_replaying_io() -> None:
    events = [
        PersistedTraceEventRecord(
            id=i + 1,
            run_id="r",
            action_id=None,
            event_type="RUN_ACTIVITY_OBSERVED",
            status=None,
            duration_ms=None,
            created_at_ms=i,
            payload_json=dumps(
                {
                    "schema_version": 1,
                    "execution_id": f"{i:064x}",
                    "role": "계획 생성",
                    "state": "RECORDED",
                    "label": "기록됨",
                    "details": [{"label": "제목", "value": f"계획{i}"}],
                }
            ),
        )
        for i in range(510)
    ]
    uow = Mock()
    uow.traces.list_page.side_effect = lambda cursor, limit: tuple(
        events[cursor.after_id : cursor.after_id + limit]
    )
    uow.audits.list_page.return_value = ()
    first = ProjectRunActivityHandler()(uow, "r", run_status="COMPLETED")
    second = ProjectRunActivityHandler()(uow, "r", run_status="COMPLETED")
    assert first == second
    assert len(first["rows"]) == 510
    assert first["rows"][0]["details"][0]["value"] == "계획0"
    assert first["rows"][-1]["sequence"] == 510
    assert set(call[0] for call in uow.mock_calls) == {"traces.list_page", "audits.list_page"}


def test_activity__ignores_replay_regression__and_cross_run_events() -> None:
    events = []
    for i, (run_id, state, value) in enumerate(
        [
            ("r", "RUNNING", ""),
            ("r", "WAITING", ""),
            ("r", "RUNNING", ""),
            ("r", "RECORDED", "old revision"),
            ("r", "RUNNING", ""),
            ("r", "RECORDED", "new revision"),
            ("r", [], "malformed state"),
            ("other", "RECORDED", "wrong run"),
        ]
    ):
        events.append(
            PersistedTraceEventRecord(
                i + 1,
                run_id,
                None,
                "RUN_ACTIVITY_OBSERVED",
                None,
                None,
                dumps(
                    {
                        "schema_version": 1,
                        "execution_id": "a" * 64,
                        "role": "計画" if run_id == "other" else "계획 생성",
                        "state": state,
                        "label": "기록",
                        "details": [{"label": "제목", "value": value}],
                    }
                ),
                i,
            )
        )
    uow = Mock()
    uow.traces.list_page.return_value = tuple(events)
    uow.audits.list_page.return_value = ()
    result = ProjectRunActivityHandler()(uow, "r", run_status="COMPLETED")
    assert len(result["rows"]) == 1
    assert result["rows"][0]["state"] == "RECORDED"
    assert result["rows"][0]["details"][0]["value"] == "old revision"


def test_activity__accumulates_observed_facts__and_updates_same_step_in_place() -> None:
    fact_a, fact_b = "a" * 64, "b" * 64
    events = []
    for event_id, updates in enumerate(
        [
            [
                {
                    "fact_id": fact_a,
                    "state": "RUNNING",
                    "label": "자료 조회",
                    "value": "자료를 확인하고 있습니다.",
                    "occurred_at_ms": 2,
                }
            ],
            [
                {
                    "fact_id": fact_a,
                    "state": "RECORDED",
                    "label": "자료 조회",
                    "value": "자료 확인을 마쳤습니다.",
                    "occurred_at_ms": 3,
                }
            ],
            [
                {
                    "fact_id": fact_b,
                    "state": "RECORDED",
                    "label": "자료 조회",
                    "value": "자료 확인을 마쳤습니다.",
                    "occurred_at_ms": 4,
                }
            ],
        ],
        start=1,
    ):
        events.append(
            PersistedTraceEventRecord(
                event_id,
                "r",
                None,
                "RUN_ACTIVITY_OBSERVED",
                None,
                None,
                dumps(
                    {
                        "schema_version": 1,
                        "execution_id": "c" * 64,
                        "role": "자료 검색",
                        "state": "RUNNING",
                        "label": "처리하고 있습니다.",
                        "details": [],
                        "detail_updates": updates,
                    }
                ),
                event_id,
            )
        )
    events.append(
        PersistedTraceEventRecord(
            4,
            "r",
            None,
            "RUN_ACTIVITY_OBSERVED",
            None,
            None,
            dumps(
                {
                    "schema_version": 1,
                    "execution_id": "c" * 64,
                    "role": "자료 검색",
                    "state": "RECORDED",
                    "label": "자료 조회 결과를 정리했습니다.",
                    "details": [{"label": "조회 결과", "value": "관련 자료를 확인했습니다."}],
                    "detail_updates": [],
                }
            ),
            5,
        )
    )
    uow = Mock()
    uow.traces.list_page.return_value = tuple(events)
    uow.audits.list_page.return_value = ()

    row = ProjectRunActivityHandler()(uow, "r", run_status="COMPLETED")["rows"][0]

    assert row["state"] == "RECORDED"
    assert [detail.get("fact_id") for detail in row["details"]] == [fact_a, fact_b, None]
    assert row["details"][0]["state"] == "RECORDED"
    assert row["details"][0]["occurred_at_ms"] == 3
    assert row["details"][1]["occurred_at_ms"] == 4
    assert row["details"][2] == {"label": "조회 결과", "value": "관련 자료를 확인했습니다."}


def test_activity__does_not_present_unconfirmed_running_row__after_worker_stops() -> None:
    event = PersistedTraceEventRecord(
        1,
        "r",
        None,
        "RUN_ACTIVITY_OBSERVED",
        None,
        None,
        dumps(
            {
                "schema_version": 1,
                "execution_id": "a" * 64,
                "role": "자료 검색",
                "state": "RUNNING",
                "label": "처리하고 있습니다.",
                "details": [],
            }
        ),
        1,
    )
    uow = Mock()
    uow.traces.list_page.return_value = (event,)
    uow.audits.list_page.return_value = ()

    active = ProjectRunActivityHandler()(uow, "r", run_status="RETRIEVING", is_run_active=True)[
        "rows"
    ][0]
    stale = ProjectRunActivityHandler()(uow, "r", run_status="RETRIEVING", is_run_active=False)[
        "rows"
    ][0]

    assert active["state"] == "RUNNING"
    assert stale["state"] == "UNKNOWN"
    assert "현재 실행 중임을 확인할 수 없습니다" in stale["label"]


def test_activity__uses_committed_audit__for_unknown_and_verification() -> None:
    uow = Mock()
    uow.traces.list_page.return_value = ()
    uow.audits.list_page.return_value = tuple(
        PersistedAuditEventRecord(
            i + 1,
            None,
            "r",
            None,
            "SYSTEM",
            "test",
            None,
            name,
            "TRANSITION_APPLIED",
            dumps({"attempt_id": "attempt", "verification_id": "v"}),
            i,
        )
        for i, name in enumerate(
            ["EXECUTION_DISPATCH_STARTED", "WRITE_UNKNOWN_RESULT", "VERIFICATION_MISMATCH"]
        )
    )
    result = ProjectRunActivityHandler()(uow, "r", run_status="RECOVERY_REQUIRED")
    assert len(result["rows"]) == 2
    assert result["rows"][0]["state"] == "UNKNOWN"
    assert result["rows"][1]["state"] == "PARTIAL"
    assert "일치합니다" not in str(result)


def test_activity__updates_existing_wait__from_committed_reauth_and_recovery_resolution() -> None:
    uow = Mock()
    uow.traces.list_page.return_value = ()
    uow.audits.list_page.return_value = tuple(
        PersistedAuditEventRecord(
            i + 1,
            None,
            "r",
            None,
            "SYSTEM",
            "test",
            None,
            name,
            "TRANSITION_APPLIED",
            dumps({"resolution": "ACCEPT_PARTIAL"}),
            i,
        )
        for i, name in enumerate(
            [
                "RUN_REAUTH_REQUIRED",
                "RUN_REAUTH_RESUMED",
                "RECOVERY_REQUIRED",
                "RECOVERY_RESOLVED",
            ]
        )
    )
    rows = ProjectRunActivityHandler()(uow, "r", run_status="COMPLETED")["rows"]
    assert len(rows) == 2
    assert all(row["state"] == "RECORDED" for row in rows)
    assert rows[0]["started_at_ms"] == 0 and rows[0]["updated_at_ms"] == 1
    assert rows[1]["details"] == [{"label": "복구 결정", "value": "확인된 부분 결과 수용"}]
    assert "성공" not in str(rows)


def test_activity__projects_cancellation_once__without_duplicate_workflow_observation() -> None:
    uow = Mock()
    uow.traces.list_page.return_value = (
        PersistedTraceEventRecord(
            1,
            "r",
            None,
            "RUN_ACTIVITY_OBSERVED",
            None,
            None,
            dumps(
                {
                    "schema_version": 1,
                    "execution_id": "a" * 64,
                    "role": "중단 처리",
                    "state": "RECORDED",
                    "label": "처리 종료",
                    "details": [],
                }
            ),
            1,
        ),
    )
    uow.audits.list_page.return_value = (
        PersistedAuditEventRecord(
            1,
            None,
            "r",
            None,
            "SYSTEM",
            "test",
            None,
            "RUN_CANCELLED",
            "TRANSITION_APPLIED",
            "{}",
            2,
        ),
    )
    rows = ProjectRunActivityHandler()(uow, "r", run_status="CANCELLED")["rows"]
    assert len(rows) == 1
    assert rows[0]["role"] == "작업 중단"
    assert rows[0]["state"] == "INTERRUPTED"
    assert "이미 발생한 외부 변경은 취소되지 않습니다" in rows[0]["label"]
