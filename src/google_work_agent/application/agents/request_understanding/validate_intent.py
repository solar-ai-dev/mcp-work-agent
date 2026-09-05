from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Literal, cast, overload

from google_work_agent.application.agents.request_understanding.contracts.request_intent import (
    AmbiguityV1,
    ConstraintKindValue,
    ConstraintProvenanceSource,
    ConstraintProvenanceV1,
    ConstraintV1,
    RequestIntentCandidateV1,
    RequestIntentV2,
)
from google_work_agent.ports.system.contracts.workflow_execution import SelectedResourceRef


class RequestUnderstandingValidationError(ValueError):
    """Raised when a Request Understanding artifact violates its owner contract."""


_CONSTRAINT_KINDS = {"PERSON", "EMAIL", "DATE", "TIME", "RESOURCE", "SCOPE", "USER_REQUIREMENT"}
_EFFECTS = {"READ", "CREATE", "UPDATE", "SEND", "DELETE"}
_PROVENANCE_SOURCES = {"USER_REQUEST", "CONFIRMATION_RESPONSE"}


@overload
def validate_intent(
    value: object,
    *,
    require_meta: Literal[True],
    provenance_sources: Mapping[ConstraintProvenanceSource, str] | None = None,
) -> RequestIntentV2: ...


@overload
def validate_intent(
    value: object,
    *,
    require_meta: Literal[False] = False,
    provenance_sources: Mapping[ConstraintProvenanceSource, str] | None = None,
) -> RequestIntentCandidateV1: ...


def validate_intent(
    value: object,
    *,
    require_meta: bool = False,
    provenance_sources: Mapping[ConstraintProvenanceSource, str] | None = None,
) -> RequestIntentCandidateV1 | RequestIntentV2:
    root = _mapping(value, "$")
    expected = {
        "schema_version",
        "goal",
        "completion_conditions",
        "constraints",
        "requested_effect_hints",
        "requested_resource_hints",
        "analysis_requirement",
        "ambiguity",
    }
    if require_meta:
        expected.add("meta")
    if set(root) != expected:
        raise RequestUnderstandingValidationError("RequestIntentV2 fields are invalid")
    if root.get("schema_version") != 2:
        raise RequestUnderstandingValidationError("$.schema_version must be 2")
    goal = _string(root, "goal", "$")
    completion_conditions = _string_list(
        root.get("completion_conditions"), "$.completion_conditions"
    )
    constraints = [
        _constraint(item, f"$.constraints[{index}]")
        for index, item in enumerate(_list(root.get("constraints"), "$.constraints"))
    ]
    if provenance_sources is not None:
        for index, constraint in enumerate(constraints):
            _validate_provenance_binding(
                constraint,
                f"$.constraints[{index}]",
                provenance_sources=provenance_sources,
            )
    effects = _string_list(root.get("requested_effect_hints"), "$.requested_effect_hints")
    if any(effect not in _EFFECTS for effect in effects):
        raise RequestUnderstandingValidationError(
            "$.requested_effect_hints contains an invalid effect"
        )
    resource_hints = _string_list(
        root.get("requested_resource_hints"), "$.requested_resource_hints"
    )
    analysis_requirement = root.get("analysis_requirement")
    if analysis_requirement not in {"NONE", "REQUIRED"}:
        raise RequestUnderstandingValidationError("$.analysis_requirement is invalid")
    ambiguity = _ambiguity(root.get("ambiguity"))
    candidate: RequestIntentCandidateV1 = {
        "schema_version": 2,
        "goal": goal,
        "completion_conditions": completion_conditions,
        "constraints": constraints,
        "requested_effect_hints": cast(
            list[Literal["READ", "CREATE", "UPDATE", "SEND", "DELETE"]], effects
        ),
        "requested_resource_hints": resource_hints,
        "analysis_requirement": cast(Literal["NONE", "REQUIRED"], analysis_requirement),
        "ambiguity": ambiguity,
    }
    if not require_meta:
        return candidate
    meta = _mapping(root.get("meta"), "$.meta")
    if set(meta) != {"artifact_id", "revision", "based_on"}:
        raise RequestUnderstandingValidationError("$.meta fields are invalid")
    artifact_id = _string(meta, "artifact_id", "$.meta")
    revision = meta.get("revision")
    based_on = meta.get("based_on")
    if not isinstance(revision, int) or revision < 1 or not isinstance(based_on, list):
        raise RequestUnderstandingValidationError("$.meta is invalid")
    return cast(
        RequestIntentV2,
        {
            **candidate,
            "meta": {"artifact_id": artifact_id, "revision": revision, "based_on": list(based_on)},
        },
    )


def _ambiguity(value: object) -> AmbiguityV1:
    root = _mapping(value, "$.ambiguity")
    if set(root) != {"requires_confirmation", "reason_codes", "missing_fields"}:
        raise RequestUnderstandingValidationError("$.ambiguity fields are invalid")
    requires_confirmation = root.get("requires_confirmation")
    if not isinstance(requires_confirmation, bool):
        raise RequestUnderstandingValidationError(
            "$.ambiguity.requires_confirmation must be boolean"
        )
    return {
        "requires_confirmation": requires_confirmation,
        "reason_codes": _string_list(root.get("reason_codes"), "$.ambiguity.reason_codes"),
        "missing_fields": _string_list(root.get("missing_fields"), "$.ambiguity.missing_fields"),
    }


def _constraint(value: object, path: str) -> ConstraintV1:
    root = _mapping(value, path)
    if not {"kind", "field", "value"} <= set(root) <= {
        "kind",
        "field",
        "value",
        "provenance",
    }:
        raise RequestUnderstandingValidationError(f"{path} fields are invalid")
    kind = root.get("kind")
    if kind not in _CONSTRAINT_KINDS:
        raise RequestUnderstandingValidationError(f"{path}.kind is invalid")
    field = _string(root, "field", path)
    raw_value = root.get("value")
    normalized_value: str | list[str] = (
        raw_value if isinstance(raw_value, str) else _string_list(raw_value, f"{path}.value")
    )
    constraint: ConstraintV1 = {
        "kind": cast(ConstraintKindValue, kind),
        "field": field,
        "value": normalized_value,
    }
    if "provenance" in root:
        constraint["provenance"] = _provenance(root.get("provenance"), f"{path}.provenance")
    return constraint


def materialize_validated_constraint_provenance(
    constraints: Sequence[ConstraintV1],
    *,
    user_request: str,
    confirmation_response_text: str | None,
) -> list[ConstraintV1]:
    """Bind identity constraints to exact current-Run source text."""
    sources: list[tuple[ConstraintProvenanceSource, str]] = [
        ("USER_REQUEST", user_request)
    ]
    if confirmation_response_text is not None:
        sources.insert(0, ("CONFIRMATION_RESPONSE", confirmation_response_text))
    materialized: list[ConstraintV1] = []
    for index, constraint in enumerate(constraints):
        copied = cast(ConstraintV1, dict(constraint))
        copied.pop("provenance", None)
        if not _is_repository_constraint(copied):
            materialized.append(copied)
            continue
        value = copied["value"]
        if not isinstance(value, str) or not is_fully_qualified_repository(value):
            raise RequestUnderstandingValidationError(
                f"$.constraints[{index}].value must be a fully-qualified repository"
            )
        for source, source_text in sources:
            start = source_text.find(value)
            if start < 0:
                continue
            copied["provenance"] = {
                "source": source,
                "start_offset": start,
                "end_offset": start + len(value),
            }
            materialized.append(copied)
            break
        else:
            raise RequestUnderstandingValidationError(
                f"$.constraints[{index}].value has no current-Run source binding"
            )
    return materialized


def repository_authority_requires_confirmation(
    constraints: Sequence[ConstraintV1],
    *,
    user_request: str,
    confirmation_response_text: str | None,
    selected_resources: Sequence[SelectedResourceRef],
) -> bool:
    repository_constraints = [item for item in constraints if _is_repository_constraint(item)]
    try:
        materialized = materialize_validated_constraint_provenance(
            repository_constraints,
            user_request=user_request,
            confirmation_response_text=confirmation_response_text,
        )
        _repository_authority(materialized, selected_resources=selected_resources)
    except RequestUnderstandingValidationError:
        return True
    return False


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
    return _repository_authority(
        request_intent["constraints"],
        selected_resources=selected_resources,
    )


def _repository_authority(
    constraints: Sequence[ConstraintV1],
    *,
    selected_resources: Sequence[SelectedResourceRef],
) -> str | None:
    repository_constraints = [item for item in constraints if _is_repository_constraint(item)]
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
    parts = value.split("/")
    return (
        value == value.strip()
        and len(parts) == 2
        and bool(parts[0])
        and bool(parts[1])
    )


def _is_repository_constraint(constraint: ConstraintV1) -> bool:
    return constraint["kind"] == "RESOURCE" and constraint["field"] == "repository"


def _provenance(value: object, path: str) -> ConstraintProvenanceV1:
    root = _mapping(value, path)
    if set(root) != {"source", "start_offset", "end_offset"}:
        raise RequestUnderstandingValidationError(f"{path} fields are invalid")
    source = root.get("source")
    start_offset = root.get("start_offset")
    end_offset = root.get("end_offset")
    if source not in _PROVENANCE_SOURCES:
        raise RequestUnderstandingValidationError(f"{path}.source is invalid")
    if type(start_offset) is not int or type(end_offset) is not int:
        raise RequestUnderstandingValidationError(f"{path} offsets must be integers")
    if start_offset < 0 or end_offset <= start_offset:
        raise RequestUnderstandingValidationError(f"{path} offsets are invalid")
    return {
        "source": cast(ConstraintProvenanceSource, source),
        "start_offset": start_offset,
        "end_offset": end_offset,
    }


def _validate_provenance_binding(
    constraint: ConstraintV1,
    path: str,
    *,
    provenance_sources: Mapping[ConstraintProvenanceSource, str],
) -> None:
    provenance = constraint.get("provenance")
    if _is_repository_constraint(constraint) and provenance is None:
        raise RequestUnderstandingValidationError(f"{path}.provenance is required")
    if provenance is None:
        return
    value = constraint["value"]
    if not isinstance(value, str):
        raise RequestUnderstandingValidationError(
            f"{path}.provenance requires a scalar string value"
        )
    source_text = provenance_sources.get(provenance["source"])
    start_offset = provenance["start_offset"]
    end_offset = provenance["end_offset"]
    if source_text is None or end_offset > len(source_text):
        raise RequestUnderstandingValidationError(f"{path}.provenance source is unavailable")
    if source_text[start_offset:end_offset] != value:
        raise RequestUnderstandingValidationError(f"{path}.provenance does not match source")
    if _is_repository_constraint(constraint) and not is_fully_qualified_repository(value):
        raise RequestUnderstandingValidationError(
            f"{path}.value must be a fully-qualified repository"
        )


def _mapping(value: object, path: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise RequestUnderstandingValidationError(f"{path} must be an object")
    return cast(Mapping[str, object], value)


def _list(value: object, path: str) -> list[object]:
    if not isinstance(value, list):
        raise RequestUnderstandingValidationError(f"{path} must be a list")
    return value


def _string(root: Mapping[str, object], key: str, path: str) -> str:
    value = root.get(key)
    if not isinstance(value, str):
        raise RequestUnderstandingValidationError(f"{path}.{key} must be a string")
    return value


def _string_list(value: object, path: str) -> list[str]:
    items = _list(value, path)
    if any(not isinstance(item, str) for item in items):
        raise RequestUnderstandingValidationError(f"{path} must contain strings")
    return cast(list[str], items)
