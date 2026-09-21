from __future__ import annotations

from collections.abc import Mapping
from typing import TypedDict, cast

from google_work_agent.application.agents.request_understanding.contracts.request_intent import (
    RequestIntentV3,
)
from google_work_agent.application.agents.work_analysis.contracts.work_analysis_candidates import (
    DuplicateConflictAssessmentV1,
)
from google_work_agent.application.agents.work_analysis.contracts.work_analysis_result import (
    WorkFactV1,
)

from .retrieval_source_statuses_projection import project_retrieval_source_statuses


class AssessActionNecessityInput(TypedDict):
    request_intent: RequestIntentV3
    output_routes: list[dict[str, object]]
    work_facts: list[WorkFactV1]
    evidence: list[dict[str, object]]
    source_statuses: list[dict[str, object]]
    task_review_candidates: list[dict[str, object]]
    duplicate_conflict_assessment: DuplicateConflictAssessmentV1
    allowed_evidence_refs: set[str]


def project_assess_action_necessity_input(
    state: Mapping[str, object],
) -> AssessActionNecessityInput:
    required = (
        "request_intent",
        "tool_route_plan",
        "fact_candidates",
        "evidence",
        "evidence_refs",
        "duplicate_conflict_assessment",
    )
    if any(key not in state for key in required):
        raise ValueError("missing typed input projection for analysis.assess_action_necessity")
    plan = state["tool_route_plan"]
    if not isinstance(plan, Mapping) or not isinstance(plan.get("output_plan"), Mapping):
        raise ValueError("action necessity requires the frozen output plan")
    output_plan = cast(Mapping[str, object], plan["output_plan"])
    raw_routes = output_plan.get("output_routes", [])
    if not isinstance(raw_routes, list):
        raise ValueError("ACTION output routes must be a list")
    routes = raw_routes
    retrieval = state.get("retrieval_result")
    candidates = (
        retrieval.get("task_review_candidates", [])
        if isinstance(retrieval, Mapping)
        else []
    )
    if not isinstance(candidates, list) or not all(
        isinstance(item, Mapping) for item in candidates
    ):
        raise ValueError("Task review candidate projection is invalid")
    return {
        "request_intent": cast(RequestIntentV3, state["request_intent"]),
        "output_routes": [dict(item) for item in routes if isinstance(item, Mapping)],
        "work_facts": cast(list[WorkFactV1], state["fact_candidates"]),
        "evidence": [dict(item) for item in cast(list[dict[str, object]], state["evidence"])],
        "source_statuses": project_retrieval_source_statuses(state),
        "task_review_candidates": [
            dict(item) for item in cast(list[Mapping[str, object]], candidates)
        ],
        "duplicate_conflict_assessment": cast(
            DuplicateConflictAssessmentV1, state["duplicate_conflict_assessment"]
        ),
        "allowed_evidence_refs": set(cast(list[str], state["evidence_refs"])),
    }


__all__ = ["AssessActionNecessityInput", "project_assess_action_necessity_input"]
