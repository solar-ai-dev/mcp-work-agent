"""Fixed Work-owner-only diagnostic using the real isolated Product composition.

Raw structure and semantic quality are separate. No downstream workflow score is
produced; model execution requires an exact preregistered plan and a new output.
"""

from __future__ import annotations

import argparse
import hashlib
import time
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import asdict
from pathlib import Path
from typing import Any, cast
from unittest.mock import patch

from scripts import evaluate_production_snapshot_workflow as shared
from scripts import evaluate_snapshot_request_tool_route as components
from scripts import production_snapshot_runtime as snapshot
from scripts import production_work_ref_candidate as candidate
from scripts.ru_observation import object_hash

from google_work_agent.application.agents.request_understanding.identify_requested_work import (
    REQUESTED_WORK_OUTPUT_SCHEMA,
    identify_requested_work,
)
from google_work_agent.application.prompt_runtime.prompt_registry import PromptRegistry
from google_work_agent.application.use_cases.run.account_provider_dispatch import (
    provider_dispatch_budget_scope,
    provider_dispatch_execution_scope,
)
from google_work_agent.application.use_cases.run.guard_run_budget import RunBudgetV2
from google_work_agent.ports.system.contracts.workflow_execution import WorkflowStartRequest
from google_work_agent.ports.system.settings_port import SettingsPatchV1

CASE_IDS = ("CASE-CORE-005", "CASE-CORE-017", "CASE-CORE-019", "CASE-CORE-035", "CASE-CORE-049")
ARMS = ("production", "work-ref-v34")


@contextmanager
def registered_cases() -> Iterator[None]:
    """Reuse the evaluation binding checks with this fixed Core diagnostic list."""
    with patch.object(components, "CASE_IDS", CASE_IDS):
        yield


def _prompt_binding() -> dict[str, Any]:
    manifest = shared.default_prompt_manifest_path()
    registry = PromptRegistry(manifest, manifest.parent / "prompt_runtime_input_contract_v1.json")
    source = registry.source_text(candidate.WORK_SLOT)
    if source.count(candidate._SPAN_INSTRUCTION) != 1:
        raise ValueError("current Work instruction differs from the candidate basis")
    instruction = source.replace(candidate._SPAN_INSTRUCTION, candidate._REF_INSTRUCTION)
    return {
        "baseline_prompt_ref": asdict(registry.lookup_for_evaluation(candidate.WORK_SLOT)),
        "candidate_prompt_id": candidate.EVALUATION_SLOT,
        "candidate_prompt_sha256": hashlib.sha256(instruction.encode()).hexdigest(),
        "candidate_input_version": candidate.INPUT_VERSION,
        "candidate_output_version": candidate.OUTPUT_VERSION,
        "baseline_output_schema_sha256": object_hash(REQUESTED_WORK_OUTPUT_SCHEMA.json_schema),
        "candidate_schema": "CLOSED_REQUEST_LOCAL_TOKEN_IDS_FROM_UNCHANGED_REQUEST",
    }


def build_plan(
    model_digest: str, *, trial_id: str | None = None, reference_time_ms: int | None = None
) -> dict[str, Any]:
    """Read-only preregistration. Does not bootstrap a runtime or discover a model."""
    plan = shared.build_plan(model_digest, trial_id=trial_id)
    for field in ("case_id", "case_sha256", "resource_scope", "candidate"):
        plan.pop(field)
    reference_ms = int(time.time() * 1000) if reference_time_ms is None else reference_time_ms
    if not isinstance(reference_ms, int) or isinstance(reference_ms, bool) or reference_ms < 1:
        raise ValueError("a positive preregistered pair reference time is required")
    with registered_cases():
        cases = [
            components.case_binding(snapshot.load_case(item), reference_ms) for item in CASE_IDS
        ]
    plan.update(
        schema_version=1,
        kind="PRODUCTION_SNAPSHOT_WORK_OWNER_PAIRED_DIAGNOSTIC",
        scope="ACTUAL_PRODUCT_WORK_OWNER_ONLY_NOT_RU_ROUTE_OR_WORKFLOW_SUCCESS",
        arms=list(ARMS),
        cases=cases,
        preregistered_reference_time_ms=reference_ms,
        trials_per_case_arm=1,
        owner_invocations_per_case_arm=1,
        planned_first_calls=10,
        schema_repair="UNCHANGED_PRODUCT_ROUTER_BOUND",
        semantic_revision_calls=0,
        execution_order="SEQUENTIAL_CASE_THEN_ARM",
        prompt_binding=_prompt_binding(),
        provider_reads=0,
        stop_before=["Goal", "Source", "Output", "ToolRoute", "Retrieval", "Planning"],
        semantic_grader="UNREVIEWED_NO_EXACT_WORK_COUNT_GOLD",
    )
    for path in (
        Path(__file__),
        Path(components.__file__),
        Path(candidate.__file__),
        shared.PROJECT_ROOT / "scripts/production_goal_output_candidate.py",
        shared.PROJECT_ROOT / "evaluation/request_semantic_authority_candidate.py",
    ):
        plan["dependency_sha256"][path.resolve().relative_to(shared.PROJECT_ROOT).as_posix()] = (
            shared.file_hash(path)
        )
    return plan


def validate_plan(plan: Mapping[str, Any]) -> None:
    expected = build_plan(
        plan["model"]["digest"],
        trial_id=plan["trial_id"],
        reference_time_ms=plan["preregistered_reference_time_ms"],
    )
    if dict(plan) != expected:
        raise ValueError("Work diagnostic preregistered input/code/runtime binding changed")


def run_arm(plan: dict[str, Any], binding: dict[str, Any], arm: str, output: Path) -> None:
    observation = shared.TrialObservation(output)
    report: dict[str, Any] = {
        "plan_sha256": object_hash(plan),
        "case_binding": binding,
        "arm": arm,
        "state": "STARTING",
        "scope": plan["scope"],
        "structural_status": "NOT_OBSERVED",
        "semantic_verdict": "UNREVIEWED",
        "rerun_to_pass": 0,
    }
    try:
        validate_plan(plan)
        if arm not in ARMS or binding not in plan["cases"]:
            raise ValueError("unregistered Work diagnostic Case/arm")

        def decorate(provider: Any) -> Any:
            leaf = candidate.decorate_work_ref_provider(provider) if arm == ARMS[1] else provider
            return observation.decorate(leaf)

        with (
            observation.wire_observer(),
            registered_cases(),
            components.component_boundary(binding["account_id"]),
            snapshot.snapshot_production_runtime(
                output / "runtime",
                case_id=binding["case_id"],
                allow_loopback_model=True,
                llm_provider_decorator=decorate,
                sampling_seed=shared.SEED,
            ) as (container, boundary),
            shared.drain_before_guard_release(container),
        ):
            request: WorkflowStartRequest | None = None
            try:
                report["settings"] = asdict(
                    container.settings_port.update_settings(
                        SettingsPatchV1(
                            1,
                            preferred_llm_mode="LOCAL_GPU",
                            preferred_local_model_id=shared.MODEL_ID,
                        ),
                        operation_ref=plan["trial_id"],
                    )
                )
                installed = [
                    item
                    for item in shared.OllamaHTTPClient().list_installed_models()
                    if item.model_id == shared.MODEL_ID
                ]
                if len(installed) != 1 or installed[0].digest != plan["model"]["digest"]:
                    raise ValueError("model digest differs from preregistration")
                case = snapshot.load_case(binding["case_id"])
                request = components.admit_request(container, boundary, case, binding)
                router = container.structured_inference_port
                manifest = router.prompt_manifest_path or shared.default_prompt_manifest_path()
                registry = PromptRegistry(
                    manifest,
                    manifest.parent / "prompt_runtime_input_contract_v1.json",
                )
                prompt_ref = registry.lookup_for_evaluation(candidate.WORK_SLOT)
                report.update(
                    state="OWNER_RUNNING",
                    run_id=request.run_id,
                    request=asdict(request),
                    actual_router_policy=asdict(router.runtime_policy),
                )
                shared.write_json(output / "raw.json", report)
                started = time.monotonic()
                reference_ms = binding["effective_reference_time_ms"]
                with (
                    provider_dispatch_execution_scope(
                        run_id=request.run_id,
                        now_ms=lambda: reference_ms + int((time.monotonic() - started) * 1000),
                    ),
                    provider_dispatch_budget_scope(cast(RunBudgetV2, request.run_budget)),
                ):
                    if arm == "production":
                        work = identify_requested_work(
                            llm_runtime=router,
                            requested_mode="LOCAL_GPU",
                            prompt_ref=prompt_ref,
                            user_request=request.request_text,
                        )
                    else:
                        owner = candidate.ConnectedWorkRefCandidate(
                            delegate=router, run_id=request.run_id
                        )
                        try:
                            if (
                                owner.binding["candidate_prompt_hash"]
                                != plan["prompt_binding"]["candidate_prompt_sha256"]
                            ):
                                raise ValueError("candidate Prompt differs from preregistration")
                            work = owner.identify(
                                llm_runtime=router,
                                requested_mode="LOCAL_GPU",
                                prompt_ref=prompt_ref,
                                user_request=request.request_text,
                            )
                        finally:
                            report["candidate_binding"] = owner.binding
                            report["candidate_events"] = deepcopy(owner.events)
                            owner.close()
                report.update(
                    state="OWNER_RETURNED",
                    structural_status="VALID_WORK_DEFINITION",
                    requested_work=work,
                )
            finally:
                if request is not None:
                    report["run_budget_after"] = deepcopy(request.run_budget)
                report.update(
                    boundary_events=deepcopy(boundary.events),
                    provider_reads=len(boundary.read_results),
                    provider_writes=len(boundary.provider.write_calls),
                    provider_read_attempts=sum(
                        item.get("boundary") == "component_connector_read"
                        for item in boundary.events
                    ),
                    provider_write_attempts=sum(
                        item.get("boundary") == "provider_write_dispatch"
                        for item in boundary.events
                    ),
                )
    except Exception as error:
        previous = report["state"]
        report.update(
            state_before_error=previous,
            state=(
                "EXPERIMENT_BOUND_REACHED"
                if observation.bound_reason
                else "OWNER_ERROR"
                if previous == "OWNER_RUNNING"
                else "HARNESS_ERROR"
            ),
            bound_reason=observation.bound_reason,
            error_type=type(error).__name__,
            error=str(error),
        )
    finally:
        report.update(
            metrics=observation.metrics(),
            wall_latency_ms=int((time.monotonic() - observation.started) * 1000),
        )
        shared.write_json(output / "raw.json", report)


def execute_plan(plan_path: Path, output: Path) -> int:
    # Reuse parent process isolation, exclusive claim, sequential order and wall bound.
    # Only evaluation dispatch/validation functions differ; Product guards are untouched.
    with (
        patch.object(components, "validate_plan", validate_plan),
        patch.object(components, "run_arm", run_arm),
    ):
        return components.execute_plan(plan_path, output)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    raise SystemExit(execute_plan(arguments.plan, arguments.output))


if __name__ == "__main__":
    main()
