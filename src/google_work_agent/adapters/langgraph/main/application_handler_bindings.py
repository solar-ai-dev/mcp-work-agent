"""Typed Application handler bindings consumed by the Main LangGraph runtime."""

from __future__ import annotations

from dataclasses import dataclass

from google_work_agent.application.use_cases.action.cancel_pending_action import (
    CancelPendingActionHandler,
)
from google_work_agent.application.use_cases.action.claim_read_action import (
    ClaimReadActionHandler,
)
from google_work_agent.application.use_cases.action.complete_read_action import (
    CompleteReadActionHandler,
)
from google_work_agent.application.use_cases.action.fail_read_action import FailReadActionHandler
from google_work_agent.application.use_cases.action.finalize_read_action import (
    FinalizeReadActionHandler,
)
from google_work_agent.application.use_cases.action.refresh_expired_action import (
    RefreshExpiredActionHandler,
)
from google_work_agent.application.use_cases.action.validate_action_arguments import (
    ValidateActionArgumentsHandler,
)
from google_work_agent.application.use_cases.approval.expire_approval import (
    ExpireApprovalHandler,
)
from google_work_agent.application.use_cases.claim.build_claim_context import (
    BuildClaimContextHandler,
)
from google_work_agent.application.use_cases.claim.claim_execution import (
    ClaimExecutionHandler,
)
from google_work_agent.application.use_cases.execution_attempt.abort_claimed_execution import (
    AbortClaimedExecutionHandler,
)
from google_work_agent.application.use_cases.execution_attempt.begin_execution_attempt import (
    BeginExecutionAttemptHandler,
)
from google_work_agent.application.use_cases.execution_attempt.classify_dispatch_result import (
    ClassifyDispatchResultHandler,
)
from google_work_agent.application.use_cases.execution_attempt.mark_failed import (
    MarkFailedHandler,
)
from google_work_agent.application.use_cases.execution_attempt.mark_unknown_result import (
    MarkUnknownResultHandler,
)
from google_work_agent.application.use_cases.execution_attempt.recover_existing_result import (
    RecoverExistingResultHandler,
)
from google_work_agent.application.use_cases.execution_attempt.resolve_as_failed import (
    ResolveAsFailedHandler,
)
from google_work_agent.application.use_cases.execution_attempt.store_success import (
    StoreSuccessHandler,
)
from google_work_agent.application.use_cases.plan.publish_plan import PublishPlanHandler
from google_work_agent.application.use_cases.plan.publish_read_only_plan import (
    PublishReadOnlyPlanHandler,
)
from google_work_agent.application.use_cases.plan.record_review_result import (
    RecordReviewResultHandler,
)
from google_work_agent.application.use_cases.plan.validate_plan_for_publication import (
    ValidatePlanForPublicationHandler,
)
from google_work_agent.application.use_cases.recovery.lookup_unknown_result import (
    LookupUnknownResultHandler,
)
from google_work_agent.application.use_cases.recovery.require_recovery import (
    RequireRecoveryHandler,
)
from google_work_agent.application.use_cases.recovery.resolve_recovery import (
    ResolveRecoveryHandler,
)
from google_work_agent.application.use_cases.resource_ref.persist_resource_ref import (
    PersistResourceRefHandler,
)
from google_work_agent.application.use_cases.resource_ref.resolve_resource_ref import (
    ResolveResourceRefHandler,
)
from google_work_agent.application.use_cases.run.begin_planning import BeginPlanningHandler
from google_work_agent.application.use_cases.run.begin_retrieval import BeginRetrievalHandler
from google_work_agent.application.use_cases.run.begin_verification import (
    BeginVerificationHandler,
)
from google_work_agent.application.use_cases.run.block_run import BlockRunHandler
from google_work_agent.application.use_cases.run.build_terminal_message import (
    BuildTerminalMessageHandler,
)
from google_work_agent.application.use_cases.run.complete_answer_only_run import (
    CompleteAnswerOnlyRunHandler,
)
from google_work_agent.application.use_cases.run.complete_read_only_run import (
    CompleteReadOnlyRunHandler,
)
from google_work_agent.application.use_cases.run.complete_write_run import (
    CompleteWriteRunHandler,
)
from google_work_agent.application.use_cases.run.continue_cancel_resolution import (
    ContinueCancelResolutionHandler,
)
from google_work_agent.application.use_cases.run.finalize_cancel import FinalizeCancelHandler
from google_work_agent.application.use_cases.run.get_run_snapshot import (
    GetRunSnapshotHandler,
)
from google_work_agent.application.use_cases.run.get_supervisor_observation import (
    GetSupervisorObservationHandler,
)
from google_work_agent.application.use_cases.run.request_confirmation import (
    RequestConfirmationHandler,
)
from google_work_agent.application.use_cases.run.require_reauth import RequireReauthHandler
from google_work_agent.application.use_cases.run.start_analysis import StartAnalysisHandler
from google_work_agent.application.use_cases.sse_event.project_run_event import (
    ProjectRunEventHandler,
)
from google_work_agent.application.use_cases.trace_event.emit_trace_event import (
    EmitTraceEventHandler,
)
from google_work_agent.application.use_cases.verification.store_verification import (
    StoreVerificationHandler,
)
from google_work_agent.application.use_cases.verification.verify_effect import (
    VerifyEffectHandler,
)


@dataclass(frozen=True, slots=True)
class RunLifecycleHandlerBindings:
    start_analysis: StartAnalysisHandler
    get_run_snapshot: GetRunSnapshotHandler
    get_supervisor_observation: GetSupervisorObservationHandler
    build_terminal_message: BuildTerminalMessageHandler
    emit_terminal_trace: EmitTraceEventHandler
    project_terminal_event: ProjectRunEventHandler | None
    begin_retrieval: BeginRetrievalHandler
    begin_planning: BeginPlanningHandler
    request_confirmation: RequestConfirmationHandler
    complete_answer_only: CompleteAnswerOnlyRunHandler
    complete_read_only_run: CompleteReadOnlyRunHandler
    complete_write_run: CompleteWriteRunHandler
    block_run: BlockRunHandler


@dataclass(frozen=True, slots=True)
class ReadExecutionHandlerBindings:
    domain_validation: ValidatePlanForPublicationHandler
    persist_resource_ref: PersistResourceRefHandler
    publish_read_plan: PublishReadOnlyPlanHandler
    claim_read: ClaimReadActionHandler
    complete_read: CompleteReadActionHandler
    finalize_read: FinalizeReadActionHandler
    fail_read: FailReadActionHandler


@dataclass(frozen=True, slots=True)
class WriteExecutionHandlerBindings:
    publish_write_plan: PublishPlanHandler
    build_claim_context: BuildClaimContextHandler
    begin_execution_attempt: BeginExecutionAttemptHandler
    abort_claimed_execution: AbortClaimedExecutionHandler
    classify_dispatch_result: ClassifyDispatchResultHandler
    expire_approval: ExpireApprovalHandler
    refresh_expired_action: RefreshExpiredActionHandler
    claim_execution: ClaimExecutionHandler
    store_write_success: StoreSuccessHandler
    mark_write_failed: MarkFailedHandler
    mark_write_unknown: MarkUnknownResultHandler


@dataclass(frozen=True, slots=True)
class VerificationRecoveryHandlerBindings:
    verify_effect: VerifyEffectHandler
    store_verification: StoreVerificationHandler
    require_recovery: RequireRecoveryHandler
    resolve_recovery: ResolveRecoveryHandler
    require_write_reauth: RequireReauthHandler
    lookup_unknown_result: LookupUnknownResultHandler
    recover_existing_result: RecoverExistingResultHandler
    resolve_as_failed: ResolveAsFailedHandler
    begin_write_verification: BeginVerificationHandler
    resolve_resource_ref: ResolveResourceRefHandler


@dataclass(frozen=True, slots=True)
class WorkflowControlHandlerBindings:
    cancel_pending_action: CancelPendingActionHandler
    finalize_cancel: FinalizeCancelHandler
    continue_cancel_resolution: ContinueCancelResolutionHandler
    record_review_result: RecordReviewResultHandler
    validate_action_arguments: ValidateActionArgumentsHandler


@dataclass(frozen=True, slots=True)
class WorkflowApplicationHandlerBindings:
    """Non-owning typed transfer object for handlers assembled at the composition root."""

    run_lifecycle: RunLifecycleHandlerBindings
    read_execution: ReadExecutionHandlerBindings
    write_execution: WriteExecutionHandlerBindings
    verification_recovery: VerificationRecoveryHandlerBindings
    workflow_control: WorkflowControlHandlerBindings


__all__ = [
    "ReadExecutionHandlerBindings",
    "RunLifecycleHandlerBindings",
    "VerificationRecoveryHandlerBindings",
    "WorkflowApplicationHandlerBindings",
    "WorkflowControlHandlerBindings",
    "WriteExecutionHandlerBindings",
]
