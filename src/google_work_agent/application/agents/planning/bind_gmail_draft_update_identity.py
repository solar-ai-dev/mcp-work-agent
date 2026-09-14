"""Bind a Gmail Draft UPDATE to its retrieved provider identity."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from google_work_agent.application.agents.planning.resolve_default_container import (
    PlanningArgumentBindingError,
)
from google_work_agent.application.agents.preserve_exact_user_literals import (
    quoted_user_literals,
)
from google_work_agent.ports.system.contracts.workflow_execution import SelectedResourceRef


class GmailDraftUpdateAlreadySatisfiedError(PlanningArgumentBindingError):
    """The requested patch is already present in the authoritative Draft snapshot."""

    def __init__(self, *, route_id: str, evidence_refs: Sequence[str]) -> None:
        super().__init__("Gmail Draft UPDATE patch does not change the source")
        self.route_id = route_id
        self.evidence_refs = tuple(dict.fromkeys(evidence_refs))


def bind_gmail_draft_update_identity(
    *,
    route: Mapping[str, object],
    action_objective: Mapping[str, object],
    arguments: Mapping[str, object],
    evidence: Sequence[Mapping[str, object]],
    source_snapshots: Mapping[str, Mapping[str, object]],
    selected_evidence_refs: Sequence[str],
    selected_resources: Sequence[SelectedResourceRef] = (),
    request_intent: Mapping[str, object] | None = None,
) -> tuple[dict[str, object], list[str]]:
    if not _is_gmail_draft_update_route(route):
        return dict(arguments), []
    if action_objective.get("target_semantics") != "GMAIL_DRAFT":
        raise PlanningArgumentBindingError("Gmail Draft UPDATE target semantics are invalid")

    authoritative_handle = _authoritative_draft_handle(
        evidence=evidence,
        source_snapshots=source_snapshots,
        selected_resources=selected_resources,
    )
    selected = set(selected_evidence_refs)
    identities: dict[str, tuple[dict[str, object], list[str]]] = {}
    for item in evidence:
        handle = item.get("resource_handle")
        evidence_ref = item.get("evidence_ref") or item.get("evidence_id") or item.get("id")
        if (
            not isinstance(handle, str)
            or handle != authoritative_handle
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
    patch = _materialize_exact_body_append(
        patch,
        snapshot=snapshot,
        request_intent=request_intent,
    )
    unknown = set(patch) - set(snapshot)
    if unknown:
        raise PlanningArgumentBindingError("Gmail Draft UPDATE patch contains unknown fields")
    if all(snapshot[name] == value for name, value in patch.items()):
        raise GmailDraftUpdateAlreadySatisfiedError(
            route_id=str(route["route_id"]),
            evidence_refs=evidence_refs,
        )
    return {
        **arguments,
        "draft_id": draft_id,
        "payload": {**snapshot, **dict(patch)},
    }, list(dict.fromkeys(evidence_refs))


def _materialize_exact_body_append(
    patch: Mapping[str, object],
    *,
    snapshot: Mapping[str, object],
    request_intent: Mapping[str, object] | None,
) -> dict[str, object]:
    """Recover one explicit body edit only when the inferred patch is a no-op."""

    copied = dict(patch)
    current_body = snapshot.get("body")
    if (
        "body" not in copied
        or not isinstance(current_body, str)
        or copied["body"] != current_body
        or any(snapshot.get(name) != value for name, value in copied.items())
    ):
        return copied
    literal = _required_exact_body_literal(request_intent)
    if literal is None or literal in current_body:
        return copied
    separator = "" if not current_body or current_body.endswith(("\n", "\r")) else "\n"
    copied["body"] = f"{current_body}{separator}{literal}"
    return copied


def _required_exact_body_literal(
    request_intent: Mapping[str, object] | None,
) -> str | None:
    if not isinstance(request_intent, Mapping):
        return None
    constraints = request_intent.get("constraints")
    completion_conditions = request_intent.get("completion_conditions")
    if not isinstance(constraints, list) or not isinstance(completion_conditions, list):
        return None
    source_texts: list[str] = []
    body_semantics: list[str] = []
    for constraint in constraints:
        if not isinstance(constraint, Mapping):
            continue
        raw_value = constraint.get("value")
        values = raw_value if isinstance(raw_value, list) else [raw_value]
        strings = [value for value in values if isinstance(value, str)]
        if constraint.get("field") == "original_search_request":
            source_texts.extend(strings)
        if constraint.get("kind") == "RESOURCE" and constraint.get("field") == "notes":
            body_semantics.extend(strings)
    candidates = list(
        dict.fromkeys(
            literal
            for source_text in source_texts
            for literal in quoted_user_literals(source_text)
            if any(literal in semantic for semantic in body_semantics)
            and any(
                isinstance(condition, str) and literal in condition
                for condition in completion_conditions
            )
        )
    )
    return candidates[0] if len(candidates) == 1 else None


def project_gmail_draft_editable_source(
    *,
    route: Mapping[str, object],
    evidence: Sequence[Mapping[str, object]],
    source_snapshots: Mapping[str, Mapping[str, object]],
    preferred_evidence_refs: Sequence[str],
    selected_resources: Sequence[SelectedResourceRef] = (),
) -> dict[str, object] | None:
    """Project one current Draft's editable values without exposing provider identity fields."""

    if not _is_gmail_draft_update_route(route):
        return None
    try:
        authoritative_handle = _authoritative_draft_handle(
            evidence=evidence,
            source_snapshots=source_snapshots,
            selected_resources=selected_resources,
        )
    except PlanningArgumentBindingError:
        return None
    preferred = set(preferred_evidence_refs)
    candidates: dict[str, dict[str, object]] = {}
    for item in evidence:
        handle = item.get("resource_handle")
        evidence_ref = item.get("evidence_ref") or item.get("evidence_id") or item.get("id")
        if (
            not isinstance(handle, str)
            or handle != authoritative_handle
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


def _authoritative_draft_handle(
    *,
    evidence: Sequence[Mapping[str, object]],
    source_snapshots: Mapping[str, Mapping[str, object]],
    selected_resources: Sequence[SelectedResourceRef],
) -> str:
    eligible_handles = {
        handle
        for item in evidence
        for handle, evidence_ref in (_draft_handle_and_evidence_ref(item),)
        if handle is not None
        and evidence_ref is not None
        and evidence_ref in source_snapshots
    }
    selected_handles = {
        f"gmail_draft:{item.resource_id}"
        for item in selected_resources
        if item.resource_type == "gmail_draft"
    }
    if selected_handles:
        if len(selected_handles) != 1:
            raise PlanningArgumentBindingError(
                "Gmail Draft UPDATE requires exactly one selected Draft identity"
            )
        selected_handle = next(iter(selected_handles))
        if selected_handle not in eligible_handles:
            raise PlanningArgumentBindingError(
                "selected Gmail Draft identity has no current-run source snapshot"
            )
        return selected_handle
    if len(eligible_handles) != 1:
        raise PlanningArgumentBindingError(
            "Gmail Draft UPDATE requires exactly one retrieved Draft identity"
        )
    return next(iter(eligible_handles))


def _draft_handle_and_evidence_ref(
    item: Mapping[str, object],
) -> tuple[str | None, str | None]:
    handle = item.get("resource_handle")
    evidence_ref = item.get("evidence_ref") or item.get("evidence_id") or item.get("id")
    return (
        handle if isinstance(handle, str) and handle.startswith("gmail_draft:") else None,
        evidence_ref if isinstance(evidence_ref, str) and evidence_ref else None,
    )


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


__all__ = [
    "GmailDraftUpdateAlreadySatisfiedError",
    "bind_gmail_draft_update_identity",
    "project_gmail_draft_editable_source",
]
