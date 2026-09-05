"""Canonical Retrieval semantic operation: select_evidence."""

from __future__ import annotations

from collections.abc import Collection, Sequence
from typing import Literal, cast

from google_work_agent.application.agents.request_understanding.contracts.request_intent import (
    RequestIntentV2,
)
from google_work_agent.application.agents.retrieval.contracts.evidence_selection_schema import (
    bind_evidence_selection_schema,
    required_resource_segments,
)
from google_work_agent.application.agents.retrieval.contracts.query_attempt import QueryAttemptV1
from google_work_agent.application.agents.retrieval.contracts.query_plan import (
    TemporalRangeConstraintV1,
)
from google_work_agent.application.agents.retrieval.contracts.retrieval_result import (
    EvidenceDraftV1,
    EvidenceRoleDraftV2,
    EvidenceSelectionResultV2,
)
from google_work_agent.application.agents.retrieval.match_temporal_evidence import (
    project_event_date_candidates,
)
from google_work_agent.application.agents.retrieval.normalize_segments import (
    DEFAULT_CONTEXT_BUDGET,
    ContextBudget,
    SourceSegment,
    _truncate,
)
from google_work_agent.application.agents.retrieval.prioritize_material_gmail_evidence import (
    prioritize_material_gmail_evidence,
    select_explicit_lineage_gmail_evidence,
)
from google_work_agent.application.agents.retrieval.project_query_temporal_constraints import (
    project_query_temporal_constraints,
)
from google_work_agent.application.agents.retrieval.rag_retrieve_rerank import RagCandidateV1
from google_work_agent.application.prompt_runtime.contracts.failure_record import (
    build_failure_record_v1,
)
from google_work_agent.application.use_cases.run.guard_run_budget import (
    BudgetDecision,
    RunBudgetV2,
    approve_semantic_revision,
    build_semantic_failure_signature_v1,
)
from google_work_agent.ports.llm.structured_inference_contracts import (
    PromptReference,
)
from google_work_agent.ports.llm.structured_inference_port import StructuredInferencePort
from google_work_agent.ports.system.contracts.workflow_handoff import RequestedModeV1


def select_evidence(
    *,
    llm_runtime: StructuredInferencePort,
    prompt_ref: PromptReference,
    revision_prompt_ref: PromptReference,
    requested_mode: RequestedModeV1,
    request_intent: RequestIntentV2,
    rag_candidates: list[RagCandidateV1],
    segments: list[SourceSegment],
    retry_budget: RunBudgetV2,
    context_budget: ContextBudget = DEFAULT_CONTEXT_BUDGET,
    exclusion_obligation_segment_ids: Collection[str] = (),
    query_attempts: Sequence[QueryAttemptV1] = (),
) -> tuple[EvidenceSelectionResultV2, RunBudgetV2]:
    """Select evidence only from the bounded ranked segments supplied by RAG."""
    obligations = _stable_unique(exclusion_obligation_segment_ids)
    excluded = set(obligations)
    eligible_candidates = [
        candidate for candidate in rag_candidates if candidate["segment_id"] not in excluded
    ]
    eligible_candidates = _bounded_prompt_candidates(
        eligible_candidates,
        requested_resource_hints=request_intent["requested_resource_hints"],
        limit=min(context_budget.max_normalized_context_items, context_budget.max_evidence),
    )
    deterministic_selection = _exact_selected_read_selection(
        request_intent=request_intent,
        candidates=eligible_candidates,
        exclusion_obligations=obligations,
    )
    if deterministic_selection is not None:
        return deterministic_selection, retry_budget
    lineage_selection = select_explicit_lineage_gmail_evidence(
        request_intent=request_intent,
        rag_candidates=eligible_candidates,
        segments=segments,
        max_evidence=context_budget.max_evidence,
    )
    if lineage_selection is not None:
        bounded_selection = _apply_exclusions(lineage_selection, obligations)
        if bounded_selection["selected_segment_ids"]:
            return bounded_selection, retry_budget
    temporal_constraints = project_query_temporal_constraints(query_attempts)
    projection = _ranked_segments_projection(eligible_candidates, segments, temporal_constraints)
    candidate_ids = [candidate["segment_id"] for candidate in eligible_candidates]
    candidate_resource_refs = {
        candidate["segment_id"]: candidate["resource_ref"] for candidate in eligible_candidates
    }
    output_schema = bind_evidence_selection_schema(
        candidate_resource_refs=candidate_resource_refs,
        max_evidence=context_budget.max_evidence,
    )
    result = llm_runtime.infer(
        requested_mode,
        prompt_ref,
        {
            "request_intent": request_intent,
            "ranked_segments": projection,
            "temporal_constraints": temporal_constraints,
        },
        output_schema,
    )
    try:
        return (
            _apply_exclusions(
                prioritize_material_gmail_evidence(
                    _validate_selection(
                        result.structured_output,
                        candidate_segment_ids=candidate_ids,
                        context_budget=context_budget,
                    ),
                    request_intent=request_intent,
                    rag_candidates=eligible_candidates,
                    segments=segments,
                    max_evidence=context_budget.max_evidence,
                ),
                obligations,
            ),
            retry_budget,
        )
    except ValueError as error:
        signature = build_semantic_failure_signature_v1(
            node_id="retrieval.select_evidence",
            failure_reason_codes=["EVIDENCE_SELECTION_SEMANTIC_INVALID"],
        )
        decision = approve_semantic_revision(retry_budget, signature=signature)
        if decision["decision"] == BudgetDecision.DENY.value:
            return (
                _material_fallback_selection(
                    request_intent=request_intent,
                    eligible_candidates=eligible_candidates,
                    segments=segments,
                    obligations=obligations,
                    context_budget=context_budget,
                ),
                decision["run_budget"],
            )
        revision = llm_runtime.infer(
            requested_mode,
            revision_prompt_ref,
            {
                "base_projection": {
                    "request_intent": request_intent,
                    "ranked_segments": projection,
                    "temporal_constraints": temporal_constraints,
                },
                "candidate_output": result.structured_output,
                "failure_record": build_failure_record_v1(
                    failure_reason_code="EVIDENCE_SELECTION_SEMANTIC_INVALID",
                    failure_origin="RETRIEVAL_RESULT",
                    detected_by="RUNTIME_DOMAIN_VALIDATOR",
                    runtime_disposition="RETRYABLE",
                    experiment_disposition="RUN_REVISION",
                    affected_field_paths=[
                        "$.segment_assessments",
                    ],
                    failure_context_ids=[str(error)],
                ),
            },
            output_schema,
        )
        try:
            return (
                _apply_exclusions(
                    prioritize_material_gmail_evidence(
                        _validate_selection(
                            revision.structured_output,
                            candidate_segment_ids=candidate_ids,
                            context_budget=context_budget,
                        ),
                        request_intent=request_intent,
                        rag_candidates=eligible_candidates,
                        segments=segments,
                        max_evidence=context_budget.max_evidence,
                    ),
                    obligations,
                ),
                decision["run_budget"],
            )
        except ValueError:
            return (
                _material_fallback_selection(
                    request_intent=request_intent,
                    eligible_candidates=eligible_candidates,
                    segments=segments,
                    obligations=obligations,
                    context_budget=context_budget,
                ),
                decision["run_budget"],
            )


def _material_fallback_selection(
    *,
    request_intent: RequestIntentV2,
    eligible_candidates: list[RagCandidateV1],
    segments: list[SourceSegment],
    obligations: Collection[str],
    context_budget: ContextBudget,
) -> EvidenceSelectionResultV2:
    return _apply_exclusions(
        prioritize_material_gmail_evidence(
            _empty_selection(),
            request_intent=request_intent,
            rag_candidates=eligible_candidates,
            segments=segments,
            max_evidence=context_budget.max_evidence,
        ),
        obligations,
    )


def _exact_selected_read_selection(
    *,
    request_intent: RequestIntentV2,
    candidates: list[RagCandidateV1],
    exclusion_obligations: Collection[str],
) -> EvidenceSelectionResultV2 | None:
    """Select bounded segments from one exact selected resource without inference."""

    resource_refs = {candidate["resource_ref"] for candidate in candidates}
    if (
        request_intent["analysis_requirement"] != "NONE"
        or set(request_intent["requested_effect_hints"]) != {"READ"}
        or not candidates
        or len(resource_refs) != 1
        or any("EXACT_RESOURCE" not in candidate["reason_codes"] for candidate in candidates)
    ):
        return None
    selected_segment_ids = [candidates[0]["segment_id"]]
    return {
        "schema_version": 2,
        "evidence_drafts": [
            {
                "segment_id": segment_id,
                "role": "SUPPORTS",
                "relevance_reason": "EXACT_SELECTED_RESOURCE",
            }
            for segment_id in selected_segment_ids
        ],
        "selected_segment_ids": selected_segment_ids,
        "excluded_segment_ids": _stable_unique(exclusion_obligations),
    }


def _bounded_prompt_candidates(
    candidates: list[RagCandidateV1], *, requested_resource_hints: Collection[str], limit: int,
) -> list[RagCandidateV1]:
    """Apply the declared context cap without starving another requested source."""
    groups = required_resource_segments(
        {item["segment_id"]: item["resource_ref"] for item in candidates},
        requested_resource_hints,
    )
    represented = {
        next(item["segment_id"] for item in candidates if item["segment_id"] in segment_ids)
        for segment_ids in groups.values()
    }
    if limit < len(represented) or limit < 1:
        raise ValueError("evidence context budget cannot represent requested sources")
    for item in candidates:
        if len(represented) >= limit:
            break
        represented.add(item["segment_id"])
    return [item for item in candidates if item["segment_id"] in represented]


def _ranked_segments_projection(
    candidates: list[RagCandidateV1], segments: list[SourceSegment],
    temporal_constraints: Sequence[TemporalRangeConstraintV1],
) -> list[dict[str, object]]:
    by_id = {segment.segment_id: segment for segment in segments}
    result: list[dict[str, object]] = []
    for candidate in candidates:
        segment = by_id.get(candidate["segment_id"])
        if segment is None:
            raise ValueError(f"RAG_SEGMENT_REFERENCE_INVALID: {candidate['segment_id']}")
        temporal_dates: list[dict[str, object]] = []
        for index, constraint in enumerate(temporal_constraints):
            if constraint["axis"] != "EVENT_TIME":
                continue
            mentions = project_event_date_candidates(segment.text, constraint)
            temporal_dates.append({
                "target_index": index, "date_mentions": mentions[:12],
                "date_mentions_truncated": len(mentions) > 12,
            })
        result.append(
            {
                "segment_id": candidate["segment_id"],
                "resource_ref": candidate["resource_ref"],
                "excerpt": segment.text,
                "retrieval_score": candidate["retrieval_score"],
                "reason_codes": list(candidate["reason_codes"]),
                "trust_class": "UNTRUSTED_SOURCE_CONTENT",
                "content_role": "DATA_ONLY",
                "temporal_date_candidates": temporal_dates,
            }
        )
    return result


def _validate_selection(
    value: object,
    *,
    candidate_segment_ids: Sequence[str],
    context_budget: ContextBudget,
) -> EvidenceSelectionResultV2:
    if not isinstance(value, dict) or set(value) != {
        "schema_version",
        "segment_assessments",
    }:
        raise ValueError("invalid evidence selection envelope")
    if value["schema_version"] != 3:
        raise ValueError("inference schema_version must be 3")
    assessments = value["segment_assessments"]
    if not isinstance(assessments, dict) or set(assessments) != set(candidate_segment_ids):
        raise ValueError("each visible candidate requires exactly one assessment")
    drafts: list[EvidenceRoleDraftV2] = []
    excluded: list[str] = []
    # JSON object key order is not retrieval priority. Preserve the RAG order
    # used by bounded detail acquisition, regardless of the model's key order.
    for segment_id in candidate_segment_ids:
        raw = assessments[segment_id]
        if not isinstance(raw, dict) or set(raw) != {"role", "relevance_reason"}:
            raise ValueError("invalid evidence assessment")
        role = raw.get("role")
        reason = raw.get("relevance_reason")
        if role not in {"SUPPORTS", "CONTRADICTS", "CONTEXT", "EXCLUDED"}:
            raise ValueError("invalid evidence role")
        if not isinstance(reason, str) or not reason.strip():
            raise ValueError("every assessment requires a nonempty relevance reason")
        if role == "EXCLUDED":
            excluded.append(segment_id)
            continue
        drafts.append(
            {
                "segment_id": str(segment_id),
                "role": cast(Literal["SUPPORTS", "CONTRADICTS", "CONTEXT"], role),
                "relevance_reason": reason,
            }
        )
    if len(drafts) > context_budget.max_evidence:
        raise ValueError("evidence selection exceeds the evidence budget")
    return {
        "schema_version": 2,
        "evidence_drafts": drafts,
        "selected_segment_ids": [draft["segment_id"] for draft in drafts],
        "excluded_segment_ids": excluded,
    }


def _empty_selection(excluded_segment_ids: Collection[str] = ()) -> EvidenceSelectionResultV2:
    return {
        "schema_version": 2,
        "evidence_drafts": [],
        "selected_segment_ids": [],
        "excluded_segment_ids": _stable_unique(excluded_segment_ids),
    }


def _apply_exclusions(
    selection: EvidenceSelectionResultV2,
    obligations: Collection[str],
) -> EvidenceSelectionResultV2:
    excluded = _stable_unique([*obligations, *selection["excluded_segment_ids"]])
    excluded_set = set(excluded)
    return {
        "schema_version": 2,
        "evidence_drafts": [
            draft
            for draft in selection["evidence_drafts"]
            if draft["segment_id"] not in excluded_set
        ],
        "selected_segment_ids": [
            segment_id
            for segment_id in selection["selected_segment_ids"]
            if segment_id not in excluded_set
        ],
        "excluded_segment_ids": excluded,
    }


def _stable_unique(values: Collection[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        if value not in seen:
            seen.add(value)
            result.append(value)
    return result


def materialize_evidence_drafts(
    selection: EvidenceSelectionResultV2,
    *,
    segments: list[SourceSegment],
    context_budget: ContextBudget = DEFAULT_CONTEXT_BUDGET,
) -> list[EvidenceDraftV1]:
    """Join thin model-selected segment roles to deterministic source-owned fields."""
    draft_ids = [draft["segment_id"] for draft in selection["evidence_drafts"]]
    if len(draft_ids) != len(set(draft_ids)) or set(draft_ids) != set(
        selection["selected_segment_ids"]
    ):
        raise ValueError("cannot materialize inconsistent selected segment/evidence binding")
    by_id = {segment.segment_id: segment for segment in segments}
    result: list[EvidenceDraftV1] = []
    seen: set[tuple[str, str, str]] = set()
    for role_draft in selection["evidence_drafts"]:
        segment = by_id.get(role_draft["segment_id"])
        if segment is None:
            raise ValueError(f"RAG_SEGMENT_REFERENCE_INVALID: {role_draft['segment_id']}")
        excerpt = _truncate(segment.text, context_budget.max_excerpt_chars)
        key = (segment.resource_handle, segment.segment_id, excerpt)
        if key in seen:
            continue
        seen.add(key)
        result.append(
            {
                "schema_version": 1,
                "evidence_id": f"evidence-{segment.segment_id}",
                "resource_handle": segment.resource_handle,
                "segment_id": segment.segment_id,
                "kind": "excerpt",
                "excerpt": excerpt,
                "locator": dict(segment.locator),
                "reason_codes": [role_draft["role"]],
            }
        )
    return result


__all__ = [
    "materialize_evidence_drafts",
    "select_evidence",
]
