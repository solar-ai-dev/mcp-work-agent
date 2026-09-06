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


class ConstraintProvenanceV1(TypedDict):
    source: ConstraintProvenanceSource
    start_offset: int
    end_offset: int


class ConstraintV1(TypedDict):
    kind: ConstraintKindValue
    field: str
    value: str | list[str]
    provenance: NotRequired[ConstraintProvenanceV1]


class AmbiguityV1(TypedDict):
    requires_confirmation: bool
    reason_codes: list[str]
    missing_fields: list[str]


class RequestGoalCandidateV1(TypedDict):
    goal: str
    completion_conditions: list[str]
    constraints: list[ConstraintV1]
    requested_effect_hints: list[ActionEffectValue]
    requested_resource_hints: list[str]
    analysis_requirement: Literal["NONE", "REQUIRED"]


class RequestIntentCandidateV1(RequestGoalCandidateV1):
    schema_version: Required[Literal[2]]
    ambiguity: AmbiguityV1


class RequestIntentV2(RequestIntentCandidateV1):
    meta: StateArtifactMetaV1
    repository_default: NotRequired[dict[str, object]]


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
