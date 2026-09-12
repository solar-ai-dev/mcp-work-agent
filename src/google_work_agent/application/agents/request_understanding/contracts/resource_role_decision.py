"""Owner-local contracts for bounded Resource role selection."""

from __future__ import annotations

from typing import Literal, NotRequired, TypedDict

from .request_intent import WriteEffectValue

ResourceRoleValue = Literal["NONE", "SOURCE", "OUTPUT", "SOURCE_AND_OUTPUT"]


class ResourceRoleCandidateV1(TypedDict):
    resource_type: str
    allowed_roles: list[ResourceRoleValue]
    read_tool_ids: list[str]
    allowed_output_effects: list[WriteEffectValue]


class ResourceRoleDecisionV1(TypedDict):
    resource_type: str
    role: ResourceRoleValue
    required_information: NotRequired[list[str]]
    effect: NotRequired[WriteEffectValue]


class ResourceRoleDecisionCandidateV1(TypedDict):
    resource_decisions: list[ResourceRoleDecisionV1]


__all__ = [
    "ResourceRoleCandidateV1",
    "ResourceRoleDecisionCandidateV1",
    "ResourceRoleDecisionV1",
    "ResourceRoleValue",
]
