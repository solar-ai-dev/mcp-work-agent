"""Bind a Gmail Thread Reply to validated provider message identity."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime

from google_work_agent.application.agents.planning.resolve_default_container import (
    PlanningArgumentBindingError,
)


def bind_gmail_thread_reply_identity(
    *,
    route: Mapping[str, object],
    request_intent: Mapping[str, object] | None,
    arguments: Mapping[str, object],
    evidence: Sequence[Mapping[str, object]],
) -> tuple[dict[str, object], list[str]]:
    """Preserve one retrieved Thread's current RFC reply chain in write arguments."""
    if not _is_gmail_thread_reply(route=route, request_intent=request_intent):
        return dict(arguments), []
    payload = arguments.get("payload")
    if not isinstance(payload, Mapping):
        raise PlanningArgumentBindingError("Gmail Thread Reply requires a payload")

    identities: dict[tuple[str, str], tuple[str | None, str | None, list[str]]] = {}
    for item in evidence:
        handle = item.get("resource_handle")
        locator = item.get("locator")
        if not isinstance(handle, str) or not handle.startswith("gmail_thread:"):
            continue
        if not isinstance(locator, Mapping):
            continue
        thread_id = locator.get("thread_id")
        message_id = locator.get("rfc822_message_id")
        references = locator.get("references")
        received_at = locator.get("received_at")
        evidence_ref = item.get("evidence_ref") or item.get("evidence_id") or item.get("id")
        if (
            not isinstance(thread_id, str)
            or not thread_id
            or handle != f"gmail_thread:{thread_id}"
            or not isinstance(message_id, str)
            or not message_id
            or references is not None
            and not isinstance(references, str)
            or received_at is not None
            and not isinstance(received_at, str)
            or not isinstance(evidence_ref, str)
            or not evidence_ref
        ):
            continue
        identity = (thread_id, message_id)
        prior_references, prior_received_at, refs = identities.setdefault(
            identity, (references, received_at, [])
        )
        if prior_references != references or prior_received_at != received_at:
            raise PlanningArgumentBindingError("Gmail reply evidence has conflicting metadata")
        refs.append(evidence_ref)

    thread_ids = {identity[0] for identity in identities}
    if not identities or len(thread_ids) != 1:
        raise PlanningArgumentBindingError(
            "Gmail Thread Reply requires exactly one validated Thread identity"
        )
    if len(identities) == 1:
        selected = next(iter(identities.items()))
    else:
        timestamped = [
            (identity, metadata, _gmail_reply_timestamp(metadata[1]))
            for identity, metadata in identities.items()
        ]
        if any(timestamp is None for _, _, timestamp in timestamped):
            raise PlanningArgumentBindingError(
                "Gmail Thread Reply requires ordered message evidence"
            )
        latest = max(timestamp for _, _, timestamp in timestamped if timestamp is not None)
        latest_messages = [
            (identity, metadata)
            for identity, metadata, timestamp in timestamped
            if timestamp == latest
        ]
        if len(latest_messages) != 1:
            raise PlanningArgumentBindingError(
                "Gmail Thread Reply latest message identity is ambiguous"
            )
        selected = latest_messages[0]
    (thread_id, message_id), (prior_references, _, evidence_refs) = selected
    reference_tokens = prior_references.split() if prior_references else []
    if message_id not in reference_tokens:
        reference_tokens.append(message_id)
    bindings = {
        "thread_id": thread_id,
        "in_reply_to": message_id,
        "references": " ".join(reference_tokens),
    }
    bound_payload = dict(payload)
    for name, expected in bindings.items():
        actual = bound_payload.get(name)
        if actual is not None and actual != expected:
            raise PlanningArgumentBindingError(
                f"argument candidate attempts to override Gmail reply {name}"
            )
        bound_payload[name] = expected
    return {**arguments, "payload": bound_payload}, list(dict.fromkeys(evidence_refs))


def _gmail_reply_timestamp(value: str | None) -> datetime | None:
    if value is None:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else None


def _is_gmail_thread_reply(
    *, route: Mapping[str, object], request_intent: Mapping[str, object] | None
) -> bool:
    if (
        route.get("connector_id") != "google_workspace"
        or route.get("resource_type") != "GMAIL_MESSAGE"
        or route.get("effect") != "SEND"
        or route.get("selected_tool_id") != "gmail_send"
        or not isinstance(request_intent, Mapping)
    ):
        return False
    effects = request_intent.get("requested_effect_hints")
    resources = request_intent.get("requested_resource_hints")
    return (
        isinstance(effects, Sequence)
        and not isinstance(effects, (str, bytes))
        and set(effects) == {"READ", "SEND"}
        and isinstance(resources, Sequence)
        and not isinstance(resources, (str, bytes))
        and "GMAIL_THREAD" in resources
    )


__all__ = ["bind_gmail_thread_reply_identity"]
