from typing import TypedDict

from google_work_agent.adapters.langgraph.subgraphs.work_analysis.state import (
    WorkAnalysisLocalState,
)
from google_work_agent.application.agents.work_analysis import (
    detect_duplicate_conflict_candidates as duplicate_conflict_detector,
)
from google_work_agent.application.agents.work_analysis.contracts.work_analysis_candidates import (
    DuplicateConflictAssessmentV1,
)
from google_work_agent.application.agents.work_analysis.contracts.work_analysis_result import (
    WorkRelationV1,
)
from google_work_agent.application.use_cases.run.guard_run_budget import RunBudgetV2
from google_work_agent.ports.llm.structured_inference_contracts import PromptReference
from google_work_agent.ports.llm.structured_inference_port import StructuredInferencePort
from google_work_agent.ports.system.contracts.workflow_handoff import RequestedModeV1

from ..projections.detect_duplicate_conflict_candidates_projection import (
    project_detect_duplicate_conflict_candidates_input,
)

_detect_duplicate_conflicts = (
    duplicate_conflict_detector.detect_duplicate_conflict_candidates_with_budget
)


class _DetectDuplicateConflictCandidatesUpdate(TypedDict):
    duplicate_conflict_candidates: list[WorkRelationV1]
    duplicate_conflict_assessment: DuplicateConflictAssessmentV1
    retry_budget: RunBudgetV2


def detect_duplicate_conflict_candidates_node(
    state: WorkAnalysisLocalState,
    *,
    llm_runtime: StructuredInferencePort,
    prompt_ref: PromptReference,
    task_satisfaction_prompt_ref: PromptReference,
    requested_mode: RequestedModeV1,
    confirmation_response: dict[str, object] | None = None,
) -> _DetectDuplicateConflictCandidatesUpdate:
    assessment, retry_budget = _detect_duplicate_conflicts(
        **project_detect_duplicate_conflict_candidates_input(state),
        llm_runtime=llm_runtime,
        prompt_ref=prompt_ref,
        task_satisfaction_prompt_ref=task_satisfaction_prompt_ref,
        requested_mode=requested_mode,
        retry_budget=state["retry_budget"],
        confirmation_response=confirmation_response,
    )
    return {
        "duplicate_conflict_candidates": assessment["relation_candidates"],
        "duplicate_conflict_assessment": assessment,
        "retry_budget": retry_budget,
    }
