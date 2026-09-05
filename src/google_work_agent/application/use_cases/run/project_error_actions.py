"""Project deterministic Error UI actions from durable Run/Action facts."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

from google_work_agent.application.use_cases.execution_attempt.project_delivery_certainty import (
    project_latest_delivery_certainty,
)
from google_work_agent.application.use_cases.plan.persistence_projection import (
    current_plan_tuple,
)
from google_work_agent.application.use_cases.run.resume_confirmation import (
    ResumeTargetValidator,
)
from google_work_agent.application.use_cases.run.resume_safe_checkpoint import (
    safe_checkpoint_resume_is_allowed,
)
from google_work_agent.domain.action.model import ActionStatusV1
from google_work_agent.domain.run.model import RunStatusV1
from google_work_agent.ports.persistence.unit_of_work import UnitOfWork
from google_work_agent.ports.persistence.trace_event_repository import TraceEventCursor
from google_work_agent.ports.system.checkpoint_port import CheckpointPort

type ErrorUiActionKindV1 = Literal[
    "PREPARE_RETRY",
    "REAUTHENTICATE_GOOGLE",
    "REAUTHENTICATE_CONNECTOR",
    "RESUME_SAFE_CHECKPOINT",
    "OPEN_SETTINGS",
    "OPEN_DIAGNOSTICS",
]


@dataclass(frozen=True, slots=True)
class ProjectErrorActionsQueryV1:
    run_id: str


@dataclass(frozen=True, slots=True)
class ErrorUiActionV1:
    kind: ErrorUiActionKindV1
    action_id: str | None = None
    resume_kind: str | None = None
    connector_id: str | None = None


@dataclass(frozen=True, slots=True)
class ProjectErrorActionsResultV1:
    schema_version: int
    error_code: str
    message: str
    actions: tuple[ErrorUiActionV1, ...]


class ProjectErrorActionsHandler:
    def __init__(
        self,
        *,
        unit_of_work_factory: Callable[[], UnitOfWork],
        checkpoint_port: CheckpointPort,
        resume_target_registry: ResumeTargetValidator,
    ) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._checkpoint_port = checkpoint_port
        self._resume_target_registry = resume_target_registry

    def __call__(self, query: ProjectErrorActionsQueryV1) -> ProjectErrorActionsResultV1 | None:
        with self._unit_of_work_factory() as unit_of_work:
            run = unit_of_work.runs.get(query.run_id)
            if run is None:
                raise LookupError(f"run not found: {query.run_id}")
            plans = current_plan_tuple(unit_of_work.plans, run.id)
            plan = max(plans, key=lambda item: (item.revision_no, item.id), default=None)
            actions = () if plan is None else unit_of_work.actions.list_for_plan(plan.id)

            retry_actions = tuple(
                ErrorUiActionV1("PREPARE_RETRY", action_id=action.id)
                for action in actions
                if action.status == ActionStatusV1.FAILED.value
                and project_latest_delivery_certainty(unit_of_work, action.id) == "NOT_SENT"
            )
            if run.status is RunStatusV1.REAUTH_REQUIRED:
                latest_action_id = _latest_reauth_action_id(unit_of_work, run.id)
                affected_action = next(
                    (action for action in actions if latest_action_id is not None and action.id == latest_action_id),
                    None,
                )
                connector_id = "google_workspace" if affected_action is None else affected_action.connector_id
                if connector_id == "google_workspace":
                    error_code = "GOOGLE_REAUTH_REQUIRED"
                    message = "Google authentication must be restored before this run can continue."
                    reauth_action = ErrorUiActionV1("REAUTHENTICATE_GOOGLE")
                else:
                    error_code = "CONNECTOR_REAUTH_REQUIRED"
                    message = "Connector authentication must be restored before this run can continue."
                    reauth_action = ErrorUiActionV1("REAUTHENTICATE_CONNECTOR", connector_id=connector_id)
                return ProjectErrorActionsResultV1(
                    1,
                    error_code,
                    message,
                    (
                        reauth_action,
                        ErrorUiActionV1("OPEN_SETTINGS"),
                        ErrorUiActionV1("OPEN_DIAGNOSTICS"),
                    ),
                )
            if retry_actions:
                return ProjectErrorActionsResultV1(
                    1,
                    "ACTION_NOT_SENT",
                    "One or more actions failed before provider delivery.",
                    (*retry_actions, ErrorUiActionV1("OPEN_DIAGNOSTICS")),
                )
            if safe_checkpoint_resume_is_allowed(
                unit_of_work=unit_of_work,
                checkpoint_port=self._checkpoint_port,
                run=run,
                resume_target_registry=self._resume_target_registry,
            ):
                return ProjectErrorActionsResultV1(
                    1,
                    "SAFE_CHECKPOINT_RESUME_AVAILABLE",
                    "This run can continue from its validated safe checkpoint.",
                    (
                        ErrorUiActionV1(
                            "RESUME_SAFE_CHECKPOINT",
                            resume_kind="SAFE_CHECKPOINT_RESUME",
                        ),
                        ErrorUiActionV1("OPEN_DIAGNOSTICS"),
                    ),
                )
            if run.status is RunStatusV1.FAILED:
                return ProjectErrorActionsResultV1(
                    1,
                    "RUN_FAILED",
                    "The run failed.",
                    (ErrorUiActionV1("OPEN_DIAGNOSTICS"),),
                )
        return None


def _latest_reauth_action_id(unit_of_work: UnitOfWork, run_id: str) -> str | None:
    after_id: int | None = None
    latest_action_id: str | None = None
    while True:
        page = unit_of_work.traces.list_page(TraceEventCursor(run_id=run_id, after_id=after_id), 500)
        for event in page:
            if event.event_type == "RUN_REAUTH_REQUIRED" and event.action_id is not None:
                latest_action_id = event.action_id
        if len(page) < 500:
            return latest_action_id
        after_id = page[-1].id


__all__ = [
    "ErrorUiActionV1",
    "ProjectErrorActionsHandler",
    "ProjectErrorActionsQueryV1",
    "ProjectErrorActionsResultV1",
]
