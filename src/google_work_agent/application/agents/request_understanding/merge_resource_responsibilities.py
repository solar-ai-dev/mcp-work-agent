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
    output_items = list(output_decisions["output_responsibilities"])
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
    source_work_unit_ids = {
        resource_type: list(decision["work_unit_ids"])
        for resource_type, decision in source_by_resource.items()
        if decision["dependency"] == "SOURCE_REQUIRED"
    }
    source_information = _without_access_only_parents(
        source_information,
        request_text=request_text or "",
    )
    source_reads = [
        SourceResourceResponsibilityV1(
            resource_type=candidate["resource_type"],
            required_information=list(source_information[candidate["resource_type"]]),
            target_scope=source_scopes[candidate["resource_type"]],
            work_unit_ids=source_work_unit_ids[candidate["resource_type"]],
        )
        for candidate in source_candidates
        if candidate["resource_type"] in source_information
    ]
    allowed_output_resources = {candidate["resource_type"] for candidate in output_candidates}
    outputs = [
        OutputResourceResponsibilityV1(
            resource_type=decision["resource_type"],
            effect=cast(WriteEffectValue, decision["effect"]),
            work_unit_ids=list(decision["work_unit_ids"]),
        )
        for decision in output_items
        if decision["resource_type"] in allowed_output_resources
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
