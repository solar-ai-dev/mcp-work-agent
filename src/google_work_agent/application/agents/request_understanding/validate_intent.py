from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import asdict
from typing import Literal, cast, overload

from google_work_agent.application.agents.request_understanding.contracts.request_intent import (
    SOURCE_STATUS_VALUES_BY_RESOURCE,
    WRITE_EFFECT_RESOURCE_TYPES,
    AmbiguityV1,
    ConstraintKindValue,
    ConstraintProvenanceSource,
    ConstraintProvenanceV1,
    ConstraintV1,
    EffectProhibitionV1,
    RequestIntentCandidateV1,
    RequestIntentV3,
    RequestUnderstandingValidationError,
    ResourceResponsibilitiesV1,
    is_fully_qualified_repository,
    is_gmail_draft_constraint,
    is_repository_constraint,
    is_source_status_constraint,
    is_valid_gmail_draft_id,
    repository_from_constraints,
)
from google_work_agent.application.agents.request_understanding.contracts.work_unit_binding import (
    validate_requested_work_definition,
    validate_work_unit_refs,
)
from google_work_agent.ports.system.contracts.workflow_execution import SelectedResourceRef
from google_work_agent.ports.system.settings_port import GitHubRepositoryDefaultV1

_CONSTRAINT_KINDS = {"PERSON", "EMAIL", "DATE", "TIME", "RESOURCE", "SCOPE", "USER_REQUIREMENT"}
_EFFECTS = {"READ", "CREATE", "UPDATE", "SEND", "DELETE"}
_PROVENANCE_SOURCES = {"USER_REQUEST", "CONFIRMATION_RESPONSE"}
_SOURCE_LITERAL_FIELDS = frozenset(
    {
        "search_terms",
        "subject",
        "search_criteria_subject",
        "sender",
        "sender_email",
        "from",
        "search_criteria_sender",
        "recipient",
        "recipient_email",
        "to",
        "search_criteria_recipient",
        "person",
    }
)


@overload
def validate_intent(
    value: object,
    *,
    require_meta: Literal[True],
    provenance_sources: Mapping[ConstraintProvenanceSource, str] | None = None,
) -> RequestIntentV3: ...


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
) -> RequestIntentCandidateV1 | RequestIntentV3:
    root = _mapping(value, "$")
    expected = {
        "schema_version",
        "goal",
        "completion_conditions",
        "constraints",
        "requested_effect_hints",
        "requested_resource_hints",
        "analysis_requirement",
        "effect_prohibitions",
        "requested_work",
        "ambiguity",
    }
    if "resource_responsibilities" in root:
        expected.add("resource_responsibilities")
    if require_meta:
        expected.add("meta")
        if "repository_default" in root:
            expected.add("repository_default")
    if set(root) != expected:
        raise RequestUnderstandingValidationError("RequestIntentV3 fields are invalid")
    if root.get("schema_version") != 3:
        raise RequestUnderstandingValidationError("$.schema_version must be 3")
    if provenance_sources is None or "USER_REQUEST" not in provenance_sources:
        raise RequestUnderstandingValidationError(
            "RequestIntentV3 validation requires current user request provenance"
        )
    requested_work = validate_requested_work_definition(
        root.get("requested_work"),
        user_request=provenance_sources["USER_REQUEST"],
    )
    unit_ids = [item["unit_id"] for item in requested_work["work_units"]]
    goal = _string(root, "goal", "$")
    completion_conditions = _string_list(
        root.get("completion_conditions"), "$.completion_conditions"
    )
    constraints = [
        _constraint(item, f"$.constraints[{index}]", known_unit_ids=unit_ids)
        for index, item in enumerate(_list(root.get("constraints"), "$.constraints"))
    ]
    effects = _string_list(root.get("requested_effect_hints"), "$.requested_effect_hints")
    if any(effect not in _EFFECTS for effect in effects):
        raise RequestUnderstandingValidationError(
            "$.requested_effect_hints contains an invalid effect"
        )
    resource_hints = _string_list(
        root.get("requested_resource_hints"), "$.requested_resource_hints"
    )
    responsibilities = validate_resource_responsibilities(
        root.get("resource_responsibilities"),
        effects=effects,
        resource_hints=resource_hints,
        constraints=constraints,
        known_unit_ids=unit_ids,
        required=requires_resource_responsibilities(
            effects=effects,
            resource_hints=resource_hints,
        ),
    )
    if provenance_sources is not None:
        for index, constraint in enumerate(constraints):
            _validate_provenance_binding(
                constraint,
                f"$.constraints[{index}]",
                provenance_sources=provenance_sources,
                effects=effects,
                resource_hints=resource_hints,
            )
    analysis_requirement = root.get("analysis_requirement")
    if analysis_requirement not in {"NONE", "REQUIRED"}:
        raise RequestUnderstandingValidationError("$.analysis_requirement is invalid")
    ambiguity = _ambiguity(root.get("ambiguity"))
    effect_prohibitions = _effect_prohibitions(
        root.get("effect_prohibitions"),
        known_unit_ids=unit_ids,
    )
    candidate: RequestIntentCandidateV1 = {
        "schema_version": 3,
        "goal": goal,
        "completion_conditions": completion_conditions,
        "constraints": constraints,
        "requested_effect_hints": cast(
            list[Literal["READ", "CREATE", "UPDATE", "SEND", "DELETE"]], effects
        ),
        "requested_resource_hints": resource_hints,
        "analysis_requirement": cast(Literal["NONE", "REQUIRED"], analysis_requirement),
        "effect_prohibitions": effect_prohibitions,
        "requested_work": requested_work,
        "ambiguity": ambiguity,
    }
    if responsibilities is not None:
        candidate["resource_responsibilities"] = responsibilities
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
        RequestIntentV3,
        {
            **candidate,
            "meta": {"artifact_id": artifact_id, "revision": revision, "based_on": list(based_on)},
            **(
                {
                    "repository_default": asdict(
                        GitHubRepositoryDefaultV1.from_payload(root["repository_default"])
                    )
                }
                if "repository_default" in root
                else {}
            ),
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


def _constraint(
    value: object,
    path: str,
    *,
    known_unit_ids: Sequence[str],
) -> ConstraintV1:
    root = _mapping(value, path)
    if (
        not {"kind", "field", "value", "work_unit_ids"}
        <= set(root)
        <= {
            "kind",
            "field",
            "value",
            "provenance",
            "source_resource_type",
            "work_unit_ids",
        }
    ):
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
        "work_unit_ids": validate_work_unit_refs(
            root.get("work_unit_ids"),
            known_unit_ids=known_unit_ids,
            path=f"{path}.work_unit_ids",
        ),
    }
    if "provenance" in root:
        constraint["provenance"] = _provenance(root.get("provenance"), f"{path}.provenance")
    if "source_resource_type" in root:
        constraint["source_resource_type"] = _string(root, "source_resource_type", path)
    if not is_source_status_constraint(constraint) and "source_resource_type" in constraint:
        raise RequestUnderstandingValidationError(
            f"{path}.source_resource_type is only valid for a source status"
        )
    return constraint


def materialize_validated_constraint_provenance(
    constraints: Sequence[ConstraintV1],
    *,
    user_request: str,
    confirmation_response_text: str | None,
) -> list[ConstraintV1]:
    """Bind source-owned literal, identity, and status constraints to current-Run text."""
    sources: list[tuple[ConstraintProvenanceSource, str]] = [("USER_REQUEST", user_request)]
    if confirmation_response_text is not None:
        sources.insert(0, ("CONFIRMATION_RESPONSE", confirmation_response_text))
    materialized: list[ConstraintV1] = []
    for index, constraint in enumerate(constraints):
        copied = cast(ConstraintV1, dict(constraint))
        supplied_provenance = copied.pop("provenance", None)
        if is_source_status_constraint(copied):
            if supplied_provenance is None or not isinstance(
                supplied_provenance.get("source_text"), str
            ):
                raise RequestUnderstandingValidationError(
                    f"$.constraints[{index}].provenance.source_text is required"
                )
            source = supplied_provenance["source"]
            source_text = supplied_provenance["source_text"]
            source_value = dict(sources).get(source)
            start = -1 if source_value is None else source_value.find(source_text)
            if start < 0:
                raise RequestUnderstandingValidationError(
                    f"$.constraints[{index}].provenance has no current-Run source binding"
                )
            copied["provenance"] = {
                "source": source,
                "start_offset": start,
                "end_offset": start + len(source_text),
                "source_text": source_text,
            }
            materialized.append(copied)
            continue
        is_repository = is_repository_constraint(copied)
        is_gmail_draft = is_gmail_draft_constraint(copied)
        if not is_repository and not is_gmail_draft:
            if copied["field"] not in _SOURCE_LITERAL_FIELDS:
                materialized.append(copied)
                continue
            values = copied["value"]
            literal_values = [values] if isinstance(values, str) else values
            for literal_value in literal_values:
                literal = cast(ConstraintV1, {**copied, "value": literal_value})
                for source, source_text in sources:
                    start = source_text.find(literal_value)
                    if start < 0:
                        continue
                    literal["provenance"] = {
                        "source": source,
                        "start_offset": start,
                        "end_offset": start + len(literal_value),
                    }
                    break
                materialized.append(literal)
            continue
        identity_value = copied["value"]
        if not isinstance(identity_value, str):
            raise RequestUnderstandingValidationError(
                f"$.constraints[{index}].value must be a scalar identity"
            )
        if is_repository and not is_fully_qualified_repository(identity_value):
            raise RequestUnderstandingValidationError(
                f"$.constraints[{index}].value must be a fully-qualified repository"
            )
        if is_gmail_draft and not is_valid_gmail_draft_id(identity_value):
            raise RequestUnderstandingValidationError(
                f"$.constraints[{index}].value must be a valid Gmail Draft identifier"
            )
        for source, source_text in sources:
            start = source_text.find(identity_value)
            if start < 0:
                continue
            copied["provenance"] = {
                "source": source,
                "start_offset": start,
                "end_offset": start + len(identity_value),
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
    repository_required: bool = False,
    repository_default: GitHubRepositoryDefaultV1 | None = None,
) -> bool:
    if not repository_required:
        return False
    repository_constraints = [item for item in constraints if is_repository_constraint(item)]
    try:
        materialized = materialize_validated_constraint_provenance(
            repository_constraints,
            user_request=user_request,
            confirmation_response_text=confirmation_response_text,
        )
        repository = repository_from_constraints(
            materialized, selected_resources=selected_resources,
        )
    except RequestUnderstandingValidationError:
        return True
    return repository_required and repository is None and repository_default is None




def _provenance(value: object, path: str) -> ConstraintProvenanceV1:
    root = _mapping(value, path)
    if not {"source", "start_offset", "end_offset"} <= set(root) <= {
        "source",
        "start_offset",
        "end_offset",
        "source_text",
    }:
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
    result: ConstraintProvenanceV1 = {
        "source": cast(ConstraintProvenanceSource, source),
        "start_offset": start_offset,
        "end_offset": end_offset,
    }
    if "source_text" in root:
        source_text = root["source_text"]
        if not isinstance(source_text, str) or not source_text.strip():
            raise RequestUnderstandingValidationError(f"{path}.source_text must be non-empty")
        result["source_text"] = source_text
    return result


def _validate_provenance_binding(
    constraint: ConstraintV1,
    path: str,
    *,
    provenance_sources: Mapping[ConstraintProvenanceSource, str],
    effects: Sequence[str],
    resource_hints: Sequence[str],
) -> None:
    provenance = constraint.get("provenance")
    is_source_status = is_source_status_constraint(constraint)
    requires_provenance = (
        is_repository_constraint(constraint)
        or is_gmail_draft_constraint(constraint)
        or is_source_status
    )
    if requires_provenance and provenance is None:
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
    bound_text = provenance.get("source_text", value)
    if source_text[start_offset:end_offset] != bound_text:
        raise RequestUnderstandingValidationError(f"{path}.provenance does not match source")
    if is_source_status:
        resource_type = constraint.get("source_resource_type")
        if not isinstance(resource_type, str):
            raise RequestUnderstandingValidationError(
                f"{path}.source_resource_type is required"
            )
        if resource_type not in resource_hints:
            raise RequestUnderstandingValidationError(
                f"{path}.source_resource_type is not a requested resource"
            )
        if "READ" not in effects:
            raise RequestUnderstandingValidationError(f"{path} requires a READ effect")
        if value not in SOURCE_STATUS_VALUES_BY_RESOURCE.get(resource_type, frozenset()):
            raise RequestUnderstandingValidationError(
                f"{path}.value is invalid for its source resource"
            )
        if provenance.get("source_text") is None:
            raise RequestUnderstandingValidationError(
                f"{path}.provenance.source_text is required"
            )
    elif provenance.get("source_text") is not None:
        raise RequestUnderstandingValidationError(
            f"{path}.provenance.source_text is only valid for normalized source status"
        )
    if is_repository_constraint(constraint) and not is_fully_qualified_repository(value):
        raise RequestUnderstandingValidationError(
            f"{path}.value must be a fully-qualified repository"
        )
    if is_gmail_draft_constraint(constraint) and not is_valid_gmail_draft_id(value):
        raise RequestUnderstandingValidationError(
            f"{path}.value must be a valid Gmail Draft identifier"
        )


def validate_resource_responsibilities(
    value: object,
    *,
    effects: Sequence[str],
    resource_hints: Sequence[str],
    constraints: Sequence[ConstraintV1],
    known_unit_ids: Sequence[str],
    required: bool,
) -> ResourceResponsibilitiesV1 | None:
    """Validate source/output responsibility without reclassifying natural language."""

    if value is None:
        if required:
            raise RequestUnderstandingValidationError(
                "$.resource_responsibilities is required"
            )
        return None
    root = _mapping(value, "$.resource_responsibilities")
    if set(root) != {"source_reads", "outputs"}:
        raise RequestUnderstandingValidationError(
            "$.resource_responsibilities fields are invalid"
        )
    source_reads = _list(root.get("source_reads"), "$.resource_responsibilities.source_reads")
    outputs = _list(root.get("outputs"), "$.resource_responsibilities.outputs")
    normalized_sources = []
    source_information: list[str] = []
    source_resources: set[str] = set()
    for index, item in enumerate(source_reads):
        path = f"$.resource_responsibilities.source_reads[{index}]"
        source = _mapping(item, path)
        if set(source) != {
            "resource_type",
            "required_information",
            "target_scope",
            "work_unit_ids",
        }:
            raise RequestUnderstandingValidationError(f"{path} fields are invalid")
        resource_type = _string(source, "resource_type", path)
        information = _string_list(
            source.get("required_information"), f"{path}.required_information"
        )
        target_scope = _string(source, "target_scope", path)
        work_unit_ids = validate_work_unit_refs(
            source.get("work_unit_ids"),
            known_unit_ids=known_unit_ids,
            path=f"{path}.work_unit_ids",
        )
        if target_scope not in {"SINGULAR", "CRITERIA"}:
            raise RequestUnderstandingValidationError(f"{path}.target_scope is invalid")
        if resource_type in source_resources:
            raise RequestUnderstandingValidationError(
                "$.resource_responsibilities contains a duplicate source read"
            )
        source_resources.add(resource_type)
        source_information.extend(information)
        normalized_sources.append(
            {
                "resource_type": resource_type,
                "required_information": information,
                "target_scope": target_scope,
                "work_unit_ids": work_unit_ids,
            }
        )
    normalized_outputs = []
    output_resources: set[str] = set()
    output_identities: set[tuple[str, str, tuple[str, ...]]] = set()
    output_effects: set[str] = set()
    for index, item in enumerate(outputs):
        path = f"$.resource_responsibilities.outputs[{index}]"
        output = _mapping(item, path)
        if set(output) != {"resource_type", "effect", "work_unit_ids"}:
            raise RequestUnderstandingValidationError(f"{path} fields are invalid")
        resource_type = _string(output, "resource_type", path)
        effect = _string(output, "effect", path)
        work_unit_ids = validate_work_unit_refs(
            output.get("work_unit_ids"),
            known_unit_ids=known_unit_ids,
            path=f"{path}.work_unit_ids",
        )
        if effect not in WRITE_EFFECT_RESOURCE_TYPES:
            raise RequestUnderstandingValidationError(f"{path}.effect is invalid")
        if resource_type not in WRITE_EFFECT_RESOURCE_TYPES[effect]:
            raise RequestUnderstandingValidationError(
                f"{path}.resource_type is incompatible with its output effect"
            )
        identity = (resource_type, effect, tuple(work_unit_ids))
        if identity in output_identities:
            raise RequestUnderstandingValidationError(
                "$.resource_responsibilities contains a duplicate output"
            )
        output_identities.add(identity)
        output_resources.add(resource_type)
        output_effects.add(effect)
        normalized_outputs.append(
            {
                "resource_type": resource_type,
                "effect": cast(Literal["CREATE", "UPDATE", "SEND", "DELETE"], effect),
                "work_unit_ids": work_unit_ids,
            }
        )
    derived_effects = ({"READ"} if normalized_sources else set()) | output_effects
    if derived_effects != set(effects) or (
        source_resources | output_resources
    ) != set(resource_hints):
        raise RequestUnderstandingValidationError(
            "$.resource_responsibilities does not match requested hints"
        )
    constraint_information = [
        information
        for constraint in constraints
        if constraint["field"] == "required_information"
        for information in (
            [constraint["value"]]
            if isinstance(constraint["value"], str)
            else constraint["value"]
        )
    ]
    if set(source_information) != set(constraint_information):
        raise RequestUnderstandingValidationError(
            "$.resource_responsibilities source information does not match constraints"
        )
    return cast(
        ResourceResponsibilitiesV1,
        {
            "source_reads": normalized_sources,
            "outputs": normalized_outputs,
        },
    )


def _effect_prohibitions(
    value: object,
    *,
    known_unit_ids: Sequence[str],
) -> list[EffectProhibitionV1]:
    raw = _list(value, "$.effect_prohibitions")
    normalized: list[EffectProhibitionV1] = []
    seen: set[tuple[str, tuple[str, ...]]] = set()
    for index, item in enumerate(raw):
        path = f"$.effect_prohibitions[{index}]"
        root = _mapping(item, path)
        if set(root) != {"effect", "work_unit_ids"}:
            raise RequestUnderstandingValidationError(f"{path} fields are invalid")
        effect = _string(root, "effect", path)
        if effect not in WRITE_EFFECT_RESOURCE_TYPES:
            raise RequestUnderstandingValidationError(f"{path}.effect is invalid")
        refs = validate_work_unit_refs(
            root.get("work_unit_ids"),
            known_unit_ids=known_unit_ids,
            path=f"{path}.work_unit_ids",
        )
        identity = (effect, tuple(refs))
        if identity in seen:
            raise RequestUnderstandingValidationError(
                "$.effect_prohibitions contains a duplicate prohibition"
            )
        seen.add(identity)
        normalized.append(
            {
                "effect": cast(Literal["CREATE", "UPDATE", "SEND", "DELETE"], effect),
                "work_unit_ids": refs,
            }
        )
    return normalized


def requires_resource_responsibilities(
    *, effects: Sequence[str], resource_hints: Sequence[str]
) -> bool:
    return (
        "READ" in effects
        and any(effect in WRITE_EFFECT_RESOURCE_TYPES for effect in effects)
        and len(set(resource_hints)) > 1
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
