"""Inactive exact-selected Source handoff; no model, Prompt activation or Provider I/O.

This prototype covers only identities already present in the current Run selection.
It does not authorize discovery, infer identity from SINGULAR, or extend Product V3.
The evaluation-owned acquisition envelope keeps the new binding out of Product
payloads while reusing Registry selection and the existing Query validator/builder.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from copy import deepcopy
from dataclasses import dataclass
from typing import Any, cast

from scripts.ru_source_requirements_candidate import (
    build_source_requirements_output_schema,
    validate_source_requirements_candidate,
)

from google_work_agent.application.agents.request_understanding.contracts.source_dependency_decision import (  # noqa: E501
    SourceDependencyCandidateV1,
)
from google_work_agent.application.agents.retrieval.bind_exact_resource_refs import (
    ExactResourceBindingsV1,
)
from google_work_agent.application.agents.retrieval.build_query import (
    RouteConstraintPolicy,
    build_query,
)
from google_work_agent.application.agents.retrieval.contracts.query_plan import (
    RetrievalQueryPlanV2,
    SourceFetchPlanV1,
    validate_retrieval_query_plan_v2,
)
from google_work_agent.application.agents.retrieval.plan_query import exact_resource_detail_plan
from google_work_agent.application.agents.tool_routing.bind_registry_candidates import (
    registry_candidates_for_route,
)
from google_work_agent.application.agents.tool_routing.contracts.tool_route_plan import (
    InputToolRouteV1,
)
from google_work_agent.application.tool_registry.signed_tool_registry import SignedToolRegistry
from google_work_agent.domain.action.model import EffectType
from google_work_agent.ports.llm.output_schema_validation import validate_output_schema
from google_work_agent.ports.llm.structured_inference_contracts import OutputSchemaDefinition
from google_work_agent.ports.system.contracts.workflow_execution import SelectedResourceRef

CANDIDATE_SCHEMA_VERSION = "evaluation-selected-source-requirements-v1"


@dataclass(frozen=True, slots=True)
class SelectedSourceRequirement:
    resource_type: str
    required_information: tuple[str, ...]
    target_scope: str
    work_unit_ids: tuple[str, ...]
    selected_resource_ref_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class SelectedSourceAcquisition:
    route: InputToolRouteV1
    selected_resource_ref_ids: tuple[str, ...]
    identity: SelectedResourceRef
    requirements: tuple[SelectedSourceRequirement, ...]


@dataclass(frozen=True, slots=True)
class SelectedSourceHandoff:
    requirements: tuple[SelectedSourceRequirement, ...]
    acquisitions: tuple[SelectedSourceAcquisition, ...]
    exact_bindings: ExactResourceBindingsV1
    query_plan: RetrievalQueryPlanV2
    fetch_plans: tuple[SourceFetchPlanV1, ...]


def _selected_index(
    selected_resources: Sequence[SelectedResourceRef],
) -> dict[str, SelectedResourceRef]:
    result: dict[str, SelectedResourceRef] = {}
    for selected in selected_resources:
        if (
            not all(
                (
                    selected.resource_ref_id,
                    selected.connector_id,
                    selected.resource_type,
                    selected.resource_id,
                )
            )
            or selected.resource_ref_id in result
        ):
            raise ValueError("current-Run selected refs must be non-empty and unique")
        result[selected.resource_ref_id] = selected
    if not result:
        raise ValueError("exact-selected prototype requires current-Run selected refs")
    return result


def build_selected_source_output_schema(
    source_candidates: Sequence[SourceDependencyCandidateV1],
    *,
    work_unit_ids: Sequence[str],
    selected_resources: Sequence[SelectedResourceRef],
) -> OutputSchemaDefinition:
    selected_by_id = _selected_index(selected_resources)
    base = build_source_requirements_output_schema(
        source_candidates, work_unit_ids=work_unit_ids, require_at_least_one_source=True
    )
    schema = cast(dict[str, Any], deepcopy(base.json_schema))
    variants = schema["properties"]["source_dependencies"]["items"]["oneOf"]
    required = next(
        variant
        for variant in variants
        if variant["properties"]["dependency"] == {"const": "SOURCE_REQUIRED"}
    )
    requirement = required["properties"]["requirements"]["items"]
    requirement["required"].append("selected_resource_ref_ids")
    requirement["properties"]["selected_resource_ref_ids"] = {
        "type": "array",
        "minItems": 1,
        "uniqueItems": True,
        "items": {"enum": list(selected_by_id)},
    }
    return OutputSchemaDefinition(schema_version=CANDIDATE_SCHEMA_VERSION, json_schema=schema)


def validate_selected_source_requirements(
    value: object,
    *,
    source_candidates: Sequence[SourceDependencyCandidateV1],
    work_unit_ids: Sequence[str],
    selected_resources: Sequence[SelectedResourceRef],
) -> tuple[SelectedSourceRequirement, ...]:
    schema = build_selected_source_output_schema(
        source_candidates, work_unit_ids=work_unit_ids, selected_resources=selected_resources
    )
    errors = validate_output_schema(value, schema.json_schema)
    if errors:
        raise ValueError(f"selected Source binding is invalid: {'; '.join(errors)}")
    selected_by_id = _selected_index(selected_resources)
    candidates = {candidate["resource_type"]: candidate for candidate in source_candidates}
    result: list[SelectedSourceRequirement] = []
    for decision in cast(dict[str, Any], value)["source_dependencies"]:
        if decision["dependency"] == "SOURCE_NOT_REQUIRED":
            continue
        resource_type = decision["resource_type"]
        for requirement in decision["requirements"]:
            if requirement["target_scope"] != "SINGULAR":
                raise ValueError("discovery/scope authorization is outside this prototype")
            base_requirement = {
                key: deepcopy(item)
                for key, item in requirement.items()
                if key != "selected_resource_ref_ids"
            }
            # Validate separately: two exact targets of one WorkUnit must not be
            # collapsed by the old (Resource, WorkUnit) normalizer.
            validate_source_requirements_candidate(
                {
                    "source_dependencies": [
                        {
                            "resource_type": resource_type,
                            "dependency": "SOURCE_REQUIRED",
                            "requirements": [base_requirement],
                        }
                    ]
                },
                source_candidates=(candidates[resource_type],),
                work_unit_ids=work_unit_ids,
            )
            for ref_id in requirement["selected_resource_ref_ids"]:
                if selected_by_id[ref_id].resource_type.upper() != resource_type:
                    raise ValueError("selected ref resource does not match its Source requirement")
            result.append(
                SelectedSourceRequirement(
                    resource_type=resource_type,
                    required_information=tuple(requirement["required_information"]),
                    target_scope=requirement["target_scope"],
                    work_unit_ids=tuple(requirement["work_unit_ids"]),
                    selected_resource_ref_ids=tuple(requirement["selected_resource_ref_ids"]),
                )
            )
    covered_refs = {ref for item in result for ref in item.selected_resource_ref_ids}
    if covered_refs != set(selected_by_id):
        raise ValueError("selected identity has no explicit Source WorkUnit binding")
    return tuple(result)


def build_selected_source_handoff(
    value: object,
    *,
    source_candidates: Sequence[SourceDependencyCandidateV1],
    work_unit_ids: Sequence[str],
    selected_resources: Sequence[SelectedResourceRef],
    tool_catalog: SignedToolRegistry,
    id_factory: Callable[[], str],
) -> SelectedSourceHandoff:
    """Bind exact acquisition identities, sharing capability but not distinct targets."""
    requirements = validate_selected_source_requirements(
        value,
        source_candidates=source_candidates,
        work_unit_ids=work_unit_ids,
        selected_resources=selected_resources,
    )
    selected_by_id = _selected_index(selected_resources)
    capabilities = {
        resource: registry_candidates_for_route(
            tool_catalog=tool_catalog, resource_type=resource, effect_type=EffectType.READ
        )
        for resource in dict.fromkeys(item.resource_type for item in requirements)
    }
    groups: dict[tuple[str, str, str, str | None], list[SelectedSourceRequirement]] = {}
    refs_by_group: dict[tuple[str, str, str, str | None], list[str]] = {}
    for requirement in requirements:
        for ref_id in requirement.selected_resource_ref_ids:
            selected = selected_by_id[ref_id]
            connector, _ = capabilities[requirement.resource_type]
            if connector != selected.connector_id:
                raise ValueError("selected ref connector does not match Registry capability")
            key = (
                connector,
                requirement.resource_type,
                selected.resource_id,
                selected.parent_resource_id,
            )
            items = groups.setdefault(key, [])
            if requirement not in items:
                items.append(requirement)
            refs = refs_by_group.setdefault(key, [])
            if ref_id not in refs:
                refs.append(ref_id)
    acquisitions: list[SelectedSourceAcquisition] = []
    exact: ExactResourceBindingsV1 = {"refs_by_route": {}, "identities_by_ref": {}}
    seen_route_ids: set[str] = set()
    for key, items in groups.items():
        connector, resource_type, resource_id, parent = key
        route_id = id_factory()
        if not route_id or route_id in seen_route_ids:
            raise ValueError("acquisition route ids must be non-empty and unique")
        seen_route_ids.add(route_id)
        route: InputToolRouteV1 = {
            "route_id": route_id,
            "resource_type": resource_type,
            "connector_id": connector,
            "allowed_read_tool_ids": list(capabilities[resource_type][1]),
            "required": True,
            "reason_codes": ["RESOURCE_SELECTED"],
            "work_unit_ids": list(
                dict.fromkeys(unit for item in items for unit in item.work_unit_ids)
            ),
        }
        selected_ref_ids = tuple(refs_by_group[key])
        acquisitions.append(
            SelectedSourceAcquisition(
                route=route,
                selected_resource_ref_ids=selected_ref_ids,
                identity=selected_by_id[selected_ref_ids[0]],
                requirements=tuple(items),
            )
        )
        resource_ref = f"{resource_type.lower()}:{resource_id}"
        identity = {"resource_type": resource_type, "resource_id": resource_id, "parent_id": parent}
        if (
            resource_ref in exact["identities_by_ref"]
            and exact["identities_by_ref"][resource_ref] != identity
        ):
            raise ValueError("Product exact-ref representation cannot distinguish these parents")
        exact["refs_by_route"][route_id] = [resource_ref]
        exact["identities_by_ref"][resource_ref] = cast(Any, identity)
    routes = [item.route for item in acquisitions]
    query: RetrievalQueryPlanV2 = {"schema_version": 2, "route_queries": []}
    for route in routes:
        partial = exact_resource_detail_plan(
            frozen_routes=(route,),
            validated_resource_refs=exact["refs_by_route"],
            is_followup=False,
        )
        if partial is None:
            raise ValueError("selected acquisition lacks an exact Registry detail operation")
        query["route_queries"].extend(partial["route_queries"])
    query = validate_retrieval_query_plan_v2(
        query,
        frozen_routes=routes,
        supported_constraint_kinds={},
        validated_resource_refs=exact["refs_by_route"],
    )
    fetch = build_query(
        query,
        frozen_routes=routes,
        route_policies={route["route_id"]: RouteConstraintPolicy(frozenset()) for route in routes},
        validated_resource_refs=exact["refs_by_route"],
    )
    return SelectedSourceHandoff(requirements, tuple(acquisitions), exact, query, tuple(fetch))
