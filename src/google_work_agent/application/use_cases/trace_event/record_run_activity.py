"""Select bounded execution-time artifacts for the existing diagnostic Trace sink."""

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from hashlib import sha256
from typing import Literal

from google_work_agent.application.agents.retrieval.execute_read import (
    RetrievalReadExecutionV1,
)
from google_work_agent.application.use_cases.trace_event.emit_trace_event import (
    EmitTraceEventCommand,
    EmitTraceEventHandler,
)
from google_work_agent.ports.system.contracts.observability import (
    EventCategory,
    ObservabilityContext,
    Severity,
)

ACTIVITY_ROLES = {
    "request_understanding": "요청 분석",
    "tool_route": "자료 경로 선택",
    "context_retriever": "자료 검색",
    "work_analysis": "업무 분석",
    "planning": "계획 생성",
    "review": "계획 검토",
    "waiting_approval": "승인 대기",
    "single_workflow": "요청 처리",
    "stage_one": "요청 분석·자료 검색",
    "stage_two": "업무 분석·계획 생성",
    "stage_three": "계획 검토",
}
_ARTIFACTS = {
    "request_understanding": ("request_intent",),
    "tool_route": ("tool_route_plan",),
    "context_retriever": ("retrieval_result",),
    "work_analysis": ("work_analysis_result",),
    "planning": ("planning_result",),
    "review": ("plan_review",),
    "single_workflow": (
        "request_intent",
        "retrieval_result",
        "work_analysis_result",
        "planning_result",
        "plan_review",
    ),
    "stage_one": ("request_intent", "tool_route_plan", "retrieval_result"),
    "stage_two": ("work_analysis_result", "planning_result"),
    "stage_three": ("plan_review",),
}
_FIELD_LABELS = {
    "title": "제목",
    "summary": "제목",
    "subject": "제목",
    "due": "예정일",
    "scheduled_date": "예정일",
    "status": "상태",
    "state": "상태",
    "start": "시작",
    "end": "종료",
    "timezone": "시간대",
    "location": "장소",
    "task_list_id": "대상 Task List",
    "calendar_id": "대상 Calendar",
    "repository": "대상 Repository",
    "to": "받는 사람",
    "cc": "참조",
    "bcc": "숨은 참조",
    "attendees": "참석자",
    "thread_id": "대상 Thread",
    "draft_id": "대상 Draft",
    "task_id": "대상 Task",
    "event_id": "대상 Event",
    "issue_number": "대상 Issue",
}
_EFFECT_LABELS = {
    "READ": "조회",
    "CREATE": "생성",
    "UPDATE": "수정",
    "SEND": "전송",
    "DELETE": "삭제",
}
_RESOURCE_LABELS = {
    "EMAIL": "메일",
    "GMAIL_THREAD": "Gmail Thread",
    "GMAIL_MESSAGE": "Gmail Message",
    "GMAIL_DRAFT": "Gmail Draft",
    "TASK_LIST": "Google Task List",
    "TASK": "Google Task",
    "CALENDAR": "Google Calendar",
    "CALENDAR_EVENT": "Google Calendar 일정",
    "CALENDAR_FREEBUSY": "Google Calendar 일정 충돌",
    "GITHUB_ISSUE": "GitHub Issue",
}
_CONNECTOR_LABELS = {
    "google_workspace": "Google Workspace",
    "github": "GitHub",
}
_CONSTRAINT_LABELS = {
    "sender": "보낸 사람",
    "recipient": "받는 사람",
    "recipients": "받는 사람",
    "to": "받는 사람",
    "cc": "참조",
    "bcc": "숨은 참조",
    "subject": "제목",
    "title": "제목",
    "date": "날짜",
    "start": "시작",
    "end": "종료",
    "repository": "Repository",
    "task_list_id": "Task List",
    "calendar_id": "Calendar",
    "thread_id": "Thread",
    "draft_id": "Draft",
}
_CONSTRAINT_KIND_LABELS = {
    "PERSON": "관련 인물",
    "EMAIL": "이메일",
    "DATE": "날짜",
    "TIME": "시간",
    "RESOURCE": "업무 대상",
    "SCOPE": "업무 범위",
    "USER_REQUIREMENT": "요청 조건",
}
_WORK_FACT_LABELS = {
    "TASK": "Task",
    "EVENT": "일정",
    "PERSON": "관련 인물",
    "DATE": "날짜",
    "TIME": "시간",
    "DEADLINE": "마감",
    "STATUS": "상태",
    "RESOURCE": "업무 대상",
    "TEXT_CLAIM": "업무 사실",
    "OTHER": "업무 사실",
}
_RELATION_LABELS = {
    "DEPENDS_ON": "선행 관계",
    "ASSIGNED_TO": "담당 관계",
    "DUE_AT": "마감 관계",
    "DUPLICATES": "중복 관계",
    "CONFLICTS_WITH": "충돌 관계",
    "RELATED_TO": "관련 관계",
}
_MAX_ACTIVITY_DETAILS = 40


@dataclass(frozen=True, slots=True)
class RecordRunActivityCommand:
    run_id: str
    task_namespace: str
    responsibility: str
    observation: Literal[
        "START",
        "END",
        "WAIT",
        "ERROR",
        "STEP_START",
        "STEP_END",
        "STEP_WAIT",
        "STEP_ERROR",
    ]
    output: Mapping[str, object]
    plan_id: str | None = None
    detail: tuple[str, str, str] | None = None


class RecordRunActivityHandler:
    def __init__(
        self,
        *,
        emit_trace: EmitTraceEventHandler,
        now_ms: Callable[[], int],
        service_instance_id: str,
    ) -> None:
        self._emit_trace = emit_trace
        self._now_ms = now_ms
        self._service_instance_id = service_instance_id

    def __call__(self, command: RecordRunActivityCommand) -> None:
        role = ACTIVITY_ROLES.get(command.responsibility)
        if role is None or not command.run_id or not command.task_namespace:
            return
        details: list[dict[str, str]] = []
        detail_updates: list[dict[str, object]] = []
        state = {
            "START": "RUNNING",
            "END": "RECORDED",
            "WAIT": "WAITING",
            "ERROR": "FAILED",
            "STEP_START": "RUNNING",
            "STEP_END": "RUNNING",
            "STEP_WAIT": "RUNNING",
            "STEP_ERROR": "RUNNING",
        }[command.observation]
        label = {
            "START": "처리하고 있습니다.",
            "END": "이 단계 실행을 마쳤습니다. 업무 결과는 Run 상태에서 별도로 확인합니다.",
            "WAIT": "사용자 응답을 기다리고 있습니다.",
            "ERROR": "이 단계를 마치지 못했습니다.",
            "STEP_START": "처리하고 있습니다.",
            "STEP_END": "처리하고 있습니다.",
            "STEP_WAIT": "처리하고 있습니다.",
            "STEP_ERROR": "처리하고 있습니다.",
        }[command.observation]
        if command.observation.startswith("STEP_"):
            if command.detail is None:
                return
            step_key, detail_label, detail_value = command.detail
            if not step_key or not detail_label.strip() or not detail_value.strip():
                return
            execution_id = sha256(f"{command.run_id}:{command.task_namespace}".encode()).hexdigest()
            step_details = (
                _step_details(command.responsibility, step_key, command.output)
                if command.observation == "STEP_END"
                else [{"label": detail_label, "value": detail_value}]
            )
            if not step_details:
                return
            for index, item in enumerate(step_details):
                detail_updates.append(
                    {
                        "fact_id": sha256(
                            f"{execution_id}:{step_key}:{index}:{item['label']}".encode()
                        ).hexdigest(),
                        "state": {
                            "STEP_START": "RUNNING",
                            "STEP_END": "RECORDED",
                            "STEP_WAIT": "WAITING",
                            "STEP_ERROR": "FAILED",
                        }[command.observation],
                        "label": item["label"][:512],
                        "value": item["value"][:512],
                        "occurred_at_ms": self._now_ms(),
                    }
                )
        if command.observation == "END":
            for field in _ARTIFACTS.get(command.responsibility, ()):
                artifact = command.output.get(field)
                if not isinstance(artifact, Mapping) or not _is_validated_artifact(field, artifact):
                    continue
                state = "RECORDED"
                details.extend(_artifact_details(field, artifact))
                label = {
                    "request_intent": "요청의 목적을 분석했습니다.",
                    "tool_route_plan": "허용된 자료와 실행 경로를 확인했습니다.",
                    "retrieval_result": "자료 조회 결과를 정리했습니다.",
                    "work_analysis_result": "근거의 관계와 부족한 정보를 분석했습니다.",
                    "planning_result": "답변 또는 실행안을 작성했습니다.",
                    "plan_review": "작성된 계획을 검토했습니다.",
                }.get(field, label)
                if artifact.get("coverage") == "PARTIAL":
                    state, label = (
                        "PARTIAL",
                        "확인한 범위의 자료를 남겼습니다. 부족한 정보가 있습니다.",
                    )
                review_status = artifact.get("status")
                if field == "plan_review" and review_status in {
                    "REVISE",
                    "RETRIEVE_MORE",
                    "ROUTE_RECONSIDERATION",
                }:
                    state, label = "PARTIAL", "추가 확인 또는 계획 수정이 필요합니다."
                if field == "plan_review" and review_status == "BLOCK":
                    state, label = "INTERRUPTED", "검토 결과 진행이 차단되었습니다."
            if command.responsibility == "context_retriever":
                details.extend(_retrieval_history_details(command.output))
        execution_id = sha256(f"{command.run_id}:{command.task_namespace}".encode()).hexdigest()
        self._emit_trace(
            EmitTraceEventCommand(
                correlation=ObservabilityContext(
                    service_instance_id=self._service_instance_id, run_id=command.run_id
                ),
                event_name="RUN_ACTIVITY_OBSERVED",
                event_category=EventCategory.WORKFLOW,
                occurred_at_ms=self._now_ms(),
                severity=Severity.INFO,
                component="workflow-activity",
                attributes={
                    "schema_version": 1,
                    "execution_id": execution_id,
                    "role": role,
                    "state": state,
                    "label": label,
                    "details": _limit_details(details),
                    "detail_updates": _limit_detail_updates(
                        detail_updates, execution_id=execution_id
                    ),
                    "plan_id": command.plan_id,
                },
            )
        )


def _artifact_details(field: str, artifact: Mapping[str, object]) -> list[dict[str, str]]:
    details: list[dict[str, str]] = []

    def add(label: str, value: object) -> None:
        if isinstance(value, str) and value.strip():
            details.append({"label": label, "value": value[:512]})
        elif type(value) is int:
            details.append({"label": label, "value": str(value)})
        elif isinstance(value, list) and value and all(isinstance(item, str) for item in value):
            details.append({"label": label, "value": ", ".join(value)[:512]})

    if field == "request_intent":
        add("요청 업무", artifact.get("goal"))
        for condition in _strings(artifact.get("completion_conditions")):
            add("완료 조건", condition)
        for effect in _strings(artifact.get("requested_effect_hints")):
            add("요청 작업", _EFFECT_LABELS.get(effect, effect))
        for resource in _strings(artifact.get("requested_resource_hints")):
            add("요청 대상", _RESOURCE_LABELS.get(resource, resource))
        for constraint in _objects(artifact.get("constraints")):
            value = constraint.get("value")
            label = _CONSTRAINT_LABELS.get(
                str(constraint.get("field")),
                _CONSTRAINT_KIND_LABELS.get(str(constraint.get("kind")), "요청 조건"),
            )
            provenance = constraint.get("provenance")
            if isinstance(provenance, Mapping):
                source = provenance.get("source")
                source_label = (
                    "사용자 확인" if source == "CONFIRMATION_RESPONSE" else "사용자 요청"
                )
                label = f"{source_label} · {label}"
            add(label, value)
        ambiguity = artifact.get("ambiguity")
        if isinstance(ambiguity, Mapping) and ambiguity.get("requires_confirmation") is True:
            add("사용자 확인 필요", _display_fields(ambiguity.get("missing_fields")))
    elif field == "tool_route_plan":
        input_plan = artifact.get("input_plan")
        if isinstance(input_plan, Mapping):
            for route in _objects(input_plan.get("input_routes")):
                add("검증된 조회 범위", _route_summary(route))
        output_plan = artifact.get("output_plan")
        if isinstance(output_plan, Mapping) and output_plan.get("output_mode") == "ACTION":
            for route in _objects(output_plan.get("output_routes")):
                add("검증된 변경 범위", _route_summary(route))
    elif field == "retrieval_result":
        coverage = artifact.get("coverage")
        evidence_refs = artifact.get("evidence_refs")
        source_resource_refs = artifact.get("source_resource_refs")
        source_statuses = _objects(artifact.get("source_statuses"))
        if coverage == "NO_FETCH_NEEDED":
            add("자료 조회", "이 요청에는 업무 자료 조회가 필요하지 않았습니다.")
        elif isinstance(evidence_refs, list) and not evidence_refs:
            if isinstance(source_resource_refs, list) and source_resource_refs:
                add("조회 결과", "후보 자료는 있었지만 관련 근거를 확정하지 못했습니다.")
            elif source_statuses and all(
                source.get("status") == "COMPLETE" for source in source_statuses
            ):
                add("조회 결과", "허용된 조회 범위에서 조건에 맞는 자료가 없었습니다.")
        for gap in _objects(artifact.get("missing_information")):
            add("부족한 정보", gap.get("description"))
        for source in source_statuses:
            if source.get("status") in {"FAILED", "PARTIAL", "NOT_ATTEMPTED"}:
                reason = {
                    "AUTH": "연결 확인 필요",
                    "SCOPE": "권한 확인 필요",
                    "RATE_LIMIT": "조회 제한",
                    "TIMEOUT": "조회 시간 초과",
                    "PROVIDER": "외부 조회 실패",
                    "NOT_FOUND": "대상 확인 불가",
                    "BUDGET": "조회 예산 소진",
                }.get(str(source.get("failure_kind")), "일부 자료 미확인")
                add("자료 조회 한계", reason)
    elif field == "work_analysis_result":
        facts = _objects(artifact.get("work_facts"))
        facts_by_id = {
            str(item.get("fact_id")): item for item in facts if isinstance(item.get("fact_id"), str)
        }
        for fact in facts:
            subject = fact.get("subject")
            value = fact.get("value")
            if isinstance(subject, str) and isinstance(value, str):
                add(
                    _WORK_FACT_LABELS.get(str(fact.get("kind")), "업무 사실"),
                    subject if subject == value else f"{subject} · {value}",
                )
        for relation in _objects(artifact.get("relations")):
            source = facts_by_id.get(str(relation.get("source_fact_id")))
            target = facts_by_id.get(str(relation.get("target_fact_id")))
            if source is not None and target is not None:
                add(
                    _RELATION_LABELS.get(str(relation.get("kind")), "업무 관계"),
                    f"{source.get('subject')} → {target.get('subject')}",
                )
        for key, label in (("ambiguities", "부족한 정보"), ("risks", "주의 사항")):
            for item in _objects(artifact.get(key)):
                add(label, item.get("description"))
        necessity = artifact.get("action_necessity")
        if necessity in {"REQUIRED", "NOT_REQUIRED"}:
            add(
                "외부 실행 필요",
                "필요함" if necessity == "REQUIRED" else "필요하지 않음",
            )
            add("판단 근거", artifact.get("action_necessity_reason"))
    elif field == "planning_result":
        if isinstance(artifact.get("answer"), str):
            add("계획 종류", "근거 기반 답변 초안 (아직 최종 답변이 아닙니다)")
        for index, action in enumerate(_objects(artifact.get("actions")), start=1):
            arguments = action.get("arguments")
            if not isinstance(arguments, Mapping):
                continue
            raw_effect = str(action.get("effect"))
            add(
                f"실행안 {index} · 계획",
                f"{_EFFECT_LABELS.get(raw_effect, raw_effect)} 예정 (아직 실행되지 않음)",
            )
            for key, label in _FIELD_LABELS.items():
                payload = arguments.get("payload")
                value = arguments.get(key)
                if value is None and isinstance(payload, Mapping):
                    value = payload.get(key)
                if isinstance(value, Mapping) and key in {"start", "end"}:
                    value = value.get("dateTime", value.get("date"))
                add(f"실행안 {index} · {label}", value)
    elif field == "plan_review":
        add(
            "검토 결과",
            {
                "PASS": "검토 통과",
                "REVISE": "수정 필요",
                "RETRIEVE_MORE": "추가 자료 필요",
                "ROUTE_RECONSIDERATION": "자료 경로 재검토",
                "CONFIRM": "사용자 확인 필요",
                "BLOCK": "진행 차단",
            }.get(str(artifact.get("status"))),
        )
        add("검토 요약", artifact.get("summary"))
        confirmation = artifact.get("confirmation")
        if isinstance(confirmation, Mapping):
            add("사용자 확인 질문", confirmation.get("question"))
        for key in ("issues", "evidence_gaps", "route_issues", "blockers"):
            for item in _objects(artifact.get(key)):
                add("검토 내용", item.get("description"))
                affected = [
                    *_strings(item.get("affected_action_ids")),
                    *_strings(item.get("affected_route_ids")),
                ]
                if affected:
                    add("검토 영향 범위", affected)
    return details


def _is_validated_artifact(field: str, artifact: Mapping[str, object]) -> bool:
    if field == "tool_route_plan":
        return _is_validated_tool_route_plan(artifact)
    if not _has_artifact_meta(artifact.get("meta")):
        return False
    expected_version = {
        "request_intent": 2,
        "retrieval_result": 1,
        "work_analysis_result": 2,
        "planning_result": 2,
        "plan_review": 2,
    }.get(field)
    if artifact.get("schema_version") != expected_version:
        return False
    if field == "request_intent":
        return (
            isinstance(artifact.get("goal"), str)
            and isinstance(artifact.get("completion_conditions"), list)
            and isinstance(artifact.get("constraints"), list)
            and isinstance(artifact.get("requested_effect_hints"), list)
            and isinstance(artifact.get("requested_resource_hints"), list)
            and isinstance(artifact.get("ambiguity"), Mapping)
        )
    if field == "retrieval_result":
        return (
            artifact.get("coverage") in {"SUFFICIENT", "PARTIAL", "NO_FETCH_NEEDED"}
            and isinstance(artifact.get("evidence_refs"), list)
            and isinstance(artifact.get("source_resource_refs"), list)
            and isinstance(artifact.get("source_statuses"), list)
            and isinstance(artifact.get("missing_information"), list)
        )
    if field == "work_analysis_result":
        return (
            isinstance(artifact.get("work_facts"), list)
            and isinstance(artifact.get("relations"), list)
            and isinstance(artifact.get("ambiguities"), list)
            and isinstance(artifact.get("risks"), list)
            and artifact.get("action_necessity")
            in {"REQUIRED", "NOT_REQUIRED", "UNDETERMINED"}
        )
    if field == "planning_result":
        return (
            isinstance(artifact.get("answer"), str)
            and isinstance(artifact.get("evidence_refs"), list)
        ) or isinstance(artifact.get("actions"), list)
    if field == "plan_review":
        return artifact.get("status") in {
            "PASS",
            "REVISE",
            "RETRIEVE_MORE",
            "ROUTE_RECONSIDERATION",
            "CONFIRM",
            "BLOCK",
        }
    return False


def _is_validated_tool_route_plan(artifact: Mapping[str, object]) -> bool:
    input_plan, output_plan = artifact.get("input_plan"), artifact.get("output_plan")
    return (
        isinstance(input_plan, Mapping)
        and artifact.get("schema_version") == 2
        and input_plan.get("schema_version") == 1
        and _has_artifact_meta(input_plan.get("meta"))
        and isinstance(input_plan.get("input_routes"), list)
        and isinstance(output_plan, Mapping)
        and output_plan.get("schema_version") == 1
        and _has_artifact_meta(output_plan.get("meta"))
        and output_plan.get("output_mode") in {"ANSWER", "ACTION"}
        and (
            output_plan.get("output_mode") == "ANSWER"
            or isinstance(output_plan.get("output_routes"), list)
        )
    )


def _has_artifact_meta(value: object) -> bool:
    if not isinstance(value, Mapping):
        return False
    artifact_id, revision, based_on = (
        value.get("artifact_id"),
        value.get("revision"),
        value.get("based_on"),
    )
    return (
        isinstance(artifact_id, str)
        and bool(artifact_id)
        and type(revision) is int
        and revision > 0
        and isinstance(based_on, list)
        and all(
            isinstance(item, Mapping)
            and isinstance(item.get("artifact_id"), str)
            and type(item.get("revision")) is int
            for item in based_on
        )
    )


def _objects(value: object) -> list[Mapping[str, object]]:
    return [item for item in value if isinstance(item, Mapping)] if isinstance(value, list) else []


def _strings(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str) and item]


def _step_details(
    responsibility: str,
    step_key: str,
    output: Mapping[str, object],
) -> list[dict[str, str]]:
    if responsibility not in ACTIVITY_ROLES:
        return []
    if step_key == "identify_goal":
        candidate = output.get("goal_candidate")
        if isinstance(candidate, Mapping) and isinstance(candidate.get("goal"), str):
            return [{"label": "요청 업무", "value": candidate["goal"][:512]}]
        return []
    if step_key == "identify_temporal_scope":
        candidate = output.get("goal_candidate")
        if not isinstance(candidate, Mapping):
            return []
        details: list[dict[str, str]] = []
        for constraint in _objects(candidate.get("constraints")):
            if constraint.get("kind") not in {"DATE", "TIME"}:
                continue
            value = constraint.get("value")
            if isinstance(value, str) and value:
                details.append(
                    {
                        "label": _CONSTRAINT_LABELS.get(
                            str(constraint.get("field")),
                            _CONSTRAINT_KIND_LABELS[str(constraint["kind"])],
                        ),
                        "value": value[:512],
                    }
                )
        return details
    if step_key == "detect_ambiguity":
        ambiguity = output.get("ambiguity_candidate")
        if not isinstance(ambiguity, Mapping) or ambiguity.get("requires_confirmation") is not True:
            return []
        value = _display_fields(ambiguity.get("missing_fields"))
        return [] if value is None else [{"label": "사용자 확인 필요", "value": value}]
    if step_key == "validate_route":
        plan = output.get("tool_route_plan")
        if isinstance(plan, Mapping) and _is_validated_artifact("tool_route_plan", plan):
            return _artifact_details("tool_route_plan", plan)
        return []
    if step_key == "build_query":
        local_state = output.get("__context_agent_local__")
        if not isinstance(local_state, Mapping):
            return []
        failure = local_state.get("failure_record")
        if not isinstance(failure, Mapping) or not isinstance(
            failure.get("reason_code"), str
        ):
            return []
        diagnostic = failure.get("diagnostic")
        suffix = f": {diagnostic}" if isinstance(diagnostic, str) and diagnostic else ""
        return [
            {
                "label": "검색 변경 거절 원인",
                "value": f"{failure['reason_code']}{suffix}"[:512],
            }
        ]
    if step_key == "execute_read":
        execution = output.get("read_execution")
        if not isinstance(execution, RetrievalReadExecutionV1):
            return []
        if execution.status == "COMPLETE":
            if execution.candidate_count == 0:
                value = "허용된 조회 범위에서 후보 자료가 없었습니다."
            elif execution.candidate_count is None:
                value = "허용된 범위의 자료 조회를 완료했습니다."
            else:
                value = f"허용된 범위에서 후보 자료 {execution.candidate_count}건을 확인했습니다."
        elif execution.status == "EXHAUSTED":
            value = "추가로 확인할 페이지가 없었습니다."
        else:
            failure_code = execution.failure_code
            value = {
                "NOT_FOUND": "조회 대상을 찾지 못했습니다.",
                "PERMISSION_DENIED": "허용된 권한으로 조회하지 못했습니다.",
                "BUDGET_EXHAUSTED": "허용된 조회 범위를 모두 사용했습니다.",
            }.get(
                failure_code if failure_code is not None else "",
                "자료 조회를 완료하지 못했습니다.",
            )
        return [{"label": "자료 조회", "value": value}]
    if step_key == "select_evidence":
        selection = output.get("evidence_selection")
        if not isinstance(selection, Mapping):
            return []
        selected = _strings(selection.get("selected_segment_ids"))
        return [
            {
                "label": "관련 근거",
                "value": (
                    f"조회한 자료에서 관련 근거 {len(selected)}건을 채택했습니다."
                    if selected
                    else "조회 후보에서 관련 근거를 확정하지 못했습니다."
                ),
            }
        ]
    if step_key == "assess_sufficiency":
        sufficiency = output.get("sufficiency")
        if not isinstance(sufficiency, Mapping):
            return []
        value = {
            "SUFFICIENT": "현재 근거가 요청 처리에 충분합니다.",
            "NEEDS_MORE_DATA": "요청 처리에 추가 자료가 필요합니다.",
            "NEEDS_CONFIRMATION": "자료 범위를 확정하려면 사용자 확인이 필요합니다.",
            "ROUTE_RECONSIDERATION_REQUIRED": "자료 경로를 다시 검토해야 합니다.",
            "PARTIAL": "확인한 근거만으로 일부 처리할 수 있습니다.",
            "BLOCKED": "현재 근거로 요청을 진행할 수 없습니다.",
        }.get(str(sufficiency.get("status")))
        return [] if value is None else [{"label": "자료 충족도", "value": value}]
    return []


def _route_summary(route: Mapping[str, object]) -> str | None:
    connector = route.get("connector_id")
    resource = route.get("resource_type")
    if not isinstance(connector, str) or not isinstance(resource, str):
        return None
    values = [
        _CONNECTOR_LABELS.get(connector, connector),
        _RESOURCE_LABELS.get(resource, resource),
    ]
    effect = route.get("effect")
    if isinstance(effect, str):
        values.append(_EFFECT_LABELS.get(effect, effect))
    return " · ".join(values)


def _display_fields(value: object) -> str | None:
    fields = _strings(value)
    if not fields:
        return None
    return ", ".join(_CONSTRAINT_LABELS.get(field, field) for field in fields)[:512]


def _limit_details(details: list[dict[str, str]]) -> list[dict[str, str]]:
    if len(details) <= _MAX_ACTIVITY_DETAILS:
        return details
    return [
        *details[: _MAX_ACTIVITY_DETAILS - 1],
        {
            "label": "표시 한계",
            "value": "추가 핵심 업무 사실이 있습니다. 상세 이력의 보존 범위를 확인해 주세요.",
        },
    ]


def _limit_detail_updates(
    details: list[dict[str, object]], *, execution_id: str
) -> list[dict[str, object]]:
    if len(details) <= _MAX_ACTIVITY_DETAILS:
        return details
    occurred_at_ms = details[-1].get("occurred_at_ms")
    marker: dict[str, object] = {
        "fact_id": sha256(f"{execution_id}:detail-limit".encode()).hexdigest(),
        "state": "RECORDED",
        "label": "표시 한계",
        "value": "추가 핵심 업무 사실이 있습니다. 상세 이력의 보존 범위를 확인해 주세요.",
        "occurred_at_ms": occurred_at_ms if type(occurred_at_ms) is int else 0,
    }
    return [*details[: _MAX_ACTIVITY_DETAILS - 1], marker]


def _retrieval_history_details(output: Mapping[str, object]) -> list[dict[str, str]]:
    attempts = _objects(output.get("__context_query_attempts__"))
    details: list[dict[str, str]] = []
    completed_attempts = [item for item in attempts if isinstance(item.get("stop_reason"), str)]
    if completed_attempts:
        operations = {str(item.get("operation_kind")) for item in completed_attempts}
        if "NEXT_PAGE" in operations:
            details.append(
                {"label": "조회 범위", "value": "첫 결과 이후 다음 페이지까지 확인했습니다."}
            )
        if "DETAIL_FETCH" in operations:
            details.append({"label": "조회 범위", "value": "후보의 상세 내용을 확인했습니다."})
    acquisition, retrieval = output.get("acquisition_result"), output.get("retrieval_result")
    if isinstance(acquisition, Mapping) and isinstance(retrieval, Mapping):
        selected = retrieval.get("source_resource_refs")
        for summary in _objects(acquisition.get("source_summaries")):
            for resource in _objects(summary.get("resources")):
                if (
                    not isinstance(selected, list)
                    or resource.get("resource_handle") not in selected
                ):
                    continue
                payload = resource.get("payload")
                if isinstance(payload, Mapping):
                    title = payload.get("subject", payload.get("title", payload.get("summary")))
                    if isinstance(title, str) and title:
                        details.append({"label": "선택 근거 제목", "value": title[:512]})
    return details
