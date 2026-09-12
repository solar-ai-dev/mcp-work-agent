"""Merge atomic source and output decisions into the canonical responsibility artifact."""

from __future__ import annotations

from typing import cast

from .contracts.output_responsibility_decision import (
    OutputResponsibilityCandidateV1,
    OutputResponsibilityDecisionCandidateV1,
)
from .contracts.request_intent import (
    OutputResourceResponsibilityV1,
    ResourceResponsibilitiesV1,
    SourceResourceResponsibilityV1,
    WriteEffectValue,
)
from .contracts.source_dependency_decision import (
    SourceDependencyCandidateV1,
    SourceDependencyDecisionCandidateV1,
)


def merge_resource_responsibilities(
    *,
    source_decisions: SourceDependencyDecisionCandidateV1,
    output_decisions: OutputResponsibilityDecisionCandidateV1,
    source_candidates: tuple[SourceDependencyCandidateV1, ...],
    output_candidates: tuple[OutputResponsibilityCandidateV1, ...],
) -> ResourceResponsibilitiesV1:
    """Project validated decisions without reclassifying or repairing their meaning."""

    source_by_resource = {
        decision["resource_type"]: decision for decision in source_decisions["source_dependencies"]
    }
    source_reads = [
        SourceResourceResponsibilityV1(
            resource_type=candidate["resource_type"],
            required_information=list(
                source_by_resource[candidate["resource_type"]]["required_information"]
            ),
        )
        for candidate in source_candidates
        if source_by_resource[candidate["resource_type"]]["dependency"] == "SOURCE_REQUIRED"
    ]
    outputs = project_output_responsibilities(
        output_decisions=output_decisions,
        output_candidates=output_candidates,
    )
    return ResourceResponsibilitiesV1(source_reads=source_reads, outputs=outputs)


def project_output_responsibilities(
    *,
    output_decisions: OutputResponsibilityDecisionCandidateV1,
    output_candidates: tuple[OutputResponsibilityCandidateV1, ...],
) -> list[OutputResourceResponsibilityV1]:
    """Project validated output decisions into the canonical bounded shape."""

    output_by_resource = {
        decision["resource_type"]: decision
        for decision in output_decisions["output_responsibilities"]
    }
    return [
        OutputResourceResponsibilityV1(
            resource_type=candidate["resource_type"],
            effect=cast(
                WriteEffectValue,
                output_by_resource[candidate["resource_type"]]["effect"],
            ),
        )
        for candidate in output_candidates
        if output_by_resource[candidate["resource_type"]]["effect"] != "NONE"
    ]


__all__ = ["merge_resource_responsibilities", "project_output_responsibilities"]
