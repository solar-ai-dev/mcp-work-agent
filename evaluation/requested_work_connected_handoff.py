"""Evaluation-only connected handoff for item-owned WorkUnit bindings.

The prototype starts after Request Understanding has already produced validated
semantic owner items.  It tests how those bindings can survive Tool Route,
Retrieval, and Planning without changing production contracts or inferring user
meaning again.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from typing import Literal, NotRequired, TypedDict, cast

WriteEffect = Literal["CREATE", "UPDATE", "SEND", "DELETE"]


class WorkBoundSourceResponsibilityV1(TypedDict):
    resource_type: str
    required_information: list[str]
    target_scope: Literal["SINGULAR", "CRITERIA"]
    work_unit_ids: list[str]


class WorkBoundOutputResponsibilityV1(TypedDict):
    resource_type: str
    effect: WriteEffect
    work_unit_ids: list[str]


class WorkBoundInputRouteV1(TypedDict):
    route_id: str
    resource_type: str
    connector_id: str
    allowed_read_tool_ids: list[str]
    required: bool
    work_unit_ids: list[str]


class WorkBoundOutputRouteV1(TypedDict):
    route_id: str
    resource_type: str
    connector_id: str
    effect: WriteEffect
    selected_tool_id: str
    work_unit_ids: list[str]


class RetrievalWorkCoverageV1(TypedDict):
    route_id: str
    work_unit_ids: list[str]
    evidence_refs: list[str]


class RetrievalRouteRequirementV1(TypedDict):
    route_id: str
    work_unit_ids: list[str]
    source_responsibilities: list[WorkBoundSourceResponsibilityV1]


class PlannedSpecificationV1(TypedDict):
    route_id: str
    resource_type: str
    effect: WriteEffect
    selected_tool_id: str
    work_unit_ids: list[str]
    evidence_refs: list[str]


class AnswerWorkEvidenceV1(TypedDict):
    work_unit_id: str
    evidence_refs: list[str]


class AnswerPlanningInputV1(TypedDict):
    work_unit_ids: list[str]
    evidence_by_work_unit: list[AnswerWorkEvidenceV1]


class ToolBindingV1(TypedDict):
    connector_id: str
    tool_id: str


class ConnectedHandoffResultV1(TypedDict):
    input_routes: list[WorkBoundInputRouteV1]
    output_routes: list[WorkBoundOutputRouteV1]
    retrieval_requirements: list[RetrievalRouteRequirementV1]
    retrieval_coverage: list[RetrievalWorkCoverageV1]
    answer_planning_inputs: list[AnswerPlanningInputV1]
    planned_specifications: list[PlannedSpecificationV1]
    metrics: dict[str, int]


class ConnectedScenarioV1(TypedDict):
    scenario_id: str
    work_unit_ids: list[str]
    source_responsibilities: list[WorkBoundSourceResponsibilityV1]
    output_responsibilities: list[WorkBoundOutputResponsibilityV1]
    expected: NotRequired[dict[str, int]]


def project_connected_handoff(
    scenario: Mapping[str, object],
    *,
    tool_bindings: Mapping[tuple[str, str], ToolBindingV1],
) -> ConnectedHandoffResultV1:
    """Project one validated RequestIntentV3 candidate through adjacent owners.

    READ routes are shared by Resource capability and carry the union of their
    owner-item WorkUnit bindings.  Output routes stay one-to-one with owner
    items even when their Resource/effect capability is equal.
    """

    unit_ids = _unique_strings(scenario.get("work_unit_ids"), "work_unit_ids")
    known_units = set(unit_ids)
    sources = _source_items(scenario.get("source_responsibilities"), known_units=known_units)
    outputs = _output_items(scenario.get("output_responsibilities"), known_units=known_units)

    input_routes = _project_input_routes(sources, tool_bindings=tool_bindings)
    output_routes = _project_output_routes(outputs, tool_bindings=tool_bindings)
    sources_by_resource: dict[str, list[WorkBoundSourceResponsibilityV1]] = defaultdict(list)
    for item in sources:
        sources_by_resource[item["resource_type"]].append(item)
    retrieval_requirements: list[RetrievalRouteRequirementV1] = [
        {
            "route_id": route["route_id"],
            "work_unit_ids": list(route["work_unit_ids"]),
            "source_responsibilities": [
                cast(WorkBoundSourceResponsibilityV1, dict(item))
                for item in sources_by_resource[route["resource_type"]]
            ],
        }
        for route in input_routes
    ]
    retrieval_coverage: list[RetrievalWorkCoverageV1] = [
        {
            "route_id": route["route_id"],
            "work_unit_ids": list(route["work_unit_ids"]),
            "evidence_refs": [f"evidence:{route['route_id']}"],
        }
        for route in input_routes
    ]
    evidence_by_unit: dict[str, list[str]] = defaultdict(list)
    for coverage in retrieval_coverage:
        for unit_id in coverage["work_unit_ids"]:
            evidence_by_unit[unit_id].extend(coverage["evidence_refs"])
    planned_specifications: list[PlannedSpecificationV1] = [
        {
            "route_id": route["route_id"],
            "resource_type": route["resource_type"],
            "effect": route["effect"],
            "selected_tool_id": route["selected_tool_id"],
            "work_unit_ids": list(route["work_unit_ids"]),
            "evidence_refs": _stable_union(
                evidence_by_unit[unit_id] for unit_id in route["work_unit_ids"]
            ),
        }
        for route in output_routes
    ]
    answer_planning_inputs: list[AnswerPlanningInputV1] = []
    if not output_routes:
        answer_planning_inputs.append(
            {
                "work_unit_ids": list(unit_ids),
                "evidence_by_work_unit": [
                    {
                        "work_unit_id": unit_id,
                        "evidence_refs": list(evidence_by_unit[unit_id]),
                    }
                    for unit_id in unit_ids
                ],
            }
        )
    output_capabilities = {(route["resource_type"], route["effect"]) for route in output_routes}
    return {
        "input_routes": input_routes,
        "output_routes": output_routes,
        "retrieval_requirements": retrieval_requirements,
        "retrieval_coverage": retrieval_coverage,
        "answer_planning_inputs": answer_planning_inputs,
        "planned_specifications": planned_specifications,
        "metrics": {
            "input_route_count": len(input_routes),
            "query_plan_count": len(input_routes),
            "provider_read_count": len(input_routes),
            "output_capability_selection_count": len(output_capabilities),
            "output_route_count": len(output_routes),
            "answer_planning_input_count": len(answer_planning_inputs),
            "planning_specification_count": len(planned_specifications),
            "provider_write_count": 0,
            "llm_call_count": 0,
        },
    }


def validate_connected_handoff(
    scenario: Mapping[str, object], result: Mapping[str, object]
) -> list[str]:
    errors: list[str] = []
    known_units = set(_unique_strings(scenario.get("work_unit_ids"), "work_unit_ids"))
    sources = _source_items(scenario.get("source_responsibilities"), known_units=known_units)
    outputs = _output_items(scenario.get("output_responsibilities"), known_units=known_units)
    input_routes = _mapping_list(result.get("input_routes"), "input_routes")
    output_routes = _mapping_list(result.get("output_routes"), "output_routes")
    retrieval_requirements = _mapping_list(
        result.get("retrieval_requirements"), "retrieval_requirements"
    )
    coverage = _mapping_list(result.get("retrieval_coverage"), "retrieval_coverage")
    answer_inputs = _mapping_list(result.get("answer_planning_inputs"), "answer_planning_inputs")
    specifications = _mapping_list(result.get("planned_specifications"), "planned_specifications")

    expected_source_units: dict[str, set[str]] = defaultdict(set)
    for item in sources:
        expected_source_units[item["resource_type"]].update(item["work_unit_ids"])
    actual_source_units = {
        _text(item.get("resource_type"), "input route resource_type"): set(
            _unique_strings(item.get("work_unit_ids"), "input route work_unit_ids")
        )
        for item in input_routes
    }
    if actual_source_units != dict(expected_source_units):
        errors.append("input routes do not preserve source WorkUnit applicability")
    if len(input_routes) != len(expected_source_units):
        errors.append("shared READ capability was duplicated")

    requirements_by_route = {
        _text(item.get("route_id"), "requirement route_id"): item for item in retrieval_requirements
    }
    for route in input_routes:
        route_id = _text(route.get("route_id"), "input route_id")
        requirement = requirements_by_route.get(route_id)
        expected_items = [
            item for item in sources if item["resource_type"] == route["resource_type"]
        ]
        if requirement is None or requirement.get("source_responsibilities") != expected_items:
            errors.append(f"retrieval requirement lost owner items for {route_id}")

    coverage_by_route = {
        _text(item.get("route_id"), "coverage route_id"): set(
            _unique_strings(item.get("work_unit_ids"), "coverage work_unit_ids")
        )
        for item in coverage
    }
    for route in input_routes:
        route_id = _text(route.get("route_id"), "input route_id")
        if coverage_by_route.get(route_id) != set(
            _unique_strings(route.get("work_unit_ids"), "input route work_unit_ids")
        ):
            errors.append(f"retrieval coverage lost binding for {route_id}")

    expected_outputs = [
        (item["resource_type"], item["effect"], tuple(item["work_unit_ids"])) for item in outputs
    ]
    actual_outputs = [
        (
            _text(item.get("resource_type"), "output resource_type"),
            _text(item.get("effect"), "output effect"),
            tuple(_unique_strings(item.get("work_unit_ids"), "output work_unit_ids")),
        )
        for item in output_routes
    ]
    if actual_outputs != expected_outputs:
        errors.append("output routes merged or reordered distinct owner items")
    specifications_by_route = {
        _text(item.get("route_id"), "specification route_id"): item for item in specifications
    }
    if len(specifications_by_route) != len(specifications):
        errors.append("planning specifications contain duplicate route IDs")
    for route in output_routes:
        route_id = _text(route.get("route_id"), "output route_id")
        specification = specifications_by_route.get(route_id)
        if specification is None or _unique_strings(
            specification.get("work_unit_ids"), "specification work_unit_ids"
        ) != _unique_strings(route.get("work_unit_ids"), "output route work_unit_ids"):
            errors.append(f"planning specification lost binding for {route_id}")
    if outputs and answer_inputs:
        errors.append("ACTION handoff must not create an ANSWER planning input")
    if not outputs:
        if len(answer_inputs) != 1:
            errors.append("ANSWER handoff must keep one shared planning input")
        else:
            answer_input = answer_inputs[0]
            if (
                set(_unique_strings(answer_input.get("work_unit_ids"), "answer work_unit_ids"))
                != known_units
            ):
                errors.append("ANSWER planning input lost WorkUnit coverage")
            evidence_items = _mapping_list(
                answer_input.get("evidence_by_work_unit"), "evidence_by_work_unit"
            )
            evidence_unit_ids = [
                _text(item.get("work_unit_id"), "answer evidence work_unit_id")
                for item in evidence_items
            ]
            if set(evidence_unit_ids) != known_units or len(evidence_unit_ids) != len(known_units):
                errors.append("ANSWER planning evidence binding is incomplete")
    return errors


def default_connected_scenarios() -> list[ConnectedScenarioV1]:
    """Return bounded contract cases, not semantic Gold for Canonical cases."""

    return [
        {
            "scenario_id": "SIMPLE_READ",
            "work_unit_ids": ["work-1"],
            "source_responsibilities": [
                {
                    "resource_type": "GMAIL_THREAD",
                    "required_information": ["requested message facts"],
                    "target_scope": "CRITERIA",
                    "work_unit_ids": ["work-1"],
                }
            ],
            "output_responsibilities": [],
            "expected": {
                "provider_read_count": 1,
                "output_route_count": 0,
                "answer_planning_input_count": 1,
                "planning_specification_count": 0,
            },
        },
        {
            "scenario_id": "SHARED_READ_MULTI_WORK_ANSWER",
            "work_unit_ids": ["work-1", "work-2"],
            "source_responsibilities": [
                {
                    "resource_type": "GMAIL_THREAD",
                    "required_information": ["facts used by both requested answer parts"],
                    "target_scope": "CRITERIA",
                    "work_unit_ids": ["work-1", "work-2"],
                }
            ],
            "output_responsibilities": [],
            "expected": {
                "provider_read_count": 1,
                "output_route_count": 0,
                "answer_planning_input_count": 1,
                "planning_specification_count": 0,
            },
        },
        {
            "scenario_id": "SHARED_READ_TWO_WORK_UNITS",
            "work_unit_ids": ["work-1", "work-2"],
            "source_responsibilities": [
                {
                    "resource_type": "GMAIL_THREAD",
                    "required_information": ["facts used by both requested outcomes"],
                    "target_scope": "CRITERIA",
                    "work_unit_ids": ["work-1", "work-2"],
                }
            ],
            "output_responsibilities": [
                {
                    "resource_type": "GITHUB_ISSUE",
                    "effect": "CREATE",
                    "work_unit_ids": ["work-2"],
                }
            ],
            "expected": {
                "provider_read_count": 1,
                "output_capability_selection_count": 1,
                "output_route_count": 1,
                "planning_specification_count": 1,
            },
        },
        {
            "scenario_id": "DISTINCT_RESULTS_SAME_WRITE_CAPABILITY",
            "work_unit_ids": ["work-1", "work-2"],
            "source_responsibilities": [],
            "output_responsibilities": [
                {
                    "resource_type": "GITHUB_ISSUE",
                    "effect": "CREATE",
                    "work_unit_ids": ["work-1"],
                },
                {
                    "resource_type": "GITHUB_ISSUE",
                    "effect": "CREATE",
                    "work_unit_ids": ["work-2"],
                },
            ],
            "expected": {
                "provider_read_count": 0,
                "output_capability_selection_count": 1,
                "output_route_count": 2,
                "planning_specification_count": 2,
            },
        },
        {
            "scenario_id": "SHARED_AND_DISTINCT_CAPABILITIES",
            "work_unit_ids": ["work-1", "work-2", "work-3"],
            "source_responsibilities": [
                {
                    "resource_type": "GMAIL_THREAD",
                    "required_information": ["message facts"],
                    "target_scope": "CRITERIA",
                    "work_unit_ids": ["work-1", "work-2"],
                },
                {
                    "resource_type": "TASK",
                    "required_information": ["current task state"],
                    "target_scope": "SINGULAR",
                    "work_unit_ids": ["work-3"],
                },
            ],
            "output_responsibilities": [
                {
                    "resource_type": "GMAIL_DRAFT",
                    "effect": "CREATE",
                    "work_unit_ids": ["work-2"],
                },
                {
                    "resource_type": "TASK",
                    "effect": "UPDATE",
                    "work_unit_ids": ["work-3"],
                },
            ],
            "expected": {
                "provider_read_count": 2,
                "output_capability_selection_count": 2,
                "output_route_count": 2,
                "planning_specification_count": 2,
            },
        },
    ]


def default_tool_bindings() -> dict[tuple[str, str], ToolBindingV1]:
    return {
        ("GMAIL_THREAD", "READ"): {
            "connector_id": "google_workspace",
            "tool_id": "gmail_search_threads",
        },
        ("TASK", "READ"): {
            "connector_id": "google_workspace",
            "tool_id": "tasks_get_task",
        },
        ("GITHUB_ISSUE", "CREATE"): {
            "connector_id": "github",
            "tool_id": "github_create_issue",
        },
        ("GMAIL_DRAFT", "CREATE"): {
            "connector_id": "google_workspace",
            "tool_id": "gmail_create_draft",
        },
        ("TASK", "UPDATE"): {
            "connector_id": "google_workspace",
            "tool_id": "tasks_update_task",
        },
    }


def _project_input_routes(
    items: Sequence[WorkBoundSourceResponsibilityV1],
    *,
    tool_bindings: Mapping[tuple[str, str], ToolBindingV1],
) -> list[WorkBoundInputRouteV1]:
    grouped: dict[str, list[WorkBoundSourceResponsibilityV1]] = defaultdict(list)
    for item in items:
        grouped[item["resource_type"]].append(item)
    routes: list[WorkBoundInputRouteV1] = []
    for index, resource_type in enumerate(sorted(grouped), start=1):
        binding = _tool_binding(tool_bindings, resource_type, "READ")
        owner_items = grouped[resource_type]
        routes.append(
            {
                "route_id": f"input-{index}",
                "resource_type": resource_type,
                "connector_id": binding["connector_id"],
                "allowed_read_tool_ids": [binding["tool_id"]],
                "required": True,
                "work_unit_ids": _stable_union(item["work_unit_ids"] for item in owner_items),
            }
        )
    return routes


def _project_output_routes(
    items: Sequence[WorkBoundOutputResponsibilityV1],
    *,
    tool_bindings: Mapping[tuple[str, str], ToolBindingV1],
) -> list[WorkBoundOutputRouteV1]:
    routes: list[WorkBoundOutputRouteV1] = []
    for index, item in enumerate(items, start=1):
        binding = _tool_binding(tool_bindings, item["resource_type"], item["effect"])
        routes.append(
            {
                "route_id": f"output-{index}",
                "resource_type": item["resource_type"],
                "connector_id": binding["connector_id"],
                "effect": item["effect"],
                "selected_tool_id": binding["tool_id"],
                "work_unit_ids": list(item["work_unit_ids"]),
            }
        )
    return routes


def _source_items(value: object, *, known_units: set[str]) -> list[WorkBoundSourceResponsibilityV1]:
    result: list[WorkBoundSourceResponsibilityV1] = []
    seen: set[tuple[object, ...]] = set()
    for index, raw in enumerate(_mapping_list(value, "source_responsibilities")):
        resource_type = _text(raw.get("resource_type"), f"source[{index}].resource_type")
        information = _unique_strings(
            raw.get("required_information"), f"source[{index}].required_information"
        )
        target_scope = _text(raw.get("target_scope"), f"source[{index}].target_scope")
        if target_scope not in {"SINGULAR", "CRITERIA"}:
            raise ValueError(f"source[{index}].target_scope is invalid")
        unit_ids = _validated_refs(raw.get("work_unit_ids"), known_units, f"source[{index}]")
        identity = (resource_type, tuple(information), target_scope, tuple(unit_ids))
        if identity in seen:
            raise ValueError(f"source[{index}] duplicates an owner item")
        seen.add(identity)
        result.append(
            {
                "resource_type": resource_type,
                "required_information": information,
                "target_scope": cast(Literal["SINGULAR", "CRITERIA"], target_scope),
                "work_unit_ids": unit_ids,
            }
        )
    return result


def _output_items(value: object, *, known_units: set[str]) -> list[WorkBoundOutputResponsibilityV1]:
    result: list[WorkBoundOutputResponsibilityV1] = []
    seen: set[tuple[object, ...]] = set()
    for index, raw in enumerate(_mapping_list(value, "output_responsibilities")):
        effect = _text(raw.get("effect"), f"output[{index}].effect")
        if effect not in {"CREATE", "UPDATE", "SEND", "DELETE"}:
            raise ValueError(f"output[{index}].effect is invalid")
        resource_type = _text(raw.get("resource_type"), f"output[{index}].resource_type")
        unit_ids = _validated_refs(raw.get("work_unit_ids"), known_units, f"output[{index}]")
        identity = (resource_type, effect, tuple(unit_ids))
        if identity in seen:
            raise ValueError(f"output[{index}] duplicates an owner item")
        seen.add(identity)
        result.append(
            {
                "resource_type": resource_type,
                "effect": cast(WriteEffect, effect),
                "work_unit_ids": unit_ids,
            }
        )
    return result


def _validated_refs(value: object, known: set[str], path: str) -> list[str]:
    refs = _unique_strings(value, f"{path}.work_unit_ids")
    unknown = sorted(set(refs) - known)
    if unknown:
        raise ValueError(f"{path}.work_unit_ids contains unknown IDs: {unknown}")
    return refs


def _tool_binding(
    bindings: Mapping[tuple[str, str], ToolBindingV1], resource_type: str, effect: str
) -> ToolBindingV1:
    try:
        return bindings[(resource_type, effect)]
    except KeyError as error:
        raise ValueError(f"no tool binding for {resource_type}/{effect}") from error


def _stable_union(groups: Iterable[Iterable[str]]) -> list[str]:
    result: list[str] = []
    for group in groups:
        for value in group:
            if value not in result:
                result.append(value)
    return result


def _mapping_list(value: object, path: str) -> list[Mapping[str, object]]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise TypeError(f"{path} must be a sequence")
    if not all(isinstance(item, Mapping) for item in value):
        raise TypeError(f"{path} must contain objects")
    return [cast(Mapping[str, object], item) for item in value]


def _unique_strings(value: object, path: str) -> list[str]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise TypeError(f"{path} must be a sequence")
    result: list[str] = []
    for item in value:
        text = _text(item, path)
        if text in result:
            raise ValueError(f"{path} contains duplicate {text!r}")
        result.append(text)
    if not result and path == "work_unit_ids":
        raise ValueError("work_unit_ids must not be empty")
    return result


def _text(value: object, path: str) -> str:
    if not isinstance(value, str) or not value:
        raise TypeError(f"{path} must be a non-empty string")
    return value


__all__ = [
    "ConnectedScenarioV1",
    "default_connected_scenarios",
    "default_tool_bindings",
    "project_connected_handoff",
    "validate_connected_handoff",
]
