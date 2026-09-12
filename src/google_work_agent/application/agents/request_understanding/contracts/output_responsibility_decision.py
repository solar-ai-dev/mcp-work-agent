"""Owner-local contracts for bounded output responsibility decisions."""

from __future__ import annotations

from typing import Literal, TypedDict

from .request_intent import WriteEffectValue

OutputResponsibilityValue = Literal["NONE", "CREATE", "UPDATE", "SEND", "DELETE"]


class OutputResponsibilityCandidateV1(TypedDict):
    resource_type: str
    allowed_output_effects: list[WriteEffectValue]


class OutputResponsibilityDecisionV1(TypedDict):
    resource_type: str
    effect: OutputResponsibilityValue


class OutputResponsibilityDecisionCandidateV1(TypedDict):
    output_responsibilities: list[OutputResponsibilityDecisionV1]


__all__ = [
    "OutputResponsibilityCandidateV1",
    "OutputResponsibilityDecisionCandidateV1",
    "OutputResponsibilityDecisionV1",
    "OutputResponsibilityValue",
]
