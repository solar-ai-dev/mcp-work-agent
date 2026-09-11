"""The sole production API/local structured-inference runtime binding."""

from __future__ import annotations

import re
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, cast

from google_work_agent.adapters.llm.runtime.llm_credential_router import LlmCredentialRouter
from google_work_agent.adapters.llm.runtime.llm_runtime_status_router import LlmRuntimeStatusRouter
from google_work_agent.ports.llm.local_model_catalog_unavailable_error import (
    LocalModelCatalogUnavailableError,
)
from google_work_agent.ports.llm.output_schema_validation import validate_output_schema
from google_work_agent.ports.llm.runtime_selection import LlmRuntimeSelectionV1
from google_work_agent.ports.llm.structured_inference_contracts import (
    ActualRuntime,
    ApprovedModelInfo,
    AvailabilityState,
    HardwareCapability,
    HardwareCapabilityStatus,
    LLMCredentialState,
    LLMErrorCode,
    LLMInvocationError,
    OutputSchemaDefinition,
    ProbeResult,
    PromptReference,
    RequestedRuntimeMode,
    RouteDecision,
    RouteDecisionInput,
    RuntimePolicy,
    SchemaRepairer,
    StructuredLLMProvider,
    StructuredLLMResult,
)
from google_work_agent.ports.llm.structured_inference_port import StructuredInferenceResultV1
from google_work_agent.ports.system.checkpoint_port import CheckpointPort
from google_work_agent.ports.system.contracts.external_llm_transfer_scope import (
    ExternalLlmTransferScopeV1,
)
from google_work_agent.ports.system.contracts.observability import (
    LLMEventRecorder,
    ObservabilityContext,
    Severity,
)
from google_work_agent.ports.system.external_call_trace_port import (
    ExternalCallKind,
    ExternalCallTraceFinishV1,
    ExternalCallTraceHandleV1,
    ExternalCallTracePort,
    ExternalCallTraceStartV1,
)
from google_work_agent.ports.system.hardware_probe_port import HardwareProbePort
from google_work_agent.ports.system.settings_port import SettingsViewV1


@dataclass(frozen=True, slots=True)
class NullLLMEventRecorder:
    def record(self, **kwargs: object) -> None:
        del kwargs


@dataclass
class StructuredInferenceRuntimeRouter:
    """Select API/Ollama leaves and preserve fallback only for legacy AUTO runs."""

    settings_service: Callable[[], SettingsViewV1]
    runtime_selection: LlmRuntimeSelectionV1
    status_service: LlmRuntimeStatusRouter
    credential_service: LlmCredentialRouter
    hardware_probe: HardwareProbePort
    api_provider_name: str
    api_provider: StructuredLLMProvider
    ollama_provider_factory: Callable[[ApprovedModelInfo], StructuredLLMProvider]
    runtime_policy: RuntimePolicy
    event_recorder: LLMEventRecorder = NullLLMEventRecorder()
    schema_repairer: SchemaRepairer | None = None
    prompt_manifest_path: Path | None = None
    checkpoint: CheckpointPort | None = None
    before_provider_dispatch: Callable[[], None] = lambda: None
    before_runtime_dispatch: Callable[[ActualRuntime], None] = lambda _runtime: None
    run_context_provider: Callable[[], str | None] = lambda: None
    external_call_trace: ExternalCallTracePort | None = None
    record_runtime_result: Callable[[ActualRuntime, str | None], None] = (
        lambda _runtime, _error_code: None
    )
    external_scope_projector: (
        Callable[[str, tuple[str, ...], tuple[str, ...]], ExternalLlmTransferScopeV1] | None
    ) = None

    def __post_init__(self) -> None:
        self._api_leaf: StructuredLLMProvider = self.api_provider

    def get_approved_model(self, model_id: str) -> ApprovedModelInfo | None:
        """Expose the router-owned approved-model lookup to tool-call orchestration."""

        return self.status_service.get_approved_model(model_id)

    def get_runtime_status(self) -> dict[str, object]:
        """Project the router's canonical local-runtime facts for tool calls."""

        hardware = self.hardware_probe.probe()
        capability_status = (
            HardwareCapabilityStatus.VALIDATED
            if hardware.local_runtime_eligible
            else HardwareCapabilityStatus.NOT_VALIDATED
        )
        return {
            "ollama": {
                "availability": self.status_service.get_status("ollama").availability,
                "hardware_capability": {
                    "cpu_arch": hardware.architecture,
                    "core_summary": str(hardware.cpu_logical_cores),
                    "memory_bytes": hardware.ram_total_bytes,
                    "gpu_present": hardware.gpu_present,
                    "gpu_vendor": None,
                    "gpu_name": hardware.gpu_name,
                    "gpu_memory_bytes": hardware.vram_total_bytes,
                    "capability_status": capability_status.value,
                    "safe_reason_codes": hardware.local_runtime_reason_codes,
                },
            }
        }

    def infer(
        self,
        requested_mode: Literal["AUTO", "LOCAL_GPU", "API_LLM"],
        prompt_ref: PromptReference,
        input_projection: Mapping[str, object],
        output_schema_ref: OutputSchemaDefinition,
    ) -> StructuredInferenceResultV1:
        settings = self.settings_service()
        requested = RequestedRuntimeMode(requested_mode)
        uses_local_runtime = requested is not RequestedRuntimeMode.API_LLM
        uses_api_runtime = requested is not RequestedRuntimeMode.LOCAL_GPU
        approved_model, hardware_capability = self._local_runtime_inputs(
            prompt_id=prompt_ref.prompt_id,
            required=uses_local_runtime,
        )
        api_status = (
            self.status_service.get_status(self.api_provider_name)
            if uses_api_runtime
            else None
        )
        credential = (
            self.credential_service.get_credential_status(self.api_provider_name)
            if uses_api_runtime
            else None
        )
        decision = self.decide(
            RouteDecisionInput(
                build_profile=self.runtime_selection.deployment_profile,
                requested_mode=requested,
                external_llm_consent=settings.external_llm_consent,
                api_credential_state=(
                    LLMCredentialState.KEYRING
                    if credential is not None and credential.storage_mode == "KEYRING"
                    else LLMCredentialState.SESSION_MEMORY
                    if credential is not None and credential.storage_mode == "SESSION_ONLY"
                    else LLMCredentialState.UNAVAILABLE
                    if credential is not None and credential.validation_status == "UNAVAILABLE"
                    else LLMCredentialState.NOT_CONFIGURED
                ),
                api_probe=ProbeResult(
                    availability=(
                        AvailabilityState.AVAILABLE
                        if api_status is not None and api_status.availability == "READY"
                        else AvailabilityState.NOT_APPLICABLE
                        if api_status is None
                        else AvailabilityState.UNAVAILABLE
                    ),
                    safe_error_code=None if api_status is None else api_status.error_code,
                ),
                hardware_capability=hardware_capability,
                ollama_probe=ProbeResult(
                    availability=(
                        AvailabilityState.AVAILABLE
                        if hardware_capability.capability_status
                        is HardwareCapabilityStatus.VALIDATED
                        else AvailabilityState.NOT_APPLICABLE
                        if not uses_local_runtime
                        else AvailabilityState.UNAVAILABLE
                    ),
                    safe_error_code=next(iter(hardware_capability.safe_reason_codes), None),
                ),
                approved_model=approved_model,
            )
        )
        trace_context = ObservabilityContext(run_id=self.run_context_provider())
        external_transfer_scope = self._project_external_scope(
            requested_mode=requested,
            prompt_input=input_projection,
            trace_context=trace_context,
        )
        self._record_selection(
            prompt_ref=prompt_ref,
            trace_context=trace_context,
            requested_mode=requested,
            decision=decision,
            selected_model_id=(
                approved_model.model_id
                if decision.primary_runtime is ActualRuntime.LOCAL_GPU
                and approved_model is not None
                else None
            ),
        )
        if decision.safe_reason_code == LLMErrorCode.RUNTIME_MODE_BLOCKED.value:
            raise LLMInvocationError(
                LLMErrorCode.RUNTIME_MODE_BLOCKED,
                "requested runtime mode is disabled by the release profile",
                runtime_prerequisite=True,
            )
        try:
            provider = self._resolve_provider(
                runtime=decision.primary_runtime,
                settings=settings,
                approved_model=approved_model,
                hardware_capability=hardware_capability,
            )
            result = self._invoke_provider(
                provider=provider,
                prompt_ref=prompt_ref,
                prompt_input=input_projection,
                output_schema=output_schema_ref,
                requested_mode=requested,
                trace_context=trace_context,
                fallback_reason=None,
                semantic_validate=None,
                external_transfer_scope=external_transfer_scope,
                selected_model_id=(
                    approved_model.model_id
                    if decision.primary_runtime is ActualRuntime.LOCAL_GPU
                    and approved_model is not None
                    else None
                ),
            )
            return _canonical_result(result)

        except LLMInvocationError as error:
            if not self._should_fallback(
                error=error,
                decision=decision,
                requested_mode=requested,
                settings=settings,
            ):
                raise
            self._record_fallback_started(
                trace_context=trace_context,
                requested_mode=requested,
                decision=decision,
                error=error,
            )
            result = self._invoke_provider(
                provider=self._resolve_provider(
                    runtime=ActualRuntime.API_LLM,
                    settings=settings,
                    approved_model=approved_model,
                    hardware_capability=hardware_capability,
                ),
                prompt_ref=prompt_ref,
                prompt_input=input_projection,
                output_schema=output_schema_ref,
                requested_mode=requested,
                trace_context=trace_context,
                fallback_reason=error.code.value,
                semantic_validate=None,
                external_transfer_scope=external_transfer_scope,
                selected_model_id=None,
            )
            self.event_recorder.record(
                event_name="LLM_FALLBACK_COMPLETED",
                severity=Severity.INFO,
                correlation=trace_context,
                attributes={
                    "requested_mode": requested.value,
                    "fallback_reason": error.code.value,
                    "actual_runtime": result.actual_runtime.value,
                    "provider": result.provider,
                    "model": result.model,
                },
                result_code="FALLBACK_COMPLETED",
                status="COMPLETED",
            )
            return _canonical_result(result)

    def _local_runtime_inputs(
        self,
        *,
        prompt_id: str,
        required: bool,
    ) -> tuple[ApprovedModelInfo | None, HardwareCapability]:
        if not required:
            return None, HardwareCapability(
                cpu_arch="NOT_APPLICABLE",
                core_summary="NOT_APPLICABLE",
                memory_bytes=None,
                gpu_present=False,
                gpu_vendor=None,
                gpu_name=None,
                gpu_memory_bytes=None,
                capability_status=HardwareCapabilityStatus.NOT_APPLICABLE,
                safe_reason_codes=(),
            )
        try:
            approved_model = self.status_service.get_model_for_prompt(prompt_id)
            hardware = self.hardware_probe.probe()
        except LocalModelCatalogUnavailableError as error:
            raise LLMInvocationError(
                LLMErrorCode.LOCAL_UNAVAILABLE,
                error.safe_error_code,
                runtime_prerequisite=True,
            ) from error
        return approved_model, HardwareCapability(
            cpu_arch=hardware.architecture,
            core_summary=str(hardware.cpu_logical_cores),
            memory_bytes=hardware.ram_total_bytes,
            gpu_present=hardware.gpu_present,
            gpu_vendor=None,
            gpu_name=hardware.gpu_name,
            gpu_memory_bytes=hardware.vram_total_bytes,
            capability_status=(
                HardwareCapabilityStatus.VALIDATED
                if hardware.local_runtime_eligible
                else HardwareCapabilityStatus.NOT_VALIDATED
            ),
            safe_reason_codes=hardware.local_runtime_reason_codes,
        )

    def discard_run(self, *, run_id: str) -> None:
        """Run budgets live in checkpointed workflow state, not this router."""

        del run_id

    def test_connection(self) -> dict[str, object]:
        settings = self.settings_service()
        if (
            RequestedRuntimeMode(settings.preferred_llm_mode) is RequestedRuntimeMode.API_LLM
            and not settings.external_llm_consent
        ):
            raise LLMInvocationError(
                LLMErrorCode.CONSENT_REQUIRED,
                "external LLM consent is disabled",
            )
        return self.get_runtime_status()

    def _project_external_scope(
        self,
        *,
        requested_mode: RequestedRuntimeMode,
        prompt_input: Mapping[str, object],
        trace_context: ObservabilityContext,
    ) -> ExternalLlmTransferScopeV1 | None:
        if (
            requested_mode is RequestedRuntimeMode.LOCAL_GPU
            or trace_context.run_id is None
            or self.external_scope_projector is None
        ):
            return None
        source_kinds = tuple(sorted(str(key) for key in prompt_input)) or ("PROMPT_INPUT",)
        return self.external_scope_projector(
            trace_context.run_id,
            source_kinds,
            _external_data_classes(source_kinds),
        )

    def decide(self, request: RouteDecisionInput) -> RouteDecision:
        """Preserved deterministic requested-mode and availability rules."""
        if request.build_profile == "API_ONLY":
            if request.requested_mode is not RequestedRuntimeMode.API_LLM:
                return _decision(
                    ActualRuntime.API_LLM,
                    False,
                    LLMErrorCode.RUNTIME_MODE_BLOCKED.value,
                )
            if not request.external_llm_consent:
                return _decision(ActualRuntime.API_LLM, False, "CONSENT_REQUIRED")
            return _decision(ActualRuntime.API_LLM, False, None)
        if request.requested_mode is RequestedRuntimeMode.API_LLM:
            if not request.external_llm_consent:
                return _decision(ActualRuntime.API_LLM, False, "CONSENT_REQUIRED")
            return _decision(ActualRuntime.API_LLM, False, None)
        if request.requested_mode is RequestedRuntimeMode.LOCAL_GPU:
            return _decision(ActualRuntime.LOCAL_GPU, False, _local_runtime_reason(request))
        fallback_allowed = (
            request.external_llm_consent
            and request.api_credential_state
            in {LLMCredentialState.KEYRING, LLMCredentialState.SESSION_MEMORY}
            and request.api_probe.availability
            in {AvailabilityState.AVAILABLE, AvailabilityState.UNKNOWN}
        )
        return RouteDecision(
            primary_runtime=ActualRuntime.LOCAL_GPU,
            fallback_allowed=fallback_allowed,
            fallback_target=ActualRuntime.API_LLM if fallback_allowed else None,
            safe_reason_code=_local_runtime_reason(request),
        )

    def _resolve_provider(
        self,
        *,
        runtime: ActualRuntime,
        settings: SettingsViewV1,
        approved_model: ApprovedModelInfo | None,
        hardware_capability: HardwareCapability,
    ) -> StructuredLLMProvider:
        if runtime is ActualRuntime.API_LLM:
            if not settings.external_llm_consent:
                raise LLMInvocationError(
                    LLMErrorCode.CONSENT_REQUIRED,
                    "external LLM consent is disabled",
                    runtime_prerequisite=True,
                )
            if self.credential_service.read_secret(self.api_provider_name) is None:
                raise LLMInvocationError(
                    LLMErrorCode.API_KEY_MISSING,
                    "LLM API key is not configured",
                    runtime_prerequisite=True,
                )
            return self._api_leaf
        if hardware_capability.capability_status is not HardwareCapabilityStatus.VALIDATED:
            raise LLMInvocationError(
                LLMErrorCode.LOCAL_UNAVAILABLE,
                "local hardware capability is not validated for LOCAL_GPU",
                runtime_prerequisite=True,
            )
        if approved_model is None:
            raise LLMInvocationError(
                LLMErrorCode.MODEL_NOT_APPROVED,
                "approved model is unavailable",
                runtime_prerequisite=True,
            )
        if not self.runtime_selection.is_active:
            raise LLMInvocationError(
                LLMErrorCode.LOCAL_UNAVAILABLE,
                "local runtime is not activated by a current signed product decision",
                runtime_prerequisite=True,
            )
        return self.ollama_provider_factory(approved_model)

    def _invoke_provider(
        self,
        *,
        provider: StructuredLLMProvider,
        prompt_ref: PromptReference,
        prompt_input: Mapping[str, object],
        output_schema: OutputSchemaDefinition,
        requested_mode: RequestedRuntimeMode,
        trace_context: ObservabilityContext,
        fallback_reason: str | None,
        semantic_validate: Callable[[object], object] | None,
        external_transfer_scope: ExternalLlmTransferScopeV1 | None,
        selected_model_id: str | None,
    ) -> StructuredLLMResult:
        self.before_runtime_dispatch(provider.runtime)
        try:
            result = self._invoke_provider_unchecked(
                provider=provider,
                prompt_ref=prompt_ref,
                prompt_input=prompt_input,
                output_schema=output_schema,
                requested_mode=requested_mode,
                trace_context=trace_context,
                fallback_reason=fallback_reason,
                semantic_validate=semantic_validate,
                external_transfer_scope=external_transfer_scope,
                selected_model_id=selected_model_id,
            )
        except LLMInvocationError as error:
            self.event_recorder.record(
                event_name="LLM_CALL_FAILED",
                severity=Severity.ERROR,
                correlation=trace_context,
                attributes={
                    "operation": "INFER_STRUCTURED",
                    "prompt_id": prompt_ref.prompt_id,
                    "prompt_version": prompt_ref.prompt_version,
                    "prompt_content_hash": prompt_ref.content_hash,
                    "requested_mode": requested_mode.value,
                    "actual_runtime": provider.runtime.value,
                    "provider": provider.provider_name,
                    "selected_model_id": selected_model_id,
                    "output_schema_id": output_schema.schema_version,
                    "safe_error_code": error.code.value,
                    "error_type": type(error).__name__,
                    "affected_field_paths": list(
                        _safe_schema_field_paths(error.affected_field_paths, output_schema)
                    ),
                    "provider_dispatch_occurred": error.provider_dispatch_occurred,
                    "fallback_reason": fallback_reason,
                },
                result_code=error.code.value,
                status="FAILED",
            )
            self.record_runtime_result(provider.runtime, error.code.value)
            raise
        self.record_runtime_result(provider.runtime, None)
        return result

    def _invoke_provider_unchecked(
        self,
        *,
        provider: StructuredLLMProvider,
        prompt_ref: PromptReference,
        prompt_input: Mapping[str, object],
        output_schema: OutputSchemaDefinition,
        requested_mode: RequestedRuntimeMode,
        trace_context: ObservabilityContext,
        fallback_reason: str | None,
        semantic_validate: Callable[[object], object] | None,
        external_transfer_scope: ExternalLlmTransferScopeV1 | None,
        selected_model_id: str | None,
    ) -> StructuredLLMResult:
        if provider.runtime is ActualRuntime.API_LLM:
            self._require_external_call(external_transfer_scope)
        started = time.perf_counter()
        local_profile = self.runtime_selection.local_model_profile
        profile_attributes = (
            {
                "local_model_profile_id": local_profile.profile_id,
                "inference_class": local_profile.inference_class_for_prompt(
                    prompt_ref.prompt_id
                ).value,
            }
            if provider.runtime is ActualRuntime.LOCAL_GPU and local_profile is not None
            else {}
        )
        self.event_recorder.record(
            event_name="LLM_CALL_STARTED",
            severity=Severity.INFO,
            correlation=trace_context,
            attributes={
                "operation": "INFER_STRUCTURED",
                "prompt_id": prompt_ref.prompt_id,
                "prompt_version": prompt_ref.prompt_version,
                "prompt_content_hash": prompt_ref.content_hash,
                "requested_mode": requested_mode.value,
                "actual_runtime": provider.runtime.value,
                "provider": provider.provider_name,
                "selected_model_id": selected_model_id,
                "output_schema_id": output_schema.schema_version,
                **profile_attributes,
            },
            result_code="STARTED",
            status="STARTED",
        )
        api_key_bytes = (
            self.credential_service.read_secret(self.api_provider_name)
            if provider.runtime is ActualRuntime.API_LLM
            else None
        )
        api_key = None if api_key_bytes is None else api_key_bytes.decode("utf-8")
        provider_dispatch_occurred = False
        try:
            self.before_provider_dispatch()
            provider_dispatch_occurred = True
            trace_started = time.perf_counter()
            trace_handle = self._begin_llm_trace(
                call_kind="LLM_INFERENCE",
                provider=provider,
                prompt_ref=prompt_ref,
                output_schema=output_schema,
                selected_model_id=selected_model_id,
            )
            try:
                payload = provider.invoke_structured(
                    prompt_ref=prompt_ref,
                    prompt_input=prompt_input,
                    output_schema=output_schema,
                    runtime_policy=self.runtime_policy,
                    api_key=api_key,
                )
            except Exception as error:
                self._finish_llm_trace(
                    trace_handle,
                    status="FAILED",
                    started=trace_started,
                    error=error,
                )
                raise
            self._finish_llm_trace(
                trace_handle,
                status="COMPLETED",
                started=trace_started,
                input_tokens=payload.input_tokens,
                output_tokens=payload.output_tokens,
            )
            structured_output, attempts = self._validate_or_repair(
                provider=provider,
                prompt_ref=prompt_ref,
                prompt_input=prompt_input,
                payload=payload.content,
                output_schema=output_schema,
                api_key=api_key,
                trace_context=trace_context,
                semantic_validate=semantic_validate,
                external_transfer_scope=external_transfer_scope,
            )
        except LLMInvocationError as error:
            error.provider_dispatch_occurred = provider_dispatch_occurred
            raise
        except ValueError as error:
            raise LLMInvocationError(
                LLMErrorCode.INVALID_PROVIDER_RESPONSE,
                str(error),
                provider_dispatch_occurred=provider_dispatch_occurred,
            ) from error
        except TimeoutError as error:
            raise LLMInvocationError(
                LLMErrorCode.PROVIDER_TIMEOUT,
                "LLM invocation timed out",
                retryable=True,
                provider_dispatch_occurred=provider_dispatch_occurred,
            ) from error
        duration_ms = int((time.perf_counter() - started) * 1000)
        result = StructuredLLMResult(
            structured_output=structured_output,
            provider=provider.provider_name,
            model=payload.model,
            requested_mode=requested_mode,
            actual_runtime=provider.runtime,
            input_tokens=payload.input_tokens,
            output_tokens=payload.output_tokens,
            total_tokens=_sum_tokens(payload.input_tokens, payload.output_tokens),
            latency_ms=max(duration_ms, payload.latency_ms),
            estimated_cost_usd=payload.estimated_cost_usd,
            fallback_reason=fallback_reason,
            structured_output_attempts=attempts,
            provider_request_id=payload.provider_request_id,
            safe_error_code=None,
        )
        self.event_recorder.record(
            event_name="LLM_CALL_COMPLETED",
            severity=Severity.INFO,
            correlation=trace_context,
            attributes={
                "operation": "INFER_STRUCTURED",
                "prompt_id": prompt_ref.prompt_id,
                "prompt_version": prompt_ref.prompt_version,
                "prompt_content_hash": prompt_ref.content_hash,
                "requested_mode": requested_mode.value,
                "actual_runtime": result.actual_runtime.value,
                "provider": result.provider,
                "model": result.model,
                "selected_model_id": selected_model_id,
                "output_schema_id": output_schema.schema_version,
                "input_tokens": result.input_tokens,
                "output_tokens": result.output_tokens,
                "total_tokens": result.total_tokens,
                "estimated_cost_usd": result.estimated_cost_usd,
                "fallback_reason": result.fallback_reason,
                "structured_output_attempts": result.structured_output_attempts,
                **profile_attributes,
            },
            result_code="COMPLETED",
            status="COMPLETED",
            duration_ms=result.latency_ms,
        )
        return result

    def _validate_or_repair(
        self,
        *,
        provider: StructuredLLMProvider,
        prompt_ref: PromptReference,
        prompt_input: Mapping[str, object],
        payload: object,
        output_schema: OutputSchemaDefinition,
        api_key: str | None,
        trace_context: ObservabilityContext,
        semantic_validate: Callable[[object], object] | None,
        external_transfer_scope: ExternalLlmTransferScopeV1 | None,
    ) -> tuple[object, int]:
        try:
            candidate = _parse_payload(payload)
        except ValueError:
            candidate = payload
            errors = ["$: provider output is not valid JSON"]
        else:
            errors = _collect_validation_errors(candidate, output_schema, semantic_validate)
        if not errors:
            return candidate, 1
        if self.schema_repairer is None or self.runtime_policy.structured_output_repair_budget < 1:
            raise LLMInvocationError(
                LLMErrorCode.OUTPUT_SCHEMA_INVALID,
                "structured output did not satisfy schema",
                affected_field_paths=_validation_error_paths(errors),
            )
        if provider.runtime is ActualRuntime.API_LLM:
            self._require_external_call(external_transfer_scope)
        self.before_provider_dispatch()
        trace_started = time.perf_counter()
        trace_handle = self._begin_llm_trace(
            call_kind="LLM_SCHEMA_REPAIR",
            provider=provider,
            prompt_ref=prompt_ref,
            output_schema=output_schema,
            selected_model_id=None,
        )
        try:
            repaired = self.schema_repairer.repair(
                provider=provider,
                prompt_ref=prompt_ref,
                prompt_input=prompt_input,
                failed_output=candidate,
                output_schema=output_schema,
                runtime_policy=self.runtime_policy,
                api_key=api_key,
                attempt_no=1,
                max_attempts=self.runtime_policy.structured_output_repair_budget,
                failure_reason_code=LLMErrorCode.OUTPUT_SCHEMA_INVALID.value,
                validator_errors=tuple(errors),
            )
        except Exception as error:
            self._finish_llm_trace(
                trace_handle,
                status="FAILED",
                started=trace_started,
                error=error,
            )
            raise
        self._finish_llm_trace(
            trace_handle,
            status="COMPLETED",
            started=trace_started,
        )
        repair_errors = _collect_validation_errors(repaired, output_schema, semantic_validate)
        if repair_errors:
            raise LLMInvocationError(
                LLMErrorCode.OUTPUT_SCHEMA_INVALID,
                "schema repair did not produce a valid payload: " + "; ".join(repair_errors[-8:]),
                affected_field_paths=_validation_error_paths(repair_errors),
            )
        return repaired, 2

    def _require_external_call(self, scope: ExternalLlmTransferScopeV1 | None) -> None:
        if not self.settings_service().external_llm_consent:
            raise LLMInvocationError(
                LLMErrorCode.CONSENT_REQUIRED, "external LLM consent is disabled"
            )
        if scope is None or self.checkpoint is None:
            raise LLMInvocationError(
                LLMErrorCode.CONSENT_REQUIRED,
                "external LLM transfer scope is not published",
            )
        published = self.checkpoint.load_external_llm_scope(scope.run_id)
        if published != scope:
            raise LLMInvocationError(
                LLMErrorCode.CONSENT_REQUIRED,
                "external LLM transfer scope checkpoint is stale",
            )

    def _begin_llm_trace(
        self,
        *,
        call_kind: ExternalCallKind,
        provider: StructuredLLMProvider,
        prompt_ref: PromptReference,
        output_schema: OutputSchemaDefinition,
        selected_model_id: str | None,
    ) -> ExternalCallTraceHandleV1 | None:
        trace = self.external_call_trace
        if trace is None:
            return None
        try:
            return trace.begin_external_call(
                ExternalCallTraceStartV1(
                    schema_version=1,
                    domain_run_id=self.run_context_provider(),
                    call_kind=call_kind,
                    operation=(
                        "INFER_STRUCTURED"
                        if call_kind == "LLM_INFERENCE"
                        else "REPAIR_STRUCTURED_OUTPUT"
                    ),
                    provider=provider.provider_name,
                    model_id=selected_model_id,
                    prompt_id=prompt_ref.prompt_id,
                    prompt_version=prompt_ref.prompt_version,
                    prompt_content_hash=prompt_ref.content_hash,
                    output_schema_id=output_schema.schema_version,
                )
            )
        except Exception:
            return None

    def _finish_llm_trace(
        self,
        handle: ExternalCallTraceHandleV1 | None,
        *,
        status: Literal["COMPLETED", "FAILED"],
        started: float,
        input_tokens: int | None = None,
        output_tokens: int | None = None,
        error: Exception | None = None,
    ) -> None:
        trace = self.external_call_trace
        if trace is None or handle is None:
            return
        safe_error_code = error.code.value if isinstance(error, LLMInvocationError) else None
        try:
            trace.finish_external_call(
                handle,
                ExternalCallTraceFinishV1(
                    schema_version=1,
                    status=status,
                    duration_ms=max(0, int((time.perf_counter() - started) * 1000)),
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    total_tokens=_sum_tokens(input_tokens, output_tokens),
                    error_type=None if error is None else type(error).__name__,
                    safe_error_code=safe_error_code,
                ),
            )
        except Exception:
            return

    def _should_fallback(
        self,
        *,
        error: LLMInvocationError,
        decision: RouteDecision,
        requested_mode: RequestedRuntimeMode,
        settings: SettingsViewV1,
    ) -> bool:
        return (
            requested_mode is RequestedRuntimeMode.AUTO
            and settings.external_llm_consent
            and decision.fallback_allowed
            and error.code
            in {
                LLMErrorCode.LOCAL_UNAVAILABLE,
                LLMErrorCode.MODEL_NOT_FOUND,
                LLMErrorCode.MODEL_NOT_APPROVED,
                LLMErrorCode.MODEL_LOAD_FAILED,
                LLMErrorCode.GPU_OOM,
                LLMErrorCode.PROVIDER_TIMEOUT,
                LLMErrorCode.OUTPUT_SCHEMA_INVALID,
            }
        )

    def _record_selection(
        self,
        *,
        prompt_ref: PromptReference,
        trace_context: ObservabilityContext,
        requested_mode: RequestedRuntimeMode,
        decision: RouteDecision,
        selected_model_id: str | None,
    ) -> None:
        self.event_recorder.record(
            event_name="LLM_RUNTIME_SELECTED",
            severity=Severity.INFO,
            correlation=trace_context,
            attributes={
                "prompt_id": prompt_ref.prompt_id,
                "prompt_version": prompt_ref.prompt_version,
                "prompt_content_hash": prompt_ref.content_hash,
                "requested_mode": requested_mode.value,
                "primary_runtime": decision.primary_runtime.value,
                "fallback_allowed": decision.fallback_allowed,
                "fallback_target": None
                if decision.fallback_target is None
                else decision.fallback_target.value,
                "safe_error_code": decision.safe_reason_code,
                "selected_model_id": selected_model_id,
            },
            result_code="ROUTED",
            status="COMPLETED",
        )

    def _record_fallback_started(
        self,
        *,
        trace_context: ObservabilityContext,
        requested_mode: RequestedRuntimeMode,
        decision: RouteDecision,
        error: LLMInvocationError,
    ) -> None:
        self.event_recorder.record(
            event_name="LLM_FALLBACK_STARTED",
            severity=Severity.WARNING,
            correlation=trace_context,
            attributes={
                "requested_mode": requested_mode.value,
                "fallback_reason": error.code.value,
                "from_runtime": decision.primary_runtime.value,
                "to_runtime": None
                if decision.fallback_target is None
                else decision.fallback_target.value,
            },
            result_code="FALLBACK_STARTED",
            status="STARTED",
        )


def _decision(runtime: ActualRuntime, fallback_allowed: bool, reason: str | None) -> RouteDecision:
    return RouteDecision(runtime, fallback_allowed, None, reason)


def _local_runtime_reason(request: RouteDecisionInput) -> str | None:
    if request.hardware_capability.capability_status in {
        HardwareCapabilityStatus.UNKNOWN,
        HardwareCapabilityStatus.NOT_VALIDATED,
    }:
        return "LOCAL_HARDWARE_NOT_VALIDATED"
    if request.hardware_capability.capability_status is HardwareCapabilityStatus.INSUFFICIENT:
        return "LOCAL_HARDWARE_INSUFFICIENT"
    if request.approved_model is None:
        return "APPROVED_MODEL_UNAVAILABLE"
    if request.ollama_probe.safe_error_code is not None:
        return cast(str, request.ollama_probe.safe_error_code)
    if request.ollama_probe.availability is not AvailabilityState.AVAILABLE:
        return "OLLAMA_UNAVAILABLE"
    return None


def _probe_from_dict(value: object) -> ProbeResult:
    summary = cast(dict[str, object], value)
    return ProbeResult(
        availability=AvailabilityState(str(summary["availability"])),
        safe_error_code=cast(str | None, summary.get("safe_error_code")),
        last_probe_at_ms=cast(int | None, summary.get("last_probe")),
    )


def _hardware_from_dict(value: object) -> HardwareCapability:
    summary = cast(dict[str, object], value)
    return HardwareCapability(
        cpu_arch=str(summary["cpu_arch"]),
        core_summary=str(summary["core_summary"]),
        memory_bytes=cast(int | None, summary["memory_bytes"]),
        gpu_present=bool(summary["gpu_present"]),
        gpu_vendor=cast(str | None, summary["gpu_vendor"]),
        gpu_name=cast(str | None, summary["gpu_name"]),
        gpu_memory_bytes=cast(int | None, summary["gpu_memory_bytes"]),
        capability_status=HardwareCapabilityStatus(str(summary["capability_status"])),
        safe_reason_codes=tuple(cast(list[str], summary.get("safe_reason_codes", []))),
    )


def _parse_payload(payload: object) -> object:
    if isinstance(payload, str):
        import json

        return json.loads(payload)
    return payload


def _collect_validation_errors(
    candidate: object,
    output_schema: OutputSchemaDefinition,
    semantic_validate: Callable[[object], object] | None,
) -> list[str]:
    shape_errors = cast(list[str], validate_output_schema(candidate, output_schema.json_schema))
    if shape_errors or semantic_validate is None:
        return shape_errors
    try:
        semantic_validate(candidate)
    except ValueError as error:
        return [str(error)]
    return []


_JSON_PATH_PREFIX = re.compile(r"^\$[\w.\[\]]*")


def _validation_error_paths(errors: list[str]) -> tuple[str, ...]:
    return tuple(
        sorted(
            {
                match.group(0)
                for message in errors
                if (match := _JSON_PATH_PREFIX.match(message)) is not None
            }
        )
    )


def _safe_schema_field_paths(
    paths: tuple[str, ...], output_schema: OutputSchemaDefinition
) -> tuple[str, ...]:
    properties = output_schema.json_schema.get("properties")
    allowed_roots = frozenset(properties) if isinstance(properties, Mapping) else frozenset()
    safe_paths: list[str] = []
    for path in paths:
        match = _JSON_PATH_PREFIX.fullmatch(path)
        if match is None:
            continue
        if path == "$":
            safe_paths.append(path)
            continue
        root = path[2:].split(".", 1)[0].split("[", 1)[0]
        if root in allowed_roots:
            safe_paths.append(path)
    return tuple(sorted(set(safe_paths)))


def _sum_tokens(input_tokens: int | None, output_tokens: int | None) -> int | None:
    if input_tokens is None and output_tokens is None:
        return None
    return (input_tokens or 0) + (output_tokens or 0)


def _canonical_result(result: StructuredLLMResult) -> StructuredInferenceResultV1:
    if not isinstance(result.structured_output, dict):
        raise LLMInvocationError(
            LLMErrorCode.OUTPUT_SCHEMA_INVALID,
            "structured inference output must be an object",
        )
    return StructuredInferenceResultV1(
        schema_version=1,
        structured_output=cast(dict[str, object], result.structured_output),
        provider=result.provider,
        model=result.model,
        actual_runtime=cast(Literal["LOCAL_GPU", "API_LLM"], result.actual_runtime.value),
        input_tokens=result.input_tokens or 0,
        output_tokens=result.output_tokens or 0,
        latency_ms=result.latency_ms,
        fallback_reason=result.fallback_reason,
    )


def _external_data_classes(source_kinds: tuple[str, ...]) -> tuple[str, ...]:
    """Classify bounded prompt field names without disclosing prompt values."""

    lowered = tuple(item.lower() for item in source_kinds)
    classes: set[str] = set()
    if any(any(marker in item for marker in ("user", "request", "query")) for item in lowered):
        classes.add("USER_REQUEST")
    if any(
        any(marker in item for marker in ("resource", "calendar", "gmail", "task", "tool"))
        for item in lowered
    ):
        classes.add("RESOURCE_METADATA")
    if any(any(marker in item for marker in ("evidence", "excerpt", "source")) for item in lowered):
        classes.add("EVIDENCE_EXCERPT")
    if (
        any(
            any(marker in item for marker in ("plan", "context", "analysis", "route", "goal"))
            for item in lowered
        )
        or not classes
    ):
        classes.add("PLAN_CONTEXT")
    return tuple(sorted(classes))
