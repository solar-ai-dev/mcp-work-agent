"""Canonical Retrieval deterministic operation: finalize_retrieval."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Literal, cast

from google_work_agent.application.agents.request_understanding.contracts.request_intent import (
    RequestIntentV2,
    StateArtifactRefV1,
)
from google_work_agent.application.agents.retrieval.assess_sufficiency import (
    missing_information_projection,
    source_statuses_prompt_projection,
)
from google_work_agent.application.agents.retrieval.contracts.retrieval_result import (
    AcquisitionResultV1,
    EvidenceDraftV1,
    EvidenceSelectionResultV2,
    RetrievalResultV1,
    RetrievalSourceStatusV1,
    SufficiencyResultV2,
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
) -> RetrievalResultV1:
    """Materialize the only parent-facing Retrieval business artifact."""
    selected_ids = list(selection_result["selected_segment_ids"])
    selected = set(selected_ids)
    evidence = [item for item in evidence_drafts if item["segment_id"] in selected]
    route_meta = tool_route_plan["input_plan"]["meta"]
    prior_ref: list[StateArtifactRefV1] = (
        []
        if prior_result is None
        else [
            {
                "artifact_id": prior_result["meta"]["artifact_id"],
                "revision": prior_result["meta"]["revision"],
            }
        ]
    )
    artifact_identity = artifact_id if prior_result is None else prior_result["meta"]["artifact_id"]
    revision = 1 if prior_result is None else prior_result["meta"]["revision"] + 1
    excluded_ids = _unique(
        [
            *(prior_result["excluded_segment_ids"] if prior_result is not None else []),
            *selection_result["excluded_segment_ids"],
            *exclusion_obligation_segment_ids,
        ]
    )
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
        "coverage": _coverage(sufficiency_result["status"], acquisition_result),
        "context_bundle_ref": None,
        "evidence_refs": [item["evidence_id"] for item in evidence],
        "selected_segment_ids": selected_ids,
        "excluded_segment_ids": excluded_ids,
        "source_resource_refs": _unique(item["resource_handle"] for item in evidence),
        "source_statuses": _source_statuses(
            tool_route_plan,
            acquisition_result,
            evidence_drafts=evidence,
        ),
        "availability_results": [dict(item) for item in (availability_results or [])],
        "missing_information": missing_information_projection(sufficiency_result["issues"]),
        "retrieval_rounds": retrieval_round_count(current_round_no=current_round_no),
    }


def _coverage(
    status: str, acquisition_result: AcquisitionResultV1
) -> Literal["SUFFICIENT", "PARTIAL", "NO_FETCH_NEEDED"]:
    if status == "SUFFICIENT" and not acquisition_result["resource_handles"]:
        return "NO_FETCH_NEEDED"
    return "SUFFICIENT" if status == "SUFFICIENT" else "PARTIAL"


def _source_statuses(
    tool_route_plan: ToolRoutePlanV2,
    acquisition_result: AcquisitionResultV1,
    *,
    evidence_drafts: list[EvidenceDraftV1],
) -> list[RetrievalSourceStatusV1]:
    routes = tool_route_plan["input_plan"]["input_routes"]
    routes_by_id = {route["route_id"]: route for route in routes}
    handles_by_route = _resource_handles_by_route(
        acquisition_result,
        single_route_id=routes[0]["route_id"] if len(routes) == 1 else None,
    )
    return [
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
                if draft["resource_handle"] in handles_by_route.get(str(item["route_id"]), set())
            ],
            "failure_kind": _failure_kind(item["failure_kind"]),
        }
        for item in source_statuses_prompt_projection(
            tool_route_plan=tool_route_plan,
            acquisition_result=acquisition_result,
        )
    ]


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
