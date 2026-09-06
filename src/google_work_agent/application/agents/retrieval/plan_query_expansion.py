"""Deterministic next-page and no-result semantic query expansion."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import cast

from google_work_agent.application.agents.retrieval.assess_sufficiency import (
    select_followup_routes,
)
from google_work_agent.application.agents.retrieval.contracts.query_attempt import (
    QueryAttemptV1,
)
from google_work_agent.application.agents.retrieval.contracts.query_plan import (
    RetrievalQueryPlanV2,
    SemanticRetrievalConstraintV1,
)
from google_work_agent.application.agents.retrieval.contracts.retrieval_result import (
    PersonCandidateV1,
)
from google_work_agent.application.agents.retrieval.has_explicit_gmail_subject import (
    has_explicit_gmail_subject,
)
from google_work_agent.application.agents.retrieval.match_person_mention import (
    person_discovery_term,
)
from google_work_agent.application.agents.retrieval.preserve_gmail_search_semantics import (
    temporal_discovery_manifestations,
)
from google_work_agent.application.agents.tool_routing.contracts.tool_route_plan import (
    InputToolRouteV1,
)

_GENERIC_SEARCH_TERMS = frozenset(
    {
        "관련",
        "메일",
        "이메일",
        "찾기",
        "찾아",
        "about",
        "email",
        "emails",
        "message",
        "messages",
        "regarding",
        "schedule",
        "schedules",
        "일정",
        "논의한",
        "논의했던",
        "얘기한",
        "얘기했던",
        "이야기한",
        "이야기했던",
    }
)


def plan_query_expansion(
    *,
    prompt_input: Mapping[str, object],
    frozen_routes: Sequence[InputToolRouteV1],
    person_candidates: Sequence[PersonCandidateV1] = (),
    selected_person_identities: Mapping[str, str] | None = None,
) -> RetrievalQueryPlanV2 | None:
    """Return a distinct continuation only when current facts prove it useful."""

    if "current_round_no" not in prompt_input:
        return None
    attempts = _query_attempts(prompt_input)
    summaries = _read_summaries(prompt_input)
    route_queries: list[dict[str, object]] = []
    retrieval_order: list[str] = []
    for route in select_followup_routes(prompt_input, frozen_routes):
        route_id = route["route_id"]
        if "gmail_search_threads" in route[
            "allowed_read_tool_ids"
        ] and not _has_exact_subject_constraint(prompt_input):
            prior_searches = [
                item
                for item in attempts
                if item["route_id"] == route_id and item["operation_kind"] == "SEARCH"
            ]
            for mention in dict.fromkeys(item["mention"] for item in person_candidates):
                identities = {
                    item["identity"] for item in person_candidates if item["mention"] == mention
                }
                chosen = (selected_person_identities or {}).get(mention)
                if chosen not in identities:
                    chosen = next(iter(identities)) if len(identities) == 1 else None
                if chosen is None or not prior_searches:
                    continue
                if any(
                    constraint["kind"] == "PARTICIPANT"
                    and any(
                        item["identity"].casefold() == chosen for item in constraint["participants"]
                    )
                    for attempt in prior_searches
                    for constraint in attempt["normalized_intent_constraints"]
                ):
                    continue
                prior_participant = next((
                    constraint for constraint in prior_searches[-1]["normalized_intent_constraints"]
                    if constraint["kind"] == "PARTICIPANT"
                ), None)
                if (
                    prior_participant is not None and prior_participant["match_mode"] == "ANY"
                    and len(prior_participant["participants"]) > 1
                ):
                    # This schema cannot express (A OR B) AND the newly resolved identity.
                    continue
                upserts: list[SemanticRetrievalConstraintV1] = [{
                    "kind": "PARTICIPANT", "participants": [
                        *(prior_participant["participants"] if prior_participant else []),
                        {"role": "ANY", "identity": chosen},
                    ],
                    "match_mode": "ALL",
                }]
                remove = []
                for constraint in prior_searches[-1]["normalized_intent_constraints"]:
                    if constraint["kind"] != "KEYWORD":
                        continue
                    terms = [term for term in constraint["terms"]
                             if term not in {mention, person_discovery_term(mention)}]
                    if terms:
                        upserts.append({**constraint, "terms": terms})
                    else:
                        remove.append("KEYWORD")
                return cast(RetrievalQueryPlanV2, {
                    "schema_version": 2, "route_queries": [{
                        "route_id": route_id, "operation": "SEARCH",
                        "reason_codes": ["PERSON_IDENTITY_SEARCH_REQUIRED"],
                        "search_spec": {"mode": "CHANGED", "constraint_delta": {
                            "upsert_constraints": upserts, "remove_constraint_kinds": remove,
                        }}, "detail_candidate_ref": None,
                    }], "required_information": ["resolved participant evidence"],
                    "retrieval_order": [route_id],
                })
        summary = summaries.get(route_id)
        if summary is None:
            continue
        if summary.get("has_next_page") is True and summary.get("exhausted") is not True:
            route_queries.append(_route_query(route_id, "NEXT_PAGE"))
            retrieval_order.append(route_id)
            continue
        if (
            summary.get("result_count") != 0
            or _has_exact_subject_constraint(prompt_input)
            or "gmail_search_threads" not in route["allowed_read_tool_ids"]
        ):
            continue
        route_attempts = [attempt for attempt in attempts if attempt.get("route_id") == route_id]
        if sum(attempt.get("operation_kind") == "SEARCH" for attempt in route_attempts) != 1:
            continue
        constraints = route_attempts[-1]["normalized_intent_constraints"]
        concept = next((item for item in constraints if item["kind"] == "CONCEPT"), None)
        temporal = next(
            (
                item
                for item in constraints
                if item["kind"] == "TEMPORAL_RANGE" and item["axis"] == "EVENT_TIME"
            ),
            None,
        )
        if concept is not None and temporal is not None and temporal["start_local"]:
            # Date spelling is a discovery hypothesis, not a receipt-time restriction.
            # Existing KEYWORD/participant anchors and EVENT_TIME remain unchanged.
            manifestations = temporal_discovery_manifestations(temporal)
            route_queries.append({
                "route_id": route_id, "operation": "SEARCH",
                "reason_codes": ["TEMPORAL_DISCOVERY_HYPOTHESIS"],
                "search_spec": {"mode": "CHANGED", "constraint_delta": {
                    "upsert_constraints": [{**concept, "manifestations": manifestations}],
                    "remove_constraint_kinds": [],
                }}, "detail_candidate_ref": None,
            })
            retrieval_order.append(route_id)
            continue
        relaxed_keyword = _relaxed_keyword_constraint(route_attempts[-1])
        if relaxed_keyword is None:
            continue
        route_queries.append(
            {
                "route_id": route_id,
                "operation": "SEARCH",
                "reason_codes": ["QUERY_RELAXED_AFTER_NO_RESULTS"],
                "search_spec": {
                    "mode": "CHANGED",
                    "constraint_delta": {
                        "upsert_constraints": [relaxed_keyword],
                        "remove_constraint_kinds": [],
                    },
                },
                "detail_candidate_ref": None,
            }
        )
        retrieval_order.append(route_id)
    if not route_queries:
        return None
    return cast(
        RetrievalQueryPlanV2,
        {
            "schema_version": 2,
            "route_queries": route_queries,
            "required_information": ["additional evidence from a distinct bounded query"],
            "retrieval_order": retrieval_order,
        },
    )


def _route_query(route_id: str, operation: str) -> dict[str, object]:
    return {
        "route_id": route_id,
        "operation": operation,
        "reason_codes": ["UNREAD_PAGE_AVAILABLE"],
        "search_spec": None,
        "detail_candidate_ref": None,
    }


def _relaxed_keyword_constraint(
    attempt: Mapping[str, object],
) -> SemanticRetrievalConstraintV1 | None:
    constraints = attempt.get("normalized_intent_constraints")
    if not isinstance(constraints, list):
        return None
    keyword = next(
        (
            item
            for item in constraints
            if isinstance(item, Mapping) and item.get("kind") == "KEYWORD"
        ),
        None,
    )
    if keyword is None or keyword.get("match_mode") not in {"PHRASE", "ALL"}:
        return None
    raw_terms = keyword.get("terms")
    if not isinstance(raw_terms, list) or not all(isinstance(item, str) for item in raw_terms):
        return None
    tokens = [
        token
        for term in raw_terms
        for token in re.findall(r"[0-9A-Za-z가-힣_+-]+", term)
        if token.casefold() not in _GENERIC_SEARCH_TERMS
    ]
    relaxed_terms = list(dict.fromkeys(tokens))
    if not relaxed_terms or (relaxed_terms == raw_terms and len(relaxed_terms) == 1):
        return None
    return cast(
        SemanticRetrievalConstraintV1,
        {"kind": "KEYWORD", "terms": relaxed_terms, "match_mode": "ANY"},
    )


def _query_attempts(prompt_input: Mapping[str, object]) -> list[QueryAttemptV1]:
    value = prompt_input.get("prior_query_attempts")
    return cast(list[QueryAttemptV1], value) if isinstance(value, list) else []


def _read_summaries(prompt_input: Mapping[str, object]) -> dict[str, Mapping[str, object]]:
    value = prompt_input.get("read_result_summaries")
    if not isinstance(value, list):
        return {}
    return {
        cast(str, item["route_id"]): item
        for item in value
        if isinstance(item, Mapping) and isinstance(item.get("route_id"), str)
    }


def _has_exact_subject_constraint(prompt_input: Mapping[str, object]) -> bool:
    intent = prompt_input.get("request_intent")
    constraints = intent.get("constraints") if isinstance(intent, Mapping) else None
    return has_explicit_gmail_subject(constraints)


__all__ = ["plan_query_expansion"]
