from __future__ import annotations

from typing import Literal, TypedDict

from .request_intent import WriteEffectValue

EffectProhibitionValue = Literal["FORBIDDEN", "NOT_FORBIDDEN"]


class EffectProhibitionCandidateV1(TypedDict):
    effect: WriteEffectValue


class EffectProhibitionDecisionV1(TypedDict):
    effect: WriteEffectValue
    prohibition: EffectProhibitionValue


class EffectProhibitionDecisionCandidateV1(TypedDict):
    effect_prohibitions: list[EffectProhibitionDecisionV1]


__all__ = [
    "EffectProhibitionCandidateV1",
    "EffectProhibitionDecisionCandidateV1",
    "EffectProhibitionDecisionV1",
    "EffectProhibitionValue",
]
