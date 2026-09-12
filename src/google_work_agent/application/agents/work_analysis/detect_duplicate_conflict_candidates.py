"""Canonical Work Analysis candidate operation: duplicate/conflict relations."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from copy import deepcopy
from typing import cast

from google_work_agent.application.agents.work_analysis.assess_requested_task_satisfaction import (
    assess_requested_task_satisfaction,
    assess_requested_task_satisfaction_with_budget,
    not_applicable_task_satisfaction,
)
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
    schema_version="duplicate-conflict-candidates-v2",
    json_schema={
        "type": "object",
        "required": ["relation_candidates"],
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
            }
        },
    },
)


class DuplicateConflictSemanticValidationError(ValueError):
    reason_code = "DUPLICATE_RELATION_SEMANTIC_INVALID"
    affected_field_paths = ("$.relation_candidates",)


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
    task_satisfaction_prompt_ref: PromptReference,
    allowed_evidence_refs: set[str],
    requested_mode: RequestedModeV1,
    confirmation_response: dict[str, object] | None = None,
) -> DuplicateConflictAssessmentV1:
    relations = (
        _detect_relations(
            work_facts=work_facts,
            entity_relations=entity_relations,
            evidence=evidence,
            llm_runtime=llm_runtime,
            prompt_ref=prompt_ref,
            allowed_evidence_refs=allowed_evidence_refs,
            requested_mode=requested_mode,
            confirmation_response=confirmation_response,
        )
        if relation_candidate_llm_required(work_facts)
        else []
    )
    task_assessment = (
        assess_requested_task_satisfaction(
            work_facts=work_facts,
            evidence=evidence,
            source_state=source_state,
            request_intent=request_intent,
            llm_runtime=llm_runtime,
            prompt_ref=task_satisfaction_prompt_ref,
            allowed_evidence_refs=allowed_evidence_refs,
            requested_mode=requested_mode,
            confirmation_response=confirmation_response,
        )
        if task_duplicate_review_required
        else not_applicable_task_satisfaction()
    )
    return {**task_assessment, "relation_candidates": relations}


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
    task_satisfaction_prompt_ref: PromptReference,
    allowed_evidence_refs: set[str],
    requested_mode: RequestedModeV1,
    retry_budget: RunBudgetV2,
    confirmation_response: dict[str, object] | None = None,
) -> tuple[DuplicateConflictAssessmentV1, RunBudgetV2]:
    if relation_candidate_llm_required(work_facts):
        relations, retry_budget = _detect_relations_with_budget(
            work_facts=work_facts,
            entity_relations=entity_relations,
            evidence=evidence,
            llm_runtime=llm_runtime,
            prompt_ref=prompt_ref,
            allowed_evidence_refs=allowed_evidence_refs,
            requested_mode=requested_mode,
            retry_budget=retry_budget,
            confirmation_response=confirmation_response,
        )
    else:
        relations = []
    if task_duplicate_review_required:
        task_assessment, retry_budget = assess_requested_task_satisfaction_with_budget(
            work_facts=work_facts,
            evidence=evidence,
            source_state=source_state,
            request_intent=request_intent,
            llm_runtime=llm_runtime,
            prompt_ref=task_satisfaction_prompt_ref,
            allowed_evidence_refs=allowed_evidence_refs,
            requested_mode=requested_mode,
            retry_budget=retry_budget,
            confirmation_response=confirmation_response,
        )
    else:
        task_assessment = not_applicable_task_satisfaction()
    return ({**task_assessment, "relation_candidates": relations}, retry_budget)


def duplicate_conflict_candidate_llm_required(
    work_facts: Sequence[WorkFactV1],
    *,
    task_duplicate_review_required: bool = False,
) -> bool:
    return task_duplicate_review_required or relation_candidate_llm_required(work_facts)


def relation_candidate_llm_required(work_facts: Sequence[WorkFactV1]) -> bool:
    return len({fact["fact_id"] for fact in work_facts}) >= 2


def _detect_relations(
    *,
    work_facts: Sequence[WorkFactV1],
    entity_relations: Sequence[WorkRelationV1],
    evidence: list[dict[str, object]],
    llm_runtime: StructuredInferencePort,
    prompt_ref: PromptReference,
    allowed_evidence_refs: set[str],
    requested_mode: RequestedModeV1,
    confirmation_response: dict[str, object] | None,
) -> list[WorkRelationV1]:
    prompt_input = _relation_prompt_input(
        work_facts=work_facts,
        entity_relations=entity_relations,
        evidence=evidence,
        confirmation_response=confirmation_response,
    )
    fact_ids = {fact["fact_id"] for fact in work_facts}
    output_schema = _bound_output_schema(fact_ids, allowed_evidence_refs)
    result = llm_runtime.infer(requested_mode, prompt_ref, prompt_input, output_schema)
    return _validate_relations(
        result.structured_output,
        output_schema=output_schema,
        fact_ids=fact_ids,
        allowed_evidence_refs=allowed_evidence_refs,
    )


def _detect_relations_with_budget(
    *,
    work_facts: Sequence[WorkFactV1],
    entity_relations: Sequence[WorkRelationV1],
    evidence: list[dict[str, object]],
    llm_runtime: StructuredInferencePort,
    prompt_ref: PromptReference,
    allowed_evidence_refs: set[str],
    requested_mode: RequestedModeV1,
    retry_budget: RunBudgetV2,
    confirmation_response: dict[str, object] | None,
) -> tuple[list[WorkRelationV1], RunBudgetV2]:
    prompt_input = _relation_prompt_input(
        work_facts=work_facts,
        entity_relations=entity_relations,
        evidence=evidence,
        confirmation_response=confirmation_response,
    )
    fact_ids = {fact["fact_id"] for fact in work_facts}
    output_schema = _bound_output_schema(fact_ids, allowed_evidence_refs)
    with provider_dispatch_budget_scope(retry_budget):
        result = llm_runtime.infer(requested_mode, prompt_ref, prompt_input, output_schema)
        try:
            relations = _validate_relations(
                result.structured_output,
                output_schema=output_schema,
                fact_ids=fact_ids,
                allowed_evidence_refs=allowed_evidence_refs,
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
            relations = _validate_relations(
                revised.structured_output,
                output_schema=output_schema,
                fact_ids=fact_ids,
                allowed_evidence_refs=allowed_evidence_refs,
            )
            retry_budget = decision["run_budget"]
        return relations, merge_provider_dispatch_usage(retry_budget)


def _relation_prompt_input(
    *,
    work_facts: Sequence[WorkFactV1],
    entity_relations: Sequence[WorkRelationV1],
    evidence: list[dict[str, object]],
    confirmation_response: dict[str, object] | None,
) -> dict[str, object]:
    prompt_input: dict[str, object] = {
        "work_facts": [dict(fact) for fact in work_facts],
        "entity_relations": [dict(item) for item in entity_relations],
        "evidence": list(evidence),
    }
    if confirmation_response is not None:
        prompt_input["confirmation_response"] = dict(confirmation_response)
    return prompt_input


def _validate_relations(
    value: object,
    *,
    output_schema: OutputSchemaDefinition,
    fact_ids: set[str],
    allowed_evidence_refs: set[str],
) -> list[WorkRelationV1]:
    errors = validate_output_schema(value, output_schema.json_schema)
    if errors:
        raise ValueError(f"invalid duplicate/conflict relation schema: {'; '.join(errors)}")
    seen: set[str] = set()
    root = cast(Mapping[str, object], value)
    result: list[WorkRelationV1] = []
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
        result.append(cast(WorkRelationV1, dict(item)))
    return result


def _bound_output_schema(
    fact_ids: set[str], allowed_evidence_refs: set[str]
) -> OutputSchemaDefinition:
    schema = deepcopy(DUPLICATE_CONFLICT_CANDIDATES_OUTPUT_SCHEMA.json_schema)
    properties = cast(dict[str, object], schema["properties"])
    candidates = cast(dict[str, object], properties["relation_candidates"])
    item = cast(dict[str, object], candidates["items"])
    item_properties = cast(dict[str, object], item["properties"])
    fact_id_schema = {"type": "string", "enum": sorted(fact_ids)}
    item_properties["source_fact_id"] = fact_id_schema
    item_properties["target_fact_id"] = dict(fact_id_schema)
    item_properties["evidence_refs"] = {
        "type": "array",
        "uniqueItems": True,
        "items": {"type": "string", "enum": sorted(allowed_evidence_refs)},
    }
    return OutputSchemaDefinition(
        schema_version=DUPLICATE_CONFLICT_CANDIDATES_OUTPUT_SCHEMA.schema_version,
        json_schema=schema,
    )


__all__ = [
    "DUPLICATE_CONFLICT_CANDIDATES_OUTPUT_SCHEMA",
    "DuplicateConflictSemanticValidationError",
    "detect_duplicate_conflict_candidates",
    "detect_duplicate_conflict_candidates_with_budget",
    "duplicate_conflict_candidate_llm_required",
    "relation_candidate_llm_required",
]
