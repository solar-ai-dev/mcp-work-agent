"""The single final eligibility decision for the signed local runtime selection."""

from __future__ import annotations

from dataclasses import dataclass

from google_work_agent.ports.llm.runtime_selection import LlmRuntimeSelectionV1
from google_work_agent.ports.llm.structured_inference_contracts import (
    AvailabilityState,
    ProbeResult,
)


@dataclass(frozen=True, slots=True)
class LocalRuntimeEligibilityDecision:
    eligible: bool
    safe_reason_codes: tuple[str, ...]


def evaluate_local_runtime_eligibility(
    *,
    runtime_selection: LlmRuntimeSelectionV1,
    operating_system: str,
    architecture: str,
    cpu_logical_cores: int,
    ram_total_bytes: int,
    gpu_present: bool,
    vram_total_bytes: int | None,
    ollama_probe: ProbeResult,
) -> LocalRuntimeEligibilityDecision:
    cpu_profile_reasons: list[str] = []
    gpu_profile_reasons: list[str] = []
    requirements = runtime_selection.requirements
    if not runtime_selection.is_active or requirements is None:
        cpu_profile_reasons.append(runtime_selection.local_runtime_activation_status.value)
    else:
        if operating_system != requirements.supported_os:
            cpu_profile_reasons.append("UNSUPPORTED_OPERATING_SYSTEM")
        if architecture != requirements.supported_architecture:
            cpu_profile_reasons.append("UNSUPPORTED_ARCHITECTURE")
        if cpu_logical_cores < requirements.minimum_cpu_logical_cores:
            cpu_profile_reasons.append("INSUFFICIENT_CPU")
        if ram_total_bytes < requirements.minimum_ram_bytes:
            cpu_profile_reasons.append("INSUFFICIENT_RAM")
        if not gpu_present or vram_total_bytes is None:
            gpu_profile_reasons.append("GPU_NOT_AVAILABLE")
        elif vram_total_bytes < requirements.minimum_vram_bytes:
            gpu_profile_reasons.append("INSUFFICIENT_VRAM")
        if ollama_probe.availability is not AvailabilityState.AVAILABLE:
            cpu_profile_reasons.append(ollama_probe.safe_error_code or "OLLAMA_UNAVAILABLE")
    gpu_profile_reasons = [*cpu_profile_reasons, *gpu_profile_reasons]
    cpu_profile_eligible = not cpu_profile_reasons
    gpu_profile_eligible = not gpu_profile_reasons
    eligible = gpu_profile_eligible or cpu_profile_eligible
    blocking_reasons = (
        () if eligible else tuple(dict.fromkeys([*cpu_profile_reasons, *gpu_profile_reasons]))
    )
    return LocalRuntimeEligibilityDecision(
        eligible=eligible,
        safe_reason_codes=blocking_reasons,
    )


__all__ = ["LocalRuntimeEligibilityDecision", "evaluate_local_runtime_eligibility"]
