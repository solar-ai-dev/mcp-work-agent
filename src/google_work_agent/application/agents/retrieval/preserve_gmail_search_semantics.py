"""Preserve user-owned Gmail search meaning across semantic query planning."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from copy import deepcopy

from google_work_agent.application.agents.retrieval.contracts.query_plan import (
    TemporalRangeConstraintV1,
)
from google_work_agent.application.agents.retrieval.expand_business_concept import (
    expand_business_concept,
)
from google_work_agent.application.agents.retrieval.has_explicit_gmail_subject import (
    has_explicit_gmail_subject,
)
from google_work_agent.application.agents.retrieval.resolve_relative_period import (
    resolve_relative_period,
)
from google_work_agent.application.agents.tool_routing.contracts.tool_route_plan import (
    InputToolRouteV1,
)


def resolve_gmail_query_periods(
    *, prompt_input: Mapping[str, object], frozen_routes: Sequence[InputToolRouteV1],
    now_ms: int | None, timezone: str | None,
) -> dict[str, TemporalRangeConstraintV1]:
    """Bind the existing period resolver to Gmail routes, never Calendar policy reads."""
    intent = prompt_input.get("request_intent")
    if not isinstance(intent, Mapping) or now_ms is None or timezone is None:
        return {}
    temporal = resolve_relative_period(intent.get("constraints"), now_ms=now_ms, timezone=timezone)
    if temporal is None:
        return {}
    bound: TemporalRangeConstraintV1 = {**temporal}
    return {
        route["route_id"]: bound
        for route in frozen_routes
        if route["resource_type"] in {"GMAIL_THREAD", "GMAIL_MESSAGE"}
    }


def preserve_gmail_search_semantics(
    value: object,
    *,
    prompt_input: Mapping[str, object],
    frozen_routes: Sequence[InputToolRouteV1],
    now_ms: int | None,
    timezone: str | None,
) -> object:
    """Keep validated explicit Gmail values exact across semantic planning.

    The LLM still decides whether and how to search. Once it chooses an
    initial Gmail search, sender/recipient/subject strings already owned by
    RequestIntent are data, not a new semantic choice.
    """
    gmail_routes = [route for route in frozen_routes if route["resource_type"] == "GMAIL_THREAD"]
    if len(gmail_routes) != 1:
        return value
    request_intent = prompt_input.get("request_intent")
    if not isinstance(request_intent, Mapping):
        return value
    explicit_constraints = _explicit_gmail_constraints(
        request_intent.get("constraints"),
        now_ms=now_ms,
        timezone=timezone,
    )
    if not explicit_constraints or not isinstance(value, Mapping):
        return value
    route_queries = value.get("route_queries")
    if not isinstance(route_queries, list):
        return value

    route_id = gmail_routes[0]["route_id"]
    candidate = deepcopy(dict(value))
    candidate_queries = candidate.get("route_queries")
    if not isinstance(candidate_queries, list):
        return value
    replacement_kinds = {str(item["kind"]) for item in explicit_constraints}
    intent_constraints = request_intent.get("constraints")
    has_topic = isinstance(intent_constraints, list) and any(
        isinstance(item, Mapping)
        and item.get("field") in {
            "business_concepts", "search_terms", "subject", "search_criteria_subject",
        }
        and item.get("value")
        for item in intent_constraints
    )
    if replacement_kinds == {"TEMPORAL_RANGE"} and not has_topic:
        # A period-only intent has no topical filter for the planner to specialize.
        replacement_kinds.update({"KEYWORD", "CONCEPT"})
    if "CONCEPT" in replacement_kinds:
        # A model's literal concept keyword must not AND away its alternatives.
        replacement_kinds.add("KEYWORD")
    if has_explicit_gmail_subject(request_intent.get("constraints")):
        replacement_kinds.add("CONCEPT")
    for route_query in candidate_queries:
        if not isinstance(route_query, dict):
            continue
        if route_query.get("route_id") != route_id or route_query.get("operation") != "SEARCH":
            continue
        search_spec = route_query.get("search_spec")
        if not isinstance(search_spec, dict) or search_spec.get("mode") != "INITIAL":
            continue
        constraints = search_spec.get("constraints")
        if not isinstance(constraints, list):
            continue
        search_spec["constraints"] = [
            item
            for item in constraints
            if not isinstance(item, Mapping) or str(item.get("kind")) not in replacement_kinds
        ] + explicit_constraints
    return candidate


def _explicit_gmail_constraints(
    value: object,
    *,
    now_ms: int | None,
    timezone: str | None,
) -> list[dict[str, object]]:
    if not isinstance(value, list):
        return []
    participants: list[dict[str, str]] = []
    subjects: list[str] = []
    search_terms: list[str] = []
    business_concepts: list[str] = []
    participant_fields = {
        "sender": "SENDER",
        "sender_email": "SENDER",
        "from": "SENDER",
        "recipient": "RECIPIENT",
        "recipient_email": "RECIPIENT",
        "to": "RECIPIENT",
        "search_criteria_sender": "SENDER",
        "search_criteria_recipient": "RECIPIENT",
        "person": "ANY",
    }
    for item in value:
        if not isinstance(item, Mapping):
            continue
        kind = str(item.get("kind", "")).upper()
        field = str(item.get("field", "")).strip().lower()
        values = item.get("value")
        exact_values = [values] if isinstance(values, str) else values
        if not isinstance(exact_values, list) or not all(
            isinstance(entry, str) and entry for entry in exact_values
        ):
            continue
        if kind in {"EMAIL", "PERSON", "SCOPE"} and field in participant_fields:
            participants.extend(
                {"role": participant_fields[field], "identity": entry} for entry in exact_values
            )
        elif kind in {"RESOURCE", "SCOPE", "USER_REQUIREMENT"} and field in {
            "subject",
            "search_criteria_subject",
        }:
            subjects.extend(exact_values)
        elif kind == "USER_REQUIREMENT" and field == "search_terms":
            search_terms.extend(exact_values)
        elif kind == "USER_REQUIREMENT" and field == "business_concepts":
            business_concepts.extend(exact_values)

    result: list[dict[str, object]] = []
    if participants:
        result.append({"kind": "PARTICIPANT", "participants": participants, "match_mode": "ALL"})
    if subjects and (not search_terms or has_explicit_gmail_subject(value)):
        result.append({"kind": "KEYWORD", "terms": subjects, "match_mode": "PHRASE"})
    else:
        concept = next(
            (expanded for name in business_concepts if (expanded := expand_business_concept(name))),
            None,
        )
        if concept is not None:
            result.append(dict(concept))
            search_terms = [term for term in search_terms if term != concept["concept"]]
        if search_terms:
            result.append(
                {
                    "kind": "KEYWORD",
                    "terms": search_terms,
                    "match_mode": "ALL" if len(search_terms) > 1 else "PHRASE",
                }
            )
    if now_ms is not None and timezone is not None:
        temporal = resolve_relative_period(value, now_ms=now_ms, timezone=timezone)
        if temporal is not None:
            result.append(dict(temporal))
    return result
