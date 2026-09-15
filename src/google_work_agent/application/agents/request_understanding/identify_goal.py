from __future__ import annotations

import re
from collections.abc import Mapping
from pathlib import Path

from google_work_agent.application.agents.preserve_exact_user_literals import (
    quoted_user_literals,
    restore_exact_user_literals,
    without_quoted_user_literals,
)
from google_work_agent.application.agents.project_run_reference_time import (
    project_run_reference_time,
)
from google_work_agent.application.agents.request_understanding.contracts.request_intent import (
    AmbiguityV1,
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

from .contracts.output_responsibility_decision import (
    OutputResponsibilityCandidateV1,
    OutputResponsibilityDecisionCandidateV2,
    OutputResponsibilityDecisionV2,
)
from .contracts.request_goal_candidate_schema import (
    IDENTIFY_GOAL_OUTPUT_SCHEMA,
    RequestGoalSemanticValidationError,
    derive_requested_resource_fields,
    validate_normalized_request_goal_candidate,
    validate_request_goal_candidate,
)
from .contracts.source_dependency_decision import SourceDependencyCandidateV1
from .identify_effect_prohibitions import (
    build_effect_prohibition_candidates,
    identify_effect_prohibitions,
)
from .identify_output_responsibilities import (
    ProhibitedOutputResponsibilityDecisionError,
    identify_output_responsibilities,
)
from .identify_source_dependencies import (
    SourceDependencyContradictionError,
    identify_source_dependencies,
    validate_source_dependency_semantics,
)
from .identify_source_status import identify_source_status
from .merge_resource_responsibilities import merge_resource_responsibilities
from .preserve_explicit_search_anchors import (
    preserve_explicit_search_anchors,
    project_extractive_source_goal,
)


def identify_goal(
    *,
    llm_runtime: StructuredInferencePort,
    request: WorkflowStartRequest,
    source_dependency_candidates: tuple[SourceDependencyCandidateV1, ...],
    output_responsibility_candidates: tuple[OutputResponsibilityCandidateV1, ...],
    prompt_ref: PromptReference | None = None,
    effect_prohibition_prompt_ref: PromptReference | None = None,
    source_dependency_prompt_ref: PromptReference | None = None,
    output_responsibility_prompt_ref: PromptReference | None = None,
    source_status_prompt_ref: PromptReference | None = None,
    manifest_path: Path | None = None,
    confirmation_response: ConfirmationResponseProjectionV1 | None = None,
    request_reconsideration: Mapping[str, object] | None = None,
) -> RequestGoalCandidateV1:
    """Identify only the current Run's goal semantics."""
    resolved_manifest_path = manifest_path or default_prompt_manifest_path()
    resolved_prompt_ref = prompt_ref or load_prompt_reference(
        "request_understanding.identify_goal", resolved_manifest_path
    )
    resolved_source_dependency_prompt_ref = source_dependency_prompt_ref or load_prompt_reference(
        "request_understanding.identify_source_dependencies",
        resolved_manifest_path,
    )
    resolved_output_responsibility_prompt_ref = (
        output_responsibility_prompt_ref
        or load_prompt_reference(
            "request_understanding.identify_output_responsibilities",
            resolved_manifest_path,
        )
    )
    resolved_effect_prohibition_prompt_ref = effect_prohibition_prompt_ref or load_prompt_reference(
        "request_understanding.identify_effect_prohibitions",
        resolved_manifest_path,
    )
    resolved_source_status_prompt_ref = source_status_prompt_ref or load_prompt_reference(
        "request_understanding.identify_source_status",
        resolved_manifest_path,
    )
    prompt_input = _prompt_input(
        request=request,
        confirmation_response=confirmation_response,
        request_reconsideration=request_reconsideration,
    )
    result = llm_runtime.infer(
        request.requested_mode,
        resolved_prompt_ref,
        prompt_input,
        IDENTIFY_GOAL_OUTPUT_SCHEMA,
    )
    effect_prohibitions = identify_effect_prohibitions(
        llm_runtime=llm_runtime,
        requested_mode=request.requested_mode,
        prompt_ref=resolved_effect_prohibition_prompt_ref,
        prompt_input=prompt_input,
        goal_candidate=result.structured_output,
        effect_candidates=build_effect_prohibition_candidates(output_responsibility_candidates),
    )
    source_decisions = identify_source_dependencies(
        llm_runtime=llm_runtime,
        requested_mode=request.requested_mode,
        prompt_ref=resolved_source_dependency_prompt_ref,
        prompt_input=prompt_input,
        goal_candidate=project_extractive_source_goal(
            result.structured_output,
            request_text=request.request_text,
        ),
        source_candidates=source_dependency_candidates,
    )
    output_decisions = identify_output_responsibilities(
        llm_runtime=llm_runtime,
        requested_mode=request.requested_mode,
        prompt_ref=resolved_output_responsibility_prompt_ref,
        prompt_input=prompt_input,
        goal_candidate=result.structured_output,
        output_candidates=output_responsibility_candidates,
        effect_prohibitions=effect_prohibitions,
    )
    validate_source_dependency_semantics(
        source_decisions,
        goal_candidate=project_extractive_source_goal(
            result.structured_output,
            request_text=request.request_text,
        ),
        has_output_responsibilities=bool(output_decisions["output_responsibilities"]),
    )
    responsibilities = merge_resource_responsibilities(
        source_decisions=source_decisions,
        output_decisions=output_decisions,
        source_candidates=source_dependency_candidates,
        output_candidates=output_responsibility_candidates,
        request_text=request.request_text,
    )
    source_status_output = identify_source_status(
        llm_runtime=llm_runtime,
        requested_mode=request.requested_mode,
        prompt_ref=resolved_source_status_prompt_ref,
        prompt_input=prompt_input,
        goal_candidate=result.structured_output,
        responsibilities=responsibilities,
    )
    return _validated_candidate(
        result.structured_output,
        resource_responsibilities=responsibilities,
        source_statuses=source_status_output,
        request=request,
        confirmation_response=confirmation_response,
    )


def identify_goal_with_budget(
    *,
    llm_runtime: StructuredInferencePort,
    request: WorkflowStartRequest,
    retry_budget: RunBudgetV2,
    source_dependency_candidates: tuple[SourceDependencyCandidateV1, ...],
    output_responsibility_candidates: tuple[OutputResponsibilityCandidateV1, ...],
    prompt_ref: PromptReference | None = None,
    effect_prohibition_prompt_ref: PromptReference | None = None,
    source_dependency_prompt_ref: PromptReference | None = None,
    output_responsibility_prompt_ref: PromptReference | None = None,
    source_status_prompt_ref: PromptReference | None = None,
    manifest_path: Path | None = None,
    confirmation_response: ConfirmationResponseProjectionV1 | None = None,
    request_reconsideration: Mapping[str, object] | None = None,
    prior_goal_candidate: RequestGoalCandidateV1 | None = None,
    prior_ambiguity_candidate: AmbiguityV1 | None = None,
) -> tuple[RequestGoalCandidateV1, RunBudgetV2]:
    """Identify the goal with one bounded semantic contract revision."""

    resolved_manifest_path = manifest_path or default_prompt_manifest_path()
    resolved_prompt_ref = prompt_ref or load_prompt_reference(
        "request_understanding.identify_goal", resolved_manifest_path
    )
    resolved_source_dependency_prompt_ref = source_dependency_prompt_ref or load_prompt_reference(
        "request_understanding.identify_source_dependencies",
        resolved_manifest_path,
    )
    resolved_output_responsibility_prompt_ref = (
        output_responsibility_prompt_ref
        or load_prompt_reference(
            "request_understanding.identify_output_responsibilities",
            resolved_manifest_path,
        )
    )
    resolved_effect_prohibition_prompt_ref = effect_prohibition_prompt_ref or load_prompt_reference(
        "request_understanding.identify_effect_prohibitions",
        resolved_manifest_path,
    )
    resolved_source_status_prompt_ref = source_status_prompt_ref or load_prompt_reference(
        "request_understanding.identify_source_status",
        resolved_manifest_path,
    )
    prompt_input = _prompt_input(
        request=request,
        confirmation_response=confirmation_response,
        request_reconsideration=request_reconsideration,
    )
    if (
        confirmation_response is not None
        and prior_goal_candidate is not None
        and request_reconsideration is None
    ):
        return _resolve_confirmed_goal(
            llm_runtime=llm_runtime,
            request=request,
            retry_budget=retry_budget,
            prompt_ref=resolved_prompt_ref,
            source_dependency_prompt_ref=resolved_source_dependency_prompt_ref,
            prompt_input=prompt_input,
            confirmation_response=confirmation_response,
            prior_goal_candidate=prior_goal_candidate,
            prior_ambiguity_candidate=prior_ambiguity_candidate,
            source_dependency_candidates=source_dependency_candidates,
            output_responsibility_candidates=output_responsibility_candidates,
        )
    with provider_dispatch_budget_scope(retry_budget):
        result = llm_runtime.infer(
            request.requested_mode,
            resolved_prompt_ref,
            prompt_input,
            IDENTIFY_GOAL_OUTPUT_SCHEMA,
        )
        goal_output = result.structured_output
        effect_candidates = build_effect_prohibition_candidates(output_responsibility_candidates)
        prohibition_output = identify_effect_prohibitions(
            llm_runtime=llm_runtime,
            requested_mode=request.requested_mode,
            prompt_ref=resolved_effect_prohibition_prompt_ref,
            prompt_input=prompt_input,
            goal_candidate=goal_output,
            effect_candidates=effect_candidates,
        )
        source_output = identify_source_dependencies(
            llm_runtime=llm_runtime,
            requested_mode=request.requested_mode,
            prompt_ref=resolved_source_dependency_prompt_ref,
            prompt_input=prompt_input,
            goal_candidate=project_extractive_source_goal(
                goal_output,
                request_text=request.request_text,
            ),
            source_candidates=source_dependency_candidates,
        )
        try:
            output_output = identify_output_responsibilities(
                llm_runtime=llm_runtime,
                requested_mode=request.requested_mode,
                prompt_ref=resolved_output_responsibility_prompt_ref,
                prompt_input=prompt_input,
                goal_candidate=goal_output,
                output_candidates=output_responsibility_candidates,
                effect_prohibitions=prohibition_output,
            )
        except ProhibitedOutputResponsibilityDecisionError as error:
            signature = build_semantic_failure_signature_v1(
                node_id="request.identify_goal",
                failure_reason_codes=[error.reason_code],
            )
            decision = approve_semantic_revision(retry_budget, signature=signature)
            if decision["decision"] == BudgetDecision.DENY.value:
                raise
            failure_record = build_failure_record_v1(
                failure_reason_code=error.reason_code,
                failure_origin="LLM_OUTPUT",
                detected_by="RUNTIME_DOMAIN_VALIDATOR",
                runtime_disposition="RETRYABLE",
                experiment_disposition="RUN_REVISION",
                affected_field_paths=list(error.affected_field_paths),
                failure_context_ids=[str(error)],
            )
            output_output = identify_output_responsibilities(
                llm_runtime=llm_runtime,
                requested_mode=request.requested_mode,
                prompt_ref=resolved_output_responsibility_prompt_ref,
                prompt_input=prompt_input,
                goal_candidate=goal_output,
                output_candidates=output_responsibility_candidates,
                effect_prohibitions=prohibition_output,
                candidate_output=error.candidate_output,
                failure_record=failure_record,
            )
            retry_budget = decision["run_budget"]
        source_goal = project_extractive_source_goal(
            goal_output,
            request_text=request.request_text,
        )
        try:
            source_output = validate_source_dependency_semantics(
                source_output,
                goal_candidate=source_goal,
                has_output_responsibilities=bool(
                    output_output["output_responsibilities"]
                ),
            )
        except SourceDependencyContradictionError as error:
            signature = build_semantic_failure_signature_v1(
                node_id="request.identify_goal",
                failure_reason_codes=[error.reason_code],
            )
            decision = approve_semantic_revision(retry_budget, signature=signature)
            if decision["decision"] == BudgetDecision.DENY.value:
                raise
            failure_record = build_failure_record_v1(
                failure_reason_code=error.reason_code,
                failure_origin="LLM_OUTPUT",
                detected_by="RUNTIME_DOMAIN_VALIDATOR",
                runtime_disposition="RETRYABLE",
                experiment_disposition="RUN_REVISION",
                affected_field_paths=list(error.affected_field_paths),
                failure_context_ids=[str(error)],
            )
            source_output = identify_source_dependencies(
                llm_runtime=llm_runtime,
                requested_mode=request.requested_mode,
                prompt_ref=resolved_source_dependency_prompt_ref,
                prompt_input=prompt_input,
                goal_candidate=source_goal,
                source_candidates=source_dependency_candidates,
                candidate_output=error.candidate_output,
                failure_record=failure_record,
            )
            source_output = validate_source_dependency_semantics(
                source_output,
                goal_candidate=source_goal,
                has_output_responsibilities=bool(
                    output_output["output_responsibilities"]
                ),
            )
            retry_budget = decision["run_budget"]
        responsibilities = merge_resource_responsibilities(
            source_decisions=source_output,
            output_decisions=output_output,
            source_candidates=source_dependency_candidates,
            output_candidates=output_responsibility_candidates,
            request_text=request.request_text,
        )
        source_status_output = identify_source_status(
            llm_runtime=llm_runtime,
            requested_mode=request.requested_mode,
            prompt_ref=resolved_source_status_prompt_ref,
            prompt_input=prompt_input,
            goal_candidate=goal_output,
            responsibilities=responsibilities,
        )
        try:
            candidate = _validated_candidate(
                goal_output,
                resource_responsibilities=responsibilities,
                source_statuses=source_status_output,
                request=request,
                confirmation_response=confirmation_response,
            )
        except RequestGoalSemanticValidationError as error:
            signature = build_semantic_failure_signature_v1(
                node_id="request.identify_goal",
                failure_reason_codes=[error.reason_code],
            )
            decision = approve_semantic_revision(retry_budget, signature=signature)
            if decision["decision"] == BudgetDecision.DENY.value:
                raise
            failure_record = build_failure_record_v1(
                failure_reason_code=error.reason_code,
                failure_origin="LLM_OUTPUT",
                detected_by="RUNTIME_DOMAIN_VALIDATOR",
                runtime_disposition="RETRYABLE",
                experiment_disposition="RUN_REVISION",
                affected_field_paths=list(error.affected_field_paths),
                failure_context_ids=[str(error)],
            )
            if error.reason_code == "REQUEST_EXISTING_RESOURCE_SOURCE_REQUIRED":
                source_output = identify_source_dependencies(
                    llm_runtime=llm_runtime,
                    requested_mode=request.requested_mode,
                    prompt_ref=resolved_source_dependency_prompt_ref,
                    prompt_input=prompt_input,
                    goal_candidate=project_extractive_source_goal(
                        goal_output,
                        request_text=request.request_text,
                    ),
                    source_candidates=source_dependency_candidates,
                    candidate_output=source_output,
                    failure_record=failure_record,
                )
                responsibilities = merge_resource_responsibilities(
                    source_decisions=source_output,
                    output_decisions=output_output,
                    source_candidates=source_dependency_candidates,
                    output_candidates=output_responsibility_candidates,
                    request_text=request.request_text,
                )
                source_status_output = identify_source_status(
                    llm_runtime=llm_runtime,
                    requested_mode=request.requested_mode,
                    prompt_ref=resolved_source_status_prompt_ref,
                    prompt_input=prompt_input,
                    goal_candidate=goal_output,
                    responsibilities=responsibilities,
                    candidate_output=source_status_output,
                    failure_record=failure_record,
                )
                candidate = _validated_candidate(
                    goal_output,
                    resource_responsibilities=responsibilities,
                    source_statuses=source_status_output,
                    request=request,
                    confirmation_response=confirmation_response,
                )
                retry_budget = decision["run_budget"]
                return candidate, merge_provider_dispatch_usage(retry_budget)
            if error.reason_code != "REQUEST_STATUS_PROVENANCE_MISMATCH":
                raise
            source_status_output = identify_source_status(
                llm_runtime=llm_runtime,
                requested_mode=request.requested_mode,
                prompt_ref=resolved_source_status_prompt_ref,
                prompt_input=prompt_input,
                goal_candidate=goal_output,
                responsibilities=responsibilities,
                candidate_output=source_status_output,
                failure_record=failure_record,
            )
            candidate = _validated_candidate(
                goal_output,
                resource_responsibilities=responsibilities,
                source_statuses=source_status_output,
                request=request,
                confirmation_response=confirmation_response,
            )
            retry_budget = decision["run_budget"]
        return candidate, merge_provider_dispatch_usage(retry_budget)


def _resolve_confirmed_goal(
    *,
    llm_runtime: StructuredInferencePort,
    request: WorkflowStartRequest,
    retry_budget: RunBudgetV2,
    prompt_ref: PromptReference,
    source_dependency_prompt_ref: PromptReference,
    prompt_input: Mapping[str, object],
    confirmation_response: ConfirmationResponseProjectionV1,
    prior_goal_candidate: RequestGoalCandidateV1,
    prior_ambiguity_candidate: AmbiguityV1 | None,
    source_dependency_candidates: tuple[SourceDependencyCandidateV1, ...],
    output_responsibility_candidates: tuple[OutputResponsibilityCandidateV1, ...],
) -> tuple[RequestGoalCandidateV1, RunBudgetV2]:
    """Resolve only source-bound facts supplied by one confirmation response."""

    responsibilities = prior_goal_candidate.get("resource_responsibilities")
    if responsibilities is None:
        raise ValueError("confirmation resume requires prior resource responsibilities")
    confirmation_text = _confirmation_response_text(confirmation_response)
    target_resource_confirmation_requested = (
        confirmation_text is not None
        and prior_ambiguity_candidate is not None
        and "target_resource" in prior_ambiguity_candidate["missing_fields"]
    )
    if target_resource_confirmation_requested:
        assert confirmation_text is not None
        candidate = prior_goal_candidate
        if not request.selected_resources:
            candidate = _bind_target_resource_confirmation(
                candidate,
                confirmation_text=confirmation_text,
            )
        if request.selected_resources or responsibilities["source_reads"]:
            return validate_normalized_request_goal_candidate(candidate), retry_budget
        with provider_dispatch_budget_scope(retry_budget):
            source_decisions = identify_source_dependencies(
                llm_runtime=llm_runtime,
                requested_mode=request.requested_mode,
                prompt_ref=source_dependency_prompt_ref,
                prompt_input=prompt_input,
                goal_candidate=_confirmed_source_goal(candidate),
                source_candidates=source_dependency_candidates,
                require_at_least_one_source=True,
            )
            responsibilities = merge_resource_responsibilities(
                source_decisions=source_decisions,
                output_decisions=_project_preserved_output_decisions(
                    prior_goal_candidate,
                    output_candidates=output_responsibility_candidates,
                ),
                source_candidates=source_dependency_candidates,
                output_candidates=output_responsibility_candidates,
                request_text=request.request_text,
            )
            candidate = _with_derived_resource_responsibilities(
                candidate,
                responsibilities=responsibilities,
            )
            retry_budget = merge_provider_dispatch_usage(retry_budget)
        return validate_normalized_request_goal_candidate(candidate), retry_budget
    with provider_dispatch_budget_scope(retry_budget):
        result = llm_runtime.infer(
            request.requested_mode,
            prompt_ref,
            prompt_input,
            IDENTIFY_GOAL_OUTPUT_SCHEMA,
        )
        resolved = _validated_candidate(
            result.structured_output,
            resource_responsibilities=responsibilities,
            source_statuses=_project_preserved_source_statuses(prior_goal_candidate),
            request=request,
            confirmation_response=confirmation_response,
        )
        candidate = _merge_confirmation_constraints(
            prior_goal_candidate,
            resolved,
            confirmation_text=confirmation_text,
        )
        retry_budget = merge_provider_dispatch_usage(retry_budget)
    return validate_normalized_request_goal_candidate(candidate), retry_budget


def _project_preserved_source_statuses(
    candidate: RequestGoalCandidateV1,
) -> dict[str, object]:
    statuses: list[dict[str, object]] = []
    for constraint in candidate["constraints"]:
        if not (
            constraint.get("kind") == "SCOPE"
            and constraint.get("field") == "status"
        ):
            continue
        provenance = constraint.get("provenance")
        resource_type = constraint.get("source_resource_type")
        source_text = provenance.get("source_text") if isinstance(provenance, Mapping) else None
        source = provenance.get("source") if isinstance(provenance, Mapping) else None
        if not all(
            isinstance(value, str) and value
            for value in (resource_type, source_text, source)
        ):
            raise ValueError("preserved source status has no current-Run provenance")
        statuses.append(
            {
                "value": constraint["value"],
                "source_resource_type": resource_type,
                "source": source,
                "source_text": source_text,
            }
        )
    return {"statuses": statuses}


def _merge_confirmation_constraints(
    prior: RequestGoalCandidateV1,
    resolved: RequestGoalCandidateV1,
    *,
    confirmation_text: str | None,
) -> RequestGoalCandidateV1:
    if not confirmation_text:
        return prior
    constraints = list(prior["constraints"])
    identities = {
        (item["kind"], item["field"], repr(item["value"])) for item in constraints
    }
    for constraint in resolved["constraints"]:
        if constraint.get("field") == "status":
            continue
        values = (
            constraint["value"]
            if isinstance(constraint["value"], list)
            else [constraint["value"]]
        )
        bound_values = [
            value
            for value in values
            if isinstance(value, str) and value and value in confirmation_text
        ]
        if not bound_values:
            continue
        value: str | list[str] = (
            bound_values[0] if isinstance(constraint["value"], str) else bound_values
        )
        identity = (constraint["kind"], constraint["field"], repr(value))
        if identity in identities:
            continue
        identities.add(identity)
        constraints.append({**constraint, "value": value})
    return {**prior, "constraints": constraints}


def _bind_target_resource_confirmation(
    prior: RequestGoalCandidateV1,
    *,
    confirmation_text: str,
) -> RequestGoalCandidateV1:
    return {
        **prior,
        "constraints": [
            *prior["constraints"],
            {
                "kind": "USER_REQUIREMENT",
                "field": "search_terms",
                "value": confirmation_text,
                "provenance": {
                    "source": "CONFIRMATION_RESPONSE",
                    "start_offset": 0,
                    "end_offset": len(confirmation_text),
                    "source_text": confirmation_text,
                },
            },
        ],
    }


def _confirmed_source_goal(candidate: RequestGoalCandidateV1) -> dict[str, object]:
    return {
        "goal": candidate["goal"],
        "completion_conditions": list(candidate["completion_conditions"]),
        "constraints": [dict(item) for item in candidate["constraints"]],
        "analysis_requirement": candidate["analysis_requirement"],
    }


def _project_preserved_output_decisions(
    candidate: RequestGoalCandidateV1,
    *,
    output_candidates: tuple[OutputResponsibilityCandidateV1, ...],
) -> OutputResponsibilityDecisionCandidateV2:
    allowed_effects = {
        item["resource_type"]: set(item["allowed_output_effects"])
        for item in output_candidates
    }
    decisions: list[OutputResponsibilityDecisionV2] = []
    for output in candidate["resource_responsibilities"]["outputs"]:
        if output["effect"] not in allowed_effects.get(output["resource_type"], set()):
            raise ValueError("preserved output responsibility is absent from current candidates")
        decisions.append(
            {
                "resource_type": output["resource_type"],
                "effect": output["effect"],
            }
        )
    return {"output_responsibilities": decisions}


def _with_derived_resource_responsibilities(
    candidate: RequestGoalCandidateV1,
    *,
    responsibilities: ResourceResponsibilitiesV1,
) -> RequestGoalCandidateV1:
    effects, resource_hints, source_information = derive_requested_resource_fields(
        responsibilities
    )
    constraints = [
        constraint
        for constraint in candidate["constraints"]
        if constraint["field"] != "required_information"
    ]
    if source_information:
        constraints.append(
            {
                "kind": "USER_REQUIREMENT",
                "field": "required_information",
                "value": source_information,
            }
        )
    return {
        **candidate,
        "constraints": constraints,
        "requested_effect_hints": effects,
        "requested_resource_hints": resource_hints,
        "resource_responsibilities": responsibilities,
    }


def _prompt_input(
    *,
    request: WorkflowStartRequest,
    confirmation_response: ConfirmationResponseProjectionV1 | None,
    request_reconsideration: Mapping[str, object] | None = None,
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
    reference_time = project_run_reference_time(request.run_budget)
    if reference_time is not None:
        prompt_input["run_reference_time"] = reference_time
    if confirmation_response is not None:
        prompt_input["confirmation_response"] = dict(confirmation_response)
    if request_reconsideration is not None:
        prompt_input["request_reconsideration"] = dict(request_reconsideration)
    return prompt_input


def _validated_candidate(
    value: object,
    *,
    resource_responsibilities: object,
    source_statuses: object,
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
            resource_responsibilities=resource_responsibilities,
            source_statuses=source_statuses,
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
                restore_exact_user_literals(item, source_texts=[request_text]) for item in value
            ]
        constraint = {**constraint, "value": value}
        constraints.append(constraint)
    quoted_text = " ".join(quoted_literals)
    constraints = [
        constraint
        for constraint in constraints
        if constraint["kind"] != "DATE"
        or (
            not _date_value_appears_in_text(constraint["value"], quoted_text)
            or _date_value_appears_in_text(constraint["value"], outside_literals)
            or _has_explicit_date_field_role(
                field=constraint["field"], request_text=request_text
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
            target_scope=source["target_scope"],
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


def _has_explicit_date_field_role(*, field: str, request_text: str) -> bool:
    patterns = {
        "scheduled_date": r"(?<![A-Za-z0-9_])scheduled_date(?![A-Za-z0-9_])|예정일",
        "due": r"(?<![A-Za-z0-9_])due(?![A-Za-z0-9_])|마감일|기한",
    }
    pattern = patterns.get(field)
    return pattern is not None and re.search(pattern, request_text, re.IGNORECASE) is not None


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
            source_reads.append(
                {
                    "resource_type": hint,
                    "required_information": [],
                    "target_scope": "SINGULAR",
                }
            )
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
