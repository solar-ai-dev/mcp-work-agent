"""Compare the existing initial Review decomposition on frozen corrected plans."""

from __future__ import annotations

import argparse
import hashlib
import json
import tempfile
import time
from pathlib import Path
from typing import Any, cast

from scripts.evaluate_planning_review_cycle import (
    _build_case_state,
    _graph_pair,
    _scenario_inputs,
    _stage,
)
from scripts.evaluate_retrieval_connected_segment import _RecordingInferencePort
from scripts.evaluate_review_decomposition_node import _runtime

from google_work_agent.application.prompt_runtime.prompt_registry import (
    default_prompt_manifest_path,
)
from google_work_agent.application.use_cases.run.account_provider_dispatch import (
    provider_dispatch_budget_scope,
    provider_dispatch_execution_scope,
)

LABELS = ("WRONG_DATE_023", "FORBIDDEN_ATTENDEE_023")


def evaluate(
    *,
    connected_path: Path,
    counterexamples_path: Path,
    checkpoint_root: Path,
    cycle_path: Path,
    output_path: Path,
) -> None:
    connected = json.loads(connected_path.read_text(encoding="utf-8"))
    counterexamples = json.loads(counterexamples_path.read_text(encoding="utf-8"))
    cycle_bytes = cycle_path.read_bytes()
    cycle = json.loads(cycle_bytes)
    prior = {item["label"]: item for item in cycle["cases"]}
    rows = {
        label: (source_case, candidate)
        for label, source_case, candidate in _scenario_inputs(connected, counterexamples)
    }
    runtime = _runtime(
        Path(tempfile.mkdtemp(prefix="gwa-review-split-")),
        default_prompt_manifest_path(),
    )
    recorder = _RecordingInferencePort(runtime, [], capture_structured_output=True)
    dispatch_count = 0
    before_dispatch = runtime.before_provider_dispatch

    def count_dispatch() -> None:
        nonlocal dispatch_count
        before_dispatch()
        dispatch_count += 1

    runtime.before_provider_dispatch = count_dispatch
    result: dict[str, Any] = {
        "binding": {
            "source_cycle_sha256": hashlib.sha256(cycle_bytes).hexdigest(),
            "candidate": "INITIAL_REVIEW_ON_CORRECTED_PLAN",
            "labels": LABELS,
            "temperature": 0.0,
            "seed": 1729,
            "max_review_subgraph_invocations": 2,
            "provider_read_enabled": False,
            "provider_write_enabled": False,
        },
        "cases": [],
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    for label in LABELS:
        source_case, candidate = rows[label]
        state, evidence_store, profile = _build_case_state(
            label=label,
            source_case=source_case,
            candidate=candidate,
            checkpoint_root=checkpoint_root,
        )
        revised = prior[label]["plan_after"]
        if not isinstance(revised, dict):
            raise ValueError(f"{label} has no saved corrected plan")
        state["planning_result"] = revised
        calendar_id = revised["actions"][0]["arguments"].get("calendar_id")
        review_graph, _, review_owner = _graph_pair(
            recorder=recorder,
            evidence_store=evidence_store,
            profile=profile,
            label=f"{label}-split",
            calendar_id=calendar_id if isinstance(calendar_id, str) else None,
        )
        from google_work_agent.adapters.langgraph.subgraphs.review.projections import (
            inspect_goal_and_evidence_projection,
        )

        projected = inspect_goal_and_evidence_projection.project_inspect_goal_and_evidence_input(
            review_owner._project_runtime_inputs(cast(Any, state))
        )
        record: dict[str, Any] = {
            "label": label,
            "review_goal_input_sha256": hashlib.sha256(
                json.dumps(projected, ensure_ascii=False, sort_keys=True).encode("utf-8")
            ).hexdigest(),
        }
        started = time.perf_counter()
        with (
            provider_dispatch_execution_scope(
                run_id=state["run_id"],
                now_ms=lambda started=started, base=candidate["started_at_ms"]: (
                    base + int((time.perf_counter() - started) * 1_000)
                ),
            ),
            provider_dispatch_budget_scope(cast(Any, state["retry_budget"])),
        ):
            try:
                _, stage = _stage(
                    graph=review_graph,
                    state=state,
                    recorder=recorder,
                    dispatches=lambda: dispatch_count,
                    name="review_initial_on_corrected_plan",
                )
                record["stage"] = stage
            except Exception as error:
                record["error"] = {"type": type(error).__name__, "message": str(error)}
        result["cases"].append(record)
        output_path.write_text(
            json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        print(label, record.get("error", "COMPLETED"), flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--connected", type=Path, required=True)
    parser.add_argument("--counterexamples", type=Path, required=True)
    parser.add_argument("--checkpoint-root", type=Path, required=True)
    parser.add_argument("--cycle", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    evaluate(
        connected_path=args.connected,
        counterexamples_path=args.counterexamples,
        checkpoint_root=args.checkpoint_root,
        cycle_path=args.cycle,
        output_path=args.output,
    )


if __name__ == "__main__":
    main()
