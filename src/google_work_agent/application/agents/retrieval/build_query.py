"""Canonical Retrieval deterministic operation: build_query."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Collection, Mapping, Sequence
from copy import deepcopy
from dataclasses import dataclass
from typing import cast

from google_work_agent.application.agents.retrieval.contracts.query_attempt import QueryAttemptV1
from google_work_agent.application.agents.retrieval.contracts.query_plan import (
    ProtectedConstraintsByRouteV1,
    RetrievalConstraintKindV1,
    RetrievalV2ValidationError,
    RouteQueryIntentV2,
    SemanticRetrievalConstraintV1,
    SourceFetchPlanV1,
    validate_retrieval_query_plan_v2,
)
from google_work_agent.application.agents.retrieval.contracts.retrieval_result import (
    PersonCandidateV1,
)
from google_work_agent.application.agents.tool_routing.contracts.tool_route_plan import (
    InputToolRouteV1,
)
from google_work_agent.ports.connector.connector_read_port import JsonValue


class QueryUnchangedAfterFailureError(RetrievalV2ValidationError):
    """A changed SEARCH would repeat an already-failed effective query."""


@dataclass(frozen=True, slots=True)
class RouteConstraintPolicy:
    supported_kinds: frozenset[RetrievalConstraintKindV1]
    required_kinds: frozenset[RetrievalConstraintKindV1] = frozenset()


def build_query(
    plan: object,
    *,
    frozen_routes: Sequence[InputToolRouteV1],
    route_policies: Mapping[str, RouteConstraintPolicy],
    prior_plans: Mapping[str, SourceFetchPlanV1] | None = None,
    prior_read_result_handles: Mapping[str, str] | None = None,
    validated_resource_refs: Mapping[str, Collection[str]] | None = None,
    validated_container_refs: Mapping[str, Collection[str]] | None = None,
    detail_candidate_refs: Collection[str] = (),
    person_candidates: Sequence[PersonCandidateV1] = (),
    selected_person_identities: Mapping[str, str] | None = None,
    read_result_summaries: Sequence[Mapping[str, object]] | None = None,
    protected_constraints_by_route: ProtectedConstraintsByRouteV1 | None = None,
) -> list[SourceFetchPlanV1]:
    """Validate/merge semantic constraints and materialize deterministic read plans."""
    prior_plans = prior_plans or {}
    prior_read_result_handles = prior_read_result_handles or {}
    protected_constraints_by_route = protected_constraints_by_route or {}
    route_by_id = {route["route_id"]: route for route in frozen_routes}
    _validate_policies(route_by_id, route_policies)
    bound_plan = bind_required_container_constraints(
        plan,
        route_policies=route_policies,
        validated_container_refs=validated_container_refs,
    )
    validated = validate_retrieval_query_plan_v2(
        bound_plan,
        frozen_routes=frozen_routes,
        supported_constraint_kinds={
            route_id: policy.supported_kinds for route_id, policy in route_policies.items()
        },
        validated_resource_refs=validated_resource_refs,
        validated_container_refs=validated_container_refs,
        detail_candidate_refs=detail_candidate_refs,
    )
    query_by_route = {query["route_id"]: query for query in validated["route_queries"]}
    return [
        _build_one(
            query_by_route[route_id],
            route=route_by_id[route_id],
            policy=route_policies[route_id],
            prior_plan=prior_plans.get(route_id),
            prior_read_result_handle=prior_read_result_handles.get(route_id),
            person_candidates=(
                person_candidates
                if route_by_id[route_id]["resource_type"]
                in {
                    "GMAIL_THREAD",
                    "GMAIL_MESSAGE",
                }
                else ()
            ),
            selected_person_identities=selected_person_identities or {},
            read_result_summaries=read_result_summaries,
            protected_constraints=protected_constraints_by_route.get(route_id, ()),
        )
        for route_id in (query["route_id"] for query in validated["route_queries"])
    ]


def bind_required_container_constraints(
    plan: object,
    *,
    route_policies: Mapping[str, RouteConstraintPolicy],
    validated_container_refs: Mapping[str, Collection[str]] | None,
) -> object:
    """Inject only a pre-validated required container into INITIAL SEARCH."""
    if not isinstance(plan, Mapping):
        return plan
    bound = deepcopy(dict(plan))
    queries = bound.get("route_queries")
    if not isinstance(queries, list):
        return bound
    for raw_query in queries:
        if not isinstance(raw_query, dict):
            continue
        route_id = raw_query.get("route_id")
        if not isinstance(route_id, str):
            continue
        policy = route_policies.get(route_id)
        if (
            policy is None
            or "CONTAINER_REF" not in policy.required_kinds
            or raw_query.get("operation") != "SEARCH"
        ):
            continue
        refs = list(dict.fromkeys((validated_container_refs or {}).get(route_id, ())))
        if len(refs) != 1:
            raise RetrievalV2ValidationError(
                f"route {route_id} requires one validated container authority"
            )
        search_spec = raw_query.get("search_spec")
        if not isinstance(search_spec, dict) or search_spec.get("mode") != "INITIAL":
            continue
        constraints = search_spec.get("constraints")
        if not isinstance(constraints, list):
            continue
        if not any(
            isinstance(constraint, Mapping) and constraint.get("kind") == "CONTAINER_REF"
            for constraint in constraints
        ):
            constraints.append({"kind": "CONTAINER_REF", "container_refs": refs})
    return bound


def _build_one(
    query: RouteQueryIntentV2,
    *,
    route: InputToolRouteV1,
    policy: RouteConstraintPolicy,
    prior_plan: SourceFetchPlanV1 | None,
    prior_read_result_handle: str | None,
    person_candidates: Sequence[PersonCandidateV1],
    selected_person_identities: Mapping[str, str],
    read_result_summaries: Sequence[Mapping[str, object]] | None,
    protected_constraints: Sequence[SemanticRetrievalConstraintV1],
) -> SourceFetchPlanV1:
    operation = query["operation"]
    if operation in {"SEARCH", "FREEBUSY"}:
        _validate_changed_removals(
            query,
            policy=policy,
            prior_plan=prior_plan,
            protected_constraints=protected_constraints,
        )
    effective = (
        _effective_constraints(query, policy=policy, prior_plan=prior_plan)
        if operation in {"SEARCH", "FREEBUSY"}
        else ([] if prior_plan is None else prior_plan["effective_constraints"])
    )
    if operation in {"SEARCH", "FREEBUSY"}:
        _validate_protected_constraint_continuity(
            protected_constraints,
            effective,
        )
    if prior_plan is not None and operation in {"SEARCH", "FREEBUSY"}:
        _validate_person_promotion(
            prior_plan["effective_constraints"],
            effective,
            person_candidates=person_candidates,
            selected_person_identities=selected_person_identities,
        )
    resource_type = route["resource_type"]
    normalized = _normalize_constraints(effective)
    query_identity = _query_identity(route, operation, normalized, query["detail_candidate_ref"])
    if operation == "NEXT_PAGE" and prior_plan is not None:
        query_identity = (
            _query_identity(route, "SEARCH", normalized, None)
            if prior_plan["operation_kind"] == "DETAIL_FETCH"
            else prior_plan["query_identity_hash"]
        )
        if read_result_summaries is not None:
            pending = [
                summary["read_result_handle"]
                for summary in read_result_summaries
                if summary.get("route_id") == route["route_id"]
                and summary.get("query_identity_hash") == query_identity
                and summary.get("has_next_page") is True
                and summary.get("exhausted") is not True
                and isinstance(summary.get("read_result_handle"), str)
            ]
            prior_read_result_handle = cast(str, pending[-1]) if pending else None
    if operation == "NEXT_PAGE" and prior_read_result_handle is None:
        raise RetrievalV2ValidationError("NEXT_PAGE requires a validated prior read-result handle")
    return {
        "schema_version": 1,
        "route_id": route["route_id"],
        "connector_id": route["connector_id"],
        "resource_type": resource_type,
        "operation_kind": operation,
        "effective_constraints": normalized,
        "query_identity_hash": query_identity,
        "prior_read_result_handle": prior_read_result_handle,
        "detail_candidate_ref": query["detail_candidate_ref"],
    }


def _effective_constraints(
    query: RouteQueryIntentV2,
    *,
    policy: RouteConstraintPolicy,
    prior_plan: SourceFetchPlanV1 | None,
) -> list[SemanticRetrievalConstraintV1]:
    spec = query["search_spec"]
    if spec is None:
        raise RetrievalV2ValidationError("SEARCH/FREEBUSY requires search_spec")
    if spec["mode"] == "INITIAL":
        effective = list(spec["constraints"])
    else:
        if prior_plan is None:
            raise RetrievalV2ValidationError("CHANGED SEARCH requires a prior query")
        delta = spec["constraint_delta"]
        removed = set(delta["remove_constraint_kinds"])
        if policy.required_kinds.intersection(removed):
            raise RetrievalV2ValidationError("CHANGED SEARCH removes a required constraint")
        merged = {c["kind"]: c for c in prior_plan["effective_constraints"]}
        for kind in removed:
            merged.pop(kind, None)
        for constraint in delta["upsert_constraints"]:
            merged[constraint["kind"]] = constraint
        effective = list(merged.values())
        if _canonical_constraints(effective) == _canonical_constraints(
            prior_plan["effective_constraints"]
        ):
            raise QueryUnchangedAfterFailureError("QUERY_UNCHANGED_AFTER_FAILURE")
    kinds = {constraint["kind"] for constraint in effective}
    if not policy.required_kinds.issubset(kinds):
        raise RetrievalV2ValidationError("effective constraints omit a required kind")
    return effective


def _validate_changed_removals(
    query: RouteQueryIntentV2,
    *,
    policy: RouteConstraintPolicy,
    prior_plan: SourceFetchPlanV1 | None,
    protected_constraints: Sequence[SemanticRetrievalConstraintV1],
) -> None:
    spec = query["search_spec"]
    if spec is None or spec["mode"] != "CHANGED":
        return
    if prior_plan is None:
        raise RetrievalV2ValidationError("CHANGED SEARCH requires a prior query")
    removals = set(spec["constraint_delta"]["remove_constraint_kinds"])
    protected_kinds = {item["kind"] for item in protected_constraints}
    if removals.intersection(protected_kinds):
        raise RetrievalV2ValidationError(
            "CHANGED SEARCH removes a protected constraint",
            reason_code="QUERY_PROTECTED_CONSTRAINT_CHANGED",
            affected_field_paths=(
                "$.route_queries[].search_spec.constraint_delta.remove_constraint_kinds",
            ),
        )
    prior_kinds = {item["kind"] for item in prior_plan["effective_constraints"]}
    removable = prior_kinds - policy.required_kinds - protected_kinds
    if not removals.issubset(removable):
        raise RetrievalV2ValidationError(
            "CHANGED SEARCH removes a constraint that is not removable",
            affected_field_paths=(
                "$.route_queries[].search_spec.constraint_delta.remove_constraint_kinds",
            ),
        )


def _validate_protected_constraint_continuity(
    protected: Sequence[SemanticRetrievalConstraintV1],
    effective: Sequence[SemanticRetrievalConstraintV1],
) -> None:
    current = {item["kind"]: item for item in effective}
    for expected in protected:
        actual = current.get(expected["kind"])
        if actual is not None and _canonical_constraints([actual]) == _canonical_constraints(
            [expected]
        ):
            continue
        raise RetrievalV2ValidationError(
            f"SEARCH changes protected {expected['kind']} constraint",
            reason_code="QUERY_PROTECTED_CONSTRAINT_CHANGED",
            affected_field_paths=(
                "$.route_queries[].search_spec.constraint_delta",
                f"$.source_fetch_plans[].effective_constraints[?(@.kind=='{expected['kind']}')]",
            ),
        )


def _validate_person_promotion(
    prior: Sequence[SemanticRetrievalConstraintV1],
    effective: Sequence[SemanticRetrievalConstraintV1],
    *,
    person_candidates: Sequence[PersonCandidateV1],
    selected_person_identities: Mapping[str, str],
) -> None:
    previous_participant = next(
        (item for item in prior if item["kind"] == "PARTICIPANT"),
        None,
    )
    current_participant = next(
        (item for item in effective if item["kind"] == "PARTICIPANT"),
        None,
    )
    if current_participant is None or current_participant["kind"] != "PARTICIPANT":
        return
    previous_identities = (
        set()
        if previous_participant is None or previous_participant["kind"] != "PARTICIPANT"
        else {item["identity"] for item in previous_participant["participants"]}
    )
    added_identities = {
        item["identity"] for item in current_participant["participants"]
    } - previous_identities
    if not added_identities:
        return
    resolved_identities: set[str] = set()
    for mention in {item["mention"] for item in person_candidates}:
        identities = {
            item["identity"]
            for item in person_candidates
            if item["mention"] == mention and item["source_segment_ids"]
        }
        selected = selected_person_identities.get(mention)
        if selected in identities:
            resolved_identities.add(selected)
        elif len(identities) == 1:
            resolved_identities.update(identities)
    if not added_identities.issubset(resolved_identities):
        raise RetrievalV2ValidationError(
            "CHANGED SEARCH promotes a participant without validated evidence",
            reason_code="QUERY_PROTECTED_CONSTRAINT_CHANGED",
            affected_field_paths=(
                "$.route_queries[].search_spec.constraint_delta",
                "$.source_fetch_plans[].effective_constraints[?(@.kind=='PARTICIPANT')]",
            ),
        )


def _validate_policies(
    routes: Mapping[str, InputToolRouteV1],
    policies: Mapping[str, RouteConstraintPolicy],
) -> None:
    if set(routes) != set(policies):
        raise RetrievalV2ValidationError("each frozen route requires exactly one constraint policy")
    for route_id, policy in policies.items():
        if not policy.required_kinds.issubset(policy.supported_kinds):
            raise RetrievalV2ValidationError(f"route {route_id} requires an unsupported constraint")


def _canonical_constraints(constraints: Sequence[SemanticRetrievalConstraintV1]) -> str:
    normalized = []
    for constraint in sorted(constraints, key=lambda item: item["kind"]):
        item = dict(constraint)
        for key, value in item.items():
            if isinstance(value, list):
                item[key] = (
                    list(value)
                    if item.get("kind") == "KEYWORD"
                    and item.get("match_mode") == "PHRASE"
                    and key == "terms"
                    else sorted(
                        value,
                        key=lambda member: json.dumps(
                            member, sort_keys=True, ensure_ascii=True
                        ),
                    )
                )
        normalized.append(item)
    return json.dumps(normalized, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _normalize_constraints(
    constraints: Sequence[SemanticRetrievalConstraintV1],
) -> list[SemanticRetrievalConstraintV1]:
    return cast(
        list[SemanticRetrievalConstraintV1],
        json.loads(_canonical_constraints(constraints)),
    )


def _query_identity(
    route: InputToolRouteV1,
    operation: object,
    constraints: Sequence[SemanticRetrievalConstraintV1],
    detail_candidate_ref: object,
) -> str:
    payload = {
        "connector_id": route["connector_id"],
        "detail_candidate_ref": detail_candidate_ref,
        "effective_constraints": json.loads(_canonical_constraints(constraints)),
        "operation_kind": operation,
        "resource_type": route["resource_type"],
        "route_id": route["route_id"],
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
    ).hexdigest()


# Preserved attempt construction is owned by this query-building operation.

RETRIEVAL_CONFIG_VERSION = "deterministic-retrieval-v3"
SCORE_CONFIG_VERSION = "semantic-signal-score-v2"
THRESHOLD_CONFIG_VERSION = "selection-threshold-v1"


def build_query_attempt(
    *,
    query_attempt_id: str,
    run_id: str,
    plan: SourceFetchPlanV1,
    round_no: int,
    attempt_no: int,
    tool_id: str,
    canonical_arguments: Mapping[str, JsonValue],
    previous_query_hash: str | None,
    page_state_hash: str | None,
    candidate_count: int | None,
    stop_reason: str | None,
    prior_query_attempts: Sequence[QueryAttemptV1],
    change_reason_code: str | None,
) -> QueryAttemptV1:
    """Record validated read meaning without raw provider continuation."""
    previous = next(
        (
            attempt
            for attempt in reversed(prior_query_attempts)
            if attempt["run_id"] == run_id and attempt["route_id"] == plan["route_id"]
        ),
        None,
    )
    previous_constraints = {
        item["kind"]: item
        for item in ([] if previous is None else previous["normalized_intent_constraints"])
    }
    current_constraints = {item["kind"]: item for item in plan["effective_constraints"]}
    added: list[str] = sorted(
        kind
        for kind, value in current_constraints.items()
        if previous_constraints.get(kind) != value
    )
    removed: list[str] = sorted(
        kind
        for kind, value in previous_constraints.items()
        if current_constraints.get(kind) != value
    )
    return {
        "schema_version": 1,
        "query_attempt_id": query_attempt_id,
        "run_id": run_id,
        "route_id": plan["route_id"],
        "round_no": round_no,
        "attempt_no": attempt_no,
        "resource_type": plan["resource_type"],
        "connector_id": plan["connector_id"],
        "operation_kind": plan["operation_kind"],
        "normalized_intent_constraints": list(plan["effective_constraints"]),
        "query_spec": {
            "tool_id": tool_id,
            "tool_schema_version": "v1",
            "canonical_arguments": dict(canonical_arguments),
        },
        "previous_query_hash": previous_query_hash,
        "page_state_hash": page_state_hash,
        "added_constraints": added,
        "removed_constraints": removed,
        "change_reason_code": change_reason_code,
        "candidate_count": candidate_count,
        "top_score": None,
        "score_margin": None,
        "confidence_band": None,
        "retrieval_config_version": RETRIEVAL_CONFIG_VERSION,
        "score_config_version": SCORE_CONFIG_VERSION,
        "threshold_config_version": THRESHOLD_CONFIG_VERSION,
        "stop_reason": stop_reason,
    }


def followup_planner_projection(
    *,
    current_round_no: int,
    prior_query_attempts: list[QueryAttemptV1],
    unresolved_sufficiency_issues: Collection[Mapping[str, object]],
    read_result_summaries: list[dict[str, object]],
) -> dict[str, object]:
    """Bounded local-only follow-up input; raw cache contents are excluded."""
    return {
        "current_round_no": current_round_no,
        "prior_query_attempts": [
            {
                key: cast(Mapping[str, object], attempt)[key]
                for key in (
                    "query_attempt_id",
                    "route_id",
                    "round_no",
                    "attempt_no",
                    "operation_kind",
                    "normalized_intent_constraints",
                    "previous_query_hash",
                    "added_constraints",
                    "removed_constraints",
                    "change_reason_code",
                    "candidate_count",
                    "stop_reason",
                )
                if key in attempt
            }
            for attempt in prior_query_attempts
        ],
        "unresolved_sufficiency_issues": [dict(issue) for issue in unresolved_sufficiency_issues],
        "read_result_summaries": read_result_summaries,
    }


__all__ = ["build_query_attempt", "followup_planner_projection"]
