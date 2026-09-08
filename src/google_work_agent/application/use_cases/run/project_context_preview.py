"""Project the current Retrieval selection and context-adjustment eligibility."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime
from json import JSONDecodeError, loads
from typing import Literal
from zoneinfo import ZoneInfo

from google_work_agent.application.use_cases.execution_attempt.persistence_projection import (
    latest_attempt_for_action,
)
from google_work_agent.application.use_cases.plan.persistence_projection import current_plan_tuple
from google_work_agent.domain.action.model import Action, ActionStatusV1
from google_work_agent.domain.evidence.model import Evidence
from google_work_agent.domain.execution_attempt.model import ExecutionAttemptStatusV1
from google_work_agent.domain.run.model import RunStatusV1
from google_work_agent.ports.persistence.unit_of_work import UnitOfWork
from google_work_agent.ports.system.checkpoint_port import CheckpointPort

type ContextCategoryV1 = Literal["mail", "task", "calendar", "github"]


@dataclass(frozen=True, slots=True)
class ProjectContextPreviewQueryV1:
    run_id: str


@dataclass(frozen=True, slots=True)
class ContextPreviewItemV1:
    resource_identity: str
    category: ContextCategoryV1
    title: str
    preview: str
    content: str
    segment_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ProjectContextPreviewResultV1:
    schema_version: int
    run_id: str
    retrieval_revision: int
    items: tuple[ContextPreviewItemV1, ...]
    gmail_count: int
    tasks_count: int
    calendar_count: int
    adjustment_allowed: bool
    allowed_adjustments: tuple[str, ...]
    github_count: int = 0


class ProjectContextPreviewHandler:
    def __init__(
        self,
        *,
        unit_of_work_factory: Callable[[], UnitOfWork],
        checkpoint: CheckpointPort,
        max_items: int = 100,
        max_content_chars: int = 500,
    ) -> None:
        if not 1 <= max_items <= 100:
            raise ValueError("context preview max_items must be between 1 and 100")
        if max_content_chars < 1:
            raise ValueError("context preview max_content_chars must be positive")
        self._unit_of_work_factory = unit_of_work_factory
        self._checkpoint = checkpoint
        self._max_items = max_items
        self._max_content_chars = max_content_chars

    def __call__(self, query: ProjectContextPreviewQueryV1) -> ProjectContextPreviewResultV1:
        head = self._checkpoint.load_retrieval_head(query.run_id)
        if head is None:
            raise LookupError("current RetrievalHeadV1 is unavailable")
        with self._unit_of_work_factory() as unit_of_work:
            run = unit_of_work.runs.get(query.run_id)
            if run is None:
                raise LookupError(f"run not found: {query.run_id}")
            plans = current_plan_tuple(unit_of_work.plans, query.run_id)
            plan = max(plans, key=lambda item: (item.revision_no, item.id), default=None)
            actions = () if plan is None else unit_of_work.actions.list_for_plan(plan.id)
            evidence = unit_of_work.evidence.list_for_run(query.run_id, limit=500)
            items = _deduplicated_preview_items(
                unit_of_work=unit_of_work,
                retrieval_artifact_id=head.retrieval_artifact_id,
                evidence=evidence,
                max_items=self._max_items,
                max_content_chars=self._max_content_chars,
            )
            allowed = _adjustment_allowed(
                unit_of_work=unit_of_work,
                run_status=run.status,
                plan_id=None if plan is None else plan.id,
                actions=actions,
            )

        counts = {"mail": 0, "task": 0, "calendar": 0, "github": 0}
        for item in items:
            counts[item.category] += 1
        return ProjectContextPreviewResultV1(
            schema_version=1,
            run_id=query.run_id,
            retrieval_revision=head.retrieval_revision,
            items=items,
            gmail_count=counts["mail"],
            tasks_count=counts["task"],
            calendar_count=counts["calendar"],
            github_count=counts["github"],
            adjustment_allowed=allowed,
            allowed_adjustments=("EXCLUDE_EVIDENCE", "RETRIEVE_MORE") if allowed else (),
        )


def _deduplicated_preview_items(
    *,
    unit_of_work: UnitOfWork,
    retrieval_artifact_id: str,
    evidence: tuple[Evidence, ...],
    max_items: int,
    max_content_chars: int,
) -> tuple[ContextPreviewItemV1, ...]:
    items_by_identity: dict[str, ContextPreviewItemV1] = {}
    for record in evidence:
        item = _preview_item(
            unit_of_work=unit_of_work,
            retrieval_artifact_id=retrieval_artifact_id,
            record=record,
            max_content_chars=max_content_chars,
        )
        if item is None:
            continue
        current = items_by_identity.get(item.resource_identity)
        if current is None:
            if len(items_by_identity) >= max_items:
                continue
            items_by_identity[item.resource_identity] = item
            continue
        content = _merge_content(current.content, item.content, max_content_chars)
        items_by_identity[item.resource_identity] = ContextPreviewItemV1(
            resource_identity=current.resource_identity,
            category=current.category,
            title=current.title,
            preview=_preview_text(content),
            content=content,
            segment_ids=tuple(dict.fromkeys((*current.segment_ids, *item.segment_ids))),
        )
    return tuple(items_by_identity.values())


def _preview_item(
    *,
    unit_of_work: UnitOfWork,
    retrieval_artifact_id: str,
    record: Evidence,
    max_content_chars: int,
) -> ContextPreviewItemV1 | None:
    locator_json = record.locator_json
    if not isinstance(locator_json, str):
        return None
    try:
        locator = loads(locator_json)
    except (JSONDecodeError, TypeError):
        return None
    if (
        not isinstance(locator, dict)
        or locator.get("retrieval_artifact_id") != retrieval_artifact_id
    ):
        return None
    segment_id = locator.get("segment_id")
    role = locator.get("role")
    resource_ref_id = record.resource_ref_id
    if (
        not isinstance(segment_id, str)
        or not segment_id
        or role not in {"SUPPORTS", "CONTRADICTS", "CONTEXT"}
        or not isinstance(resource_ref_id, str)
    ):
        return None
    resource = unit_of_work.resource_refs.get(resource_ref_id)
    if resource is None or resource.run_id != record.run_id:
        return None
    category = _category_for_resource_type(resource.resource_type)
    title = _user_facing_title(
        category=category,
        resource_id=resource.resource_id,
        stored_title=resource.title,
        excerpt=record.excerpt,
    )
    content = _user_facing_content(
        category=category,
        resource_type=resource.resource_type,
        title=title,
        excerpt=record.excerpt,
    )[:max_content_chars]
    return ContextPreviewItemV1(
        resource_identity=resource.id,
        category=category,
        title=title,
        preview=_preview_text(content),
        content=content,
        segment_ids=(segment_id,),
    )


def _category_for_resource_type(resource_type: str) -> ContextCategoryV1:
    if resource_type.startswith("gmail_"):
        return "mail"
    if resource_type in {"task", "task_list"}:
        return "task"
    if resource_type in {"calendar", "calendar_event", "calendar_freebusy"}:
        return "calendar"
    if resource_type == "github_issue":
        return "github"
    raise ValueError(f"unsupported context resource type: {resource_type}")


def _preview_text(content: str) -> str:
    return content[:240]


def _merge_content(current: str, additional: str, max_chars: int) -> str:
    if not additional or additional == current or additional in current.split("\n\n"):
        return current
    return f"{current}\n\n{additional}"[:max_chars]


def _user_facing_title(
    *,
    category: ContextCategoryV1,
    resource_id: str,
    stored_title: str | None,
    excerpt: str,
) -> str:
    title = (stored_title or "").strip()
    if title and title != resource_id:
        return title
    lines = tuple(line.strip() for line in excerpt.splitlines() if line.strip())
    for label in ("title:", "subject:"):
        candidate = _raw_labeled_value(lines, label)
        if candidate:
            return candidate[:200]
    return _fallback_title(category)


def _user_facing_content(
    *,
    category: ContextCategoryV1,
    resource_type: str,
    title: str,
    excerpt: str,
) -> str:
    lines = tuple(line.strip() for line in excerpt.splitlines() if line.strip())
    if resource_type == "gmail_draft":
        content = _section_content(lines, "body:")
    elif category == "mail":
        content = _without_internal_lines(
            lines,
            title=title,
            prefixes=(
                "Message:",
                "Thread messages collected:",
                "From:",
                "To:",
                "Received:",
                "Sender name:",
                "Sender email:",
                "rfc822_message_id:",
                "references:",
            ),
        )
    elif category == "task":
        content = _joined_display_lines(
            (
                _labeled_value(lines, "due:", "마감"),
                _section_content(lines, "notes:"),
            )
        )
    elif category == "calendar":
        content = _joined_display_lines(
            (
                _labeled_value(lines, "start:", "시작"),
                _labeled_value(lines, "end:", "종료"),
                _labeled_value(lines, "location:", "장소"),
                _labeled_value(lines, "description:", ""),
            )
        )
    else:
        content = _section_content(lines, "description:")
    return content or _empty_content(category)


def _without_internal_lines(
    lines: tuple[str, ...],
    *,
    title: str,
    prefixes: tuple[str, ...],
) -> str:
    visible = tuple(
        line
        for line in lines
        if line != title and line not in {"null", "[]"} and not line.startswith(prefixes)
    )
    return "\n".join(visible)


def _section_content(lines: tuple[str, ...], label: str) -> str:
    for index, line in enumerate(lines):
        if line == label:
            return "\n".join(lines[index + 1 :])
        if line.startswith(label):
            return "\n".join((line.removeprefix(label).strip(), *lines[index + 1 :])).strip()
    return ""


def _labeled_value(lines: tuple[str, ...], source_label: str, display_label: str) -> str:
    value = _raw_labeled_value(lines, source_label)
    if not value:
        return ""
    if source_label in {"due:", "start:", "end:"}:
        value = _format_temporal_value(value, date_only=source_label == "due:")
    return f"{display_label}: {value}" if display_label else value


def _raw_labeled_value(lines: tuple[str, ...], source_label: str) -> str:
    for line in lines:
        if line.startswith(source_label):
            value = line.removeprefix(source_label).strip()
            if not value or value in {"null", "[]"}:
                return ""
            return value
    return ""


def _format_temporal_value(value: str, *, date_only: bool) -> str:
    try:
        if date_only or "T" not in value:
            parsed_date = date.fromisoformat(value[:10])
            return f"{parsed_date.year}년 {parsed_date.month}월 {parsed_date.day}일"
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return value
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(ZoneInfo("Asia/Seoul"))
    period = "오전" if parsed.hour < 12 else "오후"
    hour = parsed.hour % 12 or 12
    return f"{parsed.year}년 {parsed.month}월 {parsed.day}일 {period} {hour}:{parsed.minute:02d}"


def _joined_display_lines(values: tuple[str, ...]) -> str:
    return "\n".join(value for value in values if value)


def _fallback_title(category: ContextCategoryV1) -> str:
    return {
        "mail": "메일 컨텍스트",
        "task": "태스크 컨텍스트",
        "calendar": "일정 컨텍스트",
        "github": "GitHub 컨텍스트",
    }[category]


def _empty_content(category: ContextCategoryV1) -> str:
    return {
        "mail": "이 요청에 사용된 메일입니다.",
        "task": "이 요청에 사용된 태스크입니다.",
        "calendar": "이 요청에 사용된 일정입니다.",
        "github": "이 요청에 사용된 GitHub Issue입니다.",
    }[category]


def _adjustment_allowed(
    *,
    unit_of_work: UnitOfWork,
    run_status: RunStatusV1,
    plan_id: str | None,
    actions: tuple[Action, ...],
) -> bool:
    if (
        run_status is not RunStatusV1.WAITING_APPROVAL
        or plan_id is None
        or not actions
        or any(
            getattr(action, "status", None)
            not in {ActionStatusV1.PROPOSED.value, ActionStatusV1.MODIFIED.value}
            for action in actions
        )
        or unit_of_work.approvals.list_active_for_plan(plan_id)
    ):
        return False
    for action in actions:
        attempt = latest_attempt_for_action(unit_of_work, action.id)
        if attempt is None:
            continue
        if attempt.status in {
            ExecutionAttemptStatusV1.CLAIMED,
            ExecutionAttemptStatusV1.EXECUTING,
            ExecutionAttemptStatusV1.UNKNOWN_RESULT,
        }:
            return False
        if (
            attempt.status is ExecutionAttemptStatusV1.SUCCEEDED
            and unit_of_work.verifications.get_latest_for_attempt(attempt.id) is None
        ):
            return False
    return True


__all__ = [
    "ContextPreviewItemV1",
    "ProjectContextPreviewHandler",
    "ProjectContextPreviewQueryV1",
    "ProjectContextPreviewResultV1",
]
