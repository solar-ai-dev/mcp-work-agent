"""Derive deterministic Gmail search constraints from typed request constraints."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Literal, cast

from google_work_agent.application.agents.retrieval.contracts.query_plan import (
    ParticipantMatchV1,
    ParticipantRoleV1,
    RetrievalV2ValidationError,
    SemanticRetrievalConstraintV1,
    StatusScopeValueV1,
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


def derive_gmail_search_constraints(
    value: object,
    *,
    now_ms: int | None,
    timezone: str | None,
    source_resource_type: str | None = None,
    require_validated_provenance: bool = False,
) -> list[SemanticRetrievalConstraintV1]:
    if not isinstance(value, list):
        return []
    participants: list[ParticipantMatchV1] = []
    subjects: list[str] = []
    search_terms: list[str] = []
    business_concepts: list[str] = []
    statuses: list[StatusScopeValueV1] = []
    discovery_terms: dict[str, str] = {}
    participant_fields: dict[str, ParticipantRoleV1] = {
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
        if require_validated_provenance and not _has_validated_source_provenance(item):
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
            bound_resource_type = item.get("source_resource_type")
            if (
                source_resource_type is not None
                and isinstance(bound_resource_type, str)
                and bound_resource_type != source_resource_type
            ):
                continue
            statuses.extend(
                canonical
                for entry in exact_values
                if (canonical := _canonical_gmail_status(entry)) is not None
            )

    result: list[SemanticRetrievalConstraintV1] = []
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
            bound: TemporalRangeConstraintV1 = {**temporal}
            result.append(bound)
    return result


def _has_validated_source_provenance(value: Mapping[str, object]) -> bool:
    provenance = value.get("provenance")
    if not isinstance(provenance, Mapping):
        return False
    source = provenance.get("source")
    start = provenance.get("start_offset")
    end = provenance.get("end_offset")
    return (
        source in {"USER_REQUEST", "CONFIRMATION_RESPONSE"}
        and type(start) is int
        and type(end) is int
        and 0 <= start < end
    )


def _canonical_gmail_status(value: str) -> Literal["ANY", "DRAFT", "SENT"] | None:
    normalized = "".join(value.split()).casefold().upper()
    if normalized not in {"ANY", "DRAFT", "SENT"}:
        return None
    return cast(Literal["ANY", "DRAFT", "SENT"], normalized)
