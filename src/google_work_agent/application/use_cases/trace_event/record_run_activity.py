"""Select bounded execution-time artifacts for the existing diagnostic Trace sink."""

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from hashlib import sha256
from typing import Literal

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
    "stage_one": ("request_intent", "retrieval_result"),
    "stage_two": ("work_analysis_result", "planning_result"),
    "stage_three": ("plan_review",),
}
_FIELD_LABELS = {
    "title": "제목",
    "summary": "제목",
    "subject": "제목",
    "due": "예정일",
    "scheduled_date": "예정일",
    "start": "시작",
    "end": "종료",
    "timezone": "시간대",
    "task_list_id": "대상 Task List",
    "calendar_id": "대상 Calendar",
    "repository": "대상 Repository",
}


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
            detail_updates.append(
                {
                    "fact_id": sha256(f"{execution_id}:{step_key}".encode()).hexdigest(),
                    "state": {
                        "STEP_START": "RUNNING",
                        "STEP_END": "RECORDED",
                        "STEP_WAIT": "WAITING",
                        "STEP_ERROR": "FAILED",
                    }[command.observation],
                    "label": detail_label[:512],
                    "value": detail_value[:512],
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
                    "details": details[:40],
                    "detail_updates": detail_updates,
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

    if field == "retrieval_result":
        evidence_refs = artifact.get("evidence_refs")
        if isinstance(evidence_refs, list) and not evidence_refs:
            add("조회 결과", "조건에 맞는 자료를 찾지 못했습니다.")
        for gap in _objects(artifact.get("missing_information")):
            add("부족한 정보", gap.get("description"))
        for source in _objects(artifact.get("source_statuses")):
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
        for key, label in (("ambiguities", "부족한 정보"), ("risks", "주의 사항")):
            for item in _objects(artifact.get(key)):
                add(label, item.get("description"))
    elif field == "planning_result":
        if isinstance(artifact.get("answer"), str):
            add("계획 종류", "근거 기반 답변 초안 (아직 최종 답변이 아닙니다)")
        for action in _objects(artifact.get("actions")):
            arguments = action.get("arguments")
            if not isinstance(arguments, Mapping):
                continue
            add("계획 종류", "승인 전 실행안 (실행 결과가 아닙니다)")
            for key, label in _FIELD_LABELS.items():
                payload = arguments.get("payload")
                value = arguments.get(key)
                if value is None and isinstance(payload, Mapping):
                    value = payload.get(key)
                if isinstance(value, Mapping) and key in {"start", "end"}:
                    value = value.get("dateTime", value.get("date"))
                add(label, value)
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
        for key in ("issues", "evidence_gaps", "route_issues", "blockers"):
            for item in _objects(artifact.get(key)):
                add("검토 내용", item.get("description"))
    return details


def _is_validated_artifact(field: str, artifact: Mapping[str, object]) -> bool:
    if field != "tool_route_plan":
        return isinstance(artifact.get("meta"), Mapping)
    input_plan, output_plan = artifact.get("input_plan"), artifact.get("output_plan")
    return (
        isinstance(input_plan, Mapping)
        and isinstance(input_plan.get("meta"), Mapping)
        and isinstance(output_plan, Mapping)
        and isinstance(output_plan.get("meta"), Mapping)
    )


def _objects(value: object) -> list[Mapping[str, object]]:
    return [item for item in value if isinstance(item, Mapping)] if isinstance(value, list) else []


def _retrieval_history_details(output: Mapping[str, object]) -> list[dict[str, str]]:
    attempts = _objects(output.get("__context_query_attempts__"))
    details: list[dict[str, str]] = []
    if attempts:
        operations = {str(item.get("operation_kind")) for item in attempts}
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
