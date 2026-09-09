"""Bind a Gmail Draft UPDATE to its retrieved provider identity."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from google_work_agent.application.agents.planning.resolve_default_container import (
    PlanningArgumentBindingError,
)


def bind_gmail_draft_update_identity(
    *,
    route: Mapping[str, object],
    action_objective: Mapping[str, object],
    arguments: Mapping[str, object],
    evidence: Sequence[Mapping[str, object]],
) -> tuple[dict[str, object], list[str]]:
    if not _is_gmail_draft_update_route(route):
        return dict(arguments), []
    if action_objective.get("target_semantics") != "GMAIL_DRAFT":
        raise PlanningArgumentBindingError("Gmail Draft UPDATE target semantics are invalid")

    identities: dict[str, tuple[dict[str, object], list[str]]] = {}
    for item in evidence:
        handle = item.get("resource_handle")
        evidence_ref = item.get("evidence_ref") or item.get("evidence_id") or item.get("id")
        if (
            not isinstance(handle, str)
            or not handle.startswith("gmail_draft:")
            or not isinstance(evidence_ref, str)
            or not evidence_ref
        ):
            continue
        locator = item.get("locator")
        snapshot = locator.get("draft_snapshot") if isinstance(locator, Mapping) else None
        draft_id = handle.removeprefix("gmail_draft:")
        if not draft_id or not isinstance(snapshot, Mapping):
            continue
        projected = _validated_snapshot(snapshot)
        if draft_id in identities and identities[draft_id][0] != projected:
            raise PlanningArgumentBindingError("Gmail Draft evidence snapshots disagree")
        _, refs = identities.setdefault(draft_id, (projected, []))
        refs.append(evidence_ref)
    if len(identities) != 1:
        raise PlanningArgumentBindingError(
            "Gmail Draft UPDATE requires exactly one retrieved Draft identity"
        )

    draft_id, (snapshot, evidence_refs) = next(iter(identities.items()))
    model_draft_id = arguments.get("draft_id")
    if model_draft_id is not None and model_draft_id != draft_id:
        raise PlanningArgumentBindingError(
            "Gmail Draft UPDATE cannot override retrieved Draft identity"
        )
    patch = arguments.get("payload")
    if not isinstance(patch, Mapping) or not patch:
        raise PlanningArgumentBindingError("Gmail Draft UPDATE requires a non-empty payload patch")
    unknown = set(patch) - set(snapshot)
    if unknown:
        raise PlanningArgumentBindingError("Gmail Draft UPDATE patch contains unknown fields")
    return {
        **arguments,
        "draft_id": draft_id,
        "payload": {**snapshot, **dict(patch)},
    }, list(dict.fromkeys(evidence_refs))


def _validated_snapshot(value: Mapping[str, object]) -> dict[str, object]:
    expected = {
        "to",
        "cc",
        "bcc",
        "subject",
        "body",
        "thread_id",
        "in_reply_to",
        "references",
        "attachments",
    }
    if set(value) != expected:
        raise PlanningArgumentBindingError("Gmail Draft evidence snapshot is incomplete")
    if not isinstance(value["to"], list) or not value["to"]:
        raise PlanningArgumentBindingError("Gmail Draft evidence requires recipients")
    if any(not isinstance(value[name], list) for name in ("cc", "bcc", "attachments")):
        raise PlanningArgumentBindingError("Gmail Draft list fields are invalid")
    if any(not isinstance(value[name], str) for name in ("subject", "body")):
        raise PlanningArgumentBindingError("Gmail Draft text fields are invalid")
    if any(
        value[name] is not None and not isinstance(value[name], str)
        for name in ("thread_id", "in_reply_to", "references")
    ):
        raise PlanningArgumentBindingError("Gmail Draft reply fields are invalid")
    return {name: value[name] for name in expected}


def _is_gmail_draft_update_route(route: Mapping[str, object]) -> bool:
    return (
        route.get("connector_id") == "google_workspace"
        and route.get("resource_type") == "GMAIL_DRAFT"
        and route.get("effect") == "UPDATE"
        and route.get("selected_tool_id") == "gmail_update_draft"
    )


__all__ = ["bind_gmail_draft_update_identity"]
