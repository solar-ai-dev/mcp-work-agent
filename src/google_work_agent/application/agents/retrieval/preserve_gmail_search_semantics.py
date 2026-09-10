"""Preserve user-owned Gmail search meaning across semantic query planning."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from copy import deepcopy
from typing import cast

from google_work_agent.application.agents.retrieval.contracts.query_plan import (
    ProtectedConstraintsByRouteV1,
    SemanticRetrievalConstraintV1,
)
from google_work_agent.application.agents.retrieval.has_explicit_gmail_subject import (
    has_explicit_gmail_subject,
)
from google_work_agent.application.agents.retrieval.is_searchable_gmail_route import (
    is_searchable_gmail_route,
)
from google_work_agent.application.agents.retrieval.resolve_requested_gmail_concepts import (
    resolve_requested_gmail_concepts,
)
from google_work_agent.application.agents.tool_routing.contracts.tool_route_plan import (
    InputToolRouteV1,
)


def preserve_gmail_search_semantics(
    value: object,
    *,
    prompt_input: Mapping[str, object],
    frozen_routes: Sequence[InputToolRouteV1],
    protected_constraints_by_route: ProtectedConstraintsByRouteV1,
) -> object:
    """Keep validated explicit Gmail values exact across semantic planning.

    The LLM still decides whether and how to search. Once it chooses an
    initial Gmail search, sender/recipient/subject strings already owned by
    RequestIntent are data, not a new semantic choice.
    """
    gmail_routes = {
        route["route_id"]: route
        for route in frozen_routes
        if is_searchable_gmail_route(route)
    }
    request_intent = prompt_input.get("request_intent")
    if not isinstance(request_intent, Mapping):
        return value
    concepts_by_route = resolve_requested_gmail_concepts(prompt_input, frozen_routes)
    has_protected = any(
        protected_constraints_by_route.get(route_id) for route_id in gmail_routes
    )
    if (not has_protected and not concepts_by_route) or not isinstance(value, Mapping):
        return value
    route_queries = value.get("route_queries")
    if not isinstance(route_queries, list):
        return value

    candidate = deepcopy(dict(value))
    candidate_queries = candidate.get("route_queries")
    if not isinstance(candidate_queries, list):
        return value
    has_explicit_person = any(
        isinstance(item, Mapping) and item.get("kind") in {"PERSON", "EMAIL"}
        for item in request_intent.get("constraints", [])
    )
    intent_constraints = request_intent.get("constraints")
    has_topic = isinstance(intent_constraints, list) and any(
        isinstance(item, Mapping)
        and item.get("field")
        in {
            "business_concepts",
            "search_terms",
            "subject",
            "search_criteria_subject",
        }
        and item.get("value")
        for item in intent_constraints
    )
    has_explicit_subject = has_explicit_gmail_subject(request_intent.get("constraints"))
    for route_query in candidate_queries:
        if not isinstance(route_query, dict):
            continue
        route_id = route_query.get("route_id")
        if route_id not in gmail_routes or route_query.get("operation") != "SEARCH":
            continue
        search_spec = route_query.get("search_spec")
        if not isinstance(search_spec, dict) or search_spec.get("mode") != "INITIAL":
            continue
        constraints = search_spec.get("constraints")
        if not isinstance(constraints, list):
            continue
        protected = list(protected_constraints_by_route.get(cast(str, route_id), ()))
        concepts = concepts_by_route.get(cast(str, route_id), set())
        protected_kinds = {str(item["kind"]) for item in protected}
        period_only = protected_kinds == {"TEMPORAL_RANGE"} and not has_topic
        filtered_constraints = [
            item
            for item in constraints
            if not isinstance(item, Mapping)
            or (
                not (has_explicit_person and item.get("kind") == "PARTICIPANT")
                and not (period_only and item.get("kind") in {"KEYWORD", "CONCEPT"})
                and not (concepts and item.get("kind") == "KEYWORD")
                and not (has_explicit_subject and item.get("kind") == "KEYWORD")
                and not (has_explicit_subject and item.get("kind") == "CONCEPT")
            )
        ]
        search_spec["constraints"] = _merge_initial_protected_constraints(
            filtered_constraints,
            protected,
        )
        if concepts and not has_explicit_subject:
            search_spec["constraints"] = [
                item
                for item in search_spec["constraints"]
                if not isinstance(item, Mapping)
                or item.get("kind") != "CONCEPT"
                or item.get("concept") in concepts
            ]
    return candidate


def _merge_initial_protected_constraints(
    candidate_constraints: Sequence[object],
    protected_constraints: Sequence[SemanticRetrievalConstraintV1],
) -> list[object]:
    """Bind code-owned constraints without discarding a compatible model hypothesis."""
    merged = list(candidate_constraints)
    for protected in protected_constraints:
        kind = protected["kind"]
        matching_indexes = [
            index
            for index, item in enumerate(merged)
            if isinstance(item, Mapping) and item.get("kind") == kind
        ]
        if not matching_indexes:
            merged.append(deepcopy(protected))
            continue
        if len(matching_indexes) != 1:
            # Keep malformed duplicate kinds visible to the canonical validator.
            continue
        index = matching_indexes[0]
        existing = merged[index]
        if kind == "KEYWORD" and isinstance(existing, Mapping):
            merged[index] = _merge_initial_keyword_constraint(existing, protected)
        else:
            merged[index] = deepcopy(protected)
    return merged


def _merge_initial_keyword_constraint(
    candidate: Mapping[str, object],
    protected: SemanticRetrievalConstraintV1,
) -> object:
    protected_value = cast(Mapping[str, object], protected)
    protected_terms = protected_value.get("terms")
    candidate_terms = candidate.get("terms")
    protected_mode = protected_value.get("match_mode")
    candidate_mode = candidate.get("match_mode")
    if (
        not isinstance(protected_terms, list)
        or not all(isinstance(term, str) for term in protected_terms)
        or not isinstance(candidate_terms, list)
        or not all(isinstance(term, str) for term in candidate_terms)
        or candidate_mode not in {"ANY", "ALL", "PHRASE"}
    ):
        return dict(candidate)
    if candidate_mode == "ANY" and len(candidate_terms) > 1 and protected_mode != "ANY":
        # Let the protected-continuity validator reject a genuine OR weakening.
        return dict(candidate)
    if protected_mode == "ALL" and candidate_mode == "ALL":
        return {
            "kind": "KEYWORD",
            "terms": list(dict.fromkeys([*protected_terms, *candidate_terms])),
            "match_mode": "ALL",
        }
    if protected_mode == "PHRASE" and len(protected_terms) == 1:
        if candidate_mode == "PHRASE" and candidate_terms == protected_terms:
            return deepcopy(protected)
        if candidate_mode in {"ALL", "PHRASE"} or len(candidate_terms) == 1:
            return {
                "kind": "KEYWORD",
                "terms": list(dict.fromkeys([*protected_terms, *candidate_terms])),
                "match_mode": "ALL",
            }
    # A multi-token PHRASE cannot safely share one match_mode with a separate
    # same-kind hypothesis. Preserve the verified phrase and discard that hypothesis.
    return deepcopy(protected)
