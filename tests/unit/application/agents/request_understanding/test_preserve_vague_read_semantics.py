from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from google_work_agent.application.agents.request_understanding import (
    preserve_vague_read_semantics as operation,
)
from google_work_agent.application.agents.request_understanding.contracts.request_intent import (
    RequestGoalCandidateV1,
)
from google_work_agent.application.agents.retrieval.resolve_relative_period import (
    resolve_relative_period,
)


def _candidate() -> RequestGoalCandidateV1:
    return {
        "goal": "Find and analyze meeting email",
        "completion_conditions": ["Provide schedule"],
        "constraints": [
            {"kind": "DATE", "field": "start", "value": "N/A"},
            {"kind": "TIME", "field": "timezone", "value": "Asia/Seoul"},
        ],
        "requested_effect_hints": ["READ"],
        "requested_resource_hints": ["GMAIL_THREAD"],
        "analysis_requirement": "REQUIRED",
    }


def test_period_only_listing__model_business_topics__does_not_inherit() -> None:
    candidate = _candidate()
    candidate["constraints"].extend([
        {"kind": "USER_REQUIREMENT", "field": "business_concepts", "value": ["일정 관련 메일"]},
        {"kind": "USER_REQUIREMENT", "field": "search_terms", "value": ["일정"]},
    ])
    result = operation.preserve_vague_read_semantics(
        candidate, request_text="9월 첫째주에 온 메일 찾아줘.", entry_mode="AGENT_SEARCH",
    )
    by_field = {item["field"]: item["value"] for item in result["constraints"]}
    assert "business_concepts" not in by_field
    assert "search_terms" not in by_field
    assert by_field["temporal_axis"] == ["MESSAGE_TIME"]
    assert candidate["constraints"][-1]["value"] == ["일정"]


@pytest.mark.parametrize(
    ("request_text", "axis"),
    [
        ("9월 첫째주에 온 메일 찾아줘", "MESSAGE_TIME"),
        ("9월 첫째주 일정 메일 찾아줘", "EVENT_TIME"),
        ("2026년 9월 첫째주 체육대회 메일 찾아줘", "EVENT_TIME"),
        ("이번주에 받은 회의 메일", "MESSAGE_TIME"),
        ("다음주에 열리는 박람회 관련 메일", "EVENT_TIME"),
        ("다음주 발대식 관련 메일", "EVENT_TIME"),
    ],
)
def test_temporal_meaning__event_request__preserves_separately_from_receipt(
    request_text: str, axis: str
) -> None:
    candidate = _candidate()
    candidate["constraints"].append({"kind": "TIME", "field": "temporal_axis", "value": [axis]})
    result = operation.preserve_vague_read_semantics(
        candidate,
        request_text=request_text,
        entry_mode="AGENT_SEARCH",
    )
    fields = {item["field"]: item["value"] for item in result["constraints"]}
    assert fields["temporal_axis"] == [axis]
    assert fields["period"]


def test_relative_period__llm_invented_bounds__does_not_keep() -> None:
    candidate = _candidate()
    candidate["constraints"] += [
        {"kind": "DATE", "field": "date_period_start", "value": "2026-09-07"},
        {"kind": "DATE", "field": "date_period_end", "value": "2026-09-13"},
    ]
    result = operation.preserve_vague_read_semantics(
        candidate, request_text="9월 첫째주 일정 메일 찾아줘", entry_mode="AGENT_SEARCH"
    )
    fields = {item["field"]: item["value"] for item in result["constraints"]}
    assert fields["period"] == ["9월첫째주"]
    assert "date_period_start" not in fields
    assert "date_period_end" not in fields


def test_explicit_day__day_request__does_not_expand_to_month() -> None:
    result = operation.preserve_vague_read_semantics(
        _candidate(), request_text="9월 3일 체육대회 관련 메일 찾아줘", entry_mode="AGENT_SEARCH"
    )
    assert not any(item["field"] == "period" for item in result["constraints"])


def test_model_periods__duplicate_values__cannot_override_receipt_axis_or_run_year() -> None:
    candidate = _candidate()
    candidate["constraints"] += [
        {"kind": "DATE", "field": "period", "value": "2025-09-01T00:00:00Z"},
        {"kind": "DATE", "field": "period", "value": "2025-09-07T23:59:59Z"},
        {"kind": "TIME", "field": "temporal_axis", "value": "EVENT_TIME"},
        {"kind": "TIME", "field": "temporal_axis", "value": "EVENT_TIME"},
    ]
    result = operation.preserve_vague_read_semantics(
        candidate, request_text="9월 첫째주에 받은 메일 찾아줘.", entry_mode="AGENT_SEARCH"
    )
    constraints = result["constraints"]
    assert len([item for item in constraints if item["field"] == "period"]) == 1
    assert len([item for item in constraints if item["field"] == "temporal_axis"]) == 1
    resolved = resolve_relative_period(
        constraints, timezone="Asia/Seoul",
        now_ms=int(datetime(2026, 9, 6, tzinfo=ZoneInfo("Asia/Seoul")).timestamp() * 1000),
    )
    assert resolved == {
        "kind": "TEMPORAL_RANGE", "axis": "MESSAGE_TIME",
        "start_local": "2026-09-01T00:00:00", "end_local": "2026-09-08T00:00:00",
        "timezone": "Asia/Seoul",
    }
    assert candidate["constraints"][-1]["value"] == "EVENT_TIME"


def test_temporal_meaning__unresolved_role__does_not_default_to_receipt() -> None:
    result = operation.preserve_vague_read_semantics(
        _candidate(), request_text="9월 첫째주 관련 메일 찾아줘", entry_mode="AGENT_SEARCH",
    )
    assert not any(item["field"] == "temporal_axis" for item in result["constraints"])


def test_vague_read_semantics__placeholder__preserves_request_without_inventing_topic() -> None:
    result = operation.preserve_vague_read_semantics(
        _candidate(),
        request_text="회의 관련 메일이 있는데 그거 분석해서 일정 정리해줘.",
        entry_mode="AGENT_SEARCH",
    )

    by_field = {constraint["field"]: constraint["value"] for constraint in result["constraints"]}
    assert "start" not in by_field
    assert by_field["timezone"] == "Asia/Seoul"
    assert by_field["original_search_request"] == [
        "회의 관련 메일이 있는데 그거 분석해서 일정 정리해줘."
    ]
    assert "search_terms" not in by_field
    assert by_field["required_information"] == ["일정"]


def test_vague_read_semantics__people_periods_and_topics__preserves() -> None:
    result = operation.preserve_vague_read_semantics(
        _candidate(),
        request_text="지난주에 김대리와 이야기했던 프로젝트 일정 메일을 찾아봐.",
        entry_mode="AGENT_SEARCH",
    )

    by_field = {constraint["field"]: constraint["value"] for constraint in result["constraints"]}
    assert by_field["person"] == ["김대리"]
    assert by_field["period"] == ["지난주"]
    assert "search_terms" not in by_field


def test_vague_read_semantics__discussion_verbs__does_not_use_as_search_terms() -> None:
    result = operation.preserve_vague_read_semantics(
        _candidate(),
        request_text="지난주에 프로젝트 일정 얘기한 메일 찾아서 해야 할 일 정리해줘.",
        entry_mode="AGENT_SEARCH",
    )

    by_field = {constraint["field"]: constraint["value"] for constraint in result["constraints"]}
    assert by_field["period"] == ["지난주"]
    assert "search_terms" not in by_field


def test_gmail_subject__explicit_literal__replaces_broad_search_terms() -> None:
    request_text = (
        "Gmail에서 제목이 '절대로 존재하지 않는 3/8 검증 메일 20260905'인 메일을 찾아 분석해줘."
    )
    candidate = _candidate()
    candidate["constraints"] = [
        {
            "kind": "RESOURCE",
            "field": "search_terms",
            "value": "제목:절대로 존재하지 않는 3/8 검증 메일 20260905",
        },
        {"kind": "USER_REQUIREMENT", "field": "search_terms", "value": ["검증"]},
    ]
    result = operation.preserve_vague_read_semantics(
        candidate,
        request_text=request_text,
        entry_mode="AGENT_SEARCH",
    )

    by_field = {constraint["field"]: constraint["value"] for constraint in result["constraints"]}
    assert by_field["subject"] == ["절대로 존재하지 않는 3/8 검증 메일 20260905"]
    assert "search_terms" not in by_field


def test_vague_read_semantics__model_topic__is_not_replaced_by_last_word_before_mail() -> None:
    candidate = _candidate()
    candidate["constraints"].append(
        {
            "kind": "USER_REQUIREMENT",
            "field": "search_terms",
            "value": ["협업 프로젝트"],
        }
    )

    result = operation.preserve_vague_read_semantics(
        candidate,
        request_text="협업 프로젝트와 관련된 메일을 실제 메일의 근거로 정리해줘.",
        entry_mode="AGENT_SEARCH",
    )

    by_field = {constraint["field"]: constraint["value"] for constraint in result["constraints"]}
    assert by_field["search_terms"] == ["협업 프로젝트"]
    assert "business_concepts" not in by_field


def test_vague_read_semantics__answer_information__does_not_make_query_text() -> None:
    result = operation.preserve_vague_read_semantics(
        _candidate(),
        request_text="최근 회의 메일 중 아직 후속 작업이 안 된 내용과 최신 결정을 정리해줘.",
        entry_mode="AGENT_SEARCH",
    )

    by_field = {constraint["field"]: constraint["value"] for constraint in result["constraints"]}
    assert by_field["period"] == ["최근"]
    assert "search_terms" not in by_field
    assert by_field["required_information"] == ["후속 작업", "최신 결정"]


def test_mail_to_task__source_search__preserves_write_intent() -> None:
    candidate = _candidate()
    candidate["requested_effect_hints"] = ["READ", "CREATE"]
    candidate["requested_resource_hints"] = ["GMAIL_THREAD", "TASK"]
    candidate["constraints"] = [
        {"kind": "USER_REQUIREMENT", "field": "search_terms", "value": "런타임 검증 회의"},
        {"kind": "RESOURCE", "field": "task_list", "value": "기본 목록"},
    ]
    request = "런타임 검증 회의 관련 메일을 찾아서 후속 업무를 Google Tasks에 등록해줘."
    result = operation.preserve_vague_read_semantics(
        candidate,
        request_text=request,
        entry_mode="AGENT_SEARCH",
    )
    by_field = {item["field"]: item["value"] for item in result["constraints"]}
    assert by_field["original_search_request"] == [request]
    assert by_field["search_terms"] == "런타임 검증 회의"
    assert by_field["required_information"] == ["후속 작업"]
    assert by_field["task_list"] == "기본 목록"
    assert result["requested_effect_hints"] == ["READ", "CREATE"]
    assert result["requested_resource_hints"] == ["GMAIL_THREAD", "TASK"]
