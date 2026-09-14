from __future__ import annotations

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
from google_work_agent.application.prompt_runtime.prompt_registry import (
    default_prompt_manifest_path,
    load_prompt_reference,
)
from google_work_agent.application.use_cases.run.account_provider_dispatch import (
    merge_provider_dispatch_usage,
    provider_dispatch_budget_scope,
)
from google_work_agent.application.use_cases.run.guard_run_budget import (
    RunBudgetV2,
)
from google_work_agent.ports.llm.structured_inference_contracts import (
    OutputSchemaDefinition,
    PromptReference,
)
from google_work_agent.ports.llm.structured_inference_port import StructuredInferencePort
from google_work_agent.ports.system.contracts.confirmation import (
    ConfirmationResponseProjectionV1,
)
from google_work_agent.ports.system.contracts.workflow_execution import (
    SelectedResourceRef,
    WorkflowStartRequest,
)

from .identify_source_dependencies import resource_identity_fact_kind

_SEARCHABLE_TARGET_ANCHOR_FIELDS = frozenset({"search_terms", "subject", "search_criteria_subject"})


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
                    "NONE when nothing is missing; USER when the target identity itself "
                    "still requires a user choice; CONNECTOR only for target attributes "
                    "retrievable after the target is selected or explicitly identifiable "
                    "from current-request constraints."
                ),
            },
            "missing_fields": {
                "type": "array",
                "items": {"type": "string", "minLength": 1},
                "description": (
                    "Empty for NONE; non-empty for USER or CONNECTOR-owned missing information. "
                    "Use target_resource for a USER-owned unresolved target identity."
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
    resolved_prompt_ref = prompt_ref or load_prompt_reference(
        "request_understanding.detect_ambiguity",
        manifest_path or default_prompt_manifest_path(),
    )
    resolution_responsibilities = _resolution_responsibilities(
        goal_candidate=goal_candidate,
        request=request,
    )
    prompt_input: dict[str, object] = {
        "user_request": request.request_text,
        "goal_candidate": _ambiguity_goal_candidate_projection(goal_candidate),
        "resolution_responsibilities": resolution_responsibilities,
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
        candidate = _validate_ambiguity_candidate(
            result.structured_output,
            goal_candidate=goal_candidate,
            selected_resources=request.selected_resources,
        )
        retry_budget = merge_provider_dispatch_usage(retry_budget)
    return _finalize_ambiguity_candidate(candidate), retry_budget


def _ambiguity_goal_candidate_projection(
    goal_candidate: RequestGoalCandidateV1,
) -> dict[str, object]:
    projection: dict[str, object] = {
        "goal": goal_candidate["goal"],
        "completion_conditions": list(goal_candidate["completion_conditions"]),
        "constraints": [dict(item) for item in goal_candidate["constraints"]],
    }
    resource_responsibilities = goal_candidate.get("resource_responsibilities")
    if resource_responsibilities is not None:
        projection["resource_responsibilities"] = {
            "source_reads": [
                {
                    "resource_type": item["resource_type"],
                    "required_information": list(item["required_information"]),
                }
                for item in resource_responsibilities["source_reads"]
            ],
            "outputs": [dict(item) for item in resource_responsibilities["outputs"]],
        }
    return projection


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
    selected_resources: Sequence[SelectedResourceRef],
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
    target_identity_resource_types = _target_identity_resource_types(
        missing_fields,
        goal_candidate=goal_candidate,
    )
    if (
        missing_information_owner == "USER"
        and ("target_resource" in missing_fields or target_identity_resource_types)
        and _selected_target_identity_is_resolved(
            goal_candidate,
            selected_resources=selected_resources,
            resource_specific_target_types=frozenset(
                resource_type
                for resource_types in target_identity_resource_types.values()
                for resource_type in resource_types
            ),
        )
    ):
        raise RequestAmbiguityValidationError(
            "a selected current-run target was reclassified as unresolved",
            reason_code="REQUEST_AMBIGUITY_TARGET_ANCHOR_CONFLICT",
            affected_field_paths=(
                "$.missing_information_owner",
                "$.missing_fields",
                "$.selected_resource_refs",
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
        "searchable_target_anchor_count": _searchable_target_anchor_count(goal_candidate),
        "connector_owned_source_count": _connector_owned_source_count(goal_candidate),
    }


def _searchable_target_anchor_count(goal_candidate: RequestGoalCandidateV1) -> int:
    return sum(
        1
        for constraint in goal_candidate["constraints"]
        if constraint["field"] in _SEARCHABLE_TARGET_ANCHOR_FIELDS and bool(constraint["value"])
    )


def _connector_owned_source_count(goal_candidate: RequestGoalCandidateV1) -> int:
    responsibilities = goal_candidate.get("resource_responsibilities")
    return 0 if responsibilities is None else len(responsibilities["source_reads"])


def _target_identity_resource_types(
    missing_fields: Sequence[str],
    *,
    goal_candidate: RequestGoalCandidateV1,
) -> dict[str, frozenset[str]]:
    responsibilities = goal_candidate.get("resource_responsibilities")
    if not responsibilities:
        return {}
    identity_resource_types: dict[str, set[str]] = {}
    for source_read in responsibilities["source_reads"]:
        resource_type = source_read["resource_type"].strip().upper()
        identity_fact_kind = resource_identity_fact_kind(resource_type)
        if identity_fact_kind is None or identity_fact_kind not in missing_fields:
            continue
        identity_resource_types.setdefault(identity_fact_kind, set()).add(resource_type)
    return {
        field: frozenset(resource_types)
        for field, resource_types in identity_resource_types.items()
    }


def _selected_target_identity_is_resolved(
    goal_candidate: RequestGoalCandidateV1,
    *,
    selected_resources: Sequence[SelectedResourceRef],
    resource_specific_target_types: frozenset[str],
) -> bool:
    selected_types = {
        item.resource_type.strip().upper()
        for item in selected_resources
        if item.resource_type.strip()
    }
    if not selected_types:
        return False
    if resource_specific_target_types:
        return bool(selected_types & resource_specific_target_types)
    requested_types = {
        item.strip().upper() for item in goal_candidate["requested_resource_hints"] if item.strip()
    }
    return not requested_types or requested_types.issubset(selected_types)


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
