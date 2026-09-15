"""Fake LLM transports, probes, and repair helpers."""

from __future__ import annotations

from collections import deque
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import TypedDict, cast

from google_work_agent.ports.llm.llm_runtime_status_port import (
    LlmProviderRuntimeStatus,
    LocalModelRuntimeOptionV1,
)
from google_work_agent.ports.llm.local_model_catalog_port import InstalledLocalModelV1
from google_work_agent.ports.llm.local_model_catalog_unavailable_error import (
    LocalModelCatalogUnavailableError,
)
from google_work_agent.ports.llm.output_schema_validation import validate_output_schema
from google_work_agent.ports.llm.structured_inference_contracts import (
    ApprovedModelInfo,
    AvailabilityState,
    HardwareCapability,
    HardwareCapabilityStatus,
    OutputSchemaDefinition,
    ProbeResult,
    PromptReference,
    ProviderResponsePayload,
    ToolCallProviderResponse,
    ToolDefinition,
)
from google_work_agent.ports.llm.structured_inference_port import StructuredInferenceResultV1


class StructuredInferenceCall(TypedDict):
    requested_mode: str
    prompt_ref: PromptReference
    prompt_input: dict[str, object]
    output_schema: OutputSchemaDefinition


class DisabledLlmRuntimeStatusPort:
    def get_status(self, provider: str) -> LlmProviderRuntimeStatus:
        return LlmProviderRuntimeStatus(1, provider, False, "DISABLED", None, None)

    def list_local_models(self) -> tuple[LocalModelRuntimeOptionV1, ...]:
        return ()


@dataclass
class FakeStructuredInferencePort:
    """Queued fake for the canonical structured-inference Port."""

    outputs: list[object]
    calls: list[StructuredInferenceCall] = field(default_factory=list)
    validate_schema: bool = False
    _pending_resource_responsibilities: object | None = field(
        default=None,
        init=False,
        repr=False,
    )
    _pending_source_statuses: object | None = field(
        default=None,
        init=False,
        repr=False,
    )

    def infer(
        self,
        requested_mode: str,
        prompt_ref: PromptReference,
        input_projection: Mapping[str, object],
        output_schema_ref: OutputSchemaDefinition,
    ) -> StructuredInferenceResultV1:
        self.calls.append(
            {
                "requested_mode": requested_mode,
                "prompt_ref": prompt_ref,
                "prompt_input": dict(input_projection),
                "output_schema": output_schema_ref,
            }
        )
        output: object
        if (
            output_schema_ref.schema_version == "request-source-dependency-decision-v3"
            and self._pending_resource_responsibilities is not None
        ):
            output = _source_dependency_decisions_from_responsibilities(
                self._pending_resource_responsibilities,
                input_projection=input_projection,
            )
        elif (
            output_schema_ref.schema_version == "request-output-responsibility-decision-v2"
            and self._pending_resource_responsibilities is not None
        ):
            output = _output_responsibility_decisions_from_responsibilities(
                self._pending_resource_responsibilities,
                input_projection=input_projection,
            )
            self._pending_resource_responsibilities = None
        elif output_schema_ref.schema_version == "request-effect-prohibition-decision-v1":
            if (
                self.outputs
                and isinstance(self.outputs[0], Mapping)
                and "effect_prohibitions" in self.outputs[0]
            ):
                output = self.outputs.pop(0)
            else:
                base_projection = input_projection.get("base_projection")
                base = (
                    cast(Mapping[str, object], base_projection)
                    if isinstance(base_projection, Mapping)
                    else input_projection
                )
                output = {
                    "effect_prohibitions": [
                        {
                            "effect": candidate["effect"],
                            "prohibition": "NOT_FORBIDDEN",
                        }
                        for raw_candidate in cast(Sequence[object], base["effect_candidates"])
                        if isinstance(raw_candidate, Mapping)
                        for candidate in [cast(Mapping[str, object], raw_candidate)]
                    ]
                }
        elif output_schema_ref.schema_version in {
            "request-source-status-v1",
            "request-source-status-v2",
        }:
            if self._pending_source_statuses is not None:
                output = {"statuses": self._pending_source_statuses}
                self._pending_source_statuses = None
            elif (
                self.outputs
                and isinstance(self.outputs[0], Mapping)
                and "statuses" in self.outputs[0]
            ):
                output = self.outputs.pop(0)
            else:
                output = {"statuses": []}
        else:
            output = self.outputs.pop(0)
            if isinstance(output, Mapping) and "resource_responsibilities" in output:
                responsibilities = output["resource_responsibilities"]
                if output_schema_ref.schema_version in {
                    "request-goal-candidate-v13",
                    "request-goal-candidate-v14",
                    "request-goal-candidate-v15",
                    "request-goal-candidate-v16",
                }:
                    self._pending_resource_responsibilities = responsibilities
                    output = {
                        key: value
                        for key, value in output.items()
                        if key != "resource_responsibilities"
                    }
            elif (
                output_schema_ref.schema_version == "request-source-dependency-decision-v3"
                and isinstance(output, Mapping)
                and "source_reads" in output
                and "outputs" in output
            ):
                self._pending_resource_responsibilities = output
                output = _source_dependency_decisions_from_responsibilities(
                    output,
                    input_projection=input_projection,
                )
            elif (
                output_schema_ref.schema_version == "request-output-responsibility-decision-v2"
                and isinstance(output, Mapping)
                and "source_reads" in output
                and "outputs" in output
            ):
                output = _output_responsibility_decisions_from_responsibilities(
                    output,
                    input_projection=input_projection,
                )
            if (
                output_schema_ref.schema_version
                in {
                    "request-goal-candidate-v14",
                    "request-goal-candidate-v15",
                    "request-goal-candidate-v16",
                }
                and isinstance(output, Mapping)
                and isinstance(output.get("constraints"), Mapping)
                and "status" in cast(Mapping[str, object], output["constraints"])
            ):
                constraints = cast(Mapping[str, object], output["constraints"])
                self._pending_source_statuses = constraints.get("status", [])
                output = {
                    **output,
                    "constraints": {
                        key: value for key, value in constraints.items() if key != "status"
                    },
                }
        if isinstance(output, Exception):
            raise output
        if self.validate_schema:
            assert not validate_output_schema(output, output_schema_ref.json_schema)
        return StructuredInferenceResultV1(
            schema_version=1,
            structured_output=cast(dict[str, object], output),
            provider="fake",
            model="fake",
            actual_runtime="API_LLM",
            input_tokens=1,
            output_tokens=1,
            latency_ms=1,
            fallback_reason=None,
        )


def _source_dependency_decisions_from_responsibilities(
    value: object,
    *,
    input_projection: Mapping[str, object],
) -> dict[str, object]:
    responsibilities = cast(Mapping[str, object], value)
    sources: dict[str, dict[str, object]] = {}
    for item in cast(Sequence[object], responsibilities["source_reads"]):
        if not isinstance(item, Mapping):
            continue
        source = cast(Mapping[str, object], item)
        resource_type = cast(str, source["resource_type"])
        current = sources.setdefault(
            resource_type,
            {
                "resource_type": resource_type,
                "required_information": [],
                "target_scope": source["target_scope"],
            },
        )
        if current["target_scope"] != source["target_scope"]:
            raise AssertionError("fake source responsibilities contain conflicting target scopes")
        information = cast(list[str], current["required_information"])
        for value in cast(Sequence[str], source["required_information"]):
            if value not in information:
                information.append(value)
    base_projection = input_projection.get("base_projection")
    base = (
        cast(Mapping[str, object], base_projection)
        if isinstance(base_projection, Mapping)
        else input_projection
    )
    candidates = cast(Sequence[Mapping[str, object]], base["source_candidates"])
    decisions: list[dict[str, object]] = []
    for candidate in candidates:
        resource_type = cast(str, candidate["resource_type"])
        selected_source = sources.get(resource_type)
        if selected_source is not None:
            required_information = list(
                cast(Sequence[str], selected_source["required_information"])
            )
            decisions.append(
                {
                    "resource_type": resource_type,
                    "dependency": "SOURCE_REQUIRED",
                    "required_information": required_information,
                    "target_scope": selected_source["target_scope"],
                }
            )
        else:
            decisions.append({"resource_type": resource_type, "dependency": "SOURCE_NOT_REQUIRED"})
    candidate_types = {cast(str, candidate["resource_type"]) for candidate in candidates}
    decisions.extend(
        {
            "resource_type": resource_type,
            "dependency": "SOURCE_REQUIRED",
            "required_information": list(cast(Sequence[str], source["required_information"])),
            "target_scope": source["target_scope"],
        }
        for resource_type, source in sources.items()
        if resource_type not in candidate_types
    )
    return {"source_dependencies": decisions}


def _output_responsibility_decisions_from_responsibilities(
    value: object,
    *,
    input_projection: Mapping[str, object],
) -> dict[str, object]:
    responsibilities = cast(Mapping[str, object], value)
    outputs = {
        cast(str, output["resource_type"]): output
        for item in cast(Sequence[object], responsibilities["outputs"])
        if isinstance(item, Mapping)
        for output in [cast(Mapping[str, object], item)]
    }
    base_projection = input_projection.get("base_projection")
    base = (
        cast(Mapping[str, object], base_projection)
        if isinstance(base_projection, Mapping)
        else input_projection
    )
    candidates = cast(Sequence[Mapping[str, object]], base["output_candidates"])
    decisions = [
        {
            "resource_type": candidate["resource_type"],
            "effect": outputs[cast(str, candidate["resource_type"])]["effect"],
        }
        for candidate in candidates
        if cast(str, candidate["resource_type"]) in outputs
    ]
    candidate_types = {cast(str, candidate["resource_type"]) for candidate in candidates}
    decisions.extend(
        {"resource_type": resource_type, "effect": output["effect"]}
        for resource_type, output in outputs.items()
        if resource_type not in candidate_types
    )
    return {"output_responsibilities": decisions}


@dataclass
class FakeAPIProviderTransport:
    probe_result: ProbeResult = field(
        default_factory=lambda: ProbeResult(availability=AvailabilityState.AVAILABLE)
    )
    invocations: list[dict[str, object]] = field(default_factory=list)
    queued_payloads: deque[object] = field(default_factory=deque)

    def probe(self, *, api_key: str, timeout_seconds: int) -> ProbeResult:
        self.invocations.append(
            {"kind": "probe", "api_key_length": len(api_key), "timeout_seconds": timeout_seconds}
        )
        return self.probe_result

    def invoke_structured(
        self,
        *,
        model_id: str,
        prompt_ref: PromptReference,
        prompt_input: Mapping[str, object],
        output_schema: OutputSchemaDefinition,
        timeout_seconds: int,
        api_key: str,
        instruction_text: str,
        sampling_temperature: float | None = None,
    ) -> ProviderResponsePayload:
        self.invocations.append(
            {
                "kind": "invoke",
                "model_id": model_id,
                "prompt_id": prompt_ref.prompt_id,
                "timeout_seconds": timeout_seconds,
                "api_key_length": len(api_key),
                "prompt_input": dict(prompt_input),
                "schema_version": output_schema.schema_version,
                "instruction_text": instruction_text,
                "sampling_temperature": sampling_temperature,
            }
        )
        payload = self.queued_payloads.popleft()
        if isinstance(payload, Exception):
            raise payload
        return cast(ProviderResponsePayload, payload)


@dataclass
class FakeOllamaTransport:
    probe_result: ProbeResult = field(
        default_factory=lambda: ProbeResult(availability=AvailabilityState.AVAILABLE)
    )
    invocations: list[dict[str, object]] = field(default_factory=list)
    queued_payloads: deque[object] = field(default_factory=deque)
    installed_models: tuple[InstalledLocalModelV1, ...] = ()
    catalog_error_code: str | None = None

    def list_installed_models(self) -> tuple[InstalledLocalModelV1, ...]:
        if self.catalog_error_code is not None:
            raise LocalModelCatalogUnavailableError(self.catalog_error_code)
        return self.installed_models

    def probe(self, *, endpoint: str, model_id: str | None, timeout_seconds: int) -> ProbeResult:
        self.invocations.append(
            {
                "kind": "probe",
                "endpoint": endpoint,
                "model_id": model_id,
                "timeout_seconds": timeout_seconds,
            }
        )
        return self.probe_result

    def invoke_structured(
        self,
        *,
        endpoint: str,
        model_id: str,
        prompt_ref: PromptReference,
        prompt_input: Mapping[str, object],
        output_schema: OutputSchemaDefinition,
        timeout_seconds: int,
        instruction_text: str,
        sampling_temperature: float | None = None,
        sampling_seed: int | None = None,
    ) -> ProviderResponsePayload:
        self.invocations.append(
            {
                "kind": "invoke",
                "endpoint": endpoint,
                "model_id": model_id,
                "prompt_id": prompt_ref.prompt_id,
                "prompt_input": dict(prompt_input),
                "schema_version": output_schema.schema_version,
                "timeout_seconds": timeout_seconds,
                "instruction_text": instruction_text,
                "sampling_temperature": sampling_temperature,
                "sampling_seed": sampling_seed,
            }
        )
        payload = self.queued_payloads.popleft()
        if isinstance(payload, Exception):
            raise payload
        return cast(ProviderResponsePayload, payload)

    def invoke_tool_call(
        self,
        *,
        endpoint: str,
        model_id: str,
        prompt_ref: PromptReference,
        prompt_input: Mapping[str, object],
        tools: Sequence[ToolDefinition],
        timeout_seconds: int,
        instruction_text: str,
        sampling_temperature: float | None = None,
        sampling_seed: int | None = None,
    ) -> ToolCallProviderResponse:
        self.invocations.append(
            {
                "kind": "tool_call",
                "endpoint": endpoint,
                "model_id": model_id,
                "prompt_id": prompt_ref.prompt_id,
                "prompt_input": dict(prompt_input),
                "tools": list(tools),
                "timeout_seconds": timeout_seconds,
                "instruction_text": instruction_text,
                "sampling_temperature": sampling_temperature,
                "sampling_seed": sampling_seed,
            }
        )
        payload = self.queued_payloads.popleft()
        if isinstance(payload, Exception):
            raise payload
        return cast(ToolCallProviderResponse, payload)


@dataclass(frozen=True, slots=True)
class FakeHardwareProbe:
    capability: HardwareCapability = HardwareCapability(
        cpu_arch="x86_64",
        core_summary="8",
        memory_bytes=16 * 1024 * 1024 * 1024,
        gpu_present=True,
        gpu_vendor="NVIDIA",
        gpu_name="Test GPU",
        gpu_memory_bytes=8 * 1024 * 1024 * 1024,
        capability_status=HardwareCapabilityStatus.VALIDATED,
        safe_reason_codes=(),
    )

    def probe(self) -> HardwareCapability:
        return self.capability


@dataclass
class FakeSchemaRepairer:
    repaired_output: object
    calls: list[dict[str, object]] = field(default_factory=list)

    def repair(
        self,
        *,
        provider: object = None,
        prompt_ref: PromptReference,
        prompt_input: Mapping[str, object] | None = None,
        failed_output: object,
        output_schema: OutputSchemaDefinition,
        runtime_policy: object = None,
        api_key: str | None = None,
        attempt_no: int,
        max_attempts: int = 1,
        failure_reason_code: str,
        validator_errors: tuple[str, ...] = (),
    ) -> ProviderResponsePayload:
        self.calls.append(
            {
                "prompt_id": prompt_ref.prompt_id,
                "prompt_input": dict(prompt_input) if prompt_input is not None else {},
                "attempt_no": attempt_no,
                "max_attempts": max_attempts,
                "failure_reason_code": failure_reason_code,
                "validator_errors": list(validator_errors),
                "failed_output": failed_output,
                "schema_version": output_schema.schema_version,
            }
        )
        return ProviderResponsePayload(
            content=self.repaired_output,
            model="fake-repair-model",
            provider_request_id=None,
            input_tokens=0,
            output_tokens=0,
            latency_ms=0,
            estimated_cost_usd=None,
        )


def approved_model(model_id: str = "approved-model") -> ApprovedModelInfo:
    return ApprovedModelInfo(
        model_id=model_id,
        runtime="OLLAMA",
        manifest_version="1",
        schema_version="1",
        minimum_runtime_version="0.1.0",
    )
