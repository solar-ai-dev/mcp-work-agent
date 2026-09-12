"""Owner-local contract for one bounded collection coverage decision."""

from __future__ import annotations

from typing import Literal, TypedDict

from .request_intent import ConstraintV1


class CoverageRequirementDecisionV1(TypedDict):
    coverage_requirement: list[Literal["EXHAUSTIVE"]]


def normalize_coverage_requirement_constraint(
    decision: CoverageRequirementDecisionV1,
) -> ConstraintV1 | None:
    if not decision["coverage_requirement"]:
        return None
    return {
        "kind": "SCOPE",
        "field": "coverage_requirement",
        "value": "EXHAUSTIVE",
    }


__all__ = [
    "CoverageRequirementDecisionV1",
    "normalize_coverage_requirement_constraint",
]
