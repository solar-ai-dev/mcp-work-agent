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
    source_snapshots: Mapping[str, Mapping[str, object]],
    selected_evidence_refs: Sequence[str],
) -> tuple[dict[str, object], list[str]]:
    if not _is_gmail_draft_update_route(route):
        return dict(arguments), []
    if action_objective.get("target_semantics") != "GMAIL_DRAFT":
        raise PlanningArgumentBindingError("Gmail Draft UPDATE target semantics are invalid")

    selected = set(selected_evidence_refs)
    identities: dict[str, tuple[dict[str, object], list[str]]] = {}
    for item in evidence:
        handle = item.get("resource_handle")
        evidence_ref = item.get("evidence_ref") or item.get("evidence_id") or item.get("id")
        if (
            not isinstance(handle, str)
            or not handle.startswith("gmail_draft:")
            or not isinstance(evidence_ref, str)
            or not evidence_ref
            or (selected and evidence_ref not in selected)
        ):
            continue
        draft_id = handle.removeprefix("gmail_draft:")
        snapshot = source_snapshots.get(evidence_ref)
        if not draft_id or snapshot is None:
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
    if all(snapshot[name] == value for name, value in patch.items()):
        raise PlanningArgumentBindingError("Gmail Draft UPDATE patch does not change the source")
    return {
        **arguments,
        "draft_id": draft_id,
        "payload": {**snapshot, **dict(patch)},
    }, list(dict.fromkeys(evidence_refs))


def project_gmail_draft_editable_source(
    *,
    route: Mapping[str, object],
    evidence: Sequence[Mapping[str, object]],
    source_snapshots: Mapping[str, Mapping[str, object]],
    preferred_evidence_refs: Sequence[str],
) -> dict[str, object] | None:
    """Project one current Draft's editable values without exposing provider identity fields."""

    if not _is_gmail_draft_update_route(route):
        return None
    preferred = set(preferred_evidence_refs)
    candidates: dict[str, dict[str, object]] = {}
    for item in evidence:
        handle = item.get("resource_handle")
        evidence_ref = item.get("evidence_ref") or item.get("evidence_id") or item.get("id")
        if (
            not isinstance(handle, str)
            or not handle.startswith("gmail_draft:")
            or not isinstance(evidence_ref, str)
            or not evidence_ref
            or (preferred and evidence_ref not in preferred)
        ):
            continue
        snapshot = source_snapshots.get(evidence_ref)
        if snapshot is None:
            continue
        validated = _validated_snapshot(snapshot)
        existing = candidates.get(handle)
        if existing is not None and existing != validated:
            return None
        candidates[handle] = validated
    if len(candidates) != 1:
        return None
    snapshot = next(iter(candidates.values()))
    return {
        name: snapshot[name]
        for name in ("to", "cc", "bcc", "subject", "body", "attachments")
    }


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
    if not isinstance(value["to"], list):
        raise PlanningArgumentBindingError("Gmail Draft recipients are invalid")
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


__all__ = ["bind_gmail_draft_update_identity", "project_gmail_draft_editable_source"]
