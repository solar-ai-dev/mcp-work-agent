from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

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


def _bound_tool_selection_output_schema(
    *, route_id: str, eligible_tool_ids: tuple[str, ...]
) -> OutputSchemaDefinition:
    return OutputSchemaDefinition(
        schema_version="tool-selection-v1",
        json_schema={
            "type": "object",
            "additionalProperties": False,
            "required": ["schema_version", "route_id", "selected_tool_id"],
            "properties": {
                "schema_version": {"const": 1},
                "route_id": {"const": route_id},
                "selected_tool_id": {"enum": list(eligible_tool_ids)},
            },
        },
    )


def select_tool_if_needed(
    *,
    llm_runtime: StructuredInferencePort,
    route_id: str,
    connector_id: str,
    resource_type: str,
    effect: str,
    eligible_tool_ids: tuple[str, ...],
    request: WorkflowStartRequest,
    retry_budget: RunBudgetV2,
    prompt_ref: PromptReference | None = None,
    manifest_path: Path | None = None,
    confirmation_response: ConfirmationResponseProjectionV1 | None = None,
) -> tuple[str, RunBudgetV2]:
    if len(eligible_tool_ids) == 1:
        return eligible_tool_ids[0], retry_budget
    if not eligible_tool_ids:
        raise ToolRouteValidationError("tool selection requires Registry-eligible candidates")
    resolved_prompt_ref = prompt_ref or load_prompt_reference(
        "tool_routing.select_tool_if_needed",
        manifest_path or default_prompt_manifest_path(),
    )
    output_schema = _bound_tool_selection_output_schema(
        route_id=route_id,
        eligible_tool_ids=eligible_tool_ids,
    )
    base_projection: dict[str, object] = {
        "user_request": request.request_text,
        "route_candidate": {
            "route_id": route_id,
            "connector_id": connector_id,
            "resource_type": resource_type,
            "effect": effect,
        },
        "registered_candidates": [{"tool_id": tool_id} for tool_id in eligible_tool_ids],
    }
    if confirmation_response is not None:
        base_projection["confirmation_response"] = dict(confirmation_response)
    with provider_dispatch_budget_scope(retry_budget):
        result = llm_runtime.infer(
            request.requested_mode,
            resolved_prompt_ref,
            base_projection,
            output_schema,
        )
        selected = _validated_selection(
            result.structured_output,
            route_id=route_id,
            eligible_tool_ids=eligible_tool_ids,
        )
        if selected is not None:
            return selected, merge_provider_dispatch_usage(retry_budget)
        failure_code = "TOOL_SELECTION_INVALID"
        signature = build_semantic_failure_signature_v1(
            node_id="route.select_tool", failure_reason_codes=[failure_code]
        )
        decision = approve_semantic_revision(retry_budget, signature=signature)
        if decision["decision"] == BudgetDecision.DENY.value:
            raise ToolRouteValidationError(
                "tool selection revision denied: same failure signature already used"
            )
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
                    affected_field_paths=["$.route_id", "$.selected_tool_id"],
                    failure_context_ids=[
                        "selection must preserve route_id and choose a Registry-eligible tool"
                    ],
                ),
            },
            output_schema,
        )
        selected = _validated_selection(
            revised.structured_output,
            route_id=route_id,
            eligible_tool_ids=eligible_tool_ids,
        )
        if selected is None:
            raise ToolRouteValidationError(
                "selected tool is not a Registry-eligible candidate after revision"
            )
        return selected, merge_provider_dispatch_usage(decision["run_budget"])


def _validated_selection(
    value: object,
    *,
    route_id: str,
    eligible_tool_ids: tuple[str, ...],
) -> str | None:
    if not isinstance(value, Mapping) or value.get("schema_version") != 1:
        return None
    if value.get("route_id") != route_id:
        return None
    selected = value.get("selected_tool_id")
    return selected if isinstance(selected, str) and selected in eligible_tool_ids else None
