from __future__ import annotations

import re
from collections.abc import Sequence
from typing import Literal, NotRequired, Required, TypedDict

from google_work_agent.application.agents.state_artifact import StateArtifactMetaV1
from google_work_agent.application.agents.state_artifact import (
    StateArtifactRefV1 as StateArtifactRefV1,
)
from google_work_agent.ports.system.contracts.workflow_execution import SelectedResourceRef
from google_work_agent.ports.system.settings_port import GitHubRepositoryDefaultV1


class RequestUnderstandingValidationError(ValueError):
    """Raised when a Request Understanding artifact violates its owner contract."""

ConstraintKindValue = Literal[
    "PERSON", "EMAIL", "DATE", "TIME", "RESOURCE", "SCOPE", "USER_REQUIREMENT"
]
ActionEffectValue = Literal["READ", "CREATE", "UPDATE", "SEND", "DELETE"]
ConstraintProvenanceSource = Literal["USER_REQUEST", "CONFIRMATION_RESPONSE"]
SOURCE_STATUS_VALUES_BY_RESOURCE: dict[str, frozenset[str]] = {
    "GMAIL_THREAD": frozenset({"ANY", "DRAFT", "SENT"}),
    "GMAIL_MESSAGE": frozenset({"ANY", "DRAFT", "SENT"}),
    "GMAIL_DRAFT": frozenset({"ANY", "DRAFT"}),
    "TASK": frozenset({"ANY", "INCOMPLETE", "COMPLETED"}),
    "CALENDAR": frozenset({"ANY", "CANCELLED", "CONFIRMED", "TENTATIVE"}),
    "CALENDAR_EVENT": frozenset({"ANY", "CANCELLED", "CONFIRMED", "TENTATIVE"}),
    "GITHUB_ISSUE": frozenset({"ANY", "OPEN", "CLOSED"}),
}
WRITE_EFFECT_RESOURCE_TYPES: dict[str, frozenset[str]] = {
    "CREATE": frozenset({"GMAIL_DRAFT", "TASK", "CALENDAR_EVENT", "GITHUB_ISSUE"}),
    "UPDATE": frozenset({"GMAIL_DRAFT", "TASK", "CALENDAR_EVENT", "GITHUB_ISSUE"}),
    "SEND": frozenset({"GMAIL_MESSAGE"}),
    "DELETE": frozenset({"TASK", "CALENDAR_EVENT"}),
}


class ConstraintProvenanceV1(TypedDict):
    source: ConstraintProvenanceSource
    start_offset: int
    end_offset: int
    source_text: NotRequired[str]


class ConstraintV1(TypedDict):
    kind: ConstraintKindValue
    field: str
    value: str | list[str]
    provenance: NotRequired[ConstraintProvenanceV1]
    source_resource_type: NotRequired[str]


class AmbiguityV1(TypedDict):
    requires_confirmation: bool
    reason_codes: list[str]
    missing_fields: list[str]


class SourceResourceResponsibilityV1(TypedDict):
    resource_type: str
    required_information: list[str]


class OutputResourceResponsibilityV1(TypedDict):
    resource_type: str
    effect: Literal["CREATE", "UPDATE", "SEND", "DELETE"]


class ResourceResponsibilitiesV1(TypedDict):
    source_reads: list[SourceResourceResponsibilityV1]
    outputs: list[OutputResourceResponsibilityV1]


class RequestGoalCandidateV1(TypedDict):
    goal: str
    completion_conditions: list[str]
    constraints: list[ConstraintV1]
    requested_effect_hints: list[ActionEffectValue]
    requested_resource_hints: list[str]
    resource_responsibilities: NotRequired[ResourceResponsibilitiesV1]
    analysis_requirement: Literal["NONE", "REQUIRED"]


class RequestIntentCandidateV1(RequestGoalCandidateV1):
    schema_version: Required[Literal[2]]
    ambiguity: AmbiguityV1


class RequestIntentV2(RequestIntentCandidateV1):
    meta: StateArtifactMetaV1
    repository_default: NotRequired[dict[str, object]]


def is_source_status_constraint(constraint: ConstraintV1) -> bool:
    return constraint["kind"] == "SCOPE" and constraint["field"] == "status"


def validated_repository_authority(
    request_intent: RequestIntentV2,
    *,
    selected_resources: Sequence[SelectedResourceRef],
) -> str | None:
    """Resolve the sole repository value already authorized for this Run."""
    if request_intent["ambiguity"]["requires_confirmation"]:
        raise RequestUnderstandingValidationError(
            "repository authority cannot be consumed from an ambiguous intent"
        )
    repository = repository_from_constraints(
        request_intent["constraints"],
        selected_resources=selected_resources,
    )
    if repository is not None:
        return repository
    raw_default = request_intent.get("repository_default")
    return (
        None
        if raw_default is None
        else GitHubRepositoryDefaultV1.from_payload(raw_default).repository
    )


def repository_from_constraints(
    constraints: Sequence[ConstraintV1],
    *,
    selected_resources: Sequence[SelectedResourceRef],
) -> str | None:
    repository_constraints = [item for item in constraints if is_repository_constraint(item)]
    explicit_repositories: set[str] = set()
    for constraint in repository_constraints:
        value = constraint["value"]
        if (
            not isinstance(value, str)
            or not is_fully_qualified_repository(value)
            or constraint.get("provenance") is None
        ):
            raise RequestUnderstandingValidationError(
                "repository authority requires validated provenance"
            )
        explicit_repositories.add(value)
    if len(explicit_repositories) != len(repository_constraints) or len(explicit_repositories) > 1:
        raise RequestUnderstandingValidationError("repository authority is ambiguous")

    selected_repositories: set[str] = set()
    for resource in selected_resources:
        if resource.connector_id != "github" or resource.resource_type != "github_issue":
            continue
        parent = resource.parent_resource_id
        if parent is None or not is_fully_qualified_repository(parent):
            raise RequestUnderstandingValidationError(
                "selected GitHub Issue repository authority is invalid"
            )
        prefix, separator, issue_number = resource.resource_id.rpartition("#")
        if (
            prefix != parent
            or separator != "#"
            or not issue_number.isdigit()
            or int(issue_number) < 1
        ):
            raise RequestUnderstandingValidationError("selected GitHub Issue identity is invalid")
        selected_repositories.add(parent)
    if len(selected_repositories) > 1:
        raise RequestUnderstandingValidationError("selected repository authority is ambiguous")

    repositories = explicit_repositories | selected_repositories
    if len(repositories) > 1:
        raise RequestUnderstandingValidationError("repository authorities conflict")
    return next(iter(repositories), None)


def is_fully_qualified_repository(value: str) -> bool:
    return (
        len(value) <= 200
        and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9-]*/[A-Za-z0-9_.-]+", value) is not None
        and value.split("/")[-1] not in {".", ".."}
    )


def is_repository_constraint(constraint: ConstraintV1) -> bool:
    return constraint["kind"] == "RESOURCE" and constraint["field"] == "repository"


def validated_gmail_draft_anchor(request_intent: RequestIntentV2) -> str | None:
    """Return one explicit, source-proven Gmail Draft identifier for bounded lookup."""
    if request_intent["ambiguity"]["requires_confirmation"]:
        raise RequestUnderstandingValidationError(
            "Gmail Draft authority cannot be consumed from an ambiguous intent"
        )
    anchors: set[str] = set()
    for constraint in request_intent["constraints"]:
        if not is_gmail_draft_constraint(constraint):
            continue
        value = constraint["value"]
        if (
            not isinstance(value, str)
            or not is_valid_gmail_draft_id(value)
            or constraint.get("provenance") is None
        ):
            raise RequestUnderstandingValidationError(
                "Gmail Draft anchor requires a source-proven opaque identifier"
            )
        anchors.add(value)
    if len(anchors) > 1:
        raise RequestUnderstandingValidationError("Gmail Draft anchor is ambiguous")
    return next(iter(anchors), None)


def is_gmail_draft_constraint(constraint: ConstraintV1) -> bool:
    return constraint["kind"] == "RESOURCE" and constraint["field"] == "draft_id"


def is_valid_gmail_draft_id(value: str) -> bool:
    return re.fullmatch(r"[A-Za-z0-9_-]{3,256}", value) is not None
