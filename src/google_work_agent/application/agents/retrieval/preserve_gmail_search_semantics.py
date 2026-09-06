"""Preserve user-owned Gmail search meaning across semantic query planning."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from copy import deepcopy
from typing import cast

from google_work_agent.application.agents.retrieval.contracts.query_plan import (
    RetrievalV2ValidationError,
    TemporalRangeConstraintV1,
    validate_participant_identity,
)
from google_work_agent.application.agents.retrieval.has_explicit_gmail_subject import (
    has_explicit_gmail_subject,
)
from google_work_agent.application.agents.retrieval.match_person_mention import (
    person_discovery_term,
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


def requested_participant_identities(prompt_input: Mapping[str, object]) -> list[str]:
    """Only exact user-owned email values authorize initial hard participant filters."""
    intent = prompt_input.get("request_intent")
    if not isinstance(intent, Mapping):
        return []
    constraints = _explicit_gmail_constraints(intent.get("constraints"), now_ms=None, timezone=None)
    return sorted({
        str(person["identity"])
        for constraint in constraints if constraint["kind"] == "PARTICIPANT"
        for person in cast(list[dict[str, str]], constraint["participants"])
    })


def gmail_planner_constraint_kinds(
    prompt_input: Mapping[str, object],
) -> set[str] | None:
    """Narrow optional lexical/status filters to current user meaning, not examples."""
    intent = prompt_input.get("request_intent")
    if not isinstance(intent, Mapping):
        return None
    constraints = intent.get("constraints")
    if not isinstance(constraints, list) or not constraints:
        return None
    explicit = _explicit_gmail_constraints(constraints, now_ms=None, timezone=None)
    kinds = {str(item["kind"]) for item in explicit} | {
        "CONTAINER_REF", "RESOURCE_REF", "PARTICIPANT",
    }
    if _requested_concepts(constraints):
        kinds.add("CONCEPT")
    if any(isinstance(item, Mapping) and item.get("kind") in {"DATE", "TIME"}
           for item in constraints):
        kinds.add("TEMPORAL_RANGE")
    if kinds == {"CONTAINER_REF", "RESOURCE_REF", "PARTICIPANT"}:
        # Missing RU search fields are not evidence that the original request has
        # no lexical meaning. Keep the planner's bounded discovery capability;
        # exact participants, periods and statuses still require their own facts.
        kinds.add("KEYWORD")
    return kinds


def requested_gmail_concepts(
    prompt_input: Mapping[str, object], frozen_routes: Sequence[InputToolRouteV1],
) -> dict[str, set[str]]:
    intent = prompt_input.get("request_intent")
    if not isinstance(intent, Mapping) or has_explicit_gmail_subject(intent.get("constraints")):
        return {}
    concepts = _requested_concepts(intent.get("constraints"))
    return {route["route_id"]: concepts for route in frozen_routes
            if route["resource_type"] in {"GMAIL_THREAD", "GMAIL_MESSAGE"} and concepts}


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
    concepts = _requested_concepts(request_intent.get("constraints"))
    if (not explicit_constraints and not concepts) or not isinstance(value, Mapping):
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
    # Any person mentioned by the user is projected below as either an exact
    # email or a discovery term. Do not retain a competing model participant.
    if any(
        isinstance(item, Mapping) and item.get("kind") in {"PERSON", "EMAIL"}
        for item in request_intent.get("constraints", [])
    ):
        replacement_kinds.add("PARTICIPANT")
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
    if concepts:
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
        if concepts and not has_explicit_gmail_subject(intent_constraints):
            search_spec["constraints"] = [
                item for item in search_spec["constraints"]
                if not isinstance(item, Mapping) or item.get("kind") != "CONCEPT"
                or item.get("concept") in concepts
            ]
    return candidate


def validate_requested_concepts(
    value: object, prompt_input: Mapping[str, object], frozen_routes: Sequence[InputToolRouteV1],
) -> None:
    """Keep each user-owned concept represented without prescribing its hypotheses."""
    intent = prompt_input.get("request_intent")
    if not isinstance(intent, Mapping) or not isinstance(value, Mapping):
        return
    if has_explicit_gmail_subject(intent.get("constraints")):
        return
    concepts = _requested_concepts(intent.get("constraints"))
    gmail_ids = {route["route_id"] for route in frozen_routes
                 if route["resource_type"] in {"GMAIL_THREAD", "GMAIL_MESSAGE"}}
    for query in value.get("route_queries", []):
        if query.get("route_id") not in gmail_ids:
            continue
        spec = query.get("search_spec")
        if not isinstance(spec, Mapping) or spec.get("mode") != "INITIAL":
            continue
        constraints = spec.get("constraints", [])
        if concepts:
            hypotheses = [item for item in constraints
                          if item.get("kind") == "CONCEPT" and item.get("concept") in concepts]
            if not hypotheses:
                raise RetrievalV2ValidationError(
                    "discovery hypothesis must retain a requested business concept",
                    reason_code="QUERY_USER_CONSTRAINT_MISSING",
                    affected_field_paths=("$.route_queries[].search_spec.constraints",),
                )


def _requested_concepts(value: object) -> set[str]:
    if not isinstance(value, list):
        return set()
    return {
        entry for item in value if isinstance(item, Mapping)
        and item.get("kind") == "USER_REQUIREMENT" and item.get("field") == "business_concepts"
        for entry in (item["value"] if isinstance(item.get("value"), list) else [item.get("value")])
        if isinstance(entry, str) and entry
    }


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
    statuses: list[str] = []
    discovery_terms: dict[str, str] = {}
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
            for entry in exact_values:
                try:
                    identity = validate_participant_identity(entry)
                except RetrievalV2ValidationError:
                    discovery_terms[entry] = person_discovery_term(entry)
                    search_terms.append(discovery_terms[entry])
                else:
                    participants.append({"role": participant_fields[field], "identity": identity})
        elif kind in {"RESOURCE", "SCOPE", "USER_REQUIREMENT"} and field in {
            "subject",
            "search_criteria_subject",
        }:
            subjects.extend(exact_values)
        elif kind in {"USER_REQUIREMENT", "SCOPE"} and field == "search_terms":
            search_terms.extend(exact_values)
        elif kind == "USER_REQUIREMENT" and field == "business_concepts":
            business_concepts.extend(exact_values)
        elif kind == "SCOPE" and field == "status":
            statuses.extend(entry.upper() for entry in exact_values
                            if entry.upper() in {"ANY", "SENT", "DRAFT"})

    result: list[dict[str, object]] = []
    if statuses:
        result.append({"kind": "STATUS_SCOPE", "values": list(dict.fromkeys(statuses))})
    if participants:
        result.append({"kind": "PARTICIPANT", "participants": participants, "match_mode": "ALL"})
    if subjects and (not search_terms or has_explicit_gmail_subject(value)):
        result.append({"kind": "KEYWORD", "terms": subjects, "match_mode": "PHRASE"})
    else:
        search_terms = list(
            dict.fromkeys(
                discovery_terms.get(term, term)
                for term in search_terms
                if term not in business_concepts
            )
        )
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
