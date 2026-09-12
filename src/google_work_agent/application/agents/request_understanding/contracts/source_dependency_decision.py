"""Owner-local contracts for bounded source dependency decisions."""

from __future__ import annotations

from typing import Literal, NotRequired, TypedDict

SourceDependencyValue = Literal["SOURCE_REQUIRED", "SOURCE_NOT_REQUIRED"]


class SourceDependencyCandidateV1(TypedDict):
    resource_type: str
    read_tool_ids: list[str]


class SourceDependencyDecisionV1(TypedDict):
    resource_type: str
    dependency: SourceDependencyValue
    required_information: NotRequired[list[str]]


class SourceDependencyDecisionCandidateV1(TypedDict):
    source_dependencies: list[SourceDependencyDecisionV1]


__all__ = [
    "SourceDependencyCandidateV1",
    "SourceDependencyDecisionCandidateV1",
    "SourceDependencyDecisionV1",
    "SourceDependencyValue",
]
