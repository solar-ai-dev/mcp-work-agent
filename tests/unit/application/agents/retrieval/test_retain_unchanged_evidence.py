"""Detail hydration may change its own preview judgment, not untouched evidence."""

from collections import deque
from typing import cast

import pytest
from tests.support.context_retrieval import (
    SELECT_PROMPT_REF,
    FakeLLMRuntime,
    llm_result,
    request_intent,
    run_budget,
)

from google_work_agent.application.agents.retrieval.contracts.query_plan import SourceFetchPlanV1
from google_work_agent.application.agents.retrieval.contracts.retrieval_result import (
    EvidenceSelectionResultV2,
)
from google_work_agent.application.agents.retrieval.normalize_segments import SourceSegment
from google_work_agent.application.agents.retrieval.retain_unchanged_evidence import (
    preferred_detail_evidence_ids,
    retain_unchanged_evidence,
)
from google_work_agent.application.agents.retrieval.select_evidence import select_evidence


def _selection() -> EvidenceSelectionResultV2:
    return {
        "schema_version": 2, "selected_segment_ids": ["kept", "preview"],
        "excluded_segment_ids": ["irrelevant"], "evidence_drafts": [
            {"segment_id": key, "role": "CONTEXT", "relevance_reason": "관련 행사 후보"}
            for key in ("kept", "preview")
        ],
    }


def _segments() -> list[SourceSegment]:
    return [
        SourceSegment(key, f"gmail_thread:{resource}", "GMAIL", "gmail_thread", resource,
                      None, None, {}, "실제 자료")
        for key, resource in (("kept", "a"), ("preview", "b"), ("body", "b"),
                              ("irrelevant", "c"))
    ]


def _plan(operation: str = "DETAIL_FETCH") -> SourceFetchPlanV1:
    return cast(SourceFetchPlanV1, {
        "operation_kind": operation, "detail_candidate_ref": "gmail_thread:b",
    })


def test_retain_evidence__unchanged_other_resources__preserves() -> None:
    assert preferred_detail_evidence_ids(_selection(), [_plan()]) == ["kept", "preview"]
    result = retain_unchanged_evidence(
        _selection(), source_fetch_plans=[_plan()], segments=_segments(),
    )
    assert result is not None
    assert result["selected_segment_ids"] == ["kept"]
    assert result["excluded_segment_ids"] == ["irrelevant"]


@pytest.mark.parametrize("operation", ["SEARCH", "NEXT_PAGE", "FREEBUSY"])
def test_retain_evidence__non_detail_round__requires_fresh_assessment(operation: str) -> None:
    assert preferred_detail_evidence_ids(_selection(), [_plan(operation)]) == []
    assert retain_unchanged_evidence(
        _selection(), source_fetch_plans=[_plan(operation)], segments=_segments(),
    ) is None


def test_retain_evidence__new_invocation_or_changed_segment__does_not_reuse() -> None:
    assert retain_unchanged_evidence(
        None, source_fetch_plans=[_plan()], segments=_segments(),
    ) is None
    assert retain_unchanged_evidence(
        _selection(), source_fetch_plans=[_plan()], segments=_segments()[1:],
    ) is None


def test_retain_evidence__inconsistent_checkpoint__does_not_silently_repair() -> None:
    selection = _selection()
    selection["excluded_segment_ids"].append("kept")
    with pytest.raises(ValueError, match="inconsistent prior"):
        retain_unchanged_evidence(
            selection, source_fetch_plans=[_plan()], segments=_segments(),
        )


@pytest.mark.parametrize("excluded", [[], ["kept"]])
def test_retain_evidence__detail_rejects_preview__keeps_other_sources(
    excluded: list[str],
) -> None:
    runtime = FakeLLMRuntime(deque([llm_result({
        "schema_version": 3, "segment_assessments": {
            key: {"role": "EXCLUDED", "relevance_reason": "본문에서 다른 행사로 확인됨"}
            for key in ("preview", "body")
        },
    })]))
    segments = _segments()
    result, _ = select_evidence(
        llm_runtime=runtime, prompt_ref=SELECT_PROMPT_REF, revision_prompt_ref=SELECT_PROMPT_REF,
        requested_mode="LOCAL_GPU",
        request_intent=request_intent(),
        retry_budget=run_budget(used=0),
        segments=segments, prior_selection=_selection(), source_fetch_plans=[_plan()],
        exclusion_obligation_segment_ids=excluded,
        rag_candidates=[{"segment_id": segment.segment_id,
                         "resource_ref": segment.resource_handle, "retrieval_score": 1.0,
                         "reason_codes": []} for segment in segments],
    )
    assert len(runtime.calls) == 1
    assert result["selected_segment_ids"] == ([] if excluded else ["kept"])
    assert set(result["excluded_segment_ids"]) == {"irrelevant", "preview", "body", *excluded}
    inputs = cast(dict[str, object], runtime.calls[0]["prompt_input"])
    ranked = cast(list[dict[str, object]], inputs["ranked_segments"])
    assert [item["segment_id"] for item in ranked] == ["preview", "body"]
    if excluded:
        assert "retained_evidence" not in inputs
    else:
        retained = cast(list[dict[str, object]], inputs["retained_evidence"])
        assert len(retained) == 1
        assert retained[0]["resource_ref"] == "gmail_thread:a"
        assert retained[0]["excerpt"] == "실제 자료"
        assert retained[0]["role"] == "CONTEXT"
