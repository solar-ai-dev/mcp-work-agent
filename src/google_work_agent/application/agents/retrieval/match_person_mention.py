"""Match an unresolved name/title against provider display-name metadata only."""

import re
from collections.abc import Mapping, Sequence
from typing import cast

from google_work_agent.application.agents.request_understanding.contracts.request_intent import (
    RequestIntentV3,
)
from google_work_agent.application.agents.retrieval.contracts.query_plan import (
    RetrievalV2ValidationError,
    validate_participant_identity,
)
from google_work_agent.application.agents.retrieval.contracts.retrieval_result import (
    EvidenceDraftV1,
    PersonCandidateV1,
)
from google_work_agent.application.agents.retrieval.normalize_segments import SourceSegment

_KOREAN_NAME_TITLE = re.compile(
    r"(?P<name>[가-힣]{1,4})\s*(?P<title>대리|과장|차장|부장|팀장|실장|이사|님)"
)
_EXPLICIT_CONTACT = re.compile(
    r"(?P<name>[가-힣A-Za-z][가-힣A-Za-z .]{1,39})\s*[<(]"
    r"(?P<email>[^\s<>()]+@[^\s<>()]+)[>)]"
)


def person_discovery_term(mention: str) -> str:
    """Broaden an abbreviated surname/title for discovery, not participant filtering."""
    requested = _KOREAN_NAME_TITLE.fullmatch(mention.strip())
    if requested is None:
        return mention.strip()
    return requested["title"] if len(requested["name"]) == 1 else requested["name"]


def match_person_mention(mention: str, display_name: str) -> bool:
    """Surname + title may match several people; this does not resolve identity."""
    target = re.sub(r"\s+", "", mention).casefold()
    normalized = re.sub(r"\s+", "", display_name).casefold()
    if target == normalized:
        return True
    requested = _KOREAN_NAME_TITLE.fullmatch(mention.strip())
    if requested is None:
        # A complete name remains the same metadata identity when a title is appended.
        # Do not use substring/surname matching for a name-only request.
        return any(found["name"] == target for found in _KOREAN_NAME_TITLE.finditer(display_name))
    return any(
        found["title"] == requested["title"]
        and (
            found["name"] == requested["name"]
            or len(requested["name"]) == 1 and found["name"].startswith(requested["name"])
        )
        for found in _KOREAN_NAME_TITLE.finditer(display_name)
    )


def project_person_candidates(
    intent: RequestIntentV3, evidence: Sequence[EvidenceDraftV1],
    prior_candidates: Sequence[PersonCandidateV1] = (),
    excluded_segment_ids: Sequence[str] = (),
    source_segments: Sequence[SourceSegment] = (),
) -> list[PersonCandidateV1]:
    """Join observed aliases through exact email identity, retaining source provenance."""
    mentions = [
        value
        for item in intent["constraints"]
        if item["kind"] == "PERSON"
        for value in (item["value"] if isinstance(item["value"], list) else [item["value"]])
    ]
    excluded = set(excluded_segment_ids)
    observed: dict[str, tuple[set[str], set[str]]] = {}
    for candidate in prior_candidates:
        # Aggregated aliases cannot retain a name after its supporting source was excluded.
        if set(candidate["source_segment_ids"]) & excluded:
            continue
        refs = set(candidate["source_segment_ids"]) - excluded
        if refs:
            names, sources = observed.setdefault(candidate["identity"], (set(), set()))
            names.update(candidate["display_names"])
            sources.update(refs)
    records = [
        (item["segment_id"], item["locator"] or {}, item["excerpt"]) for item in evidence
    ] + [(item.segment_id, item.locator, item.text) for item in source_segments]
    for segment_id, locator, text in records:
        if segment_id in excluded:
            continue
        for contact in _EXPLICIT_CONTACT.finditer(text):
            try:
                email = validate_participant_identity(contact["email"]).casefold()
            except RetrievalV2ValidationError:
                continue
            names, sources = observed.setdefault(email, (set(), set()))
            names.add(contact["name"].strip())
            sources.add(segment_id)
        try:
            identity = validate_participant_identity(locator.get("sender_email")).casefold()
        except RetrievalV2ValidationError:
            continue
        name = locator.get("sender_name")
        names, sources = observed.setdefault(identity, (set(), set()))
        if isinstance(name, str) and name.strip():
            names.add(name.strip())
        sources.add(segment_id)
    return cast(
        list[PersonCandidateV1],
        [
            {
                "mention": mention,
                "identity": identity,
                "display_names": sorted(names),
                "source_segment_ids": sorted(sources),
            }
            for mention in dict.fromkeys(mentions)
            for identity, (names, sources) in sorted(observed.items())
            if identity == mention.casefold()
            or any(match_person_mention(mention, name) for name in names)
        ][:40],
    )


def resolve_supported_person_identities(
    candidates: Sequence[PersonCandidateV1],
    evidence: Sequence[EvidenceDraftV1],
    prior_selection: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """Resolve only a uniquely supported observed identity; preserve user selection."""

    selected = dict(prior_selection or {})
    supporting_segments = {
        item["segment_id"] for item in evidence if "SUPPORTS" in item["reason_codes"]
    }
    for mention in dict.fromkeys(item["mention"] for item in candidates):
        if mention in selected:
            continue
        supported = {
            item["identity"]
            for item in candidates
            if item["mention"] == mention
            and supporting_segments.intersection(item["source_segment_ids"])
        }
        if len(supported) == 1:
            selected[mention] = next(iter(supported))
    return selected
