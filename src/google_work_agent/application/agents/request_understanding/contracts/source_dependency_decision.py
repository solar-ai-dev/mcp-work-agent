"""Owner-local contracts for bounded source dependency decisions."""

from __future__ import annotations

from typing import Literal, NotRequired, TypedDict

from .request_intent import TargetScopeValue

SourceDependencyValue = Literal["SOURCE_REQUIRED", "SOURCE_NOT_REQUIRED"]


class SourceDependencyCandidateV1(TypedDict):
    resource_type: str
    read_tool_ids: list[str]
    owned_fact_kinds: list[str]


class SourceDependencyDecisionV1(TypedDict):
    resource_type: str
    dependency: SourceDependencyValue
    required_information: NotRequired[list[str]]
    target_scope: NotRequired[TargetScopeValue]
    work_unit_ids: NotRequired[list[str]]


class SourceDependencyDecisionCandidateV1(TypedDict):
    source_dependencies: list[SourceDependencyDecisionV1]


def collapse_gmail_source_types(resource_types: tuple[str, ...]) -> tuple[str, ...]:
    """Use the Thread READ when Thread and Message describe one Gmail source."""
    unique = tuple(dict.fromkeys(resource_types))
    if {"GMAIL_THREAD", "GMAIL_MESSAGE"}.issubset(unique):
        return tuple(item for item in unique if item != "GMAIL_MESSAGE")
    return unique


def collapse_gmail_source_work_bindings(
    bindings: tuple[tuple[str, tuple[str, ...]], ...],
) -> tuple[tuple[str, tuple[str, ...]], ...]:
    ordered_resources = collapse_gmail_source_types(tuple(item[0] for item in bindings))
    by_resource: dict[str, list[str]] = {}
    for resource_type, unit_ids in bindings:
        effective_resource = (
            "GMAIL_THREAD"
            if resource_type in {"GMAIL_THREAD", "GMAIL_MESSAGE"}
            and "GMAIL_THREAD" in ordered_resources
            else resource_type
        )
        refs = by_resource.setdefault(effective_resource, [])
        refs.extend(unit_id for unit_id in unit_ids if unit_id not in refs)
    return tuple(
        (resource_type, tuple(by_resource[resource_type]))
        for resource_type in ordered_resources
    )


def selected_source_work_bindings(
    bindings: tuple[tuple[str, tuple[str, ...]], ...],
    selected_types: tuple[str, ...],
) -> tuple[tuple[str, tuple[str, ...]], ...]:
    """Retain Message work bindings when its selected Thread supplies the READ."""
    if "GMAIL_THREAD" in selected_types and "GMAIL_MESSAGE" not in selected_types:
        return collapse_gmail_source_work_bindings((*bindings, ("GMAIL_THREAD", ())))
    return bindings


__all__ = [
    "SourceDependencyCandidateV1",
    "SourceDependencyDecisionCandidateV1",
    "SourceDependencyDecisionV1",
    "SourceDependencyValue",
    "collapse_gmail_source_types",
    "collapse_gmail_source_work_bindings",
    "selected_source_work_bindings",
]
