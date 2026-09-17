"""Inactive BM25 ranking candidate for frozen Retrieval comparisons."""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from math import log

from google_work_agent.application.agents.request_understanding.contracts.request_intent import (
    RequestIntentV2,
)
from google_work_agent.application.agents.retrieval.contracts.query_plan import SourceFetchPlanV1
from google_work_agent.application.agents.retrieval.normalize_segments import SourceSegment
from google_work_agent.application.agents.retrieval.rag_retrieve_rerank import (
    DEFAULT_RAG_SCORING_CONFIG,
    RagCandidateV1,
    RagScoringConfig,
    _clean_terms,
    _query_terms,
    _selected_resource_ids,
    _semantic_match_reasons,
    _thread_id,
)
from google_work_agent.application.agents.task_calendar_draft_source import (
    is_task_calendar_draft_source_target,
    project_task_calendar_source_terms,
)


@dataclass(frozen=True, slots=True)
class BM25CandidateConfig:
    k1: float = 1.2
    b: float = 0.75
    score_scale: float = 1.5


DEFAULT_BM25_CANDIDATE_CONFIG = BM25CandidateConfig()


def bm25_rag_retrieve_rerank(
    segments: list[SourceSegment],
    *,
    request_intent: RequestIntentV2,
    source_plans: Sequence[SourceFetchPlanV1],
    top_k: int,
    config: RagScoringConfig = DEFAULT_RAG_SCORING_CONFIG,
    bm25_config: BM25CandidateConfig = DEFAULT_BM25_CANDIDATE_CONFIG,
) -> list[RagCandidateV1]:
    """Mirror current RAG scoring, replacing only its lexical contribution."""
    selected = _selected_resource_ids(request_intent)
    terms = _query_terms(request_intent)
    lexical_scores = _bm25_keyword_scores(segments, terms, config, bm25_config)
    task_calendar_terms = (
        project_task_calendar_source_terms(request_intent.get("constraints"))
        if is_task_calendar_draft_source_target(request_intent)
        else None
    )
    scored: list[tuple[SourceSegment, float, list[str]]] = []
    seen: set[str] = set()
    for segment in segments:
        if segment.segment_id in seen:
            continue
        seen.add(segment.segment_id)
        score = 0.0
        reasons: list[str] = []
        if segment.resource_id in selected:
            score += config.exact_resource_score
            reasons.append("EXACT_RESOURCE")
        elif segment.parent_id is not None and segment.parent_id in selected:
            score += config.related_resource_score
            reasons.append("RELATED_RESOURCE")
        lexical_score = lexical_scores.get(segment.segment_id, 0.0)
        if lexical_score > 0:
            score += lexical_score
            reasons.append("KEYWORD_MATCH")
        if task_calendar_terms is not None:
            source_terms = (
                task_calendar_terms["task_terms"]
                if segment.resource_type == "task"
                else task_calendar_terms["calendar_evidence_terms"]
                if segment.resource_type == "calendar_event"
                else []
            )
            if source_terms and all(
                term.casefold() in segment.text.casefold() for term in source_terms
            ):
                score += config.keyword_max_score
                reasons.append("EXPLICIT_SOURCE_ANCHOR_MATCH")
        semantic_reasons = _semantic_match_reasons(segment, source_plans, request_intent)
        score += len(semantic_reasons) * config.keyword_score_per_term
        reasons.extend(semantic_reasons)
        scored.append((segment, score, reasons))

    relevant_threads = {
        _thread_id(segment)
        for segment, _, reasons in scored
        if reasons and _thread_id(segment) is not None
    }
    for index, (segment, score, reasons) in enumerate(scored):
        if not reasons and _thread_id(segment) in relevant_threads:
            scored[index] = (
                segment,
                score + config.thread_lineage_score,
                ["THREAD_LINEAGE_MATCH"],
            )
    ordered = sorted(scored, key=lambda item: (-item[1], item[0].segment_id))
    top_ids = {segment.segment_id for segment, _, _ in ordered[:top_k]}
    forced = {
        segment.segment_id
        for segment, _, _ in scored
        if segment.resource_id in selected and segment.segment_id not in top_ids
    }
    return [
        {
            "segment_id": segment.segment_id,
            "resource_ref": segment.resource_handle,
            "retrieval_score": score,
            "reason_codes": reasons
            + (["RESOURCE_SELECTED_FORCED"] if segment.segment_id in forced else []),
        }
        for segment, score, reasons in ordered
        if segment.segment_id in top_ids or segment.segment_id in forced
    ]


def _bm25_keyword_scores(
    segments: Sequence[SourceSegment],
    query_terms: frozenset[str],
    config: RagScoringConfig,
    bm25_config: BM25CandidateConfig,
) -> dict[str, float]:
    if not query_terms:
        return {}
    unique_segments = {segment.segment_id: segment for segment in reversed(segments)}
    if not unique_segments:
        return {}
    documents = {
        segment_id: Counter(_clean_terms(segment.text))
        for segment_id, segment in unique_segments.items()
    }
    average_length = sum(sum(counts.values()) for counts in documents.values()) / len(documents)
    if average_length == 0:
        return {}
    document_frequency = Counter(
        term for counts in documents.values() for term in query_terms if counts[term] > 0
    )
    corpus_size = len(documents)
    scores: dict[str, float] = {}
    for segment_id, counts in documents.items():
        document_length = sum(counts.values())
        length_factor = 1 - bm25_config.b + bm25_config.b * document_length / average_length
        raw_score = sum(
            log(
                1
                + (corpus_size - document_frequency[term] + 0.5) / (document_frequency[term] + 0.5)
            )
            * counts[term]
            * (bm25_config.k1 + 1)
            / (counts[term] + bm25_config.k1 * length_factor)
            for term in sorted(query_terms)
            if counts[term] > 0
        )
        if raw_score > 0:
            scores[segment_id] = (
                config.keyword_max_score * raw_score / (raw_score + bm25_config.score_scale)
            )
    return scores
