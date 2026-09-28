"""Inactive SourceStatus WorkUnit-binding prototype; no Product monkeypatch.

The existing status call retains its semantic responsibility. Only its input and
output contract changes: confirmed work provenance enters, explicit work refs
leave. The normalized artifact is the existing ConstraintV1, not new V3 State.
Model/Provider quality, Prompt activation and historical Run repair are not
implemented here. A live experiment needs an explicit candidate Prompt binding.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from copy import deepcopy
from typing import Literal, cast

from google_work_agent.application.agents.request_understanding.contracts.request_intent import (
    ConstraintProvenanceSource,
    ConstraintV1,
    RequestedWorkDefinitionV1,
    RequestGoalCandidateV1,
    ResourceResponsibilitiesV1,
)
from google_work_agent.application.agents.request_understanding.contracts.work_unit_binding import (
    validate_requested_work_definition,
    validate_work_unit_refs,
)
from google_work_agent.application.agents.request_understanding.identify_goal import (
    _project_preserved_source_statuses,
)
from google_work_agent.application.agents.request_understanding.identify_source_status import (
    _llm_facing_status_values,
    build_identify_source_status_output_schema,
    identify_source_status,
    normalize_source_status_constraints,
)
from google_work_agent.ports.llm.output_schema_validation import validate_output_schema
from google_work_agent.ports.llm.structured_inference_contracts import (
    OutputSchemaDefinition,
    PromptReference,
)
from google_work_agent.ports.llm.structured_inference_port import (
    StructuredInferencePort,
    StructuredInferenceResultV1,
)


def _source_work_bindings(
    responsibilities: ResourceResponsibilitiesV1,
    requested_work: RequestedWorkDefinitionV1,
) -> dict[str, list[str]]:
    known = [unit["unit_id"] for unit in requested_work["work_units"]]
    result: dict[str, list[str]] = {}
    for source in responsibilities["source_reads"]:
        refs = validate_work_unit_refs(
            source["work_unit_ids"], known_unit_ids=known, path="source_reads.work_unit_ids"
        )
        if _llm_facing_status_values(source["resource_type"]):
            bound = result.setdefault(source["resource_type"], [])
            bound.extend(ref for ref in refs if ref not in bound)
    return result


def build_work_bound_source_status_schema(
    responsibilities: ResourceResponsibilitiesV1,
    requested_work: RequestedWorkDefinitionV1,
) -> OutputSchemaDefinition:
    """Close refs against existing Source membership, not the entire work set."""
    bindings = _source_work_bindings(responsibilities, requested_work)
    product_schema = build_identify_source_status_output_schema(responsibilities)
    schema = cast(dict[str, object], deepcopy(product_schema.json_schema))
    statuses = cast(dict[str, object], cast(dict[str, object], schema["properties"])["statuses"])
    items = cast(dict[str, object], statuses["items"])
    variants = cast(list[dict[str, object]], items["oneOf"]) if "oneOf" in items else [items]
    for variant in variants if bindings else []:
        properties = cast(dict[str, object], variant["properties"])
        resource_type = cast(dict[str, str], properties["source_resource_type"])["const"]
        refs = bindings[resource_type]
        properties["work_unit_ids"] = {
            "type": "array",
            "minItems": 1,
            "maxItems": len(refs),
            "uniqueItems": True,
            "items": {"enum": list(refs)},
        }
        cast(list[str], variant["required"]).append("work_unit_ids")
    statuses["maxItems"] = sum(
        len(refs) * len(_llm_facing_status_values(resource)) for resource, refs in bindings.items()
    )
    return OutputSchemaDefinition("request-source-status-v3", schema)


class _WorkBoundStatusInference:
    def __init__(
        self,
        delegate: StructuredInferencePort,
        requested_work: RequestedWorkDefinitionV1,
        schema: OutputSchemaDefinition,
    ) -> None:
        self._delegate = delegate
        self._requested_work = requested_work
        self._schema = schema

    def infer(
        self,
        requested_mode: Literal["AUTO", "LOCAL_GPU", "API_LLM"],
        prompt_ref: PromptReference,
        input_projection: Mapping[str, object],
        output_schema_ref: OutputSchemaDefinition,
    ) -> StructuredInferenceResultV1:
        if (
            prompt_ref.prompt_id != "request_understanding.identify_source_status"
            or output_schema_ref.schema_version != "request-source-status-v2"
        ):
            raise ValueError("candidate only adapts the existing SourceStatus call")
        projection = deepcopy(dict(input_projection))
        base = projection.get("base_projection", projection)
        if not isinstance(base, dict):
            raise ValueError("status revision requires its original base projection")
        base["requested_work"] = deepcopy(self._requested_work)
        return self._delegate.infer(requested_mode, prompt_ref, projection, self._schema)


def identify_work_bound_source_status(
    *,
    llm_runtime: StructuredInferencePort,
    requested_mode: Literal["AUTO", "LOCAL_GPU", "API_LLM"],
    prompt_ref: PromptReference,
    prompt_input: Mapping[str, object],
    goal_candidate: Mapping[str, object],
    responsibilities: ResourceResponsibilitiesV1,
    candidate_output: object | None = None,
    failure_record: Mapping[str, object] | None = None,
) -> object:
    """Reuse the existing single-call/zero-call and revision projection paths."""
    user_request = prompt_input.get("user_request")
    if not isinstance(user_request, str):
        raise ValueError("status candidate requires the current user request")
    work = validate_requested_work_definition(
        prompt_input.get("requested_work"), user_request=user_request
    )
    schema = build_work_bound_source_status_schema(responsibilities, work)
    return identify_source_status(
        llm_runtime=cast(
            StructuredInferencePort, _WorkBoundStatusInference(llm_runtime, work, schema)
        ),
        requested_mode=requested_mode,
        prompt_ref=prompt_ref,
        prompt_input=prompt_input,
        goal_candidate=goal_candidate,
        responsibilities=responsibilities,
        candidate_output=candidate_output,
        failure_record=failure_record,
    )


def normalize_work_bound_source_statuses(
    value: object,
    *,
    responsibilities: ResourceResponsibilitiesV1,
    requested_work: RequestedWorkDefinitionV1,
    provenance_sources: Mapping[ConstraintProvenanceSource, str] | None,
) -> list[ConstraintV1]:
    """Reuse exact provenance validation with each item's explicit Source scope."""
    schema = build_work_bound_source_status_schema(responsibilities, requested_work)
    errors = validate_output_schema(value, schema.json_schema)
    if errors:
        raise ValueError(f"work-bound status candidate is invalid: {'; '.join(errors)}")
    items = cast(Sequence[Mapping[str, object]], cast(Mapping[str, object], value)["statuses"])
    normalized: list[ConstraintV1] = []
    identities: set[tuple[object, ...]] = set()
    for item in items:
        refs = cast(list[str], item["work_unit_ids"])
        identity = (
            item["value"],
            item["source_resource_type"],
            item["source"],
            item["source_text"],
            tuple(sorted(refs)),
        )
        if identity in identities:
            raise ValueError("work-bound source status binding is duplicated")
        identities.add(identity)
        local = cast(
            ResourceResponsibilitiesV1,
            {
                "source_reads": [
                    {
                        **deepcopy(source),
                        "work_unit_ids": [ref for ref in refs if ref in source["work_unit_ids"]],
                    }
                    for source in responsibilities["source_reads"]
                    if source["resource_type"] == item["source_resource_type"]
                    and set(refs).intersection(source["work_unit_ids"])
                ],
                "outputs": deepcopy(responsibilities["outputs"]),
            },
        )
        constraint = normalize_source_status_constraints(
            {"statuses": [{key: val for key, val in item.items() if key != "work_unit_ids"}]},
            responsibilities=local,
            provenance_sources=provenance_sources,
        )[0]
        normalized.append({**constraint, "work_unit_ids": list(refs)})
    return normalized


def project_preserved_work_bound_statuses(candidate: RequestGoalCandidateV1) -> dict[str, object]:
    """Carry persisted V3 binding as-is; never infer missing historical ownership."""
    projection = _project_preserved_source_statuses(candidate)
    constraints = [
        item
        for item in candidate["constraints"]
        if item["kind"] == "SCOPE" and item["field"] == "status"
    ]
    known = [unit["unit_id"] for unit in candidate["requested_work"]["work_units"]]
    for status, constraint in zip(
        cast(list[dict[str, object]], projection["statuses"]), constraints, strict=True
    ):
        status["work_unit_ids"] = validate_work_unit_refs(
            constraint.get("work_unit_ids"),
            known_unit_ids=known,
            path="preserved_status.work_unit_ids",
        )
    return projection
