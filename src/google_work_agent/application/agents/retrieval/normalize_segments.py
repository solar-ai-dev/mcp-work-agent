"""Canonical Retrieval deterministic operation: normalize_segments."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from math import ceil
from typing import Literal, cast

from google_work_agent.application.agents.retrieval.contracts.retrieval_result import (
    AcquisitionResultV1,
)
from google_work_agent.application.agents.retrieval.contracts.segment_identity import (
    SourceSegmentIdentityV1,
)
from google_work_agent.application.agents.retrieval.format_calendar_freebusy_evidence import (
    format_calendar_freebusy_evidence,
)
from google_work_agent.application.use_cases.resource.strip_resource_recovery_marker import (
    strip_resource_recovery_marker,
)
from google_work_agent.ports.connector.contracts.gmail_message_evidence import (
    MAX_THREAD_EVIDENCE_MESSAGES,
)


@dataclass(frozen=True, slots=True)
class ContextBudget:
    max_segments: int = 24
    max_segment_chars: int = 4000
    max_evidence: int = 12
    max_excerpt_chars: int = 1200
    max_normalized_context_items: int = 12
    chunk_target_tokens: int = 600
    chunk_max_tokens: int = 900
    chunk_overlap_tokens: int = 80


DEFAULT_CONTEXT_BUDGET = ContextBudget()
CHUNK_SCHEMA_VERSION = 3
MESSAGE_CHUNK_SCHEMA_VERSION = 4
GITHUB_CHUNK_SCHEMA_VERSION = 5
GMAIL_DRAFT_CHUNK_SCHEMA_VERSION = 6


@dataclass(frozen=True, slots=True)
class SourceSegment:
    segment_id: str
    resource_handle: str
    source: str
    resource_type: str
    resource_id: str
    parent_id: str | None
    version: str | None
    locator: dict[str, object]
    text: str


_TEXT_KEYS = ("title", "subject", "summary", "snippet", "body", "text", "description", "notes")
_GMAIL_RESOURCE_TYPES = {"gmail_thread", "gmail_message"}
_QUOTE_HEADER_PATTERN = re.compile(
    r"^(>|On .+ wrote:$|-{5,}\s*Original Message\s*-{5,}$|_{10,}$"
    r"|보낸사람\s*:|원본 메일|-{2,}\s*원본 메일\s*-{2,})",
    re.IGNORECASE,
)
_SIGNATURE_DELIMITER_PATTERN = re.compile(r"^--\s?$")


def normalize_segments(
    acquisition_result: AcquisitionResultV1,
    *,
    context_budget: ContextBudget = DEFAULT_CONTEXT_BUDGET,
    preferred_segment_ids: Sequence[str] = (),
) -> list[SourceSegment]:
    """Normalize, deduplicate, sanitize, chunk, and bound acquired resources."""
    segments_by_handle: dict[str, list[SourceSegment]] = {}
    seen: set[tuple[str, str]] = set()
    source_position = 0
    for summary in acquisition_result["source_summaries"]:
        source = str(summary.get("source", "UNKNOWN"))
        resources = summary.get("resources", [])
        if not isinstance(resources, list):
            continue
        for raw in _normalization_units(resources):
            if not isinstance(raw, dict):
                raise ValueError("$.source_summaries[].resources[] must be object")
            handle = raw.get("resource_handle")
            if not isinstance(handle, str) or not handle:
                raise ValueError("resource_handle must be non-empty string")
            resource_type = str(raw.get("resource_type", ""))
            text = _resource_text(raw, resource_type=resource_type)
            if not text.strip() or (handle, text) in seen:
                continue
            seen.add((handle, text))
            chunks = _chunk_text(text, context_budget)
            message_id = raw.get("message_id")
            unit_handle = handle if message_id is None else f"{handle}#message={message_id}"
            resource_segments = segments_by_handle.setdefault(unit_handle, [])
            for index, chunk in enumerate(chunks):
                if len(resource_segments) >= context_budget.max_segments:
                    break
                # Every chunk retains its provider message provenance, not just
                # the first header chunk. Identical bodies from peers are not one fact.
                provenance = "" if message_id is None else f"Message: {message_id}\n"
                normalized_chunk = _truncate(provenance + chunk, context_budget.max_segment_chars)
                identity: SourceSegmentIdentityV1 = {
                    "schema_version": 1,
                    "connector_id": _connector_id(raw, summary),
                    "source_kind": _source_kind(source),
                    "resource_type": resource_type,
                    "resource_id": str(raw.get("resource_id", "")),
                    "source_version_ref": _optional_string(raw.get("version")),
                    "chunk_schema_version": (
                        GITHUB_CHUNK_SCHEMA_VERSION
                        if resource_type == "github_issue"
                        else GMAIL_DRAFT_CHUNK_SCHEMA_VERSION
                        if resource_type == "gmail_draft"
                        else CHUNK_SCHEMA_VERSION
                        if message_id is None
                        else MESSAGE_CHUNK_SCHEMA_VERSION
                    ),
                    "chunk_ordinal": index,
                    "normalized_content_sha256": hashlib.sha256(
                        normalized_chunk.encode("utf-8")
                    ).hexdigest(),
                }
                resource_segments.append(
                    SourceSegment(
                        segment_id=_segment_id(identity),
                        resource_handle=handle,
                        source=source,
                        resource_type=resource_type,
                        resource_id=str(raw.get("resource_id", "")),
                        parent_id=_optional_string(raw.get("parent_id")),
                        version=_optional_string(raw.get("version")),
                        locator={
                            "kind": "resource_payload",
                            "position": source_position,
                            "chunk_index": index,
                            "chunk_count": len(chunks),
                            **_gmail_draft_snapshot_locator(raw, resource_type=resource_type),
                            **cast(dict[str, object], raw.get("_message_locator", {})),
                        },
                        text=normalized_chunk,
                    )
                )
                source_position += 1
    return _round_robin_segments(
        list(segments_by_handle.values()),
        max_segments=context_budget.max_segments,
        preferred_segment_ids=preferred_segment_ids,
    )


def _normalization_units(resources: list[object]) -> list[dict[str, object]]:
    """Keep each message's headers/body independent of peer signatures and quotes."""
    units: list[dict[str, object]] = []
    for raw in resources:
        if not isinstance(raw, dict):
            raise ValueError("$.source_summaries[].resources[] must be object")
        payload = raw.get("payload")
        if (
            raw.get("resource_type") != "gmail_thread"
            or not isinstance(payload, dict)
            or "messages" not in payload
        ):
            # Existing generic snapshots without the additive detail field remain readable.
            if raw.get("resource_type") in _GMAIL_RESOURCE_TYPES and isinstance(payload, dict):
                metadata = {
                    key: payload[key]
                    for key in ("sender_name", "sender_email", "received_at")
                    if key in payload
                }
                if any(
                    value is not None and not isinstance(value, str) for value in metadata.values()
                ):
                    raise ValueError("invalid Gmail candidate metadata")
                units.append(
                    {
                        **raw,
                        "_message_locator": {
                            **metadata,
                            "is_metadata_only": not any(key in payload for key in ("body", "text")),
                        },
                    }
                )
            else:
                units.append(raw)
            continue
        messages = payload["messages"]
        if not isinstance(messages, list) or len(messages) > MAX_THREAD_EVIDENCE_MESSAGES:
            raise ValueError("Gmail message evidence must be a bounded list")
        for message in messages:
            optional_fields = {"rfc822_message_id", "references"}
            if not isinstance(message, dict) or set(message) - optional_fields != {
                "message_id",
                "thread_id",
                "sender_name",
                "sender_email",
                "recipients",
                "received_at",
                "subject",
                "body",
                "body_truncated",
            }:
                raise ValueError("incomplete Gmail message evidence contract")
            if (
                not isinstance(message["message_id"], str)
                or not message["message_id"]
                or message["thread_id"] != raw.get("resource_id")
            ):
                raise ValueError("Gmail message/thread binding mismatch")
            if not isinstance(message["recipients"], list) or not all(
                isinstance(value, str) for value in message["recipients"]
            ):
                raise ValueError("invalid Gmail message recipients")
            if any(
                message[key] is not None and not isinstance(message[key], str)
                for key in (
                    "sender_name",
                    "sender_email",
                    "received_at",
                    "subject",
                    "body",
                )
            ) or not isinstance(message["body_truncated"], bool):
                raise ValueError("invalid Gmail message metadata")
            message_count = payload.get("message_count")
            if not isinstance(message_count, int) or message_count < len(messages):
                raise ValueError("invalid Gmail message coverage")
            headers = [
                f"Thread messages collected: {len(messages)}/{message_count}",
                f"From: {message['sender_name'] or ''} <{message['sender_email'] or ''}>",
                f"To: {', '.join(message['recipients'])}",
                f"Received: {message['received_at'] or 'unknown'}",
            ]
            for name in ("rfc822_message_id", "references"):
                value = message.get(name)
                if value is not None:
                    if not isinstance(value, str):
                        raise ValueError("invalid Gmail reply metadata")
                    headers.append(f"{name}: {value}")
            body = _strip_email_quote_and_signature(message["body"] or "")
            if message["body_truncated"]:
                body += "\n[본문 일부만 수집됨]"
            units.append(
                {
                    **raw,
                    "message_id": message["message_id"],
                    "_message_locator": {
                        **{
                            key: message[key]
                            for key in (
                                "message_id",
                                "thread_id",
                                "sender_name",
                                "sender_email",
                                "recipients",
                                "received_at",
                            )
                        },
                        "rfc822_message_id": message.get("rfc822_message_id"),
                        "references": message.get("references"),
                    },
                    "payload": {
                        "subject": message["subject"],
                        "body": "\n".join([*headers, body]),
                    },
                }
            )
    return units


def _round_robin_segments(
    resource_segments: list[list[SourceSegment]],
    *,
    max_segments: int,
    preferred_segment_ids: Sequence[str] = (),
) -> list[SourceSegment]:
    """Bound context without allowing one long resource to hide its peers."""

    by_id = {segment.segment_id: segment for group in resource_segments for segment in group}
    preferred = [by_id[key] for key in dict.fromkeys(preferred_segment_ids) if key in by_id]
    preferred_sources = {segment.source for segment in preferred}
    new_sources: dict[str, SourceSegment] = {}
    for group in resource_segments:
        if group and group[0].source not in preferred_sources:
            new_sources.setdefault(group[0].source, group[0])
    reserved = list(new_sources.values())[:max_segments] if preferred else []
    result = preferred[: max(0, max_segments - len(reserved))] + reserved
    selected = {segment.segment_id for segment in result}
    if result and len(result) < max_segments:
        # Retaining earlier evidence must not hide a newly acquired source category.
        sources = {segment.source for segment in result}
        for group in resource_segments:
            if group and group[0].source not in sources and len(result) < max_segments:
                result.append(group[0])
                selected.add(group[0].segment_id)
                sources.add(group[0].source)
    chunk_index = 0
    while len(result) < max_segments:
        added = False
        for segments in resource_segments:
            if chunk_index >= len(segments):
                continue
            added = True
            if segments[chunk_index].segment_id in selected:
                continue
            result.append(segments[chunk_index])
            selected.add(segments[chunk_index].segment_id)
            if len(result) >= max_segments:
                return result
        if not added:
            return result
        chunk_index += 1
    return result


def _resource_text(resource: dict[str, object], *, resource_type: str) -> str:
    payload = resource.get("payload")
    if not isinstance(payload, dict):
        return ""
    if resource_type == "calendar_freebusy":
        return format_calendar_freebusy_evidence(payload)
    if resource_type == "gmail_draft":
        return _gmail_draft_text(resource, payload)
    if resource_type == "github_issue":
        fields = []
        for key in ("repository", "issue_number", "title", "state", "url"):
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                fields.append(f"{key}: {value.strip()}")
            elif key == "issue_number" and type(value) is int and value > 0:
                fields.append(f"{key}: {value}")
        description = payload.get("description")
        if isinstance(description, str) and description.strip():
            fields.append(f"description:\n{description.strip()}")
        return "\n".join(fields)
    if resource_type == "task":
        fields = []
        parent_id = resource.get("parent_id")
        if isinstance(parent_id, str) and parent_id.strip():
            fields.append(f"task_list_id: {parent_id.strip()}")
        for key in ("title", "status", "due"):
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                fields.append(f"{key}: {value.strip()}")
        notes = payload.get("notes")
        if isinstance(notes, str):
            visible_notes = strip_resource_recovery_marker(notes)
            if visible_notes is not None and visible_notes.strip():
                fields.append(f"notes:\n{visible_notes.strip()}")
        if fields:
            return "\n".join(fields)
    if resource_type == "calendar_event":
        fields = []
        for label, value in (
            ("calendar_id", resource.get("parent_id")),
            ("event_id", resource.get("resource_id")),
            ("title", payload.get("title")),
            ("start", payload.get("start")),
            ("end", payload.get("end")),
            ("timezone", payload.get("timezone")),
            ("status", payload.get("status")),
            ("location", payload.get("location")),
            ("description", payload.get("description")),
        ):
            if isinstance(value, str) and value.strip():
                fields.append(f"{label}: {value.strip()}")
        attendees = payload.get("attendees")
        if isinstance(attendees, list) and all(isinstance(value, str) for value in attendees):
            fields.append("attendees: " + (", ".join(attendees) if attendees else "[]"))
        return "\n".join(fields)
    parts: list[str] = []
    if resource_type in _GMAIL_RESOURCE_TYPES:
        # Metadata was acquired by the provider, not inferred from the snippet.
        for key, label in (
            ("sender_name", "Sender name"),
            ("sender_email", "Sender email"),
            ("received_at", "Received"),
        ):
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                parts.append(f"{label}: {value.strip()}")
    for key in _TEXT_KEYS:
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            normalized = value.strip()
            if key == "body" and resource_type in _GMAIL_RESOURCE_TYPES:
                normalized = _strip_email_quote_and_signature(normalized)
            if normalized:
                parts.append(normalized)
    if not parts:
        parts.extend(
            f"{key}: {value.strip()}"
            for key, value in payload.items()
            if isinstance(value, str) and value.strip()
        )
    return "\n".join(parts)


def _gmail_draft_text(resource: Mapping[str, object], payload: Mapping[str, object]) -> str:
    fields = [f"draft_id: {resource.get('resource_id', '')}"]
    for key in (
        "to",
        "cc",
        "bcc",
        "subject",
        "thread_id",
        "in_reply_to",
        "references",
        "attachments",
    ):
        value = payload.get(key)
        if isinstance(value, (str, list)) or value is None:
            fields.append(f"{key}: {json.dumps(value, ensure_ascii=False, separators=(',', ':'))}")
    body = payload.get("body")
    if isinstance(body, str):
        fields.append(f"body:\n{body}")
    return "\n".join(fields)


def _gmail_draft_snapshot_locator(
    resource: Mapping[str, object], *, resource_type: str
) -> dict[str, object]:
    """Project the complete editable Draft state needed by the existing UPDATE binder."""

    if resource_type != "gmail_draft":
        return {}
    payload = resource.get("payload")
    if not isinstance(payload, Mapping):
        raise ValueError("Gmail Draft evidence requires a provider payload")
    snapshot: dict[str, object] = {}
    for name in ("to", "cc", "bcc", "attachments"):
        value = payload.get(name, [])
        if not isinstance(value, list):
            raise ValueError(f"Gmail Draft {name} must be a list")
        snapshot[name] = list(value)
    for name in ("subject", "body"):
        value = payload.get(name)
        if not isinstance(value, str):
            raise ValueError(f"Gmail Draft {name} must be a string")
        snapshot[name] = value
    for name in ("thread_id", "in_reply_to", "references"):
        value = payload.get(name)
        if value is not None and not isinstance(value, str):
            raise ValueError(f"Gmail Draft {name} must be a string or null")
        snapshot[name] = value
    return {"draft_snapshot": snapshot}


def _strip_email_quote_and_signature(text: str) -> str:
    kept: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if _QUOTE_HEADER_PATTERN.match(stripped) or _SIGNATURE_DELIMITER_PATTERN.match(stripped):
            break
        kept.append(line)
    return "\n".join(kept).strip()


def _estimate_tokens(text: str) -> int:
    stripped = text.strip()
    return 0 if not stripped else max(1, ceil(len(stripped.encode("utf-8"))))


def _chunk_text(text: str, context_budget: ContextBudget) -> list[str]:
    words = list(re.finditer(r"\S+", text))
    if not words:
        return []
    if _estimate_tokens(text) <= context_budget.chunk_max_tokens:
        return [text]
    chunks: list[str] = []
    start = 0
    while start < len(words):
        count = 0
        end = start
        while end < len(words):
            word_tokens = _estimate_tokens(words[end].group()) + (
                len(text[words[end - 1].end() : words[end].start()].encode("utf-8"))
                if end > start
                else 0
            )
            if count + word_tokens > context_budget.chunk_max_tokens and end > start:
                break
            count += word_tokens
            end += 1
            if count >= context_budget.chunk_target_tokens:
                break
        # Preserve source layout: a receipt header, a newsletter heading and
        # the following item's date must not become one synthetic sentence.
        chunks.append(text[words[start].start() : words[end - 1].end()])
        if end >= len(words):
            break
        overlap_start = end
        overlap = 0
        while overlap_start > start and overlap < context_budget.chunk_overlap_tokens:
            overlap_start -= 1
            overlap += _estimate_tokens(words[overlap_start].group())
        start = max(overlap_start, start + 1)
    return chunks


def _optional_string(value: object) -> str | None:
    return None if value is None else str(value)


def _truncate(value: str, max_chars: int) -> str:
    return value if len(value) <= max_chars else value[:max_chars]


def _connector_id(resource: dict[str, object], summary: dict[str, object]) -> str:
    source = str(summary.get("source", "")).upper()
    expected = {
        "GMAIL": "google_workspace",
        "TASKS": "google_workspace",
        "CALENDAR": "google_workspace",
        "GITHUB": "github",
    }.get(source)
    value = resource.get("connector_id", summary.get("connector_id"))
    if value is None and source in {"GMAIL", "TASKS", "CALENDAR"}:
        value = expected  # Explicit legacy Google acquisition contract.
    if not isinstance(value, str) or not value.strip():
        raise ValueError("connector_id must be a non-empty string")
    if value != expected:
        raise ValueError("acquisition connector_id does not match its source")
    return value


def _source_kind(source: str) -> LiteralSourceKind:
    try:
        return cast(
            LiteralSourceKind,
            {
                "GMAIL": "gmail",
                "TASKS": "tasks",
                "CALENDAR": "calendar",
                "GITHUB": "github",
            }[source.upper()],
        )
    except KeyError as error:
        raise ValueError(f"unsupported retrieval source kind: {source}") from error


def _segment_id(identity: SourceSegmentIdentityV1) -> str:
    canonical = json.dumps(identity, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return "seg_" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


LiteralSourceKind = Literal["gmail", "tasks", "calendar", "github"]


class RetrievalValidationError(ValueError):
    """Raised when a Retrieval semantic result violates its current contract."""


__all__ = [
    "ContextBudget",
    "DEFAULT_CONTEXT_BUDGET",
    "RetrievalValidationError",
    "SourceSegment",
    "_chunk_text",
    "_estimate_tokens",
    "_resource_text",
    "_strip_email_quote_and_signature",
    "_truncate",
]
