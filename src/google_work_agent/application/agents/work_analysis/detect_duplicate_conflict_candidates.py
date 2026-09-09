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
            "evidence_refs": {
                "type": "array",
                "uniqueItems": True,
                "items": {"type": "string", "minLength": 1},
            },
        },
    },
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
            "evidence_refs": [],
        }
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
    fact_ids = {fact["fact_id"] for fact in work_facts}
    output_schema = _bound_output_schema(fact_ids, allowed_evidence_refs)

    def validate(value: object) -> object:
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
                raise ValueError("guarded relation identity or operands are invalid")
            if len(refs) != len(set(refs)) or not set(refs).issubset(allowed_evidence_refs):
                raise ValueError("guarded relation evidence is outside current RetrievalResultV1")
            seen.add(relation_id)
        matched_fact_ids = cast(list[str], root["matched_fact_ids"])
        refs = cast(list[str], root["evidence_refs"])
        if not set(matched_fact_ids).issubset(fact_ids):
            raise ValueError("requested-work assessment references an unknown fact")
        if not set(refs).issubset(allowed_evidence_refs):
            raise ValueError("requested-work assessment evidence is outside RetrievalResultV1")
        status = root["requested_work_status"]
        reason = root["requested_work_reason"]
        if reason is not None and (not isinstance(reason, str) or not reason.strip()):
            raise ValueError("requested-work assessment reason must be non-empty or null")
        if status == "SATISFIED" and (not matched_fact_ids or not refs):
            raise ValueError("satisfied requested work requires current facts and evidence")
        if status in {"NOT_APPLICABLE", "NOT_SATISFIED"} and matched_fact_ids:
            raise ValueError("non-matching requested work cannot bind matched facts")
        if task_duplicate_review_required and status == "NOT_APPLICABLE":
            raise ValueError("required Task duplicate review cannot be not applicable")
        if not task_duplicate_review_required and status != "NOT_APPLICABLE":
            raise ValueError("unrequested Task duplicate review must be not applicable")
        if task_duplicate_review_required and status in {"SATISFIED", "NOT_SATISFIED"}:
            _validate_determinate_task_assessment(
                status=cast(str, status),
                source_state=source_state,
                work_facts=work_facts,
                matched_fact_ids=matched_fact_ids,
            )
        return value

    result = llm_runtime.infer(
        requested_mode,
        prompt_ref,
        prompt_input,
        output_schema,
    )
    root = cast(dict[str, object], validate(result.structured_output))
    return cast(
        DuplicateConflictAssessmentV1,
        {
            **root,
            "relation_candidates": [
                dict(item) for item in cast(list[dict[str, object]], root["relation_candidates"])
            ],
            "matched_fact_ids": list(cast(list[str], root["matched_fact_ids"])),
            "evidence_refs": list(cast(list[str], root["evidence_refs"])),
        },
    )


def duplicate_conflict_candidate_llm_required(
    work_facts: Sequence[WorkFactV1],
    *,
    task_duplicate_review_required: bool = False,
) -> bool:
    """Run for a policy review even when a complete read observed zero Task items."""
    return task_duplicate_review_required or len({fact["fact_id"] for fact in work_facts}) >= 2


def _validate_determinate_task_assessment(
    *,
    status: str,
    source_state: Mapping[str, object],
    work_facts: Sequence[WorkFactV1],
    matched_fact_ids: Sequence[str],
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
        raise ValueError("determinate Task duplicate review requires complete Task observation")

    facts_by_id = {fact["fact_id"]: fact for fact in work_facts}
    if status == "SATISFIED" and any(
        facts_by_id[fact_id]["kind"] != "TASK" for fact_id in matched_fact_ids
    ):
        raise ValueError("satisfied Task duplicate review must bind Task facts")
    if status != "NOT_SATISFIED":
        return

    observed_counts = [item.get("observed_resource_count") for item in task_statuses]
    if all(count == 0 for count in observed_counts):
        return
    if not any(fact["kind"] == "TASK" for fact in work_facts):
        raise ValueError(
            "non-empty Task observation must be represented before a nonduplicate decision"
        )


def _bound_output_schema(
    fact_ids: set[str], allowed_evidence_refs: set[str]
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
    item_properties["evidence_refs"] = {
        "type": "array",
        "uniqueItems": True,
        "items": {"type": "string", "enum": sorted(allowed_evidence_refs)},
    }
    properties["matched_fact_ids"] = {
        "type": "array",
        "uniqueItems": True,
        "items": {"type": "string", "enum": sorted(fact_ids)},
    }
    properties["evidence_refs"] = {
        "type": "array",
        "uniqueItems": True,
        "items": {"type": "string", "enum": sorted(allowed_evidence_refs)},
    }
    return OutputSchemaDefinition(
        schema_version=DUPLICATE_CONFLICT_CANDIDATES_OUTPUT_SCHEMA.schema_version,
        json_schema=json_schema,
    )


__all__ = [
    "DUPLICATE_CONFLICT_CANDIDATES_OUTPUT_SCHEMA",
    "detect_duplicate_conflict_candidates",
    "duplicate_conflict_candidate_llm_required",
]
