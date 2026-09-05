from __future__ import annotations

from typing import Literal, NotRequired, Required, TypedDict

from google_work_agent.application.agents.state_artifact import StateArtifactMetaV1
from google_work_agent.application.agents.state_artifact import (
    StateArtifactRefV1 as StateArtifactRefV1,
)

ConstraintKindValue = Literal[
    "PERSON", "EMAIL", "DATE", "TIME", "RESOURCE", "SCOPE", "USER_REQUIREMENT"
]
ActionEffectValue = Literal["READ", "CREATE", "UPDATE", "SEND", "DELETE"]
ConstraintProvenanceSource = Literal["USER_REQUEST", "CONFIRMATION_RESPONSE"]


class ConstraintProvenanceV1(TypedDict):
    source: ConstraintProvenanceSource
    start_offset: int
    end_offset: int


class ConstraintV1(TypedDict):
    kind: ConstraintKindValue
    field: str
    value: str | list[str]
    provenance: NotRequired[ConstraintProvenanceV1]


class AmbiguityV1(TypedDict):
    requires_confirmation: bool
    reason_codes: list[str]
    missing_fields: list[str]


class RequestGoalCandidateV1(TypedDict):
    goal: str
    completion_conditions: list[str]
    constraints: list[ConstraintV1]
    requested_effect_hints: list[ActionEffectValue]
    requested_resource_hints: list[str]
    analysis_requirement: Literal["NONE", "REQUIRED"]


class RequestIntentCandidateV1(RequestGoalCandidateV1):
    schema_version: Required[Literal[2]]
    ambiguity: AmbiguityV1


class RequestIntentV2(RequestIntentCandidateV1):
    meta: StateArtifactMetaV1
