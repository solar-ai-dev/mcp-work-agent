"""089: one actual upstream/Main trial with an inactive Planning-only overlay.

The existing snapshot runner owns admission, scheduling, budgets, isolation and
terminalization. No historical checkpoint or semantic answer is injected.
"""

from __future__ import annotations

import argparse
import json
import multiprocessing
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from copy import deepcopy
from pathlib import Path
from typing import Any
from unittest.mock import patch

from scripts import evaluate_production_snapshot_workflow as main_trial
from scripts.evaluate_effect_prohibition_sampler import write_json
from scripts.evaluate_output_format_ablation import inspect_diagnostic_model
from scripts.production_answer_choice_candidate import (
    EVALUATION_SLOT,
    INPUT_VERSION,
    OUTPUT_VERSION,
    AnswerChoicePlanningSubgraph,
    decorate_answer_choice_provider,
)
from scripts.ru_observation import object_hash

from google_work_agent.adapters.langgraph.main import workflow
from google_work_agent.application.prompt_runtime.prompt_registry import (
    DEVELOPMENT_SMOKE,
    EVALUATION,
)

ROOT = main_trial.PROJECT_ROOT
RESULTS = main_trial.RESULTS_ROOT
CRITERIA = "evaluation/experiments/089-answer-choice-main-criteria.md"
CANDIDATE = "answer-choice-v088-main-v089"
SUPPORT_FILES = (
    "scripts/evaluate_answer_choice_main.py",
    "tests/evaluation/test_answer_choice_main.py",
    "scripts/production_answer_choice_candidate.py",
    "scripts/production_goal_output_candidate.py",
    "scripts/answer_fact_selection_candidate.py",
    "scripts/answer_rendering_choice_candidate.py",
    "scripts/evaluate_answer_rendering_choice.py",
    "scripts/evaluate_answer_mode_first.py",
    "scripts/evaluate_output_format_ablation.py",
    "scripts/evaluate_effect_prohibition_sampler.py",
    CRITERIA,
)


def make_plan(model: dict[str, Any], *, trial_id: str | None = None) -> dict[str, Any]:
    """Read-only plan assembly; model inspection is supplied separately."""
    if model.get("model_id") != main_trial.MODEL_ID or not model.get("model_digest"):
        raise ValueError("the actual installed Product 9B model binding is required")
    version = model.get("ollama_version_response")
    if (
        not isinstance(version, dict)
        or version.get("version") != "0.34.0"
        or model.get("ollama_version_sha256") != object_hash(version)
    ):
        raise ValueError("hash-bound Ollama 0.34.0 runtime is required")
    production = main_trial.build_plan(model["model_digest"], trial_id=trial_id)
    return {
        "schema_version": 1,
        "kind": "ACTUAL_MAIN_UPSTREAM_WITH_EVALUATION_PLANNING",
        "candidate": CANDIDATE,
        "production_plan": production,
        "model": deepcopy(model),
        "dependency_sha256": {
            relative: main_trial.file_hash(ROOT / relative) for relative in SUPPORT_FILES
        },
        "overlay": {
            "constructor": "main.workflow.PlanningSubgraph",
            "execution_scope": EVALUATION,
            "prompt_id": EVALUATION_SLOT,
            "input_schema_version": INPUT_VERSION,
            "output_schema_version": OUTPUT_VERSION,
            "upstream": "UNCHANGED_CURRENT_PRODUCT",
            "checkpoint_input_reuse": False,
        },
        "policy": {
            "case_id": main_trial.CASE_ID,
            "trials": 1,
            "concurrency": 1,
            "rerun_to_reach_candidate": 0,
            "actual_wire_cap": main_trial.CALL_CAP,
            "wall_seconds": main_trial.WALL_SECONDS,
            "repair": "EXISTING_PRODUCT_BOUNDED_POLICY_WITHIN_TOTAL_CAP",
            "live_provider_read_write_send": 0,
            "approval_resumes": 0,
            "historical_score_reuse": False,
        },
    }


def validate_plan(plan: Mapping[str, Any], *, model: dict[str, Any] | None = None) -> None:
    production = plan["production_plan"]
    main_trial.validate_plan(production)
    expected = make_plan(plan["model"] if model is None else model, trial_id=production["trial_id"])
    if dict(plan) != expected:
        raise ValueError("089 registered Product/candidate/model/runtime binding drift")


@contextmanager
def planning_candidate_scope(
    original_candidate: str | None,
    observation: Any,
    events: list[dict[str, object]],
) -> Iterator[Callable[[Any], Any]]:
    """Replace only the construction seam before the existing Main is built."""
    if original_candidate is not None:
        raise ValueError("089 must not stack an RU or other Main candidate")

    def construct(**kwargs: Any) -> AnswerChoicePlanningSubgraph:
        if kwargs.get("prompt_execution_scope") != DEVELOPMENT_SMOKE:
            raise ValueError("089 expects the isolated development composition only")
        events.append(
            {
                "operation": "EVALUATION_PLANNING_CONSTRUCTION",
                "candidate": CANDIDATE,
                "product_scope": DEVELOPMENT_SMOKE,
                "planning_scope": EVALUATION,
            }
        )
        return AnswerChoicePlanningSubgraph(
            **{**kwargs, "prompt_execution_scope": EVALUATION}, observations=events
        )

    with patch.object(workflow, "PlanningSubgraph", construct):
        yield lambda leaf: observation.decorate(decorate_answer_choice_provider(leaf))


def run_trial(plan: dict[str, Any], output: Path) -> None:
    """Child process: unchanged Main runner and real same-Run EvidenceStore."""
    validate_plan(plan)
    main_trial.write_json(
        output / "active_evaluation_overlay.json",
        {
            "registered_plan_sha256": object_hash(plan),
            "candidate": CANDIDATE,
            "overlay": plan["overlay"],
            "production_plan_role": "BASE_RUNTIME_BINDING_NOT_ACTIVE_BASELINE_COMPOSITION",
        },
    )
    try:
        with patch.object(main_trial, "candidate_scope", planning_candidate_scope):
            main_trial.run_trial(deepcopy(plan["production_plan"]), output)
    finally:
        path = output / "raw.json"
        raw: dict[str, Any] = (
            json.loads(path.read_text(encoding="utf-8"))
            if path.exists()
            else {
                "state": "HARNESS_ERROR",
                "semantic_verdict": "UNREVIEWED",
            }
        )
        events = [
            event
            for invocation in raw.get("candidate_events", [])
            for event in invocation.get("events", [])
        ]
        calls_path = output / "calls.json"
        calls = (
            json.loads(calls_path.read_text(encoding="utf-8")).get("calls", [])
            if calls_path.exists()
            else []
        )
        raw.update(
            evaluation_candidate=CANDIDATE,
            registered_plan_sha256=object_hash(plan),
            production_plan_role="BASE_RUNTIME_BINDING_NOT_ACTIVE_BASELINE_COMPOSITION",
            candidate_choice_attempts=sum(e.get("operation") == "CHOICE_DISPATCH" for e in events),
            candidate_wire_dispatches=sum(
                call.get("wire_request_count", 0)
                for call in calls
                if call.get("prompt_id") == EVALUATION_SLOT
            ),
            candidate_delegations=sum(e.get("operation") == "PRODUCT_DELEGATE" for e in events),
            candidate_not_reached_is_not_pass=True,
        )
        main_trial.write_json(path, raw)


def _directory(path: Path) -> Path:
    resolved = path.resolve()
    if resolved == RESULTS.resolve() or not resolved.is_relative_to(RESULTS.resolve()):
        raise ValueError("a dedicated local evaluation/results directory is required")
    return resolved


def execute_plan(plan_path: Path, plan_sha256: str) -> int:
    output = _directory(plan_path.parent)
    if (
        plan_path.resolve() != output / "plan.json"
        or main_trial.file_hash(plan_path) != plan_sha256
    ):
        raise ValueError("exact registered plan.json and file hash required")
    if {p.name for p in output.iterdir()} != {"plan.json"}:
        raise FileExistsError("trial output already contains an attempt")
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    validate_plan(plan, model=inspect_diagnostic_model("presence_zero"))
    claims = RESULTS / ".answer-choice-main-trials"
    claims.mkdir(parents=True, exist_ok=True)
    write_json(
        claims / f"{plan['production_plan']['trial_id']}.json",
        {
            "plan_sha256": plan_sha256,
            "output": str(output),
        },
        exclusive=True,
    )
    write_json(output / "attempt.json", {"plan_sha256": plan_sha256}, exclusive=True)
    process = multiprocessing.get_context("spawn").Process(target=run_trial, args=(plan, output))
    process.start()
    process.join(main_trial.WALL_SECONDS)
    timed_out = process.is_alive()
    if timed_out:
        process.terminate()
        process.join(10)
    path = output / "raw.json"
    raw = (
        json.loads(path.read_text(encoding="utf-8"))
        if path.exists()
        else {
            "state": "HARNESS_ERROR",
            "exit_code": process.exitcode,
        }
    )
    if timed_out:
        raw.update(
            state_before_external_timeout=raw.get("state"),
            state="EXPERIMENT_BOUND_REACHED",
            bound_reason="EXTERNAL_WALL_TIMEOUT",
        )
    raw.update(
        evaluation_candidate=CANDIDATE,
        registered_plan_sha256=object_hash(plan),
        production_plan_role="BASE_RUNTIME_BINDING_NOT_ACTIVE_BASELINE_COMPOSITION",
        candidate_not_reached_is_not_pass=True,
        semantic_verdict="UNREVIEWED",
    )
    unchanged = False
    ending: dict[str, Any] = {}
    try:
        current_model = inspect_diagnostic_model("presence_zero")
        ending["model"] = current_model
        validate_plan(plan, model=current_model)
        unchanged = True
    except Exception as error:
        ending["failure"] = {"type": type(error).__name__, "message": str(error)}
        raw.update(state_before_binding_failure=raw.get("state"), state="BINDING_DRIFT")
    ending["unchanged"] = unchanged
    main_trial.write_json(output / "end_binding.json", ending)
    main_trial.write_json(path, raw)
    return 0 if unchanged and not timed_out and process.exitcode == 0 else 2


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--prepare", type=Path)
    mode.add_argument("--execute-plan", type=Path)
    parser.add_argument("--plan-sha256")
    args = parser.parse_args()
    if args.prepare:
        if args.plan_sha256:
            parser.error("--plan-sha256 belongs to --execute-plan")
        output = _directory(args.prepare)
        if output.exists():
            raise FileExistsError("a new trial directory is required")
        plan = make_plan(inspect_diagnostic_model("presence_zero"))
        output.mkdir(parents=True, exist_ok=False)
        write_json(output / "plan.json", plan, exclusive=True)
        print(
            json.dumps(
                {
                    "plan": str(output / "plan.json"),
                    "plan_sha256": main_trial.file_hash(output / "plan.json"),
                }
            )
        )
    else:
        if not args.plan_sha256:
            parser.error("--plan-sha256 is required")
        raise SystemExit(execute_plan(args.execute_plan, args.plan_sha256))


if __name__ == "__main__":
    main()
