from google_work_agent.application.agents.planning.complete_analysis_answer_outline import (
    complete_analysis_answer_outline,
)


def test_complete_analysis_answer_outline__grounded_facts__deduplicates_allowed_refs() -> None:
    result = complete_analysis_answer_outline(
        user_request="업무 요약", request_intent={"analysis_requirement": "REQUIRED"},
        work_analysis={
            "work_facts": [{"subject": "검토", "value": "진행 중",
                            "evidence_refs": ["e1", "e1", "unknown"]}],
            "ambiguities": [{"description": "마감일 미확정"}],
        }, sections=["요약"], evidence_refs=["e1"], allowed_evidence_refs=["e1"],
    )
    assert result["evidence_refs"] == ["e1"]
    assert result["sections"] == [
        "요약",
        "확인된 업무 사실 — 검토: 진행 중",
        "불확실성 — 마감일 미확정",
    ]


def test_complete_analysis_answer_outline__analysis_not_required__preserves_outline() -> None:
    assert complete_analysis_answer_outline(
        user_request="메일 찾아줘", request_intent={"analysis_requirement": "NONE"},
        work_analysis={"work_facts": [{"subject": "extra", "value": "not requested"}]},
        sections=["찾은 메일"], evidence_refs=["e1"], allowed_evidence_refs=["e1"],
    ) == {"sections": ["찾은 메일"], "evidence_refs": ["e1"]}
