"""Canonical Retrieval deterministic operation: rag_retrieve_rerank."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import TypedDict

from google_work_agent.application.agents.request_understanding.contracts.request_intent import (
    RequestIntentV2,
)
from google_work_agent.application.agents.retrieval.contracts.query_plan import (
    SourceFetchPlanV1,
)
from google_work_agent.application.agents.retrieval.match_person_mention import match_person_mention
from google_work_agent.application.agents.retrieval.match_temporal_evidence import (
    match_temporal_evidence,
)
from google_work_agent.application.agents.retrieval.normalize_segments import SourceSegment


class RagCandidateV1(TypedDict):
    segment_id: str
    resource_ref: str
    retrieval_score: float
    reason_codes: list[str]


@dataclass(frozen=True, slots=True)
class RagScoringConfig:
    exact_resource_score: float = 40.0
    related_resource_score: float = 15.0
    keyword_max_score: float = 15.0
    keyword_score_per_term: float = 5.0
    thread_lineage_score: float = 2.0


DEFAULT_RAG_SCORING_CONFIG = RagScoringConfig()
_MIN_QUERY_TERM_LENGTH = 2
_QUERY_TERM_CONSTRAINT_KINDS = frozenset({"PERSON", "USER_REQUIREMENT", "EMAIL"})


def rag_retrieve_rerank(
    segments: list[SourceSegment],
    *,
    request_intent: RequestIntentV2,
    source_plans: Sequence[SourceFetchPlanV1],
    top_k: int,
    config: RagScoringConfig = DEFAULT_RAG_SCORING_CONFIG,
) -> list[RagCandidateV1]:
    """Deterministically score, deduplicate, rank, and bound normalized segments."""
    selected = _selected_resource_ids(request_intent)
    terms = _query_terms(request_intent)
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
        matched = sum(1 for term in terms if term in segment.text.lower())
        if matched:
            score += min(config.keyword_max_score, matched * config.keyword_score_per_term)
            reasons.append("KEYWORD_MATCH")
        semantic_reasons = _semantic_match_reasons(segment, source_plans, request_intent)
        score += len(semantic_reasons) * config.keyword_score_per_term
        reasons.extend(semantic_reasons)
        scored.append((segment, score, reasons))

    relevant_threads = {
        _thread_id(segment) for segment, _, reasons in scored
        if reasons and _thread_id(segment) is not None
    }
    for index, (segment, score, reasons) in enumerate(scored):
        if not reasons and _thread_id(segment) in relevant_threads:
            scored[index] = (
                segment, score + config.thread_lineage_score, ["THREAD_LINEAGE_MATCH"],
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


def _thread_id(segment: SourceSegment) -> str | None:
    if segment.resource_type == "gmail_thread":
        return segment.resource_id
    if segment.resource_type == "gmail_message":
        value = segment.locator.get("thread_id")
        return value if isinstance(value, str) and value else segment.parent_id
    return None


def _semantic_match_reasons(
    segment: SourceSegment, plans: Sequence[SourceFetchPlanV1], intent: RequestIntentV2,
) -> list[str]:
    reasons: list[str] = []
    text = segment.text.casefold()
    sender = segment.locator.get("sender_email")
    recipients = segment.locator.get("recipients")
    sender_email = sender.casefold() if isinstance(sender, str) else None
    recipient_emails = {
        value.casefold() for value in recipients if isinstance(value, str)
    } if isinstance(recipients, list) else set()
    for plan in plans:
        resource_type = plan["resource_type"].lower()
        if resource_type != segment.resource_type and not (
            resource_type in {"gmail_thread", "gmail_message"}
            and segment.resource_type in {"gmail_thread", "gmail_message"}
        ):
            continue
        for constraint in plan["effective_constraints"]:
            if constraint["kind"] == "KEYWORD" and any(
                term.casefold() in text for term in constraint["terms"]
            ):
                reasons.append("EXACT_LEXICAL_ANCHOR")
            elif constraint["kind"] == "CONCEPT" and any(
                term.casefold() in text for term in constraint["manifestations"]
            ):
                reasons.append("CONCEPT_MANIFESTATION_MATCH")
            elif constraint["kind"] == "TEMPORAL_RANGE" and match_temporal_evidence(
                segment, constraint,
            ):
                reasons.append(
                    "MESSAGE_TIME_MATCH" if constraint["axis"] == "MESSAGE_TIME"
                    else "EVENT_TIME_CANDIDATE_MATCH"
                )
            elif constraint["kind"] == "PARTICIPANT":
                for person in constraint["participants"]:
                    identity = person["identity"].casefold()
                    if "@" not in identity:
                        continue
                    if (
                        person["role"] in {"ANY", "SENDER"} and identity == sender_email
                        or person["role"] in {"ANY", "RECIPIENT", "ATTENDEE"}
                        and identity in recipient_emails
                    ):
                        reasons.append("RESOLVED_PARTICIPANT_MATCH")
    display_name = segment.locator.get("sender_name")
    if isinstance(display_name, str) and sender_email:
        for item in intent["constraints"]:
            if item["kind"] != "PERSON":
                continue
            names = item["value"] if isinstance(item["value"], list) else [item["value"]]
            if any(match_person_mention(name, display_name) for name in names):
                reasons.append("ENTITY_CANDIDATE_MATCH")
    return list(dict.fromkeys(reasons))


def _selected_resource_ids(intent: RequestIntentV2) -> frozenset[str]:
    ids: set[str] = set()
    for constraint in intent["constraints"]:
        if constraint["kind"] == "RESOURCE":
            value = constraint["value"]
            ids.update(str(item) for item in (value if isinstance(value, list) else [value]))
    return frozenset(ids)


def _query_terms(intent: RequestIntentV2) -> frozenset[str]:
    terms = set(_clean_terms(intent["goal"]))
    for constraint in intent["constraints"]:
        if (
            constraint["kind"] in _QUERY_TERM_CONSTRAINT_KINDS
            and constraint["field"] != "original_search_request"
        ):
            value = constraint["value"]
            for item in value if isinstance(value, list) else [value]:
                terms.update(_clean_terms(str(item)))
    return frozenset(terms)


def _clean_terms(text: str) -> list[str]:
    return [
        cleaned
        for token in text.split()
        if len(cleaned := token.strip(".,!?;:'\"()[]{}~`").lower()) >= _MIN_QUERY_TERM_LENGTH
    ]
