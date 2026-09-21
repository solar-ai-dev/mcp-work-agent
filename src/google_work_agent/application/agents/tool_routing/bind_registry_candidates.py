from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from typing import cast

from google_work_agent.application.agents.tool_routing.contracts.route_binding_candidate import (
    BoundOutputRouteCandidateV1,
    RouteBindingCandidateV1,
)
from google_work_agent.application.agents.tool_routing.contracts.semantic_route_candidate import (
    SemanticRouteCandidate,
)
from google_work_agent.application.agents.tool_routing.contracts.tool_route_plan import (
    InputToolRouteV1,
    ToolRouteEffect,
)
from google_work_agent.application.agents.tool_routing.validate_route import (
    ToolRouteValidationError,
)
from google_work_agent.application.tool_registry.signed_tool_registry import SignedToolRegistry
from google_work_agent.domain.action.model import EffectType

_READ_DEPENDENCIES_BY_RESOURCE: Mapping[str, tuple[tuple[str, str], ...]] = {
    "GMAIL_MESSAGE": (("GMAIL_THREAD", "RETRIEVAL_GMAIL_DISCOVERY"),),
    "TASK": (("TASK_LIST", "RETRIEVAL_TASK_LIST_DISCOVERY"),),
    "TASK_LIST": (("TASK", "RETRIEVAL_TASK_DETAIL"),),
    "CALENDAR": (("CALENDAR_EVENT", "RETRIEVAL_CALENDAR_EVENT_DETAIL"),),
    "CALENDAR_EVENT": (("CALENDAR", "RETRIEVAL_CALENDAR_DISCOVERY"),),
    "CALENDAR_FREEBUSY": (
        ("CALENDAR", "RETRIEVAL_CALENDAR_DISCOVERY"),
        ("CALENDAR_EVENT", "RETRIEVAL_CALENDAR_EVENT_DISCOVERY"),
    ),
}
_RETRIEVAL_DEPENDENCY_REASON_CODES = frozenset(
    reason_code
    for dependencies in _READ_DEPENDENCIES_BY_RESOURCE.values()
    for _, reason_code in dependencies
)


def is_retrieval_dependency_route(route: InputToolRouteV1) -> bool:
    """Return whether a route exists only to execute a read prerequisite."""
    reason_codes = route["reason_codes"]
    return bool(reason_codes) and all(
        reason_code in _RETRIEVAL_DEPENDENCY_REASON_CODES
        for reason_code in reason_codes
    )


def business_required_source_routes(
    routes: Iterable[InputToolRouteV1],
) -> tuple[InputToolRouteV1, ...]:
    """Project business evidence requirements without removing execution prerequisites."""
    return tuple(
        route
        for route in routes
        if route["required"] and not is_retrieval_dependency_route(route)
    )


def normalize_resource_type(value: str) -> str:
    normalized = value.strip().upper()
    return {
        "GMAIL": "GMAIL_THREAD",
        "EMAIL": "GMAIL_THREAD",
        "TASKS": "TASK",
        "ISSUE": "GITHUB_ISSUE",
        "GITHUB": "GITHUB_ISSUE",
        "CALENDAR": "CALENDAR_EVENT",
        "EVENT": "CALENDAR_EVENT",
    }.get(normalized, normalized)


def coarse_resource_category(resource_type: str) -> str:
    resource_type = normalize_resource_type(resource_type)
    if resource_type.startswith("GMAIL"):
        return "EMAIL"
    if resource_type in {"TASK", "TASK_LIST"}:
        return "TASK"
    if resource_type == "GITHUB_ISSUE":
        return "ISSUE"
    if resource_type.startswith("CALENDAR"):
        return "CALENDAR"
    raise ToolRouteValidationError(f"resource type has no coarse category: {resource_type}")


def registry_candidates_for_route(
    *, tool_catalog: SignedToolRegistry, resource_type: str, effect_type: EffectType
) -> tuple[str, tuple[str, ...]]:
    """Return the bounded Registry candidates for one semantic route."""
    return _eligible_bindings(tool_catalog, resource_type, effect_type)


def bind_registry_candidates(
    *,
    candidate: SemanticRouteCandidate,
    tool_catalog: SignedToolRegistry,
    id_factory: Callable[[], str],
) -> RouteBindingCandidateV1:
    """Bind semantic routes to a deterministic, bounded Registry candidate artifact.

    This operation owns Registry eligibility lookup only. It never chooses among
    multiple eligible tools; semantic selection is a separate downstream authority.
    """
    output_candidates: list[BoundOutputRouteCandidateV1] = []
    output_bindings = {
        (resource_type, effect_type, index): work_unit_ids
        for index, (resource_type, effect_type, work_unit_ids) in enumerate(
            candidate.output_work_unit_bindings
        )
    }
    for index, (resource_type, effect_type) in enumerate(candidate.output_pairs):
        connector_id, eligible_tool_ids = registry_candidates_for_route(
            tool_catalog=tool_catalog,
            resource_type=resource_type,
            effect_type=effect_type,
        )
        output_candidates.append(
            BoundOutputRouteCandidateV1(
                route_id=id_factory(),
                resource_type=resource_type,
                connector_id=connector_id,
                effect=cast(ToolRouteEffect, effect_type.value),
                eligible_tool_ids=eligible_tool_ids,
                work_unit_ids=output_bindings.get(
                    (resource_type, effect_type, index),
                    (),
                ),
            )
        )
    input_routes = _bind_input_routes(
        resource_types=candidate.input_resource_types,
        tool_catalog=tool_catalog,
        id_factory=id_factory,
        reason_code="REQUESTED_INPUT",
        reason_codes_by_resource=dict(candidate.input_reason_codes),
        work_unit_ids_by_resource=dict(candidate.input_work_unit_bindings),
    )
    existing = {route["resource_type"] for route in input_routes}
    selected_resource_types = {
        resource_type
        for resource_type, reason_code in candidate.input_reason_codes
        if reason_code == "RESOURCE_SELECTED"
    }
    for resource_type, reason_code in _read_dependencies(
        candidate.input_resource_types,
        direct_resource_types=selected_resource_types,
    ):
        if resource_type in existing:
            continue
        input_routes.extend(
            _bind_input_routes(
                resource_types=(resource_type,),
                tool_catalog=tool_catalog,
                id_factory=id_factory,
                reason_code=reason_code,
                reason_codes_by_resource={},
                work_unit_ids_by_resource={
                    resource_type: _dependency_work_unit_ids(
                        dependency_resource_type=resource_type,
                        candidate=candidate,
                    )
                },
            )
        )
        existing.add(resource_type)
    return RouteBindingCandidateV1(
        semantic=candidate,
        input_routes=tuple(input_routes),
        output_candidates=tuple(output_candidates),
    )


def _bind_input_routes(
    *,
    resource_types: Iterable[str],
    tool_catalog: SignedToolRegistry,
    id_factory: Callable[[], str],
    reason_code: str,
    reason_codes_by_resource: Mapping[str, str],
    work_unit_ids_by_resource: Mapping[str, tuple[str, ...]],
) -> list[InputToolRouteV1]:
    routes: list[InputToolRouteV1] = []
    for resource_type in sorted(set(resource_types)):
        work_unit_ids = work_unit_ids_by_resource.get(resource_type, ())
        if not work_unit_ids:
            raise ToolRouteValidationError(
                f"input route has no WorkUnit binding: {resource_type}"
            )
        connector_id, candidates = _eligible_bindings(tool_catalog, resource_type, EffectType.READ)
        routes.append(
            {
                "route_id": id_factory(),
                "resource_type": resource_type,
                "connector_id": connector_id,
                "allowed_read_tool_ids": list(candidates),
                "required": True,
                "reason_codes": [reason_codes_by_resource.get(resource_type, reason_code)],
                "work_unit_ids": list(work_unit_ids),
            }
        )
    return routes


def _dependency_work_unit_ids(
    *,
    dependency_resource_type: str,
    candidate: SemanticRouteCandidate,
) -> tuple[str, ...]:
    direct_bindings = dict(candidate.input_work_unit_bindings)
    refs: list[str] = []
    for resource_type in candidate.input_resource_types:
        if dependency_resource_type not in {
            dependency for dependency, _reason in _READ_DEPENDENCIES_BY_RESOURCE.get(
                resource_type, ()
            )
        }:
            continue
        refs.extend(
            unit_id
            for unit_id in direct_bindings.get(resource_type, ())
            if unit_id not in refs
        )
    if not refs:
        raise ToolRouteValidationError(
            f"dependency route has no originating WorkUnit binding: {dependency_resource_type}"
        )
    return tuple(refs)


def _eligible_bindings(
    tool_catalog: SignedToolRegistry, resource_type: str, effect_type: EffectType
) -> tuple[str, tuple[str, ...]]:
    matches: list[tuple[str, tuple[str, ...]]] = []
    connector_ids = sorted({entry.connector_id for entry in tool_catalog.entries})
    for connector_id in connector_ids:
        entries = tool_catalog.select_candidates(
            connector_id=connector_id,
            resource_type=resource_type,
            effect=effect_type.value,
        )
        if entries:
            matches.append((connector_id, tuple(entry.tool_name for entry in entries)))
    if len(matches) != 1:
        raise ToolRouteValidationError(
            "resource/effect must resolve to exactly one connector: "
            f"{resource_type}/{effect_type.value}"
        )
    return matches[0]


def _read_dependencies(
    resource_types: Iterable[str],
    *,
    direct_resource_types: Iterable[str] = (),
) -> tuple[tuple[str, str], ...]:
    direct_resources = set(direct_resource_types)
    return tuple(
        dependency
        for resource_type in sorted(set(resource_types))
        if resource_type in _READ_DEPENDENCIES_BY_RESOURCE
        and resource_type not in direct_resources
        for dependency in _READ_DEPENDENCIES_BY_RESOURCE[resource_type]
    )
