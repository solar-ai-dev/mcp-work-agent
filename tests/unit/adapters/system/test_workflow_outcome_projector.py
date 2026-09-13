from typing import cast

from google_work_agent.adapters.system.workflow_outcome_projector import (
    WorkflowOutcomeProjector,
)
from google_work_agent.application.use_cases.recovery.project_recovery_options import (
    ProjectRecoveryOptionsResultV1,
)
from google_work_agent.application.use_cases.recovery.require_recovery import (
    RequireRecoveryCommand,
    RequireRecoveryHandler,
)
from google_work_agent.application.use_cases.sse_event.project_run_event import (
    ProjectRunEventCommand,
    ProjectRunEventHandler,
)
from google_work_agent.domain.canonical import calculate_canonical_json_hash
from google_work_agent.ports.system.contracts.workflow_execution import WorkflowOutcome


class _AppliedRecovery:
    applied = True
    conflict_detail = None


def _record_recovery(
    commands: list[RequireRecoveryCommand],
    command: RequireRecoveryCommand,
) -> _AppliedRecovery:
    commands.append(command)
    return _AppliedRecovery()


def test_waiting_approval_without_action_projection__publishes_run_status__for_snapshot_refresh(
) -> None:
    published: list[ProjectRunEventCommand] = []
    projector = WorkflowOutcomeProjector(
        require_recovery=lambda _command: None,  # type: ignore[arg-type]
        project_run_event=published.append,  # type: ignore[arg-type]
        now_ms=lambda: 10,
        id_factory=lambda: "event-1",
        recovery_target=lambda _run_id: None,
        project_recovery_options=lambda _query: ProjectRecoveryOptionsResultV1(
            "VERIFICATION_MISMATCH",
            "Google에서 확인한 결과가 요청과 다릅니다.",
            {"target_kind": "ACTION", "action_id": "action-1"},
            ("RECHECK", "ACCEPT_PARTIAL", "FAIL"),
        ),
    )

    projector.handle_result(
        "run-1",
        WorkflowOutcome.ACCEPTED,
        {
            "phase": "WAITING_APPROVAL",
            "run_status": "WAITING_APPROVAL",
            "user_interrupt": {
                "interrupt_kind": "APPROVAL",
                "run_id": "run-1",
                "plan_id": "plan-1",
            },
        },
        4,
    )

    assert len(published) == 1
    event = published[0]
    assert event.event_type == "run_status"
    assert event.payload == {
        "status": "WAITING_APPROVAL",
        "snapshot_version": 4,
    }


def test_recovery_outcome__publishes_domain_backed__canonical_recovery_event() -> None:
    published: list[ProjectRunEventCommand] = []
    projector = WorkflowOutcomeProjector(
        require_recovery=lambda _command: None,  # type: ignore[arg-type]
        project_run_event=published.append,  # type: ignore[arg-type]
        now_ms=lambda: 10,
        id_factory=lambda: "event-1",
        recovery_target=lambda _run_id: None,
        project_recovery_options=lambda _query: ProjectRecoveryOptionsResultV1(
            "VERIFICATION_MISMATCH",
            "Google에서 확인한 결과가 요청과 다릅니다.",
            {"target_kind": "ACTION", "action_id": "action-1"},
            ("RECHECK", "ACCEPT_PARTIAL", "CREATE_CORRECTIVE_PLAN", "FAIL"),
        ),
    )

    projector.handle_result(
        "run-1",
        WorkflowOutcome.RECOVERY_REQUIRED,
        {"run_status": "RECOVERY_REQUIRED"},
        5,
    )

    assert len(published) == 1
    assert published[0].event_type == "recovery_required"
    assert published[0].payload == {
        "recovery": {
            "reason_code": "VERIFICATION_MISMATCH",
            "message": "Google에서 확인한 결과가 요청과 다릅니다.",
            "target": {"target_kind": "ACTION", "action_id": "action-1"},
            "allowed_resolution_kinds": [
                "RECHECK",
                "ACCEPT_PARTIAL",
                "CREATE_CORRECTIVE_PLAN",
                "FAIL",
            ],
        }
    }


def test_contract_violation_outcome__requires_recovery__and_publishes_recovery_state() -> None:
    published: list[ProjectRunEventCommand] = []
    recovery_commands: list[RequireRecoveryCommand] = []
    projector = WorkflowOutcomeProjector(
        require_recovery=cast(
            RequireRecoveryHandler,
            lambda command: _record_recovery(recovery_commands, command),
        ),
        project_run_event=cast(ProjectRunEventHandler, published.append),
        now_ms=lambda: 10,
        id_factory=lambda: "command-1",
        recovery_target=lambda _run_id: None,
        project_recovery_options=lambda _query: ProjectRecoveryOptionsResultV1(
            "CONTRACT_VIOLATION",
            "안전한 실행 조건을 확인하지 못해 작업을 중단했습니다.",
            {"target_kind": "RUN"},
            ("RECHECK", "FAIL"),
        ),
    )

    projector.handle_result(
        "run-1",
        WorkflowOutcome.CONTRACT_VIOLATION,
        {"safe_error_code": "PROMPT_NOT_ACTIVE"},
        7,
    )

    assert len(recovery_commands) == 1
    command = recovery_commands[0]
    assert command.reason == "CONTRACT_VIOLATION"
    assert command.expected_version == 7
    assert command.recovery_fingerprint == calculate_canonical_json_hash(
        {
            "run_id": "run-1",
            "expected_version": 7,
            "reason": "CONTRACT_VIOLATION",
            "failure_classification": "PROMPT_NOT_ACTIVE",
        }
    )
    assert [event.event_type for event in published] == ["recovery_required"]


def test_unclassified_failed_outcome__is_a_contract_defect__not_a_failure_reason_alias() -> None:
    published: list[ProjectRunEventCommand] = []
    recovery_commands: list[RequireRecoveryCommand] = []
    projector = WorkflowOutcomeProjector(
        require_recovery=cast(
            RequireRecoveryHandler,
            lambda command: _record_recovery(recovery_commands, command),
        ),
        project_run_event=cast(ProjectRunEventHandler, published.append),
        now_ms=lambda: 10,
        id_factory=lambda: "command-1",
        recovery_target=lambda _run_id: None,
        project_recovery_options=lambda _query: ProjectRecoveryOptionsResultV1(
            "CONTRACT_VIOLATION",
            "안전한 실행 조건을 확인하지 못해 작업을 중단했습니다.",
            {"target_kind": "RUN"},
            ("RECHECK", "FAIL"),
        ),
    )

    projector.handle_result(
        "run-1",
        WorkflowOutcome.FAILED,
        {"error_code": "INTERNAL_ERROR"},
        4,
    )

    assert len(recovery_commands) == 1
    assert recovery_commands[0].recovery_fingerprint == calculate_canonical_json_hash(
        {
            "run_id": "run-1",
            "expected_version": 4,
            "reason": "CONTRACT_VIOLATION",
            "failure_classification": "MISSING_FAILURE_CLASSIFICATION",
        }
    )
    assert [event.event_type for event in published] == ["recovery_required"]
