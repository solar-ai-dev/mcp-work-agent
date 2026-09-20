"""Evaluation-only compiled candidate for connected requested work.

The candidate deliberately separates the user's requested work definition from
same-run derived work products and pre-execution action specifications.  It is
not imported by Product runtime and it never dispatches an external write.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Literal, Protocol, TypedDict, cast

from langgraph.graph import END, START, StateGraph


class ConstraintProjectionV1(TypedDict):
    constraint_ref: str
    kind: str
    field: str
    value: str | list[str]


class WorkConditionRefV1(TypedDict):
    constraint_ref: str


class ResourceInputBindingV1(TypedDict):
    kind: Literal["RESOURCE"]
    resource_type: str
    required_information: list[str]


class WorkProductInputBindingV1(TypedDict):
    kind: Literal["WORK_PRODUCT"]
    product_ref: str


class PlannedSpecificationInputBindingV1(TypedDict):
    kind: Literal["PLANNED_SPECIFICATION"]
    specification_ref: str


WorkInputBindingV1 = (
    ResourceInputBindingV1 | WorkProductInputBindingV1 | PlannedSpecificationInputBindingV1
)


class UserResponseOutputV1(TypedDict):
    kind: Literal["USER_RESPONSE"]


class IntermediateWorkProductOutputV1(TypedDict):
    kind: Literal["INTERMEDIATE_WORK_PRODUCT"]
    product_ref: str
    product_kind: Literal["SUMMARY", "ANALYSIS", "CONTENT"]


class ExternalActionSpecificationOutputV1(TypedDict):
    kind: Literal["EXTERNAL_ACTION_SPECIFICATION"]
    specification_ref: str
    resource_type: str
    effect: Literal["CREATE", "UPDATE", "SEND", "DELETE"]


WorkOutputDefinitionV1 = (
    UserResponseOutputV1 | IntermediateWorkProductOutputV1 | ExternalActionSpecificationOutputV1
)


class RequestedWorkUnitV1(TypedDict):
    unit_id: str
    objective: str
    operation: Literal["ANSWER", "SUMMARIZE", "ANALYZE", "COMPOSE", "PREPARE_ACTION"]
    input_bindings: list[WorkInputBindingV1]
    condition_refs: list[WorkConditionRefV1]
    output: WorkOutputDefinitionV1


class RequestedWorkRelationV1(TypedDict):
    relation_id: str
    kind: Literal["CONSUMES_WORK_PRODUCT", "CONSUMES_PLANNED_SPECIFICATION"]
    source_unit_id: str
    target_unit_id: str
    artifact_ref: str


class RequestedWorkDefinitionV1(TypedDict):
    schema_version: Literal[1]
    common_condition_refs: list[WorkConditionRefV1]
    work_units: list[RequestedWorkUnitV1]
    relations: list[RequestedWorkRelationV1]


class EvidenceProjectionV1(TypedDict):
    evidence_ref: str
    resource_type: str
    content: str


class IntermediateWorkProductV1(TypedDict):
    schema_version: Literal[1]
    product_ref: str
    producer_work_unit_id: str
    producer_boundary: Literal["INTERMEDIATE_WORK_PRODUCT_MATERIALIZER"]
    product_kind: Literal["SUMMARY", "ANALYSIS", "CONTENT"]
    content: str
    evidence_refs: list[str]
    consumed_product_refs: list[str]


class PlannedActionSpecificationV1(TypedDict):
    schema_version: Literal[1]
    specification_ref: str
    producer_work_unit_id: str
    resource_type: str
    effect: Literal["CREATE", "UPDATE", "SEND", "DELETE"]
    status: Literal["PLANNED_NOT_EXECUTED"]
    content: dict[str, object]
    consumed_product_refs: list[str]
    consumed_specification_refs: list[str]


class UserResponseCandidateV1(TypedDict):
    schema_version: Literal[1]
    producer_work_unit_id: str
    content: str
    consumed_product_refs: list[str]


class ConnectedWorkCandidateState(TypedDict, total=False):
    user_request: str
    constraint_catalog: list[ConstraintProjectionV1]
    evidence: list[EvidenceProjectionV1]
    work_definition: RequestedWorkDefinitionV1
    intermediate_work_products: list[IntermediateWorkProductV1]
    planned_action_specifications: list[PlannedActionSpecificationV1]
    user_responses: list[UserResponseCandidateV1]
    external_write_count: int


class WorkDefinitionInvoker(Protocol):
    def __call__(
        self,
        user_request: str,
    ) -> Mapping[str, object]: ...


class WorkProductInvoker(Protocol):
    def __call__(
        self,
        work_unit: RequestedWorkUnitV1,
        evidence: Sequence[EvidenceProjectionV1],
        upstream_products: Sequence[IntermediateWorkProductV1],
        conditions: Sequence[ConstraintProjectionV1],
    ) -> Mapping[str, object]: ...


class WorkConsumerInvoker(Protocol):
    def __call__(
        self,
        work_unit: RequestedWorkUnitV1,
        evidence: Sequence[EvidenceProjectionV1],
        work_products: Sequence[IntermediateWorkProductV1],
        planned_specifications: Sequence[PlannedActionSpecificationV1],
        conditions: Sequence[ConstraintProjectionV1],
    ) -> Mapping[str, object]: ...


def compile_connected_work_candidate(
    *,
    define_work: WorkDefinitionInvoker,
    materialize_product: WorkProductInvoker,
    consume_work: WorkConsumerInvoker,
) -> object:
    """Compile the bounded candidate without Product runtime side effects."""

    def define_node(state: ConnectedWorkCandidateState) -> ConnectedWorkCandidateState:
        definition = _validate_work_definition(
            define_work(state["user_request"]),
            constraint_catalog=state.get("constraint_catalog", []),
        )
        return {"work_definition": definition, "external_write_count": 0}

    def materialize_node(state: ConnectedWorkCandidateState) -> ConnectedWorkCandidateState:
        definition = state["work_definition"]
        products: list[IntermediateWorkProductV1] = []
        evidence = state.get("evidence", [])
        constraint_catalog = state.get("constraint_catalog", [])
        units_by_id = {unit["unit_id"]: unit for unit in definition["work_units"]}
        for unit_id in _topological_unit_ids(definition):
            unit = units_by_id[unit_id]
            output = unit["output"]
            if output["kind"] != "INTERMEDIATE_WORK_PRODUCT":
                continue
            resource_types = {
                binding["resource_type"]
                for binding in unit["input_bindings"]
                if binding["kind"] == "RESOURCE"
            }
            projected_evidence = [
                item for item in evidence if item["resource_type"] in resource_types
            ]
            product_refs = {
                binding["product_ref"]
                for binding in unit["input_bindings"]
                if binding["kind"] == "WORK_PRODUCT"
            }
            upstream = [item for item in products if item["product_ref"] in product_refs]
            if resource_types and not projected_evidence:
                raise ValueError(f"{unit_id}: no evidence matches the requested Resource inputs")
            if len(upstream) != len(product_refs):
                raise ValueError(f"{unit_id}: an upstream work product has not been materialized")
            conditions = _project_conditions(
                definition,
                unit=unit,
                constraint_catalog=constraint_catalog,
            )
            candidate = materialize_product(unit, projected_evidence, upstream, conditions)
            product = _validate_intermediate_product(
                candidate,
                unit=unit,
                evidence=projected_evidence,
                upstream_products=upstream,
            )
            products.append(product)
        return {"intermediate_work_products": products, "external_write_count": 0}

    def consume_node(state: ConnectedWorkCandidateState) -> ConnectedWorkCandidateState:
        definition = state["work_definition"]
        evidence = state.get("evidence", [])
        products = state.get("intermediate_work_products", [])
        constraint_catalog = state.get("constraint_catalog", [])
        planned: list[PlannedActionSpecificationV1] = []
        responses: list[UserResponseCandidateV1] = []
        units_by_id = {unit["unit_id"]: unit for unit in definition["work_units"]}
        for unit_id in _topological_unit_ids(definition):
            unit = units_by_id[unit_id]
            output = unit["output"]
            if output["kind"] == "INTERMEDIATE_WORK_PRODUCT":
                continue
            product_refs = {
                binding["product_ref"]
                for binding in unit["input_bindings"]
                if binding["kind"] == "WORK_PRODUCT"
            }
            specification_refs = {
                binding["specification_ref"]
                for binding in unit["input_bindings"]
                if binding["kind"] == "PLANNED_SPECIFICATION"
            }
            consumed_products = [item for item in products if item["product_ref"] in product_refs]
            consumed_specs = [
                item for item in planned if item["specification_ref"] in specification_refs
            ]
            if len(consumed_products) != len(product_refs):
                raise ValueError(f"{unit_id}: a required work product is unavailable")
            if len(consumed_specs) != len(specification_refs):
                raise ValueError(f"{unit_id}: a required planned specification is unavailable")
            resource_types = {
                binding["resource_type"]
                for binding in unit["input_bindings"]
                if binding["kind"] == "RESOURCE"
            }
            projected_evidence = [
                item for item in evidence if item["resource_type"] in resource_types
            ]
            candidate = consume_work(
                unit,
                projected_evidence,
                consumed_products,
                consumed_specs,
                _project_conditions(
                    definition,
                    unit=unit,
                    constraint_catalog=constraint_catalog,
                ),
            )
            if output["kind"] == "EXTERNAL_ACTION_SPECIFICATION":
                planned.append(_validate_planned_specification(candidate, unit=unit))
            else:
                responses.append(_validate_user_response(candidate, unit=unit))
        return {
            "planned_action_specifications": planned,
            "user_responses": responses,
            "external_write_count": 0,
        }

    graph = StateGraph(ConnectedWorkCandidateState)
    graph.add_node("define_requested_work", define_node)
    graph.add_node("materialize_intermediate_work_products", materialize_node)
    graph.add_node("consume_bound_work_products", consume_node)
    graph.add_edge(START, "define_requested_work")
    graph.add_edge("define_requested_work", "materialize_intermediate_work_products")
    graph.add_edge("materialize_intermediate_work_products", "consume_bound_work_products")
    graph.add_edge("consume_bound_work_products", END)
    return graph.compile(name="connected_work_candidate")


def _validate_work_definition(
    candidate: Mapping[str, object],
    *,
    constraint_catalog: Sequence[ConstraintProjectionV1],
) -> RequestedWorkDefinitionV1:
    if candidate.get("schema_version") != 1:
        raise ValueError("requested work definition schema_version must be 1")
    raw_units = candidate.get("work_units")
    raw_relations = candidate.get("relations")
    raw_common = candidate.get("common_condition_refs")
    if not isinstance(raw_units, list) or not raw_units:
        raise ValueError("requested work definition requires at least one work unit")
    if not isinstance(raw_relations, list) or not isinstance(raw_common, list):
        raise ValueError("requested work relations and common condition refs must be lists")
    units = cast(list[RequestedWorkUnitV1], raw_units)
    relations = cast(list[RequestedWorkRelationV1], raw_relations)
    common = cast(list[WorkConditionRefV1], raw_common)
    unit_ids = [unit.get("unit_id") for unit in units]
    if any(not isinstance(unit_id, str) or not unit_id for unit_id in unit_ids):
        raise ValueError("every work unit requires an id")
    if len(unit_ids) != len(set(unit_ids)):
        raise ValueError("work unit ids must be unique")
    catalog_refs = [item.get("constraint_ref") for item in constraint_catalog]
    if any(not isinstance(ref, str) or not ref for ref in catalog_refs):
        raise ValueError("constraint catalog refs must be non-empty")
    if len(catalog_refs) != len(set(catalog_refs)):
        raise ValueError("constraint catalog refs must be unique")
    known_refs = set(cast(list[str], catalog_refs))
    for condition in [
        *common,
        *(item for unit in units for item in unit.get("condition_refs", [])),
    ]:
        if condition.get("constraint_ref") not in known_refs:
            raise ValueError("work condition must reference the current constraint catalog")

    product_owner: dict[str, str] = {}
    specification_owner: dict[str, str] = {}
    for unit in units:
        if not isinstance(unit.get("objective"), str) or not unit["objective"]:
            raise ValueError("every work unit requires an objective")
        if not isinstance(unit.get("input_bindings"), list) or not isinstance(
            unit.get("condition_refs"), list
        ):
            raise ValueError("work unit inputs and conditions must be lists")
        output = unit.get("output")
        if not isinstance(output, Mapping):
            raise ValueError("every work unit requires one typed output")
        kind = output.get("kind")
        if kind == "INTERMEDIATE_WORK_PRODUCT":
            if unit.get("operation") not in {"SUMMARIZE", "ANALYZE", "COMPOSE"}:
                raise ValueError("intermediate products require a materializing operation")
            ref = output.get("product_ref")
            if not isinstance(ref, str) or not ref or ref in product_owner:
                raise ValueError("intermediate product refs must be non-empty and unique")
            product_owner[ref] = unit["unit_id"]
        elif kind == "EXTERNAL_ACTION_SPECIFICATION":
            if unit.get("operation") != "PREPARE_ACTION":
                raise ValueError("external specifications require PREPARE_ACTION")
            ref = output.get("specification_ref")
            if not isinstance(ref, str) or not ref or ref in specification_owner:
                raise ValueError("planned specification refs must be non-empty and unique")
            specification_owner[ref] = unit["unit_id"]
        elif kind != "USER_RESPONSE":
            raise ValueError("unsupported requested work output kind")
        elif unit.get("operation") != "ANSWER":
            raise ValueError("user responses require ANSWER")

    expected_relations: set[tuple[str, str, str, str]] = set()
    for unit in units:
        for binding in unit["input_bindings"]:
            kind = binding.get("kind")
            if kind == "WORK_PRODUCT":
                ref = binding.get("product_ref")
                owner = product_owner.get(cast(str, ref))
                relation_kind = "CONSUMES_WORK_PRODUCT"
            elif kind == "PLANNED_SPECIFICATION":
                ref = binding.get("specification_ref")
                owner = specification_owner.get(cast(str, ref))
                relation_kind = "CONSUMES_PLANNED_SPECIFICATION"
            elif kind == "RESOURCE":
                if not isinstance(binding.get("resource_type"), str):
                    raise ValueError("Resource input requires resource_type")
                continue
            else:
                raise ValueError("unsupported work input binding kind")
            if not isinstance(ref, str) or owner is None or owner == unit["unit_id"]:
                raise ValueError("work input artifact ref must identify another work unit output")
            expected_relations.add((relation_kind, owner, unit["unit_id"], ref))

    actual_relations: set[tuple[str, str, str, str]] = set()
    relation_ids: set[str] = set()
    for relation in relations:
        relation_id = relation.get("relation_id")
        if not isinstance(relation_id, str) or not relation_id or relation_id in relation_ids:
            raise ValueError("work relation ids must be non-empty and unique")
        relation_ids.add(relation_id)
        actual_relations.add(
            (
                relation["kind"],
                relation["source_unit_id"],
                relation["target_unit_id"],
                relation["artifact_ref"],
            )
        )
    if actual_relations != expected_relations:
        raise ValueError("work relations must exactly match artifact input bindings")
    definition = cast(
        RequestedWorkDefinitionV1,
        {
            "schema_version": 1,
            "common_condition_refs": common,
            "work_units": units,
            "relations": relations,
        },
    )
    _topological_unit_ids(definition)
    return definition


def _topological_unit_ids(definition: RequestedWorkDefinitionV1) -> list[str]:
    ordered_ids = [unit["unit_id"] for unit in definition["work_units"]]
    dependencies = {unit_id: set() for unit_id in ordered_ids}
    for relation in definition["relations"]:
        dependencies[relation["target_unit_id"]].add(relation["source_unit_id"])
    result: list[str] = []
    remaining = set(ordered_ids)
    while remaining:
        ready = [
            unit_id for unit_id in ordered_ids if unit_id in remaining and not dependencies[unit_id]
        ]
        if not ready:
            raise ValueError("requested work relations must be acyclic")
        for unit_id in ready:
            result.append(unit_id)
            remaining.remove(unit_id)
            for dependency_set in dependencies.values():
                dependency_set.discard(unit_id)
    return result


def _validate_intermediate_product(
    candidate: Mapping[str, object],
    *,
    unit: RequestedWorkUnitV1,
    evidence: Sequence[EvidenceProjectionV1],
    upstream_products: Sequence[IntermediateWorkProductV1],
) -> IntermediateWorkProductV1:
    output = cast(IntermediateWorkProductOutputV1, unit["output"])
    if (
        candidate.get("schema_version") != 1
        or candidate.get("product_ref") != output["product_ref"]
        or candidate.get("producer_work_unit_id") != unit["unit_id"]
        or candidate.get("producer_boundary") != "INTERMEDIATE_WORK_PRODUCT_MATERIALIZER"
        or candidate.get("product_kind") != output["product_kind"]
        or not isinstance(candidate.get("content"), str)
        or not candidate["content"]
        or not isinstance(candidate.get("evidence_refs"), list)
        or not isinstance(candidate.get("consumed_product_refs"), list)
    ):
        raise ValueError(f"{unit['unit_id']}: invalid intermediate work product")
    evidence_refs = cast(list[object], candidate["evidence_refs"])
    consumed_refs = cast(list[object], candidate["consumed_product_refs"])
    allowed_evidence_refs = {item["evidence_ref"] for item in evidence}
    expected_product_refs = {item["product_ref"] for item in upstream_products}
    if (
        not all(isinstance(item, str) for item in evidence_refs)
        or not all(isinstance(item, str) for item in consumed_refs)
        or len(evidence_refs) != len(set(evidence_refs))
        or not set(evidence_refs).issubset(allowed_evidence_refs)
        or len(consumed_refs) != len(set(consumed_refs))
        or set(consumed_refs) != expected_product_refs
    ):
        raise ValueError(f"{unit['unit_id']}: invalid intermediate work product lineage")
    return cast(IntermediateWorkProductV1, dict(candidate))


def _project_conditions(
    definition: RequestedWorkDefinitionV1,
    *,
    unit: RequestedWorkUnitV1,
    constraint_catalog: Sequence[ConstraintProjectionV1],
) -> list[ConstraintProjectionV1]:
    refs = {
        item["constraint_ref"]
        for item in [*definition["common_condition_refs"], *unit["condition_refs"]]
    }
    return [item for item in constraint_catalog if item["constraint_ref"] in refs]


def _validate_planned_specification(
    candidate: Mapping[str, object],
    *,
    unit: RequestedWorkUnitV1,
) -> PlannedActionSpecificationV1:
    output = cast(ExternalActionSpecificationOutputV1, unit["output"])
    if (
        candidate.get("schema_version") != 1
        or candidate.get("specification_ref") != output["specification_ref"]
        or candidate.get("producer_work_unit_id") != unit["unit_id"]
        or candidate.get("resource_type") != output["resource_type"]
        or candidate.get("effect") != output["effect"]
        or candidate.get("status") != "PLANNED_NOT_EXECUTED"
        or not isinstance(candidate.get("content"), Mapping)
        or not isinstance(candidate.get("consumed_product_refs"), list)
        or not isinstance(candidate.get("consumed_specification_refs"), list)
    ):
        raise ValueError(f"{unit['unit_id']}: invalid planned action specification")
    expected_products = {
        binding["product_ref"]
        for binding in unit["input_bindings"]
        if binding["kind"] == "WORK_PRODUCT"
    }
    expected_specifications = {
        binding["specification_ref"]
        for binding in unit["input_bindings"]
        if binding["kind"] == "PLANNED_SPECIFICATION"
    }
    product_refs = cast(list[object], candidate["consumed_product_refs"])
    specification_refs = cast(list[object], candidate["consumed_specification_refs"])
    if (
        not all(isinstance(item, str) for item in [*product_refs, *specification_refs])
        or set(product_refs) != expected_products
        or set(specification_refs) != expected_specifications
    ):
        raise ValueError(f"{unit['unit_id']}: planned specification lineage mismatch")
    return cast(PlannedActionSpecificationV1, dict(candidate))


def _validate_user_response(
    candidate: Mapping[str, object],
    *,
    unit: RequestedWorkUnitV1,
) -> UserResponseCandidateV1:
    if (
        candidate.get("schema_version") != 1
        or candidate.get("producer_work_unit_id") != unit["unit_id"]
        or not isinstance(candidate.get("content"), str)
        or not candidate["content"]
        or not isinstance(candidate.get("consumed_product_refs"), list)
    ):
        raise ValueError(f"{unit['unit_id']}: invalid user response")
    expected_products = {
        binding["product_ref"]
        for binding in unit["input_bindings"]
        if binding["kind"] == "WORK_PRODUCT"
    }
    product_refs = cast(list[object], candidate["consumed_product_refs"])
    if (
        not all(isinstance(item, str) for item in product_refs)
        or set(product_refs) != expected_products
    ):
        raise ValueError(f"{unit['unit_id']}: user response lineage mismatch")
    return cast(UserResponseCandidateV1, dict(candidate))


__all__ = [
    "ConnectedWorkCandidateState",
    "ConstraintProjectionV1",
    "EvidenceProjectionV1",
    "IntermediateWorkProductV1",
    "PlannedActionSpecificationV1",
    "RequestedWorkDefinitionV1",
    "RequestedWorkUnitV1",
    "compile_connected_work_candidate",
]
