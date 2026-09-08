"""Project stored Activity facts into bounded user-facing sentences."""

from collections.abc import Callable, Sequence
from typing import TypedDict


class ActivityDetailTextSource(TypedDict):
    label: str
    value: str


ActivityDetailTextProjector = Callable[
    [Sequence[ActivityDetailTextSource], str], dict[int, str]
]


def project_run_activity_detail_texts(
    *,
    role: str,
    state: str,
    details: Sequence[ActivityDetailTextSource],
) -> dict[int, str]:
    """Return display sentences while leaving stored facts and identity unchanged."""

    projector: ActivityDetailTextProjector = {
        "요청 분석": _request_display_texts,
        "자료 경로 선택": _route_display_texts,
        "자료 검색": _retrieval_display_texts,
        "업무 분석": _analysis_display_texts,
        "계획 생성": _planning_display_texts,
        "계획 검토": _review_display_texts,
        "요청 분석·자료 검색": _stage_one_display_texts,
        "업무 분석·계획 생성": _stage_two_display_texts,
        "요청 처리": _single_workflow_display_texts,
    }.get(role, _lifecycle_display_texts)
    return projector(details, state)


def _request_display_texts(
    details: Sequence[ActivityDetailTextSource], _state: str
) -> dict[int, str]:
    texts: dict[int, str] = {}
    goal = next(
        (
            (index, detail["value"])
            for index, detail in enumerate(details)
            if detail["label"] == "요청 업무"
        ),
        None,
    )
    if goal is not None:
        texts[goal[0]] = _sentence(goal[1])
    else:
        effects = _values_for_label(details, "요청 작업")
        resources = _values_for_label(details, "요청 대상")
        if effects or resources:
            index = next(
                index
                for index, detail in enumerate(details)
                if detail["label"] in {"요청 작업", "요청 대상"}
            )
            parts = []
            if effects:
                parts.append(f"요청한 작업은 {', '.join(effects)}입니다")
            if resources:
                parts.append(f"대상은 {', '.join(resources)}입니다")
            texts[index] = ". ".join(parts) + "."
    for index, detail in enumerate(details):
        if detail["label"] == "사용자 확인 필요":
            texts[index] = f"사용자 확인이 필요한 항목은 {detail['value']}입니다."
        elif detail["label"].startswith("사용자 확인 · "):
            field = detail["label"].removeprefix("사용자 확인 · ")
            texts[index] = (
                f"사용자 확인으로 {field} 값을 확정했습니다: {_sentence(detail['value'])}"
            )
    return texts


def _route_display_texts(
    details: Sequence[ActivityDetailTextSource], _state: str
) -> dict[int, str]:
    texts: dict[int, str] = {}
    for index, detail in enumerate(details):
        if detail["label"] not in {"검증된 조회 범위", "검증된 변경 범위"}:
            continue
        parts = [part.strip() for part in detail["value"].split("·") if part.strip()]
        scope = "의 ".join(parts[:2]) if len(parts) >= 2 else detail["value"]
        effect = parts[2] if len(parts) >= 3 else (
            "조회" if detail["label"] == "검증된 조회 범위" else "변경"
        )
        texts[index] = f"{scope} {effect} 경로를 준비했습니다."
    return texts


def _retrieval_display_texts(
    details: Sequence[ActivityDetailTextSource], _state: str
) -> dict[int, str]:
    texts: dict[int, str] = {}
    visible_labels = {
        "자료 조회",
        "조회 결과",
        "부족한 정보",
        "자료 조회 한계",
        "관련 근거",
        "자료 충족도",
        "조회 범위",
        "검색 진행",
        "자료 상세",
        "표시 한계",
    }
    for index, detail in enumerate(details):
        if detail["label"] == "선택 근거 제목":
            texts[index] = f"‘{detail['value']}’ 자료를 관련 근거로 확인했습니다."
        elif detail["label"] in visible_labels:
            texts[index] = _sentence(detail["value"])
    return texts


def _analysis_display_texts(
    details: Sequence[ActivityDetailTextSource], _state: str
) -> dict[int, str]:
    direct_labels = {"부족한 정보", "주의 사항", "판단 근거", "표시 한계"}
    fact_labels = {
        "Task",
        "일정",
        "관련 인물",
        "날짜",
        "시간",
        "마감",
        "상태",
        "업무 대상",
        "업무 사실",
    }
    texts: dict[int, str] = {}
    for index, detail in enumerate(details):
        label, value = detail["label"], detail["value"]
        if label in direct_labels:
            texts[index] = _sentence(value)
        elif label in fact_labels:
            texts[index] = f"{label} 관련 사실을 확인했습니다: {_sentence(value)}"
        elif label.endswith("관계"):
            texts[index] = f"{label}를 확인했습니다: {_sentence(value)}"
        elif label == "외부 실행 필요":
            texts[index] = (
                "요청을 완료하려면 외부 변경이 필요합니다."
                if value == "필요함"
                else "추가 외부 변경 없이 요청을 처리할 수 있습니다."
            )
    return texts


def _planning_display_texts(
    details: Sequence[ActivityDetailTextSource], _state: str
) -> dict[int, str]:
    texts: dict[int, str] = {}
    for index, detail in enumerate(details):
        if detail["label"] == "계획 종류":
            texts[index] = _sentence(detail["value"])

    action_details: dict[str, list[tuple[int, str, str]]] = {}
    for index, detail in enumerate(details):
        action, separator, field = detail["label"].partition(" · ")
        if separator and action.startswith("실행안 "):
            action_details.setdefault(action, []).append((index, field, detail["value"]))
    visible_fields = {
        "제목",
        "예정일",
        "시작",
        "종료",
        "시간대",
        "장소",
        "상태",
        "받는 사람",
        "참조",
        "숨은 참조",
        "참석자",
        "대상 Repository",
        "대상 Issue",
    }
    for action, values in action_details.items():
        plan = next(((index, value) for index, field, value in values if field == "계획"), None)
        if plan is None:
            continue
        effect = plan[1].split(" 예정", 1)[0]
        fields = [f"{field} {value}" for _, field, value in values if field in visible_fields]
        basis = f"{', '.join(fields)} 기준으로 " if fields else ""
        texts[plan[0]] = (
            f"{action}에서 {basis}{effect} 작업을 준비했습니다. "
            "아직 외부 변경은 실행하지 않았습니다."
        )
    return texts


def _review_display_texts(
    details: Sequence[ActivityDetailTextSource], _state: str
) -> dict[int, str]:
    status_texts = {
        "검토 통과": "작성한 계획이 요청과 안전 조건을 충족하는지 검토했습니다.",
        "수정 필요": "작성한 계획을 수정해야 한다고 판단했습니다.",
        "추가 자료 필요": "계획을 확정하려면 추가 자료가 필요합니다.",
        "자료 경로 재검토": "자료 경로를 다시 검토해야 합니다.",
        "사용자 확인 필요": "계획을 확정하려면 사용자 확인이 필요합니다.",
        "진행 차단": "현재 계획으로는 진행할 수 없습니다.",
    }
    texts: dict[int, str] = {}
    for index, detail in enumerate(details):
        label, value = detail["label"], detail["value"]
        if label == "검토 결과" and value in status_texts:
            texts[index] = status_texts[value]
        elif label in {"검토 요약", "검토 내용", "표시 한계"}:
            texts[index] = _sentence(value)
        elif label == "사용자 확인 질문":
            texts[index] = f"사용자 확인이 필요합니다: {_sentence(value)}"
    return texts


def _lifecycle_display_texts(
    details: Sequence[ActivityDetailTextSource], state: str
) -> dict[int, str]:
    texts: dict[int, str] = {}
    actual_prefix = "재조회 " if state == "RECORDED" else None
    hidden_targets = {
        "대상 Task List",
        "대상 Calendar",
        "대상 Thread",
        "대상 Draft",
        "대상 Task",
        "대상 Event",
    }
    for index, detail in enumerate(details):
        label, value = detail["label"], detail["value"]
        prefix, separator, field = label.partition(" ")
        if label == "복구 결정":
            texts[index] = f"복구 후속 처리 결정을 적용했습니다: {_sentence(value)}"
        elif separator and prefix in {"승인", "기대", "재조회"} and field not in hidden_targets:
            if actual_prefix is not None and prefix != actual_prefix.strip():
                continue
            source = {
                "승인": "승인에서 확정한",
                "기대": "승인에서 기대한",
                "재조회": "재조회한",
            }[prefix]
            texts[index] = f"{source} {field} 값은 {value}입니다."
    return texts


def _stage_one_display_texts(
    details: Sequence[ActivityDetailTextSource], state: str
) -> dict[int, str]:
    return _combine_display_texts(
        details,
        state,
        _request_display_texts,
        _route_display_texts,
        _retrieval_display_texts,
    )


def _stage_two_display_texts(
    details: Sequence[ActivityDetailTextSource], state: str
) -> dict[int, str]:
    return _combine_display_texts(
        details,
        state,
        _analysis_display_texts,
        _planning_display_texts,
    )


def _single_workflow_display_texts(
    details: Sequence[ActivityDetailTextSource], state: str
) -> dict[int, str]:
    return _combine_display_texts(
        details,
        state,
        _request_display_texts,
        _retrieval_display_texts,
        _analysis_display_texts,
        _planning_display_texts,
        _review_display_texts,
    )


def _combine_display_texts(
    details: Sequence[ActivityDetailTextSource],
    state: str,
    *projectors: ActivityDetailTextProjector,
) -> dict[int, str]:
    texts: dict[int, str] = {}
    for projector in projectors:
        texts.update(projector(details, state))
    return texts


def _values_for_label(
    details: Sequence[ActivityDetailTextSource], label: str
) -> list[str]:
    return list(dict.fromkeys(detail["value"] for detail in details if detail["label"] == label))


def _sentence(value: str) -> str:
    text = value.strip()
    return text if not text or text[-1] in ".!?。！？" else f"{text}."


__all__ = ["project_run_activity_detail_texts"]
