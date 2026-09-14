"""Recognize Gmail collection answers fully supported by search metadata."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from google_work_agent.application.agents.request_understanding.contracts.request_intent import (
    RequestIntentV2,
)

_GMAIL_THREAD_METADATA_FACTS = frozenset(
    {"thread_identity", "subject", "participants", "timestamps"}
)
_GMAIL_SUBJECT_MARKERS = ("subject", "title", "제목")
_GMAIL_CONTENT_MARKERS = (
    "body",
    "content",
    "message_history",
    "본문",
    "내용",
    "대화 이력",
)


def gmail_metadata_collection_is_answer_target(request_intent: RequestIntentV2) -> bool:
    """Return whether exhaustive Gmail search metadata contains every requested fact."""

    constraints = request_intent.get("constraints")
    if (
        request_intent.get("analysis_requirement") != "NONE"
        or not isinstance(constraints, list)
        or not any(
        constraint["kind"] == "SCOPE"
        and constraint["field"] == "coverage_requirement"
        and constraint["value"] == "EXHAUSTIVE"
        for constraint in constraints
        )
    ):
        return False
    responsibilities = request_intent.get("resource_responsibilities")
    if not isinstance(responsibilities, Mapping):
        return False
    source_reads = responsibilities.get("source_reads")
    if not isinstance(source_reads, Sequence):
        return False
    information = [
        value.strip().casefold()
        for source in source_reads
        if isinstance(source, Mapping) and source.get("resource_type") == "GMAIL_THREAD"
        for value in source.get("required_information", [])
        if isinstance(value, str) and value.strip()
    ]
    if not information:
        return False
    return all(
        value in _GMAIL_THREAD_METADATA_FACTS
        or (
            any(marker in value for marker in _GMAIL_SUBJECT_MARKERS)
            and not any(marker in value for marker in _GMAIL_CONTENT_MARKERS)
        )
        for value in information
    )


__all__ = ["gmail_metadata_collection_is_answer_target"]
