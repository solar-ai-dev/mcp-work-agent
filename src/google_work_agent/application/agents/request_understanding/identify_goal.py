from __future__ import annotations

import re
from pathlib import Path

from google_work_agent.application.agents.preserve_exact_user_literals import (
    quoted_user_literals,
    restore_exact_user_literals,
    without_quoted_user_literals,
)
from google_work_agent.application.agents.request_understanding.contracts.request_intent import (
    ConstraintProvenanceSource,
    RequestGoalCandidateV1,
    ResourceResponsibilitiesV1,
    SourceResourceResponsibilityV1,
    is_repository_constraint,
)
from google_work_agent.application.prompt_runtime.contracts.failure_record import (
    build_failure_record_v1,
)
from google_work_agent.application.prompt_runtime.prompt_registry import (
    default_prompt_manifest_path,
    load_prompt_reference,
)
from google_work_agent.application.use_cases.run.account_provider_dispatch import (
    merge_provider_dispatch_usage,
    provider_dispatch_budget_scope,
)
from google_work_agent.application.use_cases.run.guard_run_budget import (
    BudgetDecision,
    RunBudgetV2,
    approve_semantic_revision,
    build_semantic_failure_signature_v1,
)
from google_work_agent.ports.llm.structured_inference_contracts import (
    PromptReference,
)
from google_work_agent.ports.llm.structured_inference_port import StructuredInferencePort
from google_work_agent.ports.system.contracts.confirmation import (
    ConfirmationResponseProjectionV1,
)
from google_work_agent.ports.system.contracts.workflow_execution import WorkflowStartRequest

from .contracts.request_goal_candidate_schema import (
    IDENTIFY_GOAL_OUTPUT_SCHEMA,
    RequestGoalSemanticValidationError,
    derive_requested_resource_fields,
    validate_normalized_request_goal_candidate,
    validate_request_goal_candidate,
)
from .preserve_explicit_search_anchors import preserve_explicit_search_anchors


def identify_goal(
    *,
    llm_runtime: StructuredInferencePort,
    request: WorkflowStartRequest,
    prompt_ref: PromptReference | None = None,
    manifest_path: Path | None = None,
    confirmation_response: ConfirmationResponseProjectionV1 | None = None,
) -> RequestGoalCandidateV1:
    """Identify only the current Run's goal semantics."""
    resolved_prompt_ref = prompt_ref or load_prompt_reference(
        "request_understanding.identify_goal", manifest_path or default_prompt_manifest_path()
    )
    prompt_input = _prompt_input(
        request=request,
        confirmation_response=confirmation_response,
    )
    result = llm_runtime.infer(
        request.requested_mode,
        resolved_prompt_ref,
        prompt_input,
        IDENTIFY_GOAL_OUTPUT_SCHEMA,
    )
    return _validated_candidate(
        result.structured_output,
        request=request,
        confirmation_response=confirmation_response,
    )


def identify_goal_with_budget(
    *,
    llm_runtime: StructuredInferencePort,
    request: WorkflowStartRequest,
    retry_budget: RunBudgetV2,
    prompt_ref: PromptReference | None = None,
    manifest_path: Path | None = None,
    confirmation_response: ConfirmationResponseProjectionV1 | None = None,
) -> tuple[RequestGoalCandidateV1, RunBudgetV2]:
    """Identify the goal with one bounded semantic contract revision."""

    resolved_prompt_ref = prompt_ref or load_prompt_reference(
        "request_understanding.identify_goal", manifest_path or default_prompt_manifest_path()
    )
    prompt_input = _prompt_input(
        request=request,
        confirmation_response=confirmation_response,
    )
    with provider_dispatch_budget_scope(retry_budget):
        result = llm_runtime.infer(
            request.requested_mode,
            resolved_prompt_ref,
            prompt_input,
            IDENTIFY_GOAL_OUTPUT_SCHEMA,
        )
        try:
            candidate = _validated_candidate(
                result.structured_output,
                request=request,
                confirmation_response=confirmation_response,
            )
        except RequestGoalSemanticValidationError as error:
            source_information = _candidate_source_information(result.structured_output)
            signature = build_semantic_failure_signature_v1(
                node_id="request.identify_goal",
                failure_reason_codes=[error.reason_code],
            )
            decision = approve_semantic_revision(retry_budget, signature=signature)
            if decision["decision"] == BudgetDecision.DENY.value:
                raise
            revised = llm_runtime.infer(
                request.requested_mode,
                resolved_prompt_ref,
                {
                    "base_projection": prompt_input,
                    "candidate_output": result.structured_output,
                    "failure_record": build_failure_record_v1(
                        failure_reason_code=error.reason_code,
                        failure_origin="LLM_OUTPUT",
                        detected_by="RUNTIME_DOMAIN_VALIDATOR",
                        runtime_disposition="RETRYABLE",
                        experiment_disposition="RUN_REVISION",
                        affected_field_paths=list(error.affected_field_paths),
                        failure_context_ids=[str(error)],
                    ),
                },
                IDENTIFY_GOAL_OUTPUT_SCHEMA,
            )
            candidate = _validated_candidate(
                revised.structured_output,
                request=request,
                confirmation_response=confirmation_response,
            )
            _validate_semantic_revision_continuity(
                candidate,
                source_information=source_information,
            )
            retry_budget = decision["run_budget"]
        return candidate, merge_provider_dispatch_usage(retry_budget)


def _candidate_source_information(value: object) -> list[str]:
    if not isinstance(value, dict):
        return []
    responsibilities = value.get("resource_responsibilities")
    values: list[str] = []
    if isinstance(responsibilities, dict):
        source_reads = responsibilities.get("source_reads")
        if isinstance(source_reads, list):
            for source in source_reads:
                if not isinstance(source, dict):
                    continue
                information = source.get("required_information")
                if isinstance(information, list):
                    values.extend(item for item in information if isinstance(item, str))
    return list(dict.fromkeys(value for value in values if value.strip()))


def _validate_semantic_revision_continuity(
    candidate: RequestGoalCandidateV1,
    *,
    source_information: list[str],
) -> None:
    revised_information = {
        information
        for responsibility in candidate.get("resource_responsibilities", {}).get(
            "source_reads", []
        )
        for information in responsibility["required_information"]
    }
    if not set(source_information).issubset(revised_information):
        raise RequestGoalSemanticValidationError(
            "semantic revision removed a Connector-owned source need",
            reason_code="REQUEST_SEMANTIC_REVISION_SCOPE_EXCEEDED",
            affected_field_paths=(
                "$.resource_responsibilities.source_reads",
            ),
        )


def _prompt_input(
    *,
    request: WorkflowStartRequest,
    confirmation_response: ConfirmationResponseProjectionV1 | None,
) -> dict[str, object]:
    prompt_input: dict[str, object] = {
        "user_request": request.request_text,
        "selected_resource_refs": [
            {
                "resource_ref_id": ref.resource_ref_id,
                "connector_id": ref.connector_id,
                "resource_type": ref.resource_type,
                "resource_id": ref.resource_id,
                "parent_resource_id": ref.parent_resource_id,
            }
            for ref in request.selected_resources
        ],
    }
    if confirmation_response is not None:
        prompt_input["confirmation_response"] = dict(confirmation_response)
    return prompt_input


def _validated_candidate(
    value: object,
    *,
    request: WorkflowStartRequest,
    confirmation_response: ConfirmationResponseProjectionV1 | None,
) -> RequestGoalCandidateV1:
    provenance_sources: dict[ConstraintProvenanceSource, str] = {
        "USER_REQUEST": request.request_text
    }
    confirmation_text = _confirmation_response_text(confirmation_response)
    if confirmation_text is not None:
        provenance_sources["CONFIRMATION_RESPONSE"] = confirmation_text
    candidate = _apply_quoted_literal_authority(
        validate_request_goal_candidate(
            value,
            provenance_sources=provenance_sources,
        ),
        request_text=request.request_text,
    )
    candidate = preserve_explicit_search_anchors(
        candidate,
        request_text=request.request_text,
        entry_mode=request.entry_mode,
    )
    candidate = _apply_selected_resource_authority(candidate, request=request)
    return validate_normalized_request_goal_candidate(candidate)


def _confirmation_response_text(
    value: ConfirmationResponseProjectionV1 | None,
) -> str | None:
    if value is None:
        return None
    return value["selected_option"] or value["free_text"]


_EXPLICIT_DATE_SIGNAL = re.compile(
    r"(?i)(?:"
    r"\d{1,4}\s*(?:년|[-./])\s*\d{1,2}"
    r"|\d{1,2}\s*월\s*\d{1,2}\s*일"
    r"|오늘|내일|모레|이번\s*주|다음\s*주|다음\s*달|주말"
    r"|월요일|화요일|수요일|목요일|금요일|토요일|일요일"
    r"|까지|마감|기한|날짜|due|deadline|today|tomorrow|next\s+(?:week|month)"
    r")"
)


def _apply_quoted_literal_authority(
    candidate: RequestGoalCandidateV1,
    *,
    request_text: str,
) -> RequestGoalCandidateV1:
    """Do not reinterpret a quoted resource literal as an unstated date."""

    outside_literals = without_quoted_user_literals(request_text)
    quoted_literals = quoted_user_literals(request_text)
    if not quoted_literals:
        return candidate
    constraints = []
    for constraint in candidate["constraints"]:
        value = constraint["value"]
        if isinstance(value, str):
            value = restore_exact_user_literals(value, source_texts=[request_text])
        elif isinstance(value, list):
            value = [
                restore_exact_user_literals(item, source_texts=[request_text])
                for item in value
            ]
        constraint = {**constraint, "value": value}
        constraints.append(constraint)
    outside_has_date_signal = _EXPLICIT_DATE_SIGNAL.search(outside_literals) is not None
    quoted_text = " ".join(quoted_literals)
    constraints = [
        constraint
        for constraint in constraints
        if constraint["kind"] != "DATE"
        or (
            outside_has_date_signal
            and (
                not _date_value_appears_in_text(constraint["value"], quoted_text)
                or _date_value_appears_in_text(constraint["value"], outside_literals)
            )
        )
    ]
    responsibilities = candidate["resource_responsibilities"]
    source_reads: list[SourceResourceResponsibilityV1] = [
        SourceResourceResponsibilityV1(
            resource_type=source["resource_type"],
            required_information=[
                restore_exact_user_literals(item, source_texts=[request_text])
                for item in source["required_information"]
            ],
        )
        for source in responsibilities["source_reads"]
    ]
    return {
        **candidate,
        "goal": restore_exact_user_literals(candidate["goal"], source_texts=[request_text]),
        "completion_conditions": [
            restore_exact_user_literals(item, source_texts=[request_text])
            for item in candidate["completion_conditions"]
        ],
        "constraints": constraints,
        "resource_responsibilities": ResourceResponsibilitiesV1(
            source_reads=source_reads,
            outputs=responsibilities["outputs"],
        ),
    }


def _date_value_appears_in_text(value: object, text: str) -> bool:
    values = value if isinstance(value, list) else [value]
    for item in values:
        if not isinstance(item, str):
            continue
        match = re.search(r"(?:\d{4}[-./])?(\d{1,2})[-./](\d{1,2})", item)
        if match is None:
            continue
        month, day = (int(match.group(1)), int(match.group(2)))
        token = re.compile(rf"(?<!\d)0?{month}\s*(?:[-./]|월\s*)0?{day}(?:\s*일)?(?!\d)")
        if token.search(text):
            return True
    return False


def _apply_selected_resource_authority(
    candidate: RequestGoalCandidateV1,
    *,
    request: WorkflowStartRequest,
) -> RequestGoalCandidateV1:
    """Preserve trusted UI selection facts outside model-owned semantics."""
    if request.entry_mode != "RESOURCE_SELECTED" or not request.selected_resources:
        return candidate

    resource_ids = list(dict.fromkeys(ref.resource_id for ref in request.selected_resources))
    constraints = list(candidate["constraints"])
    selected_repositories = {
        ref.parent_resource_id
        for ref in request.selected_resources
        if ref.connector_id == "github"
        and ref.resource_type == "github_issue"
        and ref.parent_resource_id is not None
    }
    if len(selected_repositories) == 1:
        selected_repository = next(iter(selected_repositories))
        constraints = [
            constraint
            for constraint in constraints
            if not (
                is_repository_constraint(constraint)
                and constraint["value"] == selected_repository
                and selected_repository not in request.request_text
            )
        ]
    constrained_resource_ids = {
        str(item)
        for constraint in constraints
        if constraint["kind"] == "RESOURCE"
        for item in (
            constraint["value"] if isinstance(constraint["value"], list) else [constraint["value"]]
        )
    }
    missing_resource_ids = [
        resource_id for resource_id in resource_ids if resource_id not in constrained_resource_ids
    ]
    if missing_resource_ids:
        constraints.append(
            {
                "kind": "RESOURCE",
                "field": "selected_resource_id",
                "value": missing_resource_ids,
            }
        )

    responsibilities = candidate["resource_responsibilities"]
    source_reads = list(responsibilities["source_reads"])
    source_resource_types = {source["resource_type"] for source in source_reads}
    for hint in _selected_resource_hints(request):
        if hint not in source_resource_types:
            source_reads.append({"resource_type": hint, "required_information": []})
    responsibilities = ResourceResponsibilitiesV1(
        source_reads=source_reads,
        outputs=responsibilities["outputs"],
    )
    effects, resource_hints, _ = derive_requested_resource_fields(responsibilities)
    return {
        **candidate,
        "constraints": constraints,
        "requested_effect_hints": effects,
        "requested_resource_hints": resource_hints,
        "resource_responsibilities": responsibilities,
    }


_SELECTED_RESOURCE_HINTS = {
    ("google_workspace", resource_type): resource_type
    for resource_type in (
        "GMAIL_THREAD",
        "GMAIL_MESSAGE",
        "GMAIL_DRAFT",
        "GMAIL_ATTACHMENT",
        "TASK_LIST",
        "TASK",
        "CALENDAR",
        "CALENDAR_EVENT",
        "CALENDAR_FREEBUSY",
    )
} | {("github", "GITHUB_ISSUE"): "GITHUB_ISSUE"}


def _selected_resource_hints(request: WorkflowStartRequest) -> list[str]:
    return list(
        dict.fromkeys(
            hint
            for ref in request.selected_resources
            for hint in (
                _SELECTED_RESOURCE_HINTS.get((ref.connector_id, ref.resource_type.upper())),
            )
            if hint is not None
        )
    )
