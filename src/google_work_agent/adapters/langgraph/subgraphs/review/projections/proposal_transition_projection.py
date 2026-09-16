"""Bounded relation between a reviewed proposal and its same-route revision."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from copy import deepcopy


def capture_reviewed_proposal(
    planning_result: Mapping[str, object], review_result: Mapping[str, object]
) -> dict[str, object] | None:
    """Keep only an unambiguous affected Action, not the entire previous Plan."""
    if review_result.get("status") != "REVISE":
        return None
    issues = review_result.get("issues")
    actions = planning_result.get("actions")
    meta = planning_result.get("meta")
    if (
        not isinstance(issues, list)
        or not isinstance(actions, list)
        or not isinstance(meta, Mapping)
    ):
        return None
    route_ids = {
        route_id
        for issue in issues
        if isinstance(issue, Mapping)
        for route_id in _strings(issue.get("affected_route_ids"))
    }
    if len(route_ids) != 1:
        return None
    route_id = next(iter(route_ids))
    matching = [
        action
        for action in actions
        if isinstance(action, Mapping) and action.get("route_id") == route_id
    ]
    if len(matching) != 1 or not isinstance(matching[0].get("arguments"), Mapping):
        return None
    action = matching[0]
    historical = [
        {
            "dimension": list(_strings(issue.get("affected_dimensions"))),
            "code": issue.get("code"),
            "description": issue.get("description"),
            "affected_action_ids": list(_strings(issue.get("affected_action_ids"))),
            "affected_route_ids": list(_strings(issue.get("affected_route_ids"))),
        }
        for issue in issues
        if isinstance(issue, Mapping) and route_id in _strings(issue.get("affected_route_ids"))
    ]
    if not historical:
        return None
    return {
        "previous_plan_ref": deepcopy(dict(meta)),
        "route_id": route_id,
        "previous_action_id": action.get("action_id"),
        "tool_id": action.get("tool_id"),
        "effect": action.get("effect"),
        "previous_arguments": deepcopy(dict(action["arguments"])),
        "historical_review_issues": historical,
    }


def project_proposal_transition(
    previous: Mapping[str, object], planning_result: Mapping[str, object]
) -> dict[str, object] | None:
    """Bind by one frozen route; never infer a many-to-many Action correspondence."""
    route_id = previous.get("route_id")
    actions = planning_result.get("actions")
    meta = planning_result.get("meta")
    before_arguments = previous.get("previous_arguments")
    historical = previous.get("historical_review_issues")
    if (
        not isinstance(route_id, str)
        or not isinstance(actions, list)
        or not isinstance(meta, Mapping)
        or not isinstance(before_arguments, Mapping)
        or not isinstance(historical, list)
        or not historical
    ):
        return None
    matching = [
        action
        for action in actions
        if isinstance(action, Mapping) and action.get("route_id") == route_id
    ]
    if len(matching) != 1:
        return None
    current = matching[0]
    current_arguments = current.get("arguments")
    if (
        not isinstance(current_arguments, Mapping)
        or current.get("tool_id") != previous.get("tool_id")
        or current.get("effect") != previous.get("effect")
    ):
        return None
    return {
        "stage": "PROPOSAL_REVIEW_BEFORE_EXECUTION",
        "previous_plan_ref": deepcopy(previous["previous_plan_ref"]),
        "current_plan_ref": deepcopy(dict(meta)),
        "route_id": route_id,
        "previous_action_id": previous.get("previous_action_id"),
        "current_action_id": current.get("action_id"),
        "changed_arguments": _changed_values(before_arguments, current_arguments),
        "historical_review_issues": deepcopy(historical),
    }


def _changed_values(previous: object, current: object, path: str = "") -> list[dict[str, object]]:
    if isinstance(previous, Mapping) and isinstance(current, Mapping):
        changes: list[dict[str, object]] = []
        for key in sorted(previous.keys() | current.keys()):
            if not isinstance(key, str):
                return []
            nested = f"{path}/{key.replace('~', '~0').replace('/', '~1')}"
            if key not in previous:
                changes.append(
                    {
                        "path": nested,
                        "previous": {"present": False},
                        "current": {"present": True, "value": deepcopy(current[key])},
                    }
                )
            elif key not in current:
                changes.append(
                    {
                        "path": nested,
                        "previous": {"present": True, "value": deepcopy(previous[key])},
                        "current": {"present": False},
                    }
                )
            else:
                changes.extend(_changed_values(previous[key], current[key], nested))
        return changes
    if previous == current:
        return []
    return [
        {
            "path": path,
            "previous": {"present": True, "value": deepcopy(previous)},
            "current": {"present": True, "value": deepcopy(current)},
        }
    ]


def _strings(value: object) -> Sequence[str]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        return ()
    return value


__all__ = ["capture_reviewed_proposal", "project_proposal_transition"]
