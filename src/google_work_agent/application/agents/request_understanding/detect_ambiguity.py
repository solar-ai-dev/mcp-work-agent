from __future__ import annotations

import unicodedata
from collections.abc import Sequence
from pathlib import Path
from typing import Literal, TypedDict, cast

from google_work_agent.application.agents.request_understanding.contracts.request_intent import (
    AmbiguityV1,
    RequestGoalCandidateV1,
)
from google_work_agent.application.agents.request_understanding.validate_intent import (
    repository_authority_requires_confirmation,
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
    OutputSchemaDefinition,
    PromptReference,
)
from google_work_agent.ports.llm.structured_inference_port import StructuredInferencePort
from google_work_agent.ports.system.contracts.confirmation import (
    ConfirmationResponseProjectionV1,
)
from google_work_agent.ports.system.contracts.workflow_execution import WorkflowStartRequest


class AmbiguityCandidateV2(TypedDict):
    missing_information_owner: Literal["NONE", "USER", "CONNECTOR"]
    missing_fields: list[str]


class RequestAmbiguityValidationError(ValueError):
    def __init__(
        self,
        message: str,
        *,
        reason_code: str,
        affected_field_paths: Sequence[str],
    ) -> None:
        super().__init__(message)
        self.reason_code = reason_code
        self.affected_field_paths = tuple(affected_field_paths)


DETECT_AMBIGUITY_OUTPUT_SCHEMA = OutputSchemaDefinition(
    schema_version="request-ambiguity-v2",
    json_schema={
        "type": "object",
        "required": ["missing_information_owner", "missing_fields"],
        "additionalProperties": False,
        "properties": {
            "missing_information_owner": {
                "enum": ["NONE", "USER", "CONNECTOR"],
                "description": (
                    "NONE when nothing is missing; USER only for a user-owned choice; "
                    "CONNECTOR for facts retrievable from selected or routed resources."
                ),
            },
            "missing_fields": {
                "type": "array",
                "items": {"type": "string", "minLength": 1},
                "description": (
                    "Empty for NONE; non-empty for USER or CONNECTOR-owned missing information."
                ),
            },
        },
    },
)


def detect_ambiguity(
    *,
    llm_runtime: StructuredInferencePort,
    request: WorkflowStartRequest,
    goal_candidate: RequestGoalCandidateV1,
    prompt_ref: PromptReference | None = None,
    manifest_path: Path | None = None,
    confirmation_response: ConfirmationResponseProjectionV1 | None = None,
    retry_budget: RunBudgetV2,
) -> tuple[AmbiguityV1, RunBudgetV2]:
    """Decide only current-Run, user-owned ambiguity."""
    if repository_authority_requires_confirmation(
        goal_candidate["constraints"],
        user_request=request.request_text,
        confirmation_response_text=_confirmation_response_text(confirmation_response),
        selected_resources=request.selected_resources,
        repository_required="GITHUB_ISSUE" in goal_candidate["requested_resource_hints"],
        repository_default=request.default_github_repository,
    ):
        return (
            {
                "requires_confirmation": True,
                "reason_codes": ["MISSING_TARGET"],
                "missing_fields": ["repository"],
            },
            retry_budget,
        )
    if _is_general_answer_only(
        request=request,
        goal_candidate=goal_candidate,
    ):
        return (
            {"requires_confirmation": False, "reason_codes": [], "missing_fields": []},
            retry_budget,
        )
    resolved_prompt_ref = prompt_ref or load_prompt_reference(
        "request_understanding.detect_ambiguity",
        manifest_path or default_prompt_manifest_path(),
    )
    prompt_input: dict[str, object] = {
        "user_request": request.request_text,
        "goal_candidate": dict(goal_candidate),
        "resolution_responsibilities": _resolution_responsibilities(
            goal_candidate=goal_candidate,
            request=request,
        ),
        "selected_resource_refs": [
            {
                "resource_ref_id": item.resource_ref_id,
                "connector_id": item.connector_id,
                "resource_type": item.resource_type,
                "resource_id": item.resource_id,
                "parent_resource_id": item.parent_resource_id,
            }
            for item in request.selected_resources
        ],
    }
    if confirmation_response is not None:
        prompt_input["confirmation_response"] = dict(confirmation_response)
    with provider_dispatch_budget_scope(retry_budget):
        result = llm_runtime.infer(
            request.requested_mode,
            resolved_prompt_ref,
            prompt_input,
            DETECT_AMBIGUITY_OUTPUT_SCHEMA,
        )
        try:
            candidate = _validate_ambiguity_candidate(
                result.structured_output,
                goal_candidate=goal_candidate,
            )
        except RequestAmbiguityValidationError as error:
            signature = build_semantic_failure_signature_v1(
                node_id="request.detect_ambiguity",
                failure_reason_codes=[error.reason_code],
            )
            decision = approve_semantic_revision(retry_budget, signature=signature)
            if decision["decision"] == BudgetDecision.DENY.value:
                raise RequestAmbiguityValidationError(
                    "request ambiguity semantic revision denied",
                    reason_code=error.reason_code,
                    affected_field_paths=error.affected_field_paths,
                ) from error
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
                        affected_field_paths=error.affected_field_paths,
                        failure_context_ids=[str(error)],
                    ),
                },
                DETECT_AMBIGUITY_OUTPUT_SCHEMA,
            )
            candidate = _validate_ambiguity_candidate(
                revised.structured_output,
                goal_candidate=goal_candidate,
            )
            retry_budget = decision["run_budget"]
        retry_budget = merge_provider_dispatch_usage(retry_budget)
    return _finalize_ambiguity_candidate(candidate), retry_budget


def _confirmation_response_text(
    value: ConfirmationResponseProjectionV1 | None,
) -> str | None:
    if value is None:
        return None
    return value["selected_option"] or value["free_text"]


def _validate_ambiguity_candidate(
    value: object,
    *,
    goal_candidate: RequestGoalCandidateV1,
) -> AmbiguityCandidateV2:
    if not isinstance(value, dict) or set(value) != {
        "missing_information_owner",
        "missing_fields",
    }:
        raise ValueError("request ambiguity fields are invalid")
    missing_information_owner = value.get("missing_information_owner")
    missing_fields = value.get("missing_fields")
    if missing_information_owner not in {"NONE", "USER", "CONNECTOR"}:
        raise ValueError("missing_information_owner is invalid")
    if not isinstance(missing_fields, list) or any(
        not isinstance(item, str) or not item.strip() for item in missing_fields
    ):
        raise ValueError("missing_fields must contain non-empty strings")
    if missing_information_owner == "NONE" and missing_fields:
        raise RequestAmbiguityValidationError(
            "NONE ambiguity fields must be empty",
            reason_code="REQUEST_AMBIGUITY_OWNER_FIELDS_MISMATCH",
            affected_field_paths=("$.missing_information_owner", "$.missing_fields"),
        )
    if missing_information_owner != "NONE" and not missing_fields:
        raise RequestAmbiguityValidationError(
            "owned missing information requires fields",
            reason_code="REQUEST_AMBIGUITY_OWNER_FIELDS_MISMATCH",
            affected_field_paths=("$.missing_information_owner", "$.missing_fields"),
        )
    if missing_information_owner == "USER" and _overlaps_connector_owned_information(
        missing_fields,
        goal_candidate=goal_candidate,
    ):
        raise RequestAmbiguityValidationError(
            "retrieval-owned information was reclassified as a user-owned choice",
            reason_code="REQUEST_AMBIGUITY_RESOLUTION_OWNER_CONFLICT",
            affected_field_paths=(
                "$.missing_information_owner",
                "$.missing_fields",
                "$.goal_candidate.constraints",
            ),
        )
    return cast(
        AmbiguityCandidateV2,
        {
            "missing_information_owner": missing_information_owner,
            "missing_fields": missing_fields,
        },
    )


def _finalize_ambiguity_candidate(candidate: AmbiguityCandidateV2) -> AmbiguityV1:
    if candidate["missing_information_owner"] == "CONNECTOR":
        return {"requires_confirmation": False, "reason_codes": [], "missing_fields": []}
    if candidate["missing_information_owner"] == "USER":
        return {
            "requires_confirmation": True,
            "reason_codes": ["REQUEST_UNDERSTANDING_NEEDS_CONFIRMATION"],
            "missing_fields": candidate["missing_fields"],
        }
    return {
        "requires_confirmation": False,
        "reason_codes": [],
        "missing_fields": [],
    }


def _resolution_responsibilities(
    *,
    goal_candidate: RequestGoalCandidateV1,
    request: WorkflowStartRequest,
) -> dict[str, object]:
    connector_owned = _connector_owned_information(goal_candidate)
    resolved = [
        {
            "resource_ref_id": item.resource_ref_id,
            "resource_type": item.resource_type,
            "owner": "RESOLVED",
        }
        for item in request.selected_resources
    ]
    return {
        "connector_owned_information": connector_owned,
        "resolved_resource_refs": resolved,
    }


def _overlaps_connector_owned_information(
    missing_fields: Sequence[str],
    *,
    goal_candidate: RequestGoalCandidateV1,
) -> bool:
    connector_information = [
        item["information"] for item in _connector_owned_information(goal_candidate)
    ]
    return any(
        _same_information_need(missing, owned)
        for missing in missing_fields
        for owned in connector_information
    )


def _connector_owned_information(
    goal_candidate: RequestGoalCandidateV1,
) -> list[dict[str, str]]:
    responsibilities = goal_candidate.get("resource_responsibilities")
    if responsibilities:
        return [
            {
                "responsibility_path": (
                    f"$.goal_candidate.resource_responsibilities.source_reads[{index}]"
                ),
                "information": information,
                "resource_type": item["resource_type"],
                "owner": "CONNECTOR",
            }
            for index, item in enumerate(responsibilities["source_reads"])
            for information in item["required_information"]
        ]
    return [
        {
            "constraint_path": f"$.goal_candidate.constraints[{index}]",
            "information": information,
            "owner": "CONNECTOR",
        }
        for index, constraint in enumerate(goal_candidate["constraints"])
        if constraint["field"] == "required_information"
        for information in _constraint_values(constraint["value"])
    ]


def _constraint_values(value: str | list[str]) -> list[str]:
    return [value] if isinstance(value, str) else value


def _same_information_need(left: str, right: str) -> bool:
    """Match only the same normalized need; wording similarity is not ownership proof."""

    normalized_left = _normalize_information_need(left)
    normalized_right = _normalize_information_need(right)
    return bool(normalized_left and normalized_left == normalized_right)


def _normalize_information_need(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


def _is_general_answer_only(
    *, request: WorkflowStartRequest, goal_candidate: RequestGoalCandidateV1
) -> bool:
    return (
        not request.selected_resources
        and not goal_candidate["requested_effect_hints"]
        and not goal_candidate["requested_resource_hints"]
    )
