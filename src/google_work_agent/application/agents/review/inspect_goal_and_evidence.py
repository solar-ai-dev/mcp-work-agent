"""Inspect goal coverage and evidence grounding for Review."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from google_work_agent.application.agents.review.contracts.exact_calendar_create_plan import (
    is_exact_calendar_create_plan,
)
from google_work_agent.application.agents.review.contracts.exact_task_calendar_draft_plan import (
    is_exact_task_calendar_draft_plan,
)
from google_work_agent.application.agents.review.contracts.exact_task_create_plan import (
    is_exact_task_create_plan,
)
from google_work_agent.application.agents.review.contracts.review_findings import (
    ReviewDimensionIdV1,
    ReviewInspectorResultV1,
    ReviewSemanticInvoker,
    review_inspector_output_schema,
    validate_review_inspector_result,
)

PROMPT_ID = "review.inspect_goal_and_evidence"
DIMENSION: ReviewDimensionIdV1 = "review.inspect_goal_and_evidence"
REVIEW_INSPECT_GOAL_AND_EVIDENCE_OUTPUT_SCHEMA = review_inspector_output_schema(DIMENSION)


def inspect_goal_and_evidence(
    *,
    request_intent: Mapping[str, object],
    planning_result: Mapping[str, object],
    evidence: Sequence[Mapping[str, object]],
    invoke: ReviewSemanticInvoker,
    work_analysis: Mapping[str, object] | None = None,
    confirmation_response: Mapping[str, object] | None = None,
    user_action_modifications: Sequence[Mapping[str, object]] = (),
    run_reference_time: Mapping[str, object] | None = None,
) -> ReviewInspectorResultV1:
    if confirmation_response is None and (
        is_exact_calendar_create_plan(
            request_intent=request_intent,
            planning_result=planning_result,
        )
        or is_exact_task_create_plan(
            request_intent=request_intent,
            planning_result=planning_result,
            work_analysis=work_analysis,
        )
        or (
            not user_action_modifications
            and is_exact_task_calendar_draft_plan(
                request_intent=request_intent,
                planning_result=planning_result,
                evidence=evidence,
            )
        )
    ):
        return {"schema_version": 1, "dimension": DIMENSION, "findings": []}
    prompt_input: dict[str, object] = {
        "request_intent": dict(request_intent),
        "planning_result": dict(planning_result),
        "evidence": [dict(item) for item in evidence],
    }
    if work_analysis is not None:
        prompt_input["work_analysis"] = dict(work_analysis)
    if confirmation_response is not None:
        prompt_input["confirmation_response"] = dict(confirmation_response)
    if user_action_modifications:
        prompt_input["user_action_modifications"] = [
            dict(item) for item in user_action_modifications
        ]
    if run_reference_time is not None:
        prompt_input["run_reference_time"] = dict(run_reference_time)
    return validate_review_inspector_result(
        invoke(PROMPT_ID, prompt_input), expected_dimension=DIMENSION
    )


__all__ = [
    "REVIEW_INSPECT_GOAL_AND_EVIDENCE_OUTPUT_SCHEMA",
    "inspect_goal_and_evidence",
]
