"""Canonical Retrieval deterministic operation: finalize_retrieval."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from typing import Literal, cast

from google_work_agent.application.agents.request_understanding.contracts.request_intent import (
    RequestIntentV2,
    StateArtifactRefV1,
)
from google_work_agent.application.agents.retrieval.assess_sufficiency import (
    missing_information_projection,
    source_statuses_prompt_projection,
)
from google_work_agent.application.agents.retrieval.contracts.query_attempt import QueryAttemptV1
from google_work_agent.application.agents.retrieval.contracts.retrieval_result import (
    AcquisitionResultV1,
    EvidenceDraftV1,
    EvidenceSelectionResultV2,
    PersonCandidateV1,
    RetrievalCollectionItemV1,
    RetrievalCollectionResultV1,
    RetrievalResultV1,
    RetrievalSourceStatusV1,
    SufficiencyResultV2,
    TaskReviewCandidateV1,
)
from google_work_agent.application.agents.retrieval.match_temporal_evidence import (
    project_unresolved_event_dates,
)
from google_work_agent.application.agents.retrieval.project_query_temporal_constraints import (
    project_query_temporal_constraints,
)
from google_work_agent.application.agents.retrieval.resolve_availability import (
    AvailableIntervalV1,
)
from google_work_agent.application.agents.tool_routing.contracts.tool_route_plan import (
    ToolRoutePlanV2,
)


def finalize_retrieval(
    *,
    artifact_id: str,
    request_intent: RequestIntentV2,
    tool_route_plan: ToolRoutePlanV2,
    acquisition_result: AcquisitionResultV1,
    selection_result: EvidenceSelectionResultV2,
    evidence_drafts: list[EvidenceDraftV1],
    sufficiency_result: SufficiencyResultV2,
    current_round_no: int,
    availability_results: list[AvailableIntervalV1] | None = None,
    exclusion_obligation_segment_ids: Iterable[str] = (),
    prior_result: RetrievalResultV1 | None = None,
    prior_artifact_ref: StateArtifactRefV1 | None = None,
    query_attempts: Sequence[QueryAttemptV1] = (),
    read_result_summaries: Sequence[Mapping[str, object]] = (),
    person_candidates: Sequence[PersonCandidateV1] = (),
    selected_person_identities: Mapping[str, str] | None = None,
    task_review_candidates: Sequence[TaskReviewCandidateV1] = (),
) -> RetrievalResultV1:
    """Materialize the only parent-facing Retrieval business artifact."""
    selected_ids = list(selection_result["selected_segment_ids"])
    selected = set(selected_ids)
    evidence = [item for item in evidence_drafts if item["segment_id"] in selected]
    route_meta = tool_route_plan["input_plan"]["meta"]
    previous_ref = (
        prior_artifact_ref
        if prior_result is None
        else {
            "artifact_id": prior_result["meta"]["artifact_id"],
            "revision": prior_result["meta"]["revision"],
        }
    )
    prior_ref: list[StateArtifactRefV1] = [] if previous_ref is None else [previous_ref]
    artifact_identity = artifact_id if previous_ref is None else previous_ref["artifact_id"]
    revision = 1 if previous_ref is None else previous_ref["revision"] + 1
    excluded_ids = _unique(
        [
            *(prior_result["excluded_segment_ids"] if prior_result is not None else []),
            *selection_result["excluded_segment_ids"],
            *exclusion_obligation_segment_ids,
        ]
    )
    unresolved_dates = project_unresolved_event_dates(evidence, query_attempts)
    return {
        "schema_version": 1,
        "meta": {
            "artifact_id": artifact_identity,
            "revision": revision,
            "based_on": [
                {
                    "artifact_id": request_intent["meta"]["artifact_id"],
                    "revision": request_intent["meta"]["revision"],
                },
                {
                    "artifact_id": route_meta["artifact_id"],
                    "revision": route_meta["revision"],
                },
                *prior_ref,
            ],
        },
        "coverage": (
            "PARTIAL"
            if unresolved_dates and request_intent.get("requested_effect_hints") == ["READ"]
            else _coverage(sufficiency_result["status"], acquisition_result)
        ),
        "context_bundle_ref": None,
        "evidence_refs": [item["evidence_id"] for item in evidence],
        "selected_segment_ids": selected_ids,
        "excluded_segment_ids": excluded_ids,
        "source_resource_refs": _unique(item["resource_handle"] for item in evidence),
        "source_statuses": _source_statuses(
            tool_route_plan,
            acquisition_result,
            evidence_drafts=evidence,
            read_result_summaries=read_result_summaries,
        ),
        "collection_results": _collection_results(
            tool_route_plan,
            acquisition_result,
            read_result_summaries=read_result_summaries,
        ),
        "availability_results": [dict(item) for item in (availability_results or [])],
        "missing_information": missing_information_projection(sufficiency_result["issues"]),
        "retrieval_rounds": retrieval_round_count(current_round_no=current_round_no),
        "temporal_constraints": project_query_temporal_constraints(query_attempts),
        "unresolved_event_dates": unresolved_dates,
        "person_candidates": list(person_candidates),
        "selected_person_identities": dict(selected_person_identities or {}),
        "task_review_candidates": [
            cast(TaskReviewCandidateV1, dict(item)) for item in task_review_candidates
        ],
    }


def _collection_results(
    tool_route_plan: ToolRoutePlanV2,
    acquisition_result: AcquisitionResultV1,
    *,
    read_result_summaries: Sequence[Mapping[str, object]],
) -> list[RetrievalCollectionResultV1]:
    routes = tool_route_plan["input_plan"]["input_routes"]
    single_route_id = routes[0]["route_id"] if len(routes) == 1 else None
    resources_by_route: dict[str, list[RetrievalCollectionItemV1]] = {
        route["route_id"]: [] for route in routes
    }
    positions_by_route: dict[str, dict[str, int]] = {
        route["route_id"]: {} for route in routes
    }
    for summary in acquisition_result["source_summaries"]:
        route_id = summary.get("route_id", single_route_id)
        if not isinstance(route_id, str) or route_id not in resources_by_route:
            continue
        raw_resources = summary.get("resources", [])
        resource_by_ref = {
            str(resource.get("resource_handle")): resource
            for resource in cast(list[object], raw_resources)
            if isinstance(resource, Mapping)
            and isinstance(resource.get("resource_handle"), str)
            and resource.get("resource_handle")
        }
        handles = cast(list[object], summary.get("resource_handles", []))
        for raw_handle in handles:
            if not isinstance(raw_handle, str) or not raw_handle:
                continue
            resource = resource_by_ref.get(raw_handle, {})
            item: RetrievalCollectionItemV1 = {
                "resource_ref": raw_handle,
                "resource_type": str(
                    resource.get("resource_type") or raw_handle.partition(":")[0]
                ),
                "title": _collection_title(resource),
            }
            prior_position = positions_by_route[route_id].get(raw_handle)
            if prior_position is None:
                positions_by_route[route_id][raw_handle] = len(resources_by_route[route_id])
                resources_by_route[route_id].append(item)
            elif resources_by_route[route_id][prior_position]["title"] is None:
                resources_by_route[route_id][prior_position] = item
    summaries_by_route: dict[str, list[Mapping[str, object]]] = {
        route["route_id"]: [] for route in routes
    }
    acquisition_summaries_by_route: dict[str, list[Mapping[str, object]]] = {
        route["route_id"]: [] for route in routes
    }
    for summary in acquisition_result["source_summaries"]:
        route_id = summary.get("route_id", single_route_id)
        if isinstance(route_id, str) and route_id in acquisition_summaries_by_route:
            acquisition_summaries_by_route[route_id].append(summary)
    for read_summary in read_result_summaries:
        route_id = read_summary.get("route_id")
        if isinstance(route_id, str) and route_id in summaries_by_route:
            summaries_by_route[route_id].append(read_summary)
    return [
        {
            "route_id": route["route_id"],
            "resource_type": _collection_resource_type(
                route["route_id"],
                route["resource_type"],
                resources_by_route[route["route_id"]],
            ),
            "continuation_status": _collection_continuation(
                summaries_by_route[route["route_id"]],
                acquisition_summaries=acquisition_summaries_by_route[route["route_id"]],
            ),
            "items": resources_by_route[route["route_id"]],
        }
        for route in routes
    ]


def _collection_title(resource: Mapping[str, object]) -> str | None:
    payload = resource.get("payload")
    if not isinstance(payload, Mapping):
        return None
    for key in ("subject", "title", "summary"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _collection_resource_type(
    route_id: str,
    fallback: str,
    items: Sequence[RetrievalCollectionItemV1],
) -> str:
    observed = {item["resource_type"] for item in items if item["resource_type"]}
    if len(observed) > 1:
        raise ValueError(f"route {route_id} produced multiple collection resource types")
    return next(iter(observed), fallback.lower())


def _collection_continuation(
    read_result_summaries: Sequence[Mapping[str, object]],
    *,
    acquisition_summaries: Sequence[Mapping[str, object]] = (),
) -> Literal["EXHAUSTED", "HAS_MORE", "UNKNOWN"]:
    current_read_summaries = _latest_read_result_summaries(read_result_summaries)
    bounded_or_failed = any(
        summary.get("termination_kind") == "BUDGET_STOPPED"
        or summary.get("status") == "FAILED"
        for summary in acquisition_summaries
    )
    if any(summary.get("has_next_page") is True for summary in current_read_summaries):
        return "HAS_MORE"
    if bounded_or_failed:
        return "UNKNOWN"
    if current_read_summaries and all(
        summary.get("has_next_page") is False and summary.get("exhausted") is True
        for summary in current_read_summaries
    ):
        return "EXHAUSTED"
    if any(
        summary.get("continuation_status") == "HAS_MORE" for summary in acquisition_summaries
    ):
        return "HAS_MORE"
    if acquisition_summaries and all(
        summary.get("scope_complete") is True for summary in acquisition_summaries
    ):
        return "EXHAUSTED"
    return "UNKNOWN"


def _latest_read_result_summaries(
    summaries: Sequence[Mapping[str, object]],
) -> list[Mapping[str, object]]:
    """Keep only the current page fact for each effective query identity."""

    latest: dict[str, Mapping[str, object]] = {}
    for index, summary in enumerate(summaries):
        query_identity = summary.get("query_identity_hash")
        key = query_identity if isinstance(query_identity, str) else f"summary:{index}"
        latest[key] = summary
    return list(latest.values())


def _coverage(
    status: str, acquisition_result: AcquisitionResultV1
) -> Literal["SUFFICIENT", "PARTIAL", "NO_FETCH_NEEDED"]:
    attempted = any(
        item.get("status") != "NOT_ATTEMPTED" for item in acquisition_result["source_summaries"]
    )
    if status == "SUFFICIENT" and not acquisition_result["resource_handles"] and not attempted:
        return "NO_FETCH_NEEDED"
    return "SUFFICIENT" if status == "SUFFICIENT" else "PARTIAL"


def _source_statuses(
    tool_route_plan: ToolRoutePlanV2,
    acquisition_result: AcquisitionResultV1,
    *,
    evidence_drafts: list[EvidenceDraftV1],
    read_result_summaries: Sequence[Mapping[str, object]],
) -> list[RetrievalSourceStatusV1]:
    routes = tool_route_plan["input_plan"]["input_routes"]
    routes_by_id = {route["route_id"]: route for route in routes}
    handles_by_route = _resource_handles_by_route(
        acquisition_result,
        single_route_id=routes[0]["route_id"] if len(routes) == 1 else None,
    )
    statuses: list[RetrievalSourceStatusV1] = []
    for item in source_statuses_prompt_projection(
        tool_route_plan=tool_route_plan,
        acquisition_result=acquisition_result,
    ):
        route_id = str(item["route_id"])
        route_summaries = [
            summary
            for summary in acquisition_result["source_summaries"]
            if summary.get("route_id") == route_id
            or len(routes) == 1
            and summary.get("route_id") is None
        ]
        checked_read_count = sum(
            cast(int, summary.get("checked_read_count", 0)) for summary in route_summaries
        )
        known_scope_count = sum(
            cast(int, summary.get("known_scope_count", 0)) for summary in route_summaries
        )
        route_read_summaries = [
            summary for summary in read_result_summaries if summary.get("route_id") == route_id
        ]
        continuation_status = _collection_continuation(
            route_read_summaries, acquisition_summaries=route_summaries
        )
        scope_complete = (
            bool(route_summaries)
            and known_scope_count > 0
            and checked_read_count >= known_scope_count
            and continuation_status == "EXHAUSTED"
        )
        statuses.append(
            {
                "route_id": str(item["route_id"]),
                "resource_type": _exact_resource_type(
                    routes_by_id[str(item["route_id"])],
                    acquisition_result,
                ),
                "status": cast(
                    Literal["COMPLETE", "PARTIAL", "FAILED", "NOT_ATTEMPTED"],
                    item["status"],
                ),
                "evidence_refs": [
                    draft["evidence_id"]
                    for draft in evidence_drafts
                    if draft["resource_handle"] in handles_by_route.get(route_id, set())
                ],
                "observed_resource_count": len(handles_by_route.get(route_id, set())),
                "checked_read_count": checked_read_count,
                "known_scope_count": known_scope_count,
                "scope_complete": scope_complete,
                "continuation_status": continuation_status,
                "failure_kind": _failure_kind(item["failure_kind"]),
            }
        )
    return statuses


def _resource_handles_by_route(
    acquisition_result: AcquisitionResultV1,
    *,
    single_route_id: str | None,
) -> dict[str, set[str]]:
    result: dict[str, set[str]] = {}
    for summary in acquisition_result["source_summaries"]:
        route_id = summary.get("route_id", single_route_id)
        if not isinstance(route_id, str) or not route_id:
            continue
        result.setdefault(route_id, set()).update(
            str(handle) for handle in cast(list[object], summary.get("resource_handles", []))
        )
    return result


def _exact_resource_type(
    route: Mapping[str, object],
    acquisition_result: AcquisitionResultV1,
) -> str:
    observed = {
        str(resource.get("resource_type"))
        for summary in acquisition_result["source_summaries"]
        if summary.get("route_id") == route["route_id"]
        for resource in cast(list[object], summary.get("resources", []))
        if isinstance(resource, dict) and resource.get("resource_type")
    }
    if len(observed) > 1:
        raise ValueError("one frozen route produced multiple resource types")
    if observed:
        return observed.pop()
    return str(route["resource_type"]).lower()


def _failure_kind(
    value: object,
) -> (
    Literal["AUTH", "SCOPE", "RATE_LIMIT", "TIMEOUT", "PROVIDER", "NOT_FOUND", "BUDGET", "OTHER"]
    | None
):
    if value is None:
        return None
    normalized = str(value).upper()
    if normalized in {"AUTH", "SCOPE", "RATE_LIMIT", "TIMEOUT", "PROVIDER", "NOT_FOUND", "BUDGET"}:
        return cast(
            Literal["AUTH", "SCOPE", "RATE_LIMIT", "TIMEOUT", "PROVIDER", "NOT_FOUND", "BUDGET"],
            normalized,
        )
    return "OTHER"


def _unique(values: Iterable[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        if value not in seen:
            seen.add(value)
            result.append(value)
    return result


# Preserved round-budget semantics are owned by finalization.

MAX_RETRIEVAL_ROUNDS = 3


class RetrievalRoundLimitExceeded(ValueError):
    """A same-route additional Retrieval would exceed the canonical limit."""


def initialize_current_round_no(
    *,
    prior_result: RetrievalResultV1 | None,
    tool_route_plan: ToolRoutePlanV2,
) -> int:
    """Project the next 0-based local round from the official prior handoff."""
    if prior_result is None or not _uses_current_input_route(prior_result, tool_route_plan):
        return 0
    completed_rounds = prior_result["retrieval_rounds"]
    if completed_rounds >= MAX_RETRIEVAL_ROUNDS:
        raise RetrievalRoundLimitExceeded("same-route retrieval round limit is exhausted")
    return completed_rounds


def advance_current_round_no(*, current_round_no: int, is_followup: bool) -> int:
    """Return the 0-based round that the next read attempt belongs to."""

    next_round_no = current_round_no + int(is_followup)
    if next_round_no < 0 or next_round_no >= MAX_RETRIEVAL_ROUNDS:
        raise RetrievalRoundLimitExceeded("retrieval round limit is exhausted")
    return next_round_no


def retrieval_round_count(*, current_round_no: int) -> int:
    if current_round_no < 0 or current_round_no >= MAX_RETRIEVAL_ROUNDS:
        raise ValueError("current_round_no is outside the canonical retrieval round range")
    return current_round_no + 1


def _uses_current_input_route(
    result: RetrievalResultV1,
    tool_route_plan: ToolRoutePlanV2,
) -> bool:
    input_meta = tool_route_plan["input_plan"]["meta"]
    return {
        "artifact_id": input_meta["artifact_id"],
        "revision": input_meta["revision"],
    } in result["meta"]["based_on"]
