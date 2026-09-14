from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from pathlib import Path
from typing import Literal, cast

from google_work_agent.application.agents.request_understanding.contracts.request_intent import (
    RequestIntentV2,
    RequestUnderstandingValidationError,
    validated_gmail_draft_anchor,
)
from google_work_agent.application.agents.tool_routing.bind_registry_candidates import (
    coarse_resource_category,
    normalize_resource_type,
)
from google_work_agent.application.agents.tool_routing.contracts.semantic_route_candidate import (
    SemanticRouteCandidate,
)
from google_work_agent.application.agents.tool_routing.validate_route import (
    ToolRouteValidationError,
)
from google_work_agent.application.prompt_runtime.contracts.failure_record import (
    build_failure_record_v1,
)
from google_work_agent.application.prompt_runtime.prompt_registry import (
    default_prompt_manifest_path,
    load_prompt_reference,
)
from google_work_agent.application.tool_registry.signed_tool_registry import SignedToolRegistry
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
from google_work_agent.domain.action.model import EffectType
from google_work_agent.ports.llm.structured_inference_contracts import (
    OutputSchemaDefinition,
    PromptReference,
)
from google_work_agent.ports.llm.structured_inference_port import StructuredInferencePort
from google_work_agent.ports.system.contracts.confirmation import (
    ConfirmationResponseProjectionV1,
)
from google_work_agent.ports.system.contracts.workflow_execution import WorkflowStartRequest

ROUTE_RESOURCE_CANDIDATE_OUTPUT_SCHEMA = OutputSchemaDefinition(
    schema_version="route-resource-candidate-v1",
    json_schema={
        "type": "object",
        "additionalProperties": False,
        "required": [
            "schema_version",
            "input_resource_types",
            "output_resource_types",
            "output_effects",
            "disposition",
        ],
        "properties": {
            "schema_version": {"const": 1},
            "input_resource_types": {
                "type": "array",
                "items": {"enum": ["EMAIL", "TASK", "CALENDAR", "ISSUE"]},
                "uniqueItems": True,
            },
            "output_resource_types": {
                "type": "array",
                "items": {"enum": ["EMAIL", "TASK", "CALENDAR", "ISSUE"]},
                "uniqueItems": True,
            },
            "output_effects": {
                "type": "array",
                "items": {"enum": ["CREATE", "UPDATE", "SEND", "DELETE"]},
            },
            "disposition": {
                "enum": ["ROUTE_READY", "NO_TOOL_NEEDED", "NEEDS_CONFIRMATION", "BLOCKED"]
            },
        },
    },
)


def determine_io_resources(
    *,
    llm_runtime: StructuredInferencePort,
    tool_catalog: SignedToolRegistry,
    request_intent: RequestIntentV2,
    request: WorkflowStartRequest,
    retry_budget: RunBudgetV2,
    prompt_ref: PromptReference | None = None,
    manifest_path: Path | None = None,
    confirmation_response: ConfirmationResponseProjectionV1 | None = None,
) -> tuple[SemanticRouteCandidate, RunBudgetV2]:
    deterministic_candidate = _deterministic_candidate(
        request_intent=request_intent, request=request
    )
    if deterministic_candidate is not None:
        return deterministic_candidate, retry_budget
    resolved_prompt_ref = prompt_ref or load_prompt_reference(
        "tool_routing.determine_io_resources",
        manifest_path or default_prompt_manifest_path(),
    )
    base_projection: dict[str, object] = {
        "request_intent": request_intent,
        "eligible_route_capabilities": _eligible_route_capabilities(tool_catalog),
    }
    if confirmation_response is not None:
        base_projection["confirmation_response"] = dict(confirmation_response)
    output_schema = _output_schema_for_request_intent(request_intent)
    with provider_dispatch_budget_scope(retry_budget):
        result = llm_runtime.infer(
            request.requested_mode,
            resolved_prompt_ref,
            base_projection,
            output_schema,
        )
        try:
            candidate = _validated_semantic_candidate(
                result.structured_output,
                request_intent=request_intent,
                request=request,
            )
        except ToolRouteValidationError as error:
            failure_code = error.reason_code
            signature = build_semantic_failure_signature_v1(
                node_id="route.determine_resources", failure_reason_codes=[failure_code]
            )
            decision = approve_semantic_revision(retry_budget, signature=signature)
            if decision["decision"] == BudgetDecision.DENY.value:
                raise ToolRouteValidationError(
                    "tool route semantic candidate revision denied: "
                    "same failure signature already used"
                ) from error
            revised = llm_runtime.infer(
                request.requested_mode,
                resolved_prompt_ref,
                {
                    "base_projection": dict(base_projection),
                    "candidate_output": result.structured_output,
                    "failure_record": build_failure_record_v1(
                        failure_reason_code=failure_code,
                        failure_origin="LLM_OUTPUT",
                        detected_by="RUNTIME_DOMAIN_VALIDATOR",
                        runtime_disposition="RETRYABLE",
                        experiment_disposition="RUN_REVISION",
                        affected_field_paths=list(error.affected_field_paths)
                        or [
                            "$.input_resource_types",
                            "$.output_resource_types",
                            "$.output_effects",
                            "$.disposition",
                        ],
                        failure_context_ids=[str(error)],
                    ),
                },
                output_schema,
            )
            candidate = _validated_semantic_candidate(
                revised.structured_output,
                request_intent=request_intent,
                request=request,
            )
            retry_budget = decision["run_budget"]
        return candidate, merge_provider_dispatch_usage(retry_budget)


def _output_schema_for_request_intent(
    request_intent: RequestIntentV2,
) -> OutputSchemaDefinition:
    """Bind Tool Routing output effects to the validated request contract."""

    schema = deepcopy(ROUTE_RESOURCE_CANDIDATE_OUTPUT_SCHEMA.json_schema)
    properties = cast(dict[str, object], schema["properties"])
    requested_resource_categories = sorted(
        {
            coarse_resource_category(resource_type)
            for resource_type in request_intent["requested_resource_hints"]
        }
    )
    for field in ("input_resource_types", "output_resource_types"):
        resource_array = cast(dict[str, object], properties[field])
        resource_array["items"] = {"enum": requested_resource_categories}
    output_effects = cast(dict[str, object], properties["output_effects"])
    requested_write_effects = list(
        dict.fromkeys(
            effect
            for effect in request_intent["requested_effect_hints"]
            if effect != EffectType.READ.value
        )
    )
    if requested_write_effects:
        output_effects["items"] = {"enum": requested_write_effects}
    else:
        output_effects["maxItems"] = 0
    return OutputSchemaDefinition(
        schema_version=ROUTE_RESOURCE_CANDIDATE_OUTPUT_SCHEMA.schema_version,
        json_schema=schema,
    )


def requires_io_resource_inference(
    *, request_intent: RequestIntentV2, request: WorkflowStartRequest
) -> bool:
    """Return whether Tool Routing still has a semantic choice for the LLM."""
    return _deterministic_candidate(request_intent=request_intent, request=request) is None


def _deterministic_candidate(
    *, request_intent: RequestIntentV2, request: WorkflowStartRequest
) -> SemanticRouteCandidate | None:
    return (
        _selected_read_candidate(request_intent=request_intent, request=request)
        or _exact_intent_candidate(request_intent=request_intent, request=request)
        or _no_tool_candidate(request_intent=request_intent, request=request)
    )


def _exact_intent_candidate(
    *, request_intent: RequestIntentV2, request: WorkflowStartRequest
) -> SemanticRouteCandidate | None:
    if request_intent["ambiguity"]["requires_confirmation"]:
        return None
    responsibility_candidate = _resource_responsibility_candidate(request_intent)
    if responsibility_candidate is not None:
        return responsibility_candidate
    resource_types = tuple(dict.fromkeys(request_intent["requested_resource_hints"]))
    effect_values = tuple(dict.fromkeys(request_intent["requested_effect_hints"]))
    selected_types = _selected_input_resource_types(request)
    if selected_types:
        writes = tuple(effect for effect in effect_values if effect != "READ")
        if (
            len(resource_types) != 1
            or selected_types != resource_types
            or len(writes) != 1
            or writes[0] not in {"UPDATE", "DELETE"}
        ):
            return None
        return SemanticRouteCandidate(
            input_resource_types=selected_types,
            output_pairs=((resource_types[0], EffectType(writes[0])),),
            output_mode="ACTION",
            analysis_requirement=request_intent["analysis_requirement"],
            input_reason_codes=((resource_types[0], "RESOURCE_SELECTED"),),
        )
    if request.selected_resources:
        return None
    if (
        len(resource_types) == 2
        and set(resource_types) == {"GMAIL_THREAD", "GMAIL_MESSAGE"}
        and len(effect_values) == 2
        and set(effect_values) == {"READ", "SEND"}
    ):
        return SemanticRouteCandidate(
            input_resource_types=("GMAIL_THREAD",),
            output_pairs=(("GMAIL_MESSAGE", EffectType.SEND),),
            output_mode="ACTION",
            analysis_requirement=request_intent["analysis_requirement"],
            input_reason_codes=(("GMAIL_THREAD", "REQUESTED_INPUT"),),
        )
    if set(effect_values) == {"READ"}:
        resource_types = _collapse_gmail_search_inputs(resource_types)
    if len(resource_types) != 1:
        return None
    resource_type = resource_types[0]
    if effect_values == ("READ",):
        return SemanticRouteCandidate(
            input_resource_types=(resource_type,),
            output_pairs=(),
            output_mode="ANSWER",
            analysis_requirement=request_intent["analysis_requirement"],
        )
    write_effects = tuple(effect for effect in effect_values if effect != "READ")
    if len(write_effects) != 1:
        return None
    effect = EffectType(write_effects[0])
    allows_verification_read = (
        resource_type == "GMAIL_MESSAGE" and effect == EffectType.SEND
    ) or (
        resource_type == "GMAIL_DRAFT" and effect in {EffectType.UPDATE, EffectType.SEND}
    )
    if len(effect_values) != 1 and not (
        allows_verification_read and set(effect_values) == {"READ", effect.value}
    ):
        return None
    input_reason_codes: tuple[tuple[str, str], ...] = ()
    if resource_type == "GMAIL_THREAD":
        input_reason_codes = ((resource_type, "REQUESTED_INPUT"),)
    elif resource_type == "GMAIL_DRAFT" and effect in {EffectType.UPDATE, EffectType.SEND}:
        try:
            draft_id = validated_gmail_draft_anchor(request_intent)
        except RequestUnderstandingValidationError as error:
            raise ToolRouteValidationError(str(error)) from error
        input_reason_codes = (
            (
                resource_type,
                "EXPLICIT_RESOURCE_ID" if draft_id is not None else "REQUESTED_INPUT",
            ),
        )
    return SemanticRouteCandidate(
        input_resource_types=tuple(item[0] for item in input_reason_codes),
        output_pairs=(
            (
                _normalize_output_resource_type(coarse_resource_category(resource_type), effect),
                effect,
            ),
        ),
        output_mode="ACTION",
        analysis_requirement=request_intent["analysis_requirement"],
        input_reason_codes=input_reason_codes,
    )


def _resource_responsibility_candidate(
    request_intent: RequestIntentV2,
) -> SemanticRouteCandidate | None:
    responsibilities = request_intent.get("resource_responsibilities")
    if not responsibilities:
        return None
    input_resources = _collapse_gmail_search_inputs(tuple(
        item["resource_type"] for item in responsibilities["source_reads"]
    ))
    output_pairs = tuple(
        (item["resource_type"], EffectType(item["effect"]))
        for item in responsibilities["outputs"]
    )
    return SemanticRouteCandidate(
        input_resource_types=input_resources,
        output_pairs=output_pairs,
        output_mode="ACTION" if output_pairs else "ANSWER",
        analysis_requirement=request_intent["analysis_requirement"],
        input_reason_codes=tuple(
            (resource_type, "REQUESTED_INPUT") for resource_type in input_resources
        ),
    )


def _collapse_gmail_search_inputs(resource_types: tuple[str, ...]) -> tuple[str, ...]:
    """Use the searchable Thread route when Message and Thread describe one Gmail READ."""

    unique = tuple(dict.fromkeys(resource_types))
    if {"GMAIL_THREAD", "GMAIL_MESSAGE"}.issubset(unique):
        return tuple(item for item in unique if item != "GMAIL_MESSAGE")
    return unique


def _selected_read_candidate(
    *,
    request_intent: RequestIntentV2,
    request: WorkflowStartRequest,
) -> SemanticRouteCandidate | None:
    selected_input_resources = _selected_input_resource_types(request)
    if not selected_input_resources or set(request_intent["requested_effect_hints"]) != {"READ"}:
        return None
    return SemanticRouteCandidate(
        input_resource_types=selected_input_resources,
        output_pairs=(),
        output_mode="ANSWER",
        analysis_requirement=request_intent["analysis_requirement"],
        input_reason_codes=tuple(
            (resource_type, "RESOURCE_SELECTED") for resource_type in selected_input_resources
        ),
    )


def _no_tool_candidate(
    *, request_intent: RequestIntentV2, request: WorkflowStartRequest
) -> SemanticRouteCandidate | None:
    if (
        request.selected_resources
        or request_intent["requested_resource_hints"]
        or request_intent["requested_effect_hints"]
    ):
        return None
    return SemanticRouteCandidate(
        input_resource_types=(),
        output_pairs=(),
        output_mode="ANSWER",
        analysis_requirement=request_intent["analysis_requirement"],
    )


def _validated_semantic_candidate(
    value: object,
    *,
    request_intent: RequestIntentV2,
    request: WorkflowStartRequest,
) -> SemanticRouteCandidate:
    raw = _validate_candidate(value)
    if raw["disposition"] in {"NEEDS_CONFIRMATION", "BLOCKED"}:
        raise ToolRouteValidationError(
            f"tool route semantic candidate is not ready: {raw['disposition']}",
            reason_code="TOOL_ROUTE_OVERCONFIRMATION",
            affected_field_paths=("$.disposition",),
        )
    return _semantic_candidate(raw, request_intent=request_intent, request=request)


def _semantic_candidate(
    raw: Mapping[str, object],
    *,
    request_intent: RequestIntentV2,
    request: WorkflowStartRequest,
) -> SemanticRouteCandidate:
    inferred_input_resources = tuple(
        dict.fromkeys(
            normalize_resource_type(cast(str, item))
            for item in cast(list[object], raw["input_resource_types"])
        )
    )
    selected_input_resources = _selected_input_resource_types(request)
    if selected_input_resources and {
        coarse_resource_category(resource) for resource in selected_input_resources
    } != {coarse_resource_category(resource) for resource in inferred_input_resources}:
        raise ToolRouteValidationError(
            "RESOURCE_SELECTED input scope does not match the semantic route candidate",
            reason_code="TOOL_ROUTE_FORBIDDEN_INPUT_INCLUDED",
            affected_field_paths=("$.input_resource_types",),
        )
    input_resources = selected_input_resources or inferred_input_resources
    raw_output_resources = cast(list[str], raw["output_resource_types"])
    output_effects = tuple(
        EffectType(cast(str, item)) for item in cast(list[object], raw["output_effects"])
    )
    if raw["disposition"] == "NO_TOOL_NEEDED" and input_resources:
        raise ToolRouteValidationError(
            "NO_TOOL_NEEDED cannot retain input resource routes",
            reason_code="TOOL_ROUTE_FORBIDDEN_INPUT_INCLUDED",
            affected_field_paths=("$.input_resource_types",),
        )
    if raw["disposition"] == "NO_TOOL_NEEDED" and (
        raw_output_resources or output_effects
    ):
        raise ToolRouteValidationError(
            "NO_TOOL_NEEDED cannot retain output resource routes",
            reason_code="TOOL_ROUTE_OUTPUT_MODE_WRONG",
            affected_field_paths=("$.output_resource_types", "$.output_effects"),
        )
    requested_write_effects = {
        EffectType(item)
        for item in request_intent["requested_effect_hints"]
        if item != EffectType.READ.value
    }
    if not requested_write_effects:
        raw_output_resources = []
        output_effects = ()
    elif set(output_effects) != requested_write_effects:
        raise ToolRouteValidationError(
            "tool route output effects do not preserve the validated RequestIntent",
            reason_code="TOOL_ROUTE_EFFECT_MISMATCH",
            affected_field_paths=("$.output_effects",),
        )
    elif raw["disposition"] == "NO_TOOL_NEEDED":
        raise ToolRouteValidationError(
            "write RequestIntent cannot be downgraded to NO_TOOL_NEEDED",
            reason_code="TOOL_ROUTE_OUTPUT_MODE_WRONG",
            affected_field_paths=("$.disposition",),
        )
    elif not raw_output_resources or not output_effects:
        raise ToolRouteValidationError(
            "write RequestIntent requires a matching output resource and effect",
            reason_code="TOOL_ROUTE_REQUIRED_OUTPUT_MISSING",
            affected_field_paths=("$.output_resource_types", "$.output_effects"),
        )
    if not raw_output_resources or raw["disposition"] == "NO_TOOL_NEEDED":
        output_mode: Literal["ANSWER", "ACTION"] = "ANSWER"
        output_pairs: tuple[tuple[str, EffectType], ...] = ()
    else:
        output_mode = "ACTION"
        if len(output_effects) == 1:
            output_pairs = tuple(
                (_normalize_output_resource_type(resource, output_effects[0]), output_effects[0])
                for resource in raw_output_resources
            )
        elif len(output_effects) == len(raw_output_resources):
            output_pairs = tuple(
                (_normalize_output_resource_type(resource, effect), effect)
                for resource, effect in zip(raw_output_resources, output_effects, strict=True)
            )
        else:
            raise ToolRouteValidationError(
                "resource/effect candidate cardinality is ambiguous",
                reason_code="TOOL_ROUTE_EFFECT_MISMATCH",
                affected_field_paths=("$.output_resource_types", "$.output_effects"),
            )
    requested_resource_categories = {
        coarse_resource_category(resource_type)
        for resource_type in request_intent["requested_resource_hints"]
    }
    candidate_resource_categories = {
        coarse_resource_category(resource_type) for resource_type in input_resources
    } | {coarse_resource_category(resource_type) for resource_type, _effect in output_pairs}
    if candidate_resource_categories != requested_resource_categories:
        raise ToolRouteValidationError(
            "tool route resources do not preserve the validated RequestIntent",
            reason_code="TOOL_ROUTE_RESOURCE_MISMATCH",
            affected_field_paths=("$.input_resource_types", "$.output_resource_types"),
        )
    read_requested = "READ" in request_intent["requested_effect_hints"]
    if read_requested != bool(input_resources):
        raise ToolRouteValidationError(
            "tool route input resources do not preserve the validated READ responsibility",
            reason_code="TOOL_ROUTE_RESOURCE_MISMATCH",
            affected_field_paths=("$.input_resource_types",),
        )
    analysis_requirement = request_intent.get("analysis_requirement", "REQUIRED")
    if analysis_requirement not in {"NONE", "REQUIRED"}:
        raise ToolRouteValidationError("analysis_requirement is invalid")
    return SemanticRouteCandidate(
        input_resource_types=input_resources,
        output_pairs=output_pairs,
        output_mode=output_mode,
        analysis_requirement=cast(Literal["NONE", "REQUIRED"], analysis_requirement),
        input_reason_codes=tuple(
            (resource_type, "RESOURCE_SELECTED") for resource_type in selected_input_resources
        ),
    )


def _selected_input_resource_types(request: WorkflowStartRequest) -> tuple[str, ...]:
    if request.entry_mode != "RESOURCE_SELECTED":
        return ()
    mapping = {
        ("google_workspace", "gmail_thread"): "GMAIL_THREAD",
        ("google_workspace", "gmail_message"): "GMAIL_MESSAGE",
        ("google_workspace", "gmail_draft"): "GMAIL_DRAFT",
        ("google_workspace", "gmail_attachment"): "GMAIL_ATTACHMENT",
        ("google_workspace", "task_list"): "TASK_LIST",
        ("google_workspace", "task"): "TASK",
        ("google_workspace", "calendar"): "CALENDAR",
        ("google_workspace", "calendar_event"): "CALENDAR_EVENT",
        ("google_workspace", "calendar_freebusy"): "CALENDAR_FREEBUSY",
        ("github", "github_issue"): "GITHUB_ISSUE",
    }
    try:
        return tuple(
            dict.fromkeys(
                mapping[(resource.connector_id, resource.resource_type)]
                for resource in request.selected_resources
            )
        )
    except KeyError as error:
        raise ToolRouteValidationError(
            "RESOURCE_SELECTED contains an unsupported resource identity"
        ) from error


def _validate_candidate(value: object) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ToolRouteValidationError("RouteResourceCandidateV1 must be an object")
    root = cast(Mapping[str, object], value)
    if root.get("schema_version") != 1:
        raise ToolRouteValidationError("RouteResourceCandidateV1.schema_version must be 1")
    for field in ("input_resource_types", "output_resource_types"):
        items = root.get(field)
        if not isinstance(items, list) or any(
            item not in {"EMAIL", "TASK", "CALENDAR", "ISSUE"} for item in items
        ):
            raise ToolRouteValidationError(f"RouteResourceCandidateV1.{field} is invalid")
    effects = root.get("output_effects")
    if not isinstance(effects, list) or any(
        item not in {"CREATE", "UPDATE", "SEND", "DELETE"} for item in effects
    ):
        raise ToolRouteValidationError("RouteResourceCandidateV1.output_effects is invalid")
    if root.get("disposition") not in {
        "ROUTE_READY",
        "NO_TOOL_NEEDED",
        "NEEDS_CONFIRMATION",
        "BLOCKED",
    }:
        raise ToolRouteValidationError("RouteResourceCandidateV1.disposition is invalid")
    return root


def _eligible_route_capabilities(tool_catalog: SignedToolRegistry) -> list[dict[str, object]]:
    by_key: dict[tuple[str, str], dict[str, object]] = {}
    for entry in tool_catalog.entries:
        connector_id = entry.connector_id
        category = coarse_resource_category(entry.resource_type)
        capability = by_key.setdefault(
            (connector_id, category),
            {
                "connector_id": connector_id,
                "resource_type": category,
                "read_supported": False,
                "write_effects": [],
            },
        )
        if entry.effect_type is EffectType.READ:
            capability["read_supported"] = True
        else:
            write_effects = cast(list[str], capability["write_effects"])
            if entry.effect_type.value not in write_effects:
                write_effects.append(entry.effect_type.value)
    return list(by_key.values())


def _normalize_output_resource_type(coarse_resource: str, effect: EffectType) -> str:
    if coarse_resource == "EMAIL":
        if effect is EffectType.SEND:
            return "GMAIL_MESSAGE"
        if effect in {EffectType.CREATE, EffectType.UPDATE}:
            return "GMAIL_DRAFT"
    if coarse_resource == "ISSUE":
        return "GITHUB_ISSUE"
    return normalize_resource_type(coarse_resource)
