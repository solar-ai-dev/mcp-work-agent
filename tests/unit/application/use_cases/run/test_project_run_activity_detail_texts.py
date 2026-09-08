"""User-facing sentence projection for persisted Run Activity facts."""

from google_work_agent.application.use_cases.run.project_run_activity_detail_texts import (
    project_run_activity_detail_texts,
)


def test_activity_detail_texts__with_request_facts__hide_internal_field_list() -> None:
    details = [
        {"label": "요청 업무", "value": "선택한 일정을 지정한 장소로 수정합니다"},
        {"label": "완료 조건", "value": "같은 Event를 다시 조회"},
        {"label": "요청 작업", "value": "수정"},
        {"label": "요청 대상", "value": "Google Calendar 일정"},
        {"label": "사용자 요청 · Calendar", "value": "opaque-calendar-id"},
        {"label": "사용자 확인 · 날짜", "value": "2026-09-14"},
    ]

    texts = project_run_activity_detail_texts(
        role="요청 분석", state="RECORDED", details=details
    )

    assert list(texts.values()) == [
        "선택한 일정을 지정한 장소로 수정합니다.",
        "사용자 확인으로 날짜 값을 확정했습니다: 2026-09-14.",
    ]
    assert "opaque-calendar-id" not in str(texts)


def test_activity_detail_texts__with_route_and_plan__separate_preparation_from_effect() -> None:
    route = [
        {
            "label": "검증된 조회 범위",
            "value": "Google Workspace · Google Calendar 일정 · 조회",
        },
        {
            "label": "검증된 변경 범위",
            "value": "Google Workspace · Google Calendar 일정 · 수정",
        },
    ]
    plan = [
        {"label": "실행안 1 · 계획", "value": "수정 예정 (아직 실행되지 않음)"},
        {"label": "실행안 1 · 제목", "value": "주간 프로젝트 회의"},
        {"label": "실행안 1 · 시작", "value": "2026-09-14T15:00:00+09:00"},
        {"label": "실행안 1 · 장소", "value": "회의실 A"},
        {"label": "실행안 1 · 대상 Event", "value": "opaque-event-id"},
    ]

    route_texts = project_run_activity_detail_texts(
        role="자료 경로 선택", state="RECORDED", details=route
    )
    plan_texts = project_run_activity_detail_texts(
        role="계획 생성", state="RECORDED", details=plan
    )

    assert list(route_texts.values()) == [
        "Google Workspace의 Google Calendar 일정 조회 경로를 준비했습니다.",
        "Google Workspace의 Google Calendar 일정 수정 경로를 준비했습니다.",
    ]
    assert "완료" not in str(route_texts)
    assert len(plan_texts) == 1
    assert "주간 프로젝트 회의" in plan_texts[0]
    assert "2026-09-14T15:00:00+09:00" in plan_texts[0]
    assert "회의실 A" in plan_texts[0]
    assert "아직 외부 변경은 실행하지 않았습니다" in plan_texts[0]
    assert "opaque-event-id" not in plan_texts[0]


def test_activity_detail_texts__with_combined_role__compose_owned_facts() -> None:
    details = [
        {"label": "요청 업무", "value": "분기 보고서 근거를 확인합니다"},
        {
            "label": "검증된 조회 범위",
            "value": "Google Workspace · Gmail Message · 조회",
        },
        {"label": "자료 조회", "value": "허용된 범위의 자료 조회를 완료했습니다."},
    ]

    texts = project_run_activity_detail_texts(
        role="요청 분석·자료 검색", state="RECORDED", details=details
    )

    assert list(texts.values()) == [
        "분기 보고서 근거를 확인합니다.",
        "Google Workspace의 Gmail Message 조회 경로를 준비했습니다.",
        "허용된 범위의 자료 조회를 완료했습니다.",
    ]


def test_activity_detail_texts__with_analysis_review_and_reread__separate_verified_facts() -> None:
    analysis = [
        {"label": "일정", "value": "주간 프로젝트 회의 · 9월 14일 오후 3시"},
        {"label": "선행 관계", "value": "자료 확인 → 일정 수정"},
        {"label": "외부 실행 필요", "value": "필요함"},
    ]
    review = [
        {"label": "검토 결과", "value": "검토 통과"},
        {"label": "검토 요약", "value": "승인 전에 변경 내용을 확인해야 합니다"},
        {"label": "검토 영향 범위", "value": "opaque-action-id"},
    ]
    verification = [
        {"label": "기대 제목", "value": "주간 프로젝트 회의"},
        {"label": "재조회 제목", "value": "주간 프로젝트 회의"},
        {"label": "재조회 대상 Event", "value": "opaque-event-id"},
    ]
    approval = [
        {"label": "승인 제목", "value": "주간 프로젝트 회의"},
        {"label": "승인 대상 Event", "value": "opaque-event-id"},
    ]

    analysis_texts = project_run_activity_detail_texts(
        role="업무 분석", state="RECORDED", details=analysis
    )
    review_texts = project_run_activity_detail_texts(
        role="계획 검토", state="RECORDED", details=review
    )
    verification_texts = project_run_activity_detail_texts(
        role="결과 검증", state="RECORDED", details=verification
    )
    approval_texts = project_run_activity_detail_texts(
        role="사용자 승인", state="RECORDED", details=approval
    )
    mismatch_texts = project_run_activity_detail_texts(
        role="결과 검증", state="PARTIAL", details=verification
    )

    assert list(analysis_texts.values()) == [
        "일정 관련 사실을 확인했습니다: 주간 프로젝트 회의 · 9월 14일 오후 3시.",
        "선행 관계를 확인했습니다: 자료 확인 → 일정 수정.",
        "요청을 완료하려면 외부 변경이 필요합니다.",
    ]
    assert list(review_texts.values()) == [
        "작성한 계획이 요청과 안전 조건을 충족하는지 검토했습니다.",
        "승인 전에 변경 내용을 확인해야 합니다.",
    ]
    assert list(verification_texts.values()) == [
        "재조회한 제목 값은 주간 프로젝트 회의입니다."
    ]
    assert list(approval_texts.values()) == [
        "승인에서 확정한 제목 값은 주간 프로젝트 회의입니다."
    ]
    assert list(mismatch_texts.values()) == [
        "승인에서 기대한 제목 값은 주간 프로젝트 회의입니다.",
        "재조회한 제목 값은 주간 프로젝트 회의입니다.",
    ]
    assert "opaque" not in str(
        (analysis_texts, review_texts, verification_texts, approval_texts, mismatch_texts)
    )
