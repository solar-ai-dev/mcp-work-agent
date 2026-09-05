"""Keep source-local relevance judgments during same-invocation detail hydration."""

from collections.abc import Sequence

from google_work_agent.application.agents.retrieval.contracts.query_plan import SourceFetchPlanV1
from google_work_agent.application.agents.retrieval.contracts.retrieval_result import (
    EvidenceSelectionResultV2,
)
from google_work_agent.application.agents.retrieval.normalize_segments import SourceSegment


def preferred_detail_evidence_ids(
    selection: EvidenceSelectionResultV2 | None,
    source_fetch_plans: Sequence[SourceFetchPlanV1],
) -> list[str]:
    """Protect existing source excerpts only while extending the same search by detail."""
    if selection is None or not source_fetch_plans or any(
        plan["operation_kind"] != "DETAIL_FETCH" for plan in source_fetch_plans
    ):
        return []
    return list(selection["selected_segment_ids"])


def retain_unchanged_evidence(
    selection: EvidenceSelectionResultV2 | None,
    *,
    source_fetch_plans: Sequence[SourceFetchPlanV1],
    segments: Sequence[SourceSegment],
) -> EvidenceSelectionResultV2 | None:
    """Never reuse judgments across search changes or for the hydrated resource.

    The caller supplies only the current invocation's previous selection and
    the plans just executed. Segment IDs bind content, version and provenance.
    This retains relevance, not entity resolution or factual truth.
    """
    if selection is None or not source_fetch_plans:
        return None
    if any(plan["operation_kind"] != "DETAIL_FETCH" for plan in source_fetch_plans):
        return None
    refreshed = {plan["detail_candidate_ref"] for plan in source_fetch_plans}
    if None in refreshed or "" in refreshed:
        raise ValueError("detail evidence reassessment requires validated candidate refs")
    selected = selection["selected_segment_ids"]
    excluded = selection["excluded_segment_ids"]
    draft_ids = [draft["segment_id"] for draft in selection["evidence_drafts"]]
    if (
        selection["schema_version"] != 2
        or len(selected) != len(set(selected))
        or len(excluded) != len(set(excluded))
        or len(draft_ids) != len(set(draft_ids))
        or set(draft_ids) != set(selected)
        or set(selected).intersection(excluded)
    ):
        raise ValueError("inconsistent prior evidence selection")
    by_id = {segment.segment_id: segment for segment in segments}
    if not set(selected).issubset(by_id):
        return None
    unchanged = {
        key for key in (*selected, *excluded)
        if key in by_id and by_id[key].resource_handle not in refreshed
    }
    return {
        "schema_version": 2,
        "evidence_drafts": [
            draft for draft in selection["evidence_drafts"] if draft["segment_id"] in unchanged
        ],
        "selected_segment_ids": [key for key in selected if key in unchanged],
        "excluded_segment_ids": [key for key in excluded if key in unchanged],
    }
