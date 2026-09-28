"""Fixed Product RU -> Tool Route comparison changing only Work selector admission.

This is not a MainGraph, Retrieval or final business-success evaluation. The codec
does not supply missing semantics; unchanged exact Work outputs cannot explain
later Source/Output sampling variance as a semantic gain from this candidate.
"""

from __future__ import annotations

import argparse
import json
import time
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import asdict
from pathlib import Path
from typing import Any
from unittest.mock import patch

from scripts import evaluate_production_snapshot_workflow as shared
from scripts import evaluate_snapshot_request_tool_route as components
from scripts import production_snapshot_runtime as snapshot
from scripts import production_work_span_codec_candidate as codec
from scripts.ru_observation import object_hash

from google_work_agent.application.agents.request_understanding.identify_requested_work import (
    REQUESTED_WORK_OUTPUT_SCHEMA,
)
from google_work_agent.application.prompt_runtime.prompt_registry import PromptRegistry

CASE_IDS = ("CASE-CORE-005", "CASE-CORE-017", "CASE-CORE-049")
CANDIDATE = "work-span-codec-v35"
ARMS = ("production", CANDIDATE)
WORK_SLOT = "request_understanding.identify_requested_work"
_component_run_arm = components.run_arm


@contextmanager
def registered_cases() -> Iterator[None]:
    with patch.object(components, "CASE_IDS", CASE_IDS):
        yield


def _work_contract() -> dict[str, Any]:
    manifest = shared.default_prompt_manifest_path()
    registry = PromptRegistry(manifest, manifest.parent / "prompt_runtime_input_contract_v1.json")
    return {
        "both_arms_prompt_ref": asdict(registry.lookup_for_evaluation(WORK_SLOT)),
        "both_arms_output_schema_sha256": object_hash(REQUESTED_WORK_OUTPUT_SCHEMA.json_schema),
        "candidate_code_sha256": shared.file_hash(Path(codec.__file__)),
        "candidate_version": codec.CODEC_VERSION,
        "changed_boundary": "FRESH_WORK_SELECTOR_TO_EXACT_PROVENANCE_ADMISSION_ONLY",
        "prompt_schema_sampling": "UNCHANGED_PRODUCT_BOTH_ARMS",
        "goal_output_joint_authority": False,
        "token_reference_candidate": False,
    }


def build_plan(
    model_digest: str, *, trial_id: str | None = None, reference_time_ms: int | None = None
) -> dict[str, Any]:
    """Preregister six fixed arms; read local metadata without runtime bootstrap."""
    plan = shared.build_plan(model_digest, trial_id=trial_id)
    for field in ("case_id", "case_sha256", "resource_scope", "candidate"):
        plan.pop(field)
    reference = int(time.time() * 1000) if reference_time_ms is None else reference_time_ms
    if not isinstance(reference, int) or isinstance(reference, bool) or reference < 1:
        raise ValueError("a positive preregistered pair reference time is required")
    with registered_cases():
        cases = [components.case_binding(snapshot.load_case(case), reference) for case in CASE_IDS]
    plan.update(
        schema_version=1,
        kind="PAIRED_PRODUCTION_RU_TOOL_ROUTE_WORK_CODEC",
        scope="ACTUAL_PRODUCT_SUBGRAPHS_NOT_MAIN_WORKFLOW_SUCCESS",
        arms=list(ARMS),
        cases=cases,
        preregistered_reference_time_ms=reference,
        trials_per_case_arm=1,
        planned_case_arms=6,
        execution_order="SEQUENTIAL_CASE_THEN_ARM",
        work_contract=_work_contract(),
        provider_reads=0,
        stop_before=["Retrieval", "WorkAnalysis", "Planning", "Approval", "Execution"],
        component_orchestration="PRODUCTION_CALLBACKS_STOP_BEFORE_DURABLE_CONFIRMATION_COMMAND",
        semantic_grader="UNREVIEWED_RAW_PRESERVED_NO_AUTOMATIC_PASS",
        attribution=(
            "Work structural binding, Source/Output semantics, and connected completion are "
            "separate. Identical exact Work outputs cannot make downstream model variance "
            "a codec semantic gain. No omitted prohibition or business text is restored."
        ),
    )
    for path in (
        Path(__file__),
        Path(components.__file__),
        Path(codec.__file__),
        shared.PROJECT_ROOT / "scripts/production_goal_output_candidate.py",
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
        raise ValueError("codec comparison preregistered input/code/runtime binding changed")


@contextmanager
def candidate_scope(
    candidate: str | None,
    observation: shared.TrialObservation,
    events: list[dict[str, Any]],
) -> Iterator[Callable[[Any], Any]]:
    """Preserve the actual provider, observer, Product router and repair policy."""
    if candidate is None:
        yield observation.decorate
    elif candidate == CANDIDATE:
        with codec.work_span_codec_candidate(observations=events):
            yield observation.decorate
    else:
        raise ValueError("only the standalone Work codec candidate is registered")


def run_arm(plan: dict[str, Any], binding: dict[str, Any], arm: str, output: Path) -> None:
    with (
        registered_cases(),
        patch.object(components, "ARMS", ARMS),
        patch.object(components, "validate_plan", validate_plan),
        patch.object(shared, "candidate_scope", candidate_scope),
    ):
        _component_run_arm(plan, binding, arm, output)
    path = output / "raw.json"
    if path.is_file():
        report = json.loads(path.read_text(encoding="utf-8"))
        report["work_contract"] = plan["work_contract"]
        report["attribution"] = plan["attribution"]
        report["semantic_verdict"] = "UNREVIEWED"
        shared.write_json(path, report)


def execute_plan(plan_path: Path, output: Path) -> int:
    # Preserve the existing parent timeout, new output, exclusive claim and no-rerun rules.
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
