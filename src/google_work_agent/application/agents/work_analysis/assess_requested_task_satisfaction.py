"""Assess whether current Task observations already satisfy the requested work."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from copy import deepcopy
from typing import cast

from google_work_agent.application.agents.work_analysis.contracts.work_analysis_candidates import (
    DuplicateConflictAssessmentV1,
)
from google_work_agent.application.agents.work_analysis.contracts.work_analysis_result import (
    WorkFactV1,
)
from google_work_agent.application.prompt_runtime.contracts.failure_record import (
    build_failure_record_v1,
)
from google_work_agent.application.use_cases.run.account_provider_dispatch import (
    merge_provider_dispatch_usage,
    provider_dispatch_budget_scope,
)
from google_work_agent.application.use_cases.run.guard_run_budget import (
    BudgetDecision,
    RunBudgetV2,
    approve_semantic_revision,
    build_semantic_failure_signature_v1,
)
from google_work_agent.ports.llm.output_schema_validation import validate_output_schema
from google_work_agent.ports.llm.structured_inference_contracts import (
    OutputSchemaDefinition,
    PromptReference,
)
from google_work_agent.ports.llm.structured_inference_port import StructuredInferencePort
from google_work_agent.ports.system.contracts.workflow_handoff import RequestedModeV1

REQUESTED_TASK_SATISFACTION_OUTPUT_SCHEMA = OutputSchemaDefinition(
    schema_version="requested-task-satisfaction-v1",
    json_schema={
        "type": "object",
        "required": [
            "requested_work_status",
            "requested_work_reason",
            "matched_fact_ids",
            "matched_candidate_refs",
            "evidence_refs",
        ],
        "additionalProperties": False,
        "properties": {
            "requested_work_status": {"enum": ["SATISFIED", "NOT_SATISFIED", "UNDETERMINED"]},
            "requested_work_reason": {"type": "string", "minLength": 1},
            "matched_fact_ids": {
                "type": "array",
                "uniqueItems": True,
                "items": {"type": "string", "minLength": 1},
            },
            "matched_candidate_refs": {
                "type": "array",
                "uniqueItems": True,
                "items": {"type": "string", "minLength": 1},
            },
            "evidence_refs": {
                "type": "array",
                "uniqueItems": True,
                "items": {"type": "string", "minLength": 1},
            },
        },
    },
)


class RequestedTaskSatisfactionSemanticValidationError(ValueError):
    reason_code = "REQUESTED_TASK_SATISFACTION_SEMANTIC_INVALID"
    affected_field_paths = (
        "$.requested_work_status",
        "$.matched_fact_ids",
        "$.matched_candidate_refs",
        "$.evidence_refs",
    )


def assess_requested_task_satisfaction(
    *,
    work_facts: Sequence[WorkFactV1],
    evidence: list[dict[str, object]],
    source_state: Mapping[str, object],
    request_intent: Mapping[str, object],
    llm_runtime: StructuredInferencePort,
    prompt_ref: PromptReference,
    allowed_evidence_refs: set[str],
    requested_mode: RequestedModeV1,
    confirmation_response: dict[str, object] | None = None,
) -> DuplicateConflictAssessmentV1:
    prompt_input = _prompt_input(
        work_facts=work_facts,
        evidence=evidence,
        source_state=source_state,
        request_intent=request_intent,
        confirmation_response=confirmation_response,
    )
    fact_ids = {fact["fact_id"] for fact in work_facts}
    candidate_refs = _task_candidate_refs(source_state)
    output_schema = _bound_output_schema(fact_ids, allowed_evidence_refs, candidate_refs)
    result = llm_runtime.infer(requested_mode, prompt_ref, prompt_input, output_schema)
    return _validate_and_materialize(
        result.structured_output,
        output_schema=output_schema,
        fact_ids=fact_ids,
        allowed_evidence_refs=allowed_evidence_refs,
        candidate_refs=candidate_refs,
        source_state=source_state,
        work_facts=work_facts,
    )


def assess_requested_task_satisfaction_with_budget(
    *,
    work_facts: Sequence[WorkFactV1],
    evidence: list[dict[str, object]],
    source_state: Mapping[str, object],
    request_intent: Mapping[str, object],
    llm_runtime: StructuredInferencePort,
    prompt_ref: PromptReference,
    allowed_evidence_refs: set[str],
    requested_mode: RequestedModeV1,
    retry_budget: RunBudgetV2,
    confirmation_response: dict[str, object] | None = None,
) -> tuple[DuplicateConflictAssessmentV1, RunBudgetV2]:
    prompt_input = _prompt_input(
        work_facts=work_facts,
        evidence=evidence,
        source_state=source_state,
        request_intent=request_intent,
        confirmation_response=confirmation_response,
    )
    fact_ids = {fact["fact_id"] for fact in work_facts}
    candidate_refs = _task_candidate_refs(source_state)
    output_schema = _bound_output_schema(fact_ids, allowed_evidence_refs, candidate_refs)
    with provider_dispatch_budget_scope(retry_budget):
        result = llm_runtime.infer(requested_mode, prompt_ref, prompt_input, output_schema)
        try:
            assessment = _validate_and_materialize(
                result.structured_output,
                output_schema=output_schema,
                fact_ids=fact_ids,
                allowed_evidence_refs=allowed_evidence_refs,
                candidate_refs=candidate_refs,
                source_state=source_state,
                work_facts=work_facts,
            )
        except RequestedTaskSatisfactionSemanticValidationError as error:
            signature = build_semantic_failure_signature_v1(
                node_id="analysis.assess_requested_task_satisfaction",
                failure_reason_codes=[error.reason_code],
            )
            decision = approve_semantic_revision(retry_budget, signature=signature)
            if decision["decision"] == BudgetDecision.DENY.value:
                raise
            revised = llm_runtime.infer(
                requested_mode,
                prompt_ref,
                {
                    "base_projection": prompt_input,
                    "candidate_output": result.structured_output,
                    "failure_record": build_failure_record_v1(
                        failure_reason_code=error.reason_code,
                        failure_origin="LLM_OUTPUT",
                        detected_by="RUNTIME_DOMAIN_VALIDATOR",
                        runtime_disposition="RETRYABLE",
                        experiment_disposition="RUN_REVISION",
                        affected_field_paths=list(error.affected_field_paths),
                        failure_context_ids=[str(error)],
                    ),
                },
                output_schema,
            )
            assessment = _validate_and_materialize(
                revised.structured_output,
                output_schema=output_schema,
                fact_ids=fact_ids,
                allowed_evidence_refs=allowed_evidence_refs,
                candidate_refs=candidate_refs,
                source_state=source_state,
                work_facts=work_facts,
            )
            retry_budget = decision["run_budget"]
        return assessment, merge_provider_dispatch_usage(retry_budget)


def not_applicable_task_satisfaction() -> DuplicateConflictAssessmentV1:
    return {
        "relation_candidates": [],
        "requested_work_status": "NOT_APPLICABLE",
        "requested_work_reason": None,
        "matched_fact_ids": [],
        "matched_candidate_refs": [],
        "evidence_refs": [],
    }


def _prompt_input(
    *,
    work_facts: Sequence[WorkFactV1],
    evidence: list[dict[str, object]],
    source_state: Mapping[str, object],
    request_intent: Mapping[str, object],
    confirmation_response: dict[str, object] | None,
) -> dict[str, object]:
    prompt_input: dict[str, object] = {
        "request_intent": dict(request_intent),
        "work_facts": [dict(fact) for fact in work_facts],
        "evidence": list(evidence),
        "source_state": dict(source_state),
    }
    if confirmation_response is not None:
        prompt_input["confirmation_response"] = dict(confirmation_response)
    return prompt_input


def _validate_and_materialize(
    value: object,
    *,
    output_schema: OutputSchemaDefinition,
    fact_ids: set[str],
    allowed_evidence_refs: set[str],
    candidate_refs: set[str],
    source_state: Mapping[str, object],
    work_facts: Sequence[WorkFactV1],
) -> DuplicateConflictAssessmentV1:
    errors = validate_output_schema(value, output_schema.json_schema)
    if errors:
        raise ValueError(f"invalid requested Task satisfaction schema: {'; '.join(errors)}")
    root = cast(Mapping[str, object], value)
    matched_fact_ids = cast(list[str], root["matched_fact_ids"])
    matched_candidate_refs = cast(list[str], root["matched_candidate_refs"])
    refs = cast(list[str], root["evidence_refs"])
    if not set(matched_fact_ids).issubset(fact_ids):
        raise RequestedTaskSatisfactionSemanticValidationError(
            "requested-work assessment references an unknown fact"
        )
    if not set(refs).issubset(allowed_evidence_refs):
        raise RequestedTaskSatisfactionSemanticValidationError(
            "requested-work assessment evidence is outside RetrievalResultV1"
        )
    if not set(matched_candidate_refs).issubset(candidate_refs):
        raise RequestedTaskSatisfactionSemanticValidationError(
            "requested-work assessment references an unknown Task candidate"
        )
    status = cast(str, root["requested_work_status"])
    if status == "SATISFIED" and not (matched_fact_ids or matched_candidate_refs):
        raise RequestedTaskSatisfactionSemanticValidationError(
            "satisfied requested work requires a current matched observation"
        )
    if status == "NOT_SATISFIED" and (matched_fact_ids or matched_candidate_refs):
        raise RequestedTaskSatisfactionSemanticValidationError(
            "non-matching requested work cannot bind matched observations"
        )
    if status in {"SATISFIED", "NOT_SATISFIED"}:
        _validate_determinate_task_assessment(
            status=status,
            source_state=source_state,
            work_facts=work_facts,
            matched_fact_ids=matched_fact_ids,
            task_candidate_refs=candidate_refs,
        )
    return cast(
        DuplicateConflictAssessmentV1,
        {
            "relation_candidates": [],
            "requested_work_status": status,
            "requested_work_reason": cast(str, root["requested_work_reason"]),
            "matched_fact_ids": list(matched_fact_ids),
            "matched_candidate_refs": list(matched_candidate_refs),
            "evidence_refs": list(refs),
        },
    )


def _validate_determinate_task_assessment(
    *,
    status: str,
    source_state: Mapping[str, object],
    work_facts: Sequence[WorkFactV1],
    matched_fact_ids: Sequence[str],
    task_candidate_refs: set[str],
) -> None:
    raw_statuses = source_state.get("source_statuses", [])
    if not isinstance(raw_statuses, list) or not all(
        isinstance(item, Mapping) for item in raw_statuses
    ):
        raise ValueError("Task duplicate review source statuses are invalid")
    task_statuses = [
        item
        for item in cast(list[Mapping[str, object]], raw_statuses)
        if str(item.get("resource_type", "")).upper() == "TASK"
    ]
    related_statuses = [
        item
        for item in cast(list[Mapping[str, object]], raw_statuses)
        if str(item.get("resource_type", "")).upper() in {"TASK", "TASK_LIST"}
    ]
    if not task_statuses or any(item.get("status") != "COMPLETE" for item in related_statuses):
        raise RequestedTaskSatisfactionSemanticValidationError(
            "determinate Task duplicate review requires complete Task observation"
        )
    facts_by_id = {fact["fact_id"]: fact for fact in work_facts}
    if status == "SATISFIED" and any(
        facts_by_id[fact_id]["kind"] != "TASK" for fact_id in matched_fact_ids
    ):
        raise RequestedTaskSatisfactionSemanticValidationError(
            "satisfied Task duplicate review must bind Task facts"
        )
    if status != "NOT_SATISFIED":
        return
    observed_counts = [item.get("observed_resource_count") for item in task_statuses]
    if any(not isinstance(count, int) for count in observed_counts):
        raise ValueError("Task duplicate review requires observed resource counts")
    if sum(cast(list[int], observed_counts)) != len(task_candidate_refs):
        raise ValueError(
            "Task observation candidates do not cover the complete Provider observation"
        )


def _bound_output_schema(
    fact_ids: set[str], allowed_evidence_refs: set[str], candidate_refs: set[str]
) -> OutputSchemaDefinition:
    schema = deepcopy(REQUESTED_TASK_SATISFACTION_OUTPUT_SCHEMA.json_schema)
    properties = cast(dict[str, object], schema["properties"])
    properties["matched_fact_ids"] = _bounded_reference_array(fact_ids)
    properties["evidence_refs"] = _bounded_reference_array(allowed_evidence_refs)
    properties["matched_candidate_refs"] = _bounded_reference_array(candidate_refs)
    return OutputSchemaDefinition(
        schema_version=REQUESTED_TASK_SATISFACTION_OUTPUT_SCHEMA.schema_version,
        json_schema=schema,
    )


def _bounded_reference_array(values: set[str]) -> dict[str, object]:
    schema: dict[str, object] = {
        "type": "array",
        "uniqueItems": True,
        "items": {"type": "string", "minLength": 1},
    }
    if values:
        schema["items"] = {"type": "string", "enum": sorted(values)}
    else:
        schema["maxItems"] = 0
    return schema


def _task_candidate_refs(source_state: Mapping[str, object]) -> set[str]:
    raw_candidates = source_state.get("task_review_candidates", [])
    if not isinstance(raw_candidates, list) or not all(
        isinstance(item, Mapping) for item in raw_candidates
    ):
        raise ValueError("Task review candidates are invalid")
    refs = {
        str(item["candidate_ref"])
        for item in cast(list[Mapping[str, object]], raw_candidates)
        if isinstance(item.get("candidate_ref"), str) and item["candidate_ref"]
    }
    if len(refs) != len(raw_candidates):
        raise ValueError("Task review candidate identities must be unique and non-empty")
    return refs


__all__ = [
    "REQUESTED_TASK_SATISFACTION_OUTPUT_SCHEMA",
    "RequestedTaskSatisfactionSemanticValidationError",
    "assess_requested_task_satisfaction",
    "assess_requested_task_satisfaction_with_budget",
    "not_applicable_task_satisfaction",
]
