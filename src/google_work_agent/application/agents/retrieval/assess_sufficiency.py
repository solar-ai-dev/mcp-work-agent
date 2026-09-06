"""Canonical Retrieval semantic operation: assess_sufficiency."""

from __future__ import annotations

from collections.abc import Collection, Mapping, Sequence
from copy import deepcopy
from dataclasses import dataclass
from enum import StrEnum
from functools import partial
from typing import cast

import google_work_agent.application.agents.retrieval.contracts.schema_validation as _schema
from google_work_agent.application.agents.request_understanding.contracts.request_intent import (
    RequestIntentV2,
)
from google_work_agent.application.agents.retrieval.contracts.query_attempt import QueryAttemptV1
from google_work_agent.application.agents.retrieval.contracts.retrieval_result import (
    AcquisitionResultV1,
    ContextResult,
    ContextStatusValue,
    EvidenceDraftV1,
    MissingInformationRequiredForValue,
    MissingInformationV1,
    PersonCandidateV1,
    SufficiencyIssueTypeValue,
    SufficiencyIssueV2,
    SufficiencyResolutionSourceValue,
    SufficiencyResultV2,
)
from google_work_agent.application.agents.retrieval.is_complete_create_policy_read import (
    is_complete_create_policy_read,
)
from google_work_agent.application.agents.retrieval.match_person_mention import (
    project_person_candidates,
)
from google_work_agent.application.agents.retrieval.match_temporal_evidence import (
    project_unresolved_event_dates,
)
from google_work_agent.application.agents.retrieval.normalize_segments import (
    RetrievalValidationError,
)
from google_work_agent.application.agents.retrieval.project_attempted_detail_refs import (
    project_attempted_detail_refs,
)
from google_work_agent.application.agents.retrieval.project_query_temporal_constraints import (
    project_query_temporal_constraints,
)
from google_work_agent.application.agents.retrieval.require_read_evidence_support import (
    require_read_evidence_support,
)
from google_work_agent.application.agents.tool_routing.bind_registry_candidates import (
    coarse_resource_category,
    normalize_resource_type,
)
from google_work_agent.application.agents.tool_routing.contracts.tool_route_plan import (
    InputToolRouteV1,
    ToolRoutePlanV2,
)
from google_work_agent.application.use_cases.run.guard_run_budget import (
    MAX_ADDITIONAL_ACQUISITIONS,
    BudgetDecision,
    RunBudgetV2,
    approve_additional_acquisition,
)
from google_work_agent.ports.llm.structured_inference_contracts import (
    OutputSchemaDefinition,
    PromptReference,
)
from google_work_agent.ports.llm.structured_inference_port import StructuredInferencePort
from google_work_agent.ports.system.contracts.confirmation import (
    ConfirmationResponseProjectionV1,
)
from google_work_agent.ports.system.contracts.workflow_handoff import RequestedModeV1

# Outline + compose, each with its existing one-call repair allowance.
READ_ANSWER_CALL_RESERVE = 4


def _answer_call_reserve(intent: RequestIntentV2) -> int:
    # Six existing Work Analysis semantic operations precede Planning when required.
    return READ_ANSWER_CALL_RESERVE + (6 if intent.get("analysis_requirement") == "REQUIRED" else 0)


def deterministic_sufficiency(
    *, request_intent: RequestIntentV2, tool_route_plan: ToolRoutePlanV2 | None,
    acquisition_result: AcquisitionResultV1, evidence_drafts: list[EvidenceDraftV1],
    retry_budget: RunBudgetV2,
    confirmation_response: ConfirmationResponseProjectionV1 | None = None,
    person_candidates: Sequence[PersonCandidateV1] = (),
    selected_person_identities: Mapping[str, str] | None = None,
    query_attempts: Sequence[QueryAttemptV1] = (),
) -> SufficiencyResultV2 | None:
    """Close bounded READ acquisition without starving its grounded answer."""
    for mention in dict.fromkeys(item["mention"] for item in person_candidates):
        identities = {item["identity"] for item in person_candidates if item["mention"] == mention}
        chosen = (selected_person_identities or {}).get(mention)
        if chosen not in identities:
            chosen = next(iter(identities)) if len(identities) == 1 else None
        if chosen is None:
            return {"schema_version": 2, "status": "NEEDS_CONFIRMATION", "issues": [{
                "slot": "person_identity", "issue_type": "CONFLICT", "required": True,
                "resolution_source": "USER", "safety_critical": False,
                "reason_codes": ["PERSON_IDENTITY_AMBIGUOUS"],
            }]}
        searched = any(
            constraint["kind"] == "PARTICIPANT" and any(
                item["identity"].casefold() == chosen for item in constraint["participants"]
            )
            for attempt in query_attempts if attempt["operation_kind"] == "SEARCH"
            for constraint in attempt["normalized_intent_constraints"]
        )
        supported = any(
            candidate["identity"] == chosen
            and set(candidate["source_segment_ids"]).intersection(
                draft["segment_id"]
                for draft in evidence_drafts
                if "SUPPORTS" in draft["reason_codes"]
            )
            for candidate in person_candidates
            if candidate["mention"] == mention
        )
        if not searched and not supported:
            return {"schema_version": 2, "status": "NEEDS_MORE_DATA", "issues": [{
                "slot": "person_identity_search", "issue_type": "MISSING", "required": True,
                "resolution_source": "GOOGLE", "safety_critical": False,
                "reason_codes": ["PERSON_IDENTITY_SEARCH_REQUIRED"],
            }]}
    if confirmation_response is not None:
        return None
    remaining = (
        min(retry_budget["llm_call_limit"], retry_budget["absolute_llm_call_limit"])
        - retry_budget["llm_calls_used"]
    )
    if remaining > _answer_call_reserve(request_intent) or set(
        request_intent["requested_effect_hints"]
    ) != {"READ"}:
        metadata_candidates = [draft for draft in evidence_drafts
                               if (draft["locator"] or {}).get("is_metadata_only") is True]
        if metadata_candidates:
            detail_need = _require_gmail_candidate_details(
                {"schema_version": 2, "status": "NEEDS_MORE_DATA", "issues": []},
                request_intent=request_intent, tool_route_plan=tool_route_plan,
                evidence_drafts=metadata_candidates,
                attempted_detail_candidate_refs=project_attempted_detail_refs(query_attempts),
            )
            if detail_need["issues"]:
                return detail_need
        source_result = _deterministic_source_sufficiency(
            request_intent=request_intent, tool_route_plan=tool_route_plan,
            acquisition_result=acquisition_result, evidence_drafts=evidence_drafts,
            retry_budget=retry_budget, confirmation_response=confirmation_response,
        )
        return _guard_event_year(
            source_result, request_intent, evidence_drafts, query_attempts,
        ) if source_result is not None else None
    result = _fail_closed_on_empty_required_acquisition(
        {"schema_version": 2, "status": "PARTIAL", "issues": [{
            "slot": "retrieval_budget", "issue_type": "MISSING", "required": False,
            "resolution_source": "POLICY", "safety_critical": False,
            "reason_codes": ["ANSWER_CAPACITY_RESERVED"],
        }]},
        tool_route_plan=tool_route_plan, acquisition_result=acquisition_result,
        evidence_drafts=evidence_drafts,
    )
    if any(issue["required"] and issue["safety_critical"] for issue in result["issues"]):
        return {**result, "status": "BLOCKED"}
    return result


def _deterministic_source_sufficiency(
    *,
    request_intent: RequestIntentV2,
    tool_route_plan: ToolRoutePlanV2 | None,
    acquisition_result: AcquisitionResultV1,
    evidence_drafts: list[EvidenceDraftV1],
    retry_budget: RunBudgetV2,
    confirmation_response: ConfirmationResponseProjectionV1 | None = None,
) -> SufficiencyResultV2 | None:
    if (
        not evidence_drafts and set(request_intent["requested_effect_hints"]) == {"READ"}
        and acquisition_result["source_summaries"] and all(
            summary.get("status") == "COMPLETE" and summary.get("resource_count") == 0
            for summary in acquisition_result["source_summaries"]
        )
    ):
        empty_result = _fail_closed_on_empty_required_acquisition(
            {"schema_version": 2, "status": "NEEDS_MORE_DATA", "issues": []},
            tool_route_plan=tool_route_plan, acquisition_result=acquisition_result,
            evidence_drafts=evidence_drafts,
        )
        if empty_result["issues"]:
            return enforce_sufficiency_guard(
                empty_result, request_intent=request_intent, retry_budget=retry_budget,
                evidence_supported_partial_possible=False,
            )
    terminal_read_failure = any(
        summary.get("status") == "FAILED"
        and summary.get("error_code") in {"NOT_FOUND", "PERMISSION_DENIED", "BUDGET_EXHAUSTED"}
        for summary in acquisition_result["source_summaries"]
    )
    if terminal_read_failure:
        guarded = _fail_closed_on_empty_required_acquisition(
            {"schema_version": 2, "status": "PARTIAL", "issues": []},
            tool_route_plan=tool_route_plan, acquisition_result=acquisition_result,
            evidence_drafts=evidence_drafts,
        )
        return enforce_sufficiency_guard(
            guarded, request_intent=request_intent, retry_budget=retry_budget,
            evidence_supported_partial_possible=bool(evidence_drafts),
        )
    if _is_complete_selected_gmail_read(
        request_intent=request_intent,
        tool_route_plan=tool_route_plan,
        acquisition_result=acquisition_result,
        evidence_drafts=evidence_drafts,
        confirmation_response=confirmation_response,
    ):
        return {"schema_version": 2, "status": "SUFFICIENT", "issues": []}
    if is_complete_create_policy_read(
        request_intent=request_intent,
        tool_route_plan=tool_route_plan,
        acquisition_result=acquisition_result,
        confirmation_response=confirmation_response,
    ):
        return {"schema_version": 2, "status": "SUFFICIENT", "issues": []}
    if _is_complete_selected_github_update(
        request_intent, tool_route_plan, acquisition_result, evidence_drafts,
    ):
        return {"schema_version": 2, "status": "SUFFICIENT", "issues": []}
    return None


def _is_complete_selected_github_update(
    intent: RequestIntentV2, plan: ToolRoutePlanV2 | None,
    acquisition: AcquisitionResultV1, evidence: list[EvidenceDraftV1],
) -> bool:
    if (
        plan is None or plan["output_plan"]["output_mode"] != "ACTION"
        or intent["analysis_requirement"] != "NONE"
        or intent["ambiguity"]["requires_confirmation"]
        or set(intent["requested_effect_hints"]) - {"READ"} != {"UPDATE"}
        or acquisition["status"] != "COMPLETE" or acquisition["missing_slots"]
    ):
        return False
    inputs, outputs = plan["input_plan"]["input_routes"], plan["output_plan"]["output_routes"]
    if len(inputs) != 1 or len(outputs) != 1:
        return False
    route, output = inputs[0], outputs[0]
    if (
        route["connector_id"] != "github" or route["resource_type"] != "GITHUB_ISSUE"
        or "RESOURCE_SELECTED" not in route["reason_codes"] or not route["required"]
        or output["connector_id"] != "github" or output["resource_type"] != "GITHUB_ISSUE"
        or output["effect"] != "UPDATE" or output["selected_tool_id"] not in {
            "github_update_issue", "github_close_issue", "github_reopen_issue",
        }
    ):
        return False
    selected = {
        f"github_issue:{identity}"
        for constraint in intent["constraints"] if constraint["field"] == "selected_resource_id"
        and isinstance(constraint["value"], list)
        for identity in constraint["value"] if isinstance(identity, str)
    }
    summaries = _route_summaries(route, inputs, acquisition)
    return (
        len(selected) == 1 and bool(summaries)
        and all(item.get("status") == "COMPLETE" for item in summaries)
        and selected == {item["resource_handle"] for item in evidence}
        and selected.issubset({handle for item in summaries for handle in cast(
            list[str], item.get("resource_handles", [])
        )})
    )


def assess_sufficiency(
    *, llm_runtime: StructuredInferencePort, prompt_ref: PromptReference,
    requested_mode: RequestedModeV1, request_intent: RequestIntentV2,
    tool_route_plan: ToolRoutePlanV2 | None, acquisition_result: AcquisitionResultV1,
    evidence_drafts: list[EvidenceDraftV1], retry_budget: RunBudgetV2,
    confirmation_response: ConfirmationResponseProjectionV1 | None = None,
    attempted_detail_candidate_refs: Collection[str] = (),
    query_attempts: Sequence[QueryAttemptV1] = (),
    read_result_summaries: Sequence[Mapping[str, object]] = (),
) -> SufficiencyResultV2:
    """Assess evidence completeness, then apply the deterministic insufficient-data guard."""
    deterministic = deterministic_sufficiency(
        request_intent=request_intent, tool_route_plan=tool_route_plan,
        acquisition_result=acquisition_result, evidence_drafts=evidence_drafts,
        retry_budget=retry_budget, confirmation_response=confirmation_response,
        query_attempts=query_attempts,
    )
    if deterministic is not None:
        return deterministic
    prompt_input: dict[str, object] = {
        "request_intent": request_intent,
        "selected_evidence": selected_evidence_prompt_projection(evidence_drafts),
        "source_statuses": source_statuses_prompt_projection(
            tool_route_plan=tool_route_plan,
            acquisition_result=acquisition_result,
        ),
        "budget_state": budget_state_prompt_projection(retry_budget),
        "temporal_constraints": project_query_temporal_constraints(query_attempts),
    }
    if confirmation_response is not None:
        prompt_input["confirmation_response"] = dict(confirmation_response)
    result = llm_runtime.infer(
        requested_mode,
        prompt_ref,
        prompt_input,
        sufficiency_output_schema(tool_route_plan),
    )
    validated = validate_sufficiency_result_v2(result.structured_output)
    validated = _remove_unowned_read_confirmations(
        validated,
        request_intent=request_intent,
    )
    validated = _fail_closed_on_empty_required_acquisition(
        validated,
        tool_route_plan=tool_route_plan,
        acquisition_result=acquisition_result,
        evidence_drafts=evidence_drafts,
    )
    validated = _require_gmail_candidate_details(
        validated,
        request_intent=request_intent,
        tool_route_plan=tool_route_plan,
        evidence_drafts=evidence_drafts,
        attempted_detail_candidate_refs=attempted_detail_candidate_refs,
    )
    if tool_route_plan is not None and set(request_intent["requested_effect_hints"]) == {"READ"}:
        unread_routes = {
            summary.get("route_id") for summary in read_result_summaries
            if summary.get("has_next_page") is True and summary.get("exhausted") is not True
        }
        for route in tool_route_plan["input_plan"]["input_routes"]:
            if (route["route_id"] not in unread_routes
                    or "RESOURCE_SELECTED" in route["reason_codes"]):
                continue
            validated["issues"].append({
                "slot": "source_page_coverage", "route_id": route["route_id"],
                "issue_type": "MISSING", "required": True, "safety_critical": False,
                "resolution_source": "GOOGLE" if route["connector_id"] == "google_workspace"
                else "CONNECTOR", "reason_codes": ["UNREAD_PAGE_AVAILABLE"],
            })
    validated = require_read_evidence_support(
        validated,
        request_intent=request_intent,
        tool_route_plan=tool_route_plan,
        evidence_drafts=evidence_drafts,
    )
    validated = _bind_issue_routes(validated, tool_route_plan=tool_route_plan)
    if (
        validated["status"] == "SUFFICIENT"
        and not any(issue["required"] for issue in validated["issues"])
        and set(request_intent["requested_effect_hints"]) == {"READ"}
        and any(item["kind"] == "PERSON" for item in request_intent["constraints"])
        and not project_person_candidates(request_intent, evidence_drafts)
    ):
        return {"schema_version": 2, "status": "PARTIAL", "issues": [
            *validated["issues"], {
                "slot": "person_identity", "issue_type": "MISSING", "required": False,
                "resolution_source": "GOOGLE", "safety_critical": False,
                "reason_codes": ["PERSON_IDENTITY_UNRESOLVED"],
            },
        ]}
    validated = enforce_sufficiency_guard(
        validated,
        request_intent=request_intent,
        retry_budget=retry_budget,
        evidence_supported_partial_possible=bool(evidence_drafts),
    )
    return _guard_event_year(validated, request_intent, evidence_drafts, query_attempts)


def _guard_event_year(
    result: SufficiencyResultV2, intent: RequestIntentV2,
    evidence: Sequence[EvidenceDraftV1], attempts: Sequence[QueryAttemptV1],
) -> SufficiencyResultV2:
    if (
        result["status"] == "SUFFICIENT"
        and not any(issue["required"] for issue in result["issues"])
        and set(intent["requested_effect_hints"]) == {"READ"}
        and project_unresolved_event_dates(evidence, attempts)
    ):
        return {"schema_version": 2, "status": "PARTIAL", "issues": [
            *result["issues"], {
                "slot": "event_year", "issue_type": "MISSING", "required": False,
                "resolution_source": "GOOGLE", "safety_critical": False,
                "reason_codes": ["EVENT_YEAR_UNCONFIRMED"],
            },
        ]}
    return result


def _remove_unowned_read_confirmations(
    result: SufficiencyResultV2,
    *,
    request_intent: RequestIntentV2,
) -> SufficiencyResultV2:
    """Keep user-choice authority in Request Understanding for read-only runs."""

    if (
        set(request_intent["requested_effect_hints"]) != {"READ"}
        or request_intent["ambiguity"]["requires_confirmation"]
    ):
        return result
    is_google_discovery = bool(request_intent["requested_resource_hints"]) and all(
        hint.startswith(("GMAIL", "TASK", "CALENDAR"))
        for hint in request_intent["requested_resource_hints"]
    )
    if not is_google_discovery:
        return result
    issues = [issue for issue in result["issues"] if issue["resolution_source"] != "USER"]
    return {"schema_version": 2, "status": result["status"], "issues": issues}


def _fail_closed_on_empty_required_acquisition(
    result: SufficiencyResultV2,
    *,
    tool_route_plan: ToolRoutePlanV2 | None,
    acquisition_result: AcquisitionResultV1,
    evidence_drafts: list[EvidenceDraftV1],
) -> SufficiencyResultV2:
    """Preserve route-specific failure, policy and empty-result facts independently of the LLM."""
    if tool_route_plan is None:
        return result
    routes = tool_route_plan["input_plan"]["input_routes"]
    issues = list(result["issues"])
    evidence_handles = {draft["resource_handle"] for draft in evidence_drafts}
    for route in routes:
        if not route["required"]:
            continue
        summaries = _route_summaries(route, routes, acquisition_result)
        status = _worst_source_status(summaries)[0] if summaries else "NOT_ATTEMPTED"
        is_policy = bool(route["reason_codes"]) and all(
            code in {"POLICY_TASK_DUPLICATE_CHECK", "POLICY_CALENDAR_CONFLICT_CHECK"}
            for code in route["reason_codes"]
        )
        if is_policy and status == "COMPLETE":
            continue
        route_handles = {
            handle for summary in summaries
            for handle in cast(list[str], summary.get("resource_handles", []))
        }
        has_evidence = bool(evidence_handles & route_handles)
        if not route_handles and sum(
            other["resource_type"] == route["resource_type"] for other in routes
        ) == 1:
            resource_type = (
                normalize_resource_type(route["resource_type"])
                if route["resource_type"] == "EMAIL" else route["resource_type"]
            )
            has_evidence = any(
                handle.startswith(resource_type.lower() + ":") for handle in evidence_handles
            )
        if status == "COMPLETE" and has_evidence:
            continue
        no_resources = bool(summaries) and all(
            summary.get("resource_count") == 0 for summary in summaries
        )
        reason = (
            "REQUIRED_SOURCE_" + status if status != "COMPLETE"
            else "REQUIRED_SOURCE_RETURNED_NO_RESOURCES" if no_resources
            else "REQUIRED_SOURCE_HAS_NO_RELEVANT_EVIDENCE"
        )
        access_reasons = [
            "SOURCE_" + str(summary["error_code"])
            for summary in summaries
            if summary.get("status") == "FAILED"
            and summary.get("error_code") in {"NOT_FOUND", "PERMISSION_DENIED", "BUDGET_EXHAUSTED"}
        ]
        issues.append({
            "slot": "required_source_evidence",
            "route_id": route["route_id"],
            "issue_type": "MISSING",
            "required": True,
            "resolution_source": "POLICY" if is_policy else
            "GOOGLE" if route["connector_id"] == "google_workspace" else "CONNECTOR",
            "safety_critical": is_policy,
            "reason_codes": list(dict.fromkeys([reason, *access_reasons])),
        })
    return {
        "schema_version": 2,
        "status": result["status"],
        "issues": issues,
    }


def _bind_issue_routes(
    result: SufficiencyResultV2, *, tool_route_plan: ToolRoutePlanV2 | None,
) -> SufficiencyResultV2:
    routes = [] if tool_route_plan is None else tool_route_plan["input_plan"]["input_routes"]
    issues: list[SufficiencyIssueV2] = []
    for original in result["issues"]:
        issue = original.copy()
        source = issue["resolution_source"]
        route_id = issue.get("route_id")
        if route_id is not None and not any(route["route_id"] == route_id for route in routes):
            raise RetrievalValidationError("sufficiency issue references an unknown frozen route")
        if source in {"GOOGLE", "CONNECTOR"}:
            eligible = [route for route in routes if
                        (route["connector_id"] == "google_workspace") == (source == "GOOGLE")]
            if route_id is not None:
                if not any(route["route_id"] == route_id for route in eligible):
                    raise RetrievalValidationError("sufficiency issue Connector binding conflicts")
            elif len(eligible) == 1:
                issue["route_id"] = eligible[0]["route_id"]
            elif len(eligible) > 1:
                issue["resolution_source"] = "ROUTE"
        issues.append(issue)
    return {**result, "issues": issues}


def _route_summaries(
    route: InputToolRouteV1, routes: Sequence[InputToolRouteV1],
    acquisition_result: AcquisitionResultV1,
) -> list[dict[str, object]]:
    source = _RESOURCE_TYPE_TO_SOURCE_NAME[coarse_resource_category(route["resource_type"])]
    source_route_count = sum(
        _RESOURCE_TYPE_TO_SOURCE_NAME[coarse_resource_category(item["resource_type"])] == source
        for item in routes
    )
    return [
        summary for summary in acquisition_result["source_summaries"]
        if summary.get("source") == source
        and summary.get("connector_id", route["connector_id"]) == route["connector_id"]
        and (summary.get("route_id") == route["route_id"] or (
            summary.get("route_id") is None and source_route_count == 1
        ))
    ]


def _is_complete_selected_gmail_read(
    *,
    request_intent: RequestIntentV2,
    tool_route_plan: ToolRoutePlanV2 | None,
    acquisition_result: AcquisitionResultV1,
    evidence_drafts: list[EvidenceDraftV1],
    confirmation_response: ConfirmationResponseProjectionV1 | None,
) -> bool:
    if (
        confirmation_response is not None
        or tool_route_plan is None
        or tool_route_plan["output_plan"]["output_mode"] != "ANSWER"
        or request_intent["analysis_requirement"] != "NONE"
        or set(request_intent["requested_effect_hints"]) != {"READ"}
        or acquisition_result["status"] != "COMPLETE"
        or acquisition_result["missing_slots"]
        or not evidence_drafts
    ):
        return False
    routes = tool_route_plan["input_plan"]["input_routes"]
    if len(routes) != 1:
        return False
    route = routes[0]
    return (
        route["resource_type"] == "GMAIL_THREAD"
        and route["required"]
        and "RESOURCE_SELECTED" in route["reason_codes"]
        and all(draft["resource_handle"].startswith("gmail_thread:") for draft in evidence_drafts)
    )


# Preserved insufficient-data policy is owned by this sufficiency operation.


class ResolutionSource(StrEnum):
    USER = "USER"
    GOOGLE = "GOOGLE"
    CONNECTOR = "CONNECTOR"
    POLICY = "POLICY"
    ROUTE = "ROUTE"


class InsufficientDataDisposition(StrEnum):
    CONTINUE = "CONTINUE"
    BLOCKED = "BLOCKED"
    NEEDS_CONFIRMATION = "NEEDS_CONFIRMATION"
    ROUTE_RECONSIDERATION_REQUIRED = "ROUTE_RECONSIDERATION_REQUIRED"
    RETRIEVE_MORE = "RETRIEVE_MORE"
    PARTIAL = "PARTIAL"


@dataclass(frozen=True, slots=True)
class InsufficientDataIssue:
    issue_type: str
    required: bool
    resolution_source: ResolutionSource
    safety_critical: bool = False


@dataclass(frozen=True, slots=True)
class InsufficientDataContext:
    issues: tuple[InsufficientDataIssue, ...]
    budget_remaining: int
    read_only: bool
    evidence_supported_partial_possible: bool
    write_required_data_missing: bool = False
    user_can_resolve_write_gap: bool = False


def decide_insufficient_data(context: InsufficientDataContext) -> InsufficientDataDisposition:
    """Apply the canonical fail-closed precedence independently of LLM confidence."""

    required = tuple(issue for issue in context.issues if issue.required)
    if any(issue.resolution_source is ResolutionSource.POLICY for issue in required):
        return InsufficientDataDisposition.BLOCKED
    if any(
        issue.safety_critical
        for issue in required
    ):
        return InsufficientDataDisposition.BLOCKED
    if any(issue.resolution_source is ResolutionSource.USER for issue in required):
        return InsufficientDataDisposition.NEEDS_CONFIRMATION
    if any(issue.resolution_source is ResolutionSource.ROUTE for issue in required):
        return InsufficientDataDisposition.ROUTE_RECONSIDERATION_REQUIRED
    if (
        any(
            issue.resolution_source in {ResolutionSource.GOOGLE, ResolutionSource.CONNECTOR}
            for issue in required
        )
        and context.budget_remaining > 0
    ):
        return InsufficientDataDisposition.RETRIEVE_MORE
    if context.budget_remaining <= 0 and context.read_only:
        return InsufficientDataDisposition.PARTIAL
    if context.write_required_data_missing:
        if context.user_can_resolve_write_gap:
            return InsufficientDataDisposition.NEEDS_CONFIRMATION
        return InsufficientDataDisposition.BLOCKED
    if required:
        return InsufficientDataDisposition.BLOCKED
    return InsufficientDataDisposition.CONTINUE


# Preserved deterministic evaluator is owned by this sufficiency operation.

def sufficiency_output_schema(tool_route_plan: ToolRoutePlanV2 | None) -> OutputSchemaDefinition:
    """Constrain route references before inference to the current frozen route set."""
    schema = deepcopy(SUFFICIENCY_OUTPUT_SCHEMA.json_schema)
    routes = [] if tool_route_plan is None else tool_route_plan["input_plan"]["input_routes"]
    properties = cast(dict[str, object], schema["properties"])
    issues = cast(dict[str, object], properties["issues"])
    item = cast(dict[str, object], issues["items"])
    fields = cast(dict[str, object], item["properties"])
    if routes:
        fields["route_id"] = {"type": "string", "enum": [route["route_id"] for route in routes]}
    else:
        fields.pop("route_id", None)
    return OutputSchemaDefinition(
        schema_version=SUFFICIENCY_OUTPUT_SCHEMA.schema_version, json_schema=schema,
    )


SUFFICIENCY_OUTPUT_SCHEMA = OutputSchemaDefinition(
    schema_version="sufficiency-result-v2",
    json_schema={
        "type": "object",
        "required": ["schema_version", "status", "issues"],
        "additionalProperties": False,
        "properties": {
            "schema_version": {"type": "integer", "enum": [2]},
            "status": {
                "type": "string",
                "enum": [
                    "SUFFICIENT",
                    "NEEDS_MORE_DATA",
                    "NEEDS_CONFIRMATION",
                    "ROUTE_RECONSIDERATION_REQUIRED",
                    "PARTIAL",
                    "BLOCKED",
                ],
            },
            "issues": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": [
                        "slot",
                        "issue_type",
                        "required",
                        "resolution_source",
                        "safety_critical",
                        "reason_codes",
                    ],
                    "properties": {
                        "slot": {"type": "string"},
                        "route_id": {"type": "string", "minLength": 1},
                        "issue_type": {"type": "string", "enum": ["MISSING", "CONFLICT"]},
                        "required": {"type": "boolean"},
                        "resolution_source": {
                            "type": "string",
                            "enum": ["USER", "GOOGLE", "CONNECTOR", "POLICY", "ROUTE"],
                        },
                        "safety_critical": {"type": "boolean"},
                        "reason_codes": {"type": "array", "items": {"type": "string"}},
                    },
                },
            },
        },
    },
)

_CONTEXT_RESULT_VALUES = {item.value for item in ContextResult}
_ISSUE_TYPE_VALUES = {"MISSING", "CONFLICT"}
_RESOLUTION_SOURCE_VALUES = {"USER", "GOOGLE", "CONNECTOR", "POLICY", "ROUTE"}
_RESOURCE_TYPE_TO_SOURCE_NAME: dict[str, str] = {
    "EMAIL": "GMAIL",
    "TASK": "TASKS",
    "CALENDAR": "CALENDAR",
    "ISSUE": "GITHUB",
}
_SOURCE_STATUS_MAP: dict[str, tuple[str, str | None]] = {
    "COMPLETE": ("COMPLETE", None),
    "PARTIAL": ("PARTIAL", None),
    "AUTH_REQUIRED": ("FAILED", "AUTH_REQUIRED"),
    "RATE_LIMITED": ("FAILED", "RATE_LIMITED"),
    "BUDGET_EXHAUSTED": ("FAILED", "BUDGET_EXHAUSTED"),
    "FAILED": ("FAILED", "FAILED"),
}
_SOURCE_STATUS_PRIORITY = {"COMPLETE": 1, "PARTIAL": 2, "FAILED": 3}
_DISPOSITION_TO_STATUS: dict[InsufficientDataDisposition, ContextStatusValue] = {
    InsufficientDataDisposition.CONTINUE: "SUFFICIENT",
    InsufficientDataDisposition.BLOCKED: "BLOCKED",
    InsufficientDataDisposition.NEEDS_CONFIRMATION: "NEEDS_CONFIRMATION",
    InsufficientDataDisposition.ROUTE_RECONSIDERATION_REQUIRED: "ROUTE_RECONSIDERATION_REQUIRED",
    InsufficientDataDisposition.RETRIEVE_MORE: "NEEDS_MORE_DATA",
    InsufficientDataDisposition.PARTIAL: "PARTIAL",
}
# docs/05-context-retrieval.md SS19.1 has no free-text description field and
# docs/06-agent-workflow.md SS3.3's MissingInformationV1.required_for has no
# 1:1 Canonical definition from resolution_source -- both are documented,
# deterministic Q2-D defaults for the Parent-facing projection boundary,
# not fabricated data. Q2-E owns refining them once RetrievalResultV1 itself
# is finalized.
_RESOLUTION_SOURCE_TO_REQUIRED_FOR: dict[str, MissingInformationRequiredForValue] = {
    "USER": "USER_CONFIRMATION",
    "GOOGLE": "RETRIEVAL",
    "CONNECTOR": "RETRIEVAL",
    "ROUTE": "RETRIEVAL",
    "POLICY": "PLANNING",
}


def selected_evidence_prompt_projection(
    evidence_drafts: list[EvidenceDraftV1],
) -> list[dict[str, object]]:
    """retrieval-sufficiency-input-v1.schema.json ``selected_evidence``.

    Reuses select_evidence's already-materialized EvidenceDraftV1 list
    (docs/05 section 5.6 deterministic Segment join) -- assess_sufficiency
    never re-derives evidence from EvidenceSelectionResultV2/segments
    itself. role is read back from reason_codes[0], where
    select_evidence.materialize_evidence_drafts stores the LLM's role
    classification."""
    return [
        {
            "evidence_ref": draft["evidence_id"],
            "excerpt": draft["excerpt"],
            "role": draft["reason_codes"][0],
            "resource_ref": draft["resource_handle"],
        }
        for draft in evidence_drafts
    ]


def source_statuses_prompt_projection(
    *,
    tool_route_plan: ToolRoutePlanV2 | None,
    acquisition_result: AcquisitionResultV1,
) -> list[dict[str, object]]:
    """retrieval-sufficiency-input-v1.schema.json ``source_statuses``: one
    entry per frozen input_route (docs/05 SS4/CTX-002 Tool Route owns
    route_id), COMPLETE/PARTIAL/FAILED/NOT_ATTEMPTED joined from
    AcquisitionResultV1.source_summaries -- never the raw Provider/MCP
    response. tool_route_plan may be absent the same way
    The canonical plan_query prompt projection treats it defensively."""
    routes = () if tool_route_plan is None else tool_route_plan["input_plan"]["input_routes"]
    projections: list[dict[str, object]] = []
    for route in routes:
        resource_type = coarse_resource_category(route["resource_type"])
        summaries = _route_summaries(route, routes, acquisition_result)
        if not summaries:
            status, failure_kind = "NOT_ATTEMPTED", None
        else:
            status, failure_kind = _worst_source_status(summaries)
        projections.append(
            {
                "route_id": route["route_id"],
                "resource_type": resource_type,
                "status": status,
                "failure_kind": failure_kind,
            }
        )
    return projections


def _worst_source_status(summaries: list[dict[str, object]]) -> tuple[str, str | None]:
    worst_status = "COMPLETE"
    worst_failure_kind: str | None = None
    worst_priority = 0
    for summary in summaries:
        raw_status = str(summary.get("status"))
        status, failure_kind = _SOURCE_STATUS_MAP.get(raw_status, ("FAILED", raw_status))
        if raw_status == "FAILED":
            failure_kind = {
                "NOT_FOUND": "NOT_FOUND", "PERMISSION_DENIED": "SCOPE",
                "BUDGET_EXHAUSTED": "BUDGET_EXHAUSTED",
            }.get(str(summary.get("error_code")), failure_kind)
        priority = _SOURCE_STATUS_PRIORITY.get(status, 3)
        if priority > worst_priority:
            worst_priority = priority
            worst_status = status
            worst_failure_kind = failure_kind
    return worst_status, worst_failure_kind


def budget_state_prompt_projection(retry_budget: RunBudgetV2) -> dict[str, object]:
    """retrieval-sufficiency-input-v1.schema.json ``budget_state``, derived
    from the official RunBudgetV2/MAX_ADDITIONAL_ACQUISITIONS gate (docs/05
    section 13 MAX_ADDITIONAL_RETRIEVAL_ROUNDS=2) -- never a new hardcoded
    number."""
    used = retry_budget["additional_retrieval_rounds_used"]
    return {
        "additional_rounds_used": used,
        "additional_rounds_remaining": max(MAX_ADDITIONAL_ACQUISITIONS - used, 0),
    }


def validate_sufficiency_result_v2(value: object) -> SufficiencyResultV2:
    """sufficiency-result-v2.schema.json (docs/05-context-retrieval.md SS5.7/
    SS19.1). issues[] follows the Canonical SufficiencyIssue shape
    (slot/issue_type/required/resolution_source/safety_critical/
    reason_codes) -- see SufficiencyIssueV2 docstring for why this is not
    {code,description,required_for}."""
    root = _require_mapping(value, "$")
    _require_exact_keys(root, "$", {"schema_version", "status", "issues"})
    schema_version = _require_int(root, "schema_version", "$")
    if schema_version != 2:
        raise RetrievalValidationError("$.schema_version must be 2")
    status = _require_string(root, "status", "$")
    if status not in _CONTEXT_RESULT_VALUES:
        raise RetrievalValidationError("$.status is invalid")
    issues = [
        _validate_sufficiency_issue(item, f"$.issues[{index}]")
        for index, item in enumerate(_require_list(root["issues"], "$.issues"))
    ]
    return {
        "schema_version": 2,
        "status": cast(ContextStatusValue, status),
        "issues": issues,
    }


def _validate_sufficiency_issue(value: object, path: str) -> SufficiencyIssueV2:
    issue = _require_mapping(value, path)
    _require_exact_keys(
        issue,
        path,
        {"slot", "issue_type", "required", "resolution_source", "safety_critical", "reason_codes"}
        | ({"route_id"} if "route_id" in issue else set()),
    )
    issue_type = _require_string(issue, "issue_type", path)
    if issue_type not in _ISSUE_TYPE_VALUES:
        raise RetrievalValidationError(f"{path}.issue_type is invalid")
    resolution_source = _require_string(issue, "resolution_source", path)
    if resolution_source not in _RESOLUTION_SOURCE_VALUES:
        raise RetrievalValidationError(f"{path}.resolution_source is invalid")
    required = issue.get("required")
    if not isinstance(required, bool):
        raise RetrievalValidationError(f"{path}.required must be boolean")
    safety_critical = issue.get("safety_critical")
    if not isinstance(safety_critical, bool):
        raise RetrievalValidationError(f"{path}.safety_critical must be boolean")
    validated: SufficiencyIssueV2 = {
        "slot": _require_string(issue, "slot", path),
        "issue_type": cast(SufficiencyIssueTypeValue, issue_type),
        "required": required,
        "resolution_source": cast(SufficiencyResolutionSourceValue, resolution_source),
        "safety_critical": safety_critical,
        "reason_codes": _require_string_list(issue["reason_codes"], f"{path}.reason_codes"),
    }
    if "route_id" in issue:
        validated["route_id"] = _require_string(issue, "route_id", path)
    return validated


def enforce_sufficiency_guard(
    sufficiency_result: SufficiencyResultV2,
    *,
    request_intent: RequestIntentV2,
    retry_budget: RunBudgetV2,
    evidence_supported_partial_possible: bool,
) -> SufficiencyResultV2:
    """docs/05-context-retrieval.md SS19.2 결정적 종료 Guard: the LLM's
    proposed status is a candidate, never final authority. Reuses/extends
    insufficient_data.decide_insufficient_data (the same engine
    supervisor._route_additional_acquisition already uses) instead of a
    second guard engine. If the deterministic disposition disagrees with the
    LLM's status, the deterministic disposition wins."""
    read_only = all(effect == "READ" for effect in request_intent["requested_effect_hints"])
    budget_state = budget_state_prompt_projection(retry_budget)
    budget_remaining = cast(int, budget_state["additional_rounds_remaining"])
    if any(issue["slot"] == "gmail_candidate_detail" for issue in sufficiency_result["issues"]):
        budget_remaining = max(
            0, retry_budget["max_detail_fetches"] - retry_budget["detail_fetches_used"]
        )
    if any(
        set(issue["reason_codes"]) & {
            "SOURCE_NOT_FOUND", "SOURCE_PERMISSION_DENIED", "SOURCE_BUDGET_EXHAUSTED",
        }
        for issue in sufficiency_result["issues"]
    ):
        # A different query cannot restore a missing target or repository access.
        # This is eligibility for another acquisition, not mutation of RunBudget.
        budget_remaining = 0
    issues = tuple(
        InsufficientDataIssue(
            issue_type=issue["issue_type"],
            required=issue["required"],
            resolution_source=ResolutionSource(issue["resolution_source"]),
            safety_critical=issue["safety_critical"],
        )
        for issue in sufficiency_result["issues"]
    )
    # A survives-to-here required issue (nothing safety-critical/POLICY/
    # USER/ROUTE, and no GOOGLE issue with remaining budget) is only a
    # write-effect concern: Read-only runs fall through to the PARTIAL/
    # CONTINUE branches instead. No issue already flagged this as
    # USER-resolvable (that would have matched the NEEDS_CONFIRMATION
    # branch above it), so this never assumes a Write gap is user-fixable.
    write_required_data_missing = not read_only and any(issue.required for issue in issues)
    disposition = decide_insufficient_data(
        InsufficientDataContext(
            issues=issues,
            budget_remaining=budget_remaining,
            read_only=read_only,
            evidence_supported_partial_possible=evidence_supported_partial_possible,
            write_required_data_missing=write_required_data_missing,
            user_can_resolve_write_gap=False,
        )
    )
    authoritative_status = _DISPOSITION_TO_STATUS[disposition]
    if authoritative_status == sufficiency_result["status"]:
        return sufficiency_result
    return {
        "schema_version": 2,
        "status": authoritative_status,
        "issues": sufficiency_result["issues"],
    }


def _require_gmail_candidate_details(
    result: SufficiencyResultV2,
    *,
    request_intent: RequestIntentV2,
    tool_route_plan: ToolRoutePlanV2 | None,
    evidence_drafts: list[EvidenceDraftV1],
    attempted_detail_candidate_refs: Collection[str],
) -> SufficiencyResultV2:
    """Hydrate semantic matches before treating search previews as business evidence."""

    if (
        tool_route_plan is None
        or not (
            request_intent["analysis_requirement"] == "REQUIRED"
            or any((draft["locator"] or {}).get("is_metadata_only") is True
                   for draft in evidence_drafts)
            or any(
                item["kind"] == "PERSON" or item["field"] == "business_concepts"
                for item in request_intent["constraints"]
            )
            or any(
                item["field"] == "temporal_axis"
                and "EVENT_TIME"
                in (item["value"] if isinstance(item["value"], list) else [item["value"]])
                for item in request_intent["constraints"]
            )
        )
        or set(request_intent["requested_effect_hints"]) != {"READ"}
        or "GMAIL_THREAD" not in request_intent["requested_resource_hints"]
    ):
        return result
    routes = tool_route_plan["input_plan"]["input_routes"]
    if not any(
        route["resource_type"] == "GMAIL_THREAD"
        and "gmail_get_thread" in route["allowed_read_tool_ids"]
        and "RESOURCE_SELECTED" not in route["reason_codes"]
        for route in routes
    ):
        return result
    attempted = set(attempted_detail_candidate_refs)
    missing_refs = {
        draft["resource_handle"]
        for draft in evidence_drafts
        if draft["resource_handle"].startswith("gmail_thread:")
        and draft["resource_handle"] not in attempted
    }
    if not missing_refs:
        return result
    issue: SufficiencyIssueV2 = {
        "slot": "gmail_candidate_detail",
        "issue_type": "MISSING",
        "required": True,
        "resolution_source": "GOOGLE",
        "safety_critical": False,
        "reason_codes": ["CANDIDATE_DETAIL_REQUIRED"],
    }
    return {
        "schema_version": 2,
        "status": result["status"],
        "issues": [
            *[
                existing
                for existing in result["issues"]
                if existing["slot"] != "gmail_candidate_detail"
            ],
            issue,
        ],
    }


def authorize_retrieval_followup(
    sufficiency_result: SufficiencyResultV2,
    *,
    request_intent: RequestIntentV2,
    retry_budget: RunBudgetV2,
    evidence_supported_partial_possible: bool,
    can_acquire_new_information: bool,
    detail_fetch_count: int = 0,
) -> tuple[SufficiencyResultV2, RunBudgetV2, bool]:
    """Charge one owner-local follow-up or normalize an exhausted result.

    ``NEEDS_MORE_DATA`` is not a Parent-facing disposition.  The Retrieval
    owner consumes the same durable Run budget used by cross-owner back-edges
    before it schedules another read.  If no slot remains, the existing
    sufficiency guard deterministically closes the result as PARTIAL/BLOCKED
    (or another non-loop disposition) instead of leaking it to Main.
    """

    if sufficiency_result["status"] != "NEEDS_MORE_DATA":
        return sufficiency_result, retry_budget, False
    if (
        set(request_intent["requested_effect_hints"]) == {"READ"}
        and min(retry_budget["llm_call_limit"], retry_budget["absolute_llm_call_limit"])
        - retry_budget["llm_calls_used"] <= _answer_call_reserve(request_intent) + 2
    ):
        # Another query/evidence pass must leave the answer's existing allowance intact.
        return {**sufficiency_result, "status": "PARTIAL"}, retry_budget, False
    if not can_acquire_new_information:
        read_only = all(effect == "READ" for effect in request_intent["requested_effect_hints"])
        return (
            {
                "schema_version": 2,
                "status": ("PARTIAL" if read_only else "BLOCKED"),
                "issues": sufficiency_result["issues"],
            },
            retry_budget,
            False,
        )
    if detail_fetch_count > 0:
        # Dispatch consumes DETAIL_FETCH. Hydration is not a semantic search round.
        if (
            detail_fetch_count
            <= retry_budget["max_detail_fetches"] - retry_budget["detail_fetches_used"]
        ):
            return sufficiency_result, retry_budget, True
        return (
            {
                **sufficiency_result,
                "status": "PARTIAL"
                if set(request_intent["requested_effect_hints"]) == {"READ"}
                else "BLOCKED",
            },
            retry_budget,
            False,
        )
    authorization = approve_additional_acquisition(retry_budget)
    if authorization["decision"] == BudgetDecision.ALLOW.value:
        return sufficiency_result, authorization["run_budget"], True
    normalized = enforce_sufficiency_guard(
        sufficiency_result,
        request_intent=request_intent,
        retry_budget=authorization["run_budget"],
        evidence_supported_partial_possible=evidence_supported_partial_possible,
    )
    return normalized, authorization["run_budget"], False


def _issue_description(issue: SufficiencyIssueV2) -> str:
    if issue["reason_codes"]:
        return "; ".join(issue["reason_codes"])
    return issue["slot"]


def missing_information_projection(
    issues: list[SufficiencyIssueV2],
) -> list[MissingInformationV1]:
    """docs/06-agent-workflow.md SS3.3 RetrievalResultV1.missing_information
    projection boundary -- deliberately not the same type as SufficiencyIssue
    (docs/05 SS19.1): SufficiencyIssue is Retrieval's own internal judgment
    input to the SS19.2 deterministic Guard, MissingInformationV1 is the
    Parent-facing handoff shape. The projection keeps those two contracts
    separate without introducing a second Retrieval result authority."""
    return [
        {
            "code": issue["slot"],
            "description": _issue_description(issue),
            "required_for": _RESOLUTION_SOURCE_TO_REQUIRED_FOR[issue["resolution_source"]],
        }
        for issue in issues
    ]


# Shared with the other agent workflow modules; see _schema_support module docstring.
_require_mapping = partial(_schema.require_mapping, error_cls=RetrievalValidationError)
_require_exact_keys = partial(_schema.require_exact_keys, error_cls=RetrievalValidationError)
_require_int = partial(_schema.require_int, error_cls=RetrievalValidationError)
_require_string = partial(_schema.require_string, error_cls=RetrievalValidationError)
_require_string_list = partial(_schema.require_string_list, error_cls=RetrievalValidationError)
_require_list = partial(_schema.require_list, error_cls=RetrievalValidationError)
