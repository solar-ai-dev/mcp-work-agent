from typing import TypedDict, cast

from google_work_agent.adapters.langgraph.subgraphs.work_analysis.state import (
    WorkAnalysisLocalState,
)
from google_work_agent.application.agents.request_understanding.contracts.request_intent import (
    RequestIntentV2,
)
from google_work_agent.application.agents.work_analysis.contracts.work_analysis_result import (
    WorkFactV1,
    WorkRelationV1,
)

from .retrieval_source_statuses_projection import project_retrieval_source_statuses
from .task_duplicate_review_requirement_projection import (
    project_task_duplicate_review_requirement,
)


class DetectDuplicateConflictCandidatesInput(TypedDict):
    work_facts: list[WorkFactV1]
    entity_relations: list[WorkRelationV1]
    evidence: list[dict[str, object]]
    source_state: dict[str, object]
    allowed_evidence_refs: set[str]
    request_intent: RequestIntentV2
    task_duplicate_review_required: bool


def project_detect_duplicate_conflict_candidates_input(
    state: WorkAnalysisLocalState,
) -> DetectDuplicateConflictCandidatesInput:
    required = (
        "request_intent",
        "tool_route_plan",
        "fact_candidates",
        "entity_relation_candidates",
        "evidence",
        "evidence_refs",
    )
    if any(key not in state for key in required):
        raise ValueError(
            "missing typed input projection for analysis.detect_duplicate_conflict_candidates"
        )
    retrieval = state.get("retrieval_result")
    selected_segment_ids = retrieval["selected_segment_ids"] if retrieval is not None else []
    excluded_segment_ids = retrieval["excluded_segment_ids"] if retrieval is not None else []
    return {
        "work_facts": list(state["fact_candidates"]),
        "entity_relations": list(state["entity_relation_candidates"]),
        "evidence": [dict(item) for item in state["evidence"]],
        "source_state": {
            "availability_results": list(state.get("availability_results", [])),
            "source_statuses": project_retrieval_source_statuses(state),
            "selected_segment_count": len(selected_segment_ids),
            "excluded_segment_count": len(excluded_segment_ids),
            "task_review_candidates": (
                []
                if retrieval is None
                else [dict(item) for item in retrieval.get("task_review_candidates", [])]
            ),
        },
        "allowed_evidence_refs": set(state["evidence_refs"]),
        "request_intent": cast(RequestIntentV2, state["request_intent"]),
        "task_duplicate_review_required": project_task_duplicate_review_requirement(state),
    }
