from google_work_agent.application.agents.request_understanding import (
    preserve_explicit_search_anchors as operation,
)
from google_work_agent.application.agents.request_understanding.contracts.request_intent import (
    RequestGoalCandidateV1,
)


def _candidate() -> RequestGoalCandidateV1:
    return {
        "goal": "메일 조회",
        "completion_conditions": ["자료 확인"],
        "constraints": [
            {"kind": "DATE", "field": "period", "value": ["9월 첫째주"]},
            {"kind": "TIME", "field": "temporal_axis", "value": ["EVENT_TIME"]},
            {"kind": "PERSON", "field": "person", "value": ["김대리"]},
        ],
        "requested_effect_hints": ["READ"],
        "requested_resource_hints": ["GMAIL_THREAD"],
        "analysis_requirement": "NONE",
    }


def test_semantic_slots__with_request_keywords__remain_model_owned() -> None:
    candidate = _candidate()

    result = operation.preserve_explicit_search_anchors(
        candidate,
        request_text="9월 첫째주에 김대리에게 온 메일을 분석해줘.",
        entry_mode="AGENT_SEARCH",
    )

    fields = {item["field"]: item["value"] for item in result["constraints"]}
    assert fields["period"] == ["9월 첫째주"]
    assert fields["temporal_axis"] == ["EVENT_TIME"]
    assert fields["person"] == ["김대리"]
    assert result["analysis_requirement"] == "NONE"
    assert fields["original_search_request"] == [
        "9월 첫째주에 김대리에게 온 메일을 분석해줘."
    ]


def test_explicit_subject__with_competing_anchors__replaces_only_lexical_values() -> None:
    candidate = _candidate()
    candidate["constraints"].append(
        {"kind": "USER_REQUIREMENT", "field": "search_terms", "value": ["검증"]}
    )

    result = operation.preserve_explicit_search_anchors(
        candidate,
        request_text="제목이 '절대로 존재하지 않는 3/8 검증 메일'인 메일을 찾아줘.",
        entry_mode="AGENT_SEARCH",
    )

    fields = {item["field"]: item["value"] for item in result["constraints"]}
    assert fields["subject"] == ["절대로 존재하지 않는 3/8 검증 메일"]
    assert "search_terms" not in fields
    assert fields["period"] == ["9월 첫째주"]
    assert fields["temporal_axis"] == ["EVENT_TIME"]


def test_unstated_placeholder__without_source_value__is_removed() -> None:
    candidate = _candidate()
    candidate["constraints"].append(
        {"kind": "USER_REQUIREMENT", "field": "required_information", "value": ["N/A"]}
    )

    result = operation.preserve_explicit_search_anchors(
        candidate,
        request_text="관련 메일을 찾아줘.",
        entry_mode="AGENT_SEARCH",
    )

    assert not any(item["field"] == "required_information" for item in result["constraints"])


def test_inferred_anchor__with_source_spacing__restores_exact_text() -> None:
    candidate = _candidate()
    candidate["constraints"].append(
        {"kind": "USER_REQUIREMENT", "field": "search_terms", "value": ["오로라 현장"]}
    )
    candidate["constraints"][2] = {
        "kind": "PERSON",
        "field": "person",
        "value": ["김 대리"],
    }

    result = operation.preserve_explicit_search_anchors(
        candidate,
        request_text="오로라 현장의 김대리와 잡힌 일정을 메일에서 확인해줘.",
        entry_mode="AGENT_SEARCH",
    )

    fields = {item["field"]: item["value"] for item in result["constraints"]}
    assert fields["search_terms"] == ["오로라 현장"]
    assert fields["person"] == ["김대리"]


def test_business_concept__paraphrase__is_not_removed_by_substring_guard() -> None:
    candidate = _candidate()
    candidate["constraints"].extend(
        [
            {
                "kind": "USER_REQUIREMENT",
                "field": "business_concepts",
                "value": ["현장 교육"],
            },
            {
                "kind": "USER_REQUIREMENT",
                "field": "search_terms",
                "value": ["오로라 연수"],
            },
        ]
    )

    result = operation.preserve_explicit_search_anchors(
        candidate,
        request_text="오로라 참여자의 연수 일정을 확인해줘.",
        entry_mode="AGENT_SEARCH",
    )

    fields = {item["field"]: item["value"] for item in result["constraints"]}
    assert fields["business_concepts"] == ["현장 교육"]
    assert "search_terms" not in fields


def test_repeated_explicit_anchor__remains_source_bound() -> None:
    candidate = _candidate()
    candidate["constraints"].append(
        {"kind": "USER_REQUIREMENT", "field": "search_terms", "value": ["Nimbus"]}
    )

    result = operation.preserve_explicit_search_anchors(
        candidate,
        request_text="Nimbus 출시와 Nimbus 일정 변경을 메일에서 확인해줘.",
        entry_mode="AGENT_SEARCH",
    )

    fields = {item["field"]: item["value"] for item in result["constraints"]}
    assert fields["search_terms"] == ["Nimbus"]


def test_explicit_relative_period__without_year__preserves_source_text() -> None:
    candidate = _candidate()
    candidate["constraints"][0] = {
        "kind": "DATE",
        "field": "period",
        "value": ["2025-09-01 ~ 2025-09-07"],
    }

    result = operation.preserve_explicit_search_anchors(
        candidate,
        request_text="오로라 참여자의 9월 첫째주 연수 날짜를 메일에서 확인해줘.",
        entry_mode="AGENT_SEARCH",
    )

    fields = {item["field"]: item["value"] for item in result["constraints"]}
    assert fields["period"] == ["9월 첫째주"]
    assert fields["temporal_axis"] == ["EVENT_TIME"]


def test_non_gmail_candidate__during_anchor_preservation__is_unchanged() -> None:
    candidate = _candidate()
    candidate["requested_resource_hints"] = ["TASK"]

    assert operation.preserve_explicit_search_anchors(
        candidate,
        request_text="태스크를 보여줘.",
        entry_mode="AGENT_SEARCH",
    ) is candidate


def test_github_candidate__with_explicit_repository__restores_identity_from_request() -> None:
    candidate = _candidate()
    candidate["constraints"] = []
    candidate["requested_resource_hints"] = ["GITHUB_ISSUE"]

    result = operation.preserve_explicit_search_anchors(
        candidate,
        request_text="List open issues in acme/search-save.",
        entry_mode="AGENT_SEARCH",
    )

    assert result["constraints"] == [
        {"kind": "RESOURCE", "field": "repository", "value": "acme/search-save"}
    ]


def test_github_candidate__with_bare_project_name__does_not_infer_repository() -> None:
    candidate = _candidate()
    candidate["constraints"] = []
    candidate["requested_resource_hints"] = ["GITHUB_ISSUE"]

    result = operation.preserve_explicit_search_anchors(
        candidate,
        request_text="search-save 저장소의 열린 이슈를 조회해줘.",
        entry_mode="AGENT_SEARCH",
    )

    assert result is candidate


def test_gmail_draft_source_update__with_quoted_anchor__separates_status_scope() -> None:
    request = (
        "임시보관함의 “Quartz 납품 회신 검토” 초안 끝에 "
        "“8월 21일 입고 준비를 확인 중입니다.”만 추가해줘. 보내지는 마."
    )
    candidate = _candidate()
    candidate["constraints"] = [
        {
            "kind": "USER_REQUIREMENT",
            "field": "search_terms",
            "value": ['"임시보관함"', '"Quartz 납품 회신 검토"'],
        },
        {
            "kind": "USER_REQUIREMENT",
            "field": "required_information",
            "value": ["8월 21일 입고 준비 상태"],
        },
        {"kind": "SCOPE", "field": "status", "value": ["초안"]},
    ]
    candidate["requested_effect_hints"] = ["UPDATE"]
    candidate["requested_resource_hints"] = ["GMAIL_DRAFT"]

    result = operation.preserve_explicit_search_anchors(
        candidate,
        request_text=request,
        entry_mode="AGENT_SEARCH",
    )

    fields = {item["field"]: item["value"] for item in result["constraints"]}
    assert fields["search_terms"] == ["Quartz 납품 회신 검토"]
    assert fields["status"] == ["초안"]
    assert fields["required_information"] == ["8월 21일 입고 준비 상태"]
    assert fields["original_search_request"] == [request]


def test_gmail_draft_source__with_status_word_as_subject__preserves_lexical_value() -> None:
    request = "제목에 임시보관함이 들어간 초안을 찾아줘."
    candidate = _candidate()
    candidate["constraints"] = [
        {"kind": "RESOURCE", "field": "subject", "value": ["임시보관함"]},
        {
            "kind": "USER_REQUIREMENT",
            "field": "search_terms",
            "value": ["임시보관함"],
        },
        {"kind": "SCOPE", "field": "status", "value": ["초안"]},
    ]
    candidate["requested_resource_hints"] = ["GMAIL_DRAFT"]

    result = operation.preserve_explicit_search_anchors(
        candidate,
        request_text=request,
        entry_mode="AGENT_SEARCH",
    )

    fields = {item["field"]: item["value"] for item in result["constraints"]}
    assert fields["subject"] == ["임시보관함"]
    assert fields["status"] == ["초안"]
    assert "search_terms" not in fields


def test_gmail_draft_candidate__with_explicit_id__restores_exact_anchor() -> None:
    candidate = _candidate()
    candidate["constraints"] = [
        {"kind": "RESOURCE", "field": "draft_id", "value": "invented-draft"}
    ]
    candidate["requested_effect_hints"] = ["UPDATE"]
    candidate["requested_resource_hints"] = ["GMAIL_DRAFT"]

    result = operation.preserve_explicit_search_anchors(
        candidate,
        request_text="Gmail 초안 ID r976635311795334843를 수정해줘.",
        entry_mode="AGENT_SEARCH",
    )

    assert result["constraints"] == [
        {"kind": "RESOURCE", "field": "draft_id", "value": "r976635311795334843"}
    ]


def test_gmail_draft_candidate__without_explicit_id__does_not_infer_anchor() -> None:
    candidate = _candidate()
    candidate["constraints"] = []
    candidate["requested_effect_hints"] = ["UPDATE"]
    candidate["requested_resource_hints"] = ["GMAIL_DRAFT"]

    result = operation.preserve_explicit_search_anchors(
        candidate,
        request_text="방금 만든 Gmail 초안을 수정해줘.",
        entry_mode="AGENT_SEARCH",
    )

    assert result is candidate


def test_gmail_draft_candidate__draft_word_in_subject__is_not_an_identifier() -> None:
    candidate = _candidate()
    candidate["constraints"] = []
    candidate["requested_effect_hints"] = ["UPDATE"]
    candidate["requested_resource_hints"] = ["GMAIL_DRAFT"]

    result = operation.preserve_explicit_search_anchors(
        candidate,
        request_text=(
            "Gmail 초안 ID draft-123를 수정하고 제목은 "
            '"[GWA E2E] Draft updated"로 바꿔.'
        ),
        entry_mode="AGENT_SEARCH",
    )

    assert result["constraints"] == [
        {"kind": "RESOURCE", "field": "draft_id", "value": "draft-123"}
    ]
