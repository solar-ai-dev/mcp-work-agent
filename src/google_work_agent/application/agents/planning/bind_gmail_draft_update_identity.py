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

    identities: dict[str, list[str]] = {}
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
        draft_id = handle.removeprefix("gmail_draft:")
        if draft_id:
            identities.setdefault(draft_id, []).append(evidence_ref)
    if len(identities) != 1:
        raise PlanningArgumentBindingError(
            "Gmail Draft UPDATE requires exactly one retrieved Draft identity"
        )

    draft_id, evidence_refs = next(iter(identities.items()))
    model_draft_id = arguments.get("draft_id")
    if model_draft_id is not None and model_draft_id != draft_id:
        raise PlanningArgumentBindingError(
            "Gmail Draft UPDATE cannot override retrieved Draft identity"
        )
    return {**arguments, "draft_id": draft_id}, list(dict.fromkeys(evidence_refs))


def _is_gmail_draft_update_route(route: Mapping[str, object]) -> bool:
    return (
        route.get("connector_id") == "google_workspace"
        and route.get("resource_type") == "GMAIL_DRAFT"
        and route.get("effect") == "UPDATE"
        and route.get("selected_tool_id") == "gmail_update_draft"
    )


__all__ = ["bind_gmail_draft_update_identity"]
