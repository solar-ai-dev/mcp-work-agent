"""Canonical Work Analysis semantic operation: ``extract_work_facts``."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from copy import deepcopy
from typing import cast

from google_work_agent.application.agents.work_analysis.contracts.work_analysis_candidates import (
    WorkAnalysisSemanticInputV1,
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

_FACT_KINDS = (
    "TASK",
    "EVENT",
    "PERSON",
    "DATE",
    "TIME",
    "DEADLINE",
    "STATUS",
    "RESOURCE",
    "TEXT_CLAIM",
    "OTHER",
)
EXTRACT_WORK_FACTS_OUTPUT_SCHEMA = OutputSchemaDefinition(
    schema_version="work-fact-candidates-v2",
    json_schema={
        "type": "object",
        "required": ["fact_candidates"],
        "additionalProperties": False,
        "properties": {
            "fact_candidates": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": [
                        "kind",
                        "subject",
                        "value",
                        "derivation",
                        "evidence_refs",
                    ],
                    "additionalProperties": False,
                    "properties": {
                        "kind": {"enum": list(_FACT_KINDS)},
                        "subject": {"type": "string", "minLength": 1},
                        "value": {"type": "string", "minLength": 1},
                        "derivation": {"enum": ["EXPLICIT", "DERIVED"]},
                        "evidence_refs": {
                            "type": "array",
                            "minItems": 1,
                            "uniqueItems": True,
                            "items": {"type": "string", "minLength": 1},
                        },
                    },
                },
            }
        },
    },
)


class TaskObservationRepresentationError(ValueError):
    reason_code = "TASK_OBSERVATION_UNREPRESENTED"
    affected_field_paths = ("$.fact_candidates",)


def extract_work_facts(
    *,
    semantic_input: WorkAnalysisSemanticInputV1,
    llm_runtime: StructuredInferencePort,
    prompt_ref: PromptReference,
    allowed_evidence_refs: set[str],
    requested_mode: RequestedModeV1,
) -> list[WorkFactV1]:
    """Extract only evidence-grounded facts from the current Retrieval revision."""

    root = _infer_and_validate(
        prompt_input=_prompt_input(semantic_input),
        semantic_input=semantic_input,
        llm_runtime=llm_runtime,
        prompt_ref=prompt_ref,
        allowed_evidence_refs=allowed_evidence_refs,
        requested_mode=requested_mode,
    )
    return _materialize_work_facts(root)


def extract_work_facts_with_budget(
    *,
    semantic_input: WorkAnalysisSemanticInputV1,
    llm_runtime: StructuredInferencePort,
    prompt_ref: PromptReference,
    allowed_evidence_refs: set[str],
    requested_mode: RequestedModeV1,
    retry_budget: RunBudgetV2,
) -> tuple[list[WorkFactV1], RunBudgetV2]:
    """Extract facts with one bounded revision for an unrepresented Task observation."""

    prompt_input = _prompt_input(semantic_input)
    bounded_schema = _bind_allowed_evidence_refs(allowed_evidence_refs)
    with provider_dispatch_budget_scope(retry_budget):
        result = llm_runtime.infer(
            requested_mode,
            prompt_ref,
            prompt_input,
            bounded_schema,
        )
        try:
            root = _validate_candidate(
                result.structured_output,
                semantic_input=semantic_input,
                allowed_evidence_refs=allowed_evidence_refs,
            )
        except TaskObservationRepresentationError as error:
            signature = build_semantic_failure_signature_v1(
                node_id="analysis.extract_facts",
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
                bounded_schema,
            )
            root = _validate_candidate(
                revised.structured_output,
                semantic_input=semantic_input,
                allowed_evidence_refs=allowed_evidence_refs,
            )
            retry_budget = decision["run_budget"]
        return _materialize_work_facts(root), merge_provider_dispatch_usage(retry_budget)


def _prompt_input(semantic_input: WorkAnalysisSemanticInputV1) -> dict[str, object]:
    prompt_input: dict[str, object] = {
        "user_request": semantic_input["user_request"],
        "request_intent": semantic_input["request_intent"],
        "evidence": list(semantic_input["evidence"]),
        "task_duplicate_review_required": semantic_input.get(
            "task_duplicate_review_required", False
        ),
    }
    if "availability_results" in semantic_input:
        prompt_input["availability_results"] = list(semantic_input["availability_results"])
    if "confirmation_response" in semantic_input:
        prompt_input["confirmation_response"] = dict(semantic_input["confirmation_response"])
    return prompt_input


def _infer_and_validate(
    *,
    prompt_input: Mapping[str, object],
    semantic_input: WorkAnalysisSemanticInputV1,
    llm_runtime: StructuredInferencePort,
    prompt_ref: PromptReference,
    allowed_evidence_refs: set[str],
    requested_mode: RequestedModeV1,
) -> Mapping[str, object]:
    bounded_schema = _bind_allowed_evidence_refs(allowed_evidence_refs)
    result = llm_runtime.infer(
        requested_mode,
        prompt_ref,
        prompt_input,
        bounded_schema,
    )
    return _validate_candidate(
        result.structured_output,
        semantic_input=semantic_input,
        allowed_evidence_refs=allowed_evidence_refs,
    )


def _validate_candidate(
    value: object,
    *,
    semantic_input: WorkAnalysisSemanticInputV1,
    allowed_evidence_refs: set[str],
) -> Mapping[str, object]:
    errors = validate_output_schema(value, EXTRACT_WORK_FACTS_OUTPUT_SCHEMA.json_schema)
    if errors:
        raise ValueError(f"invalid WorkFactV1 candidate schema: {'; '.join(errors)}")
    root = cast(Mapping[str, object], value)
    for item in cast(list[Mapping[str, object]], root["fact_candidates"]):
        refs = cast(list[str], item["evidence_refs"])
        if len(refs) != len(set(refs)) or not set(refs).issubset(allowed_evidence_refs):
            raise ValueError("work fact references evidence outside current RetrievalResultV1")
    _validate_task_observation_representation(
        semantic_input=semantic_input,
        candidates=cast(list[Mapping[str, object]], root["fact_candidates"]),
    )
    return root


def _materialize_work_facts(root: Mapping[str, object]) -> list[WorkFactV1]:
    return [
        _materialize_work_fact(item, ordinal=index)
        for index, item in enumerate(
            cast(list[Mapping[str, object]], root["fact_candidates"]), start=1
        )
    ]


def _materialize_work_fact(item: Mapping[str, object], *, ordinal: int) -> WorkFactV1:
    """Assign internal fact identity after semantic extraction succeeds."""

    semantic_fields = {
        "kind": item["kind"],
        "subject": item["subject"],
        "value": item["value"],
        "derivation": item["derivation"],
        "evidence_refs": list(cast(list[str], item["evidence_refs"])),
    }
    identity_payload = json.dumps(
        {"ordinal": ordinal, **semantic_fields},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return cast(
        WorkFactV1,
        {
            "fact_id": f"fact-{hashlib.sha256(identity_payload).hexdigest()[:24]}",
            **semantic_fields,
        },
    )


def _validate_task_observation_representation(
    *,
    semantic_input: WorkAnalysisSemanticInputV1,
    candidates: list[Mapping[str, object]],
) -> None:
    if semantic_input.get("task_duplicate_review_required") is not True:
        return
    task_evidence_refs = {
        str(item["evidence_id"])
        for item in semantic_input["evidence"]
        if isinstance(item.get("evidence_id"), str)
        and str(item.get("resource_handle", "")).startswith("task:")
    }
    if not task_evidence_refs:
        return
    if not any(
        item.get("kind") == "TASK"
        and bool(set(cast(list[str], item.get("evidence_refs", []))) & task_evidence_refs)
        for item in candidates
    ):
        raise TaskObservationRepresentationError(
            "selected Task observation must be represented before duplicate analysis"
        )


def _bind_allowed_evidence_refs(allowed_evidence_refs: set[str]) -> OutputSchemaDefinition:
    """Bind fact citations to evidence owned by the current Retrieval revision."""

    schema = deepcopy(EXTRACT_WORK_FACTS_OUTPUT_SCHEMA.json_schema)
    properties = cast(dict[str, object], schema["properties"])
    candidates = cast(dict[str, object], properties["fact_candidates"])
    if not allowed_evidence_refs:
        candidates["maxItems"] = 0
    candidate = cast(dict[str, object], candidates["items"])
    candidate_properties = cast(dict[str, object], candidate["properties"])
    evidence_refs = cast(dict[str, object], candidate_properties["evidence_refs"])
    evidence_refs["items"] = {"type": "string", "enum": sorted(allowed_evidence_refs)}
    return OutputSchemaDefinition(
        schema_version=EXTRACT_WORK_FACTS_OUTPUT_SCHEMA.schema_version,
        json_schema=schema,
    )


__all__ = [
    "EXTRACT_WORK_FACTS_OUTPUT_SCHEMA",
    "TaskObservationRepresentationError",
    "extract_work_facts",
    "extract_work_facts_with_budget",
]
