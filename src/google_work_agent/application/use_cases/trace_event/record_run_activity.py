"""Select bounded execution-time artifacts for the existing diagnostic Trace sink."""

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from hashlib import sha256
from typing import Literal, cast

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
    observation: Literal["START", "END", "WAIT", "ERROR"]
    output: Mapping[str, object]
    plan_id: str | None = None


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
        state = {"START": "RUNNING", "END": "RECORDED", "WAIT": "WAITING", "ERROR": "FAILED"}[
            command.observation
        ]
        label = {
            "START": "처리하고 있습니다.",
            "END": "이 단계의 처리가 종료되었습니다.",
            "WAIT": "사용자 응답을 기다리고 있습니다.",
            "ERROR": "이 단계를 마치지 못했습니다.",
        }[command.observation]
        if command.observation == "END":
            for field in _ARTIFACTS.get(command.responsibility, ()):
                artifact = command.output.get(field)
                if not isinstance(artifact, Mapping) or not isinstance(
                    artifact.get("meta"), Mapping
                ):
                    continue
                details.extend(_artifact_details(field, artifact))
                label = {
                    "request_intent": "요청의 목적을 분석했습니다.",
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

    meta = artifact.get("meta")
    if isinstance(meta, Mapping):
        add("결과 revision", meta.get("revision"))
    if field == "request_intent":
        add("확인한 요청 목적", artifact.get("goal"))
    elif field == "retrieval_result":
        for key, label in (
            ("evidence_refs", "선택 근거 수"),
            ("source_resource_refs", "근거 Source 수"),
        ):
            values = artifact.get(key)
            if isinstance(values, list):
                add(label, len(set(str(item) for item in values)))
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
        for key, label in (("relations", "확인한 관계 수"), ("work_facts", "분석한 사실 수")):
            values = artifact.get(key)
            if isinstance(values, list):
                add(label, len(values))
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


def _objects(value: object) -> list[Mapping[str, object]]:
    return [item for item in value if isinstance(item, Mapping)] if isinstance(value, list) else []


def _retrieval_history_details(output: Mapping[str, object]) -> list[dict[str, str]]:
    attempts = _objects(output.get("__context_query_attempts__"))
    details: list[dict[str, str]] = []
    if attempts:
        search = [
            item for item in attempts if item.get("operation_kind") in {"SEARCH", "NEXT_PAGE"}
        ]
        counts = [
            cast(int, item["candidate_count"])
            for item in search
            if type(item.get("candidate_count")) is int
        ]
        if counts:
            details.append(
                {"label": "현재까지 검색 반환 후보 합계 (중복 포함)", "value": str(sum(counts))}
            )
        detail_reads = [
            item
            for item in attempts
            if item.get("operation_kind") == "DETAIL_FETCH"
            and item.get("candidate_count") is not None
        ]
        details.append({"label": "현재까지 완료한 상세 조회 수", "value": str(len(detail_reads))})
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
