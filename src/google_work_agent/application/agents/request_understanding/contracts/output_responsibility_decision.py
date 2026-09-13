"""Owner-local contracts for bounded output responsibility decisions."""

from __future__ import annotations

from typing import TypedDict

from .request_intent import WriteEffectValue


class OutputResponsibilityCandidateV1(TypedDict):
    resource_type: str
    allowed_output_effects: list[WriteEffectValue]


class OutputResponsibilityDecisionV2(TypedDict):
    resource_type: str
    effect: WriteEffectValue


class OutputResponsibilityDecisionCandidateV2(TypedDict):
    output_responsibilities: list[OutputResponsibilityDecisionV2]


__all__ = [
    "OutputResponsibilityCandidateV1",
    "OutputResponsibilityDecisionCandidateV2",
    "OutputResponsibilityDecisionV2",
]
