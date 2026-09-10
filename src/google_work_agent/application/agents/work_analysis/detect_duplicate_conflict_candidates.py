"""Canonical Work Analysis candidate operation: duplicate/conflict detection."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from copy import deepcopy
from typing import cast

from google_work_agent.application.agents.work_analysis.contracts.work_analysis_candidates import (
    DuplicateConflictAssessmentV1,
)
from google_work_agent.application.agents.work_analysis.contracts.work_analysis_result import (
    WorkFactV1,
    WorkRelationV1,
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

_GUARDED_KINDS = ("DUPLICATES", "CONFLICTS_WITH")
DUPLICATE_CONFLICT_CANDIDATES_OUTPUT_SCHEMA = OutputSchemaDefinition(
    schema_version="duplicate-conflict-candidates-v1",
    json_schema={
        "type": "object",
        "required": [
            "relation_candidates",
            "requested_work_status",
            "requested_work_reason",
            "matched_fact_ids",
            "matched_candidate_refs",
            "evidence_refs",
        ],
        "additionalProperties": False,
        "properties": {
            "relation_candidates": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": [
                        "relation_id",
                        "kind",
                        "source_fact_id",
                        "target_fact_id",
                        "evidence_refs",
                    ],
                    "additionalProperties": False,
                    "properties": {
                        "relation_id": {"type": "string", "minLength": 1},
                        "kind": {"enum": list(_GUARDED_KINDS)},
                        "source_fact_id": {"type": "string", "minLength": 1},
                        "target_fact_id": {"type": "string", "minLength": 1},
                        "evidence_refs": {
                            "type": "array",
                            "items": {"type": "string", "minLength": 1},
                        },
                    },
                },
            },
            "requested_work_status": {
                "enum": [
                    "NOT_APPLICABLE",
                    "SATISFIED",
                    "NOT_SATISFIED",
                    "UNDETERMINED",
                ]
            },
            "requested_work_reason": {"type": ["string", "null"]},
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


class DuplicateConflictSemanticValidationError(ValueError):
    reason_code = "DUPLICATE_ASSESSMENT_SEMANTIC_INVALID"
    affected_field_paths = (
        "$.requested_work_status",
        "$.matched_fact_ids",
        "$.matched_candidate_refs",
        "$.evidence_refs",
    )


def detect_duplicate_conflict_candidates(
    *,
    work_facts: Sequence[WorkFactV1],
    entity_relations: Sequence[WorkRelationV1],
    evidence: list[dict[str, object]],
    source_state: Mapping[str, object],
    request_intent: Mapping[str, object],
    task_duplicate_review_required: bool,
    llm_runtime: StructuredInferencePort,
    prompt_ref: PromptReference,
    allowed_evidence_refs: set[str],
    requested_mode: RequestedModeV1,
    confirmation_response: dict[str, object] | None = None,
) -> DuplicateConflictAssessmentV1:
    """Own duplicate semantics for the request and current Provider observations."""
    if not duplicate_conflict_candidate_llm_required(
        work_facts,
        task_duplicate_review_required=task_duplicate_review_required,
    ):
        return {
            "relation_candidates": [],
            "requested_work_status": "NOT_APPLICABLE",
            "requested_work_reason": None,
            "matched_fact_ids": [],
            "matched_candidate_refs": [],
            "evidence_refs": [],
        }
    prompt_input = _prompt_input(
        work_facts=work_facts,
        entity_relations=entity_relations,
        evidence=evidence,
        source_state=source_state,
        request_intent=request_intent,
        task_duplicate_review_required=task_duplicate_review_required,
        confirmation_response=confirmation_response,
    )
    fact_ids = {fact["fact_id"] for fact in work_facts}
    candidate_refs = _task_candidate_refs(source_state)
    output_schema = _bound_output_schema(fact_ids, allowed_evidence_refs, candidate_refs)
    result = llm_runtime.infer(
        requested_mode,
        prompt_ref,
        prompt_input,
        output_schema,
    )
    return _validate_and_materialize(
        result.structured_output,
        output_schema=output_schema,
        fact_ids=fact_ids,
        allowed_evidence_refs=allowed_evidence_refs,
        candidate_refs=candidate_refs,
        source_state=source_state,
        work_facts=work_facts,
        task_duplicate_review_required=task_duplicate_review_required,
    )


def detect_duplicate_conflict_candidates_with_budget(
    *,
    work_facts: Sequence[WorkFactV1],
    entity_relations: Sequence[WorkRelationV1],
    evidence: list[dict[str, object]],
    source_state: Mapping[str, object],
    request_intent: Mapping[str, object],
    task_duplicate_review_required: bool,
    llm_runtime: StructuredInferencePort,
    prompt_ref: PromptReference,
    allowed_evidence_refs: set[str],
    requested_mode: RequestedModeV1,
    retry_budget: RunBudgetV2,
    confirmation_response: dict[str, object] | None = None,
) -> tuple[DuplicateConflictAssessmentV1, RunBudgetV2]:
    """Evaluate Task duplication with one bounded semantic correction."""

    if not duplicate_conflict_candidate_llm_required(
        work_facts,
        task_duplicate_review_required=task_duplicate_review_required,
    ):
        return (
            detect_duplicate_conflict_candidates(
                work_facts=work_facts,
                entity_relations=entity_relations,
                evidence=evidence,
                source_state=source_state,
                request_intent=request_intent,
                task_duplicate_review_required=task_duplicate_review_required,
                llm_runtime=llm_runtime,
                prompt_ref=prompt_ref,
                allowed_evidence_refs=allowed_evidence_refs,
                requested_mode=requested_mode,
                confirmation_response=confirmation_response,
            ),
            retry_budget,
        )
    prompt_input = _prompt_input(
        work_facts=work_facts,
        entity_relations=entity_relations,
        evidence=evidence,
        source_state=source_state,
        request_intent=request_intent,
        task_duplicate_review_required=task_duplicate_review_required,
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
                task_duplicate_review_required=task_duplicate_review_required,
            )
        except DuplicateConflictSemanticValidationError as error:
            signature = build_semantic_failure_signature_v1(
                node_id="analysis.detect_duplicate_conflict_candidates",
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
                task_duplicate_review_required=task_duplicate_review_required,
            )
            retry_budget = decision["run_budget"]
        return assessment, merge_provider_dispatch_usage(retry_budget)


def duplicate_conflict_candidate_llm_required(
    work_facts: Sequence[WorkFactV1],
    *,
    task_duplicate_review_required: bool = False,
) -> bool:
    """Run for a policy review even when a complete read observed zero Task items."""
    return task_duplicate_review_required or len({fact["fact_id"] for fact in work_facts}) >= 2


def _prompt_input(
    *,
    work_facts: Sequence[WorkFactV1],
    entity_relations: Sequence[WorkRelationV1],
    evidence: list[dict[str, object]],
    source_state: Mapping[str, object],
    request_intent: Mapping[str, object],
    task_duplicate_review_required: bool,
    confirmation_response: dict[str, object] | None,
) -> dict[str, object]:
    prompt_input: dict[str, object] = {
        "request_intent": dict(request_intent),
        "work_facts": [dict(fact) for fact in work_facts],
        "entity_relations": [dict(item) for item in entity_relations],
        "evidence": list(evidence),
        "source_state": dict(source_state),
        "task_duplicate_review_required": task_duplicate_review_required,
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
    task_duplicate_review_required: bool,
) -> DuplicateConflictAssessmentV1:
    errors = validate_output_schema(value, output_schema.json_schema)
    if errors:
        raise ValueError(f"invalid duplicate/conflict candidate schema: {'; '.join(errors)}")
    seen: set[str] = set()
    root = cast(Mapping[str, object], value)
    for item in cast(list[Mapping[str, object]], root["relation_candidates"]):
        relation_id = cast(str, item["relation_id"])
        source = cast(str, item["source_fact_id"])
        target = cast(str, item["target_fact_id"])
        refs = cast(list[str], item["evidence_refs"])
        if (
            relation_id in seen
            or source == target
            or source not in fact_ids
            or target not in fact_ids
        ):
            raise DuplicateConflictSemanticValidationError(
                "guarded relation identity or operands are invalid"
            )
        if len(refs) != len(set(refs)) or not set(refs).issubset(allowed_evidence_refs):
            raise DuplicateConflictSemanticValidationError(
                "guarded relation evidence is outside current RetrievalResultV1"
            )
        seen.add(relation_id)
    matched_fact_ids = cast(list[str], root["matched_fact_ids"])
    matched_candidate_refs = cast(list[str], root["matched_candidate_refs"])
    refs = cast(list[str], root["evidence_refs"])
    if not set(matched_fact_ids).issubset(fact_ids):
        raise DuplicateConflictSemanticValidationError(
            "requested-work assessment references an unknown fact"
        )
    if not set(refs).issubset(allowed_evidence_refs):
        raise DuplicateConflictSemanticValidationError(
            "requested-work assessment evidence is outside RetrievalResultV1"
        )
    if not set(matched_candidate_refs).issubset(candidate_refs):
        raise DuplicateConflictSemanticValidationError(
            "requested-work assessment references an unknown Task candidate"
        )
    status = root["requested_work_status"]
    reason = root["requested_work_reason"]
    if reason is not None and (not isinstance(reason, str) or not reason.strip()):
        raise DuplicateConflictSemanticValidationError(
            "requested-work assessment reason must be non-empty or null"
        )
    if status == "SATISFIED" and not (matched_fact_ids or matched_candidate_refs):
        raise DuplicateConflictSemanticValidationError(
            "satisfied requested work requires a current matched observation"
        )
    if status in {"NOT_APPLICABLE", "NOT_SATISFIED"} and (
        matched_fact_ids or matched_candidate_refs
    ):
        raise DuplicateConflictSemanticValidationError(
            "non-matching requested work cannot bind matched observations"
        )
    if task_duplicate_review_required and status == "NOT_APPLICABLE":
        raise DuplicateConflictSemanticValidationError(
            "required Task duplicate review cannot be not applicable"
        )
    if not task_duplicate_review_required and status != "NOT_APPLICABLE":
        raise DuplicateConflictSemanticValidationError(
            "unrequested Task duplicate review must be not applicable"
        )
    if task_duplicate_review_required and status in {"SATISFIED", "NOT_SATISFIED"}:
        _validate_determinate_task_assessment(
            status=cast(str, status),
            source_state=source_state,
            work_facts=work_facts,
            matched_fact_ids=matched_fact_ids,
            task_candidate_refs=candidate_refs,
        )
    materialized = cast(dict[str, object], root)
    return cast(
        DuplicateConflictAssessmentV1,
        {
            **materialized,
            "relation_candidates": [
                dict(item)
                for item in cast(list[dict[str, object]], materialized["relation_candidates"])
            ],
            "matched_fact_ids": list(cast(list[str], materialized["matched_fact_ids"])),
            "matched_candidate_refs": list(cast(list[str], materialized["matched_candidate_refs"])),
            "evidence_refs": list(cast(list[str], materialized["evidence_refs"])),
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
        raise DuplicateConflictSemanticValidationError(
            "determinate Task duplicate review requires complete Task observation"
        )

    facts_by_id = {fact["fact_id"]: fact for fact in work_facts}
    if status == "SATISFIED" and any(
        facts_by_id[fact_id]["kind"] != "TASK" for fact_id in matched_fact_ids
    ):
        raise DuplicateConflictSemanticValidationError(
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
    """Bind guarded candidates to the current fact and Retrieval identities."""

    json_schema = deepcopy(DUPLICATE_CONFLICT_CANDIDATES_OUTPUT_SCHEMA.json_schema)
    properties = cast(dict[str, object], json_schema["properties"])
    candidates = cast(dict[str, object], properties["relation_candidates"])
    item = cast(dict[str, object], candidates["items"])
    item_properties = cast(dict[str, object], item["properties"])
    fact_id_schema = {"type": "string", "enum": sorted(fact_ids)}
    item_properties["source_fact_id"] = fact_id_schema
    item_properties["target_fact_id"] = dict(fact_id_schema)
    item_properties["evidence_refs"] = _bounded_reference_array(allowed_evidence_refs)
    properties["matched_fact_ids"] = _bounded_reference_array(fact_ids)
    properties["evidence_refs"] = _bounded_reference_array(allowed_evidence_refs)
    properties["matched_candidate_refs"] = _bounded_reference_array(candidate_refs)
    return OutputSchemaDefinition(
        schema_version=DUPLICATE_CONFLICT_CANDIDATES_OUTPUT_SCHEMA.schema_version,
        json_schema=json_schema,
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
    "DUPLICATE_CONFLICT_CANDIDATES_OUTPUT_SCHEMA",
    "DuplicateConflictSemanticValidationError",
    "detect_duplicate_conflict_candidates",
    "detect_duplicate_conflict_candidates_with_budget",
    "duplicate_conflict_candidate_llm_required",
]
