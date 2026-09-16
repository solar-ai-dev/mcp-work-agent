"""Merge atomic source and output decisions into the canonical responsibility artifact."""

from __future__ import annotations

import re
from typing import cast

from .contracts.output_responsibility_decision import (
    OutputResponsibilityCandidateV1,
    OutputResponsibilityDecisionCandidateV2,
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
    output_decisions: OutputResponsibilityDecisionCandidateV2,
    source_candidates: tuple[SourceDependencyCandidateV1, ...],
    output_candidates: tuple[OutputResponsibilityCandidateV1, ...],
    request_text: str | None = None,
) -> ResourceResponsibilitiesV1:
    """Merge validated decisions and preserve explicit direct-Resource ownership."""

    source_by_resource = {
        decision["resource_type"]: decision for decision in source_decisions["source_dependencies"]
    }
    output_by_resource = {
        decision["resource_type"]: decision
        for decision in output_decisions["output_responsibilities"]
    }
    source_information = {
        resource_type: list(decision["required_information"])
        for resource_type, decision in source_by_resource.items()
        if decision["dependency"] == "SOURCE_REQUIRED"
    }
    source_scopes = {
        resource_type: decision["target_scope"]
        for resource_type, decision in source_by_resource.items()
        if decision["dependency"] == "SOURCE_REQUIRED"
    }
    for resource_type, effect in output_by_resource.items():
        if effect["effect"] == "CREATE":
            source_information.pop(resource_type, None)
            source_scopes.pop(resource_type, None)
    source_information = _without_access_only_parents(
        source_information,
        request_text=request_text or "",
    )
    source_reads = [
        SourceResourceResponsibilityV1(
            resource_type=candidate["resource_type"],
            required_information=list(source_information[candidate["resource_type"]]),
            target_scope=source_scopes[candidate["resource_type"]],
        )
        for candidate in source_candidates
        if candidate["resource_type"] in source_information
    ]
    outputs = [
        OutputResourceResponsibilityV1(
            resource_type=candidate["resource_type"],
            effect=cast(
                WriteEffectValue,
                output_by_resource[candidate["resource_type"]]["effect"],
            ),
        )
        for candidate in output_candidates
        if candidate["resource_type"] in output_by_resource
    ]
    return ResourceResponsibilitiesV1(source_reads=source_reads, outputs=outputs)


def _without_access_only_parents(
    source_information: dict[str, list[str]],
    *,
    request_text: str,
) -> dict[str, list[str]]:
    normalized = request_text.casefold()
    retained = dict(source_information)
    if "TASK" in retained and not re.search(
        r"할\s*일\s*목록|태스크\s*목록|\btask\s+lists?\b", normalized
    ):
        retained.pop("TASK_LIST", None)
    if "CALENDAR_EVENT" in retained and not re.search(
        r"캘린더\s*(?:이름|목록|메타데이터)|\bcalendar\s+(?:name|list|metadata)\b",
        normalized,
    ):
        retained.pop("CALENDAR", None)
    return retained


__all__ = ["merge_resource_responsibilities"]
