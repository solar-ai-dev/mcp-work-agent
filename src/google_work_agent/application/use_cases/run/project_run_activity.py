"""Restore stored responsibility observations and committed lifecycle facts, without I/O."""

from collections.abc import Mapping
from json import JSONDecodeError, loads
from typing import Literal, TypedDict, cast

from google_work_agent.ports.persistence.audit_event_repository import AuditEventCursor
from google_work_agent.ports.persistence.trace_event_repository import TraceEventCursor
from google_work_agent.ports.persistence.unit_of_work import UnitOfWork
from google_work_agent.ports.system.contracts.observability import sanitize_event_attributes

ActivityState = Literal[
    "RUNNING", "WAITING", "RECORDED", "PARTIAL", "FAILED", "INTERRUPTED", "UNKNOWN"
]
_STATES = {"RUNNING", "WAITING", "RECORDED", "PARTIAL", "FAILED", "INTERRUPTED", "UNKNOWN"}


class RunActivityDetailV1(TypedDict):
    label: str
    value: str


class RunActivityRowV1(TypedDict):
    execution_id: str
    sequence: int
    role: str
    state: ActivityState
    label: str
    details: list[RunActivityDetailV1]
    started_at_ms: int
    updated_at_ms: int


class RunActivityV1(TypedDict):
    schema_version: Literal[1]
    trace_cursor: int
    audit_cursor: int
    rows: list[RunActivityRowV1]


_AUDIT_LABELS: dict[str, tuple[str, ActivityState, str]] = {
    "ACTION_APPROVED": ("사용자 승인", "RECORDED", "이 실행안을 승인했습니다."),
    "ACTION_REJECTED": ("사용자 결정", "INTERRUPTED", "이 실행안을 건너뛰었습니다."),
    "EXECUTION_DISPATCH_STARTED": ("승인된 작업 실행", "RUNNING", "외부 변경을 실행하고 있습니다."),
    "WRITE_EXECUTED": (
        "승인된 작업 실행",
        "RECORDED",
        "실행 결과를 받았습니다. 재조회 검증과 구분됩니다.",
    ),
    "WRITE_UNKNOWN_RESULT": (
        "승인된 작업 실행",
        "UNKNOWN",
        "외부 변경 여부가 불확실합니다. 다시 실행하지 않습니다.",
    ),
    "WRITE_FAILED": ("승인된 작업 실행", "FAILED", "실행을 완료하지 못했습니다."),
    "WRITE_RECOVERED": ("실행 결과 복구", "RECORDED", "이미 발생한 실행 결과를 확인했습니다."),
    "VERIFICATION_VERIFIED": ("결과 검증", "RECORDED", "재조회한 결과가 승인 내용과 일치합니다."),
    "VERIFICATION_MISMATCH": ("결과 검증", "PARTIAL", "재조회한 결과가 승인 내용과 다릅니다."),
    "RUN_REAUTH_REQUIRED": ("연결 확인", "WAITING", "사용한 연결의 재인증이 필요합니다."),
    "RUN_REAUTH_RESUMED": ("연결 확인", "RECORDED", "재인증 후 같은 요청을 이어갔습니다."),
    "RECOVERY_REQUIRED": ("안전한 복구", "WAITING", "불확실한 결과의 안전한 확인이 필요합니다."),
    "RECOVERY_RESOLVED": ("안전한 복구", "RECORDED", "복구 후속 처리를 결정했습니다."),
    "RUN_CANCELLED": (
        "작업 중단",
        "INTERRUPTED",
        "작업을 중단했습니다. 이미 발생한 외부 변경은 취소되지 않습니다.",
    ),
}


class ProjectRunActivityHandler:
    def __call__(self, unit_of_work: UnitOfWork, run_id: str, *, run_status: str) -> RunActivityV1:
        """Read every retained page. Trace is never used as approval/effect authority."""
        rows: dict[str, RunActivityRowV1] = {}
        waiting_plans: dict[str, str] = {}
        order: dict[str, tuple[int, int, int]] = {}
        trace_cursor = 0
        while True:
            page = unit_of_work.traces.list_page(TraceEventCursor(run_id, trace_cursor), 500)
            if not page:
                break
            for event in page:
                trace_cursor = max(trace_cursor, event.id)
                if event.run_id != run_id or event.event_type != "RUN_ACTIVITY_OBSERVED":
                    continue
                attrs = _attributes(event.payload_json)
                if attrs.get("schema_version") != 1:
                    continue
                identity, state = attrs.get("execution_id"), attrs.get("state")
                if (
                    not isinstance(identity, str)
                    or len(identity) != 64
                    or not isinstance(state, str)
                    or state not in _STATES
                ):
                    continue
                role, label = attrs.get("role"), attrs.get("label")
                if not isinstance(role, str) or not isinstance(label, str):
                    continue
                # Whitelist semantic observations; execution success must come from Audit below.
                if role not in {
                    "요청 분석",
                    "자료 경로 선택",
                    "자료 검색",
                    "업무 분석",
                    "계획 생성",
                    "계획 검토",
                    "승인 대기",
                    "요청 처리",
                    "요청 분석·자료 검색",
                    "업무 분석·계획 생성",
                }:
                    continue
                key = f"trace:{identity}"
                plan_id = attrs.get("plan_id")
                if role == "승인 대기" and isinstance(plan_id, str):
                    waiting_plans[key] = plan_id
                previous = rows.get(key)
                if (
                    previous
                    and state == "RUNNING"
                    and previous["state"] not in {"RUNNING", "WAITING"}
                ):
                    continue
                if previous and previous["state"] not in {"RUNNING", "WAITING"}:
                    continue
                started = previous["started_at_ms"] if previous else event.created_at_ms
                details = _details(attrs.get("details"))
                rows[key] = RunActivityRowV1(
                    execution_id=key,
                    sequence=0,
                    role=role,
                    state=cast(ActivityState, state),
                    label=label,
                    details=details,
                    started_at_ms=started,
                    updated_at_ms=event.created_at_ms,
                )
                order.setdefault(key, (started, 0, event.id))
            if len(page) < 500:
                break
        audit_cursor = 0
        waiting_audits: dict[tuple[str, str | None], str] = {}
        while True:
            audits = unit_of_work.audits.list_page(
                AuditEventCursor(run_id=run_id, after_id=audit_cursor), 500
            )
            if not audits:
                break
            for audit in audits:
                audit_cursor = max(audit_cursor, audit.id)
                presentation = _AUDIT_LABELS.get(audit.event_type)
                if (
                    audit.run_id != run_id
                    or presentation is None
                    or audit.outcome not in {"TRANSITION_APPLIED", "APPLIED", "SUCCESS"}
                ):
                    continue
                attrs = _attributes(audit.metadata_json)
                role, state, label = presentation
                attempt_id = attrs.get("attempt_id")
                if audit.event_type in {
                    "EXECUTION_DISPATCH_STARTED",
                    "WRITE_EXECUTED",
                    "WRITE_UNKNOWN_RESULT",
                    "WRITE_FAILED",
                } and isinstance(attempt_id, str):
                    key = f"attempt:{attempt_id}"
                else:
                    key = f"audit:{audit.id}"
                if audit.event_type == "RUN_REAUTH_REQUIRED":
                    waiting_audits[("reauth", None)] = key
                elif audit.event_type == "RECOVERY_REQUIRED":
                    waiting_audits[("recovery", audit.action_id)] = key
                elif audit.event_type == "RUN_REAUTH_RESUMED":
                    key = waiting_audits.pop(("reauth", None), key)
                elif audit.event_type == "RECOVERY_RESOLVED":
                    key = waiting_audits.pop(("recovery", audit.action_id), key)
                previous = rows.get(key)
                details = (
                    list(previous["details"])
                    if previous and audit.event_type in {"RUN_REAUTH_RESUMED", "RECOVERY_RESOLVED"}
                    else []
                )
                if audit.event_type == "RECOVERY_RESOLVED":
                    resolution = {
                        "RECHECK": "같은 대상 재확인",
                        "ACCEPT_PARTIAL": "확인된 부분 결과 수용",
                        "CREATE_CORRECTIVE_PLAN": "수정 계획 준비 (재승인 필요)",
                        "CANCEL": "후속 작업 중단 (기존 외부 효과 유지)",
                        "FAIL": "실패로 종료",
                    }.get(str(attrs.get("resolution")))
                    if resolution:
                        details.append({"label": "복구 결정", "value": resolution})
                if audit.action_id is not None:
                    action = unit_of_work.actions.get(audit.action_id)
                    if action is not None:
                        provider = {"google_workspace": "Google Workspace", "github": "GitHub"}.get(
                            action.connector_id
                        )
                        if provider:
                            details.append({"label": "연결", "value": provider})
                        approval_id = attrs.get("approval_id")
                        if isinstance(attempt_id, str):
                            attempt = unit_of_work.execution_attempts.get(attempt_id)
                            if attempt is not None:
                                approval_id = attempt.approval_id
                        if isinstance(approval_id, str):
                            approval = unit_of_work.approvals.get(approval_id)
                            if approval is not None and approval.action_id == audit.action_id:
                                details.extend(
                                    _domain_fields("승인", approval.arguments_snapshot_json)
                                )
                        verification_id = attrs.get("verification_id")
                        if isinstance(verification_id, str):
                            for verification in unit_of_work.verifications.list_for_action(
                                audit.action_id
                            ):
                                if verification.id == verification_id:
                                    details.extend(
                                        _domain_fields("기대", verification.expected_json)
                                    )
                                    if verification.actual_json is not None:
                                        details.extend(
                                            _domain_fields("재조회", verification.actual_json)
                                        )
                rows[key] = RunActivityRowV1(
                    execution_id=key,
                    sequence=0,
                    role=role,
                    state=state,
                    label=label,
                    details=details,
                    started_at_ms=previous["started_at_ms"] if previous else audit.created_at_ms,
                    updated_at_ms=audit.created_at_ms,
                )
                order.setdefault(key, (audit.created_at_ms, 1, audit.id))
            if len(audits) < 500:
                break
        result = sorted(rows.values(), key=lambda row: order[row["execution_id"]])
        for index, row in enumerate(result):
            row["sequence"] = index + 1
            waiting_plan = waiting_plans.get(row["execution_id"])
            if waiting_plan is not None and row["state"] in {"WAITING", "RUNNING"}:
                bundle = unit_of_work.plans.load_bundle(waiting_plan)
                if (
                    bundle is not None
                    and bundle.plan.run_id == run_id
                    and bundle.actions
                    and all(
                        action.status not in {"PROPOSED", "MODIFIED"} for action in bundle.actions
                    )
                ):
                    row["state"] = "RECORDED"
                    row["label"] = "실행안에 대한 사용자 결정을 확인했습니다."
            if run_status in {"COMPLETED", "CANCELLED", "FAILED", "BLOCKED"} and row["state"] in {
                "RUNNING",
                "WAITING",
            }:
                row["state"] = "INTERRUPTED"
                row["label"] = "Run이 종료되었습니다. 이 단계의 완료 결과는 기록되지 않았습니다."
        return RunActivityV1(
            schema_version=1, trace_cursor=trace_cursor, audit_cursor=audit_cursor, rows=result
        )


def _attributes(raw: str) -> dict[str, object]:
    try:
        value = loads(raw)
    except (JSONDecodeError, TypeError):
        return {}
    if not isinstance(value, dict):
        return {}
    attrs = value.get("attributes", value)
    if not isinstance(attrs, Mapping):
        return {}
    return dict(sanitize_event_attributes(dict(attrs)).values)


def _details(value: object) -> list[RunActivityDetailV1]:
    if not isinstance(value, list):
        return []
    return [
        RunActivityDetailV1(label=item["label"][:512], value=item["value"][:512])
        for item in value
        if isinstance(item, dict)
        and isinstance(item.get("label"), str)
        and isinstance(item.get("value"), str)
    ][:40]


def _domain_fields(prefix: str, raw: str) -> list[RunActivityDetailV1]:
    value = _attributes(raw)
    payload = value.get("payload")
    fields = dict(payload) if isinstance(payload, Mapping) else value
    result: list[RunActivityDetailV1] = []
    for key, label in {
        "title": "제목",
        "subject": "제목",
        "summary": "제목",
        "due": "예정일",
        "scheduled_date": "예정일",
        "start": "시작",
        "end": "종료",
        "timezone": "시간대",
    }.items():
        item = fields.get(key)
        if isinstance(item, Mapping):
            item = item.get("dateTime", item.get("date"))
        if isinstance(item, str):
            result.append({"label": f"{prefix} {label}", "value": item[:512]})
    return result
