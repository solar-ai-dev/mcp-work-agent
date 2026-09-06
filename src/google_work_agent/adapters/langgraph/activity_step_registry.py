"""Bounded user-facing facts for observed semantic Agent subgraph steps."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ActivityStepPresentation:
    label: str
    started: str
    completed: str
    waiting: str
    failed: str


def _step(label: str, subject: str) -> ActivityStepPresentation:
    return ActivityStepPresentation(
        label=label,
        started=f"{subject} 확인하고 있습니다.",
        completed=f"{subject} 확인을 마쳤습니다.",
        waiting=f"{subject} 확인에 사용자 응답이 필요합니다.",
        failed=f"{subject} 확인을 마치지 못했습니다.",
    )


_STEPS: dict[tuple[str, str], ActivityStepPresentation] = {
    ("request_understanding", "identify_goal"): _step("요청 목적", "요청 목적을"),
    ("request_understanding", "identify_temporal_scope"): _step(
        "기간 조건", "요청의 기간 조건을"
    ),
    ("request_understanding", "detect_ambiguity"): _step(
        "필요한 사용자 결정", "안전한 진행에 필요한 사용자 결정을"
    ),
    ("tool_route", "determine_io_resources"): _step(
        "자료 범위", "요청에 필요한 자료 범위를"
    ),
    ("tool_route", "bind_registry_candidates"): _step(
        "사용 가능한 연결", "허용된 연결과 도구를"
    ),
    ("tool_route", "select_tool_if_needed"): _step(
        "자료 경로", "사용할 자료 경로를"
    ),
    ("tool_route", "validate_route"): _step("경로 검증", "선택한 자료 경로를"),
    ("context_retriever", "plan_query"): _step("검색 계획", "검색할 조건과 범위를"),
    ("context_retriever", "execute_read"): _step("자료 조회", "허용된 범위의 자료를"),
    ("context_retriever", "select_evidence"): _step("관련 근거", "업무에 관련된 근거를"),
    ("context_retriever", "assess_sufficiency"): _step(
        "자료 충족도", "현재 자료가 요청에 충분한지"
    ),
    ("work_analysis", "extract_work_facts"): _step("업무 사실", "근거에 나타난 업무 사실을"),
    ("work_analysis", "resolve_entity_relations"): _step(
        "대상 관계", "사람과 업무 대상의 관계를"
    ),
    ("work_analysis", "resolve_temporal_dependencies"): _step(
        "시간 관계", "업무의 시간 관계를"
    ),
    ("work_analysis", "detect_duplicate_conflict_candidates"): _step(
        "중복·충돌 후보", "중복되거나 충돌할 수 있는 항목을"
    ),
    ("work_analysis", "validate_relations"): _step("관계 검증", "근거와 업무 관계를"),
    ("work_analysis", "assess_information_gaps"): _step(
        "부족한 정보", "업무 처리에 부족한 정보를"
    ),
    ("work_analysis", "assess_operational_risks"): _step(
        "주의 사항", "실행 전에 확인할 주의 사항을"
    ),
    ("planning", "outline_answer"): _step("답변 구성", "근거 기반 답변 구성을"),
    ("planning", "compose_answer"): _step("답변 초안", "근거 기반 답변 초안을"),
    ("planning", "draft_action_objective_per_output_route"): _step(
        "실행 목적", "요청한 실행 목적을"
    ),
    ("planning", "compose_arguments_per_output_route"): _step(
        "실행 값", "실행 대상과 업무 값을"
    ),
    ("planning", "derive_dependencies"): _step("실행 순서", "작업 사이의 실행 순서를"),
    ("review", "inspect_goal_and_evidence"): _step(
        "목적·근거 검토", "요청 목적과 근거의 일치를"
    ),
    ("review", "inspect_action_scope_route"): _step(
        "대상·경로 검토", "실행 대상과 자료 경로를"
    ),
    ("review", "inspect_constraints_policy"): _step(
        "제약·정책 검토", "요청 제약과 안전 정책을"
    ),
    ("review", "recheck"): _step("수정 영향 재검토", "수정된 부분의 영향을"),
}

_COMPOSITE_RESPONSIBILITIES: dict[str, tuple[str, ...]] = {
    "stage_one": ("request_understanding", "tool_route", "context_retriever"),
    "stage_two": ("work_analysis", "planning"),
    "stage_three": ("review",),
    "single_workflow": (
        "request_understanding",
        "tool_route",
        "context_retriever",
        "work_analysis",
        "planning",
        "review",
    ),
}


def resolve_activity_step(
    responsibility: str, node: str
) -> ActivityStepPresentation | None:
    direct = _STEPS.get((responsibility, node))
    if direct is not None:
        return direct
    for owner in _COMPOSITE_RESPONSIBILITIES.get(responsibility, ()):
        presentation = _STEPS.get((owner, node))
        if presentation is not None:
            return presentation
    return None


__all__ = ["ActivityStepPresentation", "resolve_activity_step"]
